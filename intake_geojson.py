"""
Subdivision Agent — GeoJSON Intake Pipeline.

Loads parcel geometry from GeoJSON, reprojectes to a working CRS,
cleans topology, parses access points, and validates integrity.
"""

from __future__ import annotations

import json
import math
import warnings as _warnings
from pathlib import Path
from typing import Optional

from shapely.geometry import (
    Polygon, MultiPolygon, LineString, Point, MultiLineString, mapping, shape as shp_shape,
)
from shapely.ops import unary_union, transform as shp_transform
from shapely.geometry.polygon import orient as shp_orient
from shapely import make_valid, simplify as shp_simplify
import pyproj

from models import Parcel, AccessPoint, ConstraintArea, LayoutRules


# ── 1.1 Load GeoJSON ───────────────────────────────────────────────────────

def load_geojson_parcel(path: str, rules: Optional[LayoutRules] = None) -> Parcel:
    """Load a parcel from a GeoJSON file.

    Accepts FeatureCollection or single Feature. Geometry must be Polygon
    or MultiPolygon. Required properties: zone_code, servicing_type.
    Optional: pid, municipality, access_points.
    """
    raw = json.loads(Path(path).read_text())

    # Normalize to a features list
    if raw.get("type") == "FeatureCollection":
        features = raw.get("features", [])
    elif raw.get("type") == "Feature":
        features = [raw]
    else:
        raise ValueError("GeoJSON must be a Feature or FeatureCollection")

    if not features:
        raise ValueError("No features found in GeoJSON")

    # Determine CRS from GeoJSON crs field (2016 spec) or default 4326
    source_crs = 4326
    crs_field = raw.get("crs")
    if crs_field and crs_field.get("type") == "name":
        name = crs_field.get("properties", {}).get("name", "")
        # Parse "urn:ogc:def:crs:EPSG::2961" or "EPSG:2961"
        if "2961" in name:
            source_crs = 2961
        elif "2959" in name:
            source_crs = 2959
        elif "4326" in name:
            source_crs = 4326

    # Separate parcel geometry, access points, and constraints
    parcel_feature = None
    access_features = []
    constraint_features = []

    for feat in features:
        props = feat.get("properties", {}) or {}
        geom_type = feat.get("geometry", {}).get("type", "")
        if "access" in props.get("feature_type", "").lower() or geom_type == "Point" and "direction" in props:
            access_features.append(feat)
        elif "constraint" in props.get("feature_type", "").lower() or "constraint_type" in props:
            constraint_features.append(feat)
        elif geom_type in ("Polygon", "MultiPolygon"):
            if parcel_feature is None:
                parcel_feature = feat
        elif geom_type in ("Point", "LineString") and not access_features:
            # Might be an access feature
            access_features.append(feat)

    if parcel_feature is None:
        raise ValueError("No Polygon/MultiPolygon feature found for parcel")

    props = parcel_feature.get("properties", {}) or {}

    # Validate required properties
    required = ["zone_code", "servicing_type"]
    for key in required:
        if key not in props:
            raise ValueError(f"Missing required property: {key}")

    # Build geometry
    geom = shp_shape(parcel_feature["geometry"])
    if geom.is_empty:
        raise ValueError("Parcel geometry is empty")

    # If MultiPolygon, union and take largest
    if isinstance(geom, MultiPolygon):
        unioned = unary_union(list(geom.geoms))
        if isinstance(unioned, MultiPolygon):
            # Keep largest component
            largest = max(unioned.geoms, key=lambda g: g.area)
            _warnings.warn(f"MultiPolygon parcel: kept largest component ({largest.area:.0f} m²)")
            geom = largest
        else:
            geom = unioned

    # Reproject BEFORE cleaning: clean_polygon's simplify tolerance is in
    # metres, so the geometry must be in a projected CRS first. Geographic
    # input (4326) goes to NAD83(CSRS) / UTM zone 20N; input already in a
    # projected CRS is kept as-is.
    if source_crs == 4326:
        target_crs = 2961  # NAD83(CSRS) / UTM zone 20N (Nova Scotia)
        geom = to_projected(geom, source_crs, target_crs)
    else:
        target_crs = source_crs

    # Clean and orient (in projected metres)
    geom = clean_polygon(geom)
    geom = force_ccw_exterior(geom)

    # Build parcel
    pid = props.get("pid", "")
    municipality = props.get("municipality", "hrm")

    parcel = Parcel(
        geometry=geom,
        pid=pid,
        zone_code=props["zone_code"],
        municipality=municipality,
        source_crs=source_crs,
        working_crs=target_crs,
    )

    # Parse access points
    access_points = parse_access_points(access_features, parcel)
    parcel.access_points = access_points

    # Parse constraints
    for cf in constraint_features:
        ca = _load_constraint_feature(cf, parcel)
        if ca is not None:
            parcel.constraint_areas.append(ca)

    return parcel


