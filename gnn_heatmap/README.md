# gnn3d+2d：3D 热力 → 2D 观测热力 → 可视化

## 目录

| 目录 | 说明 |
|------|------|
| `output/` | **3D 输出**（`occupied_space.heatmap.json`，用于实体留白） |
| `outputs/` | **2D 输入**（`ground_top_observations_live.json`） |
| `output_2d/` | **2D 输出**（JSON + HTML 快照） |

## 2D 输入格式

默认读取：

```
outputs/ground_top_observations_live.json
```

JSON 为**观测数组**，每条例如：

```json
{
  "id": 4,
  "center_x_mm": 1957.82,
  "center_y_mm": 403.71,
  "center_z_mm": -59.29,
  "row": 1,
  "col": 4,
  "level": 0,
  "orientation": "0,1",
  "source": "cam_b",
  "serial_number": 37807506
}
```

- **row / col**：1-based 网格坐标（10×6，400mm/格）
- 按 `row/col` 统计每格观测次数并归一化为热力
- 若存在 3D 热力 JSON，实体占据格仍**留白**

## 用法

```powershell
# 仅 2D（读 outputs/ground_top_observations_live.json）
python entity_to_heatmap.py --only-2d

# 指定观测文件
python entity_to_heatmap.py --only-2d --ground-top outputs/ground_top_observations_live.json

# 实时网页（监听 outputs/ 下 JSON 变化）
python entity_to_heatmap.py --only-2d --serve

# 旧模式：从 3D heatmap.json 投影 2D
python entity_to_heatmap.py --only-2d --from-3d
```

## 实时网址

```
http://127.0.0.1:8766/heatmap_2d_live.html
```

`outputs/ground_top_observations_live.json` 更新后，网页约 1 秒自动刷新。

## 2D 网格参数

- 网格：**10 × 6** 格（col × row）
- 格大小：**400mm × 400mm**
- 范围：**4.0m × 2.4m**

## 离线快照

双击 `output_2d/ground_top_observations_live.heatmap2d.html`
