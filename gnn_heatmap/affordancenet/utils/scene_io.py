"""场景 I/O 精简子集（仅类型映射）。"""

from __future__ import annotations

from dataset.voxel_schema import VoxelCategory, VoxelType


def _default_category(vtype: VoxelType) -> VoxelCategory:
    building = {VoxelType.DOOR, VoxelType.WINDOW, VoxelType.WALL, VoxelType.SHOP_SIGN, VoxelType.CANOPY}
    semi = {
        VoxelType.STEP, VoxelType.RAMP, VoxelType.PLANTER,
        VoxelType.OUTDOOR_SEATING, VoxelType.POSTER_STAND, VoxelType.DISPLAY_STAND,
    }
    if vtype in building:
        return VoxelCategory.BUILDING_INTERFACE
    if vtype in semi:
        return VoxelCategory.SEMI_PUBLIC_ZONE
    return VoxelCategory.ROADSIDE_FACILITY
