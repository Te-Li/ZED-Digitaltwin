# 1:40 Multi-System ZED ArUco Grid Twin Usage (Desktop & Ground)

通过在命令最前方指定 --system-name desktop（默认）或 --system-name ground，可在同一台主机上同时、独立地运行“桌面 1:40 缩尺系统”与“地面 1:1 实体系统”，两套系统的文件流、画布预览窗口和输出 CSV 完全隔离。


参数,桌面系统 (--system-name desktop),地面系统 (--system-name ground)
默认方格网格,非均匀布局 (由 JSON 定义),6 × 10 阵列 (400 × 400 均匀)
方格尺寸 (--cell-mm),动态 (40mm / 60mm 等),400 mm
方块高度 (--block-height-mm),40 mm,400 mm
标签边长 (--marker-size-mm),30 mm,120 mm
相机分辨率 / 帧率,HD1080 @ 30 FPS,HD1080 @ 30 FPS


## 1. Install dependencies
安装 OpenCV ArUco 和数值计算依赖。

```powershell
pip install -r requirements.txt
```

## 2. Generate the ground field image
生成可直接打印的场地基础总览图。采用左下角为 (0, 0, 0) 的物理坐标系，标签位置已实现向内收缩移动一格（避开边缘格点顶点），右上角对齐网格顶点。地图长边分辨率默认统一加粗渲染为 4000 px 以保证清晰度。

```powershell
# 桌面版本（采用 JSON 非均匀布局定义底图）：
python aruco_grid_twin.py --system-name desktop make-ground --layout-json urban-grid-layout.json --marker-size-mm 30.0 --add-midpoints

# 地面 1:1 版本（保持 400mm 均匀网格，命令不变）：
python aruco_grid_twin.py --system-name ground make-ground --cols 10 --rows 6 --cell-x-mm 400.0 --cell-y-mm 400.0 --marker-size-mm 120.0 --output-dir markers/ground --add-midpoints
```

`--add-midpoints` 会额外生成 4 个内缩边界的边中点标签。

输出文件：
- 桌面：markers/desktop/{field_no_labels.png, field_with_labels.png, id_###.png, config_markers.json}
- 地面：markers/ground/{field_no_labels.png, field_with_labels.png, id_###.png, config_markers.json}

## 3. Generate top block ArUco markers
生成贴在可移动方块顶面中心的 ArUco 标签。
桌面版本（30 mm 标签）：
```powershell
python aruco_grid_twin.py --system-name desktop make-top --count 90 --start-id 10 --marker-size-mm 30.0 --output-dir markers/top_desktop
```

地面 1:1 版本（120 mm 标签）：
```powershell
python aruco_grid_twin.py --system-name ground make-top --count 90 --start-id 10 --marker-size-mm 120.0 --output-dir markers/top_ground
```


## 4. Capture camera ground image
使用指定 ZED 相机拍摄地面/桌面背景场地图像用于外参计算。

```powershell
# 桌面相机捕捉
python zed_intrinsic_calibration.py capture --output-image captures/desktop_cam_c_ground.png --camera zed3

# 地面相机捕捉
python zed_intrinsic_calibration.py capture --output-image captures/ground_cam_b_ground.png --camera zed2
```

## 5. Solve camera extrinsic
利用生成的场地配置文件，计算相机相对于各自系统网格坐标系的外参（矩阵与旋转向量）。

桌面版本：
```powershell
python aruco_grid_twin.py --system-name desktop solve-extrinsic --image captures/desktop_cam_c_ground.png --intrinsics calibration/zedc_left_intrinsics.json --ground-config markers/desktop/config_markers.json --camera-name cam_c --output calibration/desktop_cam_c_extrinsic.json
```

地面 1:1 版本：
```powershell
python aruco_grid_twin.py --system-name ground solve-extrinsic --image captures/ground_cam_b_ground.png --intrinsics calibration/zedb_left_intrinsics.json --ground-config markers/ground/config_markers.json --camera-name cam_b --output calibration/ground_cam_b_extrinsic.json
```

## 6. Capture camera top image
码放好积木方块后，拍摄带有顶部标签的实拍画面。

```powershell
python zed_intrinsic_calibration.py capture --output-image captures/desktop_cam_a_top.png --camera zed1
```

## 7. Detect top markers (离线静态单张检测)
通过单张照片生成带有系统前缀区分的层数表（Grid）、朝向表（Orientation）和观测数据。

桌面版本：

```powershell
python aruco_grid_twin.py --system-name desktop detect-top --image captures/desktop_cam_a_top.png --intrinsics calibration/zeda_left_intrinsics.json --extrinsic calibration/desktop_cam_a_extrinsic.json --ground-config markers/desktop/config_markers.json --top-marker-size-mm 30.0 --block-height-mm 40.0 --output-csv outputs/desktop_grid_heights.csv --output-observations outputs/desktop_top_observations.json
```

地面1：1版本：
```powershell
python aruco_grid_twin.py --system-name ground detect-top --image captures/ground_cam_b_top.png --intrinsics calibration/zed2_left_intrinsics.json --extrinsic calibration/ground_cam_b_extrinsic.json --ground-config markers/ground/config_markers.json --top-marker-size-mm 120.0 --block-height-mm 400.0 --output-csv outputs/ground_grid_heights.csv --output-observations outputs/ground_top_observations.json
```

## 8. Merge one or more camera observations
融合单个系统下、多台相机重叠视角产生的离线数据。

桌面观测融合：

```powershell
python aruco_grid_twin.py --system-name desktop merge-observations --ground-config markers/desktop/config_markers.json --observations outputs/desktop_cam_a_obs.json outputs/desktop_cam_b_obs.json --output-csv outputs/desktop_grid_heights_merged.csv --output-json outputs/desktop_top_observations_merged.json
```

## 9. Prepare live camera config
由于多实例并行，建议为桌面和地面准备两份不同的 live 配置文件，如 live_cameras_desktop.json 和 live_cameras_ground.json。

内部结构示例：

{
  "cameras": [
    {
      "name": "camera_a",
      "serial_number": "ZED_SERIAL_1",
      "intrinsics": "calibration/zed1_left_intrinsics.json",
      "extrinsic": "calibration/desktop_cam_a_extrinsic.json"
    }
  ]
}


## 10. Run live multi-camera tracking (双系统同时运行)
打开两个相互独立的终端控制台，分别复制并执行以下两条命令，两套实时追踪系统将同时启动，实时渲染带系统标签的预览视窗，并各自独立刷新各自的 CSV 表格。

终端终端 1（启动桌面流实时追踪）：

```powershell
python aruco_grid_twin.py --system-name desktop live-top --camera-config live_cameras_desktop.json --ground-config markers/desktop/config_markers.json --top-marker-size-mm 30.0 --block-height-mm 40.0 --output-csv outputs/desktop_grid_heights_live.csv --output-observations outputs/desktop_top_observations_live.json
```


终端终端 2（启动地面流实时追踪）：
```powershell
python aruco_grid_twin.py --system-name ground live-top --camera-config live_cameras_ground.json --ground-config markers/ground/config_markers.json --top-marker-size-mm 120.0 --block-height-mm 400.0 --output-csv outputs/ground_grid_heights_live.csv --output-observations outputs/ground_top_observations_live.json
```