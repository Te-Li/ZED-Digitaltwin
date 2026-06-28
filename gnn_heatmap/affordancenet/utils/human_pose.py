"""简化人体姿态模板：局部关节 → 世界坐标，用于合成骨骼与可视化。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Tuple

from dataset.voxel_schema import EntityVoxel, VoxelType

SkeletonPoint = Tuple[float, float, float]
JointMap = Dict[str, SkeletonPoint]

# 骨骼连线（stick figure）
BONE_EDGES: Tuple[Tuple[str, str], ...] = (
    ("head", "neck"),
    ("neck", "chest"),
    ("chest", "pelvis"),
    ("chest", "L_shoulder"),
    ("L_shoulder", "L_elbow"),
    ("L_elbow", "L_hand"),
    ("chest", "R_shoulder"),
    ("R_shoulder", "R_elbow"),
    ("R_elbow", "R_hand"),
    ("pelvis", "L_hip"),
    ("L_hip", "L_knee"),
    ("L_knee", "L_foot"),
    ("pelvis", "R_hip"),
    ("R_hip", "R_knee"),
    ("R_knee", "R_foot"),
)

POSE_COLORS: Dict[str, str] = {
    "standing": "#546E7A",
    "walking": "#1E88E5",
    "sitting": "#8E24AA",
    "seated_table": "#6A1B9A",
    "reaching": "#FB8C00",
    "bending": "#F4511E",
    "looking_up": "#43A047",
    "leaning": "#00897B",
}

ENTITY_POSE: Dict[VoxelType, str] = {
    VoxelType.BENCH: "sitting",
    VoxelType.OUTDOOR_SEATING: "seated_table",
    VoxelType.TRASH_BIN: "bending",
    VoxelType.TREE: "looking_up",
    VoxelType.PLANTER: "looking_up",
    VoxelType.SHOP_SIGN: "reaching",
    VoxelType.DOOR: "walking",
    VoxelType.POSTER_STAND: "reaching",
    VoxelType.DISPLAY_STAND: "reaching",
    VoxelType.BIKE_RACK: "leaning",
    VoxelType.BUS_STOP: "standing",
    VoxelType.STREETLIGHT: "walking",
    VoxelType.TRAFFIC_SIGNAL: "standing",
    VoxelType.CANOPY: "standing",
    VoxelType.UTILITY_POLE: "walking",
}


@dataclass
class PoseInstance:
    pose_id: str
    label_cn: str
    anchor: SkeletonPoint
    yaw: float
    joints: JointMap = field(default_factory=dict)
    related_entity: str | None = None


def _rot_yaw(x: float, y: float, z: float, yaw: float) -> SkeletonPoint:
    c, s = math.cos(yaw), math.sin(yaw)
    return (x * c - y * s, x * s + y * c, z)


def _template_standing() -> JointMap:
    return {
        "pelvis": (0.0, 0.0, 0.92),
        "chest": (0.0, 0.0, 1.32),
        "neck": (0.0, 0.0, 1.52),
        "head": (0.0, 0.0, 1.70),
        "L_shoulder": (-0.04, 0.20, 1.38),
        "R_shoulder": (-0.04, -0.20, 1.38),
        "L_elbow": (-0.06, 0.32, 1.12),
        "R_elbow": (-0.06, -0.32, 1.12),
        "L_hand": (-0.04, 0.36, 0.88),
        "R_hand": (-0.04, -0.36, 0.88),
        "L_hip": (0.0, 0.14, 0.88),
        "R_hip": (0.0, -0.14, 0.88),
        "L_knee": (0.06, 0.14, 0.48),
        "R_knee": (0.06, -0.14, 0.48),
        "L_foot": (0.10, 0.14, 0.05),
        "R_foot": (0.10, -0.14, 0.05),
    }


def _template_walking(phase: float) -> JointMap:
    """phase∈[0,1) 控制步态周期。"""
    swing = math.sin(phase * 2 * math.pi)
    base = _template_standing()
    base["L_foot"] = (0.14 + 0.10 * swing, 0.16, 0.05 + 0.04 * max(swing, 0))
    base["R_foot"] = (0.14 - 0.10 * swing, -0.16, 0.05 + 0.04 * max(-swing, 0))
    base["L_knee"] = (0.10 + 0.08 * swing, 0.16, 0.42 + 0.06 * max(swing, 0))
    base["R_knee"] = (0.10 - 0.08 * swing, -0.16, 0.42 + 0.06 * max(-swing, 0))
    base["L_hand"] = (-0.02 - 0.12 * swing, 0.34, 0.92)
    base["R_hand"] = (-0.02 + 0.12 * swing, -0.34, 0.92)
    base["chest"] = (0.03, 0.0, 1.32)
    return base


def _template_sitting() -> JointMap:
    return {
        "pelvis": (0.0, 0.0, 0.52),
        "chest": (-0.06, 0.0, 0.98),
        "neck": (-0.08, 0.0, 1.18),
        "head": (-0.08, 0.0, 1.36),
        "L_shoulder": (-0.10, 0.18, 1.02),
        "R_shoulder": (-0.10, -0.18, 1.02),
        "L_elbow": (-0.04, 0.30, 0.82),
        "R_elbow": (-0.04, -0.30, 0.82),
        "L_hand": (0.02, 0.32, 0.68),
        "R_hand": (0.02, -0.32, 0.68),
        "L_hip": (0.0, 0.16, 0.48),
        "R_hip": (0.0, -0.16, 0.48),
        "L_knee": (0.28, 0.16, 0.38),
        "R_knee": (0.28, -0.16, 0.38),
        "L_foot": (0.38, 0.16, 0.06),
        "R_foot": (0.38, -0.16, 0.06),
    }


def _template_seated_table() -> JointMap:
    p = _template_sitting()
    p["chest"] = (-0.02, 0.0, 1.02)
    p["L_elbow"] = (0.08, 0.22, 0.78)
    p["R_elbow"] = (0.08, -0.22, 0.78)
    p["L_hand"] = (0.22, 0.18, 0.62)
    p["R_hand"] = (0.22, -0.18, 0.62)
    return p


def _template_reaching() -> JointMap:
    p = _template_standing()
    p["R_shoulder"] = (0.02, -0.18, 1.40)
    p["R_elbow"] = (0.18, -0.22, 1.28)
    p["R_hand"] = (0.38, -0.20, 1.22)
    p["L_hand"] = (-0.02, 0.30, 0.90)
    p["head"] = (0.04, -0.04, 1.68)
    return p


def _template_bending() -> JointMap:
    return {
        "pelvis": (0.0, 0.0, 0.88),
        "chest": (0.22, 0.0, 1.02),
        "neck": (0.30, 0.0, 1.12),
        "head": (0.34, 0.0, 1.26),
        "L_shoulder": (0.18, 0.18, 1.06),
        "R_shoulder": (0.18, -0.18, 1.06),
        "L_elbow": (0.32, 0.20, 0.88),
        "R_elbow": (0.32, -0.20, 0.88),
        "L_hand": (0.42, 0.16, 0.72),
        "R_hand": (0.42, -0.16, 0.72),
        "L_hip": (0.0, 0.14, 0.84),
        "R_hip": (0.0, -0.14, 0.84),
        "L_knee": (0.04, 0.14, 0.46),
        "R_knee": (0.04, -0.14, 0.46),
        "L_foot": (0.08, 0.14, 0.05),
        "R_foot": (0.08, -0.14, 0.05),
    }


def _template_looking_up() -> JointMap:
    p = _template_standing()
    p["neck"] = (-0.06, 0.0, 1.54)
    p["head"] = (-0.12, 0.0, 1.74)
    p["L_hand"] = (-0.02, 0.28, 1.02)
    p["R_hand"] = (-0.02, -0.28, 1.02)
    return p


def _template_leaning() -> JointMap:
    p = _template_standing()
    p["chest"] = (0.10, 0.0, 1.28)
    p["pelvis"] = (-0.04, 0.0, 0.90)
    p["L_hand"] = (0.18, 0.22, 1.05)
    p["R_hand"] = (0.06, -0.30, 0.92)
    return p


POSE_LABEL_CN: Dict[str, str] = {
    "standing": "站立",
    "walking": "行走",
    "sitting": "就座",
    "seated_table": "就餐饮",
    "reaching": "伸手/驻足",
    "bending": "俯身",
    "looking_up": "仰视",
    "leaning": "倚靠",
}


def build_local_pose(pose_id: str, phase: float = 0.0) -> JointMap:
    if pose_id == "walking":
        return _template_walking(phase)
    builders = {
        "standing": _template_standing,
        "sitting": _template_sitting,
        "seated_table": _template_seated_table,
        "reaching": _template_reaching,
        "bending": _template_bending,
        "looking_up": _template_looking_up,
        "leaning": _template_leaning,
    }
    fn = builders.get(pose_id, _template_standing)
    return fn()


def yaw_toward(from_xy: Tuple[float, float], to_xy: Tuple[float, float]) -> float:
    dx = to_xy[0] - from_xy[0]
    dy = to_xy[1] - from_xy[1]
    if abs(dx) + abs(dy) < 1e-6:
        return 0.0
    return math.atan2(dy, dx)


def pose_for_entity(entity: EntityVoxel) -> str:
    return ENTITY_POSE.get(entity.type, "standing")


def instantiate_pose(
    pose_id: str,
    feet_xy: Tuple[float, float],
    floor_z: float,
    yaw: float,
    *,
    phase: float = 0.0,
    related_entity: str | None = None,
) -> PoseInstance:
    local = build_local_pose(pose_id, phase)
    world: JointMap = {}
    ax, ay = feet_xy
    for name, (lx, ly, lz) in local.items():
        wx, wy, wz = _rot_yaw(lx, ly, lz, yaw)
        world[name] = (ax + wx, ay + wy, floor_z + wz)
    return PoseInstance(
        pose_id=pose_id,
        label_cn=POSE_LABEL_CN.get(pose_id, pose_id),
        anchor=(ax, ay, floor_z),
        yaw=yaw,
        joints=world,
        related_entity=related_entity,
    )


def flatten_joints(poses: Iterable[PoseInstance]) -> List[SkeletonPoint]:
    pts: List[SkeletonPoint] = []
    seen: set[Tuple[float, float, float]] = set()
    for pose in poses:
        for p in pose.joints.values():
            key = (round(p[0], 4), round(p[1], 4), round(p[2], 4))
            if key in seen:
                continue
            seen.add(key)
            pts.append(p)
    return pts


def pose_bone_segments(pose: PoseInstance) -> List[Tuple[SkeletonPoint, SkeletonPoint]]:
    segs: List[Tuple[SkeletonPoint, SkeletonPoint]] = []
    for a, b in BONE_EDGES:
        if a in pose.joints and b in pose.joints:
            segs.append((pose.joints[a], pose.joints[b]))
    return segs


def append_pose_plotly_traces(
    traces: list,
    trace_roles: list[str],
    poses: Iterable[PoseInstance],
) -> None:
    """为 Plotly 3D 图追加按姿态类型分组的骨架连线 + 关节点。"""
    import plotly.graph_objects as go

    line_buckets: Dict[str, Tuple[List, List, List, List]] = {}
    joint_buckets: Dict[str, Tuple[List, List, List, List]] = {}

    for pose in poses:
        color = POSE_COLORS.get(pose.pose_id, "#E91E63")
        lb = line_buckets.setdefault(pose.pose_id, ([], [], [], []))
        jb = joint_buckets.setdefault(pose.pose_id, ([], [], [], []))
        hover = (
            f"<b>{pose.label_cn}</b>"
            + (f" · 靠近{pose.related_entity}" if pose.related_entity else "")
        )
        for a, b in pose_bone_segments(pose):
            lb[0].extend([a[0], b[0], None])
            lb[1].extend([a[1], b[1], None])
            lb[2].extend([a[2], b[2], None])
            lb[3].append(hover)
        for name, (x, y, z) in pose.joints.items():
            jb[0].append(x)
            jb[1].append(y)
            jb[2].append(z)
            jb[3].append(f"{hover}<br>{name}")

    for pose_id, (xs, ys, zs, hovers) in line_buckets.items():
        label = POSE_LABEL_CN.get(pose_id, pose_id)
        traces.append(
            go.Scatter3d(
                x=xs, y=ys, z=zs,
                mode="lines",
                line=dict(color=POSE_COLORS.get(pose_id, "#E91E63"), width=5),
                name=f"姿态 · {label}",
                legendgroup=f"pose_{pose_id}",
                hoverinfo="skip",
            )
        )
        trace_roles.append("skeleton")

    for pose_id, (xs, ys, zs, hovers) in joint_buckets.items():
        label = POSE_LABEL_CN.get(pose_id, pose_id)
        traces.append(
            go.Scatter3d(
                x=xs, y=ys, z=zs,
                mode="markers",
                marker=dict(size=3, color=POSE_COLORS.get(pose_id, "#E91E63"), opacity=0.9),
                name=f"关节 · {label}",
                legendgroup=f"pose_{pose_id}",
                showlegend=False,
                text=hovers,
                hovertemplate="%{text}<extra></extra>",
            )
        )
        trace_roles.append("skeleton")

