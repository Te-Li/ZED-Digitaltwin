"""Path conventions for 3D input/output, mask input, and 2D exports."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent

DIR_3D_OUTPUT = ROOT / "output"
DIR_OBS_INPUT = ROOT.parent / "outputs"
DIR_2D_OUTPUT = ROOT / "output_2d"

DEFAULT_OCCUPIED_SPACE_INPUT = DIR_OBS_INPUT / "occupied_space.json"
DEFAULT_STREET_ELEMENTS_CSV = ROOT / "street elements.csv"

DEFAULT_3D_HEATMAP_JSON = DIR_3D_OUTPUT / "occupied_space.heatmap.json"

DEFAULT_GROUND_TOP_MASK_SOURCE = DIR_OBS_INPUT / "ground_top_observations_live.json"

DEFAULT_2D_HEATMAP_JSON = DIR_2D_OUTPUT / "2d_heatmap.json"
DEFAULT_2D_HEATMAP_HTML = DIR_2D_OUTPUT / "2d_heatmap.html"
DEFAULT_PROJECTION_CALIBRATION = ROOT / "projection_calibration.json"

LIVE_PORT = 8766
LIVE_API_PATH = "/api/live/heatmap2d"
LIVE_CALIBRATION_API_PATH = "/api/live/projection-calibration"
