"""4m³ 体素网格工具：400mm 模数，10×10×10 满格。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np

from dataset.voxel_schema import EntityVoxel, SpaceVoxel, VoxelScene

# 街道体素模数：400mm × 400mm × 400mm
VOXEL_MODULE_M = 0.4
SCENE_EXTENT_M = 4.0
GRID_DIVISIONS = int(SCENE_EXTENT_M / VOXEL_MODULE_M)  # 10
TOTAL_VOXELS = GRID_DIVISIONS ** 3  # 1000

SPACE_TYPE_LABEL = "space"

GridKey = Tuple[int, int, int]


@dataclass
class AnnotatedVoxelField:
    """满格体素场，含坐标、强度与类型标注。"""

    x: np.ndarray
    y: np.ndarray
    z: np.ndarray
    intensity: np.ndarray
    voxel_type: List[str]
    is_entity: np.ndarray

    @property
    def heatmap_array(self) -> np.ndarray:
        """兼容旧接口 (N, 4): x, y, z, intensity。"""
        return np.column_stack([self.x, self.y, self.z, self.intensity]).astype(np.float32)

    def entity_mask(self) -> np.ndarray:
        return self.is_entity

    def space_mask(self) -> np.ndarray:
        return ~self.is_entity


def grid_to_center(ix: int, iy: int, iz: int, res: float = VOXEL_MODULE_M) -> Tuple[float, float, float]:
    """网格索引 → 体素中心坐标（米）。"""
    half = res / 2.0
    return (ix * res + half, iy * res + half, iz * res + half)


def meter_to_grid_index(m: float, res: float = VOXEL_MODULE_M) -> int:
    """
    米制坐标 → 格索引（400mm 模数，坐标落在格线/格底）。
    例：z=0.8m→iz=2，z=1.2m→iz=3。
    """
    return int(round(m / res))


def meter_to_grid(x: float, y: float, z: float, res: float = VOXEL_MODULE_M) -> GridKey:
    """米制 xyz → 格索引 (ix, iy, iz)。"""
    return (
        meter_to_grid_index(x, res),
        meter_to_grid_index(y, res),
        meter_to_grid_index(z, res),
    )


def coord_to_grid(
    x: float, y: float, z: float, res: float = VOXEL_MODULE_M
) -> GridKey:
    """体素中心坐标 → 网格索引。"""
    return (
        int(round((x - res / 2.0) / res)),
        int(round((y - res / 2.0) / res)),
        int(round((z - res / 2.0) / res)),
    )


def _entity_type_map(entities: List[EntityVoxel], res: float) -> Dict[GridKey, str]:
    mapping: Dict[GridKey, str] = {}
    for e in entities:
        mapping[coord_to_grid(e.x, e.y, e.z, res)] = e.type.value
    return mapping


def _space_intensity_map(
    space_voxels: List[SpaceVoxel], res: float
) -> Dict[GridKey, float]:
    mapping: Dict[GridKey, float] = {}
    for sv in space_voxels:
        mapping[coord_to_grid(sv.x, sv.y, sv.z, res)] = sv.social_intensity
    return mapping


def build_annotated_voxel_field(
    scene: VoxelScene,
    space_intensity_override: Optional[Dict[GridKey, float]] = None,
    res: float = VOXEL_MODULE_M,
    extent: float = SCENE_EXTENT_M,
) -> AnnotatedVoxelField:
    """
    构建满格标注体素场。

    每个体素包含：x, y, z, intensity, type（实体为元素名如 tree，空间为 space）。
    实体 intensity 恒为 0.0。
    """
    n = int(round(extent / res))
    entity_types = _entity_type_map(scene.entity_voxels, res)

    if space_intensity_override is not None:
        space_map = space_intensity_override
    else:
        space_map = _space_intensity_map(scene.space_voxels, res)

    xs, ys, zs, intensities, types, is_entity = [], [], [], [], [], []

    for iz in range(n):
        for iy in range(n):
            for ix in range(n):
                key = (ix, iy, iz)
                x, y, z = grid_to_center(ix, iy, iz, res)
                if key in entity_types:
                    xs.append(x)
                    ys.append(y)
                    zs.append(z)
                    intensities.append(0.0)
                    types.append(entity_types[key])
                    is_entity.append(True)
                else:
                    xs.append(x)
                    ys.append(y)
                    zs.append(z)
                    intensities.append(float(space_map.get(key, 0.0)))
                    types.append(SPACE_TYPE_LABEL)
                    is_entity.append(False)

    return AnnotatedVoxelField(
        x=np.array(xs, dtype=np.float32),
        y=np.array(ys, dtype=np.float32),
        z=np.array(zs, dtype=np.float32),
        intensity=np.array(intensities, dtype=np.float32),
        voxel_type=types,
        is_entity=np.array(is_entity, dtype=bool),
    )


def build_full_voxel_field(
    scene: VoxelScene,
    space_intensity_override: Optional[Dict[GridKey, float]] = None,
    res: float = VOXEL_MODULE_M,
    extent: float = SCENE_EXTENT_M,
) -> np.ndarray:
    """构建满格体素场 (N, 4)：每行 [x, y, z, social_intensity]。"""
    return build_annotated_voxel_field(
        scene, space_intensity_override, res, extent
    ).heatmap_array


def validate_scene_grid(scene: VoxelScene, res: float = VOXEL_MODULE_M) -> bool:
    """校验实体 + 空间体素是否恰好填满整个网格。"""
    entity_keys = set(_entity_type_map(scene.entity_voxels, res).keys())
    space_keys = {coord_to_grid(s.x, s.y, s.z, res) for s in scene.space_voxels}
    return (
        len(entity_keys) + len(space_keys) == TOTAL_VOXELS
        and len(entity_keys & space_keys) == 0
    )
