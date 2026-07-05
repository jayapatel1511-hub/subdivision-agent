# QGIS Export Spec — Subdivision Agent

**Project:** subdivision-agent
**Repo:** https://github.com/jayapatl1511-hub/subdivision-agent
**Branch:** Create `qgis-export` from `main`
**Current state:** Irregular v1 complete, 42/42 tests passing on `main`.

---

## Goal

Add a `qgis` export format that produces a **QGIS project file (.qgz)** with all layers pre-loaded and professionally styled. Opening the output folder in QGIS should immediately show a polished subdivision sketch — lots colored by pass/fail, roads in blue, remainders in orange, buildable envelopes dashed, frontage lines highlighted — zero manual styling required.

The engine stays pure Python. QGIS is the renderer. No matplotlib, no static PNGs.

---

## Architecture

### New file: `export_qgis.py`

One module that takes a `LayoutResult` and an output path, and produces:

1. **Per-layer GeoJSON files** — separate files instead of one mega-FeatureCollection
2. **QML style files** — one per layer, defining symbology
3. **QGZ project file** — zipped QGIS project referencing all layers + styles

### Modified file: `main.py`

Add `qgis` to the `--format` choices and wire it up:

```python
parser.add_argument("--format", default="geojson",
                    choices=["geojson", "dxf", "json", "qgis", "all"],
                    help="Export format")
```

In the export section:
```python
if args.format in ("qgis", "all"):
    path = f"{prefix}_qgis"
    export_qgis(result, path)
    print(f"  Exported: {path}/")
```

---

## 1. Per-Layer GeoJSON Files

Split the current monolithic `export_geojson()` output into separate files:

| File | Contents | Geometry type |
|---|---|---|
| `lots_passing.geojson` | Residential lots that pass all checks | Polygon |
| `lots_failing.geojson` | Residential lots that fail one or more checks | Polygon |
| `remainders.geojson` | Remainder lots (not checked) | Polygon |
| `roads.geojson` | Road ROW polygons | Polygon |
| `road_centerlines.geojson` | Road centerlines | LineString |
| `frontage_lines.geojson` | Lot frontage lines on road | LineString |
| `buildable_envelopes.geojson` | Buildable envelope polygons (lot minus setbacks) | Polygon |
| `parcel_boundary.geojson` | Original parcel boundary | Polygon |

### Properties per layer

**lots_passing.geojson / lots_failing.geojson:**
```json
{
  "lot_id": 1,
  "lot_type": "residential",
  "area_sqm": 450.2,
  "frontage_m": 18.5,
  "depth_m": 24.3,
  "width_min_m": 17.8,
  "shape_quality": 0.72,
  "passes_area": true,
  "passes_frontage": true,
  "passes_depth": true,
  "passes_shape": true,
  "passes_buildable": true,
  "passes_service": true
}
```

**roads.geojson:**
```json
{
  "road_id": 0,
  "name": "Road 1",
  "road_type": "through",
  "row_width_m": 20,
  "length_m": 200.0,
  "area_sqm": 4000.0
}
```

**All other layers:** `lot_id` + relevant metrics only. Keep it simple.

### CRS

All GeoJSON files must include:
```json
{
  "type": "FeatureCollection",
  "crs": {
    "type": "name",
    "properties": { "name": "urn:ogc:def:crs:EPSG::2959" }
  },
  "features": [...]
}
```

If the parcel was loaded from GeoJSON, use the parcel's `working_crs`. If created interactively, default to EPSG:2959 (MTM Zone 4 for HRM).

---

## 2. QML Style Files

QML is QGIS's XML-based style format. Create one per layer.

### `lots_passing.qml` — Green fill, dark green border

```xml
<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.28">
  <renderer-v2 type="singleSymbol" symbollevels="0">
    <symbols>
      <symbol type="fill" name="passing">
        <layer class="SimpleFill" enabled="1" locked="0">
          <prop k="color" v="134,219,108,180"/>
          <prop k="outline_color" v="56,142,60,255"/>
          <prop k="outline_width" v="0.8"/>
          <prop k="style" v="solid"/>
        </layer>
      </symbol>
    </symbols>
  </renderer-v2>
</qgis>
```

### `lots_failing.qml` — Red fill, dark red border

Same structure, colors:
- Fill: `244,108,88,180` (semi-transparent red)
- Outline: `183,28,28,255` (dark red), width 1.0

### `remainders.qml` — Orange fill, dashed border

