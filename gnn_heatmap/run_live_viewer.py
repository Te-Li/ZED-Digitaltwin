#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实时二维热力服务（监听 outputs/ground_top_observations_live.json）。"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "affordancenet"))

from config_paths import (  # noqa: E402
    DEFAULT_2D_JSON,
    DEFAULT_3D_SOURCE,
    LIVE_API_PATH,
    LIVE_PORT,
    ROOT,
    resolve_ground_top_source,
)
from services.ground_top_2d import (  # noqa: E402
    export_heatmap_2d_html,
    load_ground_top_observations,
    project_ground_top_observations_to_2d,
)
from services.heatmap_2d import Heatmap2DOptions  # noqa: E402

DEFAULT_OPTIONS = Heatmap2DOptions()


class LiveState:
    def __init__(self, source_obs: Path, out_2d_json: Path, entity_pack: Path | None):
        self.source_obs = source_obs.resolve()
        self.out_2d_json = out_2d_json.resolve()
        self.entity_pack_path = entity_pack.resolve() if entity_pack else None
        self.lock = threading.Lock()
        self.last_mtime = 0.0
        self.last_payload: dict | None = None

    def refresh(self, *, write_disk: bool = True) -> dict:
        with self.lock:
            if not self.source_obs.exists():
                raise FileNotFoundError(f"2D 观测输入不存在: {self.source_obs}")
            mtime = self.source_obs.stat().st_mtime
            if self.last_payload and mtime == self.last_mtime:
                return self.last_payload

            observations = load_ground_top_observations(self.source_obs)
            entity_pack = None
            if self.entity_pack_path and self.entity_pack_path.is_file():
                entity_pack = json.loads(self.entity_pack_path.read_text(encoding="utf-8"))

            payload = project_ground_top_observations_to_2d(
                observations,
                options=DEFAULT_OPTIONS,
                entity_pack=entity_pack,
                source_file=self.source_obs.name,
            )
            payload["source_ground_top"] = str(self.source_obs)
            payload["source_ground_top_mtime"] = mtime

            if write_disk:
                self.out_2d_json.parent.mkdir(parents=True, exist_ok=True)
                self.out_2d_json.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8",
                )
                export_heatmap_2d_html(payload, self.out_2d_json.with_suffix(".html"))

            self.last_mtime = mtime
            self.last_payload = payload
            return payload

    def refresh_if_changed(self) -> None:
        try:
            if self.source_obs.exists() and self.source_obs.stat().st_mtime != self.last_mtime:
                self.refresh(write_disk=True)
        except Exception as exc:
            print(f"[watch] {exc}")


class LiveHandler(BaseHTTPRequestHandler):
    state: LiveState

    def log_message(self, fmt, *args) -> None:
        if args and "/api/" in str(args[0]):
            return
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == LIVE_API_PATH:
            try:
                payload = self.state.refresh(write_disk=False)
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                self.send_response(503)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            return
        rel = parsed.path.lstrip("/") or "heatmap_2d_live.html"
        fp = (ROOT / rel).resolve()
        if not str(fp).startswith(str(ROOT.resolve())) or not fp.is_file():
            self.send_error(404)
            return
        data = fp.read_bytes()
        ctype = "application/json" if fp.suffix == ".json" else "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def run_live_server(
    source_obs: Path,
    out_2d: Path,
    port: int = LIVE_PORT,
    open_browser: bool = True,
    entity_pack: Path | None = None,
) -> None:
    state = LiveState(source_obs, out_2d, entity_pack)
    try:
        state.refresh(write_disk=True)
    except FileNotFoundError as exc:
        print(f"警告: {exc}")

    def _watch() -> None:
        while True:
            state.refresh_if_changed()
            time.sleep(1.0)

    threading.Thread(target=_watch, daemon=True).start()
    LiveHandler.state = state
    url = f"http://127.0.0.1:{port}/heatmap_2d_live.html"
    server = ThreadingHTTPServer(("127.0.0.1", port), LiveHandler)
    server.allow_reuse_address = True
    print("=" * 56)
    print(f"实时二维热力: {url}")
    print(f"  2D 观测输入: {source_obs}")
    if entity_pack and entity_pack.is_file():
        print(f"  实体留白  : {entity_pack}")
    print(f"  2D 输出   : {out_2d}")
    print("=" * 56)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=str(resolve_ground_top_source()))
    parser.add_argument("--out-2d", default=str(DEFAULT_2D_JSON))
    parser.add_argument("--entity-pack", default=str(DEFAULT_3D_SOURCE))
    parser.add_argument("--port", type=int, default=LIVE_PORT)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    entity = Path(args.entity_pack) if args.entity_pack else None
    if entity and not entity.is_file():
        entity = None

    run_live_server(
        Path(args.source),
        Path(args.out_2d),
        args.port,
        not args.no_open,
        entity,
    )


if __name__ == "__main__":
    main()
