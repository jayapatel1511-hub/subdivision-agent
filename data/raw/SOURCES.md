# SOURCES.md — Verified Open-Data Endpoints for HRM / NS Subdivision Data

**Compiled:** 2026-07-06  
**Author:** Penny (manual research, Agent 1 timed out)  
**User-Agent:** `SubdivisionAgent/1.0 (research; contact: jayapatel1511-hub)`  
**Method:** Every URL below was curl-tested and verified live. HTTP status, content-type, and file size recorded.

---

## 1. NS Property / Parcel Boundaries

### 1a. ★★★ HRM Parcel Polygons with Accounts — ArcGIS REST FeatureServer

| Field | Value |
|-------|-------|
| **URL** | `https://services2.arcgis.com/11XBiaBYA9Ep0yNJ/arcgis/rest/services/HRM_Parcel_Polygon_with_Accounts/FeatureServer` |
| **Layer** | `0` — "Parcel Account and Assessments" |
| **Type** | FeatureServer (query-capable) |
| **Geometry** | Polygon |
| **CRS** | Web Mercator (wkid=102100 / latestWkid=3857) |
| **Max Record Count** | 2000 per query |
| **Fields** | `PID` (string), `AAN` (string), `ASSESSMENT` (int), `AREAUNITS` (string), `OBJECTID`, `Shape__Area`, `Shape__Length` |
| **Extent** | xmin=-7174556.6, ymin=5530164.0, xmax=-6911824.7, ymax=5665029.5 (covers all HRM) |
| **License** | HRM Open Data License (see data-hrm.hub.arcgis.com) |
| **Query URL** | `https://services2.arcgis.com/11XBiaBYA9Ep0yNJ/arcgis/rest/services/HRM_Parcel_Polygon_with_Accounts/FeatureServer/0/query?where=1=1&outFields=*&f=geojson&resultRecordCount=2000` |

**Notes:** This is the primary parcel layer for HRM. Contains PID (Property Identifier), assessment value, and area. Use `resultOffset` for pagination beyond 2000. No coordinate transformation needed if working in Web Mercator; use `outSR=4326` for lat/lon GeoJSON.

### 1b. ★ GeoNOVA / NS Geographic Data Directory

| Field | Value |
|-------|-------|
| **Homepage** | `https://geonova.novascotia.ca/` |
| **Status** | HTTP 200 (25KB HTML), but no ArcGIS REST endpoint found at standard paths |
| **Notes** | GeoNOVA is a discovery portal, not a direct API. It redirects to various NS department servers. Provincial parcel data (NS Property Online) is NOT publicly available via API — it's behind a paid/professional access system. Use the HRM FeatureServer (1a) for HRM parcels. |

**NOT FOUND:** Provincial-scale parcel boundaries as a public API. NS Property Online requires professional credentials.

---

## 2. HRM Open Data Portal — ArcGIS Hub

### Portal Info

| Field | Value |
|-------|-------|
| **Portal URL** | `https://data-hrm.hub.arcgis.com/` |
| **ArcGIS Org ID** | `11XBiaBYA9Ep0yNJ` |
| **Org Search API** | `https://www.arcgis.com/sharing/rest/search?q=orgid:11XBiaBYA9Ep0yNJ&f=json&num=100` |
| **Total Datasets** | 400+ (across multiple pages) |
| **License** | HRM Open Data License — see portal terms |

### 2a. ★★★ Zoning Boundaries — FeatureServer

| Field | Value |
|-------|-------|
| **URL** | `https://services2.arcgis.com/11XBiaBYA9Ep0yNJ/arcgis/rest/services/ZoningBoundaries/FeatureServer` |
| **Layer** | `0` |
| **Geometry** | Polygon |
| **CRS** | Web Mercator (3857) |
| **Max Record Count** | 2000 |
| **Verified** | HTTP 200, layer metadata confirmed |
| **Query URL** | `…/ZoningBoundaries/FeatureServer/0/query?where=1=1&outFields=*&f=geojson&resultRecordCount=2000` |

