#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
occupied_space → 3D 热力 (output/) → 2D 热力 (output_2d/) → 可视化网址

用法:
  python entity_to_heatmap.py -i occupied_space.json          # 3D + 2D
  python entity_to_heatmap.py --only-2d                      # 仅 2D（读 output/occupied_space.heatmap.json）
  python entity_to_heatmap.py -i occupied_space.json --serve # 3D + 2D + 打开实时网页
"""

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
    DEFAULT_2D_JSON,
    DEFAULT_3D_SOURCE,
    DEFAULT_GROUND_TOP_SOURCE,
    DIR_2D_OUTPUT,
    DIR_3D_OUTPUT,
    DIR_OBS_INPUT,
    LIVE_PORT,
    resolve_ground_top_source,
)
from affordancenet.services.ground_top_2d import export_ground_top_2d_bundle  # noqa: E402
from affordancenet.services.heatmap_2d import Heatmap2DOptions, export_heatmap_2d_bundle  # noqa: E402
from affordancenet.services.occupied_space_pipeline import (  # noqa: E402
    OccupiedSpacePredictOptions,
    export_occupied_space_heatmap,
)
from affordancenet.utils.street_elements_io import find_paired_street_elements_csv  # noqa: E402

API_URL = "http://127.0.0.1:8000/api/simulation/public-layout/current/attraction"
HEATMAP_2D_OPTIONS = Heatmap2DOptions(cell_m=0.4, nx=10, ny=6)


def _sync_api(out: Path) -> None:
    if os.environ.get("SKIP_API_SYNC"):
        return
    try:
        import requests
    except ImportError:
        return
    print("\n正在同步三维热力到 API …")
    try:
        resp = requests.put(API_URL, json=json.loads(out.read_text(encoding="utf-8")), timeout=30)
        print(f"API 状态码: {resp.status_code}")
    except Exception as exc:
        print(f"API 同步失败: {exc}")


def _stem_from_heatmap(path: Path) -> str:
    if path.stem.endswith(".heatmap"):
        return path.stem[: -len(".heatmap")]
    return path.stem.replace(".heatmap2d", "")


def export_2d_from_ground_top(
    source_obs: Path,
    out_2d_json: Path | None = None,
    *,
    entity_pack: Path | None = None,
) -> tuple[dict, Path, Path]:
    """outputs/ground_top_observations_live.json → 2D 热力。"""
    source_obs = Path(source_obs).resolve()
    if not source_obs.exists():
        raise FileNotFoundError(f"2D 观测输入不存在: {source_obs}")

    stem = source_obs.stem
    out_json = Path(out_2d_json) if out_2d_json else DIR_2D_OUTPUT / f"{stem}.heatmap2d.json"
    if not out_json.is_absolute():
        out_json = (HERE / out_json).resolve()

    mask_src = entity_pack or DEFAULT_3D_SOURCE
    if not Path(mask_src).is_file():
        mask_src = None

    DIR_2D_OUTPUT.mkdir(parents=True, exist_ok=True)
    data, html_path = export_ground_top_2d_bundle(
        source_obs,
        out_json,
        options=HEATMAP_2D_OPTIONS,
        entity_pack_path=Path(mask_src) if mask_src else None,
    )
    return data, out_json, html_path



def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def run_3d(inp: Path, elements_csv: Path, out: Path, options: OccupiedSpacePredictOptions):
    return export_occupied_space_heatmap(inp, out, options=options)


def main() -> None:
    parser = argparse.ArgumentParser(description="3D 热力 → 2D 热力 → 可视化网址")
    parser.add_argument("--input", "-i", default=None, help="occupied_space JSON（3D 流程）")
    parser.add_argument("--elements-csv", "-e", default=None)
    parser.add_argument("--output", "-o", default=None, help="3D 输出（默认 output/<名>.heatmap.json）")
    parser.add_argument("--heatmap-3d", default=None, help="3D 热力（仅用于实体留白 mask）")
    parser.add_argument(
        "--ground-top",
        default=None,
        help="2D 观测 JSON（默认 outputs/ground_top_observations_live.json）",
    )
    parser.add_argument("--output-2d", default=None, help="2D JSON 输出（默认 output_2d/）")
    parser.add_argument(
        "--only-2d",
        action="store_true",
        help="跳过 3D，从 ground_top_observations_live.json 生成 2D",
    )
    parser.add_argument("--from-3d", action="store_true", help="2D 仍从 3D heatmap.json 投影（旧模式）")
    parser.add_argument("--skip-2d", action="store_true")
    parser.add_argument("--serve", action="store_true", help="完成后启动实时可视化网址")
    parser.add_argument("--port", type=int, default=LIVE_PORT)
    parser.add_argument("--skeleton-count", type=int, default=100)
    parser.add_argument("--skeleton-seed", type=int, default=42)
    parser.add_argument("--heat-sigma", type=float, default=0.55)
    args = parser.parse_args()

    source_3d = Path(args.heatmap_3d) if args.heatmap_3d else DEFAULT_3D_SOURCE
    if not source_3d.is_absolute():
        source_3d = (HERE / source_3d).resolve()

    source_obs = Path(args.ground_top) if args.ground_top else resolve_ground_top_source()
    if not source_obs.is_absolute():
        source_obs = (HERE / source_obs).resolve()

    DIR_OBS_INPUT.mkdir(parents=True, exist_ok=True)

    if not args.only_2d:
        if not args.input:
            print("请指定 -i occupied_space.json，或使用 --only-2d")
            sys.exit(1)
        inp = Path(args.input)
        if not inp.is_absolute():
            inp = (Path.cwd() / inp).resolve()
        if not inp.exists():
            print(f"文件不存在: {inp}")
            sys.exit(1)

        elements_csv = Path(args.elements_csv) if args.elements_csv else find_paired_street_elements_csv(inp)
        if elements_csv is None or not Path(elements_csv).exists():
            print("未找到 street elements CSV")
            sys.exit(1)
        elements_csv = Path(elements_csv).resolve()

        out = Path(args.output) if args.output else DIR_3D_OUTPUT / f"{inp.stem}.heatmap.json"
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
            print(f"3D 失败: {exc}")
            sys.exit(1)

        sv = result.social_vitality
        source_3d = out
        print()
        print("=" * 52)
        print(f"[3D] 输入     : {inp.name}")
        print(f"[3D] 输出     : {out}")
        print(f"实体         : {len(result.record.scene.entity_voxels)}")
        print(f"SVI          : {sv.index:.3f}（{sv.level_cn}）")
        print("=" * 52)
        _sync_api(out)

    if args.skip_2d:
        return

    out_2d = Path(args.output_2d) if args.output_2d else None
    try:
        if args.from_3d:
            if not source_3d.exists():
                raise FileNotFoundError(f"3D 输入不存在: {source_3d}")
            stem = _stem_from_heatmap(source_3d)
            out_json = out_2d or DIR_2D_OUTPUT / f"{stem}.heatmap2d.json"
            if not out_json.is_absolute():
                out_json = (HERE / out_json).resolve()
            DIR_2D_OUTPUT.mkdir(parents=True, exist_ok=True)
            data, html_path = export_heatmap_2d_bundle(
                source_3d, out_json, options=HEATMAP_2D_OPTIONS,
            )
            json_path = out_json
        else:
            data, json_path, html_path = export_2d_from_ground_top(
                source_obs, out_2d, entity_pack=source_3d if source_3d.is_file() else None,
            )
    except Exception as exc:
        print(f"2D 失败: {exc}")
        sys.exit(1)

    ir = data["intensity_range"]
    print()
    print("=" * 52)
    if args.from_3d:
        print(f"[2D] 3D 输入   : {source_3d}")
    else:
        print(f"[2D] 观测输入  : {source_obs}")
        print(f"             （格式: ground_top_observations 数组 JSON）")
        if source_3d.is_file():
            print(f"[2D] 实体留白  : {source_3d.name}")
    print(f"[2D] JSON 输出 : {json_path}")
    print(f"[2D] HTML 快照 : {html_path}")
    print(f"[2D] 尺寸      : 4.0m × 2.4m (10×6, 400mm/格)")
    print(f"[2D] 观测点    : {data.get('observation_count', '?')} · 有效格 {data.get('observation_cells', '?')}")
    print(f"[2D] 强度      : {ir['min']:.4f} ~ {ir['max']:.4f}")
    print(f"[2D] 离线查看  : 双击 {html_path.name}")


if __name__ == "__main__":
    main()
