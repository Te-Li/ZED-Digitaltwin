import argparse
import csv
import ctypes
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

from camera_serials import resolve_camera_serial_number

try:
    import cv2
except ImportError:
    cv2 = None


def require_opencv():
    if cv2 is None:
        raise RuntimeError("OpenCV is not installed. Run: pip install opencv-contrib-python")


def get_preview_fit_size(image_width, image_height, margin_ratio=0.9):
    screen_width = 1600
    screen_height = 900
    try:
        user32 = ctypes.windll.user32
        screen_width = int(user32.GetSystemMetrics(0))
        screen_height = int(user32.GetSystemMetrics(1))
    except Exception:
        pass

    max_width = max(1, int(screen_width * margin_ratio))
    max_height = max(1, int(screen_height * margin_ratio))
    scale = min(1.0, max_width / float(image_width), max_height / float(image_height))
    return max(1, int(round(image_width * scale))), max(1, int(round(image_height * scale)))


def resize_preview_for_display(image):
    height, width = image.shape[:2]
    target_width, target_height = get_preview_fit_size(width, height)
    if target_width == width and target_height == height:
        return image, (width, height)
    resized = cv2.resize(image, (target_width, target_height), interpolation=cv2.INTER_AREA)
    return resized, (target_width, target_height)


def get_aruco_dict(name):
    require_opencv()
    if not hasattr(cv2, "aruco"):
        raise RuntimeError("Your OpenCV build has no aruco module. Install opencv-contrib-python.")
    if not hasattr(cv2.aruco, name):
        raise ValueError(f"Unknown ArUco dictionary: {name}")
    return cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, name))


def detect_markers(gray, dictionary_name):
    dictionary = get_aruco_dict(dictionary_name)
    params = cv2.aruco.DetectorParameters()
    if hasattr(cv2.aruco, "ArucoDetector"):
        detector = cv2.aruco.ArucoDetector(dictionary, params)
        corners, ids, rejected = detector.detectMarkers(gray)
    else:
        corners, ids, rejected = cv2.aruco.detectMarkers(gray, dictionary, parameters=params)
    return corners, ids, rejected


