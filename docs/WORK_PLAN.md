# Subdivision Agent — Detailed Work Plan

**Date:** 2026-07-06
**Status basis:** logic review of the full engine, verified bug probes, the data-scrape-v1 run, and the 30-real-parcel baseline (`docs/REAL_PARCEL_VALIDATION.md`).

**Scoreboard metric:** passing-lot coverage on the 30 real parcels — currently **8/30**. Every engine change below should be judged by whether it moves this number (or makes it more trustworthy).

---

## Current State Snapshot

| Area | State |
|---|---|
| Engine (rectangle path) | Works on convex parcels; 3 confirmed correctness bugs inflate yield |
| Engine (irregular path) | Single-strip carving; leaves most of concave parcels as remainder |
| Road model | Straight polylines + buffer; no curves, no bulbs, no intersections |
| Intake | Fixed (CRS + clean order) — 56/56 tests passing on `claude/repo-review-approach-67ut0s` |
| Data | Bedford LUB + Regional Subdivision By-law extracted; road standards, zoning enrichment, pagination outstanding |
| Web app | Built on `webapp` branch (FastAPI + Leaflet), not merged |
| Tests | 56 passing, but no yield-quality or geometric-invariant assertions |
| CI | None |

**Branch merge order first:** merge `claude/repo-review-approach-67ut0s` (intake fix) → then reconcile `data-scrape-v1` (after binary cleanup, §6.1) → then `webapp`.

---

## Phase 0 — Engine Correctness (do first; small; everything else is noise until done)

These three bugs were verified by direct measurement on a plain 300×200 m rectangle. They mean current yield numbers and layout rankings are wrong.

### 0.1 Landlocked back-row lots pass the access check

- **Where:** `generator.py` `_carve_lots_along_road()` — depth-row loop (`num_rows = available_depth / target_depth`).
- **Problem:** Row 2+ lots sit behind row 1 with no road contact, but inherit the front lot's `frontage_line`, so `passes_access=True`. Measured: 44 lots on the test rectangle, **22 landlocked**. Yield is ~2× inflated on deep parcels.
- **Fix:** Remove the multi-row loop (carve one row per road side), or gate interior rows behind `rules.flag_lots_allowed` with an explicit access-lane deduction. Recommended: remove now, revisit with blocks-first (Phase 2).
- **Accept:** every residential lot's geometry intersects (within 0.5 m) the union of road ROW polygons; invariant test added.
- **Size:** small.

### 0.2 Multi-road patterns carve overlapping lots

