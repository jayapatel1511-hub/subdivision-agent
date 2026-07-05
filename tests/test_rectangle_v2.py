"""
Subdivision Agent — Regression Tests for Rectangle v2.

Validates the core metrics and lot classification after the v2 rewrite.
Tests use 300×200 rectangular parcel as reference geometry.
"""

import pytest
from shapely.geometry import Polygon

from models import (
    Parcel, AccessPoint, LayoutRules, LotType, ServiceType,
    LayoutResult, Lot, RoadPattern,
)
from constraints import ConstraintEngine
from generator import LayoutGenerator
from checker import LotChecker, LayoutScorer


# ── Fixtures ──

def make_parcel(width=300, depth=200):
    """Create a rectangular test parcel."""
    coords = [(0, 0), (width, 0), (width, depth), (0, depth), (0, 0)]
    return Parcel(geometry=Polygon(coords), pid="test-parcel", zone_code="R-2")


def make_access(x=0, y=100, dx=1, dy=0):
    """Create an access point on the left side."""
    return AccessPoint(point=(x, y), direction=(dx, dy), road_name="Test Road")


def get_rules(zone="R-2", servicing="serviced"):
    """Get layout rules from the HRM constraint engine."""
    engine = ConstraintEngine("hrm")
    engine.load()
    pc = engine.resolve(zone, servicing)
    return LayoutRules.from_constraint_engine(pc)


# ── R-2 Serviced Tests ──

class TestR2Serviced:
    """Tests for R-2 serviced (municipal water/sewer) on 300×200."""

    def test_generates_layout(self):
        """Layout generation completes without errors."""
        parcel = make_parcel()
        parcel.access_points = [make_access()]
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)
        assert result is not None
        assert len(result.lots) > 0

    def test_residential_lots_pass(self):
        """All residential lots should pass R-2 serviced checks."""
        parcel = make_parcel()
        parcel.access_points = [make_access()]
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        checker = LotChecker(rules)
        checker.check_layout(result)

        residential = result.residential_lots
        assert len(residential) > 0, "Should have residential lots"

        # All residential lots should pass for R-2 serviced on a clean rectangle
        for lot in residential:
            assert lot.passes_all, (
                f"Lot {lot.id} ({lot.lot_type.value}) fails: "
                f"area={lot.passes_area}, frontage={lot.passes_frontage}, "
                f"depth={lot.passes_depth}, shape={lot.passes_shape}, "
                f"buildable={lot.passes_buildable}, service={lot.passes_service}"
            )

    def test_saleable_land_not_zero(self):
        """Saleable land % must be > 0 after checking (was 0% before fix)."""
        parcel = make_parcel()
        parcel.access_points = [make_access()]
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        checker = LotChecker(rules)
        checker.check_layout(result)

        assert result.saleable_land_pct > 0, (
            f"Saleable land % should be > 0, got {result.saleable_land_pct}%"
        )

    def test_saleable_land_reasonable(self):
        """Saleable land % should be in a reasonable range for a rectangle."""
        parcel = make_parcel()
        parcel.access_points = [make_access()]
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        checker = LotChecker(rules)
        checker.check_layout(result)

        # For a clean 300×200 rectangle with single road, expect 40-80%
        assert 30 < result.saleable_land_pct < 85, (
            f"Saleable land % out of expected range: {result.saleable_land_pct}%"
        )

    def test_remainder_not_counted_as_failed(self):
        """Remainder lots should NOT appear in failed residential count."""
        parcel = make_parcel()
        parcel.access_points = [make_access()]
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        checker = LotChecker(rules)
        checker.check_layout(result)

        # Remainder lots exist
        remainders = result.remainder_lots
        # Failed lots = only residential lots that fail, NOT remainders
        failed_residential = [l for l in result.lots if l.is_residential and not l.passes_all]
        # No remainder should appear in failed residential
        for l in failed_residential:
            assert l.lot_type != LotType.REMAINDER, (
                f"Remainder lot {l.id} should not be in failed residential"
            )

    def test_remainder_area_reported_separately(self):
        """Remainder area should be reported separately from passing/failing."""
        parcel = make_parcel()
        parcel.access_points = [make_access()]
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        checker = LotChecker(rules)
        checker.check_layout(result)

        # Area breakdown should balance approximately
        total = result.gross_area
        accounted = (result.road_area + result.passing_lot_area +
                     result.failing_lot_area + result.remainder_area)
        # Allow 5% rounding tolerance
        assert abs(total - accounted) < total * 0.05, (
            f"Area breakdown doesn't balance: gross={total:.0f}, "
            f"accounted={accounted:.0f} (road={result.road_area:.0f} + "
            f"passing={result.passing_lot_area:.0f} + "
            f"failing={result.failing_lot_area:.0f} + "
            f"remainder={result.remainder_area:.0f})"
        )

    def test_lot_types_are_valid(self):
        """Every lot should have a valid LotType."""
        parcel = make_parcel()
        parcel.access_points = [make_access()]
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        checker = LotChecker(rules)
        checker.check_layout(result)

        valid_types = {LotType.RESIDENTIAL, LotType.CORNER, LotType.IRREGULAR,
                      LotType.REMAINDER, LotType.ROAD_ROW, LotType.CONSTRAINT,
                      LotType.OPEN_SPACE}
        for lot in result.lots:
            assert lot.lot_type in valid_types, (
                f"Lot {lot.id} has invalid lot_type: {lot.lot_type}"
            )

    def test_scoring_works(self):
        """Scoring should produce a reasonable total score."""
        parcel = make_parcel()
        parcel.access_points = [make_access()]
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        checker = LotChecker(rules)
        checker.check_layout(result)

        scorer = LayoutScorer(rules)
        scorer.score_layout(result)

        assert result.score.total_score > 0, "Score should be positive"
        assert result.score.explanation, "Should have explanation text"

    def test_developable_used_pct(self):
        """Developable used % should be computed and reasonable."""
        parcel = make_parcel()
        parcel.access_points = [make_access()]
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        checker = LotChecker(rules)
        checker.check_layout(result)

        assert result.developable_used_pct > 0, (
            f"Developable used % should be > 0, got {result.developable_used_pct}%"
        )
        assert result.developable_used_pct <= 100, (
            f"Developable used % should be <= 100, got {result.developable_used_pct}%"
        )


