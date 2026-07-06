# Real Parcel Validation Report — data-scrape-v1

**Date:** 2026-07-06
**Scope:** Verification of the multi-agent scraping run, two intake bugs found and fixed, and the first honest engine baseline on 30 real HRM parcels.

---

## 1. Scrape Pipeline Status

| Agent | Task | Status | Output |
|---|---|---|---|
| 1 — Source Scout | Find + verify endpoints | ✅ Done | `data/raw/SOURCES.md` — 12 curl-verified endpoints |
| 2 — GIS Harvester | Download layers + fixtures | ✅ Done | 4 raw layers, 30 real parcel fixtures (`tests/fixtures/real/`) |
| 3 — Bylaw Extractor | Extract zone tables from PDFs | ✅ Done | `data/normalized/bedford_zone_requirements.csv` (19 zones), `regional_subdivision_lot_defaults.csv` (8 rows) |
| 4 — Validator | Diff vs baseline, run tests | ⚠️ Ran, but see §3 | `data/normalized/VALIDATION.md` |

### Extraction quality (Agent 3)

- 19 Bedford LUB zones with per-row `source_doc` / `source_page` provenance.
- Imperial units preserved honestly (`min_lot_area_sqft`, unit column) rather than silently converted.
- Conditional rules kept in `notes` instead of flattened into single numbers.
- Correct judgment calls: Downtown Halifax LUB skipped (precinct-based, no lot tables); road standards flagged as living in the Municipal Design Guidelines (not in the PDF set).

### Known gaps (from the scrape's own reports + this review)

1. **Road standards not extracted** — Municipal Design Guidelines PDF not sourced.
2. **Zoning enrichment is a placeholder** — all 30 fixtures default to `zone_code=R-1`; real zone assignment needs the paginated zoning layer (ArcGIS 2,000-record page cap).
3. **Raw GIS layers are first-page-only** — zoning/streets/wetlands need `resultOffset` pagination for full coverage.
4. **~30 MB of binaries committed to git** on `data-scrape-v1` (three 5–6 MB PDFs, a 22 MB GeoJSON). `data/raw/` should be gitignored and those commits rewritten before merging.
5. **No Sackville/Dartmouth LUBs** — HTML sources, separate extraction needed.

---

## 2. Two Intake Bugs Found (and Fixed)

Both were exposed only by running **real** parcels through intake — every synthetic fixture declares a projected CRS and therefore skipped the code paths involved.

### Bug 1 — Cleaning ran before reprojection (geometry destroyed)

`intake_geojson.py` called `clean_polygon()` — which includes `simplify(tolerance=0.5)` — **while coordinates were still lat/lon degrees**. The tolerance therefore meant 0.5° ≈ 50 km, flattening every real parcel to its 3–4 extreme vertices.

Measured on parcel PID 41243577 (assessed 3,840 m²):

| Pipeline | Vertices | Area |
|---|---|---|
| Reproject first (correct) | 15 | 3,837 m² |
| Simplify-then-reproject (bug) | 4 | 809 m² |

Symptom: 29/30 real parcels misclassified as `corridor`; two parcels collapsed below 100 m².

**Fix:** reproject to a projected CRS *before* cleaning, so the tolerance is 0.5 m as intended.

### Bug 2 — Wrong UTM zone as working CRS

The working CRS was `EPSG:2959`, commented as "MTM zone 4 for HRM". It is actually **NAD83(CSRS) / UTM zone 18N** — the Ontario/Ottawa longitude band. Halifax is UTM zone 20N → **EPSG:2961**.

Measured effect: systematic **+2.1% area inflation** (3,918 vs 3,837 m² on the test parcel) — enough to flip a minimum-lot-area compliance check near the 460 m² R-2 threshold.

**Fix:** geographic input now projects to EPSG:2961; input already in a projected CRS is kept as-is (preserves synthetic-fixture behaviour exactly). Defaults updated in `models.py` and `export_qgis.py`.

### Note on the Agent-4 validation report

`VALIDATION.md` claimed "30/30 parcels loaded … EPSG:2959 (UTM zone 20N) … all classified as rectangle." All three claims were artifacts of the bugs above: parcels *loaded* but as mangled triangles, 2959 is not zone 20N, and real suburban parcels are not all rectangles. Validation must assert geometry *fidelity* (area/vertices preserved), not just absence of exceptions.

### Regression tests added

`tests/test_intake_crs.py`:
- lat/lon parcel area preserved within 1% through intake,
- a 12-vertex lat/lon parcel is not collapsed by cleaning,
- projected-CRS input is not reprojected.

**Full suite: 56/56 passing** (was 53 + 3 new; two QGIS-export assertions updated from the incorrect 2959 to 2961).

---