def _load_constraint_feature(feat: dict, parcel: Parcel) -> Optional[ConstraintArea]:
    """Load a constraint area from a GeoJSON feature."""
    props = feat.get("properties", {}) or {}
    geom = shp_shape(feat["geometry"])
    if geom.is_empty:
        return None
    # Reproject if needed (same as parcel)
    if parcel.source_crs != parcel.working_crs:
        geom = to_projected(geom, parcel.source_crs, parcel.working_crs)
    # Clip to parcel
    geom = geom.intersection(parcel.geometry)
    if geom.is_empty:
        return None
    name = props.get("name", props.get("constraint_type", "Constraint"))
    buffer_m = float(props.get("buffer_m", 0.0))
    deductible = props.get("deductible", True)
    source = props.get("regulation_source", "")
    return ConstraintArea(name=name, geometry=geom, deductible=deductible,
                          buffer_m=buffer_m, source=source)


# ── 1.2 CRS Transform ──────────────────────────────────────────────────────

def to_projected(geom, source_crs: int, target_crs: int):
    """Reproject a Shapely geometry from source_crs to target_crs."""
    if source_crs == target_crs:
        return geom
    transformer = pyproj.Transformer.from_crs(
        f"EPSG:{source_crs}", f"EPSG:{target_crs}", always_xy=True
    )
    return shp_transform(transformer.transform, geom)


# ── 1.3 Clean Polygon ──────────────────────────────────────────────────────

def clean_polygon(poly) -> Polygon:
    """Fix topology, simplify, remove zero-length edges."""
    # make_valid
    poly = make_valid(poly)
    if isinstance(poly, MultiPolygon):
        poly = max(poly.geoms, key=lambda g: g.area)
    elif hasattr(poly, "geoms"):
        # GeometryCollection — filter to Polygon parts
        polys = [g for g in poly.geoms if isinstance(g, Polygon)]
        if not polys:
            raise ValueError("No polygon geometry found after make_valid")
        poly = unary_union(polys)
        if isinstance(poly, MultiPolygon):
            poly = max(poly.geoms, key=lambda g: g.area)

    if not isinstance(poly, Polygon):
        raise ValueError(f"clean_polygon: expected Polygon, got {type(poly).__name__}")

    if not poly.is_valid:
        _warnings.warn(f"Polygon invalid after make_valid: {poly.wkt[:200]}")

    # Simplify with topology preservation
    simplified = shp_simplify(poly, tolerance=0.5, preserve_topology=True)
    if not simplified.is_valid:
        simplified = make_valid(simplified)
        if isinstance(simplified, MultiPolygon):
            simplified = max(simplified.geoms, key=lambda g: g.area)
    poly = simplified

    # Remove zero-length edges (consecutive duplicate coords)
    coords = list(poly.exterior.coords)
    cleaned = []
    for i, c in enumerate(coords):
        if i > 0:
            dx = c[0] - cleaned[-1][0]
            dy = c[1] - cleaned[-1][1]
            if math.sqrt(dx * dx + dy * dy) < 1e-6:
                continue
        cleaned.append(c)
    # Ensure closed
    if cleaned[0] != cleaned[-1]:
        cleaned.append(cleaned[0])

    # Handle interiors (holes)
    interiors = []
    for ring in poly.interiors:
        ring_coords = list(ring.coords)
        ring_cleaned = []
        for i, c in enumerate(ring_coords):
            if i > 0:
                dx = c[0] - ring_cleaned[-1][0]
                dy = c[1] - ring_cleaned[-1][1]
                if math.sqrt(dx * dx + dy * dy) < 1e-6:
                    continue
            ring_cleaned.append(c)
        if ring_cleaned[0] != ring_cleaned[-1]:
            ring_cleaned.append(ring_cleaned[0])
        interiors.append(ring_cleaned)

    poly = Polygon(cleaned, interiors)

    if not poly.is_valid:
        _warnings.warn(f"Polygon invalid after cleaning: {poly.wkt[:200]}")
        poly = make_valid(poly)
        if isinstance(poly, MultiPolygon):
            poly = max(poly.geoms, key=lambda g: g.area)

    return poly


# ── 1.4 Force CCW Exterior ─────────────────────────────────────────────────

def force_ccw_exterior(poly: Polygon) -> Polygon:
    """Force exterior ring to CCW orientation, interiors to CW."""
    return shp_orient(poly, sign=1.0)


# ── 1.5 Parse Access Points ────────────────────────────────────────────────

