# Irregular Parcel v1 — Brainstorm Reference

Two AI brainstorming sessions on extending subdivision-agent from Rectangle v2 to irregular parcels.

---

## Session 1: Qwen 3.5 (Local)

### 1. GeoJSON Input Pipeline
- **Topology Repair First:** `shapely.validation.make_valid(geom)` before any processing
- **Coordinate Snapping:** `shapely.ops.snap_to_grid(geom, snap_distance=0.1)` for GPS drift
- **SRID Normalization:** GeoJSON = WGS84 (EPSG:4326). Need UTM re-projection for meter-based subdivision math
- **Feature Metadata Extraction:** Map GeoJSON properties like `{min_area, max_aspect_ratio}` directly into scoring constraints
- **Self-intersection Repair:** Convert invalid rings to polygons, handle MultiPolygon (pick largest)

### 2. Road Placement Algorithms
- **Buffer-Intersect Method:** Subtract setback buffer from parcel boundary, project roads inside remaining area
- **Road Network Mesh:** Use `shapely.ops.split` with road centerlines as buffers around parcel boundary intersections
- **Convex Vertex Projection:** Identify convex vertices, project lines from these toward centroid using Delaunay triangulation
- **Corridor Constraint Strategy:** Roads as deducted areas, not overlaid features. `P_available = P - Buffer(P_outer, setback)`
- **A*/Voronoi Pathfinding:** On available land area after deducting setback zones from irregular parcels

### 3. Polygon Clipping Strategies
- **Recursive Convex Hull Peeling:** Start with convex hull, subtract existing parcels until hitting irregular edge constraints
- **Delaunay Triangulation Split Points:** Use `shapely.ops.split` with lines from Delaunay triangulation within parcel interior
- **Lloyd's Relaxation:** Voronoi partitioning constrained by boundary polygons (not just rectangles)
- **Constrained Cut Algorithm:** Cut lines only drawn inside valid land buffers

### 4. Edge Cases
- **Concavity Detection:** Reflex vertices (>180°). If a split line crosses into concave region, it risks narrow corner lots with bad aspect ratio
- **Minimum Width Threshold:** If projected cut creates area < min_area, skip and select next candidate line
- **Narrow Corridors:** Minimum Spanning Tree or skeleton analysis. If corridor width < road_width + buffer, mark as "No-Split"
- **Morphological Erosion:** Use `shapely` polygon difference to remove resulting polygons with area < 2% of average lot size, append back to parent parcels
- **Sliver Re-absorption:** After splits, collect slivers by adjacency to valid lots. `lot.union(sliver)` if sliver.area < threshold

### 5. Architecture
- **Strategy Pattern:** `BaseParcelGenerator` → `RectangleEngine` + `IrregularEngine`
- **Geometry Detection:** At initialization, check `is_quadrilateral(parcel)` → route to RectangleEngine, else IrregularEngine
- **Shared Scoring Engine:** Scorer takes dictionary of Shapely objects. `.area`, `.perimeter`, shape index work universally
- **Factory Pattern:** Input polygon type determines engine selection automatically

---

## Session 2: GLM-5.1 (Cloud via z.ai)

### 1. GeoJSON Input Pipeline
**Function: `normalize_geojson(geo_dict, target_crs_epsg)`**

1. **Z-Stripping & 3D Flattening:** GeoJSON Z coords break Shapely 2D ops. Use `wkt_2d = shapely.wkt.dumps(geom, output_dimension=2)` then `shapely.from_wkt(wkt_2d)`
2. **Metric CRS Projection:** Check if EPSG:4326 → calculate UTM zone via `pyproj.CRS.area_of_use()`, transform with `shapely.ops.transform(proj, geom)`
3. **Polygon Orientation Enforcement:** `shapely.geometry.polygon.orient(polygon, sign=1.0)` — CCW exterior, CW interior. Critical for consistent `split` and `buffer`
4. **Topological Repair:** `shapely.make_valid()`. If MultiPolygon result, select `max(polys, key=lambda p: p.area)`
5. **Sliver Hole Removal:** Iterate `polygon.interiors`, if `Polygon(interior).area < min_hole_area`, exclude from reconstructed polygon
6. **Vertex Densification:** `shapely.segmentize(polygon, max_segment_length=5.0)` — interpolate points along long edges for accurate `split` intersections

### 2. Road Placement on Irregular Parcels
**Function: `generate_irregular_roads(polygon, params)`**

1. **Minimum Rotated Bounding Box (MRB):** `polygon.minimum_rotated_rectangle` → extract longest edge → calculate azimuth → rotate polygon, run axis-aligned grid, rotate results back
2. **PCA Routing:** Extract `polygon.exterior.coords`, subtract centroid, compute eigenvectors via `numpy.linalg.eig`. Primary eigenvector = dominant axis = primary road heading
3. **Medial Axis (Skeleton) Spine:** Convert boundary to Voronoi graph, clip to interior. Find longest path → main collector road. For organic shapes (bean, kidney)
4. **Contour-Following Loop Roads:** `polygon.buffer(-setback)` creates inner island. `polygon.buffer(-setback-road_width)`. Difference = loop road polygon conforming to parcel edge
5. **Angle-Bisector Cul-de-Sacs:** Vertices where interior angle < 90° → compute bisector vector → extend line along bisector for `max_culdesac_depth` → seed road split

