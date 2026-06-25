import csv
import json
import ast
import numpy as np

def load_csv_mapping(csv_path):
    """
    读取CSV文件并建立 id 到 元素属性（要素、长度、宽度、高度）的映射字典
    """
    id_to_element = {}
    with open(csv_path, mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            id_range = ast.literal_eval(row['id_range'])
            start_id, end_id = id_range[0], id_range[1]
            
            element_type = row['要素']
            length = float(row['长度'])
            width = float(row['宽度'])
            height = float(row['高度'])
            
            for idx in range(start_id, end_id + 1):
                id_to_element[idx] = {
                    'type': element_type,
                    'length': length,
                    'width': width,
                    'height': height
                }
    return id_to_element

def calculate_occupied_cells(model_json_path, id_to_element):
    """
    根据模型左下角位置和方向向量，直接向三个维度遍历并计算出元素占据的空间网格。
    依据 vector_1 的朝向动态修正基准起点 (sx, sy)。
    """
    with open(model_json_path, 'r', encoding='utf-8-sig') as f:
        models = json.load(f)
        
    cells = []
    
    for item in models:
        coord = item['coordinate']
        # 1. 过滤掉坐标为 [0.0, 0.0, 100.0] 的元素
        if coord == [0.0, 0.0, 100.0]:
            continue
            
        item_id = item['id']
        if item_id not in id_to_element:
            continue
            
        # 获取 CSV 中对应的尺寸信息 [cite: 1]
        elem_info = id_to_element[item_id]
        L = int(elem_info['length'])   # 显式转换为整数步进 [cite: 1]
        W = int(elem_info['width'])
        H = int(elem_info['height'])
        elem_type = elem_info['type']
        
        # 将浮点方向向量转换为整数网格步进 [cite: 1]
        v_L = np.round(np.array([item['vector_1'][0], item['vector_1'][1], 0.0])).astype(int)
        v_W = np.round(np.array([item['vector_2'][0], item['vector_2'][1], 0.0])).astype(int)
        v_H = np.array([0, 0, 1])  # 向上为高度正方向
        
        # 2. 确定空间扩展的离散网格步进向量
        # 基础未修正起点
        sx = int(round(coord[0]))
        sy = int(round(coord[1]))
        sz = 0 
        
        # 📢 核心修改点：根据 vector_1 (v_L) 的四个离散方向动态调整空间扩散基点 [cite: 1]
        if v_L[0] == 1 and v_L[1] == 0:
            pass  # [1, 0] -> 不调整
        elif v_L[0] == 0 and v_L[1] == 1:
            sx -= 1  # [0, 1] -> sx = sx - 1
        elif v_L[0] == -1 and v_L[1] == 0:
            sx -= 1  # [-1, 0] -> sx = sx - 1, sy = sy - 1
            sy -= 1
        elif v_L[0] == 0 and v_L[1] == -1:
            sy -= 1  # [0, -1] -> sy = sy - 1
        
        # 若是“桌椅单元”，高度方向需从原始 coord[2] 开始
        if elem_type == "桌椅单元":
            sz = int(round(coord[2]))

        # 3. 严格按照长、宽、高范围进行三重循环，步进占据空间 [cite: 1]
        for l in range(L):
            for w in range(W):
                for h in range(H):
                    # 组合向量：从修正后的起点出发，加上各方向上的累加步进
                    target_pos = np.array([sx, sy, sz]) + l * v_L + w * v_W + h * v_H
                    x, y, z = int(target_pos[0]), int(target_pos[1]), int(target_pos[2])
                    
                    cell_entry = {
                        "x": x,
                        "y": y,
                        "z": z,
                        "type": elem_type
                    }
                    
                    # 避免不同元素之间可能产生的重复坐标冲突 [cite: 1]
                    if cell_entry not in cells:
                        cells.append(cell_entry)
                        
        # 4. 为“树干”在上方增加直径为 5 的球体（树冠）
        if elem_type == "树干":
            # 计算树干顶部的中心点（网格坐标）
            cx = sx + (L - 1) / 2.0 * v_L[0] + (W - 1) / 2.0 * v_W[0]
            cy = sy + (L - 1) / 2.0 * v_L[1] + (W - 1) / 2.0 * v_W[1]
            
            r = 2.5

            r_sq = r**2

            cz = int(sz + H + r / 2.0)  # 树干正上方作为球心 z 轴位置
            search_r = 3  # 外接搜索立方体半径扩大到 4
            
            # 遍历球体可能覆盖的整数网格范围
            for bx in range(int(np.floor(cx - search_r)), int(np.ceil(cx + search_r)) + 1):
                for by in range(int(np.floor(cy - search_r)), int(np.ceil(cy + search_r)) + 1):
                    for bz in range(int(np.floor(cz - search_r)), int(np.ceil(cz + search_r)) + 1):
                        

                        dist_sq = (bx - cx)**2 + (by - cy)**2 + (bz - cz)**2
                        
                        # 如果在球体半径内，作为树干（树冠）部分加入空间
                        if dist_sq <= r_sq:
                            cell_entry = {
                                "x": bx,
                                "y": by,
                                "z": bz,
                                "type": elem_type
                            }
                            if cell_entry not in cells:
                                cells.append(cell_entry)                    
    return cells

def save_output_json(cells, output_path):
    """
    将生成的cells填充入模板并保存
    """
    output_data = {
        "parent_x": 12,
        "parent_y": 8,
        "width": 10,
        "height": 6,
        "depth": 6,
        "base_attraction": 0.79,
        "cells": cells
    }
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    csv_file = "street elements.csv"
    json_file = "outputs/model_plane.json"
    output_file = "outputs/occupied_space.json"
    
    # 1. 建立ID到属性的映射
    id_mapping = load_csv_mapping(csv_file)
    
    # 2. 计算被占据的空间网格
    occupied_cells = calculate_occupied_cells(json_file, id_mapping)
    
    # 3. 输出并保存到新的JSON文件中
    save_output_json(occupied_cells, output_file)
    print(f"处理完成！空间信息已成功写入至 {output_file}，共占据了 {len(occupied_cells)} 个网格单元。")