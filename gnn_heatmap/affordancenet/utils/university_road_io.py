"""大学路场景记录精简子集（无 xls / pandas 依赖）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from dataset.voxel_schema import SpaceVoxel, VoxelType
from utils.training_data_io import TRAINING_CN_TYPE_MAP, TrainingSceneRecord
from utils.voxel_grid import GridKey

UNIVERSITY_CN_TYPE_MAP: Dict[str, VoxelType] = {
    **TRAINING_CN_TYPE_MAP,
    "人行道": VoxelType.RUNNING_TRACK,
    "车道": VoxelType.RUNNING_TRACK,
    "绿化道": VoxelType.RUNNING_TRACK,
    "车位": VoxelType.RUNNING_TRACK,
    "餐饮外摆": VoxelType.OUTDOOR_SEATING,
    "立展板": VoxelType.POSTER_STAND,
    "路灯": VoxelType.STREETLIGHT,
    "自动售货机": VoxelType.DISPLAY_STAND,
    "电压箱": VoxelType.UTILITY_POLE,
    "消防栓": VoxelType.BOLLARD,
    "邮筒": VoxelType.POSTER_STAND,
    "公告板": VoxelType.POSTER_STAND,
}

ZoneBounds = Tuple[float, float, float, float, float, float]


@dataclass
class ZoneInfo:
    zone_id: str
    bounds: ZoneBounds
    is_variable: bool
    anchor_key: Optional[GridKey] = None


@dataclass
class UniversityRoadRecord(TrainingSceneRecord):
    scene_kind: str = "storefront"
    street_zones: List[ZoneInfo] = field(default_factory=list)
    entity_zones: Dict[str, str] = field(default_factory=dict)
    entity_source_cn: Dict[str, str] = field(default_factory=dict)
    parse_stats: Dict[str, int] = field(default_factory=dict)


def active_zone_bounds(record: UniversityRoadRecord) -> Optional[ZoneBounds]:
    active = record.meta.get("active_zone")
    if not active:
        return None
    for z in record.street_zones:
        if z.zone_id == active:
            return z.bounds
    return None


def space_voxel_in_bounds(sv: SpaceVoxel, bounds: ZoneBounds) -> bool:
    x0, x1, y0, y1, z0, z1 = bounds
    return x0 <= sv.x <= x1 and y0 <= sv.y <= y1 and z0 <= sv.z <= z1


def mask_space_to_active_zone(
    space_voxels: List[SpaceVoxel],
    bounds: ZoneBounds,
) -> List[SpaceVoxel]:
    masked: List[SpaceVoxel] = []
    for sv in space_voxels:
        if space_voxel_in_bounds(sv, bounds):
            masked.append(sv)
        else:
            masked.append(
                SpaceVoxel(x=sv.x, y=sv.y, z=sv.z, social_intensity=0.0)
            )
    return masked
