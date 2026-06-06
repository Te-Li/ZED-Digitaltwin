# ZED 左相机内参标定工具使用说明

## 概述

本工具用于对 **ZED 立体相机**的**左摄像头**进行内参标定。它基于 **ChArUco 棋盘格**标定法，支持以下功能：

- 生成 ChArUco 标定板图像
- 查看 ZED 相机出厂内参
- 从 ZED 相机采集左目图像
- 从采集的图像计算标定内参

---

## 依赖安装

```bash
pip install -r requirements.txt
```

## 完整标定流程示例/内参获取

## 1. Generate ChArUco calibration board
生成相机内参标定板图片并按 100% 尺寸打印。

```powershell
python zed_intrinsic_calibration.py make-board --output calibration/neo_charuco_board.png
```

## 2. Capture ZED left-camera calibration images
用指定 SN 的 ZED 左目采集 20-40 张不同角度的标定板图片。

```powershell
python zed_intrinsic_calibration.py capture --output-dir calibration/images --camera zed1
```

## 3. Calibrate ZED left-camera intrinsics
根据采集图片计算左目 OpenCV 内参。

```powershell
python zed_intrinsic_calibration.py calibrate --image-dir calibration/images --output calibration/zed_left_intrinsics.json
```
### 标定质量评估

- **RMS < 0.5 px**：优秀
- **0.5 px < RMS < 1.0 px**：良好
- **RMS > 1.0 px**：需要重新采集更多、更丰富的图像

## 4. Show ZED factory intrinsics
读取指定 SN 的 ZED SDK 出厂内参用于对比检查。

```powershell
python zed_intrinsic_calibration.py show-zed-factory  --camera zed1
```


---

## 命令总览

```bash
python calibrate_zed.py <command> [options]
```

| 命令 | 功能 |
|------|------|
| `make-board` | 生成 ChArUco 标定板图片 |
| `show-zed-factory` | 读取并显示 ZED 出厂内参 |
| `capture` | 从 ZED 左相机采集标定图像 |
| `calibrate` | 从采集的图像计算内参 |

---

## 1. 生成 ChArUco 标定板

### 用途
生成用于打印的 ChArUco 标定板图像。

### 命令
```bash
python calibrate_zed.py make-board [选项]
```

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--dictionary` | `DICT_5X5_100` | ArUco 字典名称 |
| `--squares-x` | `7` | 棋盘横向方格数 |
| `--squares-y` | `5` | 棋盘纵向方格数 |
| `--square-length-mm` | `40.0` | 每个方格的边长（毫米） |
| `--marker-length-mm` | `30.0` | 每个 ArUco 标记的边长（毫米） |
| `--output` | `calibration/charuco_board.png` | 输出图片路径 |
| `--image-width-px` | `2400` | 输出图片宽度（像素） |
| `--image-height-px` | `1800` | 输出图片高度（像素） |
| `--margin-px` | `80` | 图片边距（像素） |

### 示例
```bash
# 使用默认参数生成标定板
python calibrate_zed.py make-board

# 自定义标定板尺寸
python calibrate_zed.py make-board     --squares-x 9     --squares-y 6     --square-length-mm 50.0     --marker-length-mm 40.0     --output my_board.png
```

### 打印要求
- 以 **100% 实际尺寸** 打印，不要缩放
- 打印后测量一个方格的实际尺寸，确认与设定值一致
- 建议打印在硬质平整材料上，避免褶皱

---

## 2. 查看 ZED 出厂内参

### 用途
读取 ZED 相机存储的出厂标定参数，作为参考或对比。

### 命令
```bash
python calibrate_zed.py show-zed-factory [选项]
```

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--resolution` | `HD1080` | 采集分辨率（如 `HD720`, `HD1080`, `HD2K`） |
| `--fps` | `30` | 采集帧率 |
| `--camera` / `--serial-number` | 无 | 指定相机（相机 ID 如 `zed1` 或序列号） |

### 示例
```bash
# 查看默认相机的出厂内参
python calibrate_zed.py show-zed-factory

# 指定分辨率和帧率
python calibrate_zed.py show-zed-factory --resolution HD2K --fps 15

# 指定特定相机
python calibrate_zed.py show-zed-factory --camera zed1
```

### 输出示例
```json
Left camera factory intrinsics:
{
  "fx": 700.123,
  "fy": 700.456,
  "cx": 640.0,
  "cy": 360.0,
  "distortion": [0.0, 0.0, 0.0, 0.0, 0.0],
  "image_size": [1280, 720]
}
```

---

## 3. 采集标定图像

### 用途
从 ZED 左相机实时采集用于标定的图像。

