#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import argparse
from pathlib import Path

SERVER_IP = "127.0.0.1"
SERVER_PORT = 8000

# ✨ 最新配置路径：根据新版 config_paths 映射到根目录的 out 文件夹
CSV_FILE = "street elements.csv"
LIVE_JSON = "outputs/ground_top_observations_live.json"
MODEL_PLANE_JSON = "outputs/model_plane.json"
OCCUPIED_SPACE_JSON = "outputs/occupied_space.json"

# ✨ 最新输出路径规范化
HEATMAP_OUTPUT = "outputs/occupied_space.heatmap.json"
HEATMAP_2D_OUTPUT = "outputs/2d_heatmap.json" 

# 接口配置
MODEL_PLANE_API_URL = f"http://{SERVER_IP}:{SERVER_PORT}/api/static/model-plane"
LAYOUT_API_URL = f"http://{SERVER_IP}:{SERVER_PORT}/api/simulation/public-layout/current"
HEATMAP_API_URL = f"http://{SERVER_IP}:{SERVER_PORT}/api/simulation/public-layout/current/attraction"

# 假设 entity_to_heatmap.py 在下一级目录 gnn_heatmap 中
HEATMAP_SCRIPT = Path("gnn_heatmap") / "entity_to_heatmap.py"


def is_file_ready_and_complete(filepath):
    """
    检查本地输入 file 是否可以 safe 读取（防止读取到写了一半的残缺 JSON）
    """
    path = Path(filepath)
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        with open(path, 'a'):
            pass
        with open(path, 'rb') as f:
            f.seek(-1, 2)
            last_char = f.read(1)
            if last_char not in b']}\n ': 
                return False
            return True
    except IOError:
        return False


