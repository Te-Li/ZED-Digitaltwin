"""ground_top_observations_live.json → 二维热力网格。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np

from services.heatmap_2d import (
    PACK_FORMAT_2D,
    PACK_VERSION,
    Heatmap2DOptions,
    VOXEL_MODULE_M,
    _entity_footprint_mask,
    _grid_to_json_list,
    export_heatmap_2d_html,
)

GROUND_TOP_FORMAT = "ground-top-observations"


def load_ground_top_observations(path: Path) -> list[dict[str, Any]]:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"{path.name} 应为观测数组 JSON")
    return [item for item in raw if isinstance(item, dict)]


def _cell_from_observation(
    obs: dict[str, Any],
    *,
    nx: int,
    ny: int,
    cell_mm: float,
) -> tuple[int, int] | None:
    """row/col 为 1-based 网格索引；若无则回退 mm 坐标。"""
    row = obs.get("row")
    col = obs.get("col")
    if row is not None and col is not None:
        iy = int(row) - 1
        ix = int(col) - 1
    else:
        x_mm = float(obs.get("center_x_mm", 0))
        y_mm = float(obs.get("center_y_mm", 0))
        ix = int(x_mm / cell_mm)
        iy = int(y_mm / cell_mm)
    if ix < 0 or iy < 0 or ix >= nx or iy >= ny:
        return None
    return ix, iy


def project_ground_top_observations_to_2d(
    observations: list[dict[str, Any]],
    *,
    options: Optional[Heatmap2DOptions] = None,
    entity_pack: Optional[dict[str, Any]] = None,
    source_file: str = "ground_top_observations_live.json",
) -> dict[str, Any]:
    """观测点数组 → affordancenet-heatmap-2d 包。"""
    options = options or Heatmap2DOptions()
    nx, ny = options.nx, options.ny
    cell_m = options.cell_m
    cell_mm = cell_m * 1000.0

    entity_mask = (
        _entity_footprint_mask(entity_pack, nx, ny)
        if options.mask_entity_cells and entity_pack
        else np.zeros((ny, nx), dtype=bool)
    )

    grid = np.zeros((ny, nx), dtype=np.float64)
    skipped = 0
    for obs in observations:
        cell = _cell_from_observation(obs, nx=nx, ny=ny, cell_mm=cell_mm)
        if cell is None:
            skipped += 1
            continue
        ix, iy = cell
        if entity_mask[iy, ix]:
            continue
        grid[iy, ix] += 1.0

    peak = float(grid.max())
    if peak > 0:
        grid = grid / peak

    if options.mask_entity_cells:
        grid[entity_mask] = np.nan

    active = grid[~entity_mask & ~np.isnan(grid) & (grid > 1e-6)]

    return {
        "format": PACK_FORMAT_2D,
        "version": PACK_VERSION,
        "source_format": GROUND_TOP_FORMAT,
        "source_file": source_file,
        "scene_id": Path(source_file).stem,
        "region_label": "ground_top_observations",
        "heatmap_method": "ground_top_observation_count",
        "projection": "top_down_count",
        "width_m": options.width_m,
        "height_m": options.height_m,
        "nx": nx,
        "ny": ny,
        "cell_x_m": cell_m,
        "cell_y_m": cell_m,
        "axis": {"x": "width_m", "y": "height_m", "origin": "bottom_left"},
        "entity_mask_applied": options.mask_entity_cells and entity_pack is not None,
        "entity_cell_count": int(entity_mask.sum()) if entity_pack else 0,
        "observation_count": len(observations),
        "observation_skipped": skipped,
        "observation_cells": int(np.sum(grid > 1e-6) if not np.all(np.isnan(grid)) else 0),
        "intensity_range": {
            "min": float(active.min()) if active.size else 0.0,
            "max": float(active.max()) if active.size else 0.0,
        },
        "values": _grid_to_json_list(grid),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def export_ground_top_2d_json(
    input_json: Path,
    output_json: Path,
    *,
    options: Optional[Heatmap2DOptions] = None,
    entity_pack_path: Optional[Path] = None,
) -> dict[str, Any]:
    input_json = Path(input_json)
    output_json = Path(output_json)
    observations = load_ground_top_observations(input_json)

    entity_pack = None
    if entity_pack_path and Path(entity_pack_path).is_file():
        entity_pack = json.loads(Path(entity_pack_path).read_text(encoding="utf-8"))

    result = project_ground_top_observations_to_2d(
        observations,
        options=options,
        entity_pack=entity_pack,
        source_file=input_json.name,
    )
    result["source_ground_top"] = str(input_json.resolve())
    if input_json.exists():
        result["source_ground_top_mtime"] = input_json.stat().st_mtime

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def export_ground_top_2d_bundle(
    input_json: Path,
    output_json: Path,
    *,
    output_html: Optional[Path] = None,
    options: Optional[Heatmap2DOptions] = None,
    entity_pack_path: Optional[Path] = None,
) -> tuple[dict[str, Any], Path]:
    result = export_ground_top_2d_json(
        input_json,
        output_json,
        options=options,
        entity_pack_path=entity_pack_path,
    )
    html_path = output_html or output_json.with_suffix(".html")
    export_heatmap_2d_html(result, html_path)
    return result, html_path