def parse_access_points(features: list, parcel: Parcel) -> list[AccessPoint]:
    """Parse access point features from GeoJSON, or derive from boundary."""
    access_points = []

    for feat in features:
        geom = shp_shape(feat["geometry"])
        props = feat.get("properties", {}) or {}

        # Reproject if needed
        if parcel.source_crs != parcel.working_crs:
            geom = to_projected(geom, parcel.source_crs, parcel.working_crs)

        if isinstance(geom, Point):
            pt = (geom.x, geom.y)
            direction = tuple(props.get("direction", (1, 0)))
            # Normalize direction
            dlen = math.sqrt(direction[0] ** 2 + direction[1] ** 2)
            if dlen > 0:
                direction = (direction[0] / dlen, direction[1] / dlen)
            else:
                direction = (1, 0)
            ap = AccessPoint(point=pt, direction=direction, source="geojson")
            access_points.append(ap)

        elif isinstance(geom, LineString):
            coords = list(geom.coords)
            if len(coords) < 2:
                continue
            first = coords[0]
            last = coords[-1]
            dx = last[0] - first[0]
            dy = last[1] - first[1]
            dlen = math.sqrt(dx * dx + dy * dy)
            if dlen > 0:
                direction = (dx / dlen, dy / dlen)
            else:
                direction = (1, 0)
            ap = AccessPoint(point=(first[0], first[1]), direction=direction, source="geojson")
            access_points.append(ap)

    # Fallback: derive from longest boundary edge facing centroid
    if not access_points:
        ap = _derive_access_point(parcel)
        if ap is not None:
            access_points.append(ap)

    # Snap each access point to parcel boundary
    boundary = parcel.geometry.boundary
    snapped = []
    for ap in access_points:
        pt = Point(ap.point)
        proj_dist = boundary.project(pt)
        snapped_pt = boundary.interpolate(proj_dist)
        dist_m = pt.distance(snapped_pt)
        if dist_m > 5:
            _warnings.warn(f"Access point snapped {dist_m:.1f}m from original position")
        snapped.append(AccessPoint(
            point=(snapped_pt.x, snapped_pt.y),
            direction=ap.direction,
            road_name=ap.road_name,
            source=ap.source,
        ))

    return snapped


def _derive_access_point(parcel: Parcel) -> Optional[AccessPoint]:
    """Derive an access point from the longest boundary edge facing the centroid."""
    coords = list(parcel.geometry.exterior.coords)
    centroid = parcel.geometry.centroid
    best_seg = None
    best_score = -1

    for i in range(len(coords) - 1):
        seg = LineString([coords[i], coords[i + 1]])
        mid = seg.interpolate(0.5, normalized=True)
        # Score: longer segments facing centroid preferred
        seg_dx = coords[i + 1][0] - coords[i][0]
        seg_dy = coords[i + 1][1] - coords[i][1]
        # Direction from midpoint to centroid
        to_cent_dx = centroid.x - mid.x
        to_cent_dy = centroid.y - mid.y
        to_cent_len = math.sqrt(to_cent_dx ** 2 + to_cent_dy ** 2)
        if to_cent_len == 0:
            continue
        to_cent_dx /= to_cent_len
        to_cent_dy /= to_cent_len
        # Perpendicular pointing inward
        perp_dx = -seg_dy / seg.length
        perp_dy = seg_dx / seg.length
        # Check which perpendicular direction faces centroid
        dot = perp_dx * to_cent_dx + perp_dy * to_cent_dy
        if dot < 0:
            perp_dx, perp_dy = -perp_dx, -perp_dy
        score = seg.length * (0.5 + dot)
        if score > best_score:
            best_score = score
            best_seg = (seg, (perp_dx, perp_dy))

    if best_seg is None:
        return None

    seg, direction = best_seg
    mid = seg.interpolate(0.5, normalized=True)
    return AccessPoint(
        point=(mid.x, mid.y),
        direction=direction,
        road_name="Derived",
        source="derived",
    )


# ── 1.6 Validate Parcel Integrity ──────────────────────────────────────────

def validate_parcel_integrity(parcel: Parcel, rules: LayoutRules) -> list[str]:
    """Return a list of warning strings. Empty list = all good."""
    warnings_list = []

    if parcel.geometry.area < rules.min_lot_area * 3:
        warnings_list.append(
            f"Parcel area {parcel.geometry.area:.0f}m² is less than 3× min lot area "
            f"({rules.min_lot_area * 3:.0f}m²) — insufficient room for road + lots"
        )

    if not parcel.geometry.is_valid:
        warnings_list.append("Parcel geometry is not valid (topology issues)")

    if not parcel.access_points:
        warnings_list.append("No access points defined")

    if parcel.gross_area > 0:
        buildable_ratio = parcel.buildable_area_sqm / parcel.gross_area
        if buildable_ratio < 0.3:
            warnings_list.append(
                f"Buildable area ratio {buildable_ratio:.1%} is below 30% — "
                f"layouts will likely fail"
            )

    return warnings_list