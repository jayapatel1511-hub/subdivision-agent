"""
Subdivision Agent — Shape Analysis.

Classifies parcel shapes and provides utilities for detecting corridors,
bottlenecks, and decomposing irregular parcels.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Optional

import numpy as np
from shapely.geometry import (
    Polygon, MultiPolygon, LineString, Point, MultiLineString,
)
from shapely.ops import split as shp_split, unary_union
from shapely import make_valid

# Re-use the ParcelShape defined in models to avoid circular imports
from models import ParcelShape


# ── 2.1 (enum lives in models.py) ──────────────────────────────────────────


# ── 2.2 Detect Parcel Shape ────────────────────────────────────────────────

def detect_parcel_shape(poly, min_width: float = 15.0) -> ParcelShape:
    """Classify a parcel polygon into a ParcelShape category."""
    if isinstance(poly, MultiPolygon):
        return ParcelShape.MULTI_PART

    if not isinstance(poly, Polygon) or poly.is_empty:
        return ParcelShape.RECTANGLE

    convex_ratio = poly.convex_hull.area / poly.area if poly.area > 0 else 1.0

    # Check for narrow corridors first (they take priority)
    corridors = detect_narrow_corridors(poly, min_width)
    if corridors and _corridor_dominates(poly, corridors, min_width):
        return ParcelShape.CORRIDOR

    if convex_ratio < 1.05:
        # CONVEX or RECTANGLE
        if is_rectangleish(poly):
            return ParcelShape.RECTANGLE
        return ParcelShape.CONVEX
    elif convex_ratio <= 1.3:
        return ParcelShape.CONCAVE
    else:
        # > 1.3 — likely L-shape or corridor
        # Check for bottleneck pattern characteristic of L-shapes
        bottlenecks = _find_bottlenecks(poly)
        if len(bottlenecks) >= 2 or (len(bottlenecks) >= 1 and convex_ratio > 1.3):
            return ParcelShape.L_SHAPE
        return ParcelShape.CONCAVE


def _corridor_dominates(poly: Polygon, corridors: list, min_width: float) -> bool:
    """Check if corridors occupy a significant portion of the polygon."""
    if not corridors:
        return False
    total_corridor_len = sum(c.length for c in corridors)
    # If corridor centerlines are long relative to parcel size, it's a corridor shape
    bounds = poly.bounds
    max_dim = max(bounds[2] - bounds[0], bounds[3] - bounds[1])
    if max_dim == 0:
        return False
    return total_corridor_len / max_dim > 0.3


# ── 2.3 Detect Narrow Corridors ────────────────────────────────────────────

def detect_narrow_corridors(poly: Polygon, min_width: float = 15.0) -> list:
    """Find narrow corridors in the polygon using a medial-axis approximation.

    Uses scipy Voronoi on boundary vertices, filters edges inside polygon,
    computes local width, and returns corridor centerlines where width < min_width.
    """
    from scipy.spatial import Voronoi

    if not isinstance(poly, Polygon) or poly.is_empty:
        return []

    # Sample boundary points
    boundary = poly.boundary
    n_samples = min(200, max(20, int(boundary.length / 5)))
    boundary_pts = []
    for i in range(n_samples):
        pt = boundary.interpolate(i / n_samples, normalized=True)
        boundary_pts.append([pt.x, pt.y])

    boundary_arr = np.array(boundary_pts)
    if len(boundary_arr) < 4:
        return []

    try:
        vor = Voronoi(boundary_arr)
    except Exception:
        return []

    # Collect Voronoi edges inside the polygon
    interior_edges = []
    for ridge in vor.ridge_vertices:
        if -1 in ridge:
            continue  # infinite ridge
        v0, v1 = ridge
        if v0 < 0 or v1 < 0:
            continue
        p0 = vor.vertices[v0]
        p1 = vor.vertices[v1]
        seg = LineString([(p0[0], p0[1]), (p1[0], p1[1])])
        # Check if edge midpoint is inside polygon (with small tolerance)
        mid = seg.interpolate(0.5, normalized=True)
        if poly.buffer(0.01).contains(mid):
            interior_edges.append(seg)

    if not interior_edges:
        return []

    # For each interior edge, compute local width
    corridors = []
    for seg in interior_edges:
        # Distance from edge endpoints to boundary
        d_start = poly.boundary.distance(Point(seg.coords[0]))
        d_end = poly.boundary.distance(Point(seg.coords[-1]))
        local_width = 2 * min(d_start, d_end)
        if local_width < min_width and local_width > 0:
            corridors.append(seg)

    # Merge adjacent corridor segments
    if corridors:
        merged = _merge_corridor_segments(corridors)
        return merged

    return corridors


def _merge_corridor_segments(segments: list, tolerance: float = 1.0) -> list:
    """Merge corridor segments that are close to each other into longer lines."""
    if len(segments) <= 1:
        return segments

    merged = []
    used = set()

    for i, seg in enumerate(segments):
        if i in used:
            continue
        coords = list(seg.coords)
        for j in range(i + 1, len(segments)):
            if j in used:
                continue
            other = segments[j]
            other_coords = list(other.coords)
            # Check if endpoints are close
            end = coords[-1]
            start = other_coords[0]
            if math.dist(end, start) < tolerance:
                coords.extend(other_coords[1:])
                used.add(j)
            else:
                start2 = other_coords[-1]
                if math.dist(coords[0], start2) < tolerance:
                    coords = other_coords[:-1] + coords
                    used.add(j)
        merged.append(LineString(coords))

    return merged


# ── 2.4 Split at Bottlenecks ───────────────────────────────────────────────

def split_at_bottlenecks(poly: Polygon) -> list:
    """Decompose a polygon at bottleneck cross-sections.

    Finds the shortest cross-section that splits the polygon and recursively
    splits sub-polygons if they're still non-convex enough.
    """
    if not isinstance(poly, Polygon) or poly.is_empty:
        return [poly] if isinstance(poly, Polygon) else []

    convex_ratio = poly.convex_hull.area / poly.area if poly.area > 0 else 1.0
    if convex_ratio <= 1.3:
        return [poly]

    bottleneck_line = _find_bottleneck_line(poly)
    if bottleneck_line is None:
        return [poly]

    try:
        pieces = shp_split(poly, bottleneck_line)
        result = []
        for piece in pieces.geoms:
            if isinstance(piece, Polygon) and not piece.is_empty:
                # Recursively split
                sub_pieces = split_at_bottlenecks(piece)
                result.extend(sub_pieces)
        return result if result else [poly]
    except Exception:
        return [poly]


def _find_bottlenecks(poly: Polygon) -> list:
    """Find potential bottleneck cross-sections."""
    if not isinstance(poly, Polygon) or poly.is_empty:
        return []
    # Sample cross-sections at boundary vertices
    coords = list(poly.exterior.coords)
    bottlenecks = []
    centroid = poly.centroid

    for i in range(len(coords) - 1):
        vertex = coords[i]
        # Cast a line from this vertex toward the centroid, extended
        dx = centroid.x - vertex[0]
        dy = centroid.y - vertex[1]
        dlen = math.sqrt(dx ** 2 + dy ** 2)
        if dlen == 0:
            continue
        dx /= dlen
        dy /= dlen

        # Extend the line well beyond the polygon
        far_point = (vertex[0] + dx * poly.boundary.length * 2,
                     vertex[1] + dy * poly.boundary.length * 2)
        test_line = LineString([vertex, far_point])
        clipped = test_line.intersection(poly.boundary)
        if clipped.is_empty:
            continue
        # Measure the cross-section length
        if isinstance(clipped, MultiLineString):
            # Find the closest intersection point on the other side
            for seg in clipped.geoms:
                far_pt = seg.coords[-1]
                cross = LineString([vertex, far_pt])
                if poly.contains(cross.interpolate(0.5, normalized=True)):
                    bottlenecks.append(cross)
                    break
        elif isinstance(clipped, Point):
            # Vertex is on boundary, the other intersection is a point
            pass
        else:
            # Single point intersection
            pass

    # Sort by length, short ones are bottlenecks
    bottlenecks.sort(key=lambda l: l.length)
    # Return short cross-sections (bottlenecks)
    if bottlenecks:
        avg_len = sum(b.length for b in bottlenecks) / len(bottlenecks)
        return [b for b in bottlenecks if b.length < avg_len * 0.5]
    return []


def _find_bottleneck_line(poly: Polygon) -> Optional[LineString]:
    """Find the shortest cross-section that splits the polygon."""
    bottlenecks = _find_bottlenecks(poly)
    if not bottlenecks:
        return None
    return bottlenecks[0]


# ── 2.5 Is Rectangleish ────────────────────────────────────────────────────

def is_rectangleish(poly: Polygon) -> bool:
    """Check if a polygon is approximately a rectangle.

    Checks:
    1. All interior angles close to 90° (within 5°)
    2. Minimum rotated rectangle area ≈ polygon area (within 2%)
    """
    if not isinstance(poly, Polygon) or poly.is_empty:
        return False

    # Check minimum rotated rectangle area ratio
    mrr = poly.minimum_rotated_rectangle
    if poly.area <= 0:
        return False
    ratio = poly.area / mrr.area
    if ratio < 0.98:
        return False

    # Check interior angles
    coords = list(poly.exterior.coords)
    if len(coords) < 5:  # Need at least 4 vertices + closing
        return False

    n = len(coords) - 1  # exclude closing duplicate
    if n != 4:
        return False  # Rectangle should have exactly 4 vertices

    for i in range(n):
        p0 = coords[i]
        p1 = coords[(i + 1) % n]
        p2 = coords[(i + 2) % n]
        # Vectors at vertex p1
        v1x = p0[0] - p1[0]
        v1y = p0[1] - p1[1]
        v2x = p2[0] - p1[0]
        v2y = p2[1] - p1[1]
        # Angle between v1 and v2
        dot = v1x * v2x + v1y * v2y
        mag1 = math.sqrt(v1x ** 2 + v1y ** 2)
        mag2 = math.sqrt(v2x ** 2 + v2y ** 2)
        if mag1 == 0 or mag2 == 0:
            return False
        cos_angle = dot / (mag1 * mag2)
        cos_angle = max(-1, min(1, cos_angle))
        angle = math.degrees(math.acos(cos_angle))
        # Interior angle is 180 - angle for exterior measurement
        interior = 180 - angle if angle < 180 else angle
        # For a rectangle, interior angle should be ~90°
        if abs(interior - 90) > 5:
            return False

    return True