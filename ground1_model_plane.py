import csv
import json
import ast

def process_street_elements(csv_path, json_path, output_path):
    # 1. 读取并解析 CSV 文件
    csv_elements = []
    total_nums = 0
    with open(csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            id_range = ast.literal_eval(row['id_range'])
            nums = int(row['nums'])
            total_nums += nums
            
            csv_elements.append({
                '要素': row['要素'],
                '长度': int(row['长度']),
                '宽度': int(row['宽度']),
                '高度': int(row['高度']),
                'id_start': id_range[0],
                'id_end': id_range[1],
                'nums': nums
            })

    # 2. 读取并过滤 JSON 数据
    with open(json_path, mode='r', encoding='utf-8-sig') as f:
        json_data = json.load(f)
        
    filtered_json_map = {}
    for item in json_data:
        if item['id'] > 10 and item['row'] >= 0 and item['col'] >= 0:
            filtered_json_map[item['id']] = item

    # 3. 匹配 CSV 和 JSON 并记录结果
    matched_records = {}
    desk_chair_range = None
    all_input_json_ids = set(filtered_json_map.keys())

    for elem in csv_elements:
        is_desk_chair = (elem['要素'] == '桌椅单元')
        if is_desk_chair:
            desk_chair_range = (elem['id_start'], elem['id_end'])

        for current_id in range(elem['id_start'], elem['id_end'] + 1):
            if current_id in filtered_json_map:
                json_item = filtered_json_map[current_id]
                height_matches = (elem['高度'] == json_item['level'])
                
                if is_desk_chair or height_matches:
                    matched_records[current_id] = {
                        'row': json_item['row'],
                        'col': json_item['col'],
                        'level': json_item['level'],
                        'orientation': json_item['orientation'].replace(" ", ""),
                        'length': elem['长度'],
                        'width': elem['宽度']
                    }

    # --- 修改部分：逐层向下补齐所有缺失的 level（从 upper_level - 1 一路补到 0） ---
    if desk_chair_range:
        dc_start, dc_end = desk_chair_range
        # 找出所有在 CSV 范围内、但输入的 JSON 里完全没出现的空闲桌椅 ID
        unused_desk_chair_ids = [
            id_for_dc for id_for_dc in range(dc_start, dc_end + 1)
            if id_for_dc not in all_input_json_ids
        ]
        
        # 筛选出原 JSON 中所有不在地面的桌椅单元
        above_ground_chairs = {
            cid: rec for cid, rec in matched_records.items()
            if dc_start <= cid <= dc_end and rec['level'] > 0
        }
        
        # 对每一个悬空的桌椅，向下层层补齐
        for upper_id, upper_rec in above_ground_chairs.items():
            upper_level = upper_rec['level']
            
            # 从 upper_level - 1 开始，倒序一直补到 0 (例如 level 2 -> 补 1 和 0)
            for target_level in range(upper_level - 1, -1, -1):
                if unused_desk_chair_ids:
                    # 弹出一个空闲 ID
                    fallback_id = unused_desk_chair_ids.pop(0)
                    
                    # 强制注册该 ID，级别设为当前的 target_level
                    matched_records[fallback_id] = {
                        'row': upper_rec['row'],
                        'col': upper_rec['col'],
                        'level': target_level,  # 逐层递减补齐
                        'orientation': upper_rec['orientation'],
                        'length': upper_rec['length'],
                        'width': upper_rec['width']
                    }
                else:
                    print(f"警告: 试图为桌椅 (原ID: {upper_id}) 补齐 level: {target_level}，但空闲桌椅 ID 已用尽！")
    # ------------------------------------------------------------------------

    # 4 & 5. 根据每个品类的起始 id 和数量按顺序生成列表
    output_list = []
    for elem in csv_elements:
        for offset in range(elem['nums']):
            current_id = elem['id_start'] + offset
            
            item_dict = {
                "id": current_id,
                "type": elem['要素'],
                "coordinate": [0.0, 0.0, 100.0],
                "vector_1": [1.0, 0.0],
                "vector_2": [0.0, 1.0]
            }
            
            if current_id in matched_records:
                rec = matched_records[current_id]
                ori = rec['orientation']
                row_val = rec['row']
                col_val = rec['col']
                level_val = rec['level']
                length = rec['length']
                width = rec['width']
                
                if ori == "0,1":
                    item_dict["coordinate"] = [float(col_val), float(row_val), float(level_val)]
                elif ori == "1,0":
                    item_dict["coordinate"] = [float(col_val), float(row_val + length), float(level_val)]
                    item_dict["vector_1"] = [0.0, -1.0]
                    item_dict["vector_2"] = [1.0, 0.0]
                elif ori == "0,-1":
                    item_dict["coordinate"] = [float(col_val + length), float(row_val + width), float(level_val)]
                    item_dict["vector_1"] = [-1.0, 0.0]
                    item_dict["vector_2"] = [0.0, -1.0]
                elif ori == "-1,0":
                    item_dict["coordinate"] = [float(col_val + width), float(row_val), float(level_val)]
                    item_dict["vector_1"] = [1.0, 0.0]
                    item_dict["vector_2"] = [-1.0, 0.0]
            
            output_list.append(item_dict)

    # 6. 将结果写入新的 JSON 文件
    with open(output_path, 'w', encoding='utf-8-sig') as f:
        json.dump(output_list, f, indent=2, ensure_ascii=False)
        
    print(f"处理完成！已生成文件：{output_path}，共包含 {len(output_list)} 个元素。")

# --- 运行脚本 ---
csv_filename = "street elements.csv"
json_filename = "outputs/ground_top_observations_live.json"
output_filename = "outputs/model_plane.json"

process_street_elements(csv_filename, json_filename, output_filename)