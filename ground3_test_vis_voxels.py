import json
import random
import matplotlib.pyplot as plt
import numpy as np

# 设置中文字体，解决中文乱码问题
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'WenQuanYi Micro Hei']  # 设置中文字体
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题

def load_occupied_space(json_path):
    """
    加载生成的网格数据
    """
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data['cells']

def generate_type_colors(cells):
    """
    为 json 中出现的每种不同的 type 随机分配一种 RGB 颜色
    """
    unique_types = list(set(cell['type'] for cell in cells))
    
    # 为常见类型预设颜色，使可视化更直观
    preset_colors = {
        'building': (0.8, 0.4, 0.2, 0.9),    # 棕色 - 建筑
        'road': (0.3, 0.3, 0.3, 0.7),         # 灰色 - 道路
        'tree': (0.2, 0.7, 0.2, 0.9),         # 绿色 - 树木
        'car': (0.2, 0.3, 0.8, 0.9),          # 蓝色 - 车辆
        'streetlight': (0.9, 0.9, 0.1, 0.9),  # 黄色 - 路灯
        'pedestrian': (0.9, 0.2, 0.2, 0.9),   # 红色 - 行人
        'sign': (0.5, 0.5, 0.5, 0.9),         # 灰色 - 标识
    }
    
    type_to_color = {}
    for t in unique_types:
        if t in preset_colors:
            type_to_color[t] = preset_colors[t]
        else:
            # 生成一个随机的 (R, G, B) 元组，范围在 0-1 之间
            r = random.uniform(0.2, 0.9)
            g = random.uniform(0.2, 0.9)
            b = random.uniform(0.2, 0.9)
            type_to_color[t] = (r, g, b, 0.8)  # 0.8 是不透明度 alpha
            
    return type_to_color

def visualize_voxels(json_path):
    cells = load_occupied_space(json_path)
    if not cells:
        print("没有找到被占据的网格单元！")
        return

    # 1. 获取所有点，用来确定三维空间的边界
    x_coords = [c['x'] for c in cells]
    y_coords = [c['y'] for c in cells]
    z_coords = [c['z'] for c in cells]
    
    min_x, max_x = min(x_coords), max(x_coords)
    min_y, max_y = min(y_coords), max(y_coords)
    min_z, max_z = min(z_coords), max(z_coords)
    
    # 2. Z轴从0开始：计算偏移量
    offset_x = min_x
    offset_y = min_y
    offset_z = 0  # Z轴固定从0开始
    
    # 计算网格矩阵需要的长宽高维度
    dim_x = max_x - min_x + 1
    dim_y = max_y - min_y + 1
    dim_z = max_z - min_z + 1
    
    # 确保网格尺寸均匀（使体素在三个维度上大小一致）
    # 获取坐标范围
    range_x = max_x - min_x + 1
    range_y = max_y - min_y + 1
    range_z = max_z - min_z + 1
    
    # 计算最大范围，使图形更均匀
    max_range = max(range_x, range_y, range_z)
    
    # 3. 初始化用于 matplotlib voxels 的布尔矩阵和颜色矩阵
    voxel_grid = np.zeros((dim_x, dim_y, dim_z), dtype=bool)
    color_grid = np.zeros((dim_x, dim_y, dim_z, 4))  # RGBA 颜色映射
    
    # 获取随机颜色表
    type_to_color = generate_type_colors(cells)
    
    # 4. 填充体素网格
    for cell in cells:
        # 将世界/网格绝对坐标转换为相对于矩阵的局部索引 (从0开始)
        ix = cell['x'] - min_x
        iy = cell['y'] - min_y
        iz = cell['z'] - min_z
        
        voxel_grid[ix, iy, iz] = True
        color_grid[ix, iy, iz] = type_to_color[cell['type']]
    
    # 5. 开始绘图
    fig = plt.figure(figsize=(12, 10))
    ax = fig.add_subplot(111, projection='3d')
    
    # 调整视角倾斜度
    ax.view_init(elev=30, azim=45)
    
    # 生成网格边缘网格点，并利用绝对坐标轴进行平移
    X, Y, Z = np.indices((dim_x + 1, dim_y + 1, dim_z + 1))
    X = X + min_x
    Y = Y + min_y
    Z = Z + min_z  # 保持Z从min_z开始，但min_z应该已经是0
    
    # 如果是Z从0开始，确保min_z为0
    if min_z != 0:
        # 重新调整Z坐标，使其从0开始
        Z = Z - min_z
    
    # 渲染体素
    ax.voxels(X, Y, Z, voxel_grid, facecolors=color_grid, edgecolors='gray', linewidth=0.2, alpha=0.9)
    
    # 6. 轴标签与图例设置
    ax.set_xlabel('X 轴', fontsize=12)
    ax.set_ylabel('Y 轴', fontsize=12)
    ax.set_zlabel('Z 轴 (高度)', fontsize=12)
    
    # 动态调整网格显示范围，使三个轴比例尽量均匀
    # 计算中心点和范围，使显示更均匀
    center_x = (min_x + max_x) / 2
    center_y = (min_y + max_y) / 2
    center_z = (min_z + max_z) / 2 if min_z != 0 else max_z / 2
    
    # 设置等比例轴
    max_range = max(max_x - min_x + 2, max_y - min_y + 2, max_z - min_z + 2)
    mid_x = (min_x + max_x) / 2
    mid_y = (min_y + max_y) / 2
    mid_z = (min_z + max_z) / 2
    
    # 使用set_box_aspect使三个轴比例一致
    ax.set_box_aspect([dim_x, dim_y, dim_z])
    
    ax.set_xlim(min_x - 0.5, max_x + 0.5)
    ax.set_ylim(min_y - 0.5, max_y + 0.5)
    ax.set_zlim(min_z - 0.5, max_z + 0.5)
    
    ax.set_title('数字孪生街道要素网格占据空间可视化', fontsize=14, pad=20)
    
    # 动态创建右侧的图例标签
    legend_elements = [
        plt.Rectangle((0, 0), 1, 1, facecolor=color, edgecolor='k', label=t)
        for t, color in type_to_color.items()
    ]
    ax.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(1.05, 1))
    
    # 添加网格线（可选）
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.show()
    
    # 打印统计信息
    print(f"  - 总占据单元数: {len(cells)}")
    print(f"  - 要素类型: {list(type_to_color.keys())}")

if __name__ == "__main__":
    # 指定你的 json 文件路径
    json_file_path = "outputs/occupied_space.json"
    visualize_voxels(json_file_path)