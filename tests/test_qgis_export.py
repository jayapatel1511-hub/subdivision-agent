"""
Subdivision Agent — Tests for QGIS export.
"""

import json
import shutil
import zipfile
from pathlib import Path

import pytest
from shapely.geometry import Polygon

from models import (
    Parcel, AccessPoint, LayoutRules, LotType, ServiceType,
    LayoutResult, Lot, RoadSegment, RoadPattern, LayoutScore,
)
from constraints import ConstraintEngine
from generator import LayoutGenerator
from checker import LotChecker, LayoutScorer
from export_qgis import export_qgis


# ── Fixtures ──

OUT_DIR = Path("/tmp/test_qgis_export")


def make_parcel(width=300, depth=200):
    coords = [(0, 0), (width, 0), (width, depth), (0, depth), (0, 0)]
    return Parcel(geometry=Polygon(coords), pid="test-parcel", zone_code="R-2")


def make_access(x=0, y=100, dx=1, dy=0):
    return AccessPoint(point=(x, y), direction=(dx, dy), road_name="Test Road")


def get_rules(zone="R-2", servicing="serviced"):
    engine = ConstraintEngine("hrm")
    engine.load()
    pc = engine.resolve(zone, servicing)
    return LayoutRules.from_constraint_engine(pc)


def generate_test_layout():
    """Generate a real, checked layout for a 300x200 R-2 serviced parcel."""
    parcel = make_parcel()
    parcel.access_points = [make_access()]
    rules = get_rules("R-2", "serviced")
    gen = LayoutGenerator(parcel, rules)
    result = gen.generate_layout(RoadPattern.SINGLE_ROAD)
    checker = LotChecker(rules)
    checker.check_layout(result)
    scorer = LayoutScorer(rules)
    scorer.score_layout(result)
    result.compute_area_metrics()
    return result, parcel


@pytest.fixture(scope="module")
def exported_layout():
    """Set up: generate a layout, export to /tmp, return out_dir."""
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    result, parcel = generate_test_layout()
    export_qgis(result, str(OUT_DIR), parcel=parcel)
    return OUT_DIR


# ── Tests ──

ALL_LAYERS = [
    "lots_passing", "lots_failing", "remainders", "roads",
    "road_centerlines", "frontage_lines", "buildable_envelopes",
    "parcel_boundary",
]


def test_qgis_export_creates_folder(exported_layout):
    """export_qgis creates the output folder with all expected files."""
    qgz = exported_layout / "test_qgis_export.qgz"
    assert qgz.exists(), f"Missing .qgz: {qgz}"
    for layer in ALL_LAYERS:
        assert (exported_layout / f"{layer}.geojson").exists(), \
            f"Missing {layer}.geojson"
        assert (exported_layout / f"{layer}.qml").exists(), \
            f"Missing {layer}.qml"


def test_qgis_export_geojson_valid(exported_layout):
    """Each GeoJSON file is valid JSON with correct structure."""
    for layer in ALL_LAYERS:
        with open(exported_layout / f"{layer}.geojson") as f:
            data = json.load(f)
        assert data["type"] == "FeatureCollection", \
            f"{layer}: bad type"
        assert "crs" in data, f"{layer}: missing crs"
        assert "features" in data, f"{layer}: missing features"
        assert isinstance(data["features"], list)


def test_qgis_export_crs_field(exported_layout):
    """CRS field uses EPSG::2959 urn format."""
    with open(exported_layout / "roads.geojson") as f:
        data = json.load(f)
    name = data["crs"]["properties"]["name"]
    assert "2959" in name, f"Bad CRS: {name}"


def test_qgis_export_qgz_valid_zip(exported_layout):
    """The .qgz file is a valid ZIP containing project.qgs."""
    qgz = exported_layout / "test_qgis_export.qgz"
    with zipfile.ZipFile(qgz) as zf:
        names = zf.namelist()
        assert "project.qgs" in names, f"project.qgs missing; got {names}"


def test_qgis_export_project_xml(exported_layout):
    """project.qgs contains layer references and CRS."""
    qgz = exported_layout / "test_qgis_export.qgz"
    with zipfile.ZipFile(qgz) as zf:
        qgs = zf.read("project.qgs").decode()
    assert "EPSG:2959" in qgs, "Missing CRS in project.qgs"
    assert "lots_passing.geojson" in qgs
    assert "roads.geojson" in qgs
    assert "parcel_boundary.geojson" in qgs
    # QML references
    assert "lots_passing.qml" in qgs


def test_qgis_export_passing_failing_split(exported_layout):
    """Passing and failing lots are correctly separated."""
    with open(exported_layout / "lots_passing.geojson") as f:
        passing = json.load(f)
    with open(exported_layout / "lots_failing.geojson") as f:
        failing = json.load(f)

    # Every feature in lots_passing has passes_all == true
    for feat in passing["features"]:
        assert feat["properties"]["passes_all"] is True, \
            f"Lot {feat['properties']['lot_id']} in passing but passes_all=False"
    # Every feature in lots_failing has passes_all == false
    for feat in failing["features"]:
        assert feat["properties"]["passes_all"] is False, \
            f"Lot {feat['properties']['lot_id']} in failing but passes_all=True"

    # Total count matches residential lots from generator
    result, _ = generate_test_layout()
    total = len(result.residential_lots)
    assert len(passing["features"]) + len(failing["features"]) == total


def test_qgis_export_parcel_boundary(exported_layout):
    """Parcel boundary GeoJSON contains the original parcel polygon."""
    with open(exported_layout / "parcel_boundary.geojson") as f:
        data = json.load(f)
    assert len(data["features"]) == 1, "parcel_boundary should have one feature"
    feat = data["features"][0]
    assert feat["geometry"]["type"] == "Polygon"
    assert feat["properties"]["pid"] == "test-parcel"


def test_qgis_export_roads_layer(exported_layout):
    """Roads layer contains road ROW polygons."""
    with open(exported_layout / "roads.geojson") as f:
        data = json.load(f)
    assert len(data["features"]) > 0, "roads layer is empty"
    for feat in data["features"]:
        assert feat["geometry"]["type"] == "Polygon"
        assert "road_id" in feat["properties"]
        assert "row_width_m" in feat["properties"]


def test_qgis_export_road_centerlines(exported_layout):
    """Road centerlines layer contains LineStrings."""
    with open(exported_layout / "road_centerlines.geojson") as f:
        data = json.load(f)
    assert len(data["features"]) > 0
    for feat in data["features"]:
        assert feat["geometry"]["type"] == "LineString"


def test_qgis_export_qml_styles(exported_layout):
    """QML files contain expected style markers."""
    passing_qml = (exported_layout / "lots_passing.qml").read_text()
    assert "134,219,108" in passing_qml, "passing fill color missing"
    assert "SimpleFill" in passing_qml

    failing_qml = (exported_layout / "lots_failing.qml").read_text()
    assert "244,108,88" in failing_qml

    roads_qml = (exported_layout / "roads.qml").read_text()
    assert "66,133,244" in roads_qml

    centerlines_qml = (exported_layout / "road_centerlines.qml").read_text()
    assert "SimpleLine" in centerlines_qml


def test_qgis_export_no_dependencies():
    """export_qgis runs with stdlib only — no new pip deps required."""
    import importlib
    mod = importlib.import_module("export_qgis")
    assert hasattr(mod, "export_qgis")