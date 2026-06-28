#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZED occupied_space JSON + street elements CSV → 合成骨骼 → 热力预测 → 可视化 JSON → 自动同步至 API

输入:
  - occupied_space(1).json（含 cells 实体格）
  - street elements(1).csv（要素命名表，默认同目录自动配对）

输出: *.heatmap.json（含 entities + heatmap_voxels + SVI，实体为中心点）
同时自动发送至: http://127.0.0.1:8000/api/simulation/public-layout/current/attraction

用法:
  python entity_to_heatmap.py -i occupied_space.json
  python entity_to_heatmap.py -i occupied_space.json --elements-csv "street elements.csv"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "affordancenet"))

from affordancenet.services.occupied_space_pipeline import (  # noqa: E402
    OccupiedSpacePredictOptions,
    export_occupied_space_heatmap,
)
from affordancenet.utils.street_elements_io import find_paired_street_elements_csv  # noqa: E402

DEFAULT_OUT_DIR = HERE / "output"
API_URL = "http://127.0.0.1:8000/api/simulation/public-layout/current/attraction"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="occupied_space JSON + street elements CSV → 合成骨骼热力 → 可视化 JSON 并同步 API",
    )
    parser.add_argument("--input", "-i", required=True, help="occupied_space JSON 路径")
    parser.add_argument(
        "--elements-csv", "-e",
        default=None,
        help="street elements CSV（默认自动配对 street elements.csv）",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="输出 JSON（默认 output/<输入名>.heatmap.json）",
    )
    parser.add_argument("--skeleton-count", type=int, default=100)
    parser.add_argument("--skeleton-seed", type=int, default=42)
    parser.add_argument("--heat-sigma", type=float, default=0.55)
    args = parser.parse_args()

    inp = Path(args.input)
    if not inp.is_absolute():
        inp = (Path.cwd() / inp).resolve()
    if not inp.exists():
        print(f"文件不存在: {inp}")
        sys.exit(1)

    elements_csv = None
    if args.elements_csv:
        elements_csv = Path(args.elements_csv)
        if not elements_csv.is_absolute():
            elements_csv = (Path.cwd() / elements_csv).resolve()
        if not elements_csv.exists():
            print(f"要素表不存在: {elements_csv}")
            sys.exit(1)
    else:
        paired = find_paired_street_elements_csv(inp)
        if paired is None:
            print("未找到 street elements CSV，请使用 --elements-csv 指定")
            sys.exit(1)
        elements_csv = paired

    out = Path(args.output) if args.output else DEFAULT_OUT_DIR / f"{inp.stem}.heatmap.json"
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
        result = export_occupied_space_heatmap(inp, out, options=options)
    except Exception as exc:
        print(f"失败: {exc}")
        sys.exit(1)

    sv = result.social_vitality
    print()
    print("=" * 52)
    print(f"输入          : {inp.name}")
    print(f"要素表        : {elements_csv.name}")
    print(f"输出          : {out}")
    print(f"实体(中心点)  : {len(result.record.scene.entity_voxels)}")
    print(f"热力体素      : {result.intensity_max and sum(1 for s in result.pred_space if s.social_intensity > 1e-6)}")
    print(f"骨骼点        : {result.skeleton_point_count} · 姿态 {result.pose_count}")
    print(f"社交活力 SVI  : {sv.index:.3f}（{sv.level_cn}）")
    print(f"强度范围      : {result.intensity_min:.3f} ~ {result.intensity_max:.3f}")
    print(f"查看          : 用 heatmap_viewer.html 打开 {out.name}")
    print("=" * 52)

    # ---- 新增代码：发送生成的 JSON 到 API ----
    print("\n正在同步热力图数据到 API...")
    try:
        with open(out, "r", encoding="utf-8") as f:
            heatmap_data = json.load(f)
        
        # 使用 PUT 方法向指定的 API_URL 发送数据
        resp = requests.put(API_URL, json=heatmap_data)
        
        print(f"Attraction 状态码: {resp.status_code}")
        if resp.ok:
            try:
                print("Attraction 响应:", resp.json())
            except Exception:
                print("Attraction 响应成功，但返回内容非 JSON 格式:", resp.text)
        else:
            print("Attraction 失败响应:", resp.text)
    except Exception as e:
        print(f"同步至 API 失败: {e}")
    print("=" * 52)


if __name__ == "__main__":
    main()