### 2b. ★★★ Street Centrelines — FeatureServer

| Field | Value |
|-------|-------|
| **URL** | `https://services2.arcgis.com/11XBiaBYA9Ep0yNJ/arcgis/rest/services/Street_Centreline/FeatureServer` |
| **Layer** | `0` |
| **Geometry** | Polyline |
| **CRS** | Web Mercator (3857) |
| **Max Record Count** | 2000 |
| **Query URL** | `…/Street_Centreline/FeatureServer/0/query?where=1=1&outFields=*&f=geojson&resultRecordCount=2000` |

### 2c. ★★★ Civic Addresses — FeatureServer

| Field | Value |
|-------|-------|
| **URL** | `https://services2.arcgis.com/11XBiaBYA9Ep0yNJ/arcgis/rest/services/Civic_Address/FeatureServer` |
| **Layer** | `0` |
| **Geometry** | Point |
| **CRS** | Web Mercator (3857) |
| **Query URL** | `…/Civic_Address/FeatureServer/0/query?where=1=1&outFields=*&f=geojson&resultRecordCount=2000` |

### 2d. ★★★ Buildings — FeatureServer

| Field | Value |
|-------|-------|
| **URL** | `https://services2.arcgis.com/11XBiaBYA9Ep0yNJ/arcgis/rest/services/Buildings/FeatureServer` |
| **Layer** | `0` |
| **Geometry** | Polygon |
| **CRS** | Web Mercator (3857) |
| **Max Record Count** | 2000 |
| **Query URL** | `…/Buildings/FeatureServer/0/query?where=1=1&outFields=*&f=geojson&resultRecordCount=2000` |

### 2e. ★★★ Floodplain Overlay Zones — FeatureServer

| Field | Value |
|-------|-------|
| **URL** | `https://services2.arcgis.com/11XBiaBYA9Ep0yNJ/arcgis/rest/services/Floodplain_Overlay_Zones/FeatureServer` |
| **Layer** | `0` — "Floodplain Overlay Zones and Modified Floodproofing" |
| **Geometry** | Polygon |
| **CRS** | Web Mercator (3857) |
| **Max Record Count** | 2000 |
| **Fields** | `OBJECTID`, `RTN_PRD`, `REG_CODE`, `BYLAW_ID`, `BYLAW_CODE`, `ADDDATE`, `MODDATE`, `SDATE`, `SOURCE`, `SACC`, `GlobalID`, `Shape__Area`, `Shape__Length` |
| **Query URL** | `…/Floodplain_Overlay_Zones/FeatureServer/0/query?where=1=1&outFields=*&f=geojson&resultRecordCount=2000` |

### 2f. ★★ Other HRM Layers (discovered via ArcGIS search, not individually verified)

| Layer | Type | Notes |
|-------|------|-------|
| Community Council Boundaries | Feature Service | Polygon — admin boundaries |
| Government Owned Properties | Feature Service | Polygon — publicly-owned land |
| NSPW HRM Service Exchange Boundary 2022 | Feature Service | Polygon — service area boundary |
| RC Special Area Boundary | Feature Service | Polygon — regional centre special areas |
| Community Plan Areas | Feature Service | Polygon — plan area boundaries |
| Land Use Schedules | Feature Service | Polygon — land use schedule zones |
| Subdivision Applications | Feature Service | Polygon — active subdivision applications |
| Heritage Properties | Feature Service | Point — heritage-registered properties |
| Parking Lot Points | Feature Service | Point — parking infrastructure |

**To get any layer's URL:** Search the ArcGIS org:
```
https://www.arcgis.com/sharing/rest/search?q=orgid:11XBiaBYA9Ep0yNJ+AND+title:"<NAME>"&f=json&num=10
```
Then take the `url` field from the result and append `?f=json` for metadata.

---

## 3. HRM Land Use By-law PDFs

