import os
import time
from pathlib import Path

# 配置路径
OBS_FILE = Path("outputs/desktop_top_observations_live.json")
# 1. 对应改动：将 CSV 文件路径改为你的新 JSON 规则文件路径
JSON_RULES_FILE = Path("shop_elements.json") 
API_BASE_URL = "http://127.0.0.1:8000/api/simulation/layout/non-public"

def is_file_ready_and_complete(filepath):
    """
    检查输入文件是否可以安全读取：
    1. 是否存在
    2. 能否独占打开
    3. 文件尾部是否完整
    """
    path = Path(filepath)
    if not path.exists() or path.stat().st_size == 0:
        return False
    try:
        # 尝试以追加模式打开
        with open(path, 'a'):
            pass
        # 尝试读取尾部字符，确保 JSON 闭合
        with open(path, 'rb') as f:
            f.seek(-1, 2)
            last_char = f.read(1)
            if last_char not in b']}\n ': 
                return False
        return True
    except IOError:
        return False

def run_desktop_pipeline():
    # 确保输出目录存在
    OBS_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        from desktop_1_update_json import update_urban_layout_via_api
    except ImportError as e:
        print(f"❌ 导入基础脚本失败，请检查 'desktop_1_update_json.py' 是否在同级目录。错误: {e}")
        return

    print("🚀 桌面城市布局更新流水线已启动...")
    
    # 用于记录上一次成功处理的文件修改时间，防止原地死循环
    last_modified_time = 0.0

    while True:
        # 校验输入观测数据是否正在被写入或不完整
        if not is_file_ready_and_complete(OBS_FILE):
            time.sleep(0.5)
            continue
            
        # 获取当前文件的修改时间
        current_mtime = OBS_FILE.stat().st_mtime
        
        # 如果文件没有被更新（修改时间没变），则跳过本次循环，避免狂刷 API
        if current_mtime <= last_modified_time:
            time.sleep(0.5)
            continue
            
        try:
            print(f"\n--- 侦测到新观测数据，开始更新城市布局网格 ---")
            
            # 2. 对应改动：修正调用的入参名，将 csv_path 改为 json_rules_path
            update_urban_layout_via_api(
                observations_path=str(OBS_FILE),
                json_rules_path=str(JSON_RULES_FILE),
                base_url=API_BASE_URL
            )
            
            # 更新成功后，记录当前的修改时间
            last_modified_time = current_mtime
            
        except Exception as e:
            print(f"💥 本轮更新运行出错: {e}")
            
        # 每 0.5 秒循环检测一次
        time.sleep(0.5)

if __name__ == "__main__":
    run_desktop_pipeline()