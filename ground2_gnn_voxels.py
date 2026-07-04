import csv
import json
import ast
import numpy as np
import requests

def load_csv_mapping(csv_path):
    """
    读取CSV文件并建立 id 到 元素属性（要素、长度、宽度、高度、英文名）的映射字典 
    """
    id_to_element = {}
    with open(csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            id_range = ast.literal_eval(row['id_range'])
            start_id, end_id = id_range[0], id_range[1]
            
            element_type = row['要素']
            element_en = row['英文']
            length = float(row['长度'])
            width = float(row['宽度'])
            height = float(row['高度'])
            
            for idx in range(start_id, end_id + 1):
                id_to_element[idx] = {
                    'type_zh': element_type,
                    'type_en': element_en,
                    'length': length,
                    'width': width,
                    'height': height
                }
    return id_to_element

def fetch_current_layout(api_url):
    """
    GET 请求：从 API 接口获取当前的 JSON 数据
    """
    try:
        response = requests.get(api_url)
        response.raise_for_status()
        res_json = response.json()
        
        # 严格校验：如果返回的不是字典，或者明确提示未选择，直接触发跳过
        if not isinstance(res_json, dict):
            print("⚠️ 服务器返回数据格式非字典，将跳过本次上传。")
            return None
            
        if res_json.get("detail") == "no public space detail layout is currently selected":
            print("ℹ️ 服务器提示：当前未选择任何公共空间布局。")
            return None
            
        return res_json
    except requests.exceptions.RequestException as e:
        print(f"❌ 获取布局失败 (GET): {e}")
        return None

import json
import numpy as np

def calculate_occupied_cells(model_plane_path, id_to_element):
    """
    🛠️ 修正：直接读取本地上一步生成的 model_plane.json 
    根据模型左下角位置和方向向量，计算出元素占据的空间网格
    """
    cells = []
    
    # 从本地的步骤1产物读取模型列表
    try:
        with open(model_plane_path, 'r', encoding='utf-8-sig') as f:
            models = json.load(f)
    except Exception as e:
        print(f"❌ 读取本地平面模型失败: {e}")
        return cells

    print(f"🔍 解析本地模型文件中 {len(models)} 个元素以计算占据网格...")
    
    for item in models:
        if not isinstance(item, dict) or 'coordinate' not in item:
            continue
            
        coord = item['coordinate']
        if coord == [0.0, 0.0, 100.0]:
            continue
            
        item_id = item.get('id')
        if item_id not in id_to_element:
            continue

        elem_info = id_to_element[item_id]
        L = int(elem_info['length'])
        W = int(elem_info['width'])
        H = int(elem_info['height'])
        elem_type_zh = elem_info['type_zh']
        elem_type_en = elem_info['type_en']  # 🔥 确保使用的是对应的英文名
        
        v_L = np.round(np.array([item['vector_1'][0], item['vector_1'][1], 0.0])).astype(int)
        v_W = np.round(np.array([item['vector_2'][0], item['vector_2'][1], 0.0])).astype(int)
        v_H = np.array([0, 0, 1])
        
        sx = int(round(coord[0]))
        sy = int(round(coord[1]))
        sz = 0 
        
        if v_L[0] == 1 and v_L[1] == 0:
            pass  
        elif v_L[0] == 0 and v_L[1] == 1:
            sx -= 1  
        elif v_L[0] == -1 and v_L[1] == 0:
            sx -= 1  
            sy -= 1
        elif v_L[0] == 0 and v_L[1] == -1:
            sy -= 1  
        
        if elem_type_zh == "桌椅单元":
            sz = int(round(coord[2]))
            print(f"🪑 桌椅单元高度调整为 sz={sz}，原始坐标 z={coord[2]}")

        # 1. 基础包围盒网格计算
        for l in range(L):
            for w in range(W):
                for h in range(H):
                    target_pos = np.array([sx, sy, sz]) + l * v_L + w * v_W + h * v_H 
                    x, y, z = int(target_pos[0]), int(target_pos[1]), int(target_pos[2])
                    
                    cell_entry = {
                        "x": x,
                        "y": y,
                        "z": z,
                        "type": elem_type_en  # 🔥 填充的是英文名，如 'tree'
                    }
                    
                    if cell_entry not in cells:
                        cells.append(cell_entry)
                        
        # 2. 特殊模型处理：树干（生成树冠）
        if elem_type_zh == "树干":
            cx = sx + (L - 1) / 2.0 * v_L[0] + (W - 1) / 2.0 * v_W[0]
            cy = sy + (L - 1) / 2.0 * v_L[1] + (W - 1) / 2.0 * v_W[1]
            
            r = 2.5
            r_sq = r**2
            cz = int(sz + H + r / 2.0)  
            search_r = 3  
            
            for bx in range(int(np.floor(cx - search_r)), int(np.ceil(cx + search_r)) + 1):
                for by in range(int(np.floor(cy - search_r)), int(np.ceil(cy + search_r)) + 1):
                    for bz in range(int(np.floor(cz - search_r)), int(np.ceil(cz + search_r)) + 1):
                        dist_sq = (bx - cx)**2 + (by - cy)**2 + (bz - cz)**2
                        
                        if dist_sq <= r_sq:
                            cell_entry = {
                                "x": bx,
                                "y": by,
                                "z": bz,
                                "type": elem_type_en  # 🔥 填充的是英文名
                            }
                            if cell_entry not in cells:
                                cells.append(cell_entry)                    

        # 🔥 3. 特殊模型处理：雨篷（额外增加相对范围网格）
        if elem_type_zh == "雨篷":
            # 设定固定的高度 z = 5
            # 注意：如果你的 5 高度也是相对高度，可以改为 sz + 5
            fixed_z = 5 
            
            # x 相对范围 -4 到 4 (即 range(-4, 5))
            # y 相对范围 1 到 9 (即 range(1, 10))
            for rx in range(-3, 4):
                for ry in range(1, 8):
                    # 通过局部坐标转换，保证雨篷旋转时网格同步旋转
                    # 假设 x 对应 v_L 方向，y 对应 v_W 方向
                    target_pos = np.array([sx, sy, fixed_z]) + rx * v_L + ry * v_W
                    x, y, z = int(target_pos[0]), int(target_pos[1]), int(target_pos[2])
                    
                    cell_entry = {
                        "x": x,
                        "y": y,
                        "z": z,
                        "type": elem_type_en
                    }
                    if cell_entry not in cells:
                        cells.append(cell_entry)
                        
        # 🔥 4. 特殊模型处理：路灯（额外增加高度6，x=0, y在 -5 到 0 之间的网格）
        if elem_type_zh == "路灯":
            fixed_z = 6
            # y 在 -5 到 0 的区间，对应 range(-5, 1)
            for ry in range(-5, 1):
                # x为0，因此局部坐标 rx=0，省略了 0 * v_L
                target_pos = np.array([sx, sy, fixed_z]) + ry * v_W
                x, y, z = int(target_pos[0]), int(target_pos[1]), int(target_pos[2])
                
                cell_entry = {
                    "x": x,
                    "y": y,
                    "z": z,
                    "type": elem_type_en
                }
                if cell_entry not in cells:
                    cells.append(cell_entry)
    return cells

def save_and_upload_layout(original_layout, cells, local_path, api_url):
    """
    1. 动态将新 cells 替换到原始获取的 layout 字典中（保留 parent_x, width 等所有元数据）
    2. 在本地保存为 JSON 文件 
    3. 通过 PUT 请求将更新后的 JSON 数据推送到服务器
    """
    # 既然在主程序中卡死了非字典不进，这里直接克隆并更新 cells 即可
    output_data = original_layout.copy()
    output_data["cells"] = cells
    
    # ---- Step 1: 本地保存 ----
    try:
        with open(local_path, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        print(f"💾 本地保存成功：{local_path}")
    except Exception as e:
        print(f"❌ 本地保存失败: {e}")
        return False

    # ---- Step 2: PUT 发送到服务器 ----
    print("🚀 正在将最新布局同步到服务器...")
    try:
        headers = {'Content-Type': 'application/json'}
        response = requests.put(api_url, json=output_data, headers=headers)
        
        if response.status_code in [200, 204]:
            print("✨ 服务器同步成功！(Update Current Public Layout Success)")
            return True
        else:
            print(f"⚠️ 服务器响应异常，状态码: {response.status_code}")
            print(f"服务器返回内容: {response.text}")
            return False
            
    except requests.exceptions.RequestException as e:
        print(f"❌ PUT 请求发送失败: {e}")
        return False

if __name__ == "__main__":
    csv_file = "street elements.csv"
    api_url = "http://127.0.0.1:8000/api/simulation/public-layout/current"
    output_file = "outputs/occupied_space.json"
    model_plane_file = "outputs/model_plane.json" # 本地模型数据
    
    id_mapping = load_csv_mapping(csv_file)
    layout_data = fetch_current_layout(api_url)
    
    if layout_data is not None:
        print("开始计算空间网格...")
        # 🔥 传入本地文件路径进行计算
        occupied_cells = calculate_occupied_cells(model_plane_file, id_mapping)
        print(f"网格计算完成，共生成 {len(occupied_cells)} 个单元。")
        
        save_and_upload_layout(layout_data, occupied_cells, output_file, api_url)
    else:
        print("⏭️ 条件未满足（尚未选择布局或返回数据非字典），已自动跳过本次上传。")