def run_pipeline():
    # 确保输出目录 out 存在
    Path("out").mkdir(parents=True, exist_ok=True)
    
    # 导入前两个脚本的处理函数
    try:
        from ground1_model_plane import process_street_elements
        from ground2_gnn_voxels import load_csv_mapping, calculate_occupied_cells, fetch_current_layout, save_and_upload_layout
    except ImportError as e:
        print(f"❌ 导入基础脚本失败，请检查脚本命名及路径。错误: {e}")
        return

    print("🚀 实时空间集成流水线控制脚本已启动...")
    print(f"  - 基础平面模型 POST 接口: {MODEL_PLANE_API_URL}")
    print(f"  - 布局同步接口: {LAYOUT_API_URL}")
    print(f"  - 热力同步接口: {HEATMAP_API_URL}\n")
    
    # 初始化记录上一次处理 LIVE_JSON 的修改时间
    last_processed_mtime = 0.0
    
    while True:
        try:
            # ----------------------------------------------------------------
            # 步骤 1: 解析基础平面模型 (时间戳发生变化且文件完整才处理)
            # ----------------------------------------------------------------
            live_path = Path(LIVE_JSON)
            should_process_pipeline = False
            
            if is_file_ready_and_complete(live_path):
                current_mtime = live_path.stat().st_mtime
                
                # 如果当前修改时间大于上一次记录的时间，说明文件被重新写入了
                if current_mtime > last_processed_mtime:
                    should_process_pipeline = True
                    last_processed_mtime = current_mtime # 更新时间戳记录
            
            if not should_process_pipeline:
                print("⏳ [Pipeline] 本地观察文件无变化，全链路静默跳过...", end="\r")
                time.sleep(0.5)
                continue
            
            # 执行到这里说明有新数据，开启全新的一轮流水线计算
            print("\n--- ⚡ 检测到数据更新，开始全链路同步与计算 ---")
            
            print("[Step 1/3] 🔄 正在解析本地观察文件并自动 POST 基础平面模型...")
            process_street_elements(CSV_FILE, LIVE_JSON, MODEL_PLANE_JSON, api_url=MODEL_PLANE_API_URL)

            # ----------------------------------------------------------------
            # 步骤 2: 从 API 获取当前布局 -> 计算实体体素 -> 同步回服务器
            # ----------------------------------------------------------------
            print("[Step 2/3] 📡 正在从服务器获取当前布局数据...")
            layout_data = fetch_current_layout(LAYOUT_API_URL)
            
            if layout_data is None or not isinstance(layout_data, dict):
                print("  ⏭️ 条件未满足（未选择布局或返回非字典格式），熔断本轮后续计算。")
                time.sleep(0.5)
                continue

            print("  -> 开始计算实体体素空间...")
            id_mapping = load_csv_mapping(CSV_FILE)
            
            occupied_cells = calculate_occupied_cells(MODEL_PLANE_JSON, id_mapping)
            print(f"  -> 网格计算完成，共生成 {len(occupied_cells)} 个单元。")
            
            save_and_upload_layout(layout_data, occupied_cells, OCCUPIED_SPACE_JSON, LAYOUT_API_URL)

            # ----------------------------------------------------------------
            # 步骤 3: 适配最新子脚本的 3D -> 2D 遮罩处理流程
            # ----------------------------------------------------------------
            print("[Step 3/3] 🔥 正在由 occupied_space 计算 3D 热力，并投影叠加 2D 遮罩...")
            if not HEATMAP_SCRIPT.exists():
                print(f"  ❌ 错误: 未找到热力图生成脚本: {HEATMAP_SCRIPT}")
            else:
                script_cwd = HEATMAP_SCRIPT.parent

                # ✨ 核心适配：依据最新的 argparse 定义重构命令数组
                cmd = [
                    "python", HEATMAP_SCRIPT.name,
                    # 1. 传入 occupied_space.json 计算 3D 热力图
                    "--input", str(Path(OCCUPIED_SPACE_JSON).resolve()),
                    "--elements-csv", str(Path(CSV_FILE).resolve()),
                    "--output", str(Path(HEATMAP_OUTPUT).resolve()),
                    
                    # 2. ✨ 参数名更新：原先的 --ground-top 变更为 --ground-top-mask
                    "--ground-top-mask", str(Path(LIVE_JSON).resolve()),
                    
                    # 3. 传入最终生成的 2D 遮罩热力图路径 (子脚本会自动先算3D再生成带遮罩的2D)
                    "--output-2d", str(Path(HEATMAP_2D_OUTPUT).resolve())
                ]
                
                # 执行子进程
                result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=script_cwd)
                
                if result.returncode == 0:
                    print(f"  ✨ 本轮流水线处理全链路成功！3D与2D遮罩热力已生成。")
                else:
                    print(f"  ⚠️ 警告: 步骤 3 热力图遮罩生成失败。")
                    print(f"  错误详情: {result.stderr.strip()}")
                    
        except Exception as e:
            print(f"\n💥 本轮循环运行中发生未知异常: {e}")
            
        # 保持原本的 0.5 秒高频循环频率
        time.sleep(0.5)


if __name__ == "__main__":
    # 解析 --serve 指令
    parser = argparse.ArgumentParser(description="实时空间集成流水线控制中心")
    parser.add_argument("--serve", action="store_true", help="启动 2D 实时热力图可视化 Web 服务器")
    args = parser.parse_args()

    if args.serve:
        try:
            print("\n🌐 [指令激活] 正在后台单独启动 2D 实时可视化 Web 服务器...")
            # ✨ 适配最新版启动逻辑
            init_cmd = [
                "python", "gnn_heatmap/entity_to_heatmap.py", 
                "--only-2d", 
                "--serve"
            ]
            # 后台挂起服务，不阻塞后面的高频 while 循环
            subprocess.Popen(init_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("✨ 2D 服务器已成功挂载服务，正在拉起可视化网页...\n")
        except Exception as e:
            print(f"⚠️ 启动 Web 服务器失败 (可能端口已被占用): {e}")

    # 启动高频流水线
    run_pipeline()