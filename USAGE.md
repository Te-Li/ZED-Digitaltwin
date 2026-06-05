# 1:20 Desktop ZED ArUco Grid Twin Usage

默认桌面尺度：原 400 mm 方格缩小为 20 mm 方格，原 400 mm 方块高度缩小为 20 mm，ground/top ArUco 黑色标签边长默认为 15 mm；打印标签时优先使用生成的 SVG 文件并按 100% 比例打印。

## 1. Install dependencies
安装 OpenCV ArUco 和数值计算依赖。

```powershell
pip install -r requirements.txt
```

## 2. Generate ground ArUco markers
生成桌面地面坐标系标签，并按 SVG 中 15 mm 黑色标签的右上角对齐 20 mm 网格顶点粘贴。

```powershell
python aruco_grid_twin.py make-ground --cols 8 --rows 6 --anchor-corner top_right --add-midpoints
```

## 3. Generate top block ArUco markers
生成 15 mm 顶部标签，并把黑色标签区域贴在每个 20 mm 方块的顶面中心。

```powershell
python aruco_grid_twin.py make-top --count 50 --start-id 20
```

## 4. Capture camera A ground image
用相机 A 拍摄地面标签图，并保存为 `captures/cam_a_ground.png`。

```powershell
python zed_intrinsic_calibration.py capture --output-image captures/cam_a_ground.png --resolution HD720 --fps 30 --serial-number 34407890
```

## 5. Solve camera A extrinsic
用相机 A 的地面图求相机到桌面网格坐标系的外参。

```powershell
python aruco_grid_twin.py solve-extrinsic --image captures/cam_a_ground.png --intrinsics calibration/zed1_left_intrinsics.json --camera-name cam_a --output calibration/cam_a_extrinsic.json
```

## 6. Capture camera B ground image
用相机 B 拍摄地面标签图，并保存为 `captures/cam_b_ground.png`。

```powershell
python zed_intrinsic_calibration.py capture --output-image captures/cam_b_ground.png --resolution HD720 --fps 30 --serial-number 37807506
```

## 7. Solve camera B extrinsic
用相机 B 的地面图求相机到桌面网格坐标系的外参。

```powershell
python aruco_grid_twin.py solve-extrinsic --image captures/cam_b_ground.png --intrinsics calibration/zed2_left_intrinsics.json --camera-name cam_b --output calibration/cam_b_extrinsic.json
```

## 8. Capture camera A top image
摆放方块后，用相机 A 拍摄顶部标签图。

```powershell
python zed_intrinsic_calibration.py capture --output-image captures/cam_a_top.png --resolution HD720 --fps 30 --serial-number 34407890
```

## 9. Detect top markers from camera A
用相机 A 的顶部标签图生成该视角下的层数表。

```powershell
python aruco_grid_twin.py detect-top --image captures/cam_a_top.png --intrinsics calibration/zed1_left_intrinsics.json --extrinsic calibration/cam_a_extrinsic.json --output-csv outputs/cam_a_grid.csv --output-observations outputs/cam_a_obs.json
```

## 10. Capture camera B top image
摆放方块后，用相机 B 拍摄顶部标签图。

```powershell
python zed_intrinsic_calibration.py capture --output-image captures/cam_b_top.png --resolution HD720 --fps 30 --serial-number 37807506
```

## 11. Detect top markers from camera B
用相机 B 的顶部标签图生成该视角下的层数表。

```powershell
python aruco_grid_twin.py detect-top --image captures/cam_b_top.png --intrinsics calibration/zed2_left_intrinsics.json --extrinsic calibration/cam_b_extrinsic.json --output-csv outputs/cam_b_grid.csv --output-observations outputs/cam_b_obs.json
```

## 12. Merge camera observations
融合两台相机的顶部标签观测并输出最终 m*n 层数表。

```powershell
python aruco_grid_twin.py merge-observations --observations outputs/cam_a_obs.json outputs/cam_b_obs.json --output-csv outputs/grid_heights_merged.csv
```

## 13. Run live dual-camera tracking
正式运行时同时打开两台相机，持续识别顶部标签并实时刷新表格。

```powershell
python aruco_grid_twin.py live-top --camera-a-serial-number 34407890 --camera-b-serial-number 37807506 --camera-a-intrinsics calibration/zed1_left_intrinsics.json --camera-b-intrinsics calibration/zed2_left_intrinsics.json --camera-a-extrinsic calibration/cam_a_extrinsic.json --camera-b-extrinsic calibration/cam_b_extrinsic.json --output-csv outputs/grid_heights_live.csv --output-observations outputs/top_observations_live.json
```

## 14. Use full-scale 400 mm settings
如果要切回真实 400 mm 方块，显式传入原尺寸参数。

```powershell
python aruco_grid_twin.py make-ground --cols 8 --rows 6 --cell-mm 400 --marker-size-mm 120 --anchor-corner top_right --add-midpoints
```
