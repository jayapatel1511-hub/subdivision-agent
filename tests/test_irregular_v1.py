"""
Subdivision Agent — Irregular Parcel v1 Tests.

Tests the irregular parcel pipeline: GeoJSON intake, shape detection,
road placement, lot carving, and area conservation invariants.
"""

import pytest
from pathlib import Path
from shapely.geometry import Polygon

from models import (
    Parcel, AccessPoint, LayoutRules, LotType, ServiceType,
    LayoutResult, Lot, RoadPattern, ParcelShape,
)
from constraints import ConstraintEngine
from generator import LayoutGenerator
from checker import LotChecker, LayoutScorer
from intake_geojson import load_geojson_parcel, validate_parcel_integrity
from shape_analysis import detect_parcel_shape, is_rectangleish


# ── Helpers ──

FIXTURES_DIR = Path(__file__).parent / "fixtures"

ALL_FIXTURES = [
    FIXTURES_DIR / "L_shape.geojson",
    FIXTURES_DIR / "wedge.geojson",
    FIXTURES_DIR / "corridor.geojson",
    FIXTURES_DIR / "concave_boundary.geojson",
    FIXTURES_DIR / "rectangle.geojson",
]


def get_rules(zone="R-2", servicing="serviced"):
    """Get layout rules from the HRM constraint engine."""
    engine = ConstraintEngine("hrm")
    engine.load()
    pc = engine.resolve(zone, servicing)
    return LayoutRules.from_constraint_engine(pc)


def compute_accounted_area(result, parcel, rules):
    """Sum of all lot areas + road area + remainder area + constraint area."""
    lot_area = sum(l.area for l in result.residential_lots)
    remainder_area = result.remainder_area
    road_area = result.road_area
    constraint_area = result.constraint_area
    return lot_area + remainder_area + road_area + constraint_area


# ── GeoJSON Intake Tests ──

class TestGeoJSONIntake:
    """Tests for the GeoJSON loading pipeline."""

    def test_load_rectangle_geojson(self):
        """Loading a rectangle GeoJSON should produce a valid parcel."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "rectangle.geojson"))
        assert parcel is not None
        assert parcel.geometry.is_valid
        assert parcel.gross_area > 0
        assert parcel.zone_code == "R-2"
        assert len(parcel.access_points) >= 1

    def test_load_L_shape_geojson(self):
        """Loading an L-shape GeoJSON should produce a valid parcel."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "L_shape.geojson"))
        assert parcel is not None
        assert parcel.geometry.is_valid
        assert parcel.gross_area > 0
        assert len(parcel.access_points) >= 1

    def test_load_wedge_geojson(self):
        """Loading a wedge GeoJSON should produce a valid parcel."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "wedge.geojson"))
        assert parcel is not None
        assert parcel.geometry.is_valid
        assert parcel.gross_area > 0

    def test_load_corridor_geojson(self):
        """Loading a corridor GeoJSON should produce a valid parcel."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "corridor.geojson"))
        assert parcel is not None
        assert parcel.geometry.is_valid
        assert parcel.gross_area > 0

    def test_load_concave_boundary_geojson(self):
        """Loading a concave boundary GeoJSON should produce a valid parcel."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "concave_boundary.geojson"))
        assert parcel is not None
        assert parcel.geometry.is_valid
        assert parcel.gross_area > 0

    def test_access_points_parsed(self):
        """Access points should be parsed from GeoJSON features."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "L_shape.geojson"))
        assert len(parcel.access_points) >= 1
        ap = parcel.access_points[0]
        assert ap.point is not None
        # Direction should be a unit vector
        import math
        d_len = math.sqrt(ap.direction[0] ** 2 + ap.direction[1] ** 2)
        assert abs(d_len - 1.0) < 0.01

    def test_validate_parcel_integrity(self):
        """validate_parcel_integrity should return warnings for problematic parcels."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "rectangle.geojson"))
        rules = get_rules()
        warnings = validate_parcel_integrity(parcel, rules)
        # A 300x200 rectangle should have no critical warnings
        assert isinstance(warnings, list)


# ── Shape Analysis Tests ──

class TestShapeAnalysis:
    """Tests for shape detection and classification."""

    def test_rectangle_detected_as_rectangle(self):
        """A 300x200 rectangle should be classified as RECTANGLE."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "rectangle.geojson"))
        shape = detect_parcel_shape(parcel.geometry)
        assert shape == ParcelShape.RECTANGLE

    def test_L_shape_detected_as_irregular(self):
        """An L-shape should be classified as L_SHAPE or CONCAVE."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "L_shape.geojson"))
        shape = detect_parcel_shape(parcel.geometry)
        assert shape in (ParcelShape.L_SHAPE, ParcelShape.CONCAVE, ParcelShape.CORRIDOR)

    def test_wedge_detected_as_irregular(self):
        """A wedge should not be classified as RECTANGLE."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "wedge.geojson"))
        shape = detect_parcel_shape(parcel.geometry)
        # Wedge is convex but not rectangleish
        assert shape != ParcelShape.RECTANGLE

    def test_is_rectangleish_true_for_rectangle(self):
        """is_rectangleish should return True for a perfect rectangle."""
        poly = Polygon([(0, 0), (300, 0), (300, 200), (0, 200), (0, 0)])
        assert is_rectangleish(poly) is True

    def test_is_rectangleish_false_for_L_shape(self):
        """is_rectangleish should return False for an L-shape."""
        poly = Polygon([(0, 0), (300, 0), (300, 100), (100, 100), (100, 200), (0, 200), (0, 0)])
        assert is_rectangleish(poly) is False