- Fill: `255,167,38,120` (semi-transparent orange)
- Outline: `230,126,34,255` (dark orange), width 0.6, dash pattern `4;2`

### `roads.qml` — Blue fill, darker blue border

- Fill: `66,133,244,200` (semi-transparent blue)
- Outline: `25,78,163,255` (dark blue), width 1.2

### `road_centerlines.qml` — Dashed blue line

- Color: `25,78,163,255` (dark blue)
- Width: 1.0
- Dash: `8;4`

### `frontage_lines.qml` — Magenta line

- Color: `216,27,96,255` (magenta)
- Width: 1.5

### `buildable_envelopes.qml` — Yellow dashed fill

- Fill: `255,235,59,80` (very transparent yellow)
- Outline: `255,193,7,200` (amber), width 0.5, dash `3;2`

### `parcel_boundary.qml` — Dark grey thick line, no fill

- Fill: none (transparent)
- Outline: `97,97,97,255` (dark grey), width 2.0

### Lot labels

Each lot layer must have a label rule:
- Font size: 8pt
- Color: black
- Expression: `'L' || "lot_id" || COALESCE(CASE WHEN NOT "passes_all" THEN ' ✗' ELSE '' END, '')`
- Placement: centroid

For remainders: `'R' || "lot_id"`

---

## 3. QGZ Project File

A `.qgz` file is a ZIP archive containing:

1. `project.qgs` — The QGIS project XML
2. Any embedded style data

### `project.qgs` structure

The project XML must include:

```xml
<QGIS version="3.28">
  <projecttitle>Subdivision Layout</projecttitle>
  <crs>
    <spatialrefsys>
      <wkt>PROJCS["NAD83(CSRS)/MTM Zone 4"...]</wkt>
      <srid>2959</srid>
      <authid>EPSG:2959</authid>
    </spatialrefsys>
  </crs>
  <projectlayers>
    <!-- One maplayer per GeoJSON file, in this draw order (bottom to top): -->
    <!-- parcel_boundary, roads, road_centerlines, remainders,
         lots_failing, lots_passing, buildable_envelopes, frontage_lines -->
  </projectlayers>
  <layer-tree-group>
    <!-- Same order as above -->
  </layer-tree-group>
</QGIS>
```

Each `<maplayer>` entry must:
- Reference the GeoJSON file by **relative path** (so the folder is portable)
- Reference the QML style file by **relative path**
- Set `provider="ogr"` and `geometry="Polygon"` or `geometry="Line"` as appropriate
- Include `<extent>` matching the data bounds
- Set CRS to EPSG:2959

### Creating the .qgz

Use Python's `zipfile` module:

```python
import zipfile

with zipfile.ZipFile(output_path + '.qgz', 'w', zipfile.ZIP_DEFLATED) as zf:
    zf.writestr('project.qgs', qgs_xml)
    # QML and GeoJSON are referenced by relative path, not embedded
```

The `.qgz` and all the GeoJSON + QML files live in the same output folder. The `.qgs` references them as `./lots_passing.geojson`, `./lots_passing.qml`, etc.

---

## 4. Output Folder Structure

When the user runs:
```bash
python main.py --geojson parcel.geojson --zone R-2 --serviced --export output/layout1 --format qgis
```

The output folder should be:
```
output/layout1_qgis/
├── layout1.qgz                  # QGIS project (zip containing project.qgs)
├── lots_passing.geojson         # Passing residential lots
├── lots_passing.qml             # Style for passing lots
├── lots_failing.geojson         # Failing residential lots
├── lots_failing.qml             # Style for failing lots
├── remainders.geojson           # Remainder lots
├── remainders.qml               # Style for remainders
├── roads.geojson                # Road ROW polygons
├── roads.qml                    # Style for roads
├── road_centerlines.geojson     # Road centerlines
├── road_centerlines.qml         # Style for centerlines
├── frontage_lines.geojson       # Frontage lines
├── frontage_lines.qml           # Style for frontage
├── buildable_envelopes.geojson  # Buildable envelopes
├── buildable_envelopes.qml      # Style for buildable envelopes
├── parcel_boundary.geojson      # Original parcel boundary
└── parcel_boundary.qml          # Style for parcel boundary
```

The user opens `layout1.qgz` in QGIS and everything is there.

---

## 5. Implementation Notes

### CRS handling

