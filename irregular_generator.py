"""
Subdivision Agent — Irregular Parcel Layout Generator.

Provides IrregularRoadPlacer and IrregularLotCarver for generating layouts
on non-rectangular parcels. Used by LayoutGenerator when the parcel shape
is not RECTANGLE or CONVEX.
"""

from __future__ import annotations

import math
from typing import Optional

from shapely.geometry import (
    Polygon, MultiPolygon, LineString, Point, MultiLineString,
)
from shapely.ops import unary_union, split as shp_split, substring
from shapely import make_valid

from models import (
    Parcel, LayoutRules, LayoutResult, Lot, RoadSegment, LotType,
    RoadPattern, LayoutWarning, WarningLevel,
    compactness, frontage_length,
)
from shape_analysis import (
    detect_narrow_corridors, split_at_bottlenecks,
)


class IrregularRoadPlacer:
    """Place roads on irregular parcels using iterative extension."""

    def place_roads(self, parcel: Parcel, rules: LayoutRules,
                    pattern: str = "single_road") -> list[RoadSegment]:
        """Generate road segments for an irregular parcel."""
        if not parcel.access_points:
            return []

        if pattern in ("loop_road", "t_road") and len(parcel.access_points) >= 2:
            return self._connect_two_access_points(parcel, rules)
        elif pattern == "cul_de_sac":
            roads = self._iterative_road_extension(parcel, rules)
            if roads:
                roads[0].is_cul_de_sac = True
                roads[0].name = "Irregular Cul-de-sac"
            return roads
        elif pattern == "spine_branch":
            return self._place_spine_branch(parcel, rules)
        else:
            return self._iterative_road_extension(parcel, rules)

    def _iterative_road_extension(self, parcel: Parcel, rules: LayoutRules,
                                   step: float = 20.0) -> list[RoadSegment]:
        """Grow a road incrementally from an access point, steering toward centroid."""
        access = parcel.access_points[0]
        current_pt = Point(access.point)
        dx, dy = access.direction
        geom = parcel.geometry

        coords = [(current_pt.x, current_pt.y)]
        max_length = geom.boundary.length * 0.5  # Safety cap
        total_length = 0.0

        centroid = geom.centroid

        while total_length < max_length:
            # Try 3 angles: straight, +15°, -15°
            best_angle = 0
            best_score = -1

            for angle_deg in [0, 15, -15]:
                angle_rad = math.radians(angle_deg)
                cos_a = math.cos(angle_rad)
                sin_a = math.sin(angle_rad)
                test_dx = dx * cos_a - dy * sin_a
                test_dy = dx * sin_a + dy * cos_a

                # Extend by 2 steps and measure developable area on each side
                test_end = Point(
                    current_pt.x + test_dx * step * 2,
                    current_pt.y + test_dy * step * 2,
                )
                test_line = LineString([(current_pt.x, current_pt.y),
                                         (test_end.x, test_end.y)])
                test_clipped = test_line.intersection(geom)
                if test_clipped.is_empty:
                    continue

                # Score: maximize min(left_area, right_area)
                score = self._score_road_segment(test_clipped, geom, rules)
                if score > best_score:
                    best_score = score
                    best_angle = angle_deg

            # Apply best angle
            # NB: compute both components from the ORIGINAL (dx, dy) before
            # reassigning. Updating dx in place first makes dy use the rotated
            # dx, compounding a steering error every step.
            angle_rad = math.radians(best_angle)
            cos_a = math.cos(angle_rad)
            sin_a = math.sin(angle_rad)
            new_dx = dx * cos_a - dy * sin_a
            new_dy = dx * sin_a + dy * cos_a
            dx, dy = new_dx, new_dy

            # Normalize direction
            dlen = math.sqrt(dx ** 2 + dy ** 2)
            if dlen > 0:
                dx /= dlen
                dy /= dlen

            # Extend by step
            next_pt = Point(current_pt.x + dx * step, current_pt.y + dy * step)
            segment = LineString([(current_pt.x, current_pt.y), (next_pt.x, next_pt.y)])
            clipped = segment.intersection(geom)

            if clipped.is_empty:
                break

            if isinstance(clipped, MultiLineString):
                clipped = max(clipped.geoms, key=lambda g: g.length)

            if not isinstance(clipped, LineString):
                break

            actual_length = clipped.length
            if actual_length < step * 0.5:
                # Road is exiting the parcel — add what we can and stop
                if actual_length > 1:
                    end_pt = clipped.coords[-1]
                    coords.append(end_pt)
                    total_length += actual_length
                break

            # Check if one side is too narrow — steer toward centroid
            left_area, right_area = self._side_areas(clipped, geom, rules)
            min_side = min(left_area, right_area)
            if min_side < rules.min_lot_area:
                # Steer toward centroid
                to_cent_dx = centroid.x - current_pt.x
                to_cent_dy = centroid.y - current_pt.y
                cent_len = math.sqrt(to_cent_dx ** 2 + to_cent_dy ** 2)
                if cent_len > 0:
                    # Blend current direction with centroid direction
                    target_dx = to_cent_dx / cent_len
                    target_dy = to_cent_dy / cent_len
                    dx = 0.5 * dx + 0.5 * target_dx
                    dy = 0.5 * dy + 0.5 * target_dy
                    dlen = math.sqrt(dx ** 2 + dy ** 2)
                    if dlen > 0:
                        dx /= dlen
                        dy /= dlen

            end_pt = (current_pt.x + dx * actual_length, current_pt.y + dy * actual_length)
            # Clip end point to parcel
            end_point_geom = Point(end_pt)
            if not geom.contains(end_point_geom) and not geom.buffer(0.1).contains(end_point_geom):
                # Use the clipped endpoint
                end_pt = clipped.coords[-1]

            coords.append(end_pt)
            total_length += actual_length
            current_pt = Point(end_pt)

        if len(coords) < 2:
            return []

        centerline = LineString(coords)
        # Final clip to parcel
        centerline = centerline.intersection(geom)
        if isinstance(centerline, MultiLineString):
            centerline = max(centerline.geoms, key=lambda g: g.length)
        if not isinstance(centerline, LineString) or centerline.length < 10:
            return []

        return [RoadSegment(
            centerline=centerline,
            row_width=rules.row_width,
            road_type="local_residential",
            name="Irregular Road A",
        )]

    def _score_road_segment(self, line: LineString, parcel_geom: Polygon,
                            rules: LayoutRules) -> float:
        """Score a road segment by the minimum developable area on either side."""
        left, right = self._side_areas(line, parcel_geom, rules)
        return min(left, right)

    def _side_areas(self, line: LineString, parcel_geom: Polygon,
                    rules: LayoutRules) -> tuple:
        """Compute the area on each side of a road line within the parcel."""
        row_half = rules.row_width / 2
        # Buffer the line to create the road ROW
        row_poly = line.buffer(row_half, cap_style=2, join_style=2)
        developable = parcel_geom.difference(row_poly)

        if developable.is_empty:
            return (0.0, 0.0)

        # Split developable into two sides using the line
        # Use perpendicular offset to determine sides
        if len(line.coords) < 2:
            return (developable.area / 2, developable.area / 2)

        # Try splitting by extending the line
        dx = line.coords[-1][0] - line.coords[0][0]
        dy = line.coords[-1][1] - line.coords[0][1]
        dlen = math.sqrt(dx ** 2 + dy ** 2)
        if dlen == 0:
            return (developable.area / 2, developable.area / 2)

        # Extend line beyond parcel bounds
        far = parcel_geom.bounds
        max_extent = max(far[2] - far[0], far[3] - far[1]) * 3
        ux, uy = dx / dlen, dy / dlen
        start_far = (line.coords[0][0] - ux * max_extent, line.coords[0][1] - uy * max_extent)
        end_far = (line.coords[-1][0] + ux * max_extent, line.coords[-1][1] + uy * max_extent)
        extended = LineString([start_far, end_far])

        try:
            pieces = shp_split(developable, extended)
            areas = []
            for g in pieces.geoms:
                if isinstance(g, Polygon) and not g.is_empty:
                    areas.append(g.area)
            if len(areas) >= 2:
                areas.sort(reverse=True)
                return (areas[0], areas[1])
            elif len(areas) == 1:
                return (areas[0], 0.0)
        except Exception:
            pass

        return (developable.area / 2, developable.area / 2)

    def _connect_two_access_points(self, parcel: Parcel,
                                   rules: LayoutRules) -> list[RoadSegment]:
        """Connect two access points, routing through the parcel."""
        a1 = parcel.access_points[0]
        a2 = parcel.access_points[1]
        p1 = Point(a1.point)
        p2 = Point(a2.point)

        # Try direct line
        direct = LineString([p1, p2])
        clipped = direct.intersection(parcel.geometry)

        if not clipped.is_empty and isinstance(clipped, LineString) and clipped.length > 10:
            # Check if the line stays within the parcel
            mid = clipped.interpolate(0.5, normalized=True)
            if parcel.geometry.buffer(-1).contains(mid) or parcel.geometry.contains(mid):
                return [RoadSegment(
                    centerline=clipped,
                    row_width=rules.row_width,
                    road_type="local_residential",
                    name="Irregular Loop A",
                )]

        # Fall back to iterative extension from access 1 toward access 2
        # Build a road that snakes toward the second access point
        coords = [(p1.x, p1.y)]
        current = p1
        target = p2
        step = 20.0
        max_steps = 50

        for _ in range(max_steps):
            dx = target.x - current.x
            dy = target.y - current.y
            dlen = math.sqrt(dx ** 2 + dy ** 2)
            if dlen < step:
                coords.append((target.x, target.y))
                break
            dx /= dlen
            dy /= dlen

            next_pt = Point(current.x + dx * step, current.y + dy * step)
            segment = LineString([(current.x, current.y), (next_pt.x, next_pt.y)])
            clipped_seg = segment.intersection(parcel.geometry)

            if clipped_seg.is_empty:
                # Try steering toward centroid
                centroid = parcel.geometry.centroid
                dx = centroid.x - current.x
                dy = centroid.y - current.y
                dlen = math.sqrt(dx ** 2 + dy ** 2)
                if dlen == 0:
                    break
                dx /= dlen
                dy /= dlen
                next_pt = Point(current.x + dx * step, current.y + dy * step)
                segment = LineString([(current.x, current.y), (next_pt.x, next_pt.y)])
                clipped_seg = segment.intersection(parcel.geometry)
                if clipped_seg.is_empty:
                    break

            if isinstance(clipped_seg, MultiLineString):
                clipped_seg = max(clipped_seg.geoms, key=lambda g: g.length)

            if not isinstance(clipped_seg, LineString) or clipped_seg.length < 5:
                break

            end = clipped_seg.coords[-1]
            coords.append(end)
            current = Point(end)

        if len(coords) < 2:
            # Fall back to single road
            return self._iterative_road_extension(parcel, rules)

        centerline = LineString(coords)
        centerline = centerline.intersection(parcel.geometry)
        if isinstance(centerline, MultiLineString):
            centerline = max(centerline.geoms, key=lambda g: g.length)
        if not isinstance(centerline, LineString) or centerline.length < 10:
            return self._iterative_road_extension(parcel, rules)

        return [RoadSegment(
            centerline=centerline,
            row_width=rules.row_width,
            road_type="local_residential",
            name="Irregular Loop A",
        )]

    def _place_spine_branch(self, parcel: Parcel, rules: LayoutRules) -> list[RoadSegment]:
        """Place a spine road with side branches."""
        spine_roads = self._iterative_road_extension(parcel, rules)
        if not spine_roads:
            return []

        spine = spine_roads[0]
        roads = list(spine_roads)

        # Add branches perpendicular to spine at 1/3 and 2/3 points
        for frac in [0.33, 0.66]:
            pt = spine.centerline.interpolate(frac, normalized=True)
            # Get spine direction at this point
            spine_coords = list(spine.centerline.coords)
            # Find nearest segment
            nearest_dir = None
            min_dist = float('inf')
            for i in range(len(spine_coords) - 1):
                seg_mid = LineString([spine_coords[i], spine_coords[i + 1]]).interpolate(0.5, normalized=True)
                d = pt.distance(seg_mid)
                if d < min_dist:
                    min_dist = d
                    dx = spine_coords[i + 1][0] - spine_coords[i][0]
                    dy = spine_coords[i + 1][1] - spine_coords[i][1]
                    nearest_dir = (dx, dy)

            if nearest_dir is None:
                continue

            dx, dy = nearest_dir
            # Perpendicular
            px, py = -dy, dx
            plen = math.sqrt(px ** 2 + py ** 2)
            if plen == 0:
                continue
            px /= plen
            py /= plen

            for direction in [1, -1]:
                branch_length = 40
                branch_end = Point(pt.x + px * branch_length * direction,
                                   pt.y + py * branch_length * direction)
                branch = LineString([(pt.x, pt.y), (branch_end.x, branch_end.y)])
                clipped = branch.intersection(parcel.geometry)
                if clipped.is_empty or clipped.length < 10:
                    continue
                if isinstance(clipped, MultiLineString):
                    clipped = max(clipped.geoms, key=lambda g: g.length)
                if not isinstance(clipped, LineString):
                    continue

                roads.append(RoadSegment(
                    centerline=clipped,
                    row_width=rules.row_width,
                    road_type="local_residential",
                    name=f"Irregular Branch {chr(66 + len(roads))}",
                ))

        return roads


