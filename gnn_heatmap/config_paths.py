"""目录约定：3D 输出 output/；2D 观测输入 outputs/；2D 输出 output_2d/。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent

DIR_3D_OUTPUT = ROOT / "output"
DIR_OBS_INPUT = ROOT / "outputs"
DIR_2D_OUTPUT = ROOT / "output_2d"

DEFAULT_3D_SOURCE = DIR_3D_OUTPUT / "occupied_space.heatmap.json"
DEFAULT_GROUND_TOP_SOURCE = DIR_OBS_INPUT / "ground_top_observations_live.json"
# 兼容旧路径样例
FALLBACK_GROUND_TOP_SOURCE = DIR_3D_OUTPUT / "ground_top_observations_live.json"

DEFAULT_2D_JSON = DIR_2D_OUTPUT / "ground_top_observations_live.heatmap2d.json"
DEFAULT_2D_HTML = DIR_2D_OUTPUT / "ground_top_observations_live.heatmap2d.html"

LIVE_PORT = 8766
LIVE_API_PATH = "/api/live/heatmap2d"


def resolve_ground_top_source() -> Path:
    """优先 outputs/，其次 output/ 样例。"""
    if DEFAULT_GROUND_TOP_SOURCE.is_file():
        return DEFAULT_GROUND_TOP_SOURCE
    return FALLBACK_GROUND_TOP_SOURCE
