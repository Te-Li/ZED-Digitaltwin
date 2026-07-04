"""Apply ground-top observations as a mask on an existing 2D heatmap."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from services.heatmap_2d import VOXEL_MODULE_M


def load_ground_top_observations(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path.name} must be an observation array JSON")
    return [item for item in raw if isinstance(item, dict)]


def _cell_from_observation(
    obs: dict[str, Any],
    *,
    nx: int,
    ny: int,
    cell_mm: float,
) -> tuple[int, int] | None:
    """row/col are sensor indices; heatmap mask is shifted +1 cell in x/y."""
    row = obs.get("row")
    col = obs.get("col")
    if row is not None and col is not None:
        # iy = int(row) + 1
        # ix = int(col) + 1
        iy = int(row)
        ix = int(col)
    else:
        x_mm = float(obs.get("center_x_mm", 0))
        y_mm = float(obs.get("center_y_mm", 0))
        ix = int(x_mm / cell_mm)
        iy = int(y_mm / cell_mm)
    if ix < 0 or iy < 0 or ix >= nx or iy >= ny:
        return None
    return ix, iy


def apply_ground_top_mask_to_2d(
    heatmap_2d: dict[str, Any],
    observations: list[dict[str, Any]],
    *,
    source_file: str = "ground_top_observations_live.json",
) -> dict[str, Any]:
    """Mask observed ground-top cells in an existing 2D heatmap."""
    result = deepcopy(heatmap_2d)
    values = result.get("values")
    if not isinstance(values, list) or not values:
        raise ValueError("2D heatmap values must be a non-empty grid")

    ny = int(result.get("ny") or len(values))
    nx = int(result.get("nx") or len(values[0]))
    cell_m = float(result.get("cell_x_m") or VOXEL_MODULE_M)
    cell_mm = cell_m * 1000.0


    masked_cells: set[tuple[int, int]] = set()
    skipped = 0
    for obs in observations:
        cell = _cell_from_observation(obs, nx=nx, ny=ny, cell_mm=cell_mm)
        if cell is None:
            skipped += 1
            continue
        ix, iy = cell
        values[iy][ix] = None
        masked_cells.add((ix, iy))

    active: list[float] = []
    for row in values:
        for value in row:
            if value is None:
                continue
            v = float(value)
            if v > 1e-6:
                active.append(v)


    result["values"] = values
    result["source_ground_top_mask"] = source_file
    result["ground_top_mask_applied"] = True
    result["ground_top_mask_mode"] = "mask_observed_cells"
    result["ground_top_observation_count"] = len(observations)
    result["ground_top_observation_skipped"] = skipped
    result["ground_top_mask_cell_count"] = len(masked_cells)
    result["heatmap_method"] = f"{result.get('heatmap_method', 'heatmap')}_ground_top_masked"
    result["intensity_range"] = {
        "min": min(active) if active else 0.0,
        "max": max(active) if active else 0.0,
    }
    result["generated_at"] = datetime.now(timezone.utc).isoformat()
    return result