### 3. Lot Carving with Shapely
**Function: `sweep_carve(polygon, frontage_line, target_area)`**

1. **Binary Search Sweeping:** Take `frontage_line`, binary search offset distance `d`. Construct cut line parallel at distance `d`. `shapely.split(polygon, cut_line)`. If front piece area > target → decrease d, else increase. 15 iterations for ~0.1m precision
2. **Radial Fan Carving (Pie-Cuts):** Apex on road centerline. Cast `shapely.LineString` rays from apex at angles. `shapely.split(polygon, unary_union(rays))` → wedge-shaped lots. Good for cul-de-sacs
3. **Greedy Frontage Stepping:** Extract `frontage = polygon.intersection(road_polygon)`. Step along frontage by `min_lot_width`. Cast perpendicular line at each step. `split`, grab lot, update `remainder = polygon.difference(lot)`
4. **Cookie-Cutter Grid Clipping:** Generate axis-aligned grid over bounding box. `shapely.intersection(polygon, grid_cell)` per cell. Filter by `min_lot_area`. Yields irregular boundary-respecting lots
5. **Snap-Split-Sanitize:** Buffer cut line by 0.01m before splitting. Use `polygon.difference(buffered_line)` instead of `split`. Avoids topological errors from floating-point near-misses

### 4. Concave/Irregular Edge Cases
**Function: `heal_geometry(polygon, params)`**

1. **Sliver Collapsing:** `polygon.buffer(-epsilon)` (0.5m) then `buffer(epsilon)` — dissolves slivers < 0.5m wide while preserving valid shape girth
2. **Convex Decomposition (L-Shape Handling):** Hertel-Mehlhorn algorithm to decompose concave polygon into convex components. Run rectangle-optimizer on each convex piece independently, then stitch results
3. **Narrow Corridor Detection:** Compute Medial Axis. For each axis point, `point.hausdorff_distance(polygon.boundary) * 2` ≈ local width. If width < `min_buildable_width`, `split` at pinch point, discard inaccessible portion
4. **Concavity Infill:** `polygon.convex_hull.difference(polygon)` identifies concavities. If area < `min_lot_area`, absorb by `polygon.union(concavity_polygon)` to square off before generation
5. **Sliver Re-absorption:** After splits, group slivers by adjacency to valid lots. `lot.union(sliver)` if `sliver.area < threshold`. Ensures 100% area coverage with clean boundaries

### 5. Architecture: Extending Without Breaking Rectangles
**Pattern: Strategy + Pipeline**

1. **Geometry-Native State:** Store only `shapely.Polygon remainder` and `shapely.LineString frontage`. Access bounds via `remainder.bounds`. Rectangle generator initializes with `box(x, y, x+w, y+h)`
2. **Strategy Pattern:** Abstract `BaseGenerator` with `place_roads(remainder)`, `carve_lots(remainder, roads)`, `score_layout(lots)`. Implement `RectangleGridGenerator` and `IrregularSweepGenerator`. Factory selects based on `is_rectangle(input_geom)`
3. **Adapter for Scoring Engine:** Don't rewrite scorer. Write `extract_metrics(lot_polygon, road_polygon)` → calculates `area`, `frontage_length = lot.intersection(road_polygon).length`, `depth = compute_depth(lot, road_polygon)` using Shapely. Pass standard floats to existing scorer
4. **Pipeline DAG:** `normalize → route_roads → carve_lots → heal_slivers → score`. Rectangle path skips `heal_slivers`. Irregular path runs full pipeline
5. **Tolerance Context:** Inject `ToleranceContext(snap=0.01, area_epsilon=0.5)` into generator. Use in all Shapely ops (`shapely.snap(a, b, ctx.snap)`). Rectangle defaults to 0.0, irregular uses meters
6. **Visual Debugging Hooks:** Optional `emit_step(step_name, geom)` callback. Hook into QGIS/Folium to render state at `post_road`, `post_carve`, `post_heal` without breaking program flow

---

## Key Takeaways (Merged)

### Priority 1 — Must Have
- `normalize_geojson()`: make_valid, Z-strip, CRS projection, orient, segmentize
- `is_rectangle()` detection for factory routing
- Binary search sweep carving (frontage-perpendicular, area-targeted)
- Snap-Split-Sanitize pattern (buffer cut line before difference)
- Sliver heal pattern (negative buffer then positive buffer)

### Priority 2 — Should Have
- MRB alignment for road orientation on irregular parcels
- Medial axis / skeleton for road spine placement
- Narrow corridor detection via skeleton width analysis
- Concavity infill for unbuildable pockets

### Priority 3 — Nice to Have
- PCA routing for highly organic shapes
- Radial fan carving for cul-de-sacs
- Convex decomposition (Hertel-Mehlhorn) for L-shapes
- Cookie-cutter grid clipping as fallback
- Visual debugging hooks (QGIS/Folium export per step)

### Architecture Decision
- **Strategy pattern** is the clear winner from both sessions
- Rectangle v2 code becomes `RectangleGridGenerator`
- New `IrregularSweepGenerator` for arbitrary polygons
- Shared `Scorer` with metric extraction adapter
- Pipeline: `normalize → route_roads → carve_lots → heal_slivers → score`