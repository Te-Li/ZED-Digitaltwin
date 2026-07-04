#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Live server for the masked 2D heatmap and projector pages."""

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
    DEFAULT_2D_HEATMAP_JSON,
    DEFAULT_3D_HEATMAP_JSON,
    DEFAULT_GROUND_TOP_MASK_SOURCE,
    DEFAULT_PROJECTION_CALIBRATION,
    LIVE_CALIBRATION_API_PATH,
    LIVE_API_PATH,
    LIVE_PORT,
    ROOT,
)
from services.ground_top_2d import (  # noqa: E402
    apply_ground_top_mask_to_2d,
    load_ground_top_observations,
)
from services.heatmap_2d import (  # noqa: E402
    Heatmap2DOptions,
    export_heatmap_2d_html,
    project_heatmap_3d_to_2d,
)

DEFAULT_OPTIONS = Heatmap2DOptions()


class MaskedLiveState:
    def __init__(self, heatmap_3d: Path, ground_top_mask: Path, out_2d_json: Path):
        self.heatmap_3d = heatmap_3d.resolve()
        self.ground_top_mask = ground_top_mask.resolve()
        self.out_2d_json = out_2d_json.resolve()
        self.lock = threading.Lock()
        self.last_mtime: tuple[float, float] = (0.0, 0.0)
        self.last_payload: dict | None = None

    def refresh(self, *, write_disk: bool = True) -> dict:
        with self.lock:
            if not self.heatmap_3d.exists():
                raise FileNotFoundError(f"3D heatmap input not found: {self.heatmap_3d}")
            if not self.ground_top_mask.exists():
                raise FileNotFoundError(f"ground-top mask input not found: {self.ground_top_mask}")

            mtimes = (
                self.heatmap_3d.stat().st_mtime,
                self.ground_top_mask.stat().st_mtime,
            )
            if self.last_payload and mtimes == self.last_mtime:
                return self.last_payload

            pack = json.loads(self.heatmap_3d.read_text(encoding="utf-8"))
            base_2d = project_heatmap_3d_to_2d(pack, options=DEFAULT_OPTIONS)
            base_2d["source_3d"] = str(self.heatmap_3d)
            base_2d["source_3d_mtime"] = mtimes[0]

            observations = load_ground_top_observations(self.ground_top_mask)
            payload = apply_ground_top_mask_to_2d(
                base_2d,
                observations,
                source_file=self.ground_top_mask.name,
            )
            payload["source_ground_top_mask"] = str(self.ground_top_mask)
            payload["source_ground_top_mask_mtime"] = mtimes[1]

            if write_disk:
                self.out_2d_json.parent.mkdir(parents=True, exist_ok=True)
                self.out_2d_json.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                export_heatmap_2d_html(payload, self.out_2d_json.with_suffix(".html"))

            self.last_mtime = mtimes
            self.last_payload = payload
            return payload

    def refresh_if_changed(self) -> None:
        try:
            if not self.heatmap_3d.exists() or not self.ground_top_mask.exists():
                return
            mtimes = (
                self.heatmap_3d.stat().st_mtime,
                self.ground_top_mask.stat().st_mtime,
            )
            if mtimes != self.last_mtime:
                self.refresh(write_disk=True)
        except Exception as exc:
            print(f"[watch] {exc}")


class LiveHandler(BaseHTTPRequestHandler):
    state: MaskedLiveState

    def log_message(self, fmt, *args) -> None:
        if args and "/api/" in str(args[0]):
            return
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == LIVE_API_PATH:
            try:
                payload = self.state.refresh(write_disk=False)
                self._send_json(200, payload)
            except Exception as exc:
                self._send_json(503, {"error": str(exc)})
            return
        if parsed.path == LIVE_CALIBRATION_API_PATH:
            if DEFAULT_PROJECTION_CALIBRATION.is_file():
                try:
                    payload = json.loads(DEFAULT_PROJECTION_CALIBRATION.read_text(encoding="utf-8"))
                    self._send_json(200, payload)
                except Exception as exc:
                    self._send_json(500, {"error": str(exc)})
            else:
                self._send_json(404, {"error": "projection calibration not found"})
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

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != LIVE_CALIBRATION_API_PATH:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            points = payload.get("dst_points")
            if not isinstance(points, list) or len(points) != 4:
                raise ValueError("dst_points must contain four points")
            for point in points:
                if not isinstance(point, list) or len(point) != 2:
                    raise ValueError("each point must be [x, y]")
                float(point[0])
                float(point[1])
            DEFAULT_PROJECTION_CALIBRATION.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            self._send_json(200, {"ok": True, "path": str(DEFAULT_PROJECTION_CALIBRATION)})
        except Exception as exc:
            self._send_json(400, {"error": str(exc)})


def run_live_server(
    heatmap_3d: Path,
    ground_top_mask: Path,
    out_2d: Path,
    port: int = LIVE_PORT,
    open_browser: bool = True,
) -> None:
    state = MaskedLiveState(heatmap_3d, ground_top_mask, out_2d)
    try:
        state.refresh(write_disk=True)
    except FileNotFoundError as exc:
        print(f"warning: {exc}")

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
    print(f"live masked 2D heatmap: {url}")
    print(f"  calibration : http://127.0.0.1:{port}/projector_calibrate.html")
    print(f"  projection  : http://127.0.0.1:{port}/projector_live.html")
    print(f"  3D heatmap  : {heatmap_3d}")
    print(f"  mask input  : {ground_top_mask}")
    print(f"  2D output   : {out_2d}")
    print("=" * 56)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--heatmap-3d", default=str(DEFAULT_3D_HEATMAP_JSON))
    parser.add_argument("--ground-top-mask", default=str(DEFAULT_GROUND_TOP_MASK_SOURCE))
    parser.add_argument("--out-2d", default=str(DEFAULT_2D_HEATMAP_JSON))
    parser.add_argument("--port", type=int, default=LIVE_PORT)
    parser.add_argument("--no-open", action="store_true")
    args = parser.parse_args()

    run_live_server(
        Path(args.heatmap_3d),
        Path(args.ground_top_mask),
        Path(args.out_2d),
        args.port,
        not args.no_open,
    )


if __name__ == "__main__":
    main()
