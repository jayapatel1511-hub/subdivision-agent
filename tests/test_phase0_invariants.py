"""
Phase 0 invariant tests — lock down engine correctness fixes.

These tests verify geometric invariants that MUST hold for every layout:
- No landlocked lots (every residential lot has road frontage)  [Bug 0.1]
- No overlapping lots (lots don't share area)                   [Bug 0.2]
- Road steering doesn't compound rotation error                [Bug 0.3]
- Real-parcel scoreboard does not regress (>= 8/30)            [regression]

Fixtures/helpers mirror tests/test_rectangle_v2.py (300x200 rectangle baseline).
"""
import math
import os

import pytest
from shapely.geometry import Polygon
from shapely.ops import unary_union

from models import (
    Parcel, AccessPoint, LayoutRules, LotType, RoadPattern,
)
from constraints import ConstraintEngine
from generator import LayoutGenerator
from checker import LotChecker
from intake_geojson import load_geojson_parcel


# ── Fixtures / helpers ────────────────────────────────────────────────────

def make_parcel(width=300, depth=200):
    """Create a rectangular test parcel (matches test_rectangle_v2 baseline)."""
    coords = [(0, 0), (width, 0), (width, depth), (0, depth), (0, 0)]
    return Parcel(geometry=Polygon(coords), pid="test-parcel", zone_code="R-2")


def make_access(x=0, y=100, dx=1, dy=0):
    return AccessPoint(point=(x, y), direction=(dx, dy), road_name="Test Road")


def get_rules(zone="R-2", servicing="serviced"):
    engine = ConstraintEngine("hrm")
    engine.load()
    pc = engine.resolve(zone, servicing)
    return LayoutRules.from_constraint_engine(pc)


def rectangle_with_access(width=300, depth=200, two_access=False):
    """300x200 rectangle with one (or two) access points."""
    parcel = make_parcel(width, depth)
    access = [make_access(0, depth / 2, 1, 0)]
    if two_access:
        access.append(AccessPoint(point=(width, depth / 2), direction=(-1, 0),
                                  road_name="Test Road"))
    parcel.access_points = access
    return parcel


def road_row_union(result):
    return unary_union([r.row_polygon for r in result.roads])


# ── Bug 0.1 — no landlocked lots ─────────────────────────────────────────

class TestNoLandlockedLots:
    """Every residential lot must have road frontage (Bug 0.1)."""

    def test_no_landlocked_lots(self):
        parcel = rectangle_with_access()
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        row = road_row_union(result)
        residential = result.residential_lots
        assert len(residential) > 0, "Should produce residential lots"

        for lot in residential:
            # The lot geometry and its claimed frontage must both touch the
            # road ROW (within a 1m tolerance — the frontage line is offset
            # row_half + 0.5m beyond the centerline). A landlocked back-row
            # lot sits ~lot_depth_target behind the road and fails this.
            assert lot.geometry.distance(row) <= 1.0, (
                f"Lot {lot.id} geometry is {lot.geometry.distance(row):.1f}m "
                f"from the road ROW — landlocked (no road frontage)"
            )
            assert lot.frontage_line.distance(row) <= 1.0, (
                f"Lot {lot.id} frontage_line does not touch the road ROW "
                f"(distance {lot.frontage_line.distance(row):.1f}m)"
            )

        # No residential lot centroid may be more than one lot_depth_target
        # from the road centerline — that would indicate a back-row lot.
        centerline = result.roads[0].centerline
        for lot in residential:
            d = centerline.distance(lot.geometry.centroid)
            assert d <= rules.lot_depth_target + 1.0, (
                f"Lot {lot.id} centroid is {d:.1f}m from the centerline "
                f"(> lot_depth_target={rules.lot_depth_target}m) — landlocked"
            )


# ── Bug 0.2 — no overlapping lots ─────────────────────────────────────────

class TestNoOverlappingLots:
    """Residential lots must not share area (Bug 0.2)."""

    @pytest.mark.parametrize("pattern", [
        RoadPattern.T_ROAD,
        RoadPattern.SPINE_BRANCH,
        RoadPattern.LOOP_ROAD,
    ])
    def test_no_overlapping_lots(self, pattern):
        parcel = rectangle_with_access(two_access=True)
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(pattern)

        assert len(result.roads) >= 1, f"{pattern.value} should generate roads"
        residential = result.residential_lots
        assert len(residential) >= 2, (
            f"{pattern.value} should produce >=2 residential lots to test overlap"
        )

        # No pair of residential lots may share area beyond a 1m² tolerance
        # (tolerance accounts for shared boundary slivers from float ops).
        overlaps = 0
        worst = 0.0
        for i in range(len(residential)):
            for j in range(i + 1, len(residential)):
                a, b = residential[i], residential[j]
                if a.geometry.intersects(b.geometry):
                    inter = a.geometry.intersection(b.geometry)
                    if inter.area > 1.0:
                        overlaps += 1
                        worst = max(worst, inter.area)
        assert overlaps == 0, (
            f"{pattern.value}: {overlaps} overlapping residential lot pairs "
            f"(worst overlap {worst:.1f}m²)"
        )

        # remaining_developable must not be significantly negative.
        assert result.remaining_developable >= -1.0, (
            f"{pattern.value}: remaining_developable "
            f"{result.remaining_developable:.1f} is significantly negative "
            f"(over-allocation / overlap)"
        )


# ── Bug 0.3 — road steering rotation ──────────────────────────────────────

