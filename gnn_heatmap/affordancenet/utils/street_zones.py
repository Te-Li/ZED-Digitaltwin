"""大学路街道六区划分与区域语义。"""

from __future__ import annotations

from typing import Dict, Set, Tuple

# 六区 ID
ZONE_SHOP = "shop"
ZONE_STOREFRONT = "storefront"
ZONE_SIDEWALK = "sidewalk"
ZONE_GREENBELT = "greenbelt"
ZONE_PARKING = "parking"
ZONE_LANE = "lane"

# 区域中文标签（GH 导出）
ZONE_FLOOR_CN: Dict[str, str] = {
    "店前区": ZONE_STOREFRONT,
    "人行道": ZONE_SIDEWALK,
    "车道": ZONE_LANE,
    "绿化道": ZONE_GREENBELT,
    "车位": ZONE_PARKING,
}

SHOP_COMPONENT_CN: Set[str] = {"立面", "门", "窗", "店招", "挑檐"}

# 现阶段不可变化区域
FIXED_ZONES: Set[str] = {ZONE_SHOP, ZONE_SIDEWALK, ZONE_LANE, ZONE_GREENBELT}

# 可进行设施/空间变化
VARIABLE_ZONES: Set[str] = {ZONE_STOREFRONT, ZONE_PARKING}

STREET_REGION_LABELS: Dict[str, str] = {
    ZONE_SHOP: "店铺",
    ZONE_STOREFRONT: "店前区",
    ZONE_SIDEWALK: "人行道",
    ZONE_GREENBELT: "绿化道",
    ZONE_PARKING: "车位",
    ZONE_LANE: "车道",
}

# 区域 ID → 地面实体中文标签（补全 10×6 地面格）
ZONE_ID_TO_FLOOR_CN: Dict[str, str] = {v: k for k, v in ZONE_FLOOR_CN.items()}

# 地面分区可视化配色
ZONE_FLOOR_COLORS: Dict[str, str] = {
    ZONE_LANE: "#78909C",
    ZONE_GREENBELT: "#66BB6A",
    ZONE_PARKING: "#42A5F5",
    ZONE_STOREFRONT: "#FF7043",
    ZONE_SIDEWALK: "#B0BEC5",
}

# 各区域体素格数 (nx, ny, nz)；车道为 10×8×1，其余可变/背景区默认 10×6×10
ZoneVoxelSize = Tuple[int, int, int]
DEFAULT_ZONE_VOXELS: ZoneVoxelSize = (10, 6, 10)

ZONE_VOXEL_SIZES: Dict[str, ZoneVoxelSize] = {
    ZONE_LANE: (10, 8, 1),
    ZONE_GREENBELT: (10, 6, 10),
    ZONE_PARKING: (10, 6, 10),
    ZONE_STOREFRONT: (10, 6, 10),
    ZONE_SIDEWALK: (10, 6, 10),
}

# 地面实体补全尺寸（车道整区 10×8×1 均为地面；其余区仅地面层 10×6×1）
ZONE_FLOOR_FILL_SIZES: Dict[str, ZoneVoxelSize] = {
    ZONE_LANE: (10, 8, 1),
    ZONE_GREENBELT: (10, 6, 1),
    ZONE_PARKING: (10, 6, 1),
    ZONE_STOREFRONT: (10, 6, 1),
    ZONE_SIDEWALK: (10, 6, 1),
}


def zone_voxel_size(zone_id: str) -> ZoneVoxelSize:
    return ZONE_VOXEL_SIZES.get(zone_id, DEFAULT_ZONE_VOXELS)


def zone_floor_fill_size(zone_id: str) -> ZoneVoxelSize:
    return ZONE_FLOOR_FILL_SIZES.get(zone_id, (10, 6, 1))


# 兼容旧常量（默认区尺寸）
ZONE_VOXELS_X, ZONE_VOXELS_Y, ZONE_VOXELS_Z = DEFAULT_ZONE_VOXELS

SCENE_STRIDE_M = 8.0
