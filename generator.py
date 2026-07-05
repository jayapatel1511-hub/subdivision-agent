"""
Subdivision Agent — Layout Generator.

Generates candidate road layouts, carves lots along frontage,
and produces LayoutResult objects ready for scoring.

The algorithm is simple:
1. Given a parcel, access point, and rules, generate N road centerlines
2. For each road, compute the ROW polygon and subtract from buildable area
3. Carve lots along each road frontage using frontage-first slicing
4. Check each lot for compliance
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
)


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
        """Generate a road centerline from an access point and direction.

        Args:
            access: (x, y, dx, dy) — start point and unit direction into parcel
            length: Road length in metres
        """
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

        # Convert MultiLineString to LineString if needed
        if isinstance(clipped, MultiLineString):
            # Take the longest segment
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
            # Fallback: single road with a loop at the end
            return self._generate_cul_de_sac(length)

        a1 = self.parcel.access_points[0]
        a2 = self.parcel.access_points[1]

        # Create two roads from the two access points
        p1 = Point(a1.point)
        p2 = Point(a2.point)

        # Direct connection
        centerline = LineString([p1, p2])

        # Clip to parcel
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

        # Add a branch at the midpoint of the main road
        main = main_roads[0]
        mid_point = main.centerline.interpolate(0.5, normalized=True)

        # Perpendicular direction
        dx, dy = self.parcel.access_points[0].direction
        # Rotate 90 degrees
        px, py = -dy, dx

        # Branch length: ~40% of parcel width
        bounds = self.parcel.geometry.bounds
        branch_length = min(bounds[2] - bounds[0], bounds[3] - bounds[1]) * 0.35

        branch_centerline = LineString([
            (mid_point.x, mid_point.y),
            (mid_point.x + px * branch_length, mid_point.y + py * branch_length),
        ])

        # Clip to parcel
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

        # Add 2-3 branches along the main road
        bounds = self.parcel.geometry.bounds
        branch_length = min(bounds[2] - bounds[0], bounds[3] - bounds[1]) * 0.30

        dx, dy = self.parcel.access_points[0].direction
        px, py = -dy, dx  # perpendicular

        # Branch at 1/3 and 2/3 along the main road
        for frac in [0.33, 0.66]:
            point = main.centerline.interpolate(frac, normalized=True)

            # Branch in both perpendicular directions
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
            # Create frontage line (offset from centerline by half ROW)
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

                # Get the frontage segment for this column
                frontage_seg = substring(frontage_line, start_frac * frontage_length,
                                          end_frac * frontage_length)

                if frontage_seg.length < self.rules.min_frontage * 0.9:
                    continue

                # Compute depth direction: perpendicular to the frontage, pointing
                # away from the road and into the developable area.
                # We determine which perpendicular direction points away from the road
                # by checking which one moves the midpoint further from the road centerline.
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

                # Pick the one that moves the segment midpoint further from the road centerline
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

                # Determine how deep we can go by ray-casting from the midpoint
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

                # Subdivide the column into depth rows
                target_depth = self.rules.lot_depth_target
                num_rows = max(1, int(available_depth / target_depth))

                for row in range(num_rows):
                    depth_start = row * target_depth
                    depth_end = min((row + 1) * target_depth, available_depth)
                    current_depth = depth_end - depth_start

                    if current_depth < self.rules.min_depth * 0.8:
                        # Last row too shallow — merge with previous row
                        if row == num_rows - 1 and lots and depth_start > 0:
                            # Skip this row; it'll be handled as a wider previous lot
                            continue
                        continue

                    # Build lot polygon: frontage edge + back edge
                    coords = list(frontage_seg.coords)
                    lot_poly_coords = list(coords)

                    # Offset frontage by current_depth for the back edge
                    for x, y in reversed(coords):
                        lot_poly_coords.append((
                            x + depth_dx * current_depth,
                            y + depth_dy * current_depth,
                        ))

                    # If not the first row, also offset the front edge by depth_start
                    if depth_start > 0:
                        # Replace front edge with offset version
                        back_coords = [(x + depth_dx * depth_start, y + depth_dy * depth_start)
                                       for x, y in coords]
                        far_back_coords = [(x + depth_dx * depth_end, y + depth_dy * depth_end)
                                           for x, y in coords]
                        lot_poly_coords = back_coords + far_back_coords[::-1]

                    lot_poly = Polygon(lot_poly_coords)

                    # Clip to developable area
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

                    # Determine lot type
                    lot_type = LotType.REGULAR
                    if i == 0 or i == num_columns - 1:
                        lot_type = LotType.CORNER

                    # Check shape quality (compactness)
                    perimeter = clipped.length
                    area = clipped.area
                    shape_quality = (4 * math.pi * area) / (perimeter ** 2) if perimeter > 0 else 0
                    if shape_quality < 0.3:
                        lot_type = LotType.IRREGULAR

                    lot = Lot(
                        id=self._next_lot_id(),
                        geometry=clipped,
                        frontage_line=frontage_seg,
                        road_segment_id=self._current_road_index(road),
                        lot_type=lot_type,
                        access_point=Point(mid_point.x, mid_point.y),
                    )
                    lot.compute_properties()
                    lots.append(lot)

        return lots

    def _carve_lots_along_boundary(self, boundary_line: LineString,
                                     developable: Polygon,
                                     direction: str = "inward") -> list[Lot]:
        """Carve lots along a parcel boundary (for existing-road patterns).

        Used when lots front an existing road and no new internal road is needed.
        """
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

            lot_type = LotType.REGULAR
            if i == 0 or i == num_lots - 1:
                lot_type = LotType.CORNER
            perimeter = clipped.length
            area = clipped.area
            shape_quality = (4 * math.pi * area) / (perimeter ** 2) if perimeter > 0 else 0
            if shape_quality < 0.3:
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

    # ── Layout Generation ─────────────────────────────────────────────────

    def generate_layout(self, pattern: RoadPattern,
                        road_length: float = None) -> LayoutResult:
        """Generate a single layout option for the given pattern."""
        self._reset_lot_counter()

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
            # Use the front boundary (nearest to access point) as frontage
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

            # Carve lots along each road
            all_lots = []
            for road in roads:
                lots = self._carve_lots_along_road(road, developable)
                all_lots.extend(lots)

            # Try to fill remaining developable area with boundary lots
            remaining = developable
            for lot in all_lots:
                remaining = remaining.difference(lot.geometry)

            # If there's significant remaining area, try to create remainder lots
            if isinstance(remaining, MultiPolygon):
                for geom in remaining.geoms:
                    if geom.area >= self.rules.min_lot_area and isinstance(geom, Polygon):
                        # Try to create a remainder lot
                        lot = Lot(
                            id=self._next_lot_id(),
                            geometry=geom,
                            frontage_line=LineString(list(geom.exterior.coords[:2])),
                            lot_type=LotType.REMAINDER,
                        )
                        lot.compute_properties()
                        all_lots.append(lot)
            elif isinstance(remaining, Polygon) and remaining.area >= self.rules.min_lot_area:
                lot = Lot(
                    id=self._next_lot_id(),
                    geometry=remaining,
                    frontage_line=LineString(list(remaining.exterior.coords[:2])),
                    lot_type=LotType.REMAINDER,
                )
                lot.compute_properties()
                all_lots.append(lot)

            result.lots = all_lots
            result.roads = roads

        # Compute final metrics
        net_area = result.gross_area - result.area_lost_to_constraints - result.area_lost_to_row
        result.net_usable_area = net_area
        result.remaining_developable = net_area - sum(l.area for l in result.lots)

        lot_area_total = sum(l.area for l in result.lots if l.passes_all)
        result.saleable_land_pct = (lot_area_total / result.gross_area * 100) if result.gross_area > 0 else 0

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
            score = dist - dot * 10  # Weight facing direction
            if score < best_score:
                best_score = score
                best_seg = seg

        return best_seg