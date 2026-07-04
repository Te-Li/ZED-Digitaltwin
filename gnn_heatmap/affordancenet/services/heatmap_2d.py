"""三维热力 JSON → 二维平面热力（顶视 max 投影，实体格留白）。"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Optional, Tuple

import numpy as np

PACK_FORMAT_2D = "affordancenet-heatmap-2d"
PACK_VERSION = 1

VOXEL_MODULE_M = 0.4


@dataclass
class Heatmap2DOptions:
    """二维网格：400mm × 400mm，默认 10（长）× 6（宽）格。"""

    cell_m: float = VOXEL_MODULE_M
    nx: int = 10
    ny: int = 6
    projection: str = "max_z"
    mask_entity_cells: bool = True

    @property
    def width_m(self) -> float:
        return self.nx * self.cell_m

    @property
    def height_m(self) -> float:
        return self.ny * self.cell_m


def _entity_footprint_mask(pack: dict[str, Any], nx: int, ny: int) -> np.ndarray:
    """顶视投影：实体占据的 (ix, iy) 格设为 True。"""
    mask = np.zeros((ny, nx), dtype=bool)

    for e in pack.get("entities") or []:
        ix = e.get("grid_ix", e.get("grid_x"))
        iy = e.get("grid_iy", e.get("grid_y"))
        if ix is None or iy is None:
            res = float(pack.get("voxel_module_m", VOXEL_MODULE_M))
            ix = int(round((float(e["x"]) - res / 2) / res))
            iy = int(round((float(e["y"]) - res / 2) / res))
        ix, iy = int(ix), int(iy)
        if 0 <= ix < nx and 0 <= iy < ny:
            mask[iy, ix] = True

    for c in pack.get("cells_with_heat") or []:
        if not c.get("is_entity"):
            continue
        ix, iy = int(c["x"]), int(c["y"])
        if 0 <= ix < nx and 0 <= iy < ny:
            mask[iy, ix] = True

    return np.zeros((ny, nx), dtype=bool)


def _coord_to_cell(x: float, y: float, cell_m: float, nx: int, ny: int) -> Tuple[int, int] | None:
    if x < 0 or y < 0:
        return None
    ix = int(x / cell_m)
    iy = int(y / cell_m)
    if ix >= nx or iy >= ny:
        return None
    return ix, iy


def _collect_voxel_samples(
    pack: dict[str, Any],
    *,
    entity_mask: np.ndarray,
    options: Heatmap2DOptions,
) -> List[Tuple[float, float, float, float]]:
    """仅收集行为空间热力样本，跳过实体占据格。"""
    samples: List[Tuple[float, float, float, float]] = []
    res = float(pack.get("voxel_module_m", options.cell_m))
    nx, ny = options.nx, options.ny

    for v in pack.get("heatmap_voxels") or []:
        intensity = float(v.get("intensity", 0.0))
        if intensity <= 1e-6:
            continue
        x, y, z = float(v["x"]), float(v["y"]), float(v["z"])
        ix = v.get("grid_ix", v.get("grid_x"))
        iy = v.get("grid_iy", v.get("grid_y"))
        if ix is not None and iy is not None:
            ix, iy = int(ix), int(iy)
        else:
            cell = _coord_to_cell(x, y, options.cell_m, nx, ny)
            if cell is None:
                continue
            ix, iy = cell
        if iy >= ny or ix >= nx:
            continue
        if entity_mask[iy, ix]:
            continue
        samples.append((x, y, z, intensity))

    if samples:
        return samples

    for c in pack.get("cells_with_heat") or []:
        if c.get("is_entity"):
            continue
        intensity = float(c.get("intensity", 0.0))
        if intensity <= 1e-6:
            continue
        ix, iy, iz = int(c["x"]), int(c["y"]), int(c["z"])
        if ix >= nx or iy >= ny:
            continue
        if entity_mask[iy, ix]:
            continue
        x = (ix + 0.5) * res
        y = (iy + 0.5) * res
        z = (iz + 0.5) * res
        samples.append((x, y, z, intensity))

    return samples


def _grid_to_json_list(grid: np.ndarray) -> list[list[float | None]]:
    out: list[list[float | None]] = []
    for row in grid:
        out.append([None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v) for v in row])
    return out


def project_heatmap_3d_to_2d(
    pack: dict[str, Any],
    options: Optional[Heatmap2DOptions] = None,
) -> dict[str, Any]:
    options = options or Heatmap2DOptions()
    nx, ny = options.nx, options.ny
    cell_m = options.cell_m

    entity_mask = _entity_footprint_mask(pack, nx, ny) if options.mask_entity_cells else np.zeros((ny, nx), dtype=bool)
    print(entity_mask, "llllllll")
    grid = np.zeros((ny, nx), dtype=np.float64)
    count = np.zeros((ny, nx), dtype=np.int32)
    samples = _collect_voxel_samples(pack, entity_mask=entity_mask, options=options)

    for x, y, _z, intensity in samples:
        cell = _coord_to_cell(x, y, cell_m, nx, ny)
        if cell is None:
            continue
        ix, iy = cell
        if entity_mask[iy, ix]:
            continue
        if options.projection == "max_z":
            grid[iy, ix] = max(grid[iy, ix], intensity)
        else:
            grid[iy, ix] += intensity
            count[iy, ix] += 1

    if options.projection == "mean_z":
        mask = count > 0
        grid[mask] /= count[mask]

    if options.mask_entity_cells:
        grid[entity_mask] = np.nan

    active = grid[~entity_mask & ~np.isnan(grid) & (grid > 1e-6)]
    entity_cell_count = int(entity_mask.sum())

    return {
        "format": PACK_FORMAT_2D,
        "version": PACK_VERSION,
        "source_format": pack.get("format"),
        "source_file": pack.get("source_file"),
        "scene_id": pack.get("scene_id"),
        "region_label": pack.get("region_label"),
        "heatmap_method": pack.get("heatmap_method"),
        "projection": options.projection,
        "width_m": options.width_m,
        "height_m": options.height_m,
        "nx": nx,
        "ny": ny,
        "cell_x_m": cell_m,
        "cell_y_m": cell_m,
        "axis": {"x": "width_m", "y": "height_m", "origin": "bottom_left"},
        "entity_mask_applied": options.mask_entity_cells,
        "entity_cell_count": entity_cell_count,
        "intensity_range": {
            "min": float(active.min()) if active.size else 0.0,
            "max": float(active.max()) if active.size else 0.0,
        },
        "values": _grid_to_json_list(grid),
        "social_vitality": pack.get("social_vitality"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>二维社交热力图 — {scene_id}</title>
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <style>
    body {{ margin:0; font-family:"Segoe UI","Microsoft YaHei",sans-serif; background:#1a1a2e; color:#eee; }}
    header {{ padding:16px 24px; background:#16213e; border-bottom:1px solid #0f3460; }}
    h1 {{ margin:0 0 6px; font-size:1.25rem; }}
    p {{ margin:0; color:#94a3b8; font-size:0.85rem; }}
    .meta {{ margin-top:8px; display:flex; gap:20px; flex-wrap:wrap; font-size:0.8rem; color:#cbd5e1; }}
    #chart {{ width:100%; height:calc(100vh - 110px); }}
  </style>
</head>
<body>
  <header>
    <h1>二维社交热力图（仅热力 · 实体格留白）</h1>
    <p id="subtitle"></p>
    <div class="meta" id="meta"></div>
  </header>
  <div id="chart"></div>
  <script>
    const d = {data_json};
    (function() {{
      function jet(t) {{
        t = Math.max(0, Math.min(1, t));
        return [
          Math.round(Math.max(0, Math.min(1, 1.5 - Math.abs(4*t-3))) * 255),
          Math.round(Math.max(0, Math.min(1, 1.5 - Math.abs(4*t-2))) * 255),
          Math.round(Math.max(0, Math.min(1, 1.5 - Math.abs(4*t-1))) * 255),
        ];
      }}
      const cs = Array.from({{length:21}}, (_, i) => {{
        const t = i/20; const [r,g,b] = jet(t); return [t, `rgb(${{r}},${{g}},${{b}})`];
      }});
      const w = d.width_m ?? 4, h = d.height_m ?? 2.4;
      const nx = d.nx ?? d.values[0].length, ny = d.ny ?? d.values.length;
      const cell = d.cell_x_m ?? 0.4;
      const vmax = (d.intensity_range?.max ?? 1) || 1;
      const x = Array.from({{length:nx}}, (_, i) => +((i+0.5)*cell).toFixed(3));
      const y = Array.from({{length:ny}}, (_, i) => +((i+0.5)*cell).toFixed(3));
      document.getElementById("subtitle").textContent =
        `${{d.scene_id||""}} · ${{w}}m × ${{h}}m · ${{cell*1000}}mm 格 · ${{d.projection||"max_z"}}`;
      const svi = d.social_vitality?.index;
      document.getElementById("meta").innerHTML = [
        `<span>网格: <b>${{nx}}×${{ny}}</b></span>`,
        d.entity_cell_count != null ? `<span>实体留白: <b>${{d.entity_cell_count}}</b> 格</span>` : "",
        svi != null ? `<span>SVI: <b>${{svi.toFixed(3)}}</b></span>` : "",
        `<span>强度: <b>${{(d.intensity_range?.min??0).toFixed(3)}} ~ ${{vmax.toFixed(3)}}</b></span>`,
      ].filter(Boolean).join("");
      Plotly.newPlot("chart", [{{
        type:"heatmap", z:d.values, x, y, colorscale:cs, zmin:0, zmax:vmax,
        colorbar:{{title:"社交强度", titleside:"right"}},
        hovertemplate:"X=%{{x}}m<br>Y=%{{y}}m<br>强度=%{{z}}<extra></extra>",
      }}], {{
        paper_bgcolor:"#1a1a2e", plot_bgcolor:"#0f172a", font:{{color:"#e2e8f0"}},
        margin:{{l:60,r:40,t:20,b:60}},
        xaxis:{{title:`X / 宽度 (m) — ${{w}}m`, scaleanchor:"y", scaleratio:1}},
        yaxis:{{title:`Y / 深度 (m) — ${{h}}m`}},
      }}, {{responsive:true}});
    }})();
  </script>
</body>
</html>
"""


