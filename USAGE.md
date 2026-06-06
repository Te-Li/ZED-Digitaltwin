# 1:40 Desktop ZED ArUco Grid Twin Usage

默认桌面尺度：40 mm 方格、40 mm 方块高度、30 mm ArUco 黑色标签边长；ZED 默认拍摄分辨率为 HD1080。

## 1. Install dependencies
安装 OpenCV ArUco 和数值计算依赖。

```powershell
pip install -r requirements.txt
```

## 2. Generate the ground field image
生成可直接打印的地面场地图像，采用左下角为 (0, 0, 0) 的坐标系，标签右上角对齐网格顶点。

```powershell
python aruco_grid_twin.py make-ground --cols 8 --rows 6 --anchor-corner top_right --add-midpoints
```

`--add-midpoints` 会额外生成 4 个边中点地面标签：bottom_mid、top_mid、left_mid、right_mid。

输出文件：
- `markers/ground/ground_field_no_labels.png`
- `markers/ground/ground_field.png`
- `markers/ground/ground_id_###.png`
- `markers/ground/ground_markers.json`

## 3. Generate top block ArUco markers
生成 30 mm 顶部标签，并贴在每个 40 mm 方块顶面中心。

```powershell
python aruco_grid_twin.py make-top --count 50 --start-id 20
```

## 4. Capture camera ground image
用指定 ZED 拍摄地面场地图像。

```powershell
python zed_intrinsic_calibration.py capture --output-image captures/cam_a_ground.png --camera zed1
```

## 5. Solve camera extrinsic
用地面图求该相机到桌面网格坐标系的外参。

```powershell
python aruco_grid_twin.py solve-extrinsic --image captures/cam_a_ground.png --intrinsics calibration/zed1_left_intrinsics.json --camera-name cam_a --output calibration/cam_a_extrinsic.json
```

## 6. Capture camera top image
摆放方块后，用同一台 ZED 拍摄顶部标签图。

```powershell
python zed_intrinsic_calibration.py capture --output-image captures/cam_a_top.png --camera zed1
```

## 7. Detect top markers
用顶部标签图生成该相机视角下的层数表和观测 JSON。

```powershell
python aruco_grid_twin.py detect-top --image captures/cam_a_top.png --intrinsics calibration/zed1_left_intrinsics.json --extrinsic calibration/cam_a_extrinsic.json --output-csv outputs/cam_a_grid.csv --output-observations outputs/cam_a_obs.json
```

## 8. Merge one or more camera observations
融合 1 个或任意多个相机观测 JSON，并输出最终层数表。

```powershell
python aruco_grid_twin.py merge-observations --observations outputs/cam_a_obs.json outputs/cam_b_obs.json outputs/cam_c_obs.json --output-csv outputs/grid_heights_merged.csv
```

## 9. Prepare live camera config
复制示例配置并按实际相机数量填写 name、camera、intrinsics、extrinsic。

```powershell
copy live_cameras.example.json live_cameras.json
```

## 10. Run live multi-camera tracking
使用配置文件同时打开 1 台或任意多台 ZED，持续融合顶部标签并实时刷新表格。

```powershell
python aruco_grid_twin.py live-top --camera-config live_cameras.json --output-csv outputs/grid_heights_live.csv --output-observations outputs/top_observations_live.json
```

## 11. Run legacy two-camera live tracking
如果只用旧的 A/B 参数，也可以继续以两台相机方式运行。

```powershell
python aruco_grid_twin.py live-top --camera-a zed1 --camera-b zed2 --camera-a-intrinsics calibration/zed1_left_intrinsics.json --camera-b-intrinsics calibration/zed2_left_intrinsics.json --camera-a-extrinsic calibration/cam_a_extrinsic.json --camera-b-extrinsic calibration/cam_b_extrinsic.json
```
