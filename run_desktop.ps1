# 1. 生成地面
python aruco_grid_twin.py make-ground --output-dir "markers/ground_desktop" --cols 8 --rows 6 --cell-mm 40.0 --marker-size-mm 30.0 --anchor-corner top_right --add-midpoints

# 2. 生成顶签
python aruco_grid_twin.py make-top --output-dir "markers/top_desktop" --count 50 --start-id 10 --marker-size-mm 30.0

# 3. 实时追踪 (日常工作只需保留这一行解注执行)
# python aruco_grid_twin.py live-top --camera-config live_cameras.json --top-marker-size-mm 30.0 --block-height-mm 40.0 --output-csv outputs/grid_heights_live.csv --output-orient-csv outputs/grid_orientations_live.csv --output-observations outputs/top_observations_live.json