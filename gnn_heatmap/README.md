# ZED occupied_space → 热力预测 → 可视化 JSON

将 ZED / Grasshopper 导出的实体 JSON 转为带热力数据的 `.heatmap.json`，可用浏览器查看 3D 热力。

## 环境

```bash
pip install -r requirements.txt
```

仅需 `numpy`、`scipy`，无需 PyTorch 或 GNN 模型权重。

## 用法

需要**两个输入文件**（同目录、同名序号自动配对）：

| 文件 | 说明 |
|------|------|
| `occupied_space.json` | 场景实体格坐标 |
| `street elements.csv` | 要素命名表（实体类型以此为准） |

```bash
python entity_to_heatmap.py -i occupied_space.json
python entity_to_heatmap.py -i occupied_space.json --elements-csv "street elements.csv"
python entity_to_heatmap.py -i your_scene.json -o output/result.heatmap.json
```

配对规则：`occupied_space(N).json` → 同目录 `street elements(N).csv`；若无序号则尝试 `street elements.csv`。

## street elements CSV 格式

支持带颜色代码的要素表（推荐 `street elements(2).csv`）：

```csv
要素,长度,宽度,高度,id_range,nums,,英文,,颜色代码
自动售货机,3,2,6,"[10, 11]",2,,vending_machine,,#E0E0E0
公告栏,6,1,5,"[12, 13]",2,,display_stand,,#FFA726
电话亭,3,3,5,"[14, 15]",2,,telephone_kiosk,,#1565C0
树干,1,1,5,"[18, 21]",4,,tree,,#2E7D32
邮筒,1,1,4,"[22, 25]",4,,pillar_box,,#C62828
...
```

实体颜色**直接从 CSV「颜色代码」列读取**，无需在代码里硬编码。

```bash
python entity_to_heatmap.py -i occupied_space(1).json --elements-csv "street elements(2).csv"
```

## occupied_space JSON 格式

```json
{
  "parent_x": 12, "parent_y": 8,
  "width": 10, "height": 6, "depth": 6,
  "base_attraction": 0.79,
  "cells": [{ "x": 2, "y": 3, "z": 0, "type": "树干" }]
}
```

- `cells[].type`：中文要素名（会按 CSV 归一化，如「公告板」→「公告栏」）
- 也支持 `element_id` / 数字 `type`（按 CSV 的 `id_range` 查表）

## 输出

默认写入 `output/<输入名>.heatmap.json`，含：

- `entities` — 实体中心点（`label_cn` 使用 CSV 标准要素名）
- `heatmap_voxels` — 热力体素
- `street_elements` — 使用的要素表摘要
- `social_vitality` — 社交活力指数 SVI

## 查看

用浏览器打开 `heatmap_viewer.html`，加载输出的 JSON 文件。

## 目录结构

```
zed数据捕捉＋gnn热力/
  entity_to_heatmap.py
  heatmap_viewer.html
  street elements(2).csv      # 要素表（含颜色代码，推荐）
  street elements(1).csv      # 要素表（无颜色列时回退体素类型色）
  occupied_space(1).json      # 场景样例
  requirements.txt
  affordancenet/              # 内置热力计算模块
  output/
```

## 流水线

1. 加载 `street elements*.csv` 要素表
2. 解析 `occupied_space` JSON → 体素场景（实体名对齐 CSV）
3. 合成骨骼 → 高斯扩散热力 → 计算 SVI → 导出 JSON
