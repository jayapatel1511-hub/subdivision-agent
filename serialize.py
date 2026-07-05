"""
Subdivision Agent — Web Serialization Helpers.

Read-only adapters that turn engine objects (Parcel, LayoutResult, Lot,
RoadSegment) into JSON-safe dicts and GeoJSON FeatureCollections for the web
frontend. Geometries are reprojected from the engine's working CRS (EPSG:2959
for HRM) to a display CRS (default EPSG:4326 lat/lng) so Leaflet can render them.

This module does NOT modify any engine logic — it only reads LayoutResult /
Parcel objects and re-projects their shapely geometries.
"""

from __future__ import annotations

from typing import Optional

import pyproj
from shapely.geometry import mapping
from shapely.ops import transform as shp_transform

from models import LayoutResult, Parcel, LotType, layout_result_to_dict


def reproject_geom(geom, src_crs: int, dst_crs: int):
    """Reproject a shapely geometry from src_crs to dst_crs (no-op if equal).

    Returns None if the geometry is None/empty, or if reprojection produces an
    empty or invalid geometry (e.g. coordinates outside the source CRS's
    valid domain). Callers should skip None results rather than emit them.
    """
    if geom is None or getattr(geom, "is_empty", False) or src_crs == dst_crs:
        return geom
    try:
        transformer = pyproj.Transformer.from_crs(
            f"EPSG:{src_crs}", f"EPSG:{dst_crs}", always_xy=True
        )
        out = shp_transform(transformer.transform, geom)
    except Exception:  # noqa: BLE001
        return None
    if out is None or getattr(out, "is_empty", False) or not out.is_valid:
        return None
    return out


def parcel_to_dict(parcel: Parcel, dst_crs: int = 4326) -> dict:
    """Serialize a Parcel to a JSON-safe dict with reprojected GeoJSON geometry."""
    geom = reproject_geom(parcel.geometry, parcel.working_crs, dst_crs)
    # Fall back to the original (working-CRS) geometry if reprojection failed,
    # so callers always get a usable geometry.
    if geom is None:
        geom = parcel.geometry
    return {
        "pid": parcel.pid,
        "zone_code": parcel.zone_code,
        "municipality": parcel.municipality,
        "source_crs": parcel.source_crs,
        "working_crs": parcel.working_crs,
        "display_crs": dst_crs,
        "geometry": mapping(geom),
        "gross_area_sqm": round(parcel.gross_area, 1),
        "buildable_area_sqm": round(parcel.buildable_area_sqm, 1),
        "constraint_area_pct": round(parcel.constraint_area_pct, 1),
        "shape": parcel.shape.value,
        "access_points": [
            {
                "point": list(ap.point),
                "direction": list(ap.direction),
                "road_name": ap.road_name,
                "source": ap.source,
            }
            for ap in parcel.access_points
        ],
        "constraint_areas": [
            {
                "name": ca.name,
                "geometry": mapping(
                    reproject_geom(ca.geometry, parcel.working_crs, dst_crs)
                    or ca.geometry),
                "deductible": ca.deductible,
                "buffer_m": ca.buffer_m,
                "source": ca.source,
            }
            for ca in parcel.constraint_areas
        ],
    }


def _lot_props(lot) -> dict:
    return {
        "lot_id": lot.id,
        "lot_type": lot.lot_type.value,
        "is_residential": lot.is_residential,
        "area_sqm": round(lot.area, 1),
        "frontage_m": round(lot.frontage, 1),
        "depth_m": round(lot.depth, 1),
        "width_min_m": round(lot.width_min, 1),
        "shape_quality": round(lot.shape_quality, 3),
        "passes_all": lot.passes_all,
        "passes_area": lot.passes_area,
        "passes_frontage": lot.passes_frontage,
        "passes_depth": lot.passes_depth,
        "passes_shape": lot.passes_shape,
        "passes_buildable": lot.passes_buildable,
        "passes_service": lot.passes_service,
        "constraint_conflicts": list(lot.constraint_conflicts),
        "warnings": list(lot.warnings),
    }