## 3. First Honest Engine Baseline — 30 Real Parcels

Run: fixed intake, zone R-2, serviced, best of {single_road, cul_de_sac, existing_road} per parcel.

**Headline: only 8 of 30 parcels produce even one passing lot. Zero crashes.**

| PID | Shape | Area (m²) | Verts | Res. lots | Passing | Best pattern |
|---|---|---|---|---|---|---|
| 00374033 | corridor | 1,272 | 11 | 0 | 0 | existing_road |
| 00582452 | convex | 5,625 | 8 | 6 | **6** | single_road |
| 40003303 | concave | 4,031 | 34 | 2 | 0 | single_road |
| 40003824 | concave | 4,463 | 19 | 1 | **1** | existing_road |
| 40064743 | concave | 4,219 | 10 | 1 | **1** | existing_road |
| 40093221 | corridor | 1,961 | 29 | 1 | 0 | existing_road |
| 40103889 | concave | 4,455 | 26 | 3 | 0 | existing_road |
| 40116683 | concave | 6,140 | 37 | 1 | 0 | existing_road |
| 40313942 | concave | 9,672 | 19 | 2 | 0 | single_road |
| 40418782 | concave | 3,064 | 12 | 1 | **1** | existing_road |
| 40430886 | concave | 5,025 | 28 | 2 | 0 | single_road |
| 40529034 | corridor | 1,329 | 7 | 1 | 0 | existing_road |
| 40543035 | corridor | 2,286 | 24 | 2 | 0 | existing_road |
| 40586703 | corridor | 1,273 | 4 | 0 | 0 | existing_road |
| 40589418 | concave | 8,041 | 49 | 2 | 0 | single_road |
| 40650665 | corridor | 1,569 | 4 | 1 | **1** | existing_road |
| 40686016 | concave | 4,111 | 24 | 2 | **1** | single_road |
| 40739534 | concave | 3,875 | 17 | 1 | **1** | existing_road |
| 40770885 | corridor | 1,306 | 22 | 1 | 0 | existing_road |
| 40771511 | corridor | 2,623 | 29 | 1 | 0 | existing_road |
| 40801078 | corridor | 1,477 | 17 | 0 | 0 | single_road |
| 40801086 | corridor | 1,933 | 15 | 0 | 0 | existing_road |
| 40840803 | concave | 4,051 | 25 | 2 | 0 | single_road |
| 41208364 | concave | 1,877 | 21 | 0 | 0 | existing_road |
| 41209347 | corridor | 1,793 | 15 | 1 | 0 | existing_road |
| 41243577 | convex | 3,802 | 5 | 4 | **4** | single_road |
| 41250945 | concave | 4,776 | 18 | 1 | 0 | existing_road |
| 41339730 | corridor | 4,890 | 10 | 0 | 0 | existing_road |
| 41515230 | concave | 3,791 | 21 | 4 | 0 | existing_road |
| 41515248 | concave | 5,123 | 20 | 0 | 0 | existing_road |

Shape distribution: 16 concave, 12 corridor, 2 convex.

### Reading the baseline

- **Areas are now trustworthy** — e.g. PID 41243577 loads at 3,802 m² vs 3,840 m² assessed (−1%).
- **Convex parcels do fine** (6 and 4 passing lots). The engine's rectangle path works when the land cooperates.
- **Concave parcels are the failure mode that matters**: 4,000–9,700 m² parcels that should fit 4–10 R-2 lots typically yield 1–2 residential lots with 0 passing. This is the single-strip irregular carver + naive road placement (see the Phase 0/logic review): one shallow strip along one road, everything else becomes remainder.
- **Corridor parcels ≤ 2,000 m²** are legitimately hard or un-subdividable — 0 lots is often the *correct* answer there.

This table is the scoreboard: generator improvements should move the 8/30 number, and the concave rows are the target cases.

---

## 4. Recommended Next Steps

1. **Merge the intake fix** (branch `claude/repo-review-approach-67ut0s`, commit `93c4531`) into `data-scrape-v1` / `main`.
2. **Phase 0 generator fixes** (from the logic review): subtract carved lots from developable between roads (T-road/spine overlap), remove/flag landlocked depth-rows, fix the rotation math in the irregular road placer. Re-run this baseline after each fix.
3. **Gitignore `data/raw/` + rewrite the binary commits** on `data-scrape-v1` before it merges.
4. **Paginate the zoning layer** and do real zone enrichment for the 30 fixtures (replace the `R-1` placeholder).
5. **Source the Municipal Design Guidelines** for road standards (curve radii, bulb radius) — prerequisite for the road-geometry work.
6. **Unit conversion pass** for Bedford data (sq ft → m²) into the engine's schema, keeping the imperial originals as provenance.
