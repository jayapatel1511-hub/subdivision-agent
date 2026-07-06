# HARVEST_LOG.md — Agent 2 (GIS Harvester) Results

**Date:** 2026-07-06  
**Agent:** Agent 2 — GIS Harvester (subagent timed out at 600s; downloads completed, fixtures + log completed manually by Penny)  
**User-Agent:** `SubdivisionAgent/1.0 (research; contact: jayapatel1511-hub)`  
**Working directory:** `/Volumes/SSD/subdivision-agent` (branch: `data-scrape-v1`)

---

## Raw Data Downloads

### 1. HRM Zoning Boundaries

| Field | Value |
|-------|-------|
| **URL** | `https://services2.arcgis.com/11XBiaBYA9Ep0yNJ/arcgis/rest/services/ZoningBoundaries/FeatureServer/0/query?where=1=1&outFields=*&f=geojson&resultRecordCount=2000&outSR=4326` |
| **HTTP status** | 200 |
| **Response size** | 22 MB |
| **Features returned** | 2000 (max page — pagination needed for full dataset) |
| **CRS** | EPSG:4326 (requested via outSR) |
| **Geometry type** | Polygon |
| **Properties** | DESCRIPTION, OBJECTID, FCODE, ZONE, BYLAW_ID, SOURCE, SACC, SDATE, GLOBALID, Shape__Area, Shape__Length |
| **Saved to** | `data/raw/zoning/hrm_zoning_raw.geojson` |
| **Status** | ✅ Complete (first 2000 of unknown total — pagination with resultOffset needed for full set) |

### 2. HRM Street Centrelines

| Field | Value |
|-------|-------|
| **URL** | `https://services2.arcgis.com/11XBiaBYA9Ep0yNJ/arcgis/rest/services/Street_Centreline/FeatureServer/0/query?where=1=1&outFields=*&f=geojson&resultRecordCount=2000&outSR=4326` |
| **HTTP status** | 200 |
| **Response size** | 4.8 MB |
| **Features returned** | 2000 (max page) |
| **CRS** | EPSG:4326 |
| **Geometry type** | Polyline |
| **Properties** | OBJECTID, FCODE, STR_NAME, STR_TYPE, FULL_NAME, MUN_CODE, FROM_STR, TO_STR, STR_DIR, STR_STATUS, ST_CLASS, OWN, MAINTENANCE, DATE_ACCEPT, STR_REM |
| **Saved to** | `data/raw/parcels/hrm_streets_raw.geojson` |
| **Status** | ✅ Complete (first 2000 of unknown total) |

### 3. NS Wetlands

| Field | Value |
|-------|-------|
| **URL** | `https://nsgiwa.novascotia.ca/arcgis/rest/services/BIO/WLD_ProvLandScapeViewer_WM84/MapServer/5/query?where=1=1&outFields=*&f=geojson&resultRecordCount=1000&outSR=4326` |
| **HTTP status** | 200 |
| **Response size** | 7.9 MB |
| **Features returned** | 1000 (max page for NSGI) |
| **CRS** | EPSG:4326 |
| **Geometry type** | Polygon |
| **Properties** | OBJECTID, Area, Perimeter, Wetland, Hectares, Shape_Length, Shape_Area, Surveyed |
| **Saved to** | `data/raw/constraints/ns_wetlands_raw.geojson` |
| **Status** | ✅ Complete (first 1000 of unknown total — NSGI max 1000 per page) |

### 4. HRM Floodplain Overlay Zones

| Field | Value |
|-------|-------|
| **URL** | `https://services2.arcgis.com/11XBiaBYA9Ep0yNJ/arcgis/rest/services/Floodplain_Overlay_Zones/FeatureServer/0/query?where=1=1&outFields=*&f=geojson&resultRecordCount=2000&outSR=4326` |
| **HTTP status** | 200 |
| **Response size** | 13 MB |
| **Features returned** | 1011 |
| **CRS** | EPSG:4326 |
| **Geometry type** | Polygon |
| **Properties** | OBJECTID, RTN_PRD, REG_CODE, BYLAW_ID, BYLAW_CODE, ADDDATE, MODDATE, SDATE, SOURCE, SACC, GlobalID, Shape__Area, Shape__Length |
| **Saved to** | `data/raw/constraints/hrm_floodplain_raw.geojson` |
| **Status** | ✅ Complete (all features — 1011 < 2000 max) |

---

## Parcel Fixtures (Agent 2 Task 5)

### Query Strategy

Used lon/lat envelopes (inSR=4326) to target 3 HRM sub-areas, filtering by `Shape__Area` between 2000 and 20000 sqm (0.2–2 hectares — suitable for subdivision concept layout testing).

