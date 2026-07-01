import json
import os
import requests

def load_shop_elements_from_api(api_url):
    """
    通过 API 获取并解析 shop elements 的数据
    返回一个列表，每个元素包含：(min_id, max_id, type_name, attraction)
    """
    ranges = []
    print(f"正在从 API 下载 ID 映射与吸引力规则: {api_url}")
    try:
        resp = requests.get(api_url)
        if not resp.ok:
            print(f"错误: 无法获取类型吸引力规则。状态码: {resp.status_code}, 原因: {resp.text}")
            return ranges
        data = resp.json()
    except Exception as e:
        print(f"API 请求失败(GET 规则): {e}")
        return ranges

    # 验证数据结构是否为列表
    if not isinstance(data, list):
        print("警告: API 返回的规则数据格式不是列表。")
        return ranges
        
    for row in data:
        range_str = row.get('id_range', '').strip('[]"')
        if ',' in range_str:
            try:
                min_id, max_id = map(int, range_str.split(','))
                type_name = row.get('英文', '').strip()
                attraction = row.get('attraction')  # 获取 attraction 属性
                ranges.append((min_id, max_id, type_name, attraction))
            except ValueError:
                continue
                
    return ranges

def get_element_info_by_id(element_id, element_ranges):
    """
    根据 id 匹配对应的 英文 type 和 attraction
    """
    if element_id is None:
        return None, None
    for min_id, max_id, type_name, attraction in element_ranges:
        if min_id <= element_id <= max_id:
            return type_name, attraction
    return None, None

def update_urban_layout_via_api(observations_path, base_url):
    # 1. 【修改点】改为从线上 API 接口读取 ID 映射规则与吸引力
    rules_api_url = "http://127.0.0.1:8000/api/simulation/type-attractions"
    element_ranges = load_shop_elements_from_api(rules_api_url)

    if not element_ranges:
        print("警告: 未获取到有效的映射规则，可能无法更新网格类型和吸引力(attraction)。")

    # 2. 本地读取观测数据
    if not os.path.exists(observations_path):
        print(f"错误: 找不到文件 {observations_path}")
        return
    
    with open(observations_path, 'r', encoding='utf-8') as f:
        observations = json.load(f)
        
    # 3. 通过 API 下载当前网格布局数据 (GET 请求)
    get_layout_url = "http://127.0.0.1:8000/api/simulation/layout"
    print(f"正在从 API 下载网格布局数据: {get_layout_url}")
    try:
        resp_get = requests.get(get_layout_url)
        if not resp_get.ok:
            print(f"错误: 无法获取网格布局。状态码: {resp_get.status_code}, 原因: {resp_get.text}")
            return
        layout_data = resp_get.json()
    except Exception as e:
        print(f"API 请求失败(GET 布局): {e}")
        return

    # 核心简化：直接以 (x, y) 对应单个 cell 字典
    cells_dict = {(cell['x'], cell['y']): cell for cell in layout_data.get('cells', [])}
    
    # 4. 遍历观测数据并更新对应位置的类型 (type) 与基础吸引力 (base_attraction)
    updated_count = 0
    
    for obs in observations:
        x = obs.get('col')
        y = obs.get('row')
        element_id = obs.get('id')
        
        if x is None or y is None:
            continue
            
        matched_type, matched_attraction = get_element_info_by_id(element_id, element_ranges)
        
        # 仅匹配横纵坐标 (x, y)
        if (x, y) in cells_dict:
            target_cell = cells_dict[(x, y)]
            
            # 更新类型
            if matched_type:
                target_cell['type'] = matched_type
                
            # 增加获取 json 中的 attraction，并修改网格布局对应的 "base_attraction" 属性
            if matched_attraction is not None:
                target_cell['base_attraction'] = matched_attraction
                
            updated_count += 1
        else:
            print(f"提示: 网格布局中未找到坐标 (x:{x}, y:{y}) 的网格，已略过。")

    print(f"本地处理完成：成功更新了 {updated_count} 个网格的类型与基础吸引力(base_attraction)。")

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
    
    # 定义您的目标上传 Base URL
    api_base_url = "http://127.0.0.1:8000/api/simulation/layout/non-public"
    
    # 【修改点】移除了本地 json_rules_file 传参
    update_urban_layout_via_api(obs_file, api_base_url)