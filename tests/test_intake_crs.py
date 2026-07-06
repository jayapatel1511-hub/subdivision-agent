"""
Regression tests for GeoJSON intake CRS handling.

Guards two bugs found with real HRM parcel data:
1. clean_polygon() ran before reprojection, so simplify(0.5) meant
   0.5 DEGREES (~50 km) on lat/lon input — real parcels collapsed to
   triangles (15 vertices -> 4, area 3918 m2 -> 809 m2).
2. The working CRS was EPSG:2959 (UTM zone 18N, Ontario) instead of
   EPSG:2961 (UTM zone 20N, Nova Scotia) — a ~2% systematic area error.
"""

import json

import pyproj
import pytest
from shapely.geometry import Polygon, mapping
from shapely.ops import transform as shp_transform

from intake_geojson import load_geojson_parcel


def _write_wgs84_fixture(tmp_path, poly_utm20n):
    """Inverse-project a metric polygon near Halifax to 4326 and write GeoJSON."""
    inv = pyproj.Transformer.from_crs("EPSG:2961", "EPSG:4326", always_xy=True)
    poly_ll = shp_transform(inv.transform, poly_utm20n)
    fc = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": mapping(poly_ll),
            "properties": {"zone_code": "R-2", "servicing_type": "serviced",
                           "pid": "crs-test"},
        }],
    }
    path = tmp_path / "wgs84_parcel.geojson"
    path.write_text(json.dumps(fc))
    return path


def test_wgs84_parcel_area_survives_intake(tmp_path):
    """A lat/lon parcel keeps its area (within 1%) through intake."""
    # 100m x 60m parcel near Bedford, NS (UTM 20N metres)
    x0, y0 = 448000, 4956000
    poly = Polygon([(x0, y0), (x0 + 100, y0), (x0 + 100, y0 + 60),
                    (x0, y0 + 60)])
    path = _write_wgs84_fixture(tmp_path, poly)

    parcel = load_geojson_parcel(str(path))

    assert parcel.working_crs == 2961
    assert abs(parcel.geometry.area - 6000) / 6000 < 0.01, \
        f"Area distorted through intake: {parcel.geometry.area:.0f} m2 (expected ~6000)"


def test_wgs84_parcel_vertices_not_collapsed(tmp_path):
    """Cleaning must not flatten a many-vertex lat/lon parcel to a triangle."""
    # 12-sided parcel: octagon-ish ring, radius ~50m
    import math
    x0, y0 = 448000, 4956000
    pts = [(x0 + 50 * math.cos(2 * math.pi * i / 12),
            y0 + 50 * math.sin(2 * math.pi * i / 12)) for i in range(12)]
    poly = Polygon(pts)
    path = _write_wgs84_fixture(tmp_path, poly)

    parcel = load_geojson_parcel(str(path))

    n_vertices = len(parcel.geometry.exterior.coords) - 1
    assert n_vertices >= 10, \
        f"Cleaning collapsed vertices: {n_vertices} left of 12"


def test_projected_input_kept_in_source_crs(tmp_path):
    """Input already in a projected CRS is not reprojected."""
    poly = Polygon([(0, 0), (100, 0), (100, 60), (0, 60)])
    fc = {
        "type": "FeatureCollection",
        "crs": {"type": "name",
                "properties": {"name": "urn:ogc:def:crs:EPSG::2959"}},
        "features": [{
            "type": "Feature",
            "geometry": mapping(poly),
            "properties": {"zone_code": "R-2", "servicing_type": "serviced"},
        }],
    }
    path = tmp_path / "projected_parcel.geojson"
    path.write_text(json.dumps(fc))

    parcel = load_geojson_parcel(str(path))

    assert parcel.working_crs == 2959
    assert abs(parcel.geometry.area - 6000) < 1.0
