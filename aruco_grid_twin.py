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
    """
    Detect ArUco markers and refine their corners to sub-pixel accuracy when
    the installed OpenCV version supports it.

    The corner refinement is especially useful for calibration images, because
    solvePnP is sensitive to even a few pixels of corner error.
    """
    dictionary = get_aruco_dict(dictionary_name)
    params = cv2.aruco.DetectorParameters()

    if hasattr(cv2.aruco, "CORNER_REFINE_SUBPIX"):
        params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        if hasattr(params, "cornerRefinementWinSize"):
            params.cornerRefinementWinSize = 5
        if hasattr(params, "cornerRefinementMaxIterations"):
            params.cornerRefinementMaxIterations = 30
        if hasattr(params, "cornerRefinementMinAccuracy"):
            params.cornerRefinementMinAccuracy = 0.01

    if hasattr(cv2.aruco, "ArucoDetector"):
        detector = cv2.aruco.ArucoDetector(dictionary, params)
        corners, ids, rejected = detector.detectMarkers(gray)
    else:
        corners, ids, rejected = cv2.aruco.detectMarkers(
            gray,
            dictionary,
            parameters=params,
        )
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
    """
    Return the marker's four corners in its local plane.

    Global/world convention used by this script:
        X: increases to the right
        Y: increases downward
        Z: increases downward from the ground plane

    The order is identical to OpenCV ArUco detection output:
        top-left, top-right, bottom-right, bottom-left.

    This convention must agree with render_ground_field_image(), which maps a
    larger world Y to a lower image pixel Y. The previous implementation had
    the marker-local Y direction reversed, causing the modelled marker corners
    to disagree with the rendered/physical layout and potentially producing
    large reprojection residuals.
    """
    half = size_mm / 2.0
    return np.array(
        [
            [-half, -half, 0.0],  # top-left
            [ half, -half, 0.0],  # top-right
            [ half,  half, 0.0],  # bottom-right
            [-half,  half, 0.0],  # bottom-left
        ],
        dtype=np.float64,
    )


