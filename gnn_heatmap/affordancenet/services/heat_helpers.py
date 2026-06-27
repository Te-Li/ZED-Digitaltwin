"""实体标注与骨骼热力扩散辅助函数。"""

from __future__ import annotations

from typing import List

from dataset.voxel_schema import SpaceVoxel
from utils.skeleton_heatmap import apply_heatmap_to_scene, compute_zone_masked_skeleton_heatmap
from utils.street_zones import STREET_REGION_LABELS, ZONE_FLOOR_CN, ZONE_FLOOR_COLORS
from utils.street_elements_io import element_color_for_name
from utils.university_road_io import mask_space_to_active_zone
from utils.voxel_grid import coord_to_grid

TYPE_COLORS: dict[str, str] = {
    "tree": "#2E7D32",
    "bench": "#8D6E63",
    "streetlight": "#FDD835",
    "utility_pole": "#9E9E9E",
    "window": "#546E7A",
    "wall": "#37474F",
    "door": "#6D4C41",
    "shop_sign": "#E91E63",
    "canopy": "#795548",
    "planter": "#43A047",
    "bus_stop": "#1E88E5",
    "fence": "#757575",
    "bollard": "#BDBDBD",
    "outdoor_seating": "#FF7043",
    "bike_rack": "#607D8B",
    "trash_bin": "#424242",
    "traffic_signal": "#D32F2F",
    "running_track": "#AB47BC",
    "step": "#A1887F",
    "ramp": "#90A4AE",
    "poster_stand": "#EC407A",
    "display_stand": "#FFA726",
}
# 说明：street elements 场景颜色来自 CSV「颜色代码」列（见 street elements(2).csv）

FLOOR_CN_COLORS = {
    "车道": ZONE_FLOOR_COLORS["lane"],
    "绿化道": ZONE_FLOOR_COLORS["greenbelt"],
    "车位": ZONE_FLOOR_COLORS["parking"],
    "店前区": ZONE_FLOOR_COLORS["storefront"],
    "人行道": ZONE_FLOOR_COLORS["sidewalk"],
}

TYPE_CN_LABELS: dict[str, str] = {
    "wall": "立面", "door": "门", "window": "窗", "shop_sign": "店招",
    "canopy": "挑檐", "tree": "树干", "bench": "长凳", "streetlight": "路灯",
    "planter": "树池/花坛", "outdoor_seating": "桌椅单元",
    "poster_stand": "立展板", "display_stand": "自动售货机",
    "utility_pole": "电压箱", "bike_rack": "自行车架",
    "trash_bin": "垃圾桶", "bollard": "消防栓",
    "bus_stop": "电话亭", "fence": "围栏", "traffic_signal": "公交站牌",
}


def _entity_label(rec, ev) -> str:
    pos = f"{ev.x:.3f},{ev.y:.3f},{ev.z:.3f}"
    cn = rec.entity_source_cn.get(pos, "")
    if cn in ZONE_FLOOR_CN or cn in FLOOR_CN_COLORS:
        return cn
    vt = ev.type.value
    return TYPE_CN_LABELS.get(vt, vt) if not cn else cn


def _entity_color(rec, label: str, ev) -> str:
    if label in FLOOR_CN_COLORS:
        return FLOOR_CN_COLORS[label]
    color_map = rec.meta.get("element_colors") or {}
    return element_color_for_name(label, ev.type.value, color_map=color_map)


def _entity_hover(rec, ev, label: str) -> str:
    ix, iy, iz = coord_to_grid(ev.x, ev.y, ev.z)
    pos = f"{ev.x:.3f},{ev.y:.3f},{ev.z:.3f}"
    zid = rec.entity_zones.get(pos, "")
    region = STREET_REGION_LABELS.get(zid, zid)
    return (
        f"<b>{rec.scene_id}</b> · 实体<br>"
        f"{label} · {region}<br>"
        f"格索引 (ix,iy,iz)=({ix},{iy},{iz})<br>"
        f"400mm 体素块 · 中心 ({ev.x:.2f},{ev.y:.2f},{ev.z:.2f}) m"
    )


def _heatmap_from_skeleton(rec, skeletons, active_bounds, sigma: float) -> list[SpaceVoxel]:
    heat = compute_zone_masked_skeleton_heatmap(
        rec.scene, skeletons, active_bounds, sigma=sigma,
    )
    heated_scene = apply_heatmap_to_scene(rec.scene, heat)
    if active_bounds:
        return mask_space_to_active_zone(heated_scene.space_voxels, active_bounds)
    return heated_scene.space_voxels
