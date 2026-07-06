# Bylaw Extraction Log — data-scrape-v1

## Source PDFs

| File | Pages | Extracted? | Notes |
|------|-------|-----------|-------|
| `bedford_lub.pdf` | 117 | ✅ All zone tables | RSU, RTU (duplex + semi-detached), RMU, RTH, RCDD, RR, CGB, CSC, CMC, CHWY, ILI, IHO, IHI, SI, SU, P, POS, RPK, CD-1 |
| `regional_subdivision_bylaw.pdf` | 127 | ✅ Lot design defaults | S7, S31, S32, S38, S66-68 — lot area/frontage defaults for areas without LUB coverage; road standards deferred to Municipal Design Guidelines (separate doc, not in PDF set) |
| `downtown_halifax_lub.pdf` | 72 | ❌ Not applicable | Precinct-based built-form controls (height, heritage, streetscape), not lot-geometry zone tables. No traditional min lot area/frontage tables. |
| `halifax_water_design_specs_2023.pdf` | 181 | ❌ Not processed | Water/sewer design specs — not zoning/subdivision requirements. Could extract pipe sizing later if needed. |

## Zone Requirements Extracted

### Bedford LUB — 19 zones normalized to `bedford_zone_requirements.csv`

| Zone | Code | Min Lot Area | Min Frontage | Min Front Yard | Min Rear Yard | Min Side Yard | Max Height | Max Coverage | Page |
|------|------|-------------|-------------|----------------|---------------|---------------|------------|-------------|------|
| Residential Single Dwelling | RSU | 6,000 sq ft | 60 ft | 15 ft (local/collector), 30 ft (arterial) | 20 ft | 8 ft | 35 ft | 35% | 59 |
| Residential Two Dwelling - Duplex | RTU_duplex | 6,000 sq ft | 60 ft | 15/30 ft | 20 ft | 8 ft | 35 ft | 35% | 60 |
| Residential Two Dwelling - Semi/Linked | RTU_semidet | 3,000 sq ft/unit | 30 ft | 15/30 ft | 20 ft | 8 ft (common 2.5 ft) | 35 ft | 35% | 60 |
| Residential Multiple Dwelling | RMU | 10,000 sq ft | 100 ft | 30 ft | 40 ft | 15 ft or ½ height | 35 ft | 35% | 61 |
| Residential Townhouse | RTH | 2,000 sq ft/unit | 20 ft/unit | 15 ft (local/collector), 30 ft (arterial) | 20 ft | 10 ft | 35 ft | 35% | 62 |
| Residential Comprehensive Dev | RCDD | By development agreement | — | — | — | — | — | — | 63 |
| Residential Reserve | RR | 5 acres | 360 ft | 30 ft | 50 ft | 8 ft | 35 ft | 10% | 66 |
| General Business District | CGB | 10,000 sq ft | 60 ft | 15 ft | 0/40 ft* | 0/20 ft* | 3 floors | — | 67 |
| Shopping Centre | CSC | 5 acres | 500 ft | 30 ft | 0/40 ft* | 0/40 ft* | 52 ft | 50% | 68 |
| Mainstreet Commercial | CMC | 4,000 sq ft | 40 ft | 0 ft | 40 ft | — | — | — | 69 |
| Highway Oriented Commercial | CHWY | 20,000 sq ft | 100 ft | 15 ft | 0/40 ft* | 0/40 ft* | 35 ft | 50% | 72 |
| Light Industrial | ILI | 5,000 sq ft | 50 ft | 30 ft | 0/40 ft* | 0/40 ft* | 52 ft | 70% | 75 |
| Harbour Oriented Industrial | IHO | 1 acre | 100 ft | 30 ft | 0/40 ft* | 0/40 ft* | 52 ft | — | 80 |
| Heavy Industrial | IHI | 5,000 sq ft | 50 ft | 30 ft | — | 15 ft | 52 ft | 70% | 81 |
| Institutional | SI | 10,000 sq ft | 100 ft | 20/30 ft† | 20 ft | 8 ft or ½ height | 35 ft | 35% | 90 |
| Utilities | SU | 6,000 sq ft | 60 ft | 20/30 ft† | 20 ft | 8 ft | 35 ft | 35% | 91 |
| Park | P | 6,000 sq ft | 60 ft | 20/30 ft† | 20 ft | 8 ft or ½ height | 35 ft | 35% | 92 |
| Park Open Space | POS | 20,000 sq ft | 60 ft | 20/30 ft† | 20 ft | 8 ft | 20 ft | 10% | 93 |
| Regional Park | RPK | — | — | 20 m | 20 m | 20 m | — | 50%/<4ha, 5%/≥4ha | 94 |
| C&D Transfer Station | CD-1 | 40,000 sq ft | 49.2 ft | 82 ft | 98.4 ft | 98.4 ft | 36 ft | 50% | 97 |

\* 0 ft default, 40 ft where abutting residential zone  
† Local Street 20 ft; Collector or Arterial 30 ft

### Regional Subdivision By-law — Lot Design Defaults → `regional_subdivision_lot_defaults.csv`

The Regional Subdivision By-law does NOT contain road cross-section/pavement width tables. It defers to:
- **Municipal Design Guidelines** (Part A — Design Guidelines, Part B — Standard Details, Part C — Drafting Standards)
- **Engineering Regulations** (per utility company)

Key lot design rules extracted:
- **S7**: Lot area/frontage per applicable LUB; remainder min frontage 20m rural / 16m urban
- **S31(2)**: 61m min frontage on trunk/route highways (Schedule K) in rural areas
- **S32**: Dartmouth defaults — 464.5 m² / 15.24m frontage (serviced); 2700 m² / 45.72m (unserviced)
- **S38**: 2-lot frontage exemption (various plan areas)
- **S66-68**: Bedford-specific — 557.4 m² / 15.24m (RSU/RTU serviced); 4047 m² / 36.576m (RR unserviced)

## Provenance

All values extracted directly from PDF text via `pdfplumber` (Python). Source PDFs stored in `data/raw/bylaws/`. Each CSV row includes `source_doc` and `source_page` columns for traceability.

## What's NOT Here

- **Sackville LUB**: Not in PDF set (was HTML). Would need separate extraction.
- **Dartmouth LUB**: Not in PDF set. Regional Subdivision By-law S32 provides defaults.
- **Road standards**: Deferred to Municipal Design Guidelines — not in the 4 PDFs. Would need to source separately (HRM Engineering & Standards publication).
- **Halifax Water design specs**: 181-page PDF available but not processed (pipe/sewer specs, not zoning).