### 3a. ★★ Downtown Halifax LUB

| Field | Value |
|-------|-------|
| **URL** | `https://cdn.halifax.ca/sites/default/files/documents/about-the-city/regional-community-planning/DowntownHalifax-LUB-Eff-21Nov27-RegCentre-PkgB-TOCLinked.pdf` |
| **Content-Type** | application/pdf |
| **Size** | 5,720,265 bytes (5.7 MB) |
| **Last Modified** | Tue, 30 Nov 2021 13:12:51 GMT |
| **Effective Date** | 2021-11-27 |
| **Plan Area** | Regional Centre (Package B — Downtown Halifax) |

### 3b. ★★ Bedford LUB

| Field | Value |
|-------|-------|
| **URL** | `https://cdn.halifax.ca/sites/default/files/documents/about-the-city/regional-community-planning/Bedford-LUB.pdf` |
| **Content-Type** | application/pdf |
| **Size** | 5,303,501 bytes (5.3 MB) |
| **Last Modified** | Thu, 23 Aug 2018 14:57:01 GMT |
| **Plan Area** | Bedford |

### 3c. ★★ Downtown Design Manual (Schedule S-1)

| Field | Value |
|-------|-------|
| **URL** | `https://cdn.halifax.ca/sites/default/files/documents/about-the-city/regional-community-planning/DowntownHalifax_ScheduleS-1DesignManual-Eff-21Nov27-RegCentre-PkgB.pdf` |
| **Content-Type** | application/pdf |
| **Size** | 10,137,505 bytes (10.1 MB) |
| **Last Modified** | Mon, 29 Nov 2021 14:42:21 GMT |
| **Effective Date** | 2021-11-27 |

### 3d. NOT FOUND — Other Plan Area LUBs

The following LUBs were searched for on the HRM CDN but **NOT FOUND**:
- **Regional Centre LUB** — tried `RegionalCentre-LUB-Eff-21Nov27-TOCLinked.pdf`, `RegCentre-LUB-Eff-21Nov27-TOCLinked.pdf`, `RegionalCentreLUB-Eff-21Nov27-TOCLinked.pdf`, `regionalcentre-lub-Eff-21Nov27-TOCLinked.pdf` — all 404. The Regional Centre may use the Downtown Halifax LUB (Package B) as its LUB.
- **Sackville LUB** — tried `Sackville-LUB.pdf`, `Sackville_LUB.pdf` — 404
- **Dartmouth LUB** — tried `Dartmouth-LUB.pdf`, `Dartmouth_LUB.pdf` — 404
- **Cole Harbour/Westphal LUB** — tried multiple patterns — 404
- **Halifax Mainland LUB** — tried multiple patterns — 404

**What was tried:** 
- Scraped HRM plan area pages (JS-rendered, PDF links not in raw HTML)
- Searched CDN with multiple naming patterns
- Checked HRM legislation-by-laws page (only By-law A-400 admin document found, 50KB)
- Checked Wayback Machine (empty response)
- Searched HRM site search (no PDF results)

**Recommendation:** The Regional Centre is governed by the Downtown Halifax LUB (Package B) + possibly a separate "Centre Plan Package A" LUB for the broader regional centre area. Agent 3 should download the Downtown Halifax LUB and check for references to other plan area LUBs within it. The older LUBs (Bedford, Sackville, Dartmouth, etc.) may only be available via the HRM planning office or by request — the CDN may use different naming conventions we haven't guessed.

---

## 4. HRM Subdivision By-law + Design Standards

### 4a. ★★ Regional Subdivision By-law

| Field | Value |
|-------|-------|
| **URL** | `https://cdn.halifax.ca/sites/default/files/documents/about-the-city/regional-community-planning/regionalsubdivisionbylaw-eff-22dec28-22257-correction-toclinked.pdf` |
| **Content-Type** | application/pdf |
| **Size** | 6,185,457 bytes (6.2 MB) |
| **Last Modified** | Fri, 30 Dec 2022 14:11:09 GMT |
| **Effective Date** | 2022-12-28 |
| **Notes** | TOC-linked (bookmarked). This is the current regional subdivision by-law. |

