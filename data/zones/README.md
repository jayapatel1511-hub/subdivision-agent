# HRM Subdivision Constraint Tables

This directory contains CSV lookup tables for the HRM (Halifax Regional Municipality) subdivision concept design engine.

## Files

| File | Purpose |
|---|---|
| `hrm_zones.csv` | Zoning requirements per zone code (min area, frontage, setbacks, density) |
| `hrm_servicing.csv` | Lot requirements by servicing type (serviced, water-only, unserviced) |
| `hrm_buffers_constraints.csv` | Buffer widths and deductions (watercourses, wetlands, slopes, wells, septic) |
| `hrm_road_standards.csv` | Road ROW widths, carriageway, sidewalk, cul-de-sac standards |
| `hrm_stormwater_servicing.csv` | SWMF sizing, storm sewer criteria, open space dedication |

## How It Works

1. **User enters PID** → Auto-pulls parcel boundary + zone from GIS
2. **Zone code** → Loads `hrm_zones.csv` → Gets min lot area, frontage, setbacks, density
3. **Servicing status** → Loads `hrm_servicing.csv` → Adjusts min lot area (unserviced = much larger)
4. **Environmental buffers** → Loads `hrm_buffers_constraints.csv` → Applies all overlapping buffers, deducts from buildable area
5. **Road standards** → Loads `hrm_road_standards.csv` → Determines ROW width, sidewalk requirements
6. **Stormwater** → Loads `hrm_stormwater_servicing.csv` → Reserves SWMF area from yield

## Key Yield Killers (in order of impact)

1. **Unserviced septic reserve** — 50% of septic field area must be reserved for replacement. This DOUBLES the land needed for on-site sewage.
2. **Well isolation distances** — 30m protection radius around each well means wells drive lot layout on unserviced sites.
3. **Watercourse buffers** — 30m from any river/stream, 20m from intermittent streams. Carved directly from buildable area.
4. **Wetland buffers** — 30m from any wetland boundary. 60m for wetlands of special significance.
5. **Steep slopes** — 5m-9m setback from top of slope. Slopes >15% need geotechnical review.
6. **Road ROW** — 14-20m consumed per road. Every meter of road is a meter not producing lots.
7. **SWMF** — 3-5% of site area for wet detention pond.
8. **Open space dedication** — Up to 10% parkland dedication at HRM's discretion.

## Municipality Swap Pattern

To add another municipality:
1. Create a new folder (e.g., `cb_rm/`) with the same 5 CSV files
2. Column headers MUST match exactly
3. The engine loads the folder based on the `municipality` parameter
4. Zone codes are municipality-specific — the engine doesn't validate zone names, just looks them up

## Validation Status

⚠️ These tables are based on domain knowledge of HRM regulations as of 2025. Before production use:
- Verify against current HRM Land Use By-law (consolidated 2024 edition)
- Cross-check with NS On-Site Sewage Disposal Regulations (O. Reg. 202/2005 amended)
- Confirm Halifax Water Development Specifications for current storm/sewer standards
- Check HRM Regional Plan for open space dedication requirements