# ── R-1 Unserved Tests ──

class TestR1Unserviced:
    """Tests for R-1 unserviced (well/septic) on 300×200."""

    def test_generates_layout(self):
        """Layout generation completes without errors."""
        parcel = make_parcel()
        parcel.access_points = [make_access()]
        rules = get_rules("R-1", "unserviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)
        assert result is not None
        assert len(result.lots) > 0

    def test_unserviced_lots_smaller_count(self):
        """R-1 unserviced should produce fewer lots than R-2 serviced."""
        parcel = make_parcel()
        parcel.access_points = [make_access()]

        rules_r2 = get_rules("R-2", "serviced")
        rules_r1 = get_rules("R-1", "unserviced")

        gen_r2 = LayoutGenerator(parcel, rules_r2)
        gen_r1 = LayoutGenerator(parcel, rules_r1)

        result_r2 = gen_r2.generate_layout(RoadPattern.SINGLE_ROAD)
        result_r1 = gen_r1.generate_layout(RoadPattern.SINGLE_ROAD)

        assert len(result_r1.residential_lots) < len(result_r2.residential_lots), (
            f"R-1 unserviced should have fewer lots than R-2 serviced "
            f"({len(result_r1.residential_lots)} vs {len(result_r2.residential_lots)})"
        )

    def test_unserviced_service_checks_fail(self):
        """R-1 unserviced lots should fail service feasibility on small parcels."""
        parcel = make_parcel()
        parcel.access_points = [make_access()]
        rules = get_rules("R-1", "unserviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        checker = LotChecker(rules)
        checker.check_layout(result)

        # On a 300×200 parcel, R-1 unserviced lots are expected to fail
        # (too small for well+septic requirements)
        residential = result.residential_lots
        service_fails = [l for l in residential if not l.passes_service]
        # This is expected behavior — not all lots can support well+septic on small parcels
        assert len(service_fails) > 0, "Expected service failures on R-1 unserviced"


# ── Area Metrics Consistency ──

class TestAreaConsistency:
    """Verify area metrics are consistent with each other."""

    def test_passing_failing_remainder_sum(self):
        """passing_lot_area + failing_lot_area + remainder_area should equal total lot area."""
        parcel = make_parcel()
        parcel.access_points = [make_access()]
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        checker = LotChecker(rules)
        checker.check_layout(result)

        lot_area_sum = result.passing_lot_area + result.failing_lot_area + result.remainder_area
        total_lot_area = sum(l.area for l in result.lots)

        assert abs(lot_area_sum - total_lot_area) < 1.0, (
            f"Area breakdown inconsistent: "
            f"passing({result.passing_lot_area:.0f}) + "
            f"failing({result.failing_lot_area:.0f}) + "
            f"remainder({result.remainder_area:.0f}) = {lot_area_sum:.0f}, "
            f"but total lot area = {total_lot_area:.0f}"
        )

    def test_road_area_positive(self):
        """Road area should be positive when a road is generated."""
        parcel = make_parcel()
        parcel.access_points = [make_access()]
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        checker = LotChecker(rules)
        checker.check_layout(result)

        assert result.road_area > 0, f"Road area should be positive, got {result.road_area}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])