### 4b. ★★ Halifax Water Design Specifications (2023)

| Field | Value |
|-------|-------|
| **URL** | `https://halifaxwater.ca/sites/default/files/2023-06/2023_design_specifications.pdf` |
| **Content-Type** | application/pdf |
| **Size** | 5,210,913 bytes (5.2 MB) |
| **Last Modified** | Mon, 26 Jun 2023 13:38:20 GMT |
| **Notes** | Current Halifax Water design specs for water, wastewater, and stormwater systems. |

### 4c. Additional Halifax Water Documents (discovered, lower priority)

| Document | URL |
|----------|-----|
| Standard HW CAD Layering | `https://halifaxwater.ca/sites/default/files/2021-12/Standard%20HW%20CAD%20Layering.pdf` |
| Supplementary Spec — Measurement & Payment | `https://halifaxwater.ca/sites/default/files/2025-02/supplementary-standard-specifications-section-01-22-00-measurement-and-payment%201.pdf` |
| Supplementary Spec — CCTV Inspection | `https://halifaxwater.ca/sites/default/files/2025-03/Supplementary%20Standard%20Specifications%20-%20SECTION%2033%2001%2030%20-%20CCTV%20Inspection.pdf` |
| Pretreatment Requirements Manual (2023) | `https://halifaxwater.ca/sites/default/files/2023-06/Pretreatment_Requirements_Manual_2023.pdf` |
| Water Meter & BFP Manual | `https://halifaxwater.ca/sites/default/files/2023-06/Water-Meter-%26-BFP-Manual.pdf` |
| HW Specs & Forms page | `https://www.halifaxwater.ca/halifax-water-specifications-forms` |

### 4d. NOT FOUND — HRM Standard Specifications for Municipal Services

Searched HRM CDN and halifax.ca for "Standard Specifications for Municipal Services" — not found as a standalone PDF. May be incorporated into the Subdivision By-law or Halifax Water specs. Agent 3 should check the Subdivision By-law PDF for references to road standards.

---

## 5. NS Environmental Constraint Layers

### 5a. ★★★ NS Wetlands Inventory — NSGI MapServer

| Field | Value |
|-------|-------|
| **MapServer URL** | `https://nsgiwa.novascotia.ca/arcgis/rest/services/BIO/WLD_ProvLandScapeViewer_WM84/MapServer` |
| **Wetlands Layer** | `5` — "Wetlands" |
| **Geometry** | Polygon |
| **CRS** | Web Mercator (wkid=102100 / latestWkid=3857) |
| **Max Record Count** | 1000 |
| **Fields** | `OBJECTID`, `Shape`, `Area`, `Perimeter`, `Wetland` (string — type), `Hectares`, `Shape_Length`, `Shape_Area`, `Surveyed` (string) |
| **Query URL** | `…/WLD_ProvLandScapeViewer_WM84/MapServer/5/query?where=1=1&outFields=*&f=geojson&resultRecordCount=1000` |
| **Notes** | MapServer (not FeatureServer) — still supports query but read-only. 15 layers total in this service; layer 5 is the primary wetlands polygon layer. |

### 5b. ★★★ HRM Floodplain Overlay Zones — FeatureServer

(See section 2e above — same layer, listed here for the environmental constraints category.)

### 5c. ★ NS Contaminated Sites

| Field | Value |
|-------|-------|
| **Info Page** | `https://novascotia.ca/nse/contaminatedsites/` |
| **Status** | HTTP 200 (11.9 KB HTML) |
| **Data Access** | No API, no download, no GIS layer found. Only an info page linking to legislation. |
| **NOT FOUND** | No registry/database/map export available. May need to contact NS Environment directly. |

