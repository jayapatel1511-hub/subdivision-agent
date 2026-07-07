# Phase 2 Task Spec — Blocks-First Generator Restructure

## Context
- Repo: `/Volumes/SSD/subdivision-agent`, branch `main` (after Phase 1 merge)
- Engine: 2D subdivision concept-layout optimizer (Python, Shapely)
- Scoreboard: **7/30** real parcels produce ≥1 passing lot (with real zone codes)
- **GLM-5.2 is the coding agent.** Implement everything below. Commit each milestone separately.
- All tests must pass after each commit: `python -m pytest tests/ -q`
- Do NOT regress the scoreboard below 7/30. Target: ≥20/30 after Phase 2.

## Problem
Strip-carving lots off roads is the root cause of:
1. Landlocked lots (back rows with no road contact)
2. Overlapping lots between multiple roads
3. Giant remainders on concave parcels (18,720 m² dead on L-shape fixture; 4,000–9,700 m² on real concave parcels yielding only 1–2 lots)

## Solution: Blocks-First
Standard civil engineering practice:
1. Generate a street network that partitions the parcel into **blocks** sized ≈ 2 × lot_depth deep and n × lot_width long
2. Subdivide each block into double-loaded lots (lots on both sides, backs touching)
3. Score as before

**Properties you get for free:** every lot fronts a street by construction; area conservation is trivial (blocks tile the parcel); the remainder question becomes "which blocks are too small".

## Architecture

### New: `block_generator.py`

```python
class BlockGenerator:
    """Blocks-first layout generator — partitions parcel into blocks, then lots."""
    
    def __init__(self, parcel: Parcel, rules: LayoutRules):
        self.parcel = parcel
        self.rules = rules
    
    def generate_layout(self, pattern: RoadPattern, road_length: float = None) -> LayoutResult:
        """Generate a blocks-first layout.
        
        Steps:
        1. Determine block dimensions from rules (block_depth = 2 * lot_depth_target, block_width = n * lot_width)
        2. Generate street network based on pattern (grid, spine, cul-de-sac tree)
        3. Streets partition developable area into blocks
        4. Subdivide each block into double-loaded lots
        5. Score as before
        """
```

### Block layout strategy by pattern:

| Pattern | Block Strategy |
|---------|---------------|
| `SINGLE_ROAD` | One road down the middle → 2 blocks (one each side) |
| `CUL_DE_SAC` | Road in + bulb → U-shaped block around bulb |
| `T_ROAD` | T creates 3 blocks |
| `SPINE_BRANCH` | Spine + branches → multiple blocks between branches |
| `LOOP_ROAD` | Loop creates a ring block + center block |
| `GRID` (NEW pattern) | Grid of streets → rectangular blocks (best yield for large parcels) |
| `EXISTING_ROAD` | Single block behind existing road frontage |

### Block subdivision:

Each block is a polygon. Subdivide it:
1. Orient block along its longest axis (minimum rotated rectangle)
2. Split block in half along the long axis (creates two rows — front row + back row, backs touching)
3. Carve each row into lots of `rules.min_lot_frontage` width (or wider if room allows)
4. Each lot gets `frontage_line` on the block's road-facing edge
5. Each lot gets `road_row_polygon` set to the adjacent road's ROW

### Concave parcel handling:

1. Use `shape_analysis.py` bottleneck detection to decompose concave parcels into near-convex chunks
2. Generate blocks per chunk
3. Connect road networks across chunk seams (a road crossing a seam connects both chunks)

## Tasks (in milestone order)

### Milestone 1: Blocks on rectangle/convex parcels

**Goal:** Beat current single-road yield on rectangles without invariant violations.

1. Create `block_generator.py` with `BlockGenerator` class
2. Implement block partitioning for SINGLE_ROAD and GRID patterns on rectangles
3. Implement block subdivision (double-loaded lots)
4. Wire into `LayoutGenerator.generate_layout()` as a new dispatch option (don't replace strip-carving yet — add a `use_blocks=True` flag or new pattern)
5. Keep existing strip-carving path as fallback

**Accept:**
- Rectangle 300×200m with SINGLE_ROAD: block-based yield ≥ strip-based yield
- All lots front a road (frontage > 0 via ROW-edge measurement)
- No overlapping lots
- Area conservation: lots + roads + remainders ≈ gross (±1%)
- All existing tests pass. Scoreboard ≥ 7/30.
- Add tests: `test_block_grid_no_landlocked`, `test_block_grid_area_conservation`, `test_block_grid_beats_strip_yield`

### Milestone 2: Blocks on concave parcels

**Goal:** Concave real parcels from the baseline produce ≥ floor(0.6 × area / (min_lot_area × 1.4)) passing lots.

1. Integrate `shape_analysis.py` decomposition into `BlockGenerator`
2. For each chunk: generate blocks oriented to chunk's OBB
3. Connect road network across chunk seams
4. Score combined result

**Accept:**
- L-shape fixture: remainder ≤ 30% of gross (was ~50%+)
- Concave real parcels: yield ≥ floor(0.6 × area / (min_lot_area × 1.4))
- All existing tests pass. Scoreboard ≥ 14/30.
- Add tests: `test_blocks_concave_decomposition`, `test_blocks_concave_remainder_bounded`

### Milestone 3: Network topologies (grid, cul-de-sac tree, loop)

**Goal:** Multiple road network topologies that work with blocks.

1. **Grid:** Generate orthogonal grid of streets at `block_depth` spacing. Best for large rectangular parcels.
2. **Cul-de-sac tree:** Spine road with cul-de-sac branches. Blocks between branches.
3. **Loop:** Real loop road that returns to the same boundary — creates ring block + center block.
4. Auto-select best pattern per parcel shape (largest parcel → grid; medium → spine; small → single/cul-de-sac)

**Accept:**
- Grid pattern produces highest yield on large rectangles (≥ 30 lots on 300×200m)
- Loop road produces an actual loop (returns to same boundary)
- Cul-de-sac tree produces branches with bulbs
- All existing tests pass. Scoreboard ≥ 20/30.
- Add tests: `test_grid_high_yield`, `test_loop_is_actual_loop`, `test_cul_de_sac_tree_branches`

## Integration Points

- **Phase 1 geometry:** Block roads use `fillet_centerline()`, `RoadSegment.row_polygon` with bulbs, intersection fillets
- **Phase 0 invariants:** All invariant tests must still pass
- **Web app:** Block layouts render correctly in the web app (lots + roads as GeoJSON)
- **QGIS export:** Block layouts export correctly

## CI / Testing
- After all milestones, run `python -m pytest tests/ -q` — must be all green
- Add new tests to `tests/test_phase2_blocks.py`
- The scoreboard regression test must pass (≥ 7/30 minimum, ≥ 20/30 target)

## Commit Format
One commit per milestone: `feat(blocks-1): block partitioning on rectangles`, `feat(blocks-2): concave decomposition`, `feat(blocks-3): network topologies`
Push to branch `phase2-blocks-first`.