- If the parcel was loaded from GeoJSON via `load_geojson_parcel()`, use `parcel.working_crs` (typically 2959 for HRM).
- If created interactively (rectangular), default to EPSG:2959.
- Store the CRS on each GeoJSON FeatureCollection in the `crs` field.
- Store the CRS in the QGIS project `<crs>` section.

### Extent calculation

Compute the bounding box from the parcel geometry:
```python
bounds = parcel.geometry.bounds  # (minx, miny, maxx, maxy)
```

Use this for:
- Each GeoJSON's `bbox` field
- QGIS project layer `<extent>` tags
- QGIS project `<canvas>` extent

### Lot classification

```python
passing_lots = [lot for lot in result.residential_lots if lot.passes_all]
failing_lots = [lot for lot in result.residential_lots if not lot.passes_all]
remainders = result.remainder_lots
```

### Don't touch existing code

**The existing `export_geojson()` and `export_dxf()` functions must remain unchanged.** Add `export_qgis()` as a new function in `export_qgis.py`. Only `main.py` gets a small modification to wire up the new `--format qgis` option and the import.

---

## 6. Testing

### New test file: `tests/test_qgis_export.py`

```python
def test_qgis_export_creates_folder():
    """export_qgis creates the output folder with all expected files."""
    result = generate_test_layout()
    export_qgis(result, "/tmp/test_qgis_export")
    assert Path("/tmp/test_qgis_export/layout.qgz").exists()
    for layer in ["lots_passing", "lots_failing", "remainders", "roads",
                  "road_centerlines", "frontage_lines", "buildable_envelopes",
                  "parcel_boundary"]:
        assert Path(f"/tmp/test_qgis_export/{layer}.geojson").exists()
        assert Path(f"/tmp/test_qgis_export/{layer}.qml").exists()

def test_qgis_export_geojson_valid():
    """Each GeoJSON file is valid JSON with correct structure."""
    for layer in [...]:
        with open(f"/tmp/test_qgis_export/{layer}.geojson") as f:
            data = json.load(f)
        assert data["type"] == "FeatureCollection"
        assert "crs" in data
        assert len(data["features"]) > 0

def test_qgis_export_qgz_valid_zip():
    """The .qgz file is a valid ZIP containing project.qgs."""
    with zipfile.ZipFile("/tmp/test_qgis_export/layout.qgz") as zf:
        names = zf.namelist()
        assert "project.qgs" in names

def test_qgis_export_project_xml():
    """project.qgs contains layer references and CRS."""
    with zipfile.ZipFile("/tmp/test_qgis_export/layout.qgz") as zf:
        qgs = zf.read("project.qgs").decode()
    assert "EPSG:2959" in qgs
    assert "lots_passing.geojson" in qgs
    assert "roads.geojson" in qgs

def test_qgis_export_passing_failing_split():
    """Passing and failing lots are correctly separated."""
    # Generate a layout where some lots fail
    # Check that passing lots go to lots_passing.geojson
    # Check that failing lots go to lots_failing.geojson
    ...

def test_qgis_export_parcel_boundary():
    """Parcel boundary GeoJSON contains the original parcel polygon."""
    ...
```

### Regression: existing tests must still pass

After changes, run:
```bash
python -m pytest tests/ -q
```

All 42 existing tests must still pass. No changes to `export_geojson()` or `export_dxf()`.

---

## 7. Final Checklist

- [ ] New file `export_qgis.py` with `export_qgis()` function
- [ ] Per-layer GeoJSON files with CRS and correct properties
- [ ] QML style files for all 8 layers
- [ ] `.qgz` project file (zipped QGIS XML) with layers, styles, CRS, extent
- [ ] `main.py` updated with `--format qgis` choice and wiring
- [ ] `requirements.txt` — no new dependencies needed (zipfile, json are stdlib)
- [ ] `tests/test_qgis_export.py` — 5+ tests
- [ ] All 42 existing tests still pass
- [ ] All new tests pass
- [ ] Manual verification: open `.qgz` in QGIS, see styled layout
- [ ] Push all changes to `qgis-export` branch

---

## Reference

- Current `export.py` (266 lines) — existing GeoJSON + DXF export
- Current `models.py` (665 lines) — LayoutResult, Lot, RoadSegment, LotType
- Current `main.py` (234 lines) — CLI entry point
- QGIS QML reference: https://docs.qgis.org/3.28/en/docs/user_manual/management_handling_projects.html
- QGS XML reference: https://docs.qgis.org/3.28/en/docs/user_manual/management_handling_projects/working_with_projects.html