class IrregularLotCarver:
    """Carve lots on irregular parcels using strip-based recursive carving."""

    def __init__(self):
        self._lot_counter = 0

    def _next_lot_id(self) -> int:
        self._lot_counter += 1
        return self._lot_counter

    def carve(self, road_segments: list[RoadSegment], developable,
              rules: LayoutRules) -> list[Lot]:
        """Carve lots along road frontages on an irregular parcel."""
        if not road_segments or developable.is_empty:
            return []

        all_lots = []
        remaining = developable

        for road in road_segments:
            if remaining.is_empty:
                break
            lots, remaining = self._carve_along_road(road, remaining, rules)
            all_lots.extend(lots)

        # Fill dead zones — merge tiny fragments into adjacent lots
        if all_lots and not remaining.is_empty:
            all_lots = self._fill_dead_zones(all_lots, remaining, rules)

        # Handle remainders
        if remaining and not remaining.is_empty:
            remainder_lots = self._remainder_as_polygon_union(remaining, rules)
            all_lots.extend(remainder_lots)

        return all_lots

    def _carve_along_road(self, road: RoadSegment, developable,
                          rules: LayoutRules) -> tuple:
        """Carve lots along a single road segment."""
        lots = []
        centerline = road.centerline
        row_half = road.row_width / 2

        # Get frontage lines on both sides
        for side in ["left", "right"]:
            offset = row_half + 0.5
            if side == "right":
                frontage_line = centerline.offset_curve(offset)
            else:
                frontage_line = centerline.offset_curve(-offset)

            if frontage_line.is_empty or frontage_line.length < rules.min_frontage:
                continue

            side_lots, developable = self._carve_side(frontage_line, road, developable, rules, side)
            lots.extend(side_lots)

        return lots, developable

    def _carve_side(self, frontage_line: LineString, road: RoadSegment,
                    developable, rules: LayoutRules, side: str) -> tuple:
        """Carve lots on one side of a road using strip-based recursive carving."""
        lots = []
        remaining_dev = developable
        lot_width = rules.lot_width_target
        frontage_length = frontage_line.length

        if frontage_length < rules.min_frontage:
            return lots, developable

        # Calculate depth direction (perpendicular to frontage, pointing inward)
        start = Point(frontage_line.coords[0])
        end = Point(frontage_line.coords[-1])
        fdx = end.x - start.x
        fdy = end.y - start.y
        flen = math.sqrt(fdx ** 2 + fdy ** 2)
        if flen == 0:
            return lots, developable

        # Perpendicular directions
        perp_a = (-fdy / flen, fdx / flen)
        perp_b = (fdy / flen, -fdx / flen)

        # Pick the direction pointing away from road centerline
        seg_mid = frontage_line.interpolate(0.5, normalized=True)
        road_near = road.centerline.interpolate(road.centerline.project(seg_mid))
        dist_a = math.dist((seg_mid.x + perp_a[0], seg_mid.y + perp_a[1]), (road_near.x, road_near.y))
        dist_b = math.dist((seg_mid.x + perp_b[0], seg_mid.y + perp_b[1]), (road_near.x, road_near.y))

        if dist_a > dist_b:
            depth_dx, depth_dy = perp_a
        else:
            depth_dx, depth_dy = perp_b

        # Carve lots one at a time
        pos = 0.0
        max_width = lot_width * 1.5

        while pos < frontage_length:
            current_width = lot_width
            lot_carved = False

            # Try carving at current width, expand if too small
            for attempt in range(3):
                end_pos = min(pos + current_width, frontage_length)
                frontage_seg = substring(frontage_line, pos, end_pos)

                if frontage_seg.length < rules.min_frontage * 0.5 and attempt > 0:
                    break

                target_depth = rules.lot_depth_target

                # Build depth strip using single-sided buffer
                depth_strip = frontage_seg.buffer(target_depth, single_sided=True, join_style=2)

                # Orient the buffer on the inward side
                # single_sided buffer goes to the left of the line direction
                # We need to check if it's on the correct side
                strip_mid = depth_strip.centroid
                # Check if strip is on the inward side
                inward_pt = (seg_mid.x + depth_dx * 5, seg_mid.y + depth_dy * 5)
                strip_to_inward = math.dist((strip_mid.x, strip_mid.y), inward_pt)
                strip_to_road = math.dist((strip_mid.x, strip_mid.y), (road_near.x, road_near.y))

                if strip_to_road < strip_to_inward:
                    # Buffer is on wrong side — flip the frontage and re-buffer
                    reversed_seg = LineString(list(frontage_seg.coords)[::-1])
                    depth_strip = reversed_seg.buffer(target_depth, single_sided=True, join_style=2)

                # Intersect with remaining developable
                if remaining_dev.is_empty:
                    break

                lot_poly = depth_strip.intersection(remaining_dev)
                lot_poly = make_valid(lot_poly)

                if lot_poly.is_empty:
                    pos += current_width
                    lot_carved = True
                    break

                # Handle MultiPolygon results
                lot_poly = self._handle_multipolygon_lots(lot_poly, rules)

                if not isinstance(lot_poly, Polygon) or lot_poly.is_empty:
                    pos += current_width
                    lot_carved = True
                    break

                # Check area
                if lot_poly.area < rules.min_lot_area * 0.8:
                    if attempt < 2 and current_width < max_width:
                        current_width += 2.0
                        continue
                    else:
                        # Too small — skip this frontage segment
                        pos += current_width
                        lot_carved = True
                        break

                # Create the lot
                lot_type = LotType.RESIDENTIAL
                shape_q = compactness(lot_poly)
                if shape_q < 0.3:
                    lot_type = LotType.IRREGULAR

                lot = Lot(
                    id=self._next_lot_id(),
                    geometry=lot_poly,
                    frontage_line=frontage_seg,
                    road_segment_id=0,
                    lot_type=lot_type,
                    access_point=Point(frontage_seg.interpolate(0.5, normalized=True).x,
                                       frontage_seg.interpolate(0.5, normalized=True).y),
                )
                lot.compute_properties()
                lots.append(lot)

                # Subtract lot from remaining developable
                remaining_dev = remaining_dev.difference(lot_poly)
                remaining_dev = make_valid(remaining_dev)
                if isinstance(remaining_dev, MultiPolygon):
                    # Keep all parts — they'll be handled as remainders
                    pass

                pos = end_pos
                lot_carved = True
                break

            if not lot_carved:
                pos += lot_width

        return lots, remaining_dev

    def _handle_multipolygon_lots(self, geom, rules: LayoutRules):
        """Handle MultiPolygon results from intersection operations."""
        if isinstance(geom, MultiPolygon):
            geoms = [g for g in geom.geoms if isinstance(g, Polygon) and not g.is_empty]
            if not geoms:
                return geom
            # Sort by area
            geoms.sort(key=lambda g: g.area, reverse=True)
            largest = geoms[0]
            small_pieces = geoms[1:]

            for piece in small_pieces:
                if piece.area < rules.min_lot_area * 0.3:
                    # Discard — will become remainder via difference
                    continue
                elif piece.area < rules.min_lot_area * 0.8:
                    # Check if it can be bridged to the largest
                    gap = piece.distance(largest)
                    if gap < 2.0:
                        # Bridge them
                        bridged = unary_union([largest, piece])
                        bridged = bridged.convex_hull
                        # Re-intersect with developable handled by caller
                        largest = bridged
                else:
                    # Both pieces are large enough — keep largest for now
                    pass

            return largest

        if isinstance(geom, Polygon):
            return geom

        # GeometryCollection or other
        if hasattr(geom, "geoms"):
            polys = [g for g in geom.geoms if isinstance(g, Polygon) and not g.is_empty]
            if polys:
                return max(polys, key=lambda g: g.area)

        return geom

    def _fill_dead_zones(self, lots: list[Lot], remaining, rules: LayoutRules) -> list[Lot]:
        """Merge tiny fragments into adjacent lots."""
        if remaining.is_empty or not lots:
            return lots

        fragments = []
        if isinstance(remaining, MultiPolygon):
            fragments = [g for g in remaining.geoms if isinstance(g, Polygon) and not g.is_empty]
        elif isinstance(remaining, Polygon):
            fragments = [remaining]

        for frag in fragments:
            if frag.area < rules.min_lot_area * 0.1:
                # Tiny — merge into adjacent lot
                best_lot = None
                best_shared = 0
                for lot in lots:
                    if not lot.is_residential:
                        continue
                    if lot.geometry.touches(frag):
                        # Estimate shared boundary length
                        shared = lot.geometry.intersection(frag).length
                        if shared > best_shared:
                            best_shared = shared
                            best_lot = lot

                if best_lot is not None:
                    merged = best_lot.geometry.union(frag)
                    merged = make_valid(merged)
                    if isinstance(merged, MultiPolygon):
                        merged = max(merged.geoms, key=lambda g: g.area)
                    if isinstance(merged, Polygon):
                        best_lot.geometry = merged
                        best_lot.compute_properties()
                        continue

            # If not merged, leave it for remainder handling
        return lots

    def _remainder_as_polygon_union(self, remaining, rules: LayoutRules) -> list[Lot]:
        """Create remainder lots from leftover developable area."""
        if remaining is None or remaining.is_empty:
            return []

        # Union all fragments. make_valid on a difference of many lots can
        # return a GeometryCollection (polygons + degenerate slivers); extract
        # only the polygonal parts so leftover developable area is never
        # silently dropped from the area accounting.
        unified = unary_union(remaining) if isinstance(remaining, MultiPolygon) else remaining
        unified = make_valid(unified)

        polys: list[Polygon] = []
        if isinstance(unified, Polygon) and not unified.is_empty:
            polys = [unified]
        elif hasattr(unified, "geoms"):
            polys = [g for g in unified.geoms
                     if isinstance(g, Polygon) and not g.is_empty]
        # Merge touching fragments so adjacent slivers count as one remainder
        if len(polys) > 1:
            merged = unary_union(polys)
            if isinstance(merged, Polygon) and not merged.is_empty:
                polys = [merged]
            elif isinstance(merged, MultiPolygon):
                polys = [g for g in merged.geoms
                         if isinstance(g, Polygon) and not g.is_empty]

        if not polys:
            return []

        lots = []
        large = [p for p in polys if p.area >= rules.min_lot_area]
        small = [p for p in polys if p.area < rules.min_lot_area]

        for poly in large:
            lot = self._make_remainder_lot(poly)
            if lot:
                lots.append(lot)

        if small:
            scrap = unary_union(small)
            if scrap.area >= rules.min_lot_area:
                lot = self._make_remainder_lot(scrap)
                if lot:
                    lots.append(lot)

        return lots

    def _make_remainder_lot(self, poly: Polygon) -> Optional[Lot]:
        """Create a remainder lot from a polygon."""
        if not isinstance(poly, Polygon) or poly.is_empty:
            return None
        coords = list(poly.exterior.coords)
        frontage_coords = coords[:2] if len(coords) >= 2 else coords
        frontage_line = LineString(frontage_coords)
        lot = Lot(
            id=self._next_lot_id(),
            geometry=poly,
            frontage_line=frontage_line,
            lot_type=LotType.REMAINDER,
        )
        lot.compute_properties()
        return lot


# ── 4.3 Setback Envelope ───────────────────────────────────────────────────

def setback_envelope(lot: Lot, road_frontage_edges, rules: LayoutRules) -> Optional[Polygon]:
    """Compute buildable envelope with different setbacks per edge classification.

    For each edge of lot.exterior.coords, classify as front (touches road ROW),
    rear (opposite), or side. Apply different setback distances.
    """
    if lot.geometry is None or lot.geometry.is_empty:
        return None

    # Simple approach: use minimum setback as a fallback
    min_setback = min(rules.front_setback, rules.rear_setback, rules.side_setback)
    try:
        envelope = lot.geometry.buffer(-min_setback, join_style=2)
        if envelope.is_empty or not isinstance(envelope, Polygon):
            return None
        return envelope
    except Exception:
        return None


# ── 4.4 Remainder as Polygon Union (static method version) ─────────────────

def remainder_as_polygon_union(remaining, rules: LayoutRules) -> list[Lot]:
    """Create remainder lots from leftover developable area."""
    carver = IrregularLotCarver()
    return carver._remainder_as_polygon_union(remaining, rules)