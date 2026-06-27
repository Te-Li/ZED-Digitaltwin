import json
import os
import csv
import requests

def load_shop_elements(csv_path):
    """
    读取并解析 shop elements.csv 文件
    返回一个列表，每个元素包含：(min_id, max_id, type_name)
    """
    ranges = []
    if not os.path.exists(csv_path):
        print(f"警告: 找不到 CSV 文件 {csv_path}，将无法更新网格类型(type)。")
        return ranges

    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            range_str = row.get('id_range', '').strip('[]"')
            if ',' in range_str:
                try:
                    min_id, max_id = map(int, range_str.split(','))
                    type_name = row.get('英文', '').strip()
                    ranges.append((min_id, max_id, type_name))
                except ValueError:
                    continue
    return ranges

def get_type_by_id(element_id, element_ranges):
    """
    根据 id 匹配对应的英文 type
    """
    if element_id is None:
        return None
    for min_id, max_id, type_name in element_ranges:
        if min_id <= element_id <= max_id:
            return type_name
    return None

def update_urban_layout_via_api(observations_path, csv_path, base_url):
    # 1. 读取 CSV 中的 ID 映射规则
    element_ranges = load_shop_elements(csv_path)

    # 2. 本地读取观测数据
    if not os.path.exists(observations_path):
        print(f"错误: 找不到文件 {observations_path}")
        return
    
    with open(observations_path, 'r', encoding='utf-8') as f:
        observations = json.load(f)
        
    # 3. 通过 API 下载当前网格布局数据 (GET 请求)
    get_layout_url = f"http://127.0.0.1:8000/api/simulation/layout"
    print(f"正在从 API 下载网格布局数据: {get_layout_url}")
    try:
        resp_get = requests.get(get_layout_url)
        if not resp_get.ok:
            print(f"错误: 无法获取网格布局。状态码: {resp_get.status_code}, 原因: {resp_get.text}")
            return
        layout_data = resp_get.json()
    except Exception as e:
        print(f"API 请求失败(GET): {e}")
        return

    # 核心简化：因为同一坐标没有多个高度，直接以 (x, y) 对应单个 cell 字典
    cells_dict = {(cell['x'], cell['y']): cell for cell in layout_data.get('cells', [])}
    
    # 4. 遍历观测数据并更新对应位置的高度 (height) 与类型 (type)
    updated_count = 0
    
    for obs in observations:
        x = obs.get('col')
        y = obs.get('row')
        level = obs.get('level')
        element_id = obs.get('id')
        
        if x is None or y is None or level is None:
            continue
            
        matched_type = get_type_by_id(element_id, element_ranges)
        
        # 仅匹配横纵坐标 (x, y)
        if (x, y) in cells_dict:
            target_cell = cells_dict[(x, y)]
            
            # 更新高度为当前观测的 level（高度不减一）
            target_cell['height'] = level
            
            # 更新类型
            if matched_type:
                target_cell['type'] = matched_type
                
            updated_count += 1
        else:
            print(f"提示: 网格布局中未找到坐标 (x:{x}, y:{y}) 的网格，已略过。")

    print(f"本地处理完成：成功更新了 {updated_count} 个网格的高度与类型。")

    # 5. 通过 API 上传更新后的非公共网格布局 (POST 请求)
    post_layout_url = f"{base_url}"
    print(f"正在向 API 上传修改后的非公共网格布局: {post_layout_url}")
    try:
        resp_post = requests.post(post_layout_url, json=layout_data)
        print(f"共有 {len(layout_data['cells'])} 个网格")
        print("Layout 状态码:", resp_post.status_code)
        if resp_post.ok:
            print("Layout 响应:", resp_post.json())
        else:
            print("Layout 失败响应:", resp_post.text)
    except Exception as e:
        print(f"API 请求失败(POST): {e}")

# --- 运行示例 ---
if __name__ == "__main__":
    obs_file = "outputs/desktop_top_observations_live.json"
    csv_file = "shop elements.csv"
    
    # 定义您的目标上传 Base URL
    api_base_url = "http://127.0.0.1:8000/api/simulation/layout/non-public"
    
    update_urban_layout_via_api(obs_file, csv_file, api_base_url)