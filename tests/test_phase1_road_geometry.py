"""
Phase 1 — Road Geometry tests.

Covers the Phase 1 sub-tasks:
- 1.4 Frontage measured on the actual ROW edge
- 1.1 Curvature-constrained centerlines
- 1.2 Real cul-de-sac bulbs
- 1.3 Intersection geometry
- 1.5 Loop road honesty fix

Helpers mirror tests/test_phase0_invariants.py (300x200 rectangle baseline).
"""
import math
import os

import pytest
from shapely.geometry import Polygon, LineString, Point

from models import (
    Parcel, AccessPoint, LayoutRules, LotType, RoadPattern, RoadSegment,
    Lot, frontage_length,
)
from constraints import ConstraintEngine
from generator import LayoutGenerator
from checker import LotChecker


# ── Fixtures / helpers ────────────────────────────────────────────────────

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


def rectangle_with_access(width=300, depth=200, two_access=False):
    parcel = make_parcel(width, depth)
    access = [make_access(0, depth / 2, 1, 0)]
    if two_access:
        access.append(AccessPoint(point=(width, depth / 2), direction=(-1, 0),
                                  road_name="Test Road"))
    parcel.access_points = access
    return parcel


# ── 1.4 Frontage on ROW edge ──────────────────────────────────────────────

class TestFrontageOnRowEdge:
    """Frontage must be the lot's shared boundary with the road ROW polygon,
    not the construction `frontage_line` segment."""

    def test_landlocked_lot_gets_zero_frontage(self):
        """A lot with a frontage_line but no ROW contact reports frontage 0."""
        # ROW polygon far from the lot
        row = Polygon([(0, 0), (50, 0), (50, 16), (0, 16), (0, 0)])
        lot_geom = Polygon([(1000, 1000), (1030, 1000),
                            (1030, 1040), (1000, 1040), (1000, 1000)])
        # A fictional construction segment that does NOT border the ROW
        fline = LineString([(1000, 1000), (1030, 1000)])
        assert fline.length == 30.0

        lot = Lot(id=1, geometry=lot_geom, frontage_line=fline,
                  road_row_polygon=row)
        lot.compute_properties()
        assert lot.frontage == 0.0, (
            f"landlocked lot should self-detect with frontage 0, got {lot.frontage}"
        )

    def test_frontage_uses_row_edge_not_construction_segment(self):
        """A lot adjacent to the ROW gets frontage equal to the shared edge
        length, NOT the (longer) construction frontage_line."""
        # Horizontal road ROW 100m long, 16m wide
        row = Polygon([(0, 0), (100, 0), (100, 16), (0, 16), (0, 0)])
        # Lot sits above the road, touching it along a 50m edge (x in [10,60])
        lot_geom = Polygon([(10, 16), (60, 16),
                            (60, 50), (10, 50), (10, 16)])
        shared_edge = 50.0
        # Fictional construction segment much longer than the real frontage
        fline = LineString([(0, 16), (100, 16)])
        assert fline.length == 100.0

        lot = Lot(id=2, geometry=lot_geom, frontage_line=fline,
                  road_row_polygon=row)
        lot.compute_properties()
        assert lot.frontage > 0.0
        # Frontage reflects the shared edge, not the 100m construction line
        assert abs(lot.frontage - shared_edge) < 5.0, (
            f"frontage should be ~{shared_edge}m (shared edge), "
            f"got {lot.frontage}"
        )
        assert lot.frontage < 70.0, (
            f"frontage should not be the 100m construction segment, "
            f"got {lot.frontage}"
        )

    def test_depth_width_use_rotated_rectangle(self):
        """depth/width_min come from the minimum rotated rectangle, not
        area/frontage or the axis-aligned bbox."""
        row = Polygon([(0, 0), (100, 0), (100, 16), (0, 16), (0, 0)])
        # 20m wide x 34m deep lot, axis-aligned, touching the ROW
        lot_geom = Polygon([(10, 16), (30, 16),
                            (30, 50), (10, 50), (10, 16)])
        fline = LineString([(10, 16), (30, 16)])
        lot = Lot(id=3, geometry=lot_geom, frontage_line=fline,
                  road_row_polygon=row)
        lot.compute_properties()
        assert abs(lot.width_min - 20.0) < 0.5
        assert abs(lot.depth - 34.0) < 0.5

    def test_generated_lots_carry_row_polygon(self):
        """Lots produced by the generator carry a road_row_polygon and report
        ROW-based frontage."""
        parcel = rectangle_with_access()
        rules = get_rules("R-2", "serviced")
        gen = LayoutGenerator(parcel, rules)
        result = gen.generate_layout(RoadPattern.SINGLE_ROAD)

        residential = result.residential_lots
        assert residential, "expected residential lots"
        for lot in residential:
            assert lot.road_row_polygon is not None, (
                f"lot {lot.id} missing road_row_polygon"
            )
            # ROW-based frontage should be positive for roadside lots
            assert lot.frontage > 0.0, (
                f"lot {lot.id} has zero ROW frontage"
            )