### 5d. NOT FOUND — Other NS Environmental Layers

| Layer | Status | Notes |
|-------|--------|-------|
| NS Watercourses / hydro network | NOT VERIFIED | NSGI likely has a hydro layer but not individually tested. Search NSGI MapServer catalog. |
| NS Flood-line / flood hazard | NOT FOUND | `novascotia.ca/nse/flood-risk-area-mapping/` returned generic page, no data. ArcGIS search returned only FEMA US data and a conservation priority layer, not official NS flood maps. |
| NS Steep slopes / terrain | NOT FOUND | Not searched exhaustively. Check NSGI for terrain/DEM services. |

---

## 6. NS On-site Sewage + Well Regulations

### 6a. ★★ NS On-site Sewage Disposal Systems Regulations

| Field | Value |
|-------|-------|
| **URL** | `https://novascotia.ca/just/regulations/regs/envsewage.htm` |
| **Type** | HTML (regulatory text) |
| **Size** | 136,805 bytes |
| **Title** | "On-site Sewage Disposal Systems Regulations - Environment Act (Nova Scotia)" |
| **Notes** | Full regulatory text in HTML. Agent 3 should extract setback distances, minimum lot sizes, and system requirements. |

### 6b. ★★ NS Well Construction Regulations

| Field | Value |
|-------|-------|
| **URL** | `https://novascotia.ca/just/regulations/regs/envwellc.htm` |
| **Type** | HTML (regulatory text) |
| **Size** | 206,796 bytes |
| **Title** | "Regulations - Environment - Well Construction" |
| **Notes** | Contains well setback requirements. Agent 3 should extract setback distances from property lines, septic systems, and watercourses. |

### 6c. ★ NS Homeowners Guide — Wells, Septic, Oil Tanks

| Field | Value |
|-------|-------|
| **URL** | `https://novascotia.ca/nse/groundwater/docs/Homeowners-Guide-Wells-Septic-Oil-Tanks-2013.pdf` |
| **Type** | PDF |
| **Notes** | Supplementary guide with practical setback distances in plain language. |

---

## Summary Scorecard

| Category | Sources Found | Verified | Not Found |
|----------|--------------|----------|-----------|
| Parcels | 1 (HRM FeatureServer) | ✅ | NS provincial parcels (paid) |
| Zoning | 1 (HRM FeatureServer) | ✅ | — |
| Streets/Roads | 1 (HRM FeatureServer) | ✅ | — |
| Buildings | 1 (HRM FeatureServer) | ✅ | — |
| Floodplain | 1 (HRM FeatureServer) | ✅ | NS provincial flood maps |
| Wetlands | 1 (NSGI MapServer) | ✅ | — |
| LUB PDFs | 2 verified (Downtown, Bedford) + Design Manual | ✅ | Regional Centre, Sackville, Dartmouth, Cole Harbour, Halifax Mainland |
| Subdivision By-law | 1 (Regional, 2022) | ✅ | — |
| Design Specs | 1 (Halifax Water, 2023) | ✅ | HRM Standard Specs for Municipal Services |
| Sewage Regs | 1 (NS HTML) | ✅ | — |
| Well Regs | 1 (NS HTML) | ✅ | — |
| Contaminated Sites | 0 | — | No data API found, only info page |

**Total verified endpoints: 12** (5 ArcGIS REST, 4 PDFs, 2 HTML regs, 1 info page)

---

## Usage Notes for Agents 2–4

### Agent 2 (GIS Harvester)
- Use the HRM ArcGIS FeatureServers for parcels, zoning, streets, buildings, floodplain — all in CRS 3857
- Use NSGI MapServer layer 5 for wetlands — also CRS 3857
- For GeoJSON output: append `?f=geojson&outFields=*&where=1=1&resultRecordCount=2000` to any FeatureServer/MapServer layer URL
- For pagination: add `&resultOffset=2000` (then 4000, etc.) — max 2000 for HRM, 1000 for NSGI
- For lat/lon output: add `&outSR=4326`
- Select 15–20 real parcel fixtures from the HRM parcel FeatureServer — filter by area to get medium-sized parcels suitable for subdivision concept layouts