def marker_local_corners_ippe_square(size_mm):
    """
    Canonical square-marker object points required by OpenCV's
    SOLVEPNP_IPPE_SQUARE solver.

    Important: this is intentionally different from marker_local_corners().
    marker_local_corners() follows this project's *world/grid* convention
    (X right, Y down). IPPE_SQUARE, however, requires its documented local
    marker convention (X right, Y up) in the exact order:
    top-left, top-right, bottom-right, bottom-left.

    Keep this helper only for estimating an individual top-marker pose.
    """
    half = size_mm / 2.0
    return np.array(
        [
            [-half,  half, 0.0],  # top-left
            [ half,  half, 0.0],  # top-right
            [ half, -half, 0.0],  # bottom-right
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


# === 修改核心：调整画布渲染，使左上角为物理原点 (0,0) ===
def render_ground_field_image(
    dictionary_name,
    placements,
    x_slices,
    y_slices,
    marker_size_mm,
    canvas_px,
    show_markers=False,
):
    width_mm = x_slices[-1]
    height_mm = y_slices[-1]
    
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

    # 修改点：0点切换至左上角，物理 Y 的增长方向即为像素 Y 的增长方向，移除了 height_mm 反转
    def world_to_canvas_y(y_val_mm):
        return margin_px + int(round(y_val_mm * scale))

    # 动态绘制垂直格线
    for x_val in x_slices:
        x = margin_px + int(round(x_val * scale))
        cv2.line(canvas, (x, 0), (x, canvas_h - 1), grid_color, 1, cv2.LINE_AA)
        
    # 动态绘制水平格线
    for y_val in y_slices:
        y = world_to_canvas_y(y_val)
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
        # 统一使用带有白边和文字标注的 panel 创建函数
        marker_image, _ = create_marker_panel(
            dictionary_name,
            item["id"],
            marker_px,
            label=f"ID {item['id']}",
            border_px=max(20, marker_px // 6) # 预留出足够的白边
        )
        cv2.imwrite(str(out_dir / f"id_{item['id']:03d}.png"), marker_image)


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
    thickness = max(1, int(marker_px / 200))
    
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
        1,
        cv2.LINE_AA,
    )
    return page


def parse_non_uniform_layout(layout_path):
    with open(layout_path, "r", encoding="utf-8") as f:
        layout = json.load(f)
    
    cols = layout["width"]
    rows = layout["height"]
    
    col_widths = [0.0] * cols
    row_lengths = [0.0] * rows
    
    for cell in layout["cells"]:
        cx = cell["x"]
        cy = cell["y"]
        col_widths[cx] = float(cell["width"])
        row_lengths[cy] = float(cell["length"])
        
    x_slices = [0.0]
    for w in col_widths:
        x_slices.append(x_slices[-1] + w)
        
    y_slices = [0.0]
    for l in row_lengths:
        y_slices.append(y_slices[-1] + l)
        
    return cols, rows, x_slices, y_slices


def make_ground(args):
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.layout_json and Path(args.layout_json).exists():
        print(f"[{args.system_name.upper()}] Loading non-uniform grid layout: {args.layout_json}")
        cols, rows, x_slices, y_slices = parse_non_uniform_layout(args.layout_json)
        cell_x_legacy = (x_slices[1] - x_slices[0])
        cell_y_legacy = (y_slices[1] - y_slices[0])
    else:
        print(f"[{args.system_name.upper()}] Using uniform grid parameters (Cols: {args.cols}, Rows: {args.rows})")
        cols = args.cols
        rows = args.rows
        cell_x_legacy = args.cell_x_mm if args.cell_x_mm else args.cell_mm
        cell_y_legacy = args.cell_y_mm if args.cell_y_mm else args.cell_mm
        x_slices = [float(i * cell_x_legacy) for i in range(cols + 1)]
        y_slices = [float(i * cell_y_legacy) for i in range(rows + 1)]
    
    width_mm = x_slices[-1]
    height_mm = y_slices[-1]
    
    # === 修改核心：判断如果是桌面级系统，则向内部移动两个格子 ===
    if args.system_name.lower() == "desktop":
        # 确保网格大小足够容纳两圈的内缩
        if cols < 5 or rows < 5:
            raise ValueError("Grid shape is too small for a 2-cell inward offset desktop layout.")
        
        print(f"[{args.system_name.upper()}] Applying 2-cell inward offset for calibration markers.")
        inner_x_min = x_slices[4]
        inner_x_max = x_slices[-5]
        inner_y_min = y_slices[2]
        inner_y_max = y_slices[-4]
    else:
        # 其它系统（如 ground）保持原有的内缩 1 个格子
        inner_x_min = x_slices[1]
        inner_x_max = x_slices[-2]
        inner_y_min = y_slices[1]
        inner_y_max = y_slices[-2]

    if inner_x_max <= inner_x_min or inner_y_max <= inner_y_min:
        raise ValueError("Grid shape is too small to complete calibration layout calculation.")

    mid_col_idx = cols // 2
    mid_row_idx = rows // 2
    grid_mid_x = x_slices[mid_col_idx]
    grid_mid_y = y_slices[mid_row_idx]

    placements = [
        {"id": args.start_id + 0, "name": "origin", "anchor_mm": [inner_x_min, inner_y_min, 0.0], "anchor_corner": args.anchor_corner, "yaw_deg": 0.0},
        {"id": args.start_id + 1, "name": "x_axis", "anchor_mm": [inner_x_max, inner_y_min, 0.0], "anchor_corner": args.anchor_corner, "yaw_deg": 0.0},
        {"id": args.start_id + 2, "name": "y_axis", "anchor_mm": [inner_x_min, inner_y_max, 0.0], "anchor_corner": args.anchor_corner, "yaw_deg": 0.0},
        {"id": args.start_id + 3, "name": "xy_corner", "anchor_mm": [inner_x_max, inner_y_max, 0.0], "anchor_corner": args.anchor_corner, "yaw_deg": 0.0},
    ]

    if args.add_midpoints:
        placements.extend([
            {"id": args.start_id + 4, "name": "top_mid", "anchor_mm": [grid_mid_x, inner_y_min, 0.0], "anchor_corner": args.anchor_corner, "yaw_deg": 0.0},
            {"id": args.start_id + 5, "name": "bottom_mid", "anchor_mm": [grid_mid_x, inner_y_max, 0.0], "anchor_corner": args.anchor_corner, "yaw_deg": 0.0},
            {"id": args.start_id + 6, "name": "left_mid", "anchor_mm": [inner_x_min, grid_mid_y, 0.0], "anchor_corner": args.anchor_corner, "yaw_deg": 0.0},
            {"id": args.start_id + 7, "name": "right_mid", "anchor_mm": [inner_x_max, grid_mid_y, 0.0], "anchor_corner": args.anchor_corner, "yaw_deg": 0.0},
        ])

    field_no_labels = render_ground_field_image(
        args.dictionary, placements, x_slices, y_slices, args.marker_size_mm, args.page_px, show_markers=False
    )
    field_with_labels = render_ground_field_image(
        args.dictionary, placements, x_slices, y_slices, args.marker_size_mm, args.page_px, show_markers=True
    )
    
    cv2.imwrite(str(out_dir / "field_no_labels.png"), field_no_labels)
    cv2.imwrite(str(out_dir / "field_with_labels.png"), field_with_labels)
    save_ground_marker_pngs(args.dictionary, placements, out_dir, int(args.page_px * 0.72), args.page_px)

    config = {
        "dictionary": args.dictionary,
        "cols": cols,
        "rows": rows,
        "cell_x_mm": cell_x_legacy,
        "cell_y_mm": cell_y_legacy,
        "x_slices": x_slices,
        "y_slices": y_slices,
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
    """
    Estimate the camera extrinsic transform from known ground ArUco markers.

    In addition to the global RMS reprojection error, this version writes:
      - per-marker and per-corner reprojection errors;
      - a visual debug image where:
          green filled dot = detected corner,
          red ring = reprojected corner,
          yellow line = residual vector;
      - optional point-level RANSAC inlier information.

    By default, ordinary solvePnP is used so that layout/configuration errors
    are visible instead of being silently excluded. Use --use-ransac only
    after the physical/configuration setup has been checked.
    """
    require_opencv()

    config = json.loads(Path(args.ground_config).read_text(encoding="utf-8"))
    camera_matrix, dist_coeffs = load_intrinsics(args.intrinsics)

    image = cv2.imread(args.image)
    if image is None:
        raise RuntimeError(f"Could not read image: {args.image}")

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detect_markers(gray, config["dictionary"])
    if ids is None:
        raise RuntimeError("No ArUco markers detected.")

    detected_marker_ids = [int(marker_id) for marker_id in ids.reshape(-1)]
    id_to_corners = {
        int(marker_id[0]): corner.reshape(4, 2).astype(np.float64)
        for marker_id, corner in zip(ids, corners)
    }

    object_points = []
    image_points = []
    used_ids = []
    marker_point_ranges = {}

    for marker in config["ground_markers"]:
        marker_id = int(marker["id"])
        if marker_id not in id_to_corners:
            continue

        if "anchor_mm" in marker:
            world_corners = marker_world_corners_from_anchor(
                marker["anchor_mm"],
                config["marker_size_mm"],
                marker.get("yaw_deg", 0.0),
                marker.get(
                    "anchor_corner",
                    config.get("ground_anchor_corner", "top_right"),
                ),
            )
        else:
            world_corners = marker_world_corners_from_center(
                marker["center_mm"],
                config["marker_size_mm"],
                marker.get("yaw_deg", 0.0),
            )

        start = len(object_points)
        object_points.extend(world_corners.tolist())
        image_points.extend(id_to_corners[marker_id].tolist())
        marker_point_ranges[marker_id] = (start, start + 4)
        used_ids.append(marker_id)

    if len(used_ids) < args.min_markers:
        raise RuntimeError(
            f"Only {len(used_ids)} calibration markers detected. "
            f"Need at least {args.min_markers}. "
            f"Detected IDs: {detected_marker_ids}; used ground IDs: {used_ids}."
        )

    object_points_np = np.asarray(object_points, dtype=np.float64)
    image_points_np = np.asarray(image_points, dtype=np.float64)

    solver_name = "SOLVEPNP_ITERATIVE"
    inlier_indices = np.arange(len(object_points_np), dtype=np.int32)

    if args.use_ransac:
        solver_name = "SOLVEPNP_RANSAC_ITERATIVE"
        ok, rvec, tvec, inliers = cv2.solvePnPRansac(
            object_points_np,
            image_points_np,
            camera_matrix,
            dist_coeffs,
            iterationsCount=200,
            reprojectionError=args.ransac_reprojection_error,
            confidence=0.999,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not ok or inliers is None or len(inliers) < 6:
            raise RuntimeError(
                "solvePnPRansac failed or returned too few inlier points. "
                "Check intrinsics, marker layout, marker IDs, and image quality."
            )

        inlier_indices = inliers.reshape(-1).astype(np.int32)

        # Refine the RANSAC result using only the inlier corner correspondences.
        if hasattr(cv2, "solvePnPRefineLM"):
            rvec, tvec = cv2.solvePnPRefineLM(
                object_points_np[inlier_indices],
                image_points_np[inlier_indices],
                camera_matrix,
                dist_coeffs,
                rvec,
                tvec,
            )
    else:
        ok, rvec, tvec = cv2.solvePnP(
            object_points_np,
            image_points_np,
            camera_matrix,
            dist_coeffs,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )
        if not ok:
            raise RuntimeError("solvePnP failed.")

    projected, _ = cv2.projectPoints(
        object_points_np,
        rvec,
        tvec,
        camera_matrix,
        dist_coeffs,
    )
    projected_np = projected.reshape(-1, 2)

    residual_vectors_px = projected_np - image_points_np
    error_px = np.linalg.norm(residual_vectors_px, axis=1)

    per_marker_error = {}
    for marker_id in used_ids:
        start, end = marker_point_ranges[marker_id]
        marker_errors = error_px[start:end]
        marker_residual_vectors = residual_vectors_px[start:end]
        marker_inliers = np.isin(
            np.arange(start, end),
            inlier_indices,
        ).tolist()

        per_marker_error[str(marker_id)] = {
            "corner_errors_px": [float(value) for value in marker_errors],
            "corner_residual_vectors_px": [
                [float(vec[0]), float(vec[1])]
                for vec in marker_residual_vectors
            ],
            "mean_error_px": float(np.mean(marker_errors)),
            "max_error_px": float(np.max(marker_errors)),
            "rms_error_px": float(np.sqrt(np.mean(marker_errors ** 2))),
            "corner_is_ransac_inlier": marker_inliers,
        }

    rotation = np.asarray(rodrigues_to_list(rvec), dtype=np.float64)
    cam_to_world_r, cam_to_world_t = invert_transform(rotation, tvec)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    debug_path = (
        Path(args.debug_output)
        if args.debug_output
        else out.with_name(out.stem + "_reprojection_debug.png")
    )
    debug_path.parent.mkdir(parents=True, exist_ok=True)

    # Write a visual overlay for diagnosing systematic or per-marker errors.
    debug_image = image.copy()
    cv2.aruco.drawDetectedMarkers(debug_image, corners, ids)

    for marker_id in used_ids:
        start, end = marker_point_ranges[marker_id]

        for detected_pt, reproj_pt in zip(
            image_points_np[start:end],
            projected_np[start:end],
        ):
            detected_xy = tuple(np.round(detected_pt).astype(int))
            reproj_xy = tuple(np.round(reproj_pt).astype(int))

            # Green: detected ArUco corner. Red: PnP reprojection.
            cv2.circle(debug_image, detected_xy, 5, (0, 255, 0), -1)
            cv2.circle(debug_image, reproj_xy, 7, (0, 0, 255), 2)
            cv2.line(
                debug_image,
                detected_xy,
                reproj_xy,
                (0, 255, 255),
                1,
                cv2.LINE_AA,
            )

        marker_center = np.mean(image_points_np[start:end], axis=0)
        label_xy = tuple(np.round(marker_center).astype(int))
        marker_rms = per_marker_error[str(marker_id)]["rms_error_px"]
        marker_max = per_marker_error[str(marker_id)]["max_error_px"]

        cv2.putText(
            debug_image,
            f"ID {marker_id}: RMS {marker_rms:.2f}px, max {marker_max:.2f}px",
            (label_xy[0], max(25, label_xy[1] - 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (255, 0, 255),
            2,
            cv2.LINE_AA,
        )

    overall_rms_error_px = float(np.sqrt(np.mean(error_px ** 2)))
    cv2.putText(
        debug_image,
        f"Overall RMS: {overall_rms_error_px:.3f}px | {solver_name}",
        (20, 36),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.85,
        (0, 0, 255),
        2,
        cv2.LINE_AA,
    )
    cv2.imwrite(str(debug_path), debug_image)

    result = {
        "camera_name": args.camera_name,
        "intrinsics": str(Path(args.intrinsics).resolve()),
        "ground_config": str(Path(args.ground_config).resolve()),
        "image": str(Path(args.image).resolve()),
        "image_size_px": {
            "width": int(image.shape[1]),
            "height": int(image.shape[0]),
        },
        "detected_marker_ids": detected_marker_ids,
        "used_ground_ids": used_ids,
        "solver": solver_name,
        "ransac_enabled": bool(args.use_ransac),
        "ransac_reprojection_error_px": (
            float(args.ransac_reprojection_error) if args.use_ransac else None
        ),
        "ransac_inlier_point_indices": [
            int(index) for index in inlier_indices
        ],
        "ransac_inlier_point_count": int(len(inlier_indices)),
        "total_point_count": int(len(object_points_np)),
        "rms_reprojection_error_px": overall_rms_error_px,
        "max_reprojection_error_px": float(np.max(error_px)),
        "mean_reprojection_error_px": float(np.mean(error_px)),
        "per_marker_reprojection_error_px": per_marker_error,
        "reprojection_debug_image": str(debug_path.resolve()),
        "world_to_camera": {
            "rotation": rotation.tolist(),
            "translation_mm": np.asarray(tvec).reshape(3).tolist(),
        },
        "camera_to_world": {
            "rotation": cam_to_world_r.tolist(),
            "translation_mm": cam_to_world_t.reshape(3).tolist(),
        },
    }

    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"Detected ArUco IDs: {detected_marker_ids}")
    print(f"Used ground IDs: {used_ids}")
    for marker_id in used_ids:
        item = per_marker_error[str(marker_id)]
        print(
            f"  ID {marker_id}: "
            f"RMS={item['rms_error_px']:.3f}px, "
            f"mean={item['mean_error_px']:.3f}px, "
            f"max={item['max_error_px']:.3f}px"
        )
    print(
        f"Saved camera extrinsic: {out.resolve()} | "
        f"RMS Error: {overall_rms_error_px:.3f} px"
    )
    print(f"Saved reprojection debug image: {debug_path.resolve()}")


def estimate_top_centers(
    image,
    dictionary_name,
    camera_matrix,
    dist_coeffs,
    marker_size_mm,
    exclude_ids=None,
):
    """Estimate the 3D center of each visible top marker in camera coordinates.

    marker_local_corners() must NOT be used here: it follows the grid/world
    Y-down convention adopted for ground-layout modelling. OpenCV's specialized
    SOLVEPNP_IPPE_SQUARE solver requires the canonical marker-local Y-up
    coordinates supplied by marker_local_corners_ippe_square(). Mixing the two
    gives a low ground-calibration RMS but an invalid top-marker tvec, which
    then makes world/grid mapping appear completely wrong.
    """
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detect_markers(gray, dictionary_name)
    if ids is None:
        return []

    excluded = set() if exclude_ids is None else {int(value) for value in exclude_ids}
    marker_size = float(marker_size_mm)
    centers = []

    # Required canonical point order for cv2.SOLVEPNP_IPPE_SQUARE.
    object_points = marker_local_corners_ippe_square(marker_size)

    for marker_id, marker_corners in zip(ids.reshape(-1), corners):
        marker_id = int(marker_id)
        if marker_id in excluded:
            continue

        ok, rvec, tvec = cv2.solvePnP(
            object_points,
            marker_corners.reshape(4, 2).astype(np.float64),
            camera_matrix,
            dist_coeffs,
            flags=cv2.SOLVEPNP_IPPE_SQUARE,
        )
        if ok and float(tvec[2]) > 0.0:
            centers.append({
                "id": marker_id,
                "camera_xyz_mm": np.asarray(tvec, dtype=np.float64).reshape(3),
                "rvec": rvec,
            })

    return centers


def build_grid_from_centers(centers, ground_config, rotation_cw, translation_cw, block_height_mm):
    rows = ground_config["rows"]
    cols = ground_config["cols"]
    grid = np.zeros((rows, cols), dtype=np.int32)
    observations = []

    tolerance_ratio = 0.4 
    margin = block_height_mm * tolerance_ratio

    if "x_slices" in ground_config and "y_slices" in ground_config:
        x_slices = ground_config["x_slices"]
        y_slices = ground_config["y_slices"]
    else:
        cell_x = ground_config.get("cell_x_mm", ground_config.get("cell_mm", 40.0))
        cell_y = ground_config.get("cell_y_mm", ground_config.get("cell_mm", 40.0))
        x_slices = [float(i * cell_x) for i in range(cols + 1)]
        y_slices = [float(i * cell_y) for i in range(rows + 1)]

    for center in centers:
        cam_xyz = center["camera_xyz_mm"].reshape(3, 1)
        world_xyz = rotation_cw @ cam_xyz + translation_cw
        x, y, z = world_xyz.reshape(3).tolist()
        
        # === 修改点：因为世界坐标系 Z 轴朝下，所以物体实际高度应该为 -z ===
        actual_height_mm = -z 
        
        col = int(np.searchsorted(x_slices, x) - 1)
        row = int(np.searchsorted(y_slices, y) - 1)
        
        # 使用修正后的实际高度计算层数
        estimated_level = actual_height_mm / block_height_mm
        base_level = int(math.floor(estimated_level))
        remainder = estimated_level - base_level
        
        if remainder > (1.0 - tolerance_ratio):
            level = base_level + 1
        elif remainder < tolerance_ratio:
            level = base_level
        else:
            level = int(round(estimated_level))
            
        # 容错边界调整也使用 actual_height_mm
        if level < 0 and actual_height_mm >= -margin:
            level = 0

        # 计算朝向信息
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

        if 0 <= row < rows and 0 <= col < cols and level >= 0:
            if level >= grid[row, col]:
                grid[row, col] = level
            
        observations.append(
            {
                "id": int(center["id"]),
                "center_x_mm": x,
                "center_y_mm": y,
                "center_z_mm": actual_height_mm,  # 保存正的高度
                "row": row,
                "col": col,
                "level": level,
                "orientation": orient_str
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

    ground_marker_ids = {int(marker["id"]) for marker in ground_config["ground_markers"]}
    centers = estimate_top_centers(
        image,
        ground_config["dictionary"],
        camera_matrix,
        dist_coeffs,
        args.top_marker_size_mm,
        exclude_ids=ground_marker_ids,
    )
    
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
    out_json = Path(args.output_observations)
    out_json.parent.mkdir(parents=True, exist_ok=True)

    last_write = 0.0
    preview_windows = set()
    last_json_str = None
    sys_tag = args.system_name.lower()

    print(f"[{args.system_name.upper()} RUNNING] Press q/ESC in preview window to stop.")
    try:
        while True:
            merged_grid = np.zeros((ground_config["rows"], ground_config["cols"]), dtype=np.int32)
            merged_observations = []
            marker_counts = []

            for camera in live_cameras:
                ok = camera["zed"].grab(camera["runtime"]) == sl.ERROR_CODE.SUCCESS
                if not ok:
                    marker_counts.append(f"{camera['name']}:0")
                    continue

                camera["zed"].retrieve_image(camera["image"], sl.VIEW.LEFT)
                frame = cv2.cvtColor(camera["image"].get_data(), cv2.COLOR_BGRA2BGR)
                ground_marker_ids = {
                    int(marker["id"])
                    for marker in ground_config["ground_markers"]
                }
                centers = estimate_top_centers(
                    frame,
                    ground_config["dictionary"],
                    camera["intrinsics"],
                    camera["dist_coeffs"],
                    args.top_marker_size_mm,
                    exclude_ids=ground_marker_ids,
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
                current_json_str = json.dumps(merged_observations, indent=2)

                if current_json_str != last_json_str:
                    with out_csv.open("w", newline="", encoding="utf-8-sig") as handle:
                        writer = csv.writer(handle)
                        writer.writerows(merged_grid.tolist())

                    out_json.write_text(current_json_str, encoding="utf-8")
                    last_json_str = current_json_str
                    print(f"[{args.system_name.upper()}] Data updated. File rewritten.")
                
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
        description="ArUco grid digital-twin helper (Top-Left Origin Hybrid Edition).",
        formatter_class=formatter,
    )
    
    parser.add_argument("--system-name", default="desktop", choices=["desktop", "ground"], help="System namespace identifier.")
    sub = parser.add_subparsers(dest="command", required=True)

    make_ground_cmd = sub.add_parser("make-ground", formatter_class=formatter)
    make_ground_cmd.add_argument("--output-dir", default="markers/desktop")
    make_ground_cmd.add_argument("--dictionary", default="DICT_5X5_100")
    
    make_ground_cmd.add_argument("--cols", type=int, default=35, help="Grid columns (X) for uniform mode.")
    make_ground_cmd.add_argument("--rows", type=int, default=17, help="Grid rows (Y) for uniform mode.")
    make_ground_cmd.add_argument("--cell-x-mm", type=float, default=40.0, help="Grid cell width (X) in mm for uniform mode.")
    make_ground_cmd.add_argument("--cell-y-mm", type=float, default=60.0, help="Grid cell height (Y) in mm for uniform mode.")
    make_ground_cmd.add_argument("--cell-mm", type=float, default=40.0, help="Legacy single cell-mm.")
    
    make_ground_cmd.add_argument("--layout-json", default=None, help="Path to non-uniform grid json layout file (Overrides uniform params).")
    
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
    solve_cmd.add_argument(
        "--debug-output",
        default=None,
        help=(
            "Optional path for the reprojection diagnostic PNG. "
            "Defaults to <output_stem>_reprojection_debug.png."
        ),
    )
    solve_cmd.add_argument(
        "--use-ransac",
        action="store_true",
        help=(
            "Use solvePnPRansac and refine with its inlier corners. "
            "Keep disabled during initial diagnosis so layout errors remain visible."
        ),
    )
    solve_cmd.add_argument(
        "--ransac-reprojection-error",
        type=float,
        default=3.0,
        help="RANSAC inlier threshold in pixels; only used with --use-ransac.",
    )
    solve_cmd.set_defaults(func=solve_extrinsic)

    detect_cmd = sub.add_parser("detect-top", formatter_class=formatter)
    detect_cmd.add_argument("--image", required=True)
    detect_cmd.add_argument("--intrinsics", required=True)
    detect_cmd.add_argument("--extrinsic", required=True)
    detect_cmd.add_argument("--ground-config", default="markers/desktop/config_markers.json")
    detect_cmd.add_argument("--top-marker-size-mm", type=float, default=30.0)
    detect_cmd.add_argument("--block-height-mm", type=float, default=40.0)
    detect_cmd.add_argument("--output-csv", default="outputs/desktop_grid_heights.csv")
    detect_cmd.add_argument("--output-observations", default="outputs/desktop_top_observations.json")
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
    live_cmd.add_argument("--output-observations", default="outputs/desktop_top_observations_live.json")
    live_cmd.add_argument("--update-interval-sec", type=float, default=0.5)
    live_cmd.set_defaults(func=live_top)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    
    if args.system_name == "ground":
        if hasattr(args, "output_dir") and args.output_dir == "markers/desktop":
            args.output_dir = "markers/ground"
        if hasattr(args, "ground_config") and args.ground_config == "markers/desktop/config_markers.json":
            args.ground_config = "markers/ground/config_markers.json"
        if hasattr(args, "output_csv"):
            args.output_csv = args.output_csv.replace("desktop_", "ground_")
        if hasattr(args, "output_observations"):
            args.output_observations = args.output_observations.replace("desktop_", "ground_")
        if hasattr(args, "output_json"):
            args.output_json = args.output_json.replace("desktop_", "ground_")

    try:
        args.func(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())