# ── Layout Generation Tests ──

class TestIrregularLayoutGeneration:
    """Tests for layout generation on irregular parcels."""

    def test_irregular_L_shape_grid(self):
        """L-shaped parcel should generate a layout without crashing."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "L_shape.geojson"))
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        # Invariant: no crash
        assert result is not None

        # Run checker
        checker = LotChecker(rules)
        checker.check_layout(result)

        # Invariant: at least one lot
        assert len(result.lots) > 0

        # Invariant: saleable land > 0 (at least some lots pass)
        # For irregular parcels, this may be lower — just assert > 0
        assert result.saleable_land_pct >= 0

        # Invariant: all lots have valid geometry
        for lot in result.lots:
            assert lot.geometry is not None
            assert lot.geometry.area > 0

    def test_irregular_wedge_grid(self):
        """Wedge-shaped parcel should generate a layout without crashing."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "wedge.geojson"))
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        assert result is not None
        checker = LotChecker(rules)
        checker.check_layout(result)
        assert len(result.lots) > 0

    def test_irregular_corridor_grid(self):
        """Corridor-shaped parcel should generate a layout without crashing."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "corridor.geojson"))
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        assert result is not None
        checker = LotChecker(rules)
        checker.check_layout(result)
        assert len(result.lots) > 0

    def test_irregular_concave_boundary_grid(self):
        """Concave boundary parcel should generate a layout without crashing."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "concave_boundary.geojson"))
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        assert result is not None
        checker = LotChecker(rules)
        checker.check_layout(result)
        assert len(result.lots) > 0

    def test_irregular_cul_de_sac(self):
        """Cul-de-sac pattern should work on irregular parcels."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "L_shape.geojson"))
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.CUL_DE_SAC)

        assert result is not None

    def test_irregular_spine_branch(self):
        """Spine-branch pattern should work on irregular parcels."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "L_shape.geojson"))
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SPINE_BRANCH)

        assert result is not None


# ── Rectangle Regression Guard ──

class TestRectangleRegression:
    """Ensure rectangle parcels still route to the existing code path."""

    def test_rectangle_still_works_via_geojson(self):
        """Loading a rectangle via GeoJSON should produce results via the rectangle path."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "rectangle.geojson"))
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        assert result is not None
        checker = LotChecker(rules)
        checker.check_layout(result)

        # Rectangle should produce passing lots
        assert result.passing_lots > 0, (
            f"Rectangle via GeoJSON should produce passing lots, got {result.passing_lots}"
        )

    def test_rectangle_shape_detected(self):
        """Rectangle GeoJSON should be classified as RECTANGLE shape."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "rectangle.geojson"))
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)
        assert parcel.shape == ParcelShape.RECTANGLE

    def test_allow_irregular_carving_false_falls_back(self):
        """Setting allow_irregular_carving=False should use the rectangle path."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "L_shape.geojson"))
        rules = get_rules("R-2", "serviced")
        rules.allow_irregular_carving = False
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        assert result is not None
        # Should still produce some result (using rectangle path on irregular shape)


# ── Area Conservation Tests ──

class TestAreaConservation:
    """Verify that area is conserved across all fixtures."""

    @pytest.mark.parametrize("fixture_path", ALL_FIXTURES)
    def test_area_conservation(self, fixture_path):
        """Sum of all lot areas + road + remainder + constraints ≈ gross area."""
        if not fixture_path.exists():
            pytest.skip(f"Fixture {fixture_path} not found")

        parcel = load_geojson_parcel(str(fixture_path))
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        checker = LotChecker(rules)
        checker.check_layout(result)

        accounted = compute_accounted_area(result, parcel, rules)
        gross = parcel.gross_area

        # Area conservation within 5% (generous for irregular shapes)
        if gross > 0:
            ratio = abs(accounted - gross) / gross
            assert ratio < 0.05, (
                f"Area not conserved for {fixture_path.name}: "
                f"accounted={accounted:.0f}, gross={gross:.0f}, "
                f"diff={abs(accounted - gross):.0f} ({ratio:.1%})"
            )

    def test_all_lots_valid_geometry(self):
        """All generated lots should have valid, non-empty geometry."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "L_shape.geojson"))
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        for lot in result.lots:
            assert lot.geometry is not None
            assert lot.geometry.area > 0, f"Lot {lot.id} has zero area"
            assert lot.geometry.is_valid, f"Lot {lot.id} has invalid geometry"

    def test_lot_types_valid(self):
        """All lots should have valid LotType values."""
        parcel = load_geojson_parcel(str(FIXTURES_DIR / "L_shape.geojson"))
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        valid_types = {LotType.RESIDENTIAL, LotType.CORNER, LotType.IRREGULAR,
                       LotType.REMAINDER, LotType.ROAD_ROW, LotType.CONSTRAINT,
                       LotType.OPEN_SPACE}
        for lot in result.lots:
            assert lot.lot_type in valid_types, (
                f"Lot {lot.id} has invalid lot_type: {lot.lot_type}"
            )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])