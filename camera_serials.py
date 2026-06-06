import argparse


CAMERA_SERIAL_NUMBERS = {
    "zed1": 34407890,
    "zed2": 37807506,
    "zed3": 30329327,
}


def format_known_camera_ids():
    return ", ".join(f"{name}={serial}" for name, serial in CAMERA_SERIAL_NUMBERS.items())


def resolve_camera_serial_number(value):
    if value is None:
        return None
    if isinstance(value, int):
        return value

    text = str(value).strip()
    camera_id = text.lower()
    if camera_id in CAMERA_SERIAL_NUMBERS:
        return CAMERA_SERIAL_NUMBERS[camera_id]
    if text.isdigit():
        return int(text)

    raise argparse.ArgumentTypeError(
        f"unknown camera id or serial number: {value}. Known cameras: {format_known_camera_ids()}"
    )
