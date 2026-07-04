#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a 3D heatmap, project it to 2D, then apply the ground-top mask."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "affordancenet"))

from config_paths import (  # noqa: E402
    DEFAULT_2D_HEATMAP_JSON,
    DEFAULT_3D_HEATMAP_JSON,
    DEFAULT_GROUND_TOP_MASK_SOURCE,
    DEFAULT_OCCUPIED_SPACE_INPUT,
    DEFAULT_STREET_ELEMENTS_CSV,
    LIVE_PORT,
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
from services.occupied_space_pipeline import (  # noqa: E402
    OccupiedSpacePredictOptions,
    export_occupied_space_heatmap,
)
from utils.street_elements_io import find_paired_street_elements_csv  # noqa: E402

API_URL = "http://127.0.0.1:8000/api/simulation/public-layout/current/attraction"
HEATMAP_2D_OPTIONS = Heatmap2DOptions(cell_m=0.4, nx=10, ny=6)


def _sync_api(out: Path) -> None:
    if os.environ.get("SKIP_API_SYNC"):
        return
    try:
        import requests
    except ImportError:
        return
    try:
        resp = requests.put(API_URL, json=json.loads(out.read_text(encoding="utf-8")), timeout=30)
        print(f"API status: {resp.status_code}")
    except Exception as exc:
        print(f"API sync failed: {exc}")


def export_masked_2d_from_3d(
    heatmap_3d: Path,
    ground_top_mask: Path,
    out_2d_json: Path | None = None,
) -> tuple[dict, Path, Path]:
    heatmap_3d = Path(heatmap_3d).resolve()
    ground_top_mask = Path(ground_top_mask).resolve()
    if not heatmap_3d.exists():
        raise FileNotFoundError(f"3D heatmap input not found: {heatmap_3d}")
    if not ground_top_mask.exists():
        raise FileNotFoundError(f"ground-top mask input not found: {ground_top_mask}")

    out_json = Path(out_2d_json) if out_2d_json else DEFAULT_2D_HEATMAP_JSON
    if not out_json.is_absolute():
        out_json = (HERE / out_json).resolve()

    pack = json.loads(heatmap_3d.read_text(encoding="utf-8"))
    if pack.get("format") != "affordancenet-heatmap-pack":
        raise ValueError(f"unsupported 3D heatmap format: {pack.get('format')}")

    base_2d = project_heatmap_3d_to_2d(pack, options=HEATMAP_2D_OPTIONS)
    base_2d["source_3d"] = str(heatmap_3d)
    base_2d["source_3d_mtime"] = heatmap_3d.stat().st_mtime

    observations = load_ground_top_observations(ground_top_mask)
    data = apply_ground_top_mask_to_2d(
        base_2d,
        observations,
        source_file=ground_top_mask.name,
    )
    data["source_ground_top_mask"] = str(ground_top_mask)
    data["source_ground_top_mask_mtime"] = ground_top_mask.stat().st_mtime

    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    html_path = out_json.with_suffix(".html")
    export_heatmap_2d_html(data, html_path)
    return data, out_json, html_path


def live_url(port: int = LIVE_PORT) -> str:
    return f"http://127.0.0.1:{port}/heatmap_2d_live.html"


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_live_viewer(
    heatmap_3d: Path,
    ground_top_mask: Path,
    out_2d: Path,
    port: int = LIVE_PORT,
) -> str:
    url = live_url(port)

    def _relative(path: Path) -> Path:
        try:
            return path.relative_to(HERE)
        except ValueError:
            return path

    # 当前端口已有服务时，本次程序并不拥有该进程，因此不主动结束它
    if _port_in_use(port):
        print(f"[2D] live server already running: {url}")
        print("[2D] 当前端口服务不是本次启动的，Ctrl+C 无法关闭已有服务。")
        webbrowser.open(url)
        return url

    cmd = [
        sys.executable,
        str(HERE / "run_live_viewer.py"),
        "--heatmap-3d",
        str(_relative(heatmap_3d)),
        "--ground-top-mask",
        str(_relative(ground_top_mask)),
        "--out-2d",
        str(_relative(out_2d)),
        "--port",
        str(port),
    ]

    process: subprocess.Popen | None = None

    try:
        # 不再使用 CREATE_NEW_CONSOLE
        # 让子进程继承当前终端，这样 Ctrl+C 能被正确处理
        process = subprocess.Popen(
            cmd,
            cwd=str(HERE),
        )

        time.sleep(1.2)

        # 子进程启动失败时及时报错
        if process.poll() is not None:
            raise RuntimeError(
                f"live viewer exited unexpectedly, return code: {process.returncode}"
            )

        webbrowser.open(url)
        print(f"[2D] live server: {url}")
        print("[2D] 按 Ctrl+C 可关闭 live viewer。")

        # 保持当前进程等待，Ctrl+C 时进入 except/finally
        process.wait()

    except KeyboardInterrupt:
        print("\n[2D] Ctrl+C received, stopping live viewer...")

    finally:
        if process is not None and process.poll() is None:
            print("[2D] terminating live viewer process...")
            process.terminate()

            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                print("[2D] process did not exit in time, force killing...")
                process.kill()
                process.wait()

        print("[2D] live viewer stopped.")

    return url


def run_3d(inp: Path, elements_csv: Path, out: Path, options: OccupiedSpacePredictOptions):
    return export_occupied_space_heatmap(inp, out, options=options)


def main() -> None:
    parser = argparse.ArgumentParser(description="occupied_space -> 3D heatmap -> masked 2D heatmap")
    parser.add_argument("--input", "-i", default=str(DEFAULT_OCCUPIED_SPACE_INPUT), help="occupied_space JSON input")
    parser.add_argument("--elements-csv", "-e", default=str(DEFAULT_STREET_ELEMENTS_CSV))
    parser.add_argument("--output", "-o", default=str(DEFAULT_3D_HEATMAP_JSON), help="3D heatmap JSON output")
    parser.add_argument("--heatmap-3d", default=None, help="existing 3D heatmap JSON used with --only-2d")
    parser.add_argument(
        "--ground-top-mask",
        default=str(DEFAULT_GROUND_TOP_MASK_SOURCE),
        help="ground_top observations JSON used as an observed-cell mask",
    )
    parser.add_argument("--output-2d", default=str(DEFAULT_2D_HEATMAP_JSON), help="masked 2D JSON output")
    parser.add_argument("--only-2d", action="store_true", help="skip 3D prediction and use an existing 3D heatmap")
    parser.add_argument("--skip-2d", action="store_true")
    parser.add_argument("--serve", action="store_true", help="start the live masked 2D viewer")
    parser.add_argument("--port", type=int, default=LIVE_PORT)
    parser.add_argument("--skeleton-count", type=int, default=100)
    parser.add_argument("--skeleton-seed", type=int, default=42)
    parser.add_argument("--heat-sigma", type=float, default=0.55)
    args = parser.parse_args()

    source_3d = Path(args.heatmap_3d) if args.heatmap_3d else Path(args.output)
    if not source_3d.is_absolute():
        source_3d = (HERE / source_3d).resolve()

    ground_top_mask = Path(args.ground_top_mask)
    if not ground_top_mask.is_absolute():
        ground_top_mask = (HERE / ground_top_mask).resolve()

    if not args.only_2d:
        inp = Path(args.input)
        if not inp.is_absolute():
            inp = (Path.cwd() / inp).resolve()
        if not inp.exists():
            print(f"occupied_space input not found: {inp}")
            sys.exit(1)

        elements_csv = Path(args.elements_csv) if args.elements_csv else find_paired_street_elements_csv(inp)
        if elements_csv is None or not Path(elements_csv).exists():
            print("street elements CSV not found")
            sys.exit(1)
        elements_csv = Path(elements_csv).resolve()

        out = Path(args.output)
        if not out.is_absolute():
            out = (Path.cwd() / out).resolve()
        out.parent.mkdir(parents=True, exist_ok=True)

        options = OccupiedSpacePredictOptions(
            skeleton_count=args.skeleton_count,
            skeleton_seed=args.skeleton_seed,
            heat_sigma=args.heat_sigma,
            elements_csv=elements_csv,
        )
        try:
            result = run_3d(inp, elements_csv, out, options)
        except Exception as exc:
            print(f"3D failed: {exc}")
            sys.exit(1)

        source_3d = out
        print()
        print("=" * 52)
        print(f"[3D] input      : {inp}")
        print(f"[3D] elements   : {elements_csv}")
        print(f"[3D] output     : {out}")
        print(f"[3D] entities   : {len(result.record.scene.entity_voxels)}")
        print(f"[3D] SVI        : {result.social_vitality.index:.3f}")
        print("=" * 52)
        _sync_api(out)

    if args.skip_2d:
        return

    out_2d = Path(args.output_2d) if args.output_2d else None
    
    try:
        data, json_path, html_path = export_masked_2d_from_3d(source_3d, ground_top_mask, out_2d)
    except Exception as exc:
        print(f"2D failed: {exc}")
        sys.exit(1)

    ir = data["intensity_range"]
    print()
    print("=" * 52)
    print(f"[2D] 3D input   : {source_3d}")
    print(f"[2D] mask input : {ground_top_mask}")
    print(f"[2D] JSON output: {json_path}")
    print(f"[2D] HTML output: {html_path}")
    print(f"[2D] size       : 4.0m x 2.4m (10x6, 400mm/cell)")
    print(f"[2D] masked obs : {data.get('ground_top_mask_cell_count', '?')} cells")
    print(f"[2D] intensity  : {ir['min']:.4f} ~ {ir['max']:.4f}")
    if args.serve:
        start_live_viewer(source_3d, ground_top_mask, json_path, args.port)
    else:
        print("[2D] live viewer: python entity_to_heatmap.py --only-2d --serve")
        print(f"                 {live_url(args.port)}")
    print("=" * 52)


if __name__ == "__main__":
    main()
