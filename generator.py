"""
Subdivision Agent — Layout Generator.

Generates candidate road layouts, carves lots along frontage,
and produces LayoutResult objects ready for scoring.

The algorithm is simple:
1. Given a parcel, access point, and rules, generate N road centerlines
2. For each road, compute the ROW polygon and subtract from buildable area
3. Carve lots along each road frontage using frontage-first slicing
4. Check each lot for compliance
5. Merge tiny remainder slivers into adjacent lots where safe
"""

from __future__ import annotations

import math
from typing import Optional

from shapely.geometry import Polygon, LineString, Point, MultiPolygon, MultiLineString
from shapely.ops import substring, split, unary_union
from shapely import affinity

from models import (
    Parcel, LayoutRules, LayoutResult, Lot, RoadSegment, LayoutScore,
    RoadPattern, LotType, LayoutWarning, WarningLevel, ServiceType,
    compactness, poly_area, poly_union, poly_difference, poly_buffer,
    frontage_length, minimum_rotated_rectangle_area,
    ParcelShape,
)
from shape_analysis import detect_parcel_shape
from irregular_generator import IrregularRoadPlacer, IrregularLotCarver

class LayoutGenerator:
    """Generate subdivision layout options from a parcel + rules."""

    def __init__(self, parcel: Parcel, rules: LayoutRules):
        self.parcel = parcel
        self.rules = rules
        self._lot_counter = 0
        self._current_roads: list[RoadSegment] = []

    def _next_lot_id(self) -> int:
        self._lot_counter += 1
        return self._lot_counter

    def _reset_lot_counter(self):
        self._lot_counter = 0

    def _current_road_index(self, road: RoadSegment) -> int:
        """Get the index of a road in the current layout's road list."""
        try:
            return self._current_roads.index(road)
        except ValueError:
            return 0

    # ── Road Generation ──────────────────────────────────────────────────

    def _road_from_access(self, access: tuple[float, float, float, float],
                          length: float) -> LineString:
        """Generate a road centerline from an access point and direction."""
        x, y, dx, dy = access
        return LineString([(x, y), (x + dx * length, y + dy * length)])

    def _generate_single_road(self, length: float = None) -> list[RoadSegment]:
        """Single road through the parcel."""
        if not self.parcel.access_points:
            return []

        access = self.parcel.access_points[0]
        pt = access.point
        dx, dy = access.direction

        # Default: road runs 80% of parcel depth
        if length is None:
            bounds = self.parcel.geometry.bounds
            parcel_depth = max(bounds[3] - bounds[1], bounds[2] - bounds[0])
            length = parcel_depth * 0.80

        centerline = LineString([
            (pt[0], pt[1]),
            (pt[0] + dx * length, pt[1] + dy * length)
        ])

        # Clip to parcel
        clipped = centerline.intersection(self.parcel.geometry)
        if clipped.is_empty or clipped.length < 10:
            return []

        if isinstance(clipped, MultiLineString):
            clipped = max(clipped.geoms, key=lambda g: g.length)

        if not isinstance(clipped, LineString):
            return []

        return [RoadSegment(
            centerline=clipped,
            row_width=self.rules.row_width,
            road_type="local_residential",
            name="Road A",
        )]

    def _generate_cul_de_sac(self, length: float = None) -> list[RoadSegment]:
        """Cul-de-sac with bulb at the end."""
        roads = self._generate_single_road(length)
        if not roads:
            return []

        roads[0].is_cul_de_sac = True
        roads[0].name = "Cul-de-sac A"
        return roads

    def _generate_loop_road(self, length: float = None) -> list[RoadSegment]:
        """Loop road: two access points connected through the parcel."""
        if len(self.parcel.access_points) < 2:
            return self._generate_cul_de_sac(length)

        a1 = self.parcel.access_points[0]
        a2 = self.parcel.access_points[1]
        p1 = Point(a1.point)
        p2 = Point(a2.point)

        centerline = LineString([p1, p2])
        clipped = centerline.intersection(self.parcel.geometry)
        if clipped.is_empty or clipped.length < 10:
            return self._generate_single_road(length)

        if isinstance(clipped, MultiLineString):
            clipped = max(clipped.geoms, key=lambda g: g.length)

        if not isinstance(clipped, LineString):
            return self._generate_single_road(length)

        return [RoadSegment(
            centerline=clipped,
            row_width=self.rules.row_width,
            road_type="local_residential",
            name="Loop A",
        )]

    def _generate_t_road(self, length: float = None) -> list[RoadSegment]:
        """T-road: main stem + cross branch."""
        if not self.parcel.access_points:
            return []

        main_roads = self._generate_single_road(length)
        if not main_roads:
            return []

        main = main_roads[0]
        mid_point = main.centerline.interpolate(0.5, normalized=True)

        dx, dy = self.parcel.access_points[0].direction
        px, py = -dy, dx

        bounds = self.parcel.geometry.bounds
        branch_length = min(bounds[2] - bounds[0], bounds[3] - bounds[1]) * 0.35

        branch_centerline = LineString([
            (mid_point.x, mid_point.y),
            (mid_point.x + px * branch_length, mid_point.y + py * branch_length),
        ])

        clipped = branch_centerline.intersection(self.parcel.geometry)
        if clipped.is_empty or clipped.length < 10:
            return main_roads

        if isinstance(clipped, MultiLineString):
            clipped = max(clipped.geoms, key=lambda g: g.length)
        if not isinstance(clipped, LineString):
            return main_roads

        main_roads.append(RoadSegment(
            centerline=clipped,
            row_width=self.rules.row_width,
            road_type="local_residential",
            name="Branch B",
        ))
        return main_roads

    def _generate_spine_branch(self, length: float = None) -> list[RoadSegment]:
        """Spine road with side branches."""
        main_roads = self._generate_single_road(length)
        if not main_roads:
            return []

        main = main_roads[0]
        roads = list(main_roads)

        bounds = self.parcel.geometry.bounds
        branch_length = min(bounds[2] - bounds[0], bounds[3] - bounds[1]) * 0.30

        dx, dy = self.parcel.access_points[0].direction
        px, py = -dy, dx

        for frac in [0.33, 0.66]:
            point = main.centerline.interpolate(frac, normalized=True)
            for direction in [1, -1]:
                branch = LineString([
                    (point.x, point.y),
                    (point.x + px * branch_length * direction,
                     point.y + py * branch_length * direction),
                ])

                clipped = branch.intersection(self.parcel.geometry)
                if clipped.is_empty or clipped.length < 10:
                    continue
                if isinstance(clipped, MultiLineString):
                    clipped = max(clipped.geoms, key=lambda g: g.length)
                if not isinstance(clipped, LineString):
                    continue

                roads.append(RoadSegment(
                    centerline=clipped,
                    row_width=self.rules.row_width,
                    road_type="local_residential",
                    name=f"Branch {chr(65 + len(roads))}",
                ))

        return roads

    # ── Lot Carving ──────────────────────────────────────────────────────

    def _carve_lots_along_road(self, road: RoadSegment,
                                 developable: Polygon,
                                 road_side: str = "both") -> list[Lot]:
        """Carve lots along a road's frontage.

        Algorithm:
        1. Offset the road centerline to create left and right frontage lines
        2. For each side, divide the frontage into lot-width columns
        3. For each column, subdivide into depth rows (min_depth each)
        4. Clip each lot to the developable area
        """
        lots = []
        centerline = road.centerline
        row_half = road.row_width / 2

        sides = ["left", "right"] if road_side == "both" else [road_side]

        for side in sides:
            offset_dist = row_half + 0.5
            if side == "right":
                frontage_line = centerline.offset_curve(offset_dist)
            else:
                frontage_line = centerline.offset_curve(-offset_dist)

            if frontage_line.is_empty:
                continue

            lot_width = self.rules.lot_width_target
            frontage_length = frontage_line.length

            if frontage_length < self.rules.min_frontage:
                continue

            num_columns = max(1, int(frontage_length / lot_width))

            for i in range(num_columns):
                start_frac = i / num_columns
                end_frac = (i + 1) / num_columns

                frontage_seg = substring(frontage_line, start_frac * frontage_length,
                                          end_frac * frontage_length)

                if frontage_seg.length < self.rules.min_frontage * 0.9:
                    continue

                # Compute depth direction: perpendicular to the frontage,
                # pointing away from the road toward the parcel interior.
                start_point = Point(frontage_seg.coords[0])
                end_point = Point(frontage_seg.coords[-1])

                frontage_dx = end_point.x - start_point.x
                frontage_dy = end_point.y - start_point.y
                frontage_len = math.sqrt(frontage_dx**2 + frontage_dy**2)
                if frontage_len == 0:
                    continue

                # Two candidate perpendicular directions
                perp_a_dx = -frontage_dy / frontage_len
                perp_a_dy = frontage_dx / frontage_len
                perp_b_dx = frontage_dy / frontage_len
                perp_b_dy = -frontage_dx / frontage_len

                # Pick the direction that moves the midpoint further from the road centerline
                seg_mid = frontage_seg.interpolate(0.5, normalized=True)
                road_near = road.centerline.interpolate(
                    road.centerline.project(seg_mid)
                )
                dist_a = math.sqrt(
                    (seg_mid.x + perp_a_dx - road_near.x)**2 +
                    (seg_mid.y + perp_a_dy - road_near.y)**2
                )
                dist_b = math.sqrt(
                    (seg_mid.x + perp_b_dx - road_near.x)**2 +
                    (seg_mid.y + perp_b_dy - road_near.y)**2
                )
                if dist_a > dist_b:
                    depth_dx = perp_a_dx
                    depth_dy = perp_a_dy
                else:
                    depth_dx = perp_b_dx
                    depth_dy = perp_b_dy

                # Ray-cast from midpoint to find available depth
                mid_point = frontage_seg.interpolate(0.5, normalized=True)
                ray_length = max(developable.bounds[3] - developable.bounds[1],
                                 developable.bounds[2] - developable.bounds[0])
                ray_end = Point(mid_point.x + depth_dx * ray_length,
                                mid_point.y + depth_dy * ray_length)
                ray = LineString([(mid_point.x, mid_point.y),
                                  (ray_end.x, ray_end.y)])
                ray_clip = ray.intersection(developable)
                if ray_clip.is_empty:
                    available_depth = self.rules.min_depth
                elif isinstance(ray_clip, MultiLineString):
                    available_depth = max(g.length for g in ray_clip.geoms)
                elif isinstance(ray_clip, LineString):
                    available_depth = ray_clip.length
                else:
                    available_depth = self.rules.min_depth

                # Only carve the frontage row. Deeper "rows" have no road
                # frontage (row 0 lots sit between them and the road), so they
                # are landlocked — creating them as RESIDENTIAL/CORNER inflated
                # lot yield ~2x on deep parcels. Leftover depth behind the
                # frontage row is honestly handled as REMAINDER by the
                # remainder logic in generate_layout.
                target_depth = self.rules.lot_depth_target
                current_depth = min(target_depth, available_depth)

                if current_depth < self.rules.min_depth * 0.8:
                    continue

                # Build lot polygon from frontage + depth offset
                coords = list(frontage_seg.coords)
                lot_poly_coords = list(coords)

                for x, y in reversed(coords):
                    lot_poly_coords.append((
                        x + depth_dx * current_depth,
                        y + depth_dy * current_depth,
                    ))

                lot_poly = Polygon(lot_poly_coords)

                if developable.is_empty:
                    continue

                clipped = lot_poly.intersection(developable)
                if clipped.is_empty:
                    continue

                if isinstance(clipped, MultiPolygon):
                    clipped = max(clipped.geoms, key=lambda g: g.area)

                if not isinstance(clipped, Polygon):
                    continue

                # Minimum area check
                if clipped.area < self.rules.min_lot_area * 0.8:
                    continue

                # Classify lot type
                lot_type = LotType.RESIDENTIAL
                if i == 0 or i == num_columns - 1:
                    lot_type = LotType.CORNER

                # Check shape quality
                shape_q = compactness(clipped)
                if shape_q < 0.3:
                    lot_type = LotType.IRREGULAR

                lot = Lot(
                    id=self._next_lot_id(),
                    geometry=clipped,
                    frontage_line=frontage_seg,
                    road_segment_id=self._current_road_index(road),
                    lot_type=lot_type,
                    access_point=Point(mid_point.x, mid_point.y),
                    road_row_polygon=road.row_polygon,
                )
                lot.compute_properties()
                lots.append(lot)

        return lots

    def _carve_lots_along_boundary(self, boundary_line: LineString,
                                     developable: Polygon,
                                     direction: str = "inward") -> list[Lot]:
        """Carve lots along a parcel boundary (for existing-road patterns)."""
        lots = []
        lot_width = self.rules.lot_width_target
        frontage_length = boundary_line.length

        if frontage_length < self.rules.min_frontage:
            return []

        num_lots = max(1, int(frontage_length / lot_width))

        for i in range(num_lots):
            start_frac = i / num_lots
            end_frac = (i + 1) / num_lots

            frontage_seg = substring(boundary_line,
                                      start_frac * frontage_length,
                                      end_frac * frontage_length)

            if frontage_seg.length < self.rules.min_frontage * 0.9:
                continue

            lot_depth = self.rules.lot_depth_target

            start_point = Point(frontage_seg.coords[0])
            end_point = Point(frontage_seg.coords[-1])

            frontage_dx = end_point.x - start_point.x
            frontage_dy = end_point.y - start_point.y
            frontage_len = math.sqrt(frontage_dx**2 + frontage_dy**2)
            if frontage_len == 0:
                continue

            # Perpendicular direction (into the parcel)
            depth_dx = -frontage_dy / frontage_len
            depth_dy = frontage_dx / frontage_len

            coords = list(frontage_seg.coords)
            lot_poly_coords = list(coords)
            for x, y in reversed(coords):
                lot_poly_coords.append((x + depth_dx * lot_depth, y + depth_dy * lot_depth))

            lot_poly = Polygon(lot_poly_coords)
            clipped = lot_poly.intersection(developable)

            if clipped.is_empty:
                continue
            if isinstance(clipped, MultiPolygon):
                clipped = max(clipped.geoms, key=lambda g: g.area)
            if not isinstance(clipped, Polygon):
                continue
            if clipped.area < self.rules.min_lot_area * 0.8:
                continue

            lot_type = LotType.RESIDENTIAL
            if i == 0 or i == num_lots - 1:
                lot_type = LotType.CORNER
            shape_q = compactness(clipped)
            if shape_q < 0.3:
                lot_type = LotType.IRREGULAR

            lot = Lot(
                id=self._next_lot_id(),
                geometry=clipped,
                frontage_line=frontage_seg,
                lot_type=lot_type,
                access_point=Point(frontage_seg.interpolate(0.5, normalized=True).x,
                                   frontage_seg.interpolate(0.5, normalized=True).y),
            )
            lot.compute_properties()
            lots.append(lot)

        return lots

    # ── Sliver Merge ─────────────────────────────────────────────────────

    def _merge_slivers(self, lots: list[Lot], developable: Polygon,
                        target_area: float) -> list[Lot]:
        """Merge tiny remainder slivers into adjacent residential lots when safe.

        A sliver is a remainder with area < 10% of target_lot_area.
        It can be merged into an adjacent lot if:
        1. The remainder touches exactly one residential lot
        2. The merged lot still has reasonable shape (compactness >= 0.25)
        3. The merged lot doesn't exceed 2× target lot area
        """
        sliver_threshold = target_area * 0.10

        # Identify slivers (small remainders)
        remainders = [l for l in lots if l.lot_type == LotType.REMAINDER]
        residential = [l for l in lots if l.is_residential]

        if not remainders or not residential:
            return lots

        merged = set()  # indices of remainders that got merged
        for ri, rem in enumerate(remainders):
            if rem.area >= sliver_threshold:
                continue  # not a sliver, leave it alone

            # Find adjacent residential lots
            adjacent = []
            for li, res_lot in enumerate(residential):
                if rem.geometry.touches(res_lot.geometry) or (
                    rem.geometry.distance(res_lot.geometry) < 0.5
                ):
                    adjacent.append((li, res_lot))

            # Only merge if touching exactly one residential lot
            if len(adjacent) != 1:
                continue

            li, res_lot = adjacent[0]
            merged_poly = res_lot.geometry.union(rem.geometry)

            # Handle MultiPolygon — take largest
            if isinstance(merged_poly, MultiPolygon):
                merged_poly = max(merged_poly.geoms, key=lambda g: g.area)

            if not isinstance(merged_poly, Polygon):
                continue

            # Check merged lot quality
            merged_compactness = compactness(merged_poly)
            merged_area = merged_poly.area

            if merged_compactness < 0.25:
                continue  # would worsen shape too much
            if merged_area > target_area * 2.0:
                continue  # would be too large

            # Merge is safe — update the residential lot
            res_lot.geometry = merged_poly
            res_lot.compute_properties()
            merged.add(ri)

        # Remove merged remainders
        new_lots = [l for l in lots if l.lot_type != LotType.REMAINDER]
        new_lots.extend([r for ri, r in enumerate(remainders) if ri not in merged])
        return new_lots

    # ── Layout Generation ─────────────────────────────────────────────────

    def generate_layout(self, pattern: RoadPattern,
                        road_length: float = None) -> LayoutResult:
        """Generate a single layout option for the given pattern."""
        self._reset_lot_counter()

        # ── Shape detection dispatch ──
        shape = detect_parcel_shape(self.parcel.geometry)
        self.parcel.shape = shape

        if (shape not in (ParcelShape.RECTANGLE, ParcelShape.CONVEX)
                and self.rules.allow_irregular_carving):
            return self._generate_irregular_layout(pattern, road_length)

        # ── Existing rectangle code path (UNCHANGED) ──
        pattern_name = {
            RoadPattern.EXISTING_ROAD: "A",
            RoadPattern.SINGLE_ROAD: "B",
            RoadPattern.CUL_DE_SAC: "C",
            RoadPattern.LOOP_ROAD: "D",
            RoadPattern.T_ROAD: "E",
            RoadPattern.SPINE_BRANCH: "F",
        }.get(pattern, "X")

        result = LayoutResult(
            name=pattern_name,
            pattern=pattern,
            rules=self.rules,
            gross_area=self.parcel.gross_area,
        )

        # Compute buildable area (subtract constraints)
        buildable = self.parcel.buildable_area
        if buildable.is_empty:
            result.warnings.append(LayoutWarning(
                level=WarningLevel.FAIL,
                message="No buildable area after constraints",
            ))
            return result

        result.area_lost_to_constraints = self.parcel.gross_area - buildable.area

        if pattern == RoadPattern.EXISTING_ROAD:
            # No new road — carve lots along existing boundary
            roads = []
            if self.parcel.access_points:
                boundary = self._get_front_boundary()
                if boundary:
                    lots = self._carve_lots_along_boundary(boundary, buildable)
                    result.lots = lots
        else:
            # Generate road(s)
            generators = {
                RoadPattern.SINGLE_ROAD: self._generate_single_road,
                RoadPattern.CUL_DE_SAC: self._generate_cul_de_sac,
                RoadPattern.LOOP_ROAD: self._generate_loop_road,
                RoadPattern.T_ROAD: self._generate_t_road,
                RoadPattern.SPINE_BRANCH: self._generate_spine_branch,
            }

            gen_func = generators.get(pattern, self._generate_single_road)
            roads = gen_func(road_length)

            if not roads:
                result.warnings.append(LayoutWarning(
                    level=WarningLevel.FAIL,
                    message=f"Could not generate roads for pattern {pattern.value}",
                ))
                return result

            # Subtract road ROW from buildable area
            row_polys = [r.row_polygon for r in roads]
            row_union = unary_union(row_polys)

            developable = buildable.difference(row_union)
            if developable.is_empty:
                result.warnings.append(LayoutWarning(
                    level=WarningLevel.FAIL,
                    message="No developable area after road subtraction",
                ))
                return result

            result.area_lost_to_row = row_union.area

            # Store current roads for reference in lot carving
            self._current_roads = roads

            # Carve lots along each road. Subtract each road's carved lots
            # from developable before carving the next road, otherwise later
            # roads carve into area already claimed by earlier roads and lots
            # overlap (T-road/spine produced 48/76 overlapping pairs; remaining
            # could go negative).
            all_lots = []
            for road in roads:
                if developable.is_empty:
                    break
                lots = self._carve_lots_along_road(road, developable)
                all_lots.extend(lots)
                for lot in lots:
                    developable = developable.difference(lot.geometry)

            # Find remaining developable area and create remainder lots.
            # Lots were already subtracted above; re-differencing is a no-op
            # but keeps the GeometryCollection/MultiPolygon decomposition below
            # working from the final developable shape.
            remaining = developable
            for lot in all_lots:
                remaining = remaining.difference(lot.geometry)

            if isinstance(remaining, MultiPolygon):
                for geom in remaining.geoms:
                    if geom.area >= self.rules.min_lot_area and isinstance(geom, Polygon):
                        # Try to create a remainder lot with a rough frontage
                        coords = list(geom.exterior.coords)
                        frontage_coords = coords[:2] if len(coords) >= 2 else coords
                        frontage_line = LineString(frontage_coords)
                        lot = Lot(
                            id=self._next_lot_id(),
                            geometry=geom,
                            frontage_line=frontage_line,
                            lot_type=LotType.REMAINDER,
                        )
                        lot.compute_properties()
                        all_lots.append(lot)
            elif isinstance(remaining, Polygon) and remaining.area >= self.rules.min_lot_area:
                coords = list(remaining.exterior.coords)
                frontage_coords = coords[:2] if len(coords) >= 2 else coords
                frontage_line = LineString(frontage_coords)
                lot = Lot(
                    id=self._next_lot_id(),
                    geometry=remaining,
                    frontage_line=frontage_line,
                    lot_type=LotType.REMAINDER,
                )
                lot.compute_properties()
                all_lots.append(lot)

            # Sliver merge: absorb tiny remainders into adjacent lots
            all_lots = self._merge_slivers(all_lots, developable,
                                            self.rules.lot_width_target * self.rules.lot_depth_target)

            result.lots = all_lots
            result.roads = roads

        # Compute final area metrics
        # NOTE: saleable_land_pct is computed AFTER checker runs via compute_area_metrics()
        # Here we only compute the geometric metrics we can determine at generation time
        net_area = result.gross_area - result.area_lost_to_constraints - result.area_lost_to_row
        result.net_usable_area = net_area
        result.remaining_developable = net_area - sum(l.area for l in result.lots)

        return result

    def generate_all_patterns(self, road_length: float = None) -> list[LayoutResult]:
        """Generate layouts for all applicable patterns and return them sorted by score."""
        results = []

        for pattern in RoadPattern:
            try:
                result = self.generate_layout(pattern, road_length)
                results.append(result)
            except Exception as e:
                # Skip patterns that fail
                continue

        return results

    def _get_front_boundary(self) -> Optional[LineString]:
        """Get the front boundary of the parcel (nearest to access point)."""
        if not self.parcel.access_points:
            # Use the longest boundary edge
            coords = list(self.parcel.geometry.exterior.coords)
            longest = None
            max_len = 0
            for i in range(len(coords) - 1):
                seg = LineString([coords[i], coords[i+1]])
                if seg.length > max_len:
                    max_len = seg.length
                    longest = seg
            return longest

        # Find the boundary edge closest to and facing the access point
        access = self.parcel.access_points[0]
        access_pt = Point(access.point)

        coords = list(self.parcel.geometry.exterior.coords)
        best_seg = None
        best_score = float('inf')

        for i in range(len(coords) - 1):
            seg = LineString([coords[i], coords[i+1]])
            mid = seg.interpolate(0.5, normalized=True)
            dist = access_pt.distance(mid)
            # Prefer segments facing the access direction
            seg_dx = coords[i+1][0] - coords[i][0]
            seg_dy = coords[i+1][1] - coords[i][1]
            dot = seg_dx * access.direction[0] + seg_dy * access.direction[1]
            score = dist - dot * 10
            if score < best_score:
                best_score = score
                best_seg = seg

        return best_seg

    # ── Irregular Parcel Code Path ───────────────────────────────────────

    def _generate_irregular_layout(self, pattern: RoadPattern,
                                    road_length: float = None) -> LayoutResult:
        """Generate a layout for an irregular parcel using the irregular code path."""
        pattern_name = {
            RoadPattern.EXISTING_ROAD: "A",
            RoadPattern.SINGLE_ROAD: "B",
            RoadPattern.CUL_DE_SAC: "C",
            RoadPattern.LOOP_ROAD: "D",
            RoadPattern.T_ROAD: "E",
            RoadPattern.SPINE_BRANCH: "F",
        }.get(pattern, "X")

        result = LayoutResult(
            name=pattern_name,
            pattern=pattern,
            rules=self.rules,
            gross_area=self.parcel.gross_area,
        )

        # Compute buildable area (subtract constraints)
        buildable = self.parcel.buildable_area
        if buildable.is_empty:
            result.warnings.append(LayoutWarning(
                level=WarningLevel.FAIL,
                message="No buildable area after constraints",
            ))
            return result

        result.area_lost_to_constraints = self.parcel.gross_area - buildable.area

        # Existing road pattern — carve along boundary
        if pattern == RoadPattern.EXISTING_ROAD:
            boundary = self._get_front_boundary()
            if boundary:
                lots = self._carve_lots_along_boundary(boundary, buildable)
                result.lots = lots
            self._finalize_irregular_result(result, [], buildable)
            return result

        # Generate roads using irregular road placer
        pattern_str = pattern.value
        road_placer = IrregularRoadPlacer()
        roads = road_placer.place_roads(self.parcel, self.rules, pattern_str)

        if not roads:
            result.warnings.append(LayoutWarning(
                level=WarningLevel.FAIL,
                message=f"Could not generate roads for pattern {pattern.value}",
            ))
            return result

        # Subtract road ROW from buildable area
        row_polys = [r.row_polygon for r in roads]
        row_union = unary_union(row_polys)

        developable = buildable.difference(row_union)
        if developable.is_empty:
            result.warnings.append(LayoutWarning(
                level=WarningLevel.FAIL,
                message="No developable area after road subtraction",
            ))
            return result

        result.area_lost_to_row = row_union.intersection(self.parcel.geometry).area

        # Carve lots using irregular lot carver
        self._current_roads = roads
        carver = IrregularLotCarver()
        carver._lot_counter = 0  # Start lot IDs from 1

        all_lots = carver.carve(roads, developable, self.rules)

        # Renumber lots to be consistent
        for i, lot in enumerate(all_lots, 1):
            lot.id = i

        # Sliver merge using existing logic
        target_area = self.rules.lot_width_target * self.rules.lot_depth_target
        all_lots = self._merge_slivers(all_lots, developable, target_area)

        result.lots = all_lots
        result.roads = roads

        self._finalize_irregular_result(result, roads, buildable)
        return result

    def _finalize_irregular_result(self, result: LayoutResult,
                                    roads: list[RoadSegment],
                                    buildable):
        """Compute final area metrics for an irregular layout."""
        net_area = result.gross_area - result.area_lost_to_constraints - result.area_lost_to_row
        result.net_usable_area = net_area
        result.remaining_developable = net_area - sum(l.area for l in result.lots)
        if roads:
            result.area_lost_to_row = sum(r.area for r in roads)