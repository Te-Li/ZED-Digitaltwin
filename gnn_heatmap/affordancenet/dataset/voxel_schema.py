"""体素场景数据模式定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List


class VoxelCategory(str, Enum):
    """实体体素三大类语义划分。"""

    ROADSIDE_FACILITY = "roadside_facility"
    SEMI_PUBLIC_ZONE = "semi_public_zone"
    BUILDING_INTERFACE = "building_interface"


class VoxelType(str, Enum):
    """具体街道元素类型。"""

    # 路侧设施
    BOLLARD = "bollard"
    FENCE = "fence"
    STREETLIGHT = "streetlight"
    TREE = "tree"
    UTILITY_POLE = "utility_pole"
    TRASH_BIN = "trash_bin"
    BIKE_RACK = "bike_rack"
    TRAFFIC_SIGNAL = "traffic_signal"
    BENCH = "bench"
    BUS_STOP = "bus_stop"
    RUNNING_TRACK = "running_track"

    # 半公共过渡区
    STEP = "step"
    RAMP = "ramp"
    PLANTER = "planter"
    OUTDOOR_SEATING = "outdoor_seating"
    POSTER_STAND = "poster_stand"
    DISPLAY_STAND = "display_stand"

    # 建筑界面变量
    DOOR = "door"
    WINDOW = "window"
    WALL = "wall"
    SHOP_SIGN = "shop_sign"
    CANOPY = "canopy"


# one-hot 维度常量（与 GraphBuilder 特征向量对齐）
NUM_CATEGORIES = 3
NUM_VOXEL_TYPES = len(VoxelType)  # 21
VOXEL_TYPE_ONEHOT_DIM = 22  # 规范要求 22 维，不足则零填充


@dataclass
class EntityVoxel:
    """实体体素：仅记录类别、类型与坐标，不含热力值。"""

    category: VoxelCategory
    type: VoxelType
    x: float
    y: float
    z: float


@dataclass
class SpaceVoxel:
    """可活动空间体素：记录坐标与社交强度。"""

    x: float
    y: float
    z: float
    social_intensity: float  # [0.0, 1.0]


@dataclass
class VoxelScene:
    """完整街道体素场景。"""

    scene_id: str
    entity_voxels: List[EntityVoxel] = field(default_factory=list)
    space_voxels: List[SpaceVoxel] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 JSON 兼容字典。"""
        return {
            "scene_id": self.scene_id,
            "entity_voxels": [
                {
                    "category": v.category.value,
                    "type": v.type.value,
                    "x": v.x,
                    "y": v.y,
                    "z": v.z,
                }
                for v in self.entity_voxels
            ],
            "space_voxels": [
                {
                    "x": v.x,
                    "y": v.y,
                    "z": v.z,
                    "social_intensity": v.social_intensity,
                }
                for v in self.space_voxels
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> VoxelScene:
        """从字典反序列化。"""
        entity_voxels = [
            EntityVoxel(
                category=VoxelCategory(e["category"]),
                type=VoxelType(e["type"]),
                x=float(e["x"]),
                y=float(e["y"]),
                z=float(e["z"]),
            )
            for e in data.get("entity_voxels", [])
        ]
        space_voxels = [
            SpaceVoxel(
                x=float(s["x"]),
                y=float(s["y"]),
                z=float(s["z"]),
                social_intensity=float(s["social_intensity"]),
            )
            for s in data.get("space_voxels", [])
        ]
        return cls(
            scene_id=str(data["scene_id"]),
            entity_voxels=entity_voxels,
            space_voxels=space_voxels,
        )
