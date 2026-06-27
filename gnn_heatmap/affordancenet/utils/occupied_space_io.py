"""ZED occupied_space JSON + street elements CSV → AffordanceNet 场景记录。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from dataset.voxel_schema import EntityVoxel, SpaceVoxel, VoxelScene
from utils.scene_io import _default_category
from utils.street_elements_io import (
    StreetElementCatalog,
    find_paired_street_elements_csv,
    load_street_elements_csv,
    resolve_cell_element_name,
)
from utils.university_road_io import UniversityRoadRecord, ZoneInfo
from utils.voxel_grid import VOXEL_MODULE_M, GridKey, grid_to_center

ACTIVE_ZONE_ID = "occupied"


def load_occupied_space_json(
    path: str | Path,
    *,
    elements_csv: str | Path | None = None,
) -> Tuple[UniversityRoadRecord, dict[str, Any]]:
    """
    解析 occupied_space JSON（cells + width/height/depth）。

    实体命名以 street elements*.csv 为准；默认同目录自动配对
    occupied_space(N).json ↔ street elements(N).csv。
    """
    path = Path(path)
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))

    csv_path = Path(elements_csv) if elements_csv else find_paired_street_elements_csv(path)
    if csv_path is None:
        raise FileNotFoundError(
            f"未找到 street elements CSV，请与 {path.name} 同目录放置 "
            f"street elements(N).csv，或用 --elements-csv 指定"
        )
    catalog = load_street_elements_csv(csv_path)

    width = int(raw.get("width", 10))
    height = int(raw.get("height", 6))
    depth = int(raw.get("depth", 6))
    res = float(raw.get("voxel_resolution", VOXEL_MODULE_M))

    cells = raw.get("cells") or []
    if not cells:
        raise ValueError(f"{path.name} 无 cells 实体数据")

    max_x = max(int(c["x"]) for c in cells)
    max_y = max(int(c["y"]) for c in cells)
    max_z = max(int(c["z"]) for c in cells)
    nx = max(width, max_x + 1)
    ny = max(height, max_y + 1)
    nz = max(depth, max_z + 1)

    occupied: Set[GridKey] = set()
    entities: List[EntityVoxel] = []
    entity_zones: Dict[str, str] = {}
    entity_source_cn: Dict[str, str] = {}

    for cell in cells:
        ix, iy, iz = int(cell["x"]), int(cell["y"]), int(cell["z"])
        if not (0 <= ix < nx and 0 <= iy < ny and 0 <= iz < nz):
            continue
        key = (ix, iy, iz)
        if key in occupied:
            continue
        cn = resolve_cell_element_name(cell, catalog)
        vtype = catalog.resolve_voxel_type(cn)
        category = _default_category(vtype)
        x, y, z = grid_to_center(ix, iy, iz, res)
        occupied.add(key)
        entities.append(EntityVoxel(category=category, type=vtype, x=x, y=y, z=z))
        pos_key = f"{x:.3f},{y:.3f},{z:.3f}"
        entity_zones[pos_key] = ACTIVE_ZONE_ID
        entity_source_cn[pos_key] = cn

    space_voxels: List[SpaceVoxel] = []
    for iz in range(nz):
        for iy in range(ny):
            for ix in range(nx):
                if (ix, iy, iz) in occupied:
                    continue
                x, y, z = grid_to_center(ix, iy, iz, res)
                space_voxels.append(SpaceVoxel(x=x, y=y, z=z, social_intensity=0.0))

    scene_id = str(raw.get("scene_id", path.stem))
    scene = VoxelScene(scene_id=scene_id, entity_voxels=entities, space_voxels=space_voxels)

    x1, y1, z1 = nx * res, ny * res, nz * res
    bounds = (0.0, x1, 0.0, y1, 0.0, z1)
    street_zones = [
        ZoneInfo(
            zone_id=ACTIVE_ZONE_ID,
            bounds=bounds,
            is_variable=True,
            anchor_key=(0, 0, 0),
        )
    ]

    meta = {
        "active_zone": ACTIVE_ZONE_ID,
        "scene_size_x": x1,
        "scene_size_y": y1,
        "scene_height": z1,
        "voxel_resolution": res,
        "grid_nx": nx,
        "grid_ny": ny,
        "grid_nz": nz,
        "street_elements_csv": str(csv_path.resolve()),
        "element_colors": catalog.element_colors(),
    }

    record = UniversityRoadRecord(
        scene_id=scene_id,
        focus_category="occupied_space",
        source_path=str(path.resolve()),
        world_offset=(0.0, 0.0),
        is_augmented=False,
        scene=scene,
        skeleton_points=[],
        meta=meta,
        scene_kind="occupied",
        street_zones=street_zones,
        entity_zones=entity_zones,
        entity_source_cn=entity_source_cn,
        parse_stats={
            "entity_count": len(entities),
            "space_count": len(space_voxels),
            "grid_cells": nx * ny * nz,
        },
    )

    source_meta = {
        "parent_x": raw.get("parent_x"),
        "parent_y": raw.get("parent_y"),
        "width": width,
        "height": height,
        "depth": depth,
        "base_attraction": raw.get("base_attraction"),
        "grid_nx": nx,
        "grid_ny": ny,
        "grid_nz": nz,
        "street_elements": catalog.to_dict(),
        "element_colors": catalog.element_colors(),
    }
    return record, source_meta
