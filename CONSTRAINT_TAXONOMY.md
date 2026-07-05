# HRM Subdivision Constraint Taxonomy

## What we've got covered

| Category | Data | Source |
|---|---|---|
| Zoning (area, frontage, depth, setbacks, density) | ✅ hrm_zones.csv | HRM Land Use Bylaw |
| Servicing (septic, well, serviced vs unserviced) | ✅ hrm_servicing.csv | NS On-Site Sewage Disposal Regs |
| Watercourse buffers | ✅ hrm_buffers_constraints.csv | HRM LUB Part 3 |
| Wetland buffers | ✅ hrm_buffers_constraints.csv | NSECC Policy |
| Road standards | ✅ hrm_road_standards.csv | HRM Subdivision Bylaw |
| Stormwater | ✅ hrm_stormwater_servicing.csv | Halifax Water specs |
| Slope setbacks | ✅ hrm_buffers_constraints.csv | HRM LUB |
| Flood plains / coastal flood | ✅ hrm_buffers_constraints.csv | HRM LUB |

---

## What you might have missed

### 1. Easements & Right-of-Way Encumbrances
- **Utility easements** (Nova Scotia Power, Eastlink, gas pipelines) — no structures within easement corridor. These are shown on property title search, not GIS.
- **Access easements** — if the parcel doesn't front a public road, you need a legal access easement (minimum 6m wide, typically 10-20m for shared).
- **Pipeline corridors** — gas transmission lines have regulated setback zones (varies by pressure class, typically 5-15m).

### 2. Well Field Protection Zones
- Halifax Water has **designated well field protection zones** around municipal well fields (Lake Major, Lake Micmac, etc.).
- Within these zones, **septic systems may be prohibited entirely**, forcing municipal sewer connection.
- Even serviced parcels near well fields may have additional restrictions.
- Source: Halifax Water Well Field Protection regulations.

### 3. Tree Protection & Urban Forest
- HRM Tree Protection By-law protects **significant trees** (trunk diameter > 50cm on public land, > 80cm on private in some areas).
- New subdivisions may need a **tree survey** before approval.
- Not a hard yield deduction but affects layout — you design around mature trees you can't remove.

### 4. Archaeological Screening
- NS Special Places Protection Act — Mi'kmaq heritage sites, historic archaeological resources.
- HRM has an **archaeological screening layer** in their GIS. Some areas require a cultural resource assessment before development.
- This is a **flag and hold** constraint — you can't pre-compute the buffer, you need to check the layer and if it triggers, the project stalls until a professional assessment clears it.

### 5. Species at Risk
- NS Endangered Species Act — if the parcel overlaps known habitat for endangered species (e.g., piping plover, mainland moose, wood turtle), development may be restricted or require mitigation.
- NSECC maintains species at risk occurrence data.
- Same as archaeological — **flag and hold**, not a fixed buffer you can pre-calculate.

### 6. Contaminated Sites
- NS Environment Act — if the parcel is on or adjacent to a contaminated site (former gas station, dry cleaner, industrial), a Phase I ESA is mandatory.
- Contamination doesn't just add a buffer — it can **kill the entire project** or require expensive remediation before any subdivision approval.
- Check: NS Environment contaminated sites registry.

### 7. Subdivision Approval Conditions (Non-Zoning)
- **HRM Subdivision By-law S-1** requires:
  - Minimum **2 emergency access routes** for subdivisions with >30 lots (dead-end >200m must have secondary access).
  - **Snow storage areas** for cul-de-sacs and commercial areas.
  - **Streetlighting** plan must be approved by HRM.
  - **Transit stops** may be required on collector roads for subdivisions >50 lots.
  - **Boulevard trees** required on local residential streets (minimum 1 per 15m of frontage).

### 8. Halifax Water Capacity
- Even if water/sewer mains exist at the parcel boundary, **Halifax Water must confirm capacity**.
- If the nearest main doesn't have capacity, you either:
  - Upgrade the main (developer pays, $100K+), or
  - Go unserviced (septic/well, much larger lots, huge yield impact)
- This is a **binary gate** — it changes which servicing.csv row applies.

### 9. Fire Hydrant Coverage
- HRM fire code requires **hydrant within 90m** of any lot for serviced subdivisions.
- If the parcel extends beyond hydrant reach, you either:
  - Pay for a hydrant extension ($15-30K per hydrant), or
  - Add sprinkler requirements to building code, or
  - Use unserviced (rural) fire protection standards (water tanker shuttle)
- Affects road layout — you design roads to reach hydrant coverage.

### 10. School Capacity & Development Charges
- HRM may impose **development charges** for school capacity, transit, and parks.
- These don't affect yield but they affect **project economics** — critical for go/no-go decisions.
- Not a geometric constraint, but worth flagging in the intake.

### 11. Stormwater Quality Requirements
- HRM requires **80% TSS removal** for stormwater before discharge to any watercourse.
- This is separate from quantity (peak flow) control.
- May require **oil-grit separators** or **treatment trains** in addition to the SWMF.
- Affects cost and space — treatment units need room too.

### 12. Lot Numbering & Addressing
- HRM has specific lot numbering conventions (odd/even by side, sequential from primary access).
- Not a yield constraint, but affects plan presentation and approval speed.

---

## Constraint Classification

| Type | How It Affects Yield | When It's Discovered |
|---|---|---|
| **Hard geometric** (zoning, frontage, setbacks) | Reduces buildable area | Pre-filled from zone code |
| **Hard geometric** (watercourse, wetland, slope buffers) | Carves out land | Pre-filled from GIS + buffers |
| **Hard geometric** (road ROW, SWMF) | Consumes land | Calculated from road layout |
| **Hard geometric** (septic reserve, well isolation) | Increases min lot size MASSIVELY | Pre-filled from servicing type |
| **Binary gate** (Halifax Water capacity, contaminated site) | Can change servicing type or kill project | Needs external check |
| **Binary gate** (archaeological, species at risk) | Can stall project indefinitely | Needs external assessment |
| **Cost** (development charges, hydrant extensions, utility upgrades) | Affects economics, not yield | Needs external quote |
| **Layout** (fire hydrant coverage, transit stops, tree protection) | Influences road layout, not yield directly | Pre-filled from road type + GIS |

---

## Recommended Intake Flow (Updated)

```
1. Enter PID/address
2. → Auto-pull: parcel boundary, zone, existing road frontage
3. → Auto-lookup: zone constraints, road standards
4. → Check GIS: watercourse, wetland, flood, slope, well field, archaeological, species at risk, contaminated sites
5. → Check Halifax Water: servicing availability and capacity
6. → Present pre-filled summary with confidence flags:
   ✅ = auto-verified from public data
   ⚠️  = auto-detected but needs confirmation
   ❌ = requires external assessment (archaeology, species, contamination)
7. User adjusts any values
8. Run engine → yield-optimized layout
```

This is the right architecture. The tool does the homework, flags what needs manual confirmation, and the engineer makes 3-4 decisions, not 20 guesses.