# 1:40 Desktop ZED ArUco Grid Twin Usage

默认桌面尺度：40 mm 方格、40 mm 方块高度、30 mm ArUco 黑色标签边长；ZED 默认拍摄分辨率为 HD1080。
地面尺寸手动命令行设置参数：400 mm 方格、400 mm 方块高度、120 mm ArUco 黑色标签边长。

## 1. Install dependencies
安装 OpenCV ArUco 和数值计算依赖。

```powershell
pip install -r requirements.txt
```

## 2. Generate the ground field image
生成可直接打印的地面场地图像，采用左下角为 (0, 0, 0) 的坐标系，标签右上角对齐网格顶点。

桌面版本：
```powershell
python aruco_grid_twin.py make-ground --cols 8 --rows 6 --anchor-corner top_right --add-midpoints
```

地面1：1版本：
```powershell
python aruco_grid_twin.py make-ground --cols 8 --rows 6 --cell-mm 400.0 --marker-size-mm 120.0 --anchor-corner top_right --add-midpoints
```

`--add-midpoints` 会额外生成 4 个边中点地面标签：bottom_mid、top_mid、left_mid、right_mid。

输出文件：
- `markers/ground/ground_field_no_labels.png`
- `markers/ground/ground_field.png`
- `markers/ground/ground_id_###.png`
- `markers/ground/ground_markers.json`

## 3. Generate top block ArUco markers
桌面版本：
生成 30 mm 顶部标签，并贴在每个 40 mm 方块顶面中心。
```powershell
python aruco_grid_twin.py make-top --count 50 --start-id 10
```

地面1：1版本：
生成 120 mm 顶部标签，并贴在每个 400 mm 方块顶面中心。
```powershell
python aruco_grid_twin.py make-top --count 50 --start-id 10 --marker-size-mm 120.0
```


## 4. Capture camera ground image
用指定 ZED 拍摄地面场地图像。

```powershell
python zed_intrinsic_calibration.py capture --output-image captures/cam_b_ground.png --camera zed2
```

## 5. Solve camera extrinsic
用地面图求该相机到桌面网格坐标系的外参。

```powershell
python aruco_grid_twin.py solve-extrinsic --image captures/cam_b_ground.png --intrinsics calibration/zedb_left_intrinsics.json --camera-name cam_b --output calibration/cam_b_extrinsic.json
```

## 6. Capture camera top image
摆放方块后，用同一台 ZED 拍摄顶部标签图。

```powershell
python zed_intrinsic_calibration.py capture --output-image captures/cam_b_top.png --camera zed2
```

## 7. Detect top markers
用顶部标签图生成该相机视角下的层数表和观测 JSON。

桌面版本：

```powershell
python aruco_grid_twin.py detect-top --image captures/cam_a_top.png --intrinsics calibration/zed1_left_intrinsics.json --extrinsic calibration/cam_a_extrinsic.json --top-marker-size-mm 30.0 --block-height-mm 40.0 --output-csv outputs/cam_a_grid.csv --output-orient-csv outputs/cam_a_orientations.csv --output-observations outputs/cam_a_obs.json
```

地面1：1版本：
```powershell
python aruco_grid_twin.py detect-top --image captures/cam_a_top.png --intrinsics calibration/zed1_left_intrinsics.json --extrinsic calibration/cam_a_extrinsic.json --top-marker-size-mm 120.0 --block-height-mm 400.0 --output-csv outputs/cam_a_grid.csv --output-orient-csv outputs/cam_a_orientations.csv --output-observations outputs/cam_a_obs.json
```

## 8. Merge one or more camera observations
融合 1 个或任意多个相机观测 JSON，并输出最终层数表。

```powershell
python aruco_grid_twin.py merge-observations --observations outputs/cam_a_obs.json [outputs/cam_b_obs.json outputs/cam_c_obs.json] --output-csv outputs/grid_heights_merged.csv
```

## 9. Prepare live camera config
根据示例配置```live_cameras.example.json```按实际相机数量填写 name、camera、intrinsics、extrinsic，保存在```live_cameras.json```。


## 10. Run live multi-camera tracking
使用配置文件同时打开 1 台或任意多台 ZED，持续融合顶部标签并实时刷新表格。

桌面版本：

```powershell
python aruco_grid_twin.py live-top --camera-config live_cameras.json --top-marker-size-mm 30.0 --block-height-mm 40.0 --output-csv outputs/grid_heights_live.csv --output-orient-csv outputs/grid_orientations_live.csv --output-observations outputs/top_observations_live.json
```

地面1：1版本：
```powershell
python aruco_grid_twin.py live-top --camera-config live_cameras.json --top-marker-size-mm 120.0 --block-height-mm 400.0 --output-csv outputs/grid_heights_live.csv --output-orient-csv outputs/grid_orientations_live.csv --output-observations outputs/top_observations_live.json
```