"""street elements CSV 要素表：实体命名、id 与颜色映射。"""

from __future__ import annotations

import ast
import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from dataset.voxel_schema import VoxelType

# street elements CSV 标准要素名 → 体素类型
ELEMENT_TO_VOXEL: Dict[str, VoxelType] = {
    "自动售货机": VoxelType.DISPLAY_STAND,
    "公告栏": VoxelType.POSTER_STAND,
    "电话亭": VoxelType.BUS_STOP,
    "公交站牌": VoxelType.BUS_STOP,
    "树干": VoxelType.TREE,
    "邮筒": VoxelType.POSTER_STAND,
    "垃圾桶": VoxelType.TRASH_BIN,
    "立展板": VoxelType.POSTER_STAND,
    "消防栓": VoxelType.BOLLARD,
    "自行车架": VoxelType.BIKE_RACK,
    "桌椅单元": VoxelType.OUTDOOR_SEATING,
    "石墩": VoxelType.BOLLARD,
    "餐饮外摆": VoxelType.OUTDOOR_SEATING,
    "长凳": VoxelType.BENCH,
    "长凳2": VoxelType.BENCH,
}

NAME_ALIASES: Dict[str, str] = {
    "公告板": "公告栏",
    "公交站台": "公交站牌",
    "树": "树干",
    "a-树": "树干",
    "a-树干": "树干",
    "树冠": "树干",
    "垃圾箱": "垃圾桶",
    "餐饮外摆": "桌椅单元",
    "广告": "立展板",
    "店前区广告": "自动售货机",
}

# 体素类型英文键回退色（CSV 无颜色代码时使用）
VOXEL_TYPE_COLORS: Dict[str, str] = {
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


@dataclass
class StreetElementSpec:
    name: str
    length: int
    width: int
    height: int
    id_start: Optional[int] = None
    id_end: Optional[int] = None
    nums: Optional[int] = None
    english_name: str = ""
    color_code: str = ""


@dataclass
class StreetElementCatalog:
    source_path: str
    elements: List[StreetElementSpec] = field(default_factory=list)
    name_to_spec: Dict[str, StreetElementSpec] = field(default_factory=dict)
    id_to_name: Dict[int, str] = field(default_factory=dict)
    name_to_color: Dict[str, str] = field(default_factory=dict)

    def canonical_name(self, raw: str) -> str:
        name = normalize_element_name(raw)
        if name in self.name_to_spec:
            return name
        if name in NAME_ALIASES:
            alias = NAME_ALIASES[name]
            if alias in self.name_to_spec or alias in ELEMENT_TO_VOXEL:
                return alias
        return name

    def resolve_voxel_type(self, raw: str) -> VoxelType:
        name = self.canonical_name(raw)
        if name in ELEMENT_TO_VOXEL:
            return ELEMENT_TO_VOXEL[name]
        for key, vt in ELEMENT_TO_VOXEL.items():
            if key in name or name in key:
                return vt
        return VoxelType.BENCH

    def name_for_id(self, element_id: int) -> Optional[str]:
        return self.id_to_name.get(int(element_id))

    def element_colors(self) -> Dict[str, str]:
        return dict(self.name_to_color)

    def to_dict(self) -> dict:
        return {
            "source_file": Path(self.source_path).name,
            "element_count": len(self.elements),
            "element_colors": self.element_colors(),
            "elements": [
                {
                    "name": s.name,
                    "english": s.english_name or None,
                    "color": s.color_code or None,
                    "length": s.length,
                    "width": s.width,
                    "height": s.height,
                    "id_range": [s.id_start, s.id_end] if s.id_start is not None else None,
                    "nums": s.nums,
                }
                for s in self.elements
            ],
        }


def normalize_element_name(name: str) -> str:
    name = (name or "").strip()
    if "|" in name:
        name = name.split("|", 1)[0].strip()
    return name


def _cell(row: dict, *keys: str) -> str:
    for key in keys:
        val = row.get(key)
        if val not in (None, ""):
            return str(val).strip()
    for k, v in row.items():
        if not k:
            continue
        for key in keys:
            if key in k and v not in (None, ""):
                return str(v).strip()
    return ""


def _normalize_hex_color(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if not raw.startswith("#"):
        raw = f"#{raw}"
    return raw.upper() if len(raw) == 4 else raw  # keep #RGB as-is, #RRGGBB as-is


def _parse_id_range(raw: str) -> tuple[Optional[int], Optional[int]]:
    raw = (raw or "").strip()
    if not raw:
        return None, None
    try:
        parsed = ast.literal_eval(raw)
        if isinstance(parsed, (list, tuple)) and len(parsed) >= 2:
            return int(parsed[0]), int(parsed[1])
    except (SyntaxError, ValueError, TypeError):
        pass
    return None, None


def load_street_elements_csv(path: str | Path) -> StreetElementCatalog:
    """加载 street elements*.csv（含 id_range、颜色代码 列）。"""
    path = Path(path)
    catalog = StreetElementCatalog(source_path=str(path.resolve()))

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames or "要素" not in reader.fieldnames:
            raise ValueError(f"{path.name} 缺少「要素」列，请使用 street elements CSV 格式")

        for row in reader:
            raw_name = (row.get("要素") or "").strip()
            if not raw_name:
                continue
            name = normalize_element_name(raw_name)
            color = _normalize_hex_color(_cell(row, "颜色代码", "颜色", "color"))
            english = _cell(row, "英文", "english")
            spec = StreetElementSpec(
                name=name,
                length=int(row.get("长度") or 1),
                width=int(row.get("宽度") or 1),
                height=int(row.get("高度") or 1),
                nums=int(row["nums"]) if row.get("nums") not in (None, "") else None,
                english_name=english,
                color_code=color,
            )
            id_start, id_end = _parse_id_range(row.get("id_range", ""))
            spec.id_start, spec.id_end = id_start, id_end
            if id_start is not None and id_end is not None:
                for eid in range(id_start, id_end + 1):
                    catalog.id_to_name[eid] = name

            if name not in catalog.name_to_spec:
                catalog.name_to_spec[name] = spec
                catalog.elements.append(spec)
                if color:
                    catalog.name_to_color[name] = color

    if not catalog.elements:
        raise ValueError(f"{path.name} 未解析到任何要素行")
    return catalog


def find_paired_street_elements_csv(json_path: str | Path) -> Optional[Path]:
    json_path = Path(json_path)
    parent = json_path.parent
    stem = json_path.stem

    suffix_match = re.search(r"(\(\d+\))$", stem)
    candidates: List[Path] = []
    if suffix_match:
        suffix = suffix_match.group(1)
        candidates.append(parent / f"street elements{suffix}.csv")

    candidates.extend([
        parent / "street elements.csv",
        parent / "street_elements.csv",
    ])

    bundle_root = Path(__file__).resolve().parents[2]
    candidates.extend([
        bundle_root / "street elements(2).csv",
        bundle_root / "street elements(1).csv",
    ])

    seen: set[Path] = set()
    for cand in candidates:
        resolved = cand.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if cand.is_file():
            return cand
    return None


def resolve_cell_element_name(cell: dict, catalog: StreetElementCatalog) -> str:
    for key in ("element_id", "id", "elementId"):
        if key in cell and cell[key] not in (None, ""):
            name = catalog.name_for_id(int(cell[key]))
            if name:
                return name
            raise ValueError(f"未知 element id: {cell[key]}")

    raw = str(cell.get("type", "")).strip()
    if raw.isdigit():
        name = catalog.name_for_id(int(raw))
        if name:
            return name

    return catalog.canonical_name(raw)


def element_color_for_name(
    label_cn: str,
    voxel_type: str = "",
    color_map: Optional[Dict[str, str]] = None,
) -> str:
    """按 CSV 要素表中的颜色代码取色。"""
    colors = color_map or {}
    name = normalize_element_name(label_cn)
    if name in colors:
        return colors[name]
    alias = NAME_ALIASES.get(name)
    if alias and alias in colors:
        return colors[alias]
    return VOXEL_TYPE_COLORS.get(voxel_type, "rgb(140,140,140)")
