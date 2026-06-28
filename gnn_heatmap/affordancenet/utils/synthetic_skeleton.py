"""大学路场景 — 实体感知、多姿态合成骨骼。"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Set, Tuple

import numpy as np
from scipy.spatial import cKDTree

from dataset.voxel_schema import EntityVoxel, VoxelType
from utils.human_pose import (
    PoseInstance,
    flatten_joints,
    instantiate_pose,
    pose_for_entity,
    yaw_toward,
)
from utils.street_zones import ZONE_FLOOR_CN
from utils.university_road_io import (
    UniversityRoadRecord,
    ZoneBounds,
    active_zone_bounds,
    space_voxel_in_bounds,
)
from utils.voxel_grid import VOXEL_MODULE_M, GridKey, coord_to_grid

SkeletonPoint = Tuple[float, float, float]

ATTRACTOR_TYPES: Set[VoxelType] = {
    VoxelType.BENCH,
    VoxelType.TREE,
    VoxelType.OUTDOOR_SEATING,
    VoxelType.DOOR,
    VoxelType.SHOP_SIGN,
    VoxelType.TRASH_BIN,
    VoxelType.BUS_STOP,
    VoxelType.POSTER_STAND,
    VoxelType.DISPLAY_STAND,
    VoxelType.PLANTER,
    VoxelType.STREETLIGHT,
    VoxelType.BIKE_RACK,
    VoxelType.TRAFFIC_SIGNAL,
    VoxelType.CANOPY,
    VoxelType.UTILITY_POLE,
}

FLOOR_CN = set(ZONE_FLOOR_CN.keys())
DEFAULT_STANDING_HEIGHT_M = 1.75


@dataclass
class SyntheticSkeletonResult:
    """合成骨骼：扁平点集（热力扩散）+ 姿态实例（可视化）。"""

    points: List[SkeletonPoint]
    poses: List[PoseInstance]


def _floor_base_z(record: UniversityRoadRecord, bounds: ZoneBounds, active: str) -> float:
    zs: List[float] = []
    for ev in record.scene.entity_voxels:
        pos = f"{ev.x:.3f},{ev.y:.3f},{ev.z:.3f}"
        if record.entity_zones.get(pos) != active:
            continue
        if record.entity_source_cn.get(pos, "") in FLOOR_CN:
            zs.append(ev.z)
    if zs:
        return float(np.median(zs))
    return bounds[4] + VOXEL_MODULE_M * 0.5


def _occupied_keys(record: UniversityRoadRecord) -> Set[GridKey]:
    return {coord_to_grid(ev.x, ev.y, ev.z) for ev in record.scene.entity_voxels}


def _candidate_walk_spaces(
    record: UniversityRoadRecord,
    bounds: ZoneBounds,
    floor_z: float,
    occupied: Set[GridKey],
) -> List[Tuple[float, float, float]]:
    foot_z = floor_z + 0.05
    tol = VOXEL_MODULE_M * 0.55
    cands: List[Tuple[float, float, float]] = []
    seen: Set[GridKey] = set()
    for sv in record.scene.space_voxels:
        if not space_voxel_in_bounds(sv, bounds):
            continue
        if abs(sv.z - foot_z) > tol and abs(sv.z - (floor_z + 0.4)) > tol:
            continue
        key = coord_to_grid(sv.x, sv.y, sv.z)
        if key in occupied or key in seen:
            continue
        seen.add(key)
        cands.append((sv.x, sv.y, sv.z))
    return cands


def _snap_xy(
    point: Tuple[float, float, float],
    tree: cKDTree,
    candidates: List[Tuple[float, float, float]],
    max_dist: float = 1.6,
) -> Tuple[float, float] | None:
    if not candidates:
        return None
    dist, idx = tree.query(point)
    if dist > max_dist:
        return None
    c = candidates[int(idx)]
    return (c[0], c[1])


def _interpolate_path(
    a: Tuple[float, float, float],
    b: Tuple[float, float, float],
    step: float = VOXEL_MODULE_M,
) -> List[Tuple[float, float, float]]:
    ax, ay, az = a
    bx, by, bz = b
    span = max(abs(bx - ax), abs(by - ay), abs(bz - az), step)
    n = max(2, int(span / step) + 1)
    return [
        (ax + t * (bx - ax), ay + t * (by - ay), az + t * (bz - az))
        for t in np.linspace(0.0, 1.0, n)
    ]


def _attractor_entities(record: UniversityRoadRecord, active: str) -> List[EntityVoxel]:
    out: List[EntityVoxel] = []
    for ev in record.scene.entity_voxels:
        pos = f"{ev.x:.3f},{ev.y:.3f},{ev.z:.3f}"
        if record.entity_zones.get(pos) != active:
            continue
        if record.entity_source_cn.get(pos, "") in FLOOR_CN:
            continue
        if ev.type in ATTRACTOR_TYPES:
            out.append(ev)
    return out


def _corridor_waypoints(bounds: ZoneBounds, walk_z: float, n_rows: int = 3) -> List[Tuple[float, float, float]]:
    x0, x1, y0, y1, _z0, _z1 = bounds
    margin = VOXEL_MODULE_M * 1.5
    xs = np.arange(x0 + margin, x1 - margin + 1e-6, VOXEL_MODULE_M * 2.5)
    if len(xs) < 2:
        xs = np.array([(x0 + x1) / 2])
    ys = np.linspace(y0 + margin, y1 - margin, max(2, n_rows))
    waypoints: List[Tuple[float, float, float]] = []
    for row_i, y in enumerate(ys):
        row_xs = xs if row_i % 2 == 0 else xs[::-1]
        for x in row_xs:
            waypoints.append((float(x), float(y), walk_z))
    return waypoints


def _entity_cn(ev: EntityVoxel, record: UniversityRoadRecord) -> str:
    pos = f"{ev.x:.3f},{ev.y:.3f},{ev.z:.3f}"
    return record.entity_source_cn.get(pos, ev.type.value)


def _add_pose(
    poses: List[PoseInstance],
    used_xy: Set[Tuple[float, float]],
    *,
    feet_xy: Tuple[float, float],
    floor_z: float,
    pose_id: str,
    yaw: float,
    phase: float = 0.0,
    related: str | None = None,
) -> bool:
    key = (round(feet_xy[0], 2), round(feet_xy[1], 2))
    if key in used_xy:
        return False
    used_xy.add(key)
    poses.append(
        instantiate_pose(
            pose_id, feet_xy, floor_z, yaw, phase=phase, related_entity=related,
        )
    )
    return True


def generate_synthetic_skeleton(
    record: UniversityRoadRecord,
    n_points: int = 100,
    seed: int = 42,
    standing_height_m: float = DEFAULT_STANDING_HEIGHT_M,
) -> List[SkeletonPoint]:
    """兼容旧接口：仅返回扁平骨骼点。"""
    return generate_synthetic_poses(
        record, n_points=n_points, seed=seed, standing_height_m=standing_height_m,
    ).points


def generate_synthetic_poses(
    record: UniversityRoadRecord,
    n_points: int = 100,
    seed: int = 42,
    standing_height_m: float = DEFAULT_STANDING_HEIGHT_M,
) -> SyntheticSkeletonResult:
    """
    根据实体分布生成多姿态人体：

    - 座椅/外摆 → 就座
    - 垃圾桶 → 俯身
    - 树/花坛 → 仰视
    - 店招/展板 → 伸手驻足
    - 通行路径 → 行走（步态周期变化）
    - 其余设施 → 站立/倚靠
    """
    del standing_height_m  # 身高已编码在各姿态模板中
    bounds = active_zone_bounds(record)
    if bounds is None:
        return SyntheticSkeletonResult(points=[], poses=[])

    active = record.meta.get("active_zone", "")
    floor_z = _floor_base_z(record, bounds, active)
    foot_z = floor_z + 0.05
    occupied = _occupied_keys(record)
    candidates = _candidate_walk_spaces(record, bounds, floor_z, occupied)
    if not candidates:
        return SyntheticSkeletonResult(points=[], poses=[])

    rng = random.Random(seed)
    tree = cKDTree(candidates)
    poses: List[PoseInstance] = []
    used_xy: Set[Tuple[float, float]] = set()

    # 1) 设施交互姿态（面向设施）
    attractors = _attractor_entities(record, active)
    rng.shuffle(attractors)
    for ev in attractors:
        feet = _snap_xy((ev.x, ev.y, foot_z), tree, candidates, max_dist=2.2)
        if feet is None:
            continue
        pose_id = pose_for_entity(ev)
        yaw = yaw_toward(feet, (ev.x, ev.y))
        _add_pose(
            poses, used_xy,
            feet_xy=feet, floor_z=floor_z, pose_id=pose_id, yaw=yaw,
            related=_entity_cn(ev, record),
        )

    # 2) 通行路径 — 行走姿态
    waypoints = _corridor_waypoints(bounds, foot_z)
    path_idx = 0
    if len(waypoints) >= 2:
        for i in range(len(waypoints) - 1):
            seg = _interpolate_path(waypoints[i], waypoints[i + 1])
            for j, pt in enumerate(seg):
                feet = _snap_xy(pt, tree, candidates, max_dist=1.0)
                if feet is None:
                    continue
                nxt = seg[min(j + 1, len(seg) - 1)]
                yaw = yaw_toward(feet, (nxt[0], nxt[1]))
                phase = (path_idx % 8) / 8.0
                path_idx += 1
                if _add_pose(
                    poses, used_xy,
                    feet_xy=feet, floor_z=floor_z, pose_id="walking", yaw=yaw, phase=phase,
                ):
                    if len(poses) >= n_points:
                        break
            if len(poses) >= n_points:
                break

    # 3) 不足则补站立/行走
    if len(poses) < max(8, n_points // 4):
        shuffled = list(candidates)
        rng.shuffle(shuffled)
        for cx, cy, _cz in shuffled:
            feet = (cx, cy)
            pose_id = "standing" if rng.random() < 0.35 else "walking"
            phase = rng.random()
            if _add_pose(
                poses, used_xy,
                feet_xy=feet, floor_z=floor_z, pose_id=pose_id,
                yaw=rng.uniform(-math.pi, math.pi), phase=phase,
            ):
                if len(poses) >= n_points:
                    break

    if len(poses) > n_points:
        rng.shuffle(poses)
        poses = poses[:n_points]

    return SyntheticSkeletonResult(points=flatten_joints(poses), poses=poses)
