"""训练场景记录精简子集（无 xls 解析依赖）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from dataset.voxel_schema import VoxelScene, VoxelType

TRAINING_CN_TYPE_MAP: Dict[str, VoxelType] = {
    "地面": VoxelType.RUNNING_TRACK,
    "立面": VoxelType.WALL,
    "窗": VoxelType.WINDOW,
    "门": VoxelType.DOOR,
    "店招": VoxelType.SHOP_SIGN,
    "挑檐": VoxelType.CANOPY,
    "店前区": VoxelType.OUTDOOR_SEATING,
    "树": VoxelType.TREE,
    "a-树": VoxelType.TREE,
    "a-树干": VoxelType.TREE,
    "树池": VoxelType.PLANTER,
    "花坛": VoxelType.PLANTER,
    "座椅": VoxelType.BENCH,
    "垃圾桶": VoxelType.TRASH_BIN,
    "垃圾箱": VoxelType.TRASH_BIN,
    "公交站台": VoxelType.BUS_STOP,
    "电话亭": VoxelType.BUS_STOP,
    "自行车架": VoxelType.BIKE_RACK,
    "自行车+架": VoxelType.BIKE_RACK,
    "电线": VoxelType.UTILITY_POLE,
    "路桩": VoxelType.BOLLARD,
    "围栏": VoxelType.FENCE,
    "路障": VoxelType.BOLLARD,
    "路障+围栏": VoxelType.FENCE,
    "路障＋围栏": VoxelType.FENCE,
    "广告": VoxelType.POSTER_STAND,
    "店前区广告": VoxelType.DISPLAY_STAND,
    "信号灯交通": VoxelType.TRAFFIC_SIGNAL,
    "交通信号灯": VoxelType.TRAFFIC_SIGNAL,
}


@dataclass
class TrainingSceneRecord:
    scene_id: str
    focus_category: str
    source_path: str
    world_offset: Tuple[float, float]
    is_augmented: bool
    scene: VoxelScene
    skeleton_points: List[Tuple[float, float, float]]
    meta: Dict[str, float]
