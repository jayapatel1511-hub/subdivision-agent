# Subdivision Agent — Rectangle v2 Summary

## What It Does

A **2D subdivision concept-layout optimizer** that takes a parcel boundary + access point + constraints + zoning rules, generates multiple road/lot layout options, checks each lot for compliance, ranks options with weighted scoring, and explains *why* each option ranks as it does. Outputs concept geometry to DXF/GeoJSON for Civil 3D import.

**Core job: smart land division, not engineering design.** No pipes, no profiles, no grading, no stormwater.

---

## Architecture — 7 Files

| File | Lines | Purpose |
|---|---|---|
| `models.py` | 645 | Data models — Lot, LotType, LayoutResult, LayoutRules, Parcel, etc. |
| `generator.py` | 720 | Layout engine — road placement, lot carving, sliver merge, remainder handling |
| `checker.py` | 295 | Compliance checks (area, frontage, depth, shape, buildable, service) + scoring |
| `constraints.py` | 263 | ConstraintEngine — loads HRM zone rules from CSV, resolves to LayoutRules |
| `main.py` | 222 | CLI entry point — parse args, generate, check, score, print, export |
| `export.py` | 260 | GeoJSON + DXF export with lot_type layers, area breakdown in properties |
| `data/zones/hrm/` | — | CSV files for R-1, R-2, R-3, C-1 zones (min area, frontage, depth, setbacks, etc.) |

Plus `tests/test_rectangle_v2.py` — 14 regression tests.

---

## Key Data Model (models.py)

### LotType enum

- `RESIDENTIAL` — standard residential lot (checked for compliance)
- `CORNER` — corner lot (frontage reduction applied)
- `IRREGULAR` — non-rectangular lot (checked, penalty in scoring)
- `REMAINDER` — leftover piece after carving (NOT checked, excluded from yield)
- `ROAD_ROW` — road right-of-way polygon
- `CONSTRAINT` — constraint buffer area (wetland, flood, etc.)
- `OPEN_SPACE` — park/OS area

### Lot properties (computed from geometry)

- `area`, `frontage`, `depth`, `width_min`, `shape_quality` (compactness 4πA/P²)
- `frontage_line` (LineString of road frontage)
- `buildable_envelope` (lot minus setbacks)
- `is_residential` — True for RESIDENTIAL/CORNER/IRREGULAR

### LayoutResult properties

- `residential_lots` — only lots checked for compliance
- `remainder_lots` — excluded from yield
- `passing_lots` / `failed_lots` — residential only
- **Area breakdown:** `road_area`, `passing_lot_area`, `failing_lot_area`, `remainder_area`, `constraint_area`
- `saleable_land_pct = passing_lot_area / gross_area × 100` — computed AFTER checker runs
- `developable_used_pct = (passing_lot_area + failing_lot_area) / (gross_area - road_area) × 100`

---

## Generator (generator.py)

### Road patterns

`single_road`, `double_road`, `cul_de_sac`, `loop_road`, `existing_road`

### Algorithm

1. Subtract road ROW from parcel polygon
2. For each developable side of the road, carve lots along frontage
3. Depth direction = perpendicular to frontage, choosing the direction toward parcel centroid (fixes the far-side road frontage bug)
4. Target lot dimensions = 1.2× min frontage, 1.3× min depth (gives comfortable lots, not bare minimums)
5. After carving, any remaining polygon < min_lot_area becomes a **remainder** lot
6. **Sliver merge:** if remainder area < 10% of target_lot_area AND it touches one adjacent lot AND merge doesn't worsen shape → absorb into that lot

---

## Checker (checker.py)

**Only checks residential lots (RESIDENTIAL, CORNER, IRREGULAR).** Remainder lots skip all checks — they get `passes_all = False` but are NOT counted as failed residential lots.

### Checks per lot

- Area ≥ min_lot_area
- Frontage ≥ min_frontage (with corner lot reduction)
- Depth ≥ min_depth
- Shape quality ≥ 0.35 (compactness threshold)
- Buildable envelope ≥ min_buildable_envelope (setback buffer)
- Access (frontage line exists, ≥ 50% of min frontage)
- Service feasibility (municipal = auto-pass, septic = area + well isolation check)

**After checking:** calls `result.compute_area_metrics()` to populate saleable_land_pct, etc.

---

## Scoring (LayoutScorer)

**Uses residential lots only** for yield, quality, and penalties. Remainders excluded.

```
Total Score = w_yield × yield_score
            + w_quality × quality_score
            + w_road × road_efficiency
            + w_constraint × constraint_score
            + w_service × service_score
            + w_future × future_expansion
            − irregular_count × p_irregular × 10
            − road_length × p_road
            − failed_residential × p_approval × 10
```

**Future expansion score** uses remainder area — 10-20% remainder is "sweet spot" for future phases, >25% is penalized as inefficient.

---

## Constraint Engine (constraints.py)

- Loads HRM zone CSVs from `data/zones/hrm/`
- `resolve(zone_code, servicing_type)` → `ParcelConstraints` with all min dimensions, setbacks, service requirements
- `LayoutRules.from_constraint_engine(pc)` → rules ready for generator/checker
- Servicing types: `serviced` (municipal water/sewer), `unserviced` (well+septic), `serviced_water_only`

---

## Export (export.py)

### GeoJSON

FeatureCollection with separate layers for lots, buildable envelopes, roads, road centerlines, frontage lines. Each feature includes `lot_type`, `is_residential`, compliance checks, and area metrics.

### DXF

Layers for LOTS, LOT_NUMBERS, ROADS, ROAD_CL, FRONTAGE, BUILDABLE, PARCEL, REMAINDER (orange). Lot labels show pass/fail status.

### Summary table

Side-by-side comparison of all layout options with Res/Pass/Fail/Rem columns, Sale% and Dev%, plus recommendation explanation.

---

## Test Results — 300×200 Rectangle

### R-2 Serviced (municipal water/sewer)

- 44 residential lots, **44/44 passing**
- Saleable land: **62.4%** (37,440m² of 60,000m²)
- Developable used: **66.7%**
- 1 remainder (18,720m² — 31% of parcel, room for second road pattern)
- Score: **281.2**

### R-1 Unserved (well+septic)

- 12 residential lots, **0/12 passing** (lots too small for septic requirements — realistic)
- 1 remainder (12,240m²)
- Score: 101.0

---

## Bugs Fixed in v2

| Bug | Before | After |
|---|---|---|
| Saleable land % | 0% (computed before checker) | 62.4% (computed after checker) |
| Remainder lots | Counted as failed residential | Separate remainder type, excluded from yield |
| Lot types | REGULAR/CORNER/IRREGULAR/FLAG | RESIDENTIAL/CORNER/IRREGULAR/REMAINDER/ROAD_ROW/CONSTRAINT/OPEN_SPACE |
| Area breakdown | None | road/passing/failing/remainder/constraint/saleable%/dev-used% |
| Slivers | Left as tiny lots | Merged into adjacent lots when <10% target area |
| Scoring | failed_lots included remainders | Only failed residential lots penalized |
| Depth direction | Sometimes pointed wrong side of road | Perpendicular-to-frontage + centroid check |

---

## What's Next — Irregular Parcel v1

1. **GeoJSON input** — accept arbitrary parcel polygons
2. **Real polygon clipping** — Shapely intersection/subtraction for irregular shapes
3. **Same scoring engine** — no changes needed, it's geometry-agnostic
4. **Better road patterns** — follow parcel edges, not just axis-aligned rectangles