@echo off
echo ===================================================
echo 正在启动所有追踪程序和流水线（Conda 环境: DIG）...
echo ===================================================

:: 终端 1：启动桌面流实时追踪
echo 启动桌面流实时追踪...
start "终端 1 - 桌面流实时追踪" cmd /k "conda activate DIG && python aruco_grid_twin.py --system-name desktop live-top --camera-config live_cameras_desktop.json --ground-config markers/desktop/config_markers.json --top-marker-size-mm 30.0 --block-height-mm 40.0 --output-csv outputs/desktop_grid_heights_live.csv --output-observations outputs/desktop_top_observations_live.json"

:: 终端 2：启动地面流实时追踪
echo 启动地面流实时追踪...
start "终端 2 - 地面流实时追踪" cmd /k "conda activate DIG && python aruco_grid_twin.py --system-name ground live-top --camera-config live_cameras_ground.json --ground-config markers/ground/config_markers.json --top-marker-size-mm 120.0 --block-height-mm 400.0 --output-csv outputs/ground_grid_heights_live.csv --output-observations outputs/ground_top_observations_live.json"

:: 终端 3：启动地面流水线运行器
echo 启动地面流水线运行器...
start "终端 3 - 地面流水线" cmd /k "conda activate DIG && python ground_pipeline_runner.py"

:: 终端 4：启动桌面流水线运行器
echo 启动桌面流水线运行器...
start "终端 4 - 桌面流水线" cmd /k "conda activate DIG && python desktop_pipeline_runner.py"

echo ===================================================
echo 所有程序已在各自的 DIG 环境窗口中启动！
echo ===================================================
pause