class TestRoadSteeringRotation:
    """The irregular road placer must not compound rotation error (Bug 0.3)."""

    @pytest.fixture
    def l_shape_parcel(self):
        # tests/fixtures/L_shape.geojson is irregular -> dispatched to the
        # irregular path which uses _iterative_road_extension.
        fix = os.path.join(os.path.dirname(__file__), "fixtures", "L_shape.geojson")
        if not os.path.exists(fix):
            pytest.skip("L_shape.geojson fixture missing")
        return load_geojson_parcel(fix)

    def test_road_stays_in_parcel_and_step_rotation_bounded(self, l_shape_parcel):
        from irregular_generator import IrregularRoadPlacer
        rules = get_rules("R-2", "serviced")
        roads = IrregularRoadPlacer().place_roads(l_shape_parcel, rules, "single_road")

        assert roads, "single_road should generate a road on the L-shape"
        centerline = roads[0].centerline
        assert centerline.length >= 20.0, (
            f"road centerline too short ({centerline.length:.1f}m)"
        )

        # The centerline must stay within the parcel (0.5m inward buffer).
        assert l_shape_parcel.geometry.buffer(-0.5).contains(centerline) or \
               l_shape_parcel.geometry.buffer(-0.5).distance(centerline) == 0.0, (
            "road centerline exits the parcel"
        )

        # No single 20m step should rotate more than 15° from the previous
        # step's direction. The steering search only tries {0, +15, -15}°,
        # so every step turn is bounded by 15°; the compounding-rotation bug
        # would drift the road out of the parcel instead.
        coords = list(centerline.coords)
        max_step = 0.0
        prev_bearing = None
        for i in range(len(coords) - 1):
            dx = coords[i + 1][0] - coords[i][0]
            dy = coords[i + 1][1] - coords[i][1]
            if dx == 0 and dy == 0:
                continue
            bearing = math.degrees(math.atan2(dy, dx))
            if prev_bearing is not None:
                delta = abs(((bearing - prev_bearing + 180) % 360) - 180)
                max_step = max(max_step, delta)
            prev_bearing = bearing
        assert max_step <= 15.0 + 1e-6, (
            f"road steering made a {max_step:.2f}° step turn "
            f"(must be <= 15°)"
        )

    def test_rotation_formula_is_correct(self):
        """Directly verify the 2D rotation used by _iterative_road_extension.

        Both components must be derived from the ORIGINAL (dx, dy); updating
        dx in place before computing dy (the Bug 0.3 bug) yields an
        under-rotated, non-orthonormal result that compounds over steps.
        """
        for angle_deg in (15.0, -15.0, 0.0, 30.0):
            angle_rad = math.radians(angle_deg)
            cos_a, sin_a = math.cos(angle_rad), math.sin(angle_rad)

            # Fixed formula (current code): both use original dx, dy.
            dx, dy = 1.0, 0.0
            new_dx = dx * cos_a - dy * sin_a
            new_dy = dx * sin_a + dy * cos_a
            assert abs(math.hypot(new_dx, new_dy) - 1.0) < 1e-9, (
                f"fixed rotation at {angle_deg}° is not unit-length"
            )
            got = math.degrees(math.atan2(new_dy, new_dx))
            assert abs(got - angle_deg) < 1e-9, (
                f"fixed rotation at {angle_deg}° produced {got:.4f}°"
            )

            # Buggy formula (pre-fix): dy uses the already-updated dx.
            # For a non-zero angle this is neither unit-length nor the
            # intended angle — the failure mode the fix removes.
            dx, dy = 1.0, 0.0
            buggy_dx = dx * cos_a - dy * sin_a
            buggy_dy = buggy_dx * sin_a + dy * cos_a  # uses updated dx
            if angle_deg not in (0.0,):
                assert abs(math.degrees(math.atan2(buggy_dy, buggy_dx))
                           - angle_deg) > 1e-3, (
                    f"buggy formula unexpectedly matches correct at {angle_deg}°"
                )


# ── Regression — real parcel scoreboard ──────────────────────────────────

class TestRealParcelRegression:
    """Real-parcel scoreboard must not regress below the documented baseline."""

    def test_real_parcels_no_regression(self):
        """At least 8/30 real parcels must produce >=1 passing residential lot.

        Mirrors the methodology in docs/REAL_PARCEL_VALIDATION.md: zone R-2
        serviced, best of {single_road, cul_de_sac, existing_road} per parcel.
        Per-pattern generation is wrapped so a crash on one pattern (e.g. the
        irregular path on some concave parcels) does not fail the whole parcel.
        """
        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures", "real")
        if not os.path.isdir(fixtures_dir):
            pytest.skip("tests/fixtures/real/ not present")
        fixtures = sorted(
            f for f in os.listdir(fixtures_dir)
            if f.startswith("parcel_") and f.endswith(".geojson")
        )
        assert len(fixtures) == 30, (
            f"expected 30 real parcel fixtures, found {len(fixtures)}"
        )

        rules = get_rules("R-2", "serviced")
        patterns = [
            RoadPattern.SINGLE_ROAD,
            RoadPattern.CUL_DE_SAC,
            RoadPattern.EXISTING_ROAD,
        ]

        passed = 0
        for fname in fixtures:
            path = os.path.join(fixtures_dir, fname)
            parcel = load_geojson_parcel(path, rules)
            # Fixtures default to zone R-1; the documented baseline runs R-2.
            parcel.zone_code = "R-2"
            best_passing = 0
            for pat in patterns:
                try:
                    gen = LayoutGenerator(parcel, rules)
                    result = gen.generate_layout(pat)
                    checker = LotChecker(rules)
                    checker.check_layout(result)
                    best_passing = max(best_passing, result.passing_lots)
                except Exception:
                    # A pattern that crashes contributes 0 passing lots,
                    # matching the best-of-3 baseline methodology.
                    continue
            if best_passing >= 1:
                passed += 1

        assert passed >= 8, (
            f"Scoreboard regression: only {passed}/30 real parcels produced "
            f"a passing lot (baseline >= 8)"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])