- **Where:** `generator.py` `generate_layout()` — `for road in roads: self._carve_lots_along_road(road, developable)`; `developable` never shrinks.
- **Problem:** Measured on the test rectangle: T-road → 48 overlapping pairs (11,358 m² double-counted); spine → 76 pairs (24,895 m²). `remaining_developable` goes **negative**. Rankings favour patterns that double-count land.
- **Fix:** Subtract each carved lot (or each road's lot set) from `developable` before carving the next road — the irregular carver already does this correctly (`irregular_generator.py` `_carve_side`); mirror that.
- **Accept:** pairwise lot intersection area < 1 m² across all patterns; `remaining_developable >= 0`; invariant tests added.
- **Size:** small.

### 0.3 Rotation math bug in irregular road steering

- **Where:** `irregular_generator.py:96-100` (`_iterative_road_extension`).
- **Problem:** `dy` is computed from the already-updated `dx` — every steer applies a wrong, non-unit rotation that compounds each 20 m step. Verified numerically: 15° rotation of (1,0) yields (0.9659, 0.250) instead of (0.9659, 0.2588).
- **Fix:** rotate via temporaries (`ndx = dx*cos - dy*sin; ndy = dx*sin + dy*cos`).
- **Accept:** unit test on the rotation helper; L-shape fixture road path visibly straightens; no test regressions.
- **Size:** trivial.

### 0.4 Invariant test suite (locks 0.1–0.3 in)

Add `tests/test_geometry_invariants.py`, parameterized over all synthetic fixtures + all patterns + a sample of the 30 real parcels:

1. No two residential lots overlap (> 1 m² tolerance).
2. Every residential lot touches a road ROW or the parcel front boundary.
3. Area conservation: lots + roads + remainders + constraint loss ≈ gross (±1%), and `remaining_developable >= 0`.
4. Every lot polygon is valid, non-empty, single-part.
5. Yield snapshots per fixture (e.g. "L-shape ≥ N passing lots, remainder ≤ X% of gross") so refactors that silently degrade yield fail CI.

- **Size:** medium. Expect honest yield numbers to *drop* when 0.1/0.2 land — update snapshots to the new truth.

---

## Phase 1 — Road Geometry (the "no curve logic" gap)

The road model is centerline-polyline + flat buffer. `hrm_road_standards.csv` already carries `horizontal_curve_min_radius_m` (30 m local) and `cul_de_sac_bulb_radius_m` (15 m) — the engine just never uses them. Ordered by value:

### 1.1 Curvature-constrained centerlines

- Densify centerline vertices; post-process every kink with a circular-arc fillet of radius ≥ `horizontal_curve_min_radius_m` (approximate arcs as dense polylines — Shapely needs no native arcs).
- Add a curvature check: reject/repair centerlines whose deflection per unit length implies a tighter radius.
- Guard `offset_curve` results: on kinked lines it can return `MultiLineString`, and `_carve_side` calls `.coords` on it unguarded (latent crash).
- **Accept:** max curvature along any centerline ≤ 1/min_radius; frontage offsets always single LineStrings; roads render smoothly in QGIS export.
- **Size:** medium.

### 1.2 Real cul-de-sac bulbs

- ROW = corridor buffer ∪ circle of `cul_de_sac_bulb_radius` at the terminus; enforce `cul_de_sac_max_length_m`.
- Carve radial (pie-slice) lots around the bulb frontage — typically the highest-value lots in a cul-de-sac.
- **Where:** `models.py` `RoadSegment.row_polygon` (currently ignores `is_cul_de_sac`), plus a bulb-frontage carver.
- **Accept:** cul-de-sac layout differs geometrically from single-road; bulb lots generated; max-length warning fires.
- **Size:** medium.

### 1.3 Intersection geometry

- Corner radii (~6–9 m fillets) where branch ROWs meet the spine; no lot frontage inside the intersection's functional area; minimum intersection spacing.
- Also fixes: corner-lot classification should be topological (lot touches two ROWs), not positional (first/last column) as it is now in `_carve_lots_along_road`.
- **Size:** medium.

### 1.4 Frontage measured on the actual ROW edge

- A lot's legal frontage = length of its shared edge with the ROW, not the construction segment's length. Compute `lot.boundary ∩ row_polygon.buffer(ε)`.
- Bonus: makes landlocked lots self-detecting (frontage = 0).
- **Where:** `models.py` `Lot.compute_properties()` — also replace `depth = area/frontage` and `width_min = bbox` with minimum-rotated-rectangle dimensions.
- **Size:** small-medium.

### 1.5 Loop roads that actually loop

- Both code paths currently draw a straight line between two access points (a through-road). A loop should return to the same boundary road. Defer full solution to Phase 2 network topology; near-term, rename/re-score honestly as "through road".
- **Size:** small (honesty fix) / Phase 2 (real fix).

---

## Phase 2 — Generator Restructure: Blocks-First (strategic)

**Why:** strip-carving off roads is the root cause of landlocked lots, overlap, and the giant remainders on concave parcels (e.g. 18,720 m² dead remainder on the L-shape fixture; 4,000–9,700 m² real concave parcels yielding 1–2 lots). The standard practice — and what the real-parcel baseline demands — is:

1. Generate a street network that partitions the parcel into **blocks** sized ≈ 2 × lot_depth deep and n × lot_width long.
2. Subdivide each block into double-loaded lots (lots on both sides, backs touching).
3. Score as before.

**Properties you get for free:** every lot fronts a street by construction; area conservation is trivial (blocks tile the parcel); the remainder question becomes "which blocks are too small", which is much easier to reason about and score.

**How it composes with existing code:**
- `shape_analysis.py` bottleneck splitting → decompose irregular parcels into near-convex chunks.
- Per chunk: oriented-bounding-box-aligned block grid; streets on block edges; connect sub-networks across chunk seams.
- Existing patterns (cul-de-sac, loop, spine) become network topologies over the block graph instead of hand-drawn centerlines — and loop roads become real loops (1.5).
- Phase 1 geometry (curves, bulbs, intersections) applies to the network edges.

**Milestones:**
1. Blocks on rectangle/convex parcels; beat current single-road yield without invariant violations.
2. Blocks on decomposed concave parcels (target: concave real parcels from the baseline produce ≥ floor(0.6 × area / (min_lot_area × 1.4)) passing lots).
3. Network topologies: grid, cul-de-sac tree, loop.
- **Accept:** 30-parcel scoreboard moves materially (target ≥ 20/30 with passing lots; corridor parcels ≤ 2,000 m² may legitimately stay 0).
- **Size:** large — the main engine investment of the next stage.

---

## Phase 3 — Data Pipeline Completion (from data-scrape-v1 gaps)

### 3.1 Merge + cleanup of `data-scrape-v1`

- Rewrite the branch to drop ~30 MB of committed binaries (3 PDFs @ 5–6 MB, 22 MB zoning GeoJSON); add `data/raw/` to `.gitignore`; keep manifests + normalized CSVs in git. Re-download raws on demand via URLs in `SOURCES.md`.
- **Size:** small, do before any merge.

### 3.2 Zoning enrichment for the 30 fixtures

- Paginate the HRM zoning FeatureServer (`resultOffset`, 2,000/page); spatial-join each fixture parcel to its actual zone; replace the `R-1` placeholder in fixture properties.
- Re-run the baseline with true zones — the scoreboard becomes real.
- **Size:** small-medium.

### 3.3 Road standards source

- Fetch HRM Municipal Design Guidelines (road cross-sections, curve radii, bulb dimensions, intersection spacing); extract into `data/normalized/road_standards.csv` with provenance. Prerequisite for Phase 1 numbers being authoritative rather than the current hand-authored CSV.
- **Size:** small (scrape) + small (extract).

### 3.4 Unit conversion + merge of Bedford data

- Convert `bedford_zone_requirements.csv` (sq ft / ft) into the engine's metric schema; keep imperial originals as provenance columns; wire the `ConstraintEngine` to resolve Bedford zones (RSU, RTU, …) alongside regional ones.
- **Size:** small-medium.

### 3.5 Conditional-rules schema (the actual "smart engine" core)

- Current CSVs hold one number per zone/field. Bylaws are conditional ("15 m frontage where fronting a cul-de-sac bulb"; "460 m² if serviced else 4,000 m²"). Design: rule = `(zone, field, value, applicability_predicate, source_quote, confidence)`.
- v1 evaluator handles: servicing conditionals, corner/cul-de-sac frontage reductions, per-unit minima (semis/towns). Everything else stored but flagged unevaluated.
- Write a short design doc before implementing; Agent-3 output already preserves conditions in `notes`, so this is a schema + evaluator task, not a re-scrape.
- **Size:** medium (schema + loader) → grows with evaluator coverage.

### 3.6 Constraint mapping (exclusion polygons)

- Wire the downloaded wetlands + floodplain layers into intake: clip to parcel, apply buffer distances from `hrm_buffers_constraints.csv`, subtract from buildable area, and surface as `ConstraintArea`s (the checker already handles conflicts).
- Requires 3.1 pagination for coverage beyond the pilot areas.
- **Accept:** a parcel overlapping a wetland shows reduced buildable area and lots avoid the buffer in exports.
- **Size:** medium. This is what makes results credible to a real user.

### 3.7 Ground-truth benchmark set

- Collect 5–10 **approved** subdivision plans from HRM planning-application documents (staff reports include tentative/final plans). Digitize lot counts + road topology per plan.
- Benchmark: engine yield / road length vs approved plan on the same parcel. This is the only external measure of "is the engine any good."
- **Size:** medium (mostly manual curation).

---

## Phase 4 — Product Surface

### 4.1 Merge and harden the webapp

- `webapp` branch exists (FastAPI + Leaflet, 11 tests). Merge after Phase 0 so it displays honest layouts; add the 30 real fixtures as a demo picker; render constraint areas once 3.6 lands.
- **Size:** small-medium.

### 4.2 Checker/scoring honesty pass

- Buildable envelope uses `min(setbacks)` on all sides (`checker.py:162`) — implement per-edge setbacks (front vs rear vs side; front edge = the ROW-touching edge from 1.4).
- `passes_access` should use ROW-edge frontage (1.4), not "frontage_line exists".
- Road-efficiency and yield scores should exclude non-passing lots from numerators where they currently don't.
- **Size:** medium.

### 4.3 Explanation layer (later)

- The scorer's text explanations are template-based; once rules carry source quotes (3.5), explanations can cite the actual bylaw line a lot fails against. Optional LLM polish is cheap later; don't build it before the data supports it.

---

## Ongoing / Infrastructure

| Task | Detail | Size |
|---|---|---|
| **CI** | GitHub Action: `pip install -r requirements.txt && python -m pytest tests/ -q` on push/PR. Suite runs in ~2 s — no excuse. | trivial |
| **Real-parcel baseline in CI** | Run the 30-parcel scoreboard on PRs touching engine files; report the N/30 number in the job summary. | small |
| **Dependency pinning** | `requirements.txt` uses loose `>=`; pin working versions (or add a lockfile). | trivial |
| **Docs debt** | README/summaries still describe EPSG:2959 as "MTM zone 4"; update after intake fix merges. | trivial |

---

## Suggested Execution Order

```
1. Merge intake fix (done, on claude/repo-review-approach-67ut0s)
2. Phase 0 (0.1–0.4) + CI                      ← unblocks trust in all numbers
3. 3.1 branch cleanup → merge data-scrape-v1
4. 3.2 zoning enrichment → re-baseline          ← scoreboard becomes real
5. Phase 1 road geometry (1.4 first — it feeds 0.4 and 4.2 — then 1.1, 1.2, 1.3)
6. 4.1 webapp merge                             ← visual feedback loop for Phase 2
7. Phase 2 blocks-first (milestone by milestone, scoreboard-driven)
8. 3.5 conditional rules + 3.4 Bedford merge
9. 3.6 constraint mapping
10. 3.7 ground-truth benchmark
11. 4.2 checker honesty, then 4.3 explanations
```

Dependencies worth respecting: 0.x before anything (numbers are lies until then); 1.4 before 4.2; 3.1 before 3.2/3.6; webapp before deep Phase 2 iteration (you need to *see* block layouts to tune them).
