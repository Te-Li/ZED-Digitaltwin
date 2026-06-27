"""由人体骨骼点向行为空间体素做高斯扩散热力标注。"""

from __future__ import annotations

from typing import Dict, List, Tuple

import numpy as np

from dataset.voxel_schema import SpaceVoxel, VoxelScene
from utils.voxel_grid import GridKey, VOXEL_MODULE_M, coord_to_grid

SkeletonPoint = Tuple[float, float, float]


def compute_skeleton_gaussian_heatmap(
    scene: VoxelScene,
    skeleton_points: List[SkeletonPoint],
    sigma: float = 0.55,
    res: float = VOXEL_MODULE_M,
) -> Dict[GridKey, float]:
    """
    以骨骼点所在行为空间为峰值，向其余行为空间体素高斯扩散。

    对每个空间体素中心 p：
        heat(p) = Σ_b exp(-||p - b||² / (2σ²))
    再归一化到 [0, 1]。
    """
    if not scene.space_voxels:
        return {}

    bones = np.asarray(skeleton_points, dtype=np.float64)
    coords = np.asarray(
        [[sv.x, sv.y, sv.z] for sv in scene.space_voxels],
        dtype=np.float64,
    )

    raw = np.zeros(len(coords), dtype=np.float64)
    for bone in bones:
        diff = coords - bone
        d2 = np.sum(diff * diff, axis=1)
        raw += np.exp(-d2 / (2.0 * sigma * sigma))

    # 骨骼最近邻行为空间体素强制为峰值（处理骨骼落在实体格旁的情况）
    space_keys = {
        coord_to_grid(sv.x, sv.y, sv.z, res): i
        for i, sv in enumerate(scene.space_voxels)
    }
    for bone in bones:
        key = coord_to_grid(float(bone[0]), float(bone[1]), float(bone[2]), res)
        idx = space_keys.get(key)
        if idx is not None:
            raw[idx] = max(raw[idx], 1.0)

    peak = float(raw.max())
    if peak < 1e-12:
        return {
            coord_to_grid(sv.x, sv.y, sv.z, res): 0.0
            for sv in scene.space_voxels
        }

    norm = np.clip(raw / peak, 0.0, 1.0)
    return {
        coord_to_grid(sv.x, sv.y, sv.z, res): float(norm[i])
        for i, sv in enumerate(scene.space_voxels)
    }


def compute_zone_masked_skeleton_heatmap(
    scene: VoxelScene,
    skeleton_points: List[SkeletonPoint],
    zone_bounds: Tuple[float, float, float, float, float, float],
    sigma: float = 0.55,
    res: float = VOXEL_MODULE_M,
) -> Dict[GridKey, float]:
    """
    骨骼高斯扩散，热力仅写入 zone_bounds 内的行为空间体素。

    zone_bounds: (x_min, x_max, y_min, y_max, z_min, z_max)
    """
    if not scene.space_voxels or not skeleton_points:
        return {}

    x0, x1, y0, y1, z0, z1 = zone_bounds
    bones = np.asarray(skeleton_points, dtype=np.float64)

    masked: List[Tuple[int, GridKey, np.ndarray]] = []
    for i, sv in enumerate(scene.space_voxels):
        if x0 <= sv.x <= x1 and y0 <= sv.y <= y1 and z0 <= sv.z <= z1:
            key = coord_to_grid(sv.x, sv.y, sv.z, res)
            masked.append((i, key, np.array([sv.x, sv.y, sv.z], dtype=np.float64)))

    if not masked:
        return {}

    coords = np.stack([m[2] for m in masked], axis=0)
    raw = np.zeros(len(masked), dtype=np.float64)
    for bone in bones:
        diff = coords - bone
        d2 = np.sum(diff * diff, axis=1)
        raw += np.exp(-d2 / (2.0 * sigma * sigma))

    key_to_local = {m[1]: li for li, m in enumerate(masked)}
    for bone in bones:
        key = coord_to_grid(float(bone[0]), float(bone[1]), float(bone[2]), res)
        li = key_to_local.get(key)
        if li is not None:
            raw[li] = max(raw[li], 1.0)

    peak = float(raw.max())
    if peak < 1e-12:
        return {m[1]: 0.0 for m in masked}

    norm = np.clip(raw / peak, 0.0, 1.0)
    return {masked[li][1]: float(norm[li]) for li in range(len(masked))}


def apply_heatmap_to_scene(
    scene: VoxelScene,
    intensity_map: Dict[GridKey, float],
    res: float = VOXEL_MODULE_M,
) -> VoxelScene:
    """将热力写回 space_voxels。"""
    from dataset.voxel_schema import VoxelScene as VS

    updated: List[SpaceVoxel] = []
    for sv in scene.space_voxels:
        key = coord_to_grid(sv.x, sv.y, sv.z, res)
        updated.append(
            SpaceVoxel(
                x=sv.x,
                y=sv.y,
                z=sv.z,
                social_intensity=float(intensity_map.get(key, 0.0)),
            )
        )
    return VS(
        scene_id=scene.scene_id,
        entity_voxels=scene.entity_voxels,
        space_voxels=updated,
    )