def _lot_status(lot) -> str:
    if lot.lot_type == LotType.REMAINDER:
        return "remainder"
    if lot.is_residential and lot.passes_all:
        return "passing"
    if lot.is_residential:
        return "failing"
    return "other"


def layout_result_to_geojson(result: LayoutResult,
                              parcel: Optional[Parcel] = None,
                              dst_crs: int = 4326) -> dict:
    """Build a GeoJSON FeatureCollection for a LayoutResult, reprojected to dst_crs.

    Features include: parcel boundary, lots (with pass/fail/remainder status),
    buildable envelopes, frontage lines, road ROW polygons, and road centerlines.
    Each feature carries a `layer` property so the frontend can style/filter.

    Features whose geometry cannot be reprojected (e.g. out-of-CRS coordinates)
    are skipped rather than emitting invalid GeoJSON.
    """
    src_crs = parcel.working_crs if parcel is not None else 2959
    features: list = []

    def _feat(geom, props):
        g = reproject_geom(geom, src_crs, dst_crs)
        if g is None or getattr(g, "is_empty", False):
            return None
        return {"type": "Feature", "geometry": mapping(g), "properties": props}

    # Parcel boundary
    if parcel is not None and parcel.geometry is not None:
        f = _feat(parcel.geometry, {"layer": "parcel", "name": "Parcel boundary"})
        if f:
            features.append(f)

    # Lots (+ envelopes + frontage)
    for lot in result.lots:
        props = _lot_props(lot)
        props["layer"] = "lots"
        props["status"] = _lot_status(lot)
        f = _feat(lot.geometry, props)
        if f:
            features.append(f)

        if lot.buildable_envelope is not None and not lot.buildable_envelope.is_empty:
            f = _feat(lot.buildable_envelope, {
                "layer": "buildable_envelope",
                "lot_id": lot.id,
                "area_sqm": round(lot.buildable_envelope.area, 1),
            })
            if f:
                features.append(f)

        if lot.frontage_line is not None and not lot.frontage_line.is_empty:
            f = _feat(lot.frontage_line, {
                "layer": "frontage",
                "lot_id": lot.id,
                "frontage_m": round(lot.frontage, 1),
            })
            if f:
                features.append(f)

    # Roads (ROW polygon + centerline)
    for i, road in enumerate(result.roads):
        f = _feat(road.row_polygon, {
            "layer": "road",
            "road_id": i,
            "name": road.name,
            "road_type": road.road_type,
            "row_width_m": road.row_width,
            "is_cul_de_sac": road.is_cul_de_sac,
            "length_m": round(road.length, 1),
            "area_sqm": round(road.area, 1),
        })
        if f:
            features.append(f)
        f = _feat(road.centerline, {
            "layer": "road_centerline",
            "road_id": i,
            "name": road.name,
        })
        if f:
            features.append(f)

    return {
        "type": "FeatureCollection",
        "crs": dst_crs,
        "features": features,
    }


def layout_result_to_web(result: LayoutResult,
                          parcel: Optional[Parcel] = None,
                          dst_crs: int = 4326) -> dict:
    """Combined serializer: metrics dict (from models) + GeoJSON + parcel.

    Returns everything the frontend needs to render one layout option.
    """
    data = layout_result_to_dict(result)
    data["geojson"] = layout_result_to_geojson(result, parcel, dst_crs)
    data["parcel"] = parcel_to_dict(parcel, dst_crs) if parcel is not None else None
    return data


def web_results(results: list[LayoutResult],
                 parcel: Optional[Parcel] = None,
                 dst_crs: int = 4326) -> list[dict]:
    """Serialize a ranked list of LayoutResults for the status endpoint."""
    return [layout_result_to_web(r, parcel, dst_crs) for r in results]