### 命令
```bash
python calibrate_zed.py capture [选项]
```

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--output-dir` | `calibration/images` | 保存图像的目录 |
| `--output-image` | 无 | 直接保存单帧到指定路径（非交互模式） |
| `--resolution` | `HD1080` | 采集分辨率 |
| `--fps` | `30` | 采集帧率 |
| `--camera` / `--serial-number` | 无 | 指定相机 |

### 交互模式（默认）

```bash
python calibrate_zed.py capture
```

运行后会打开一个预览窗口：
- **按 `空格键 (SPACE)`**：保存当前帧
- **按 `q` 或 `ESC`**：退出

**采集建议：**
- 将标定板移动到画面的**各个角落、边缘**
- 尝试**不同距离**（近、中、远）
- 尝试**不同倾斜角度**
- 确保标定板占据画面足够大的区域
- 保持图像清晰，避免运动模糊
- 建议采集 **20~50 张** 图像

### 单帧模式
```bash
# 直接保存一帧，不打开交互窗口
python calibrate_zed.py capture --output-image snapshot.png
```

---

## 4. 计算内参

### 用途
从采集的图像中检测 ChArUco 角点，计算相机内参和畸变系数。

### 命令
```bash
python calibrate_zed.py calibrate [选项]
```

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--dictionary` | `DICT_5X5_100` | ArUco 字典（必须与生成标定板时一致） |
| `--squares-x` | `7` | 横向方格数（必须与标定板一致） |
| `--squares-y` | `5` | 纵向方格数（必须与标定板一致） |
| `--square-length-mm` | `40.0` | 方格边长（毫米，必须与标定板一致） |
| `--marker-length-mm` | `30.0` | 标记边长（毫米，必须与标定板一致） |
| `--image-dir` | `calibration/images` | 输入图像目录 |
| `--output` | `calibration/zed_left_intrinsics.json` | 输出标定结果路径 |
| `--min-corners` | `12` | 单张图像最少检测到的角点数 |
| `--min-images` | `15` | 最少有效图像数 |

### 示例
```bash
# 使用默认参数标定
python calibrate_zed.py calibrate

# 自定义标定板参数（必须与生成时一致）
python calibrate_zed.py calibrate     --dictionary DICT_5X5_100     --squares-x 9     --squares-y 6     --square-length-mm 50.0     --marker-length-mm 40.0     --image-dir ./my_images     --output ./my_calib.json
```

### 输出结果

标定结果以 JSON 格式保存，包含以下字段：

```json
{
  "rms_reprojection_error_px": 0.2345,
  "image_size": [1920, 1080],
  "camera_matrix": [
    [fx, 0, cx],
    [0, fy, cy],
    [0, 0, 1]
  ],
  "dist_coeffs": [k1, k2, p1, p2, k3],
  "board": {
    "type": "ChArUco",
    "dictionary": "DICT_5X5_100",
    "squares_x": 7,
    "squares_y": 5,
    "square_length_mm": 40.0,
    "marker_length_mm": 30.0
  },
  "valid_image_count": 25
}
```

---




---

## 常见问题

### Q1: 报错 "OpenCV is not installed"
安装 contrib 版本：
```bash
pip install opencv-contrib-python
```

### Q2: 报错 "Your OpenCV build has no aruco module"
你安装的是标准 OpenCV，缺少 contrib 模块。请重新安装：
```bash
pip uninstall opencv-python
pip install opencv-contrib-python
```

### Q3: 报错 "pyzed is not installed"
需要安装 ZED SDK 的 Python API。参考 [Stereolabs 官方文档](https://www.stereolabs.com/docs/app-development/python/install) 安装。

### Q4: 采集时检测不到角点
- 确保 `--dictionary` 参数与生成标定板时一致
- 确保打印的标定板没有变形、褶皱
- 确保光照均匀，避免反光或阴影
- 让标定板占据画面更大区域

### Q5: RMS 误差很大
- 采集更多图像（建议 30 张以上）
- 确保覆盖画面的所有区域和不同距离
- 确保图像清晰，无运动模糊
- 检查打印的标定板尺寸是否准确

---

## 支持的 ArUco 字典

常用字典包括：
- `DICT_4X4_50`, `DICT_4X4_100`, `DICT_4X4_250`, `DICT_4X4_1000`
- `DICT_5X5_50`, `DICT_5X5_100`, `DICT_5X5_250`, `DICT_5X5_1000`
- `DICT_6X6_50`, `DICT_6X6_100`, `DICT_6X6_250`, `DICT_6X6_1000`
- `DICT_7X7_50`, `DICT_7X7_100`, `DICT_7X7_250`, `DICT_7X7_1000`
- `DICT_ARUCO_ORIGINAL`
- `DICT_APRILTAG_16h5`, `DICT_APRILTAG_25h9`, `DICT_APRILTAG_36h10`, `DICT_APRILTAG_36h11`

> 标定板生成和标定计算必须使用**相同的字典**。
