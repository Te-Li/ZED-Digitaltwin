import argparse
import base64
import csv
import json
import math
import sys
import time
from pathlib import Path

import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None


def require_opencv():
    if cv2 is None:
        raise RuntimeError("OpenCV is not installed. Run: pip install opencv-contrib-python")


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


def create_marker_image(dictionary_name, marker_id, marker_px, page_px, label):
    marker = create_marker_bitmap(dictionary_name, marker_id, marker_px)
    page = np.full((page_px, page_px), 255, dtype=np.uint8)
    offset = (page_px - marker_px) // 2
    page[offset : offset + marker_px, offset : offset + marker_px] = marker
    cv2.putText(
        page,
        label,
        (40, page_px - 45),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.2,
        0,
        3,
        cv2.LINE_AA,
    )
    return page


def write_marker_svg(path, dictionary_name, marker_id, marker_size_mm, label):
    marker = create_marker_bitmap(dictionary_name, marker_id, 600)
    ok, encoded = cv2.imencode(".png", marker)
    if not ok:
        raise RuntimeError(f"Could not encode marker {marker_id} as PNG.")
    payload = base64.b64encode(encoded.tobytes()).decode("ascii")
    margin_mm = 3.0
    label_height_mm = 5.0
    page_w = marker_size_mm + margin_mm * 2
    page_h = marker_size_mm + margin_mm * 2 + label_height_mm
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{page_w}mm" height="{page_h}mm" viewBox="0 0 {page_w} {page_h}">
  <rect width="100%" height="100%" fill="white"/>
  <image href="data:image/png;base64,{payload}" x="{margin_mm}" y="{margin_mm}" width="{marker_size_mm}" height="{marker_size_mm}" image-rendering="pixelated"/>
  <text x="{margin_mm}" y="{marker_size_mm + margin_mm + 4}" font-family="Arial, sans-serif" font-size="3" fill="black">{label}</text>
</svg>
"""
    Path(path).write_text(svg, encoding="utf-8")


def make_ground(args):
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    width_mm = args.cols * args.cell_mm
    height_mm = args.rows * args.cell_mm
    placements = [
        {"id": args.start_id + 0, "name": "origin", "anchor_mm": [0.0, 0.0, 0.0], "yaw_deg": 0.0},
        {"id": args.start_id + 1, "name": "x_axis", "anchor_mm": [width_mm, 0.0, 0.0], "yaw_deg": 0.0},
        {"id": args.start_id + 2, "name": "y_axis", "anchor_mm": [0.0, height_mm, 0.0], "yaw_deg": 0.0},
        {
            "id": args.start_id + 3,
            "name": "xy_corner",
            "anchor_mm": [width_mm, height_mm, 0.0],
            "yaw_deg": 0.0,
        },
    ]

    if args.add_midpoints:
        placements.extend(
            [
                {
                    "id": args.start_id + 4,
                    "name": "bottom_mid",
                    "anchor_mm": [width_mm / 2.0, 0.0, 0.0],
                    "yaw_deg": 0.0,
                },
                {
                    "id": args.start_id + 5,
                    "name": "top_mid",
                    "anchor_mm": [width_mm / 2.0, height_mm, 0.0],
                    "yaw_deg": 0.0,
                },
                {
                    "id": args.start_id + 6,
                    "name": "left_mid",
                    "anchor_mm": [0.0, height_mm / 2.0, 0.0],
                    "yaw_deg": 0.0,
                },
                {
                    "id": args.start_id + 7,
                    "name": "right_mid",
                    "anchor_mm": [width_mm, height_mm / 2.0, 0.0],
                    "yaw_deg": 0.0,
                },
            ]
        )

    marker_px = int(args.page_px * 0.72)
    for item in placements:
        image = create_marker_image(
            args.dictionary,
            item["id"],
            marker_px,
            args.page_px,
            f"GROUND ID {item['id']}",
        )
        cv2.imwrite(str(out_dir / f"ground_id_{item['id']:03d}.png"), image)
        write_marker_svg(
            out_dir / f"ground_id_{item['id']:03d}.svg",
            args.dictionary,
            item["id"],
            args.marker_size_mm,
            f"GROUND ID {item['id']}",
        )

    config = {
        "dictionary": args.dictionary,
        "cell_mm": args.cell_mm,
        "cols": args.cols,
        "rows": args.rows,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "marker_size_mm": args.marker_size_mm,
        "ground_anchor_corner": args.anchor_corner,
        "ground_markers": placements,
    }
    config_path = out_dir / "ground_markers.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    print(f"Saved ground markers to: {out_dir.resolve()}")
    print(f"Saved placement config: {config_path.resolve()}")
    print("Prefer printing SVG files at 100% scale. The black marker square is sized by marker_size_mm.")
    print(f"Place each marker's {args.anchor_corner} corner on the configured grid vertex.")


def make_top(args):
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    marker_px = int(args.page_px * 0.72)
    ids = []
    for marker_id in range(args.start_id, args.start_id + args.count):
        image = create_marker_image(
            args.dictionary,
            marker_id,
            marker_px,
            args.page_px,
            f"TOP ID {marker_id}",
        )
        cv2.imwrite(str(out_dir / f"top_id_{marker_id:03d}.png"), image)
        write_marker_svg(
            out_dir / f"top_id_{marker_id:03d}.svg",
            args.dictionary,
            marker_id,
            args.marker_size_mm,
            f"TOP ID {marker_id}",
        )
        ids.append(marker_id)
    manifest = {
        "dictionary": args.dictionary,
        "marker_size_mm": args.marker_size_mm,
        "top_marker_ids": ids,
    }
    (out_dir / "top_markers.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Saved top markers to: {out_dir.resolve()}")
    print("Prefer printing SVG files at 100% scale. The black marker square is sized by marker_size_mm.")
    print("Use different IDs on top blocks when possible. It makes multi-camera de-duplication much easier.")


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
        raise RuntimeError(f"Only {len(used_ids)} ground markers detected. Need at least {args.min_markers}.")

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
    print(f"Saved camera extrinsic: {out.resolve()}")
    print(f"Used ground IDs: {used_ids}")
    print(f"RMS reprojection error: {result['rms_reprojection_error_px']:.3f} px")


def estimate_top_centers(image, dictionary_name, camera_matrix, dist_coeffs, marker_size_mm):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detect_markers(gray, dictionary_name)
    if ids is None:
        return []
    marker_size = float(marker_size_mm)
    centers = []
    object_points = marker_local_corners(marker_size)
    for marker_id, marker_corners in zip(ids.reshape(-1), corners):
        ok, _rvec, tvec = cv2.solvePnP(
            object_points,
            marker_corners.reshape(4, 2).astype(np.float64),
            camera_matrix,
            dist_coeffs,
            flags=cv2.SOLVEPNP_IPPE_SQUARE,
        )
        if ok:
            centers.append({"id": int(marker_id), "camera_xyz_mm": np.asarray(tvec).reshape(3)})
    return centers


def build_grid_from_centers(centers, ground_config, rotation_cw, translation_cw, block_height_mm):
    grid = np.zeros((ground_config["rows"], ground_config["cols"]), dtype=np.int32)
    observations = []

    for center in centers:
        cam_xyz = center["camera_xyz_mm"].reshape(3, 1)
        world_xyz = rotation_cw @ cam_xyz + translation_cw
        x, y, z = world_xyz.reshape(3).tolist()
        col = int(math.floor(x / ground_config["cell_mm"]))
        row = int(math.floor(y / ground_config["cell_mm"]))
        level = int(round(z / block_height_mm))
        if 0 <= row < ground_config["rows"] and 0 <= col < ground_config["cols"] and level >= 0:
            grid[row, col] = max(grid[row, col], level)
        observations.append(
            {
                "id": center["id"],
                "center_x_mm": x,
                "center_y_mm": y,
                "center_z_mm": z,
                "row": row,
                "col": col,
                "level": level,
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
    print(f"Saved observations: {out_obs.resolve()}")
    print(f"Detected top markers: {len(observations)}")


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


def live_top(args):
    try:
        import pyzed.sl as sl
    except ImportError as exc:
        raise RuntimeError("pyzed is not installed or ZED SDK Python API is unavailable.") from exc

    ground_config = json.loads(Path(args.ground_config).read_text(encoding="utf-8"))
    camera_a_matrix, camera_a_dist_coeffs = load_intrinsics(args.camera_a_intrinsics)
    camera_b_matrix, camera_b_dist_coeffs = load_intrinsics(args.camera_b_intrinsics)

    camera_a_extrinsic = json.loads(Path(args.camera_a_extrinsic).read_text(encoding="utf-8"))
    camera_b_extrinsic = json.loads(Path(args.camera_b_extrinsic).read_text(encoding="utf-8"))

    rotation_a_cw, translation_a_cw = invert_transform(
        np.asarray(camera_a_extrinsic["world_to_camera"]["rotation"], dtype=np.float64),
        np.asarray(camera_a_extrinsic["world_to_camera"]["translation_mm"], dtype=np.float64),
    )
    rotation_b_cw, translation_b_cw = invert_transform(
        np.asarray(camera_b_extrinsic["world_to_camera"]["rotation"], dtype=np.float64),
        np.asarray(camera_b_extrinsic["world_to_camera"]["translation_mm"], dtype=np.float64),
    )

    camera_a = open_zed_camera(sl, args.camera_a_serial_number, args.resolution, args.fps)
    camera_b = open_zed_camera(sl, args.camera_b_serial_number, args.resolution, args.fps)

    runtime_a = sl.RuntimeParameters()
    runtime_b = sl.RuntimeParameters()
    image_a = sl.Mat()
    image_b = sl.Mat()

    out_csv = Path(args.output_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    out_json = Path(args.output_observations)
    out_json.parent.mkdir(parents=True, exist_ok=True)

    last_write = 0.0

    print("Press q/ESC in the preview window to stop the live loop.")
    try:
        while True:
            ok_a = camera_a.grab(runtime_a) == sl.ERROR_CODE.SUCCESS
            ok_b = camera_b.grab(runtime_b) == sl.ERROR_CODE.SUCCESS
            if not ok_a and not ok_b:
                continue

            centers_a = []
            centers_b = []
            frame_a = None
            frame_b = None

            if ok_a:
                camera_a.retrieve_image(image_a, sl.VIEW.LEFT)
                frame_a = cv2.cvtColor(image_a.get_data(), cv2.COLOR_RGBA2BGR)
                centers_a = estimate_top_centers(
                    frame_a,
                    ground_config["dictionary"],
                    camera_a_matrix,
                    camera_a_dist_coeffs,
                    args.top_marker_size_mm,
                )

            if ok_b:
                camera_b.retrieve_image(image_b, sl.VIEW.LEFT)
                frame_b = cv2.cvtColor(image_b.get_data(), cv2.COLOR_RGBA2BGR)
                centers_b = estimate_top_centers(
                    frame_b,
                    ground_config["dictionary"],
                    camera_b_matrix,
                    camera_b_dist_coeffs,
                    args.top_marker_size_mm,
                )

            grid_a, observations_a = build_grid_from_centers(
                centers_a,
                ground_config,
                rotation_a_cw,
                translation_a_cw,
                args.block_height_mm,
            )
            grid_b, observations_b = build_grid_from_centers(
                centers_b,
                ground_config,
                rotation_b_cw,
                translation_b_cw,
                args.block_height_mm,
            )
            merged_grid = np.maximum(grid_a, grid_b)
            merged_observations = []
            for obs in observations_a:
                item = dict(obs)
                item["source"] = "camera_a"
                merged_observations.append(item)
            for obs in observations_b:
                item = dict(obs)
                item["source"] = "camera_b"
                merged_observations.append(item)

            if frame_a is not None:
                cv2.putText(
                    frame_a,
                    f"A SN {args.camera_a_serial_number} | markers: {len(centers_a)}",
                    (24, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )
                cv2.imshow("camera A top", frame_a)

            if frame_b is not None:
                cv2.putText(
                    frame_b,
                    f"B SN {args.camera_b_serial_number} | markers: {len(centers_b)}",
                    (24, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    1.0,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )
                cv2.imshow("camera B top", frame_b)

            if time.monotonic() - last_write >= args.update_interval_sec:
                with out_csv.open("w", newline="", encoding="utf-8-sig") as handle:
                    writer = csv.writer(handle)
                    writer.writerows(merged_grid.tolist())
                out_json.write_text(json.dumps(merged_observations, indent=2), encoding="utf-8")
                print(
                    f"Updated live grid: {out_csv.resolve()} | A markers: {len(centers_a)} | B markers: {len(centers_b)}"
                )
                last_write = time.monotonic()

            key = cv2.waitKey(1) & 0xFF
            if key in (27, ord("q")):
                break
    finally:
        cv2.destroyAllWindows()
        camera_a.close()
        camera_b.close()


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
    print(f"Saved merged observations: {out_json.resolve()}")


def build_parser():
    formatter = argparse.ArgumentDefaultsHelpFormatter
    parser = argparse.ArgumentParser(
        description="ArUco grid digital-twin helper.",
        formatter_class=formatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    make_ground_cmd = sub.add_parser("make-ground", formatter_class=formatter)
    make_ground_cmd.add_argument("--output-dir", default="markers/ground")
    make_ground_cmd.add_argument("--dictionary", default="DICT_5X5_100")
    make_ground_cmd.add_argument("--cols", type=int, required=True, help="Grid columns.")
    make_ground_cmd.add_argument("--rows", type=int, required=True, help="Grid rows.")
    make_ground_cmd.add_argument("--cell-mm", type=float, default=20.0, help="Grid cell size in millimeters.")
    make_ground_cmd.add_argument(
        "--marker-size-mm",
        type=float,
        default=15.0,
        help="Physical black ArUco square size in millimeters.",
    )
    make_ground_cmd.add_argument(
        "--anchor-corner",
        default="top_right",
        choices=["top_left", "top_right", "bottom_right", "bottom_left"],
        help="Marker corner placed exactly on the configured grid vertex.",
    )
    make_ground_cmd.add_argument("--start-id", type=int, default=0, help="First ground marker ID.")
    make_ground_cmd.add_argument("--page-px", type=int, default=1200, help="Generated PNG canvas size in pixels.")
    make_ground_cmd.add_argument("--add-midpoints", action="store_true", help="Add four extra edge midpoint markers.")
    make_ground_cmd.set_defaults(func=make_ground)

    make_top_cmd = sub.add_parser("make-top", formatter_class=formatter)
    make_top_cmd.add_argument("--output-dir", default="markers/top")
    make_top_cmd.add_argument("--dictionary", default="DICT_5X5_100")
    make_top_cmd.add_argument(
        "--marker-size-mm",
        type=float,
        default=15.0,
        help="Physical black ArUco square size in millimeters.",
    )
    make_top_cmd.add_argument("--start-id", type=int, default=20, help="First top marker ID.")
    make_top_cmd.add_argument("--count", type=int, required=True, help="Number of top markers to generate.")
    make_top_cmd.add_argument("--page-px", type=int, default=1200, help="Generated PNG canvas size in pixels.")
    make_top_cmd.set_defaults(func=make_top)

    solve_cmd = sub.add_parser("solve-extrinsic", formatter_class=formatter)
    solve_cmd.add_argument("--image", required=True)
    solve_cmd.add_argument("--intrinsics", required=True)
    solve_cmd.add_argument("--ground-config", default="markers/ground/ground_markers.json")
    solve_cmd.add_argument("--camera-name", required=True)
    solve_cmd.add_argument("--output", required=True)
    solve_cmd.add_argument("--min-markers", type=int, default=4)
    solve_cmd.set_defaults(func=solve_extrinsic)

    detect_cmd = sub.add_parser("detect-top", formatter_class=formatter)
    detect_cmd.add_argument("--image", required=True)
    detect_cmd.add_argument("--intrinsics", required=True)
    detect_cmd.add_argument("--extrinsic", required=True)
    detect_cmd.add_argument("--ground-config", default="markers/ground/ground_markers.json")
    detect_cmd.add_argument(
        "--top-marker-size-mm",
        type=float,
        default=15.0,
        help="Physical black top-marker square size in millimeters.",
    )
    detect_cmd.add_argument("--block-height-mm", type=float, default=20.0, help="Physical block height in millimeters.")
    detect_cmd.add_argument("--output-csv", default="outputs/grid_heights.csv", help="Output grid-height CSV path.")
    detect_cmd.add_argument(
        "--output-observations",
        default="outputs/top_observations.json",
        help="Output detailed marker observations JSON path.",
    )
    detect_cmd.set_defaults(func=detect_top)

    merge_cmd = sub.add_parser("merge-observations", formatter_class=formatter)
    merge_cmd.add_argument("--ground-config", default="markers/ground/ground_markers.json")
    merge_cmd.add_argument("--observations", nargs="+", required=True)
    merge_cmd.add_argument("--output-csv", default="outputs/grid_heights_merged.csv")
    merge_cmd.add_argument("--output-json", default="outputs/top_observations_merged.json")
    merge_cmd.set_defaults(func=merge_observations)

    live_cmd = sub.add_parser("live-top", formatter_class=formatter)
    live_cmd.add_argument("--ground-config", default="markers/ground/ground_markers.json")
    live_cmd.add_argument("--camera-a-serial-number", type=int, required=True)
    live_cmd.add_argument("--camera-b-serial-number", type=int, required=True)
    live_cmd.add_argument("--camera-a-intrinsics", required=True)
    live_cmd.add_argument("--camera-b-intrinsics", required=True)
    live_cmd.add_argument("--camera-a-extrinsic", required=True)
    live_cmd.add_argument("--camera-b-extrinsic", required=True)
    live_cmd.add_argument("--resolution", default="HD720")
    live_cmd.add_argument("--fps", type=int, default=30)
    live_cmd.add_argument(
        "--top-marker-size-mm",
        type=float,
        default=15.0,
        help="Physical black top-marker square size in millimeters.",
    )
    live_cmd.add_argument("--block-height-mm", type=float, default=20.0, help="Physical block height in millimeters.")
    live_cmd.add_argument("--output-csv", default="outputs/grid_heights_live.csv")
    live_cmd.add_argument("--output-observations", default="outputs/top_observations_live.json")
    live_cmd.add_argument("--update-interval-sec", type=float, default=0.5)
    live_cmd.set_defaults(func=live_top)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.func(args)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