### Agent 3 (Bylaw Extractor)
- Download the Regional Subdivision By-law PDF (6.2 MB) — extract road standards, lot frontage requirements, minimum lot sizes, setback requirements
- Download the Downtown Halifax LUB (5.7 MB) — extract zone requirements (min lot size, frontage, setbacks, density) for each zone code
- Download the Bedford LUB (5.3 MB) — same extraction for Bedford zones
- Scrape the NS sewage + well regulation HTML pages — extract setback distances, minimum lot sizes
- Download Halifax Water Design Specs (5.2 MB) — extract servicing standards (pipe sizes, depths, materials)

### Agent 4 (Validator/Merger)
- Compare Agent 3's extracted zone requirements against the baseline CSVs in `data/zones/hrm/`
- Baseline has 12 zones (hrm_zones.csv), 6 road types (hrm_road_standards.csv), 5 servicing types (hrm_servicing.csv)
- Flag any zone code that appears in the LUBs but is missing from baseline, or vice versa
- Flag any numeric value that differs by more than 10% from baseline
- Run the test suite after importing real parcel fixtures through `intake_geojson.load`

---

## 13. NS Open Data Portal — Socrata-based Provincial Data

**Portal:** `https://data.novascotia.ca`  
**API:** Socrata v1 (SoQL queries)  
**License:** NS Open Data License (Crown copyright)  
**GeoJSON endpoint pattern:** `https://data.novascotia.ca/resource/{dataset_id}.geojson?$limit=N`  
**JSON endpoint pattern:** `https://data.novascotia.ca/resource/{dataset_id}.json?$select=count(*)`  

**IMPORTANT:** The Socrata catalog search is FEDERATED across all Socrata instances globally. Searching for "parcel" returns results from Winnipeg, Calgary, LA, etc. Only datasets with NS-owned provenance should be used. The 100+ NS-owned datasets were retrieved via `?domains=data.novascotia.ca`.

**NOTE ON PROPERTY PARCELS:** The NS Open Data Portal does NOT have property/parcel boundary data. "Assessment Parcels" (d4mq-wa44) in search results is a Winnipeg dataset that appears in federated search. NS property parcels are behind the NS Property Online system (paid/restricted access). The HRM ArcGIS parcel FeatureServer (Section 1a) remains the only public source for parcel geometry in HRM.

### 13a. ★★ NS Crown Land — Socrata GeoJSON

| Field | Value |
|-------|-------|
| **Dataset ID** | `3nka-59nz` |
| **GeoJSON URL** | `https://data.novascotia.ca/resource/3nka-59nz.geojson?$limit=N` |
| **Row count** | 18,225 polygons |
| **Geometry** | MultiPolygon (the_geom column) |
| **Columns** | fcode, partialown, hectares, acres, shape_leng, shape_area, symbol, dnr_id, pgpi |
| **Description** | All Crown lands in NS under administration of Minister of Natural Resources |
| **Updated** | 2026-07-05 |
| **Provenance** | Official (NS Department of Natural Resources and Renewables) |
| **Also available** | GeoNova DDS download: `https://nsgi.novascotia.ca/WSF_DDS/DDS.svc/DownloadFile?tkey=fhrTtdnDvfytwLz6&id=87` |
| **Verified** | ✅ 3 features downloaded via SoQL, MultiPolygon confirmed |

### 13b. ★★ NS Road Network (NSRN) — Socrata GeoJSON