| Area | Bounding Box (lon/lat) | Features Returned | Suitable (2000-20000 sqm) |
|------|----------------------|-------------------|--------------------------|
| Bedford | -63.40, 44.70 to -63.30, 44.75 | 10 | 10 |
| Dartmouth | -63.62, 44.65 to -63.52, 44.70 | 10 | 10 |
| Sackville | -63.70, 44.75 to -63.60, 44.80 | 10 | 10 |
| **Total** | | **30** | **30** |

**Note:** Initial attempts with Web Mercator (wkid=3857) envelopes returned 0 features. Switching to lon/lat envelopes with `inSR=4326` resolved this — the ArcGIS REST API handles the reprojection server-side.

### Selected Fixtures

30 unique parcels selected (10 per area, all PIDs unique). Each saved as:
- Individual: `tests/fixtures/real/parcel_<PID>.geojson`
- Combined: `tests/fixtures/real/all_parcels.geojson`

| PID | Area (sqm) | Area Units | Source Area |
|-----|-----------|------------|------------|
| 41243577 | 7611 | 3840 Square Metres | Bedford |
| 40529034 | 2629 | 12327 Square Feet | Bedford |
| 40064743 | 8417 | 51224 Square Feet | Bedford |
| 40650665 | 3110 | 17132 Square Feet | Bedford |
| 40313942 | 19236 | 9702 Square Metres | Bedford |
| 40418782 | 6126 | 3127 Square Metres | Bedford |
| 40430886 | 9948 | 1 Acres | Bedford |
| 00582452 | 11139 | 61293 Square Feet | Bedford |
| 40840803 | 8047 | 43729 Square Feet | Bedford |
| 40739534 | 7767 | 42180 Square Feet | Bedford |
| 41339730 | 9680 | 52642 Square Feet | Dartmouth |
| 41515230 | 7518 | 6212 Square Metres | Dartmouth |
| 41515248 | 10172 | 5148 Square Metres | Dartmouth |
| 41209347 | 3558 | 1798 Square Metres | Dartmouth |
| 41250945 | 9476 | 51607 Square Feet | Dartmouth |
| 40770885 | 2590 | 1307 Square Metres | Dartmouth |
| 40771511 | 5210 | 2633 Square Metres | Dartmouth |
| 40686016 | 8110 | 44149 Square Feet | Dartmouth |
| 40801078 | 2898 | 0 Acres | Dartmouth |
| 40801086 | 3812 | 0 Acres | Dartmouth |
| 41208364 | 3745 | 1889 Square Metres | Sackville |
| 40003303 | 8020 | 1 Acres | Sackville |
| 40003824 | 8859 | 4494 Square Metres | Sackville |
| 40586703 | 2529 | 13168 Square Feet | Sackville |
| 40093221 | 3883 | 1958 Square Metres | Sackville |
| 40543035 | 4574 | 2290 Square Metres | Sackville |
| 40116683 | 12262 | 67483 Square Feet | Sackville |
| 40589418 | 15962 | 2 Acres | Sackville |
| 40103889 | 8861 | 4269 Square Metres | Sackville |
| 00374033 | 2527 | 18000 Square Feet | Sackville |

**Note on ASSESSMENT field:** All parcels returned `ASSESSMENT = None`. The field exists in the schema but no assessment values were returned. This may be due to privacy restrictions on the public FeatureServer, or the field may be unpopulated in the current dataset version.

**Note on AREAUNITS field:** The `AREAUNITS` field contains a text description (e.g., "3840 Square Metres") rather than a numeric area value. The `Shape__Area` field (from ArcGIS) provides the actual area in projected square meters. For subdivision testing, `Shape__Area` is the reliable area measure.

---

## Issues & Notes

1. **Pagination not performed** — Each layer was queried once with maxRecordCount. Full datasets require pagination via `resultOffset`. The 2000-feature pages are sufficient for proof-of-concept but do not represent complete coverage.
2. **Web Mercator envelope filter failed** — Geometry filters using Web Mercator coordinates (wkid=3857) returned 0 features even with `inSR=3857`. Using lon/lat envelopes with `inSR=4326` worked correctly.
3. **Assessment values null** — All ASSESSMENT fields returned None. May be intentional privacy restriction on public endpoint.
4. **NSGI wetlands max 1000** — NSGI MapServer has a lower max record count (1000) than HRM ArcGIS (2000).
5. **AREAUNITS is text** — Contains descriptive text like "3840 Square Metres" or "1 Acres", not a clean numeric value. Use `Shape__Area` for area.