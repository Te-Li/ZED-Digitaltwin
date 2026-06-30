#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集成新版工作流的网格更新与 2D 热力图生成 Pipeline
"""

import json
import sys
from pathlib import Path
import requests

# 引入 entity_to_heatmap.py 同级的配置和核心方法
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from config_paths import resolve_ground_top_source, DIR_2D_OUTPUT
from entity_to_heatmap import export_2d_from_ground_top

# 配置 API 路由
GET_LAYOUT_URL = "http://127.0.0.1:8000/api/simulation/layout"
DEFAULT_POST_URL = "http://127.0.0.1:8000/api/simulation/layout/non-public"


def load_shop_elements_from_json(json_path: Path) -> list:
    """读取并解析 shop elements 的 JSON 文件 (返回规则列表)"""
    ranges = []
    if not json_path.exists():
        print(f"警告: 找不到 JSON 文件 {json_path}，将无法更新网格类型和吸引力。")
        return ranges

    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            print("警告: JSON 文件格式不是列表。")
            return ranges
            
        for row in data:
            range_str = row.get('id_range', '').strip('[]"')
            if ',' in range_str:
                try:
                    min_id, max_id = map(int, range_str.split(','))
                    type_name = row.get('英文', '').strip()
                    attraction = row.get('attraction')
                    ranges.append((min_id, max_id, type_name, attraction))
                except ValueError:
                    continue
    except Exception as e:
        print(f"读取 JSON 规则文件失败: {e}")
        
    return ranges


def get_element_info_by_id(element_id, element_ranges):
    """根据 id 匹配对应的 英文 type 和 attraction"""
    if element_id is None:
        return None, None
    for min_id, max_id, type_name, attraction in element_ranges:
        if min_id <= element_id <= max_id:
            return type_name, attraction
    return None, None


def run_pipeline(observations_path: Path, json_rules_path: Path, base_url: str):
    """
    完整的 Pipeline：本地规则匹配 -> 线上布局更新 -> 本地 2D 热力图快照生成
    """
    observations_path = Path(observations_path).resolve()
    json_rules_path = Path(json_rules_path).resolve()

    # 1. 加载映射规则
    element_ranges = load_shop_elements_from_json(json_rules_path)

    # 2. 读取观测数据
    if not observations_path.exists():
        print(f"错误: 找不到观测数据文件 {observations_path}")
        return
    
    observations = json.loads(observations_path.read_text(encoding="utf-8"))
        
    # 3. 从 API 下载当前网格布局数据
    print(f"\n[Step 1] 正在从 API 下载网格布局数据: {GET_LAYOUT_URL}")
    try:
        resp_get = requests.get(GET_LAYOUT_URL, timeout=10)
        if not resp_get.ok:
            print(f"错误: 无法获取网格布局。状态码: {resp_get.status_code}")
            return
        layout_data = resp_get.json()
    except Exception as e:
        print(f"API 请求失败(GET): {e}")
        return

    cells_dict = {(cell['x'], cell['y']): cell for cell in layout_data.get('cells', [])}
    
    # 4. 遍历并更新位置信息
    updated_count = 0
    for obs in observations:
        x = obs.get('col')
        y = obs.get('row')
        element_id = obs.get('id')
        
        if x is None or y is None:
            continue
            
        matched_type, matched_attraction = get_element_info_by_id(element_id, element_ranges)
        
        if (x, y) in cells_dict:
            target_cell = cells_dict[(x, y)]
            if matched_type:
                target_cell['type'] = matched_type
            if matched_attraction is not None:
                target_cell['base_attraction'] = matched_attraction
            updated_count += 1

    print(f"本地处理完成：更新了 {updated_count} 个网格的类型与基础吸引力。")

    # 5. 上传更新后的布局到远端 API
    print(f"\n[Step 2] 正在向 API 上传修改后的网格布局: {base_url}")
    try:
        resp_post = requests.post(base_url, json=layout_data, timeout=15)
        print(f"共有 {len(layout_data['cells'])} 个网格")
        print("Layout 状态码:", resp_post.status_code)
    except Exception as e:
        print(f"API 请求失败(POST): {e}")
        return

    # 6. 新功能：对接 entity_to_heatmap 的 2D 离线 Bundle 导出
    print(f"\n[Step 3] 正在根据新版流程生成 2D 热力图本地缓存...")
    try:
        # 使用新脚本导出的核心业务函数
        data_2d, json_path, html_path = export_2d_from_ground_top(
            source_obs=observations_path,
            out_2d_json=DIR_2D_OUTPUT / f"{observations_path.stem}.heatmap2d.json",
            entity_pack=json_rules_path  # 使用规则 JSON 进行实体过滤或留白
        )
        print("=" * 52)
        print(f"[2D Pipeline] JSON 输出 : {json_path}")
        print(f"[2D Pipeline] HTML 快照 : {html_path}")
        print(f"[2D Pipeline] 观测点数量: {data_2d.get('observation_count', '?')}")
        print("=" * 52)
    except Exception as exc:
        print(f"2D 本地快照生成失败: {exc}")


if __name__ == "__main__":
    # 自动解析为全系统统一的默认观测路径 (通常为 outputs/ground_top_observations_live.json)
    obs_file = resolve_ground_top_source()
    json_rules_file = HERE / "shop_elements.json" 
    
    run_pipeline(obs_file, json_rules_file, DEFAULT_POST_URL)