def load_intrinsics(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    camera_matrix = np.array(data["camera_matrix"], dtype=np.float64)
    dist_coeffs = np.array(data["dist_coeffs"], dtype=np.float64).reshape(-1, 1)
    return camera_matrix, dist_coeffs


def rodrigues_to_list(rvec):
    rotation, _ = cv2.Rodrigues(np.asarray(rvec, dtype=np.float64).reshape(3, 1))
    return rotation.tolist()


def invert_transform(rotation, translation):
    rotation = np.asarray(rotation, dtype=np.float64)
    translation = np.asarray(translation, dtype=np.float64).reshape(3, 1)
    inv_rotation = rotation.T
    inv_translation = -inv_rotation @ translation
    return inv_rotation, inv_translation


def marker_local_corners(size_mm):
    half = size_mm / 2.0
    return np.array(
        [
            [-half, half, 0.0],   # top-left
            [half, half, 0.0],    # top-right
            [half, -half, 0.0],   # bottom-right
            [-half, -half, 0.0],  # bottom-left
        ],
        dtype=np.float64,
    )


def marker_anchor_offset(size_mm, anchor_corner):
    corners = marker_local_corners(size_mm)
    corner_index = {
        "top_left": 0,
        "top_right": 1,
        "bottom_right": 2,
        "bottom_left": 3,
    }
    if anchor_corner not in corner_index:
        raise ValueError(f"Unsupported anchor corner: {anchor_corner}")
    return corners[corner_index[anchor_corner]]


def yaw_rotation(yaw_deg):
    yaw = math.radians(yaw_deg)
    return np.array(
        [
            [math.cos(yaw), -math.sin(yaw), 0.0],
            [math.sin(yaw), math.cos(yaw), 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def marker_world_corners_from_center(center_mm, size_mm, yaw_deg):
    rotation = yaw_rotation(yaw_deg)
    return marker_local_corners(size_mm) @ rotation.T + np.array(center_mm, dtype=np.float64)


def marker_world_corners_from_anchor(anchor_mm, size_mm, yaw_deg, anchor_corner):
    rotation = yaw_rotation(yaw_deg)
    center = np.array(anchor_mm, dtype=np.float64) - rotation @ marker_anchor_offset(size_mm, anchor_corner)
    return marker_world_corners_from_center(center, size_mm, yaw_deg)


def create_marker_bitmap(dictionary_name, marker_id, marker_px):
    dictionary = get_aruco_dict(dictionary_name)
    if hasattr(cv2.aruco, "generateImageMarker"):
        return cv2.aruco.generateImageMarker(dictionary, marker_id, marker_px)
    return cv2.aruco.drawMarker(dictionary, marker_id, marker_px)


def marker_panel_anchor_offset(marker_px, border_px, anchor_corner):
    corner_offset = {
        "top_left": (border_px, border_px),
        "top_right": (border_px + marker_px, border_px),
        "bottom_right": (border_px + marker_px, border_px + marker_px),
        "bottom_left": (border_px, border_px + marker_px),
    }
    if anchor_corner not in corner_offset:
        raise ValueError(f"Unsupported anchor corner: {anchor_corner}")
    return np.array(corner_offset[anchor_corner], dtype=np.float64)


def render_ground_field_image(
    dictionary_name,
    placements,
    width_mm,
    height_mm,
    cell_x_mm,  # 升级：显式传入 X 单元格尺寸
    cell_y_mm,  # 升级：显式传入 Y 单元格尺寸
    marker_size_mm,
    canvas_px,
    show_markers=False,
):
    margin_mm = marker_size_mm
    canvas_width_mm = width_mm + margin_mm * 2.0
    canvas_height_mm = height_mm + margin_mm * 2.0
    scale = canvas_px / max(canvas_width_mm, canvas_height_mm)
    
    marker_px = max(1, int(round(marker_size_mm * scale)))
    panel_border_px = max(12, marker_px // 8)
    panel_label_px = max(28, marker_px // 4)
    panel_extent_px = marker_px + panel_border_px * 2 + panel_label_px
    margin_px = panel_extent_px
    
    canvas_w = max(1, int(round(width_mm * scale)) + margin_px * 2)
    canvas_h = max(1, int(round(height_mm * scale)) + margin_px * 2)
    canvas = np.full((canvas_h, canvas_w, 3), 255, dtype=np.uint8)

    grid_color = (220, 220, 220)
    border_color = (180, 180, 180)

    def world_to_canvas_y(y_mm):
        return margin_px + int(round((height_mm - y_mm) * scale))

    # === 修复：使用各自的 cell 尺寸来绘制长方形网格 ===
    # 绘制垂直线（基于 cell_x_mm 步进）
    for col in range(int(round(width_mm / cell_x_mm)) + 1):
        x = margin_px + int(round(col * cell_x_mm * scale))
        cv2.line(canvas, (x, 0), (x, canvas_h - 1), grid_color, 1, cv2.LINE_AA)
        
    # 绘制水平线（基于 cell_y_mm 步进）
    for row in range(int(round(height_mm / cell_y_mm)) + 1):
        y = world_to_canvas_y(row * cell_y_mm)
        cv2.line(canvas, (0, y), (canvas_w - 1, y), grid_color, 1, cv2.LINE_AA)

    cv2.rectangle(
        canvas,
        (margin_px, margin_px),
        (margin_px + int(round(width_mm * scale)) - 1, margin_px + int(round(height_mm * scale)) - 1),
        border_color,
        2,
        cv2.LINE_AA,
    )

    if show_markers:
        for item in placements:
            label = f"MARKER ID {item['id']}"
            marker, border_px = create_marker_panel(dictionary_name, item["id"], marker_px, label, border_px=10)
            if len(marker.shape) == 2:
                marker = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
            anchor = np.asarray(item["anchor_mm"], dtype=np.float64)
            offset = marker_panel_anchor_offset(marker_px, border_px, item["anchor_corner"])
            top_left_x = margin_px + int(round(anchor[0] * scale)) - int(offset[0])
            top_left_y = world_to_canvas_y(anchor[1]) - int(offset[1])
            bottom_right_x = top_left_x + marker.shape[1]
            bottom_right_y = top_left_y + marker.shape[0]
            if top_left_x < 0 or top_left_y < 0 or bottom_right_x > canvas_w or bottom_right_y > canvas_h:
                raise RuntimeError(f"Marker {item['id']} does not fit inside the field image.")
            canvas[top_left_y:bottom_right_y, top_left_x:bottom_right_x] = marker

    return canvas

def save_ground_marker_pngs(dictionary_name, placements, out_dir, marker_px, page_px):
    for item in placements:
        marker = create_ground_marker_image(
            dictionary_name,
            item["id"],
            marker_px,
            page_px,
            f"ID {item['id']}",
        )
        cv2.imwrite(str(out_dir / f"id_{item['id']:03d}.png"), marker)


def create_marker_panel(dictionary_name, marker_id, marker_px, label, border_px=None):
    marker = create_marker_bitmap(dictionary_name, marker_id, marker_px)
    if border_px is None:
        border_px = max(16, marker_px // 6)
    
    label_height_px = max(40, marker_px // 3)
    page_w = marker_px + border_px * 2
    page_h = marker_px + border_px * 2 + label_height_px
    
    page = np.full((page_h, page_w), 255, dtype=np.uint8)
    page[border_px : border_px + marker_px, border_px : border_px + marker_px] = marker

    font_scale = max(0.5, marker_px / 110.0)
    thickness = max(2, int(marker_px / 200))
    if thickness < 1:
        thickness = 1
    
    available_width = page_w - border_px * 2
    text_size, baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
    
    if text_size[0] > available_width and text_size[0] > 0:
        font_scale *= (available_width / text_size[0]) * 0.95
        text_size, baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
    
    text_x = (page_w - text_size[0]) // 2
    text_y = border_px + marker_px + text_size[1] + 12
    
    if text_y + border_px > page_h:
        new_page_h = text_y + border_px + baseline + 4 
        new_page = np.full((new_page_h, page_w), 255, dtype=np.uint8)
        new_page[:page_h, :page_w] = page
        page = new_page
    
    cv2.putText(
        page, label, (text_x, text_y),
        cv2.FONT_HERSHEY_SIMPLEX,
        font_scale, 0, thickness, cv2.LINE_AA,
    )
    return page, border_px


def create_ground_marker_image(dictionary_name, marker_id, marker_px, page_px, label):
    marker = create_marker_bitmap(dictionary_name, marker_id, marker_px)
    page = np.full((page_px, page_px), 255, dtype=np.uint8)
    offset = (page_px - marker_px) // 2
    page[offset : offset + marker_px, offset : offset + marker_px] = marker
    
    cv2.putText(
        page,
        label,
        (50, page_px - 50),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        0,
        3,
        cv2.LINE_AA,
    )
    return page


def make_ground(args):
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    cell_x = args.cell_x_mm
    cell_y = args.cell_y_mm
    
    width_mm = args.cols * cell_x
    height_mm = args.rows * cell_y
    
    # 边界物理外轮廓内缩一个单元格
    inner_x_min = cell_x
    inner_x_max = width_mm - cell_x
    inner_y_min = cell_y
    inner_y_max = height_mm - cell_y

    if inner_x_max <= inner_x_min or inner_y_max <= inner_y_min:
        raise ValueError(f"Grid columns ({args.cols}) and rows ({args.rows}) are too small to offset inward.")

    # === 修复核心：通过计算格数索引（Index）精准定位格点 ===
    # 找到 X 方向和 Y 方向最接近正中间的那条“格线”索引
    mid_col_idx = args.cols // 2
    mid_row_idx = args.rows // 2

    # 根据格线索引，计算出真正落在网格顶点上的物理毫米坐标
    grid_mid_x = mid_col_idx * cell_x
    grid_mid_y = mid_row_idx * cell_y

    placements = [
        {"id": args.start_id + 0, "name": "origin", "anchor_mm": [inner_x_min, inner_y_min, 0.0], "anchor_corner": args.anchor_corner, "yaw_deg": 0.0},
        {"id": args.start_id + 1, "name": "x_axis", "anchor_mm": [inner_x_max, inner_y_min, 0.0], "anchor_corner": args.anchor_corner, "yaw_deg": 0.0},
        {"id": args.start_id + 2, "name": "y_axis", "anchor_mm": [inner_x_min, inner_y_max, 0.0], "anchor_corner": args.anchor_corner, "yaw_deg": 0.0},
        {"id": args.start_id + 3, "name": "xy_corner", "anchor_mm": [inner_x_max, inner_y_max, 0.0], "anchor_corner": args.anchor_corner, "yaw_deg": 0.0},
    ]

    if args.add_midpoints:
        placements.extend([
            # 底部中点：X 落在完美的格线上，Y 处于内缩下边界线
            {"id": args.start_id + 4, "name": "bottom_mid", "anchor_mm": [grid_mid_x, inner_y_min, 0.0], "anchor_corner": args.anchor_corner, "yaw_deg": 0.0},
            # 顶部中点：X 落在完美的格线上，Y 处于内缩上边界线
            {"id": args.start_id + 5, "name": "top_mid", "anchor_mm": [grid_mid_x, inner_y_max, 0.0], "anchor_corner": args.anchor_corner, "yaw_deg": 0.0},
            # 左侧中点：X 处于内缩左边界线，Y 落在完美的格线上
            {"id": args.start_id + 6, "name": "left_mid", "anchor_mm": [inner_x_min, grid_mid_y, 0.0], "anchor_corner": args.anchor_corner, "yaw_deg": 0.0},
            # 右侧中点：X 处于内缩右边界线，Y 落在完美的格线上
            {"id": args.start_id + 7, "name": "right_mid", "anchor_mm": [inner_x_max, grid_mid_y, 0.0], "anchor_corner": args.anchor_corner, "yaw_deg": 0.0},
        ])

    field_no_labels = render_ground_field_image(
        args.dictionary, placements, width_mm, height_mm, cell_x, cell_y, args.marker_size_mm, args.page_px, show_markers=False
    )
    field_with_labels = render_ground_field_image(
        args.dictionary, placements, width_mm, height_mm, cell_x, cell_y, args.marker_size_mm, args.page_px, show_markers=True
    )
    
    field_no_labels_path = out_dir / "field_no_labels.png"
    field_path = out_dir / "field_with_labels.png"
    cv2.imwrite(str(field_no_labels_path), field_no_labels)
    cv2.imwrite(str(field_path), field_with_labels)
    save_ground_marker_pngs(args.dictionary, placements, out_dir, int(args.page_px * 0.72), args.page_px)

    config = {
        "dictionary": args.dictionary,
        "cell_x_mm": cell_x,
        "cell_y_mm": cell_y,
        "cell_mm": cell_x,
        "cols": args.cols,
        "rows": args.rows,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "marker_size_mm": args.marker_size_mm,
        "ground_anchor_corner": args.anchor_corner,
        "ground_markers": placements,
    }
    config_path = out_dir / "config_markers.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"[{args.system_name.upper()} SYSTEM] Configuration saved to: {out_dir.resolve()}")

def make_top(args):
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    marker_px = int(args.page_px * 0.72)
    ids = []
    for marker_id in range(args.start_id, args.start_id + args.count):
        image, _border_px = create_marker_panel(
            args.dictionary,
            marker_id,
            marker_px,
            f"TOP ID {marker_id}",
        )
        cv2.imwrite(str(out_dir / f"top_id_{marker_id:03d}.png"), image)
        ids.append(marker_id)
    manifest = {
        "dictionary": args.dictionary,
        "marker_size_mm": args.marker_size_mm,
        "top_marker_ids": ids,
    }
    (out_dir / "top_markers.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Saved top markers to: {out_dir.resolve()}")


def solve_extrinsic(args):
    config = json.loads(Path(args.ground_config).read_text(encoding="utf-8"))
    camera_matrix, dist_coeffs = load_intrinsics(args.intrinsics)
    image = cv2.imread(args.image)
    if image is None:
        raise RuntimeError(f"Could not read image: {args.image}")
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detect_markers(gray, config["dictionary"])
    if ids is None:
        raise RuntimeError("No ArUco markers detected.")

    id_to_corners = {int(marker_id[0]): corner.reshape(4, 2) for marker_id, corner in zip(ids, corners)}
    object_points = []
    image_points = []
    used_ids = []
    for marker in config["ground_markers"]:
        marker_id = int(marker["id"])
        if marker_id not in id_to_corners:
            continue
        if "anchor_mm" in marker:
            world_corners = marker_world_corners_from_anchor(
                marker["anchor_mm"],
                config["marker_size_mm"],
                marker.get("yaw_deg", 0.0),
                config.get("ground_anchor_corner", "top_right"),
            )
        else:
            world_corners = marker_world_corners_from_center(
                marker["center_mm"],
                config["marker_size_mm"],
                marker.get("yaw_deg", 0.0),
            )
        object_points.extend(world_corners.tolist())
        image_points.extend(id_to_corners[marker_id].tolist())
        used_ids.append(marker_id)

    if len(used_ids) < args.min_markers:
        raise RuntimeError(f"Only {len(used_ids)} calibration markers detected. Need at least {args.min_markers}.")

    ok, rvec, tvec = cv2.solvePnP(
        np.asarray(object_points, dtype=np.float64),
        np.asarray(image_points, dtype=np.float64),
        camera_matrix,
        dist_coeffs,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not ok:
        raise RuntimeError("solvePnP failed.")

    projected, _ = cv2.projectPoints(
        np.asarray(object_points, dtype=np.float64), rvec, tvec, camera_matrix, dist_coeffs
    )
    error = np.linalg.norm(projected.reshape(-1, 2) - np.asarray(image_points), axis=1)
    rotation = np.asarray(rodrigues_to_list(rvec), dtype=np.float64)
    cam_to_world_r, cam_to_world_t = invert_transform(rotation, tvec)

    result = {
        "camera_name": args.camera_name,
        "intrinsics": str(Path(args.intrinsics).resolve()),
        "ground_config": str(Path(args.ground_config).resolve()),
        "image": str(Path(args.image).resolve()),
        "used_ground_ids": used_ids,
        "rms_reprojection_error_px": float(np.sqrt(np.mean(error**2))),
        "world_to_camera": {
            "rotation": rotation.tolist(),
            "translation_mm": np.asarray(tvec).reshape(3).tolist(),
        },
        "camera_to_world": {
            "rotation": cam_to_world_r.tolist(),
            "translation_mm": cam_to_world_t.reshape(3).tolist(),
        },
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"Saved camera extrinsic: {out.resolve()} | RMS Error: {result['rms_reprojection_error_px']:.3f} px")


def estimate_top_centers(image, dictionary_name, camera_matrix, dist_coeffs, marker_size_mm):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detect_markers(gray, dictionary_name)
    if ids is None:
        return []
    marker_size = float(marker_size_mm)
    centers = []
    object_points = marker_local_corners(marker_size)
    for marker_id, marker_corners in zip(ids.reshape(-1), corners):
        ok, rvec, tvec = cv2.solvePnP(
            object_points,
            marker_corners.reshape(4, 2).astype(np.float64),
            camera_matrix,
            dist_coeffs,
            flags=cv2.SOLVEPNP_IPPE_SQUARE,
        )
        if ok:
            centers.append({
                "id": int(marker_id), 
                "camera_xyz_mm": np.asarray(tvec).reshape(3),
                "rvec": rvec
            })
    return centers


def build_grid_from_centers(centers, ground_config, rotation_cw, translation_cw, block_height_mm):
    grid = np.zeros((ground_config["rows"], ground_config["cols"]), dtype=np.int32)
    observations = []

    tolerance_ratio = 0.4 
    margin = block_height_mm * tolerance_ratio

    for center in centers:
        cam_xyz = center["camera_xyz_mm"].reshape(3, 1)
        world_xyz = rotation_cw @ cam_xyz + translation_cw
        x, y, z = world_xyz.reshape(3).tolist()
        
        col = int(math.floor(x / ground_config["cell_x_mm"]))
        row = int(math.floor(y / ground_config["cell_y_mm"]))
        
        estimated_level = z / block_height_mm
        base_level = int(math.floor(estimated_level))
        remainder = estimated_level - base_level
        
        if remainder > (1.0 - tolerance_ratio):
            level = base_level + 1
        elif remainder < tolerance_ratio:
            level = base_level
        else:
            level = int(round(estimated_level))
            
        if level < 0 and z >= -margin:
            level = 0

        # === 计算朝向信息 ===
        orient_str = "0,0"
        if "rvec" in center:
            R_cm, _ = cv2.Rodrigues(center["rvec"])
            R_wm = rotation_cw @ R_cm
            local_up_in_world = -R_wm[:, 1] 
            vx, vy = local_up_in_world[0], local_up_in_world[1]
            if abs(vx) > abs(vy):
                orient_str = "1,0" if vx > 0 else "-1,0"
            else:
                orient_str = "0,1" if vy > 0 else "0,-1"

        if 0 <= row < ground_config["rows"] and 0 <= col < ground_config["cols"] and level >= 0:
            if level >= grid[row, col]:
                grid[row, col] = level
            
        # === 核心改动：在最终生成的 JSON 数据结构里融入所有相关元数据 ===
        observations.append(
            {
                "id": int(center["id"]),              # 明确标记 ID
                "center_x_mm": x,
                "center_y_mm": y,
                "center_z_mm": z,
                "row": row,
                "col": col,
                "level": level,
                "orientation": orient_str             # 朝向元数据注入
            }
        )

    return grid, observations

def detect_top(args):
    ground_config = json.loads(Path(args.ground_config).read_text(encoding="utf-8"))
    camera_matrix, dist_coeffs = load_intrinsics(args.intrinsics)
    extrinsic = json.loads(Path(args.extrinsic).read_text(encoding="utf-8"))
    rotation_wc = np.asarray(extrinsic["world_to_camera"]["rotation"], dtype=np.float64)
    translation_wc = np.asarray(extrinsic["world_to_camera"]["translation_mm"], dtype=np.float64).reshape(3, 1)
    rotation_cw, translation_cw = invert_transform(rotation_wc, translation_wc)

    image = cv2.imread(args.image)
    if image is None:
        raise RuntimeError(f"Could not read image: {args.image}")

    centers = estimate_top_centers(
        image,
        ground_config["dictionary"],
        camera_matrix,
        dist_coeffs,
        args.top_marker_size_mm,
    )
    
    # 接收两个返回值
    grid, observations = build_grid_from_centers(
        centers,
        ground_config,
        rotation_cw,
        translation_cw,
        args.block_height_mm,
    )

    out_csv = Path(args.output_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerows(grid.tolist())

    out_obs = Path(args.output_observations)
    out_obs.write_text(json.dumps(observations, indent=2), encoding="utf-8")
    print(f"Saved grid CSV: {out_csv.resolve()}")
    print(f"Saved detailed observations with metadata: {out_obs.resolve()}")


def live_top(args):
    try:
        import pyzed.sl as sl
    except ImportError as exc:
        raise RuntimeError("pyzed is not installed or ZED SDK Python API is unavailable.") from exc

    ground_config = json.loads(Path(args.ground_config).read_text(encoding="utf-8"))
    camera_configs = load_live_camera_configs(args)
    live_cameras = []

    for config in camera_configs:
        camera_matrix, dist_coeffs = load_intrinsics(config["intrinsics"])
        rotation_cw, translation_cw = camera_world_transform_from_extrinsic(config["extrinsic"])
        zed = open_zed_camera(sl, config["serial_number"], args.resolution, args.fps)
        live_cameras.append(
            {
                "name": config["name"],
                "serial_number": config["serial_number"],
                "intrinsics": camera_matrix,
                "dist_coeffs": dist_coeffs,
                "rotation_cw": rotation_cw,
                "translation_cw": translation_cw,
                "zed": zed,
                "runtime": sl.RuntimeParameters(),
                "image": sl.Mat(),
            }
        )

    out_csv = Path(args.output_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_orient_csv = Path(args.output_orient_csv)
    out_orient_csv.parent.mkdir(parents=True, exist_ok=True)
    out_json = Path(args.output_observations)
    out_json.parent.mkdir(parents=True, exist_ok=True)

    last_write = 0.0
    preview_windows = set()

    # 在图像窗口名中区分系统标识，防止两套系统共用一屏时画面覆盖
    sys_tag = args.system_name.lower()

    print(f"[{args.system_name.upper()} RUNNING] Press q/ESC in preview window to stop.")
    try:
        while True:
            merged_grid = np.zeros((ground_config["rows"], ground_config["cols"]), dtype=np.int32)
            merged_orient = np.full((ground_config["rows"], ground_config["cols"]), "0,0", dtype=object)
            merged_observations = []
            marker_counts = []
            merged_id = np.full((ground_config["rows"], ground_config["cols"]), -1, dtype=np.int32)

            for camera in live_cameras:
                ok = camera["zed"].grab(camera["runtime"]) == sl.ERROR_CODE.SUCCESS
                if not ok:
                    marker_counts.append(f"{camera['name']}:0")
                    continue

                camera["zed"].retrieve_image(camera["image"], sl.VIEW.LEFT)
                frame = cv2.cvtColor(camera["image"].get_data(), cv2.COLOR_BGRA2BGR)
                centers = estimate_top_centers(
                    frame,
                    ground_config["dictionary"],
                    camera["intrinsics"],
                    camera["dist_coeffs"],
                    args.top_marker_size_mm,
                )
                
                gray_preview = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                preview_corners, preview_ids, _ = detect_markers(gray_preview, ground_config["dictionary"])
                if preview_ids is not None:
                    cv2.aruco.drawDetectedMarkers(frame, preview_corners, preview_ids)

                grid, observations = build_grid_from_centers(
                    centers,
                    ground_config,
                    camera["rotation_cw"],
                    camera["translation_cw"],
                    args.block_height_mm,
                )
                
                for r in range(ground_config["rows"]):
                    for c in range(ground_config["cols"]):
                        if grid[r, c] >= merged_grid[r, c] and grid[r, c] > 0:
                            merged_grid[r, c] = grid[r, c]

                marker_counts.append(f"{camera['name']}:{len(centers)}")

                for obs in observations:
                    item = dict(obs)
                    item["source"] = camera["name"]
                    item["serial_number"] = camera["serial_number"]
                    merged_observations.append(item)

                cv2.putText(
                    frame,
                    f"[{args.system_name.upper()}] {camera['name']} | markers: {len(centers)}",
                    (24, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )
                window_name = f"{camera['name']} top ({sys_tag})"
                if window_name not in preview_windows:
                    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
                    preview_windows.add(window_name)
                preview_frame, (display_width, display_height) = resize_preview_for_display(frame)
                cv2.resizeWindow(window_name, display_width, display_height)
                cv2.imshow(window_name, preview_frame)

            if time.monotonic() - last_write >= args.update_interval_sec:
                with out_csv.open("w", newline="", encoding="utf-8-sig") as handle:
                    writer = csv.writer(handle)
                    writer.writerows(merged_grid.tolist())

                out_json.write_text(json.dumps(merged_observations, indent=2), encoding="utf-8")
                last_write = time.monotonic()

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
    finally:
        cv2.destroyAllWindows()
        for camera in live_cameras:
            camera["zed"].close()


def open_zed_camera(sl, serial_number, resolution, fps):
    zed = sl.Camera()
    init = sl.InitParameters()
    init.camera_resolution = getattr(sl.RESOLUTION, resolution)
    init.camera_fps = fps
    init.coordinate_units = sl.UNIT.METER
    init.set_from_serial_number(serial_number)
    status = zed.open(init)
    if status != sl.ERROR_CODE.SUCCESS:
        raise RuntimeError(f"Could not open ZED camera {serial_number}: {status}")
    return zed


def camera_world_transform_from_extrinsic(path):
    extrinsic = json.loads(Path(path).read_text(encoding="utf-8"))
    return invert_transform(
        np.asarray(extrinsic["world_to_camera"]["rotation"], dtype=np.float64),
        np.asarray(extrinsic["world_to_camera"]["translation_mm"], dtype=np.float64),
    )


def live_camera_config_from_item(item, index):
    name = item.get("name") or item.get("camera_name") or f"camera_{index + 1}"
    serial_value = item.get("serial_number", item.get("camera", item.get("serial")))
    if serial_value is None:
        raise RuntimeError(f"Live camera config item {index} is missing camera/serial_number.")
    return {
        "name": name,
        "serial_number": resolve_camera_serial_number(serial_value),
        "intrinsics": item["intrinsics"],
        "extrinsic": item["extrinsic"],
    }


def load_live_camera_configs(args):
    if args.camera_config is not None:
        data = json.loads(Path(args.camera_config).read_text(encoding="utf-8"))
        items = data.get("cameras", data) if isinstance(data, dict) else data
        if not isinstance(items, list) or not items:
            raise RuntimeError("camera-config must contain a non-empty camera list.")
        return [live_camera_config_from_item(item, index) for index, item in enumerate(items)]

    required_pairs = [
        ("--camera-a", args.camera_a_serial_number),
        ("--camera-b", args.camera_b_serial_number),
        ("--camera-a-intrinsics", args.camera_a_intrinsics),
        ("--camera-b-intrinsics", args.camera_b_intrinsics),
        ("--camera-a-extrinsic", args.camera_a_extrinsic),
        ("--camera-b-extrinsic", args.camera_b_extrinsic),
    ]
    missing = [name for name, value in required_pairs if value is None]
    if missing:
        raise RuntimeError(f"Missing camera configuration parameters: {', '.join(missing)}")
    return [
        {
            "name": "camera_a",
            "serial_number": args.camera_a_serial_number,
            "intrinsics": args.camera_a_intrinsics,
            "extrinsic": args.camera_a_extrinsic,
        },
        {
            "name": "camera_b",
            "serial_number": args.camera_b_serial_number,
            "intrinsics": args.camera_b_intrinsics,
            "extrinsic": args.camera_b_extrinsic,
        },
    ]


def merge_observations(args):
    ground_config = json.loads(Path(args.ground_config).read_text(encoding="utf-8"))
    grid = np.zeros((ground_config["rows"], ground_config["cols"]), dtype=np.int32)
    merged = []

    for path in args.observations:
        observations = json.loads(Path(path).read_text(encoding="utf-8"))
        for obs in observations:
            row = int(obs["row"])
            col = int(obs["col"])
            level = int(obs["level"])
            if 0 <= row < ground_config["rows"] and 0 <= col < ground_config["cols"] and level >= 0:
                grid[row, col] = max(grid[row, col], level)
                item = dict(obs)
                item["source"] = str(Path(path).resolve())
                merged.append(item)

    out_csv = Path(args.output_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.writer(handle)
        writer.writerows(grid.tolist())

    out_json = Path(args.output_json)
    out_json.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    print(f"Saved merged grid CSV: {out_csv.resolve()}")


def build_parser():
    formatter = argparse.ArgumentDefaultsHelpFormatter
    parser = argparse.ArgumentParser(
        description="ArUco grid digital-twin helper (Multi-System Edition).",
        formatter_class=formatter,
    )
    
    parser.add_argument("--system-name", default="desktop", choices=["desktop", "ground"], help="System namespace identifier.")
    sub = parser.add_subparsers(dest="command", required=True)

    make_ground_cmd = sub.add_parser("make-ground", formatter_class=formatter)
    make_ground_cmd.add_argument("--output-dir", default="markers/desktop")
    make_ground_cmd.add_argument("--dictionary", default="DICT_5X5_100")
    make_ground_cmd.add_argument("--cols", type=int, default=35, help="Grid columns (X).")
    make_ground_cmd.add_argument("--rows", type=int, default=17, help="Grid rows (Y).")
    
    # === 升级：解耦 X 和 Y 方向的单元格尺寸 ===
    make_ground_cmd.add_argument("--cell-x-mm", type=float, default=40.0, help="Grid cell width (X) in mm.")
    make_ground_cmd.add_argument("--cell-y-mm", type=float, default=60.0, help="Grid cell height (Y) in mm.")
    make_ground_cmd.add_argument("--cell-mm", type=float, default=40.0, help="Legacy single cell-mm.")
    
    make_ground_cmd.add_argument("--marker-size-mm", type=float, default=30.0, help="Physical marker size.")
    make_ground_cmd.add_argument("--anchor-corner", default="top_right", choices=["top_left", "top_right", "bottom_right", "bottom_left"])
    make_ground_cmd.add_argument("--start-id", type=int, default=0)
    make_ground_cmd.add_argument("--page-px", type=int, default=4000)
    make_ground_cmd.add_argument("--add-midpoints", action="store_true")
    make_ground_cmd.set_defaults(func=make_ground)

    make_top_cmd = sub.add_parser("make-top", formatter_class=formatter)
    make_top_cmd.add_argument("--output-dir", default="markers/top")
    make_top_cmd.add_argument("--dictionary", default="DICT_5X5_100")
    make_top_cmd.add_argument("--marker-size-mm", type=float, default=30.0)
    make_top_cmd.add_argument("--start-id", type=int, default=20)
    make_top_cmd.add_argument("--count", type=int, required=True)
    make_top_cmd.add_argument("--page-px", type=int, default=1200)
    make_top_cmd.set_defaults(func=make_top)

    solve_cmd = sub.add_parser("solve-extrinsic", formatter_class=formatter)
    solve_cmd.add_argument("--image", required=True)
    solve_cmd.add_argument("--intrinsics", required=True)
    solve_cmd.add_argument("--ground-config", default="markers/desktop/config_markers.json")
    solve_cmd.add_argument("--camera-name", required=True)
    solve_cmd.add_argument("--output", required=True)
    solve_cmd.add_argument("--min-markers", type=int, default=4)
    solve_cmd.set_defaults(func=solve_extrinsic)

    detect_cmd = sub.add_parser("detect-top", formatter_class=formatter)
    detect_cmd.add_argument("--image", required=True)
    detect_cmd.add_argument("--intrinsics", required=True)
    detect_cmd.add_argument("--extrinsic", required=True)
    detect_cmd.add_argument("--ground-config", default="markers/desktop/config_markers.json")
    detect_cmd.add_argument("--top-marker-size-mm", type=float, default=30.0)
    detect_cmd.add_argument("--block-height-mm", type=float, default=40.0)
    detect_cmd.add_argument("--output-csv", default="outputs/desktop_grid_heights.csv")
    detect_cmd.add_argument("--output-orient-csv", default="outputs/desktop_grid_orientations.csv")
    detect_cmd.add_argument("--output-observations", default="outputs/desktop_top_observations.json")
    detect_cmd.add_argument("--output-id-csv", default="outputs/desktop_grid_ids.csv", help="Output grid-ID CSV path.")
    detect_cmd.set_defaults(func=detect_top)
    

    merge_cmd = sub.add_parser("merge-observations", formatter_class=formatter)
    merge_cmd.add_argument("--ground-config", default="markers/desktop/config_markers.json")
    merge_cmd.add_argument("--observations", nargs="+", required=True)
    merge_cmd.add_argument("--output-csv", default="outputs/desktop_grid_heights_merged.csv")
    merge_cmd.add_argument("--output-json", default="outputs/desktop_top_observations_merged.json")
    merge_cmd.set_defaults(func=merge_observations)

    live_cmd = sub.add_parser("live-top", formatter_class=formatter)
    live_cmd.add_argument("--ground-config", default="markers/desktop/config_markers.json")
    live_cmd.add_argument("--camera-config", help="JSON containing path config.")
    live_cmd.add_argument("--camera-a", "--camera-a-serial-number", dest="camera_a_serial_number", type=resolve_camera_serial_number)
    live_cmd.add_argument("--camera-b", "--camera-b-serial-number", dest="camera_b_serial_number", type=resolve_camera_serial_number)
    live_cmd.add_argument("--camera-a-intrinsics")
    live_cmd.add_argument("--camera-b-intrinsics")
    live_cmd.add_argument("--camera-a-extrinsic")
    live_cmd.add_argument("--camera-b-extrinsic")
    live_cmd.add_argument("--resolution", default="HD1080")
    live_cmd.add_argument("--fps", type=int, default=30)
    live_cmd.add_argument("--top-marker-size-mm", type=float, default=30.0)
    live_cmd.add_argument("--block-height-mm", type=float, default=40.0)
    live_cmd.add_argument("--output-csv", default="outputs/desktop_grid_heights_live.csv")
    live_cmd.add_argument("--output-orient-csv", default="outputs/desktop_grid_orientations_live.csv")
    live_cmd.add_argument("--output-observations", default="outputs/desktop_top_observations_live.json")
    live_cmd.add_argument("--update-interval-sec", type=float, default=0.5)
    live_cmd.add_argument("--output-id-csv", default="outputs/desktop_grid_ids_live.csv", help="Output live grid-ID CSV path.")
    live_cmd.set_defaults(func=live_top)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    
    # === 核心多流沙盒隔离逻辑 ===
    # 如果用户通过命令行明确指定了系统身份为 --system-name ground，自动完成路径的重路由重映射
    if args.system_name == "ground":
        if hasattr(args, "output_dir") and args.output_dir == "markers/desktop":
            args.output_dir = "markers/ground"
        if hasattr(args, "ground_config") and args.ground_config == "markers/desktop/config_markers.json":
            args.ground_config = "markers/ground/config_markers.json"
        if hasattr(args, "output_csv"):
            args.output_csv = args.output_csv.replace("desktop_", "ground_")
        if hasattr(args, "output_orient_csv"):
            args.output_orient_csv = args.output_orient_csv.replace("desktop_", "ground_")
        if hasattr(args, "output_observations"):
            args.output_observations = args.output_observations.replace("desktop_", "ground_")
        if hasattr(args, "output_json"):
            args.output_json = args.output_json.replace("desktop_", "ground_")
        if hasattr(args, "output_id_csv"):
            args.output_id_csv = args.output_id_csv.replace("desktop_", "ground_")

    try:
        args.func(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())