import argparse
import json
import sys
from pathlib import Path

try:
    import cv2
except ImportError:
    cv2 = None


def require_opencv():
    if cv2 is None:
        raise RuntimeError("OpenCV is not installed. Run: pip install opencv-contrib-python")


def get_aruco_dict(name: str):
    require_opencv()
    if not hasattr(cv2, "aruco"):
        raise RuntimeError("Your OpenCV build has no aruco module. Install opencv-contrib-python.")
    if not hasattr(cv2.aruco, name):
        raise ValueError(f"Unknown ArUco dictionary: {name}")
    return cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, name))


def create_charuco_board(squares_x, squares_y, square_length_m, marker_length_m, dictionary):
    if hasattr(cv2.aruco, "CharucoBoard"):
        return cv2.aruco.CharucoBoard(
            (squares_x, squares_y), square_length_m, marker_length_m, dictionary
        )
    return cv2.aruco.CharucoBoard_create(
        squares_x, squares_y, square_length_m, marker_length_m, dictionary
    )


def detect_markers(gray, dictionary):
    params = cv2.aruco.DetectorParameters()
    if hasattr(cv2.aruco, "ArucoDetector"):
        detector = cv2.aruco.ArucoDetector(dictionary, params)
        return detector.detectMarkers(gray)
    return cv2.aruco.detectMarkers(gray, dictionary, parameters=params)


def interpolate_charuco(corners, ids, gray, board):
    if ids is None or len(ids) == 0:
        return 0, None, None
    return cv2.aruco.interpolateCornersCharuco(corners, ids, gray, board)


def configure_zed_init(args, sl):
    init = sl.InitParameters()
    init.camera_resolution = getattr(sl.RESOLUTION, args.resolution)
    init.camera_fps = args.fps
    init.coordinate_units = sl.UNIT.METER
    if args.serial_number is not None:
        init.set_from_serial_number(args.serial_number)
    return init


def generate_board(args):
    dictionary = get_aruco_dict(args.dictionary)
    board = create_charuco_board(
        args.squares_x,
        args.squares_y,
        args.square_length_mm / 1000.0,
        args.marker_length_mm / 1000.0,
        dictionary,
    )

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    size = (args.image_width_px, args.image_height_px)
    if hasattr(board, "generateImage"):
        image = board.generateImage(size, marginSize=args.margin_px)
    else:
        image = board.draw(size, marginSize=args.margin_px)
    cv2.imwrite(str(out), image)
    print(f"Saved ChArUco board image: {out.resolve()}")
    print("Print it at 100% scale. Measure one square after printing to confirm the mm size.")


def print_zed_factory_intrinsics(args):
    try:
        import pyzed.sl as sl
    except ImportError as exc:
        raise RuntimeError("pyzed is not installed or ZED SDK Python API is unavailable.") from exc

    zed = sl.Camera()
    init = configure_zed_init(args, sl)

    status = zed.open(init)
    if status != sl.ERROR_CODE.SUCCESS:
        raise RuntimeError(f"Could not open ZED camera: {status}")

    info = zed.get_camera_information()
    calib = info.camera_configuration.calibration_parameters
    left = calib.left_cam
    right = calib.right_cam

    print("Left camera factory intrinsics:")
    print(json.dumps({
        "fx": left.fx,
        "fy": left.fy,
        "cx": left.cx,
        "cy": left.cy,
        "distortion": list(left.disto),
        "image_size": [left.image_size.width, left.image_size.height],
    }, indent=2))
    print("Right camera factory intrinsics:")
    print(json.dumps({
        "fx": right.fx,
        "fy": right.fy,
        "cx": right.cx,
        "cy": right.cy,
        "distortion": list(right.disto),
        "image_size": [right.image_size.width, right.image_size.height],
    }, indent=2))
    zed.close()


def capture_zed_left_images(args):
    try:
        import pyzed.sl as sl
    except ImportError as exc:
        raise RuntimeError("pyzed is not installed or ZED SDK Python API is unavailable.") from exc

    out_dir = Path(args.output_dir) if args.output_dir is not None else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
    output_image = Path(args.output_image) if args.output_image is not None else None
    if output_image is not None:
        output_image.parent.mkdir(parents=True, exist_ok=True)

    zed = sl.Camera()
    init = configure_zed_init(args, sl)
    status = zed.open(init)
    if status != sl.ERROR_CODE.SUCCESS:
        raise RuntimeError(f"Could not open ZED camera: {status}")

    runtime = sl.RuntimeParameters()
    image = sl.Mat()
    index = len(list(out_dir.glob("left_*.png"))) if out_dir is not None else 0

    if output_image is not None:
        print(f"Saving one left-camera image to {output_image}")
    else:
        print("Press SPACE to save a left-camera image, q/ESC to quit.")
        print("Move the board across the whole view, including corners, edges, tilt, and distance changes.")

    while True:
        if zed.grab(runtime) != sl.ERROR_CODE.SUCCESS:
            continue
        zed.retrieve_image(image, sl.VIEW.LEFT)
        frame = image.get_data()
        frame = cv2.cvtColor(frame, cv2.COLOR_RGBA2BGR)

        if output_image is not None:
            cv2.imwrite(str(output_image), frame)
            print(f"Saved {output_image}")
            break

        preview = frame.copy()
        cv2.putText(
            preview,
            f"saved: {index} | SPACE save | q quit",
            (24, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
        cv2.imshow("ZED left calibration capture", preview)
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord("q")):
            break
        if key == 32:
            path = out_dir / f"left_{index:04d}.png"
            cv2.imwrite(str(path), frame)
            print(f"Saved {path}")
            index += 1

    cv2.destroyAllWindows()
    zed.close()


def calibrate_from_images(args):
    dictionary = get_aruco_dict(args.dictionary)
    board = create_charuco_board(
        args.squares_x,
        args.squares_y,
        args.square_length_mm / 1000.0,
        args.marker_length_mm / 1000.0,
        dictionary,
    )

    image_dir = Path(args.image_dir)
    image_paths = sorted(
        list(image_dir.glob("*.png"))
        + list(image_dir.glob("*.jpg"))
        + list(image_dir.glob("*.jpeg"))
    )
    if not image_paths:
        raise RuntimeError(f"No calibration images found in {image_dir}")

    all_corners = []
    all_ids = []
    image_size = None
    used = 0

    for path in image_paths:
        image = cv2.imread(str(path))
        if image is None:
            print(f"Skip unreadable image: {path}")
            continue
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        image_size = gray.shape[::-1]
        marker_corners, marker_ids, _ = detect_markers(gray, dictionary)
        ok, charuco_corners, charuco_ids = interpolate_charuco(
            marker_corners, marker_ids, gray, board
        )
        if ok is not None and ok >= args.min_corners:
            all_corners.append(charuco_corners)
            all_ids.append(charuco_ids)
            used += 1
            print(f"Use {path.name}: {ok} ChArUco corners")
        else:
            found = 0 if ok is None else int(ok)
            print(f"Skip {path.name}: only {found} ChArUco corners")

    if used < args.min_images:
        raise RuntimeError(f"Only {used} valid images. Capture at least {args.min_images}.")

    flags = 0
    rms, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.aruco.calibrateCameraCharuco(
        all_corners,
        all_ids,
        board,
        image_size,
        None,
        None,
        flags=flags,
    )

    result = {
        "rms_reprojection_error_px": float(rms),
        "image_size": list(image_size),
        "camera_matrix": camera_matrix.tolist(),
        "dist_coeffs": dist_coeffs.reshape(-1).tolist(),
        "board": {
            "type": "ChArUco",
            "dictionary": args.dictionary,
            "squares_x": args.squares_x,
            "squares_y": args.squares_y,
            "square_length_mm": args.square_length_mm,
            "marker_length_mm": args.marker_length_mm,
        },
        "valid_image_count": used,
    }

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"Saved calibration: {out.resolve()}")
    print(f"RMS reprojection error: {rms:.4f} px")
    if rms > 1.0:
        print("Warning: RMS is high. Capture more varied, sharp images and recalibrate.")


def build_parser():
    parser = argparse.ArgumentParser(description="ZED left-camera intrinsic calibration helper.")
    sub = parser.add_subparsers(dest="command", required=True)

    common_board = argparse.ArgumentParser(add_help=False)
    common_board.add_argument("--dictionary", default="DICT_5X5_100")
    common_board.add_argument("--squares-x", type=int, default=7)
    common_board.add_argument("--squares-y", type=int, default=5)
    common_board.add_argument("--square-length-mm", type=float, default=40.0)
    common_board.add_argument("--marker-length-mm", type=float, default=30.0)

    board = sub.add_parser("make-board", parents=[common_board])
    board.add_argument("--output", default="calibration/charuco_board.png")
    board.add_argument("--image-width-px", type=int, default=2400)
    board.add_argument("--image-height-px", type=int, default=1800)
    board.add_argument("--margin-px", type=int, default=80)
    board.set_defaults(func=generate_board)

    factory = sub.add_parser("show-zed-factory")
    factory.add_argument("--resolution", default="HD720")
    factory.add_argument("--fps", type=int, default=30)
    factory.add_argument("--serial-number", type=int, help="Open a specific ZED by serial number.")
    factory.set_defaults(func=print_zed_factory_intrinsics)

    capture = sub.add_parser("capture")
    capture.add_argument("--output-dir", default="calibration/images")
    capture.add_argument("--output-image", help="Save one frame directly to this image path.")
    capture.add_argument("--resolution", default="HD720")
    capture.add_argument("--fps", type=int, default=30)
    capture.add_argument("--serial-number", type=int, help="Open a specific ZED by serial number.")
    capture.set_defaults(func=capture_zed_left_images)

    calibrate = sub.add_parser("calibrate", parents=[common_board])
    calibrate.add_argument("--image-dir", default="calibration/images")
    calibrate.add_argument("--output", default="calibration/zed_left_intrinsics.json")
    calibrate.add_argument("--min-corners", type=int, default=12)
    calibrate.add_argument("--min-images", type=int, default=15)
    calibrate.set_defaults(func=calibrate_from_images)

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