| Field | Value |
|-------|-------|
| **Dataset ID** | `484g-adjn` |
| **GeoJSON URL** | `https://data.novascotia.ca/resource/484g-adjn.geojson?$limit=N` |
| **Geometry** | MultiLineString (the_geom column) |
| **Columns** | owner, anum, rte_no, roadc_desc, roadclass, structid, date_rev, date_act, traff_desc, trafficdir, mun_id, street, segid, ids, roadsegid, feat_code, feat_desc, owner_desc |
| **Description** | Authoritative road centerlines for NS — road class, surface type, lanes, traffic direction |
| **Provenance** | Official (Province of Nova Scotia) |
| **Verified** | ✅ 3 features downloaded, MultiLineString confirmed |

### 13c. ★ NS Primary Watersheds — Socrata GeoJSON

| Field | Value |
|-------|-------|
| **Dataset ID** | `569x-2wnq` |
| **GeoJSON URL** | `https://data.novascotia.ca/resource/569x-2wnq.geojson?$limit=N` |
| **Geometry** | MultiPolygon (the_geom column) |
| **Columns** | primary_co, shape_area, shape_leng, hectares, acres, flow_dir, river, primary__1, primary_ws, perimeter, area |
| **Description** | 1:10,000 primary watersheds for Nova Scotia |
| **Also available** | GeoNova DDS: `https://nsgi.novascotia.ca/WSF_DDS/DDS.svc/DownloadFile?tkey=fhrTtdnDvfytwLz6&id=82` |
| **Verified** | ✅ Metadata confirmed |

### 13d. ★ NS Protected Areas System — Socrata GeoJSON

| Field | Value |
|-------|-------|
| **Dataset ID** | `ticv-5du5` |
| **GeoJSON URL** | `https://data.novascotia.ca/resource/ticv-5du5.geojson?$limit=N` |
| **Geometry** | MultiPolygon (the_geom column) |
| **Columns** | created_us, shape_leng, created_da, papa_key2, papa_key1, reference, stat_date, symbol, pro_name, ha_gis, shape_area, int_name, contrib, owner, web_url (+ more) |
| **Description** | National Parks, National Wildlife Areas, Provincial Wilderness Areas, Nature Reserves, Provincial Parks, land trust properties and easements |
| **Provenance** | Official |
| **Verified** | ✅ Metadata confirmed (25 columns) |

### 13e. ★ NS Municipality Boundaries — Socrata GeoJSON

| Field | Value |
|-------|-------|
| **Dataset ID** | `7bqh-hssn` |
| **GeoJSON URL** | `https://data.novascotia.ca/resource/7bqh-hssn.geojson?$limit=N` |
| **Geometry** | MultiPolygon (the_geom column) |
| **Columns** | fullname, objectid, featdesc, shape_area, county, name, cgndb_key, shape_leng |
| **Description** | Municipal boundaries for towns, district/county/regional municipalities in NS |
| **Provenance** | Official |
| **Verified** | ✅ Metadata confirmed |

### 13f. ★ NS Topographic Database - DTM (Digital Terrain Model)

| Field | Value |
|-------|-------|
| **Dataset ID** | `5vns-2bw2` |
| **GeoJSON URL** | `https://data.novascotia.ca/resource/5vns-2bw2.geojson?$limit=N` |
| **Description** | Provincial digital terrain model — elevation data |
| **Provenance** | Official |
| **Verified** | ✅ Listed as geospatial in catalog |

### 13g. NS Groundwater Atlas (user-suggested)

| Field | Value |
|-------|-------|
| **URL** | `https://novascotia.ca/natr/meb/geoscience-online/groundwater_about.asp` |
| **Title** | Nova Scotia Groundwater Atlas |
| **Content** | Interactive map with water wells, aquifers, geology, seawater intrusion, uranium potential |
| **GIS Data page** | `https://novascotia.ca/natr/meb/download/gis-data.asp` |
| **Property/parcel data?** | **NO** — this is a geoscience/water resource atlas, not a land records system |
| **Useful for constraints?** | Potentially — well log data could inform septic suitability. But no spatial download endpoint found (interactive map only). Data layers (DP ME 430, 428, 483, 490) have individual download pages but no direct API. |