def export_heatmap_2d_html(data: dict[str, Any], output_html: Path) -> Path:
    output_html = Path(output_html)
    scene_id = str(data.get("scene_id", "heatmap"))
    html = _HTML_TEMPLATE.format(scene_id=scene_id, data_json=json.dumps(data, ensure_ascii=False))
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(html, encoding="utf-8")
    return output_html


def export_heatmap_2d_json(
    input_json: Path,
    output_json: Path,
    *,
    options: Optional[Heatmap2DOptions] = None,
) -> dict[str, Any]:
    input_json = Path(input_json)
    output_json = Path(output_json)
    pack = json.loads(input_json.read_text(encoding="utf-8"))
    if pack.get("format") != "affordancenet-heatmap-pack":
        raise ValueError(f"不支持的格式: {pack.get('format')}")

    result = project_heatmap_3d_to_2d(pack, options)
    result["source_3d"] = str(input_json.resolve())
    if input_json.exists():
        result["source_3d_mtime"] = input_json.stat().st_mtime

    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def export_heatmap_2d_bundle(
    input_json: Path,
    output_json: Path,
    *,
    output_html: Optional[Path] = None,
    options: Optional[Heatmap2DOptions] = None,
) -> tuple[dict[str, Any], Path]:
    result = export_heatmap_2d_json(input_json, output_json, options=options)
    html_path = output_html or output_json.with_suffix(".html")
    export_heatmap_2d_html(result, html_path)
    return result, html_path
