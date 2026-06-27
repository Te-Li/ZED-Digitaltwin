"""occupied_space JSON → 合成骨骼热力 → 可分享热力 JSON。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from dataset.voxel_schema import SpaceVoxel
from services.heat_helpers import (
    _entity_color,
    _entity_hover,
    _entity_label,
    _heatmap_from_skeleton,
)
from utils.occupied_space_io import ACTIVE_ZONE_ID, load_occupied_space_json
from utils.social_vitality import SocialVitalityMetrics, compute_social_vitality
from utils.synthetic_skeleton import generate_synthetic_poses
from utils.university_road_io import (
    UniversityRoadRecord,
    active_zone_bounds,
    space_voxel_in_bounds,
)
from utils.voxel_grid import VOXEL_MODULE_M, coord_to_grid

PACK_FORMAT = "affordancenet-heatmap-pack"
PACK_VERSION = 1


@dataclass
class OccupiedSpacePredictOptions:
    skeleton_count: int = 100
    skeleton_seed: int = 42
    heat_sigma: float = 0.55
    standing_height_m: float = 1.75
    elements_csv: Optional[Path] = None


@dataclass
class OccupiedSpacePredictResult:
    record: UniversityRoadRecord
    pred_space: List[SpaceVoxel]
    heatmap_method: str
    skeleton_point_count: int
    pose_count: int
    social_vitality: SocialVitalityMetrics
    intensity_min: float
    intensity_max: float
    source_meta: dict[str, Any]


def run_occupied_space_predict(
    json_path: Path,
    options: Optional[OccupiedSpacePredictOptions] = None,
) -> OccupiedSpacePredictResult:
    options = options or OccupiedSpacePredictOptions()
    record, source_meta = load_occupied_space_json(
        json_path,
        elements_csv=options.elements_csv,
    )

    active_bounds = active_zone_bounds(record)
    if active_bounds is None:
        raise ValueError("无法确定 occupied 区域边界")

    skel = generate_synthetic_poses(
        record,
        n_points=options.skeleton_count,
        seed=options.skeleton_seed,
        standing_height_m=options.standing_height_m,
    )
    if not skel.points:
        raise ValueError("合成骨骼为空，请检查实体与行为空间是否有效")

    pred_space = _heatmap_from_skeleton(
        record, skel.points, active_bounds, options.heat_sigma,
    )

    all_active_ints = [
        sv.social_intensity
        for sv in pred_space
        if space_voxel_in_bounds(sv, active_bounds)
    ]
    vitality = compute_social_vitality(all_active_ints)
    ints = [v for v in all_active_ints if v > 1e-6]

    return OccupiedSpacePredictResult(
        record=record,
        pred_space=pred_space,
        heatmap_method="synthetic_skeleton_gaussian_diffusion",
        skeleton_point_count=len(skel.points),
        pose_count=len(skel.poses),
        social_vitality=vitality,
        intensity_min=min(ints) if ints else 0.0,
        intensity_max=max(ints) if ints else 0.0,
        source_meta=source_meta,
    )


def build_occupied_heatmap_pack(
    result: OccupiedSpacePredictResult,
    *,
    source_name: str,
) -> dict[str, Any]:
    record = result.record
    active_bounds = active_zone_bounds(record)
    sm = result.source_meta

    entities: List[dict] = []
    for ev in record.scene.entity_voxels:
        label = _entity_label(record, ev)
        ix, iy, iz = coord_to_grid(ev.x, ev.y, ev.z)
        entities.append({
            "label_cn": label,
            "type": ev.type.value,
            "category": ev.category.value,
            "x": ev.x,
            "y": ev.y,
            "z": ev.z,
            "grid_ix": ix,
            "grid_iy": iy,
            "grid_iz": iz,
            "grid_x": ix,
            "grid_y": iy,
            "grid_z": iz,
            "color": _entity_color(record, label, ev),
            "region_cn": "occupied_space",
            "hover": _entity_hover(record, ev, label),
        })

    heatmap_voxels: List[dict] = []
    cells_with_heat: List[dict] = []
    intensity_by_grid: Dict[tuple[int, int, int], float] = {}

    for sv in result.pred_space:
        if active_bounds and not space_voxel_in_bounds(sv, active_bounds):
            continue
        ix, iy, iz = coord_to_grid(sv.x, sv.y, sv.z)
        intensity = float(sv.social_intensity)
        intensity_by_grid[(ix, iy, iz)] = intensity
        if intensity <= 1e-6:
            continue
        heatmap_voxels.append({
            "x": sv.x,
            "y": sv.y,
            "z": sv.z,
            "grid_ix": ix,
            "grid_iy": iy,
            "grid_iz": iz,
            "grid_x": ix,
            "grid_y": iy,
            "grid_z": iz,
            "intensity": intensity,
        })

    for ev in record.scene.entity_voxels:
        ix, iy, iz = coord_to_grid(ev.x, ev.y, ev.z)
        pos_key = f"{ev.x:.3f},{ev.y:.3f},{ev.z:.3f}"
        cn = record.entity_source_cn.get(pos_key, ev.type.value)
        cells_with_heat.append({
            "x": ix, "y": iy, "z": iz,
            "type": cn,
            "is_entity": True,
            "intensity": 0.0,
        })

    for (ix, iy, iz), intensity in sorted(intensity_by_grid.items()):
        if intensity <= 1e-6:
            continue
        cells_with_heat.append({
            "x": ix, "y": iy, "z": iz,
            "type": "behavior_space",
            "is_entity": False,
            "intensity": intensity,
        })

    sv = result.social_vitality.to_dict()
    heated = len(heatmap_voxels)
    active_count = len(intensity_by_grid)

    return {
        "format": PACK_FORMAT,
        "version": PACK_VERSION,
        "source_format": "occupied_space",
        "entity_render_mode": "center_point",
        "voxel_module_m": VOXEL_MODULE_M,
        "viewer_hint": "使用同目录 heatmap_viewer.html 加载本 JSON",
        "scene_id": record.scene_id,
        "source_file": source_name,
        "scene_kind": "occupied",
        "region_label": "occupied_space",
        "heatmap_method": result.heatmap_method,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "occupied_space": {
            "parent_x": sm.get("parent_x"),
            "parent_y": sm.get("parent_y"),
            "width": sm.get("width"),
            "height": sm.get("height"),
            "depth": sm.get("depth"),
            "base_attraction": sm.get("base_attraction"),
            "grid_nx": sm.get("grid_nx"),
            "grid_ny": sm.get("grid_ny"),
            "grid_nz": sm.get("grid_nz"),
        },
        "street_elements": sm.get("street_elements"),
        "element_colors": sm.get("element_colors"),
        "intensity_range": {
            "min": result.intensity_min,
            "max": result.intensity_max,
        },
        "stats": {
            "entity_count": len(entities),
            "active_space_count": active_count,
            "heated_count": heated,
            "heatmap_voxel_count": heated,
            "skeleton_point_count": result.skeleton_point_count,
            "pose_count": result.pose_count,
        },
        "entities": entities,
        "heatmap_voxels": heatmap_voxels,
        "cells_with_heat": cells_with_heat,
        "social_vitality": sv,
        "active_zone": ACTIVE_ZONE_ID,
    }


def export_occupied_space_heatmap(
    input_json: Path,
    output_json: Path,
    *,
    options: Optional[OccupiedSpacePredictOptions] = None,
) -> OccupiedSpacePredictResult:
    input_json = Path(input_json)
    output_json = Path(output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)

    result = run_occupied_space_predict(input_json, options)
    pack = build_occupied_heatmap_pack(result, source_name=input_json.name)
    output_json.write_text(
        json.dumps(pack, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return result
