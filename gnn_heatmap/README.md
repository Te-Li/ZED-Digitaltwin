# gnn3d+2d

This project converts an `occupied_space.json` scene into a 3D heatmap, projects that 3D heatmap into a 2D heatmap, then masks the 2D heatmap with live `ground_top_observations_live.json` observations for display and projection.

## Data Flow

```text
../out/occupied_space.json
+ street elements.csv
    -> output/occupied_space.heatmap.json
    -> output_2d/2d_heatmap.json
    -> output_2d/2d_heatmap.html
    -> /api/live/heatmap2d
    -> projector_live.html
```

The four-corner projection page uses the same masked 2D heatmap API and applies `projection_calibration.json` in the browser.

## Inputs

All default paths are defined in `config_paths.py`.

| Path | Role |
|------|------|
| `../out/occupied_space.json` | Main 3D scene input. |
| `street elements.csv` | Street-element catalog used by 3D heatmap prediction. |
| `../out/ground_top_observations_live.json` | Observation mask input. Observed cells are hidden in the final 2D heatmap. |
| `projection_calibration.json` | Four-corner projector calibration, written by `projector_calibrate.html`. |

## Outputs

| Path | Role |
|------|------|
| `output/occupied_space.heatmap.json` | 3D heatmap output, also sent to the local API if available. |
| `output_2d/2d_heatmap.json` | Final masked 2D heatmap JSON. |
| `output_2d/2d_heatmap.html` | Final masked 2D heatmap HTML snapshot. |

No raw unmasked 2D file is written by default.

## Mask Rule

The 2D heatmap is first generated from `output/occupied_space.heatmap.json`.

Then `ground_top_observations_live.json` is used as a mask:

```text
entity occupied cell -> null
observed ground-top cell -> null
other cell -> keep 3D-to-2D heatmap intensity
```

For each observation, `row` and `col` are preferred and treated as 1-based grid indices. If `row/col` are missing, `center_x_mm/center_y_mm` are converted to a cell using the 400 mm grid size.

## Ground-Top Observation Format

Example:

```json
{
  "id": 49,
  "center_x_mm": 932.93,
  "center_y_mm": 599.16,
  "center_z_mm": 901.69,
  "row": 1,
  "col": 2,
  "level": 2,
  "orientation": "1,0",
  "source": "cam_a",
  "serial_number": 34407890
}
```

Grid settings:

```text
columns x rows: 10 x 6
cell size: 400 mm x 400 mm
area: 4.0 m x 2.4 m
```

## Usage

Run the full pipeline:

```powershell
python entity_to_heatmap.py
```

This reads:

```text
../out/occupied_space.json
street elements.csv
../out/ground_top_observations_live.json
```

and writes:

```text
output/occupied_space.heatmap.json
output_2d/2d_heatmap.json
output_2d/2d_heatmap.html
```

Skip 3D prediction and regenerate only masked 2D from an existing 3D heatmap:

```powershell
python entity_to_heatmap.py --only-2d
```

Override input paths:

```powershell
python entity_to_heatmap.py `
  --input ..\out\occupied_space.json `
  --elements-csv "street elements.csv" `
  --ground-top-mask ..\out\ground_top_observations_live.json `
  --output output\occupied_space.heatmap.json `
  --output-2d output_2d\2d_heatmap.json
```

Start the live viewer:

```powershell
python entity_to_heatmap.py --only-2d --serve
```

The live server watches both:

```text
output/occupied_space.heatmap.json
../out/ground_top_observations_live.json
```

When either changes, it regenerates:

```text
output_2d/2d_heatmap.json
output_2d/2d_heatmap.html
```

## Live URLs

```text
http://127.0.0.1:8766/heatmap_2d_live.html
http://127.0.0.1:8766/projector_calibrate.html
http://127.0.0.1:8766/projector_live.html
```

API endpoints:

```text
/api/live/heatmap2d
/api/live/projection-calibration
```

`projector_live.html` reads `/api/live/heatmap2d`, so the projected image follows the masked 2D heatmap in real time.

## Projection Calibration

Start the live server, then open:

```text
http://127.0.0.1:8766/projector_calibrate.html
```

Click the projected canvas corners in this order:

```text
top-left -> top-right -> bottom-right -> bottom-left
```

Save the calibration. The result is written to:

```text
projection_calibration.json
```

Then open:

```text
http://127.0.0.1:8766/projector_live.html
```

The browser applies the four-corner transform to the current masked 2D heatmap.

## Notes

- If the local API at `127.0.0.1:8000` is not running, 3D API sync may fail, but local 3D/2D file generation still works.
