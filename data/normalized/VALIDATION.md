# Validation Report — data-scrape-v1

## 1. Normalized vs Baseline Data Comparison

### Zone Requirements
- **Baseline** (`data/zones/hrm/hrm_zones.csv`): 12 zones, metric units (sqm, m), general HRM regional zones (R-1, R-2, R-3, etc.)
- **Normalized** (`data/normalized/bedford_zone_requirements.csv`): 20 zones, imperial units (sqft, ft), Bedford-specific LUB zones (RSU, RTU, RMU, RTH, RCDD, RR, etc.)
- **Finding**: These are **complementary, not duplicates**. The baseline covers general Halifax regional zones; the normalized data covers Bedford's pre-amalgamation LUB. Bedford was a separate town with its own land-use by-law. Both datasets are valid for different jurisdictions within HRM.

| Bedford Zone | Closest Baseline | Lot Area (sqm) | Baseline (sqm) | Match? |
|---|---|---|---|---|
| RSU | R-1 | 557.4 | 560.0 | ≈ (area match) |
| RTU_duplex | R-2 | 557.4 | 460.0 | ≠ (Bedford requires more) |
| RMU | R-3 | 929.0 | 460.0 | ≠ (Bedford requires more) |
| RR | R-1 | 20,234.3 | 560.0 | ≠ (rural reserve, different category) |

### Lot Design Defaults
- **Regional Subdivision By-law** (`regional_subdivision_lot_defaults.csv`): 8 rows covering default lot requirements for areas without a specific LUB (Dartmouth, Sackville, general HRM). These are **not in the baseline** — they're new data.

### Road Standards
- **NOT extracted.** The Regional Subdivision By-law defers road cross-section standards to the Municipal Design Guidelines (separate document, not in the PDF set). The by-law itself only contains lot design rules (frontage, area). Road standards would need to be sourced from HRM Engineering & Standards publications.

## 2. Test Suite Results

| Test File | Tests | Status |
|---|---|---|
| `test_rectangle_v2.py` | 14 | ✅ All pass |
| `test_irregular_v1.py` | 28 | ✅ All pass |
| `test_qgis_export.py` | 11 | ✅ All pass |
| **Total (data-scrape-v1)** | **53** | **✅ All pass** |

Note: 11 webapp tests exist on the `webapp` branch, not on `data-scrape-v1`. Total project tests: 64.

## 3. Real Parcel Fixture Loading

All 30 real parcel fixtures (10 Bedford, 10 Dartmouth, 10 Sackville) successfully load through `intake_geojson.load_geojson_parcel()`:

- **30/30 parcels loaded** ✅
- All geometries reprojected from EPSG:4326 → EPSG:2959 (UTM zone 20N)
- Area range: 724 sqm – 14,908 sqm
- Mean area: 4,065 sqm
- Total area: 12.19 ha (121,936 sqm)
- All classified as shape type: rectangle (shape_analysis)

### Enrichment Status
- **zone_code**: All 30 parcels enriched with `R-1` (default). The HRM zoning GeoJSON (2,000 features from ArcGIS) only covers a limited extent and doesn't include the parcel locations. Full zoning enrichment would require paginating through all ArcGIS FeatureServer results (>2,000 records).
- **servicing_type**: All 30 parcels set to `serviced` (Bedford/Dartmouth/Sackville are urban areas with municipal water/sewer).

## 4. Data Coverage Summary

| Data Type | Source | Status | Records |
|---|---|---|---|
| HRM Zoning Boundaries | ArcGIS FeatureServer | ✅ Raw (2,000 features, limited extent) | `data/raw/zoning/hrm_zoning_raw.geojson` |
| HRM Parcels | ArcGIS FeatureServer | ✅ 30 fixtures | `tests/fixtures/real/` |
| HRM Streets | ArcGIS FeatureServer | ✅ Raw | `data/raw/parcels/hrm_streets_raw.geojson` |
| NS Wetlands | Provincial open data | ✅ Raw | `data/raw/constraints/ns_wetlands_raw.geojson` |
| HRM Floodplain | HRM open data | ✅ Raw | `data/raw/constraints/hrm_floodplain_raw.geojson` |
| Bedford LUB | PDF (117pp) | ✅ 19 zones extracted | `data/normalized/bedford_zone_requirements.csv` |
| Regional Subdivision By-law | PDF (127pp) | ✅ Lot defaults extracted | `data/normalized/regional_subdivision_lot_defaults.csv` |
| Downtown Halifax LUB | PDF (72pp) | ❌ Not applicable (precinct-based, no lot geometry tables) | — |
| Halifax Water Design Specs | PDF (181pp) | ❌ Not processed (pipe/sewer specs, not zoning) | — |
| Road Standards | Municipal Design Guidelines | ❌ Not sourced (separate document, not in PDF set) | — |

## 5. Known Gaps

1. **Zoning enrichment incomplete** — ArcGIS FeatureServer 2,000-record limit means zoning GeoJSON doesn't cover all parcel locations. Need to paginate for full coverage.
2. **No Sackville/Dartmouth LUBs** — These were HTML sources, not PDFs. Would need separate extraction.
3. **No road standards** — Deferred to Municipal Design Guidelines, not in the source PDF set.
4. **All fixtures default to R-1** — Real zone assignment needs full zoning data pagination.