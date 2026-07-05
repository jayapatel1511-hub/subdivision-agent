"""
Subdivision Agent — CLI Entry Point.

Generates, checks, scores, and exports subdivision layout options.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from shapely.geometry import Polygon, LineString, Point

from models import (
    Parcel, AccessPoint, ConstraintArea, LayoutRules,
    RoadPattern, LotType, WarningLevel,
)
from constraints import ConstraintEngine
from generator import LayoutGenerator
from checker import LotChecker, LayoutScorer
from export import export_geojson, export_dxf, export_summary


def make_rectangular_parcel(width: float, depth: float) -> Parcel:
    """Create a simple rectangular parcel for testing."""
    coords = [(0, 0), (width, 0), (width, depth), (0, depth), (0, 0)]
    return Parcel(geometry=Polygon(coords), pid="test-parcel", zone_code="R-2")


def make_access_point(x: float = 0, y: float = 0,
                       dx: float = 1, dy: float = 0,
                       road_name: str = "Existing Road") -> AccessPoint:
    """Create an access point."""
    return AccessPoint(
        point=(x, y),
        direction=(dx, dy),
        road_name=road_name,
    )


def add_constraint_watercourse(parcel: Parcel, x_offset: float = None,
                                 y_offset: float = None,
                                 width: float = 20) -> Parcel:
    """Add a watercourse constraint to the parcel."""
    bounds = parcel.geometry.bounds
    if x_offset is None:
        x_offset = (bounds[0] + bounds[2]) / 2
    if y_offset is None:
        y_offset = bounds[1]

    # Watercourse runs across the parcel
    stream_coords = [
        (bounds[0], y_offset - width),
        (x_offset - width/2, y_offset + width/4),
        (x_offset + width/2, y_offset - width/4),
        (bounds[2], y_offset + width),
    ]
    stream = LineString(stream_coords)
    buffer = stream.buffer(width / 2)

    # Clip to parcel
    clipped = buffer.intersection(parcel.geometry)
    if clipped.is_empty:
        return parcel

    constraint = ConstraintArea(
        name="Watercourse Buffer",
        geometry=clipped,
        deductible=True,
        buffer_m=0,
        source="NS Wetland Policy",
    )
    parcel.constraint_areas.append(constraint)
    return parcel


def print_lot_details(result, rules):
    """Print per-lot details for a layout result."""
    print(f"\n{'─' * 70}")
    print(f"LOT DETAILS — Option {result.name} " +
          ("(recommended)" if result == sorted_results[0] else ""))
    print(f"{'─' * 70}")

    for lot in result.lots:
        status = "✓" if lot.passes_all else "✗"
        lot_type_str = lot.lot_type.value if isinstance(lot.lot_type, type(LotType.RESIDENTIAL)) else lot.lot_type.value

        # Show different info for remainders
        if lot.lot_type == LotType.REMAINDER:
            print(f"  Lot {lot.id:>3} [{lot_type_str:>11}] {status} Area={lot.area:>7.0f}m²  " +
                  f"Front={lot.frontage:>5.1f}m  Depth={lot.depth:>5.1f}m  Shape={lot.shape_quality:.2f}")
        else:
            checks = []
            if not lot.passes_area: checks.append("area")
            if not lot.passes_frontage: checks.append("frontage")
            if not lot.passes_depth: checks.append("depth")
            if not lot.passes_shape: checks.append("shape")
            if not lot.passes_buildable: checks.append("buildable")
            if not lot.passes_service: checks.append("service")

            check_str = f"  ✗ [{', '.join(checks)}]" if checks else ""
            print(f"  Lot {lot.id:>3} [{lot_type_str:>11}] {status} Area={lot.area:>7.0f}m²  " +
                  f"Front={lot.frontage:>5.1f}m  Depth={lot.depth:>5.1f}m  Shape={lot.shape_quality:.2f}{check_str}")


def main():
    parser = argparse.ArgumentParser(description="Subdivision Layout Generator")
    parser.add_argument("--parcel", default="300x200",
                        help="Parcel size as WxH (e.g. 300x200)")
    parser.add_argument("--zone", default="R-2",
                        help="Zone code (e.g. R-2, R-1)")
    parser.add_argument("--servicing", default="serviced",
                        choices=["serviced", "unserviced", "serviced_water_only"],
                        help="Servicing type")
    parser.add_argument("--patterns", default="all",
                        help="Comma-separated patterns or 'all'")
    parser.add_argument("--road-length", type=float, default=None,
                        help="Override road length (metres)")
    parser.add_argument("--export", default=None,
                        help="Export prefix for output files (e.g. 'output/layout')")
    parser.add_argument("--format", default="geojson",
                        choices=["geojson", "dxf", "json", "all"],
                        help="Export format")
    args = parser.parse_args()

    # ── Create Parcel ──
    if "x" in args.parcel:
        w, h = map(float, args.parcel.split("x"))
    else:
        w, h = 300, 200

    parcel = make_rectangular_parcel(w, h)

    # Access point at bottom-left, pointing inward
    access = make_access_point(x=0, y=h/2, dx=1, dy=0)
    parcel.access_points = [access]

    print(f"Parcel: {w:.0f}m × {h:.0f}m = {parcel.gross_area:.0f} m² ({parcel.gross_area/10000:.2f} ha)")
    print()

    # ── Load Constraints ──
    engine = ConstraintEngine("hrm")
    engine.load()

    servicing_map = {
        "serviced": "serviced",
        "unserviced": "unserviced",
        "serviced_water_only": "serviced_water_only",
    }
    servicing_type = servicing_map.get(args.servicing, "serviced")

    pc = engine.resolve(args.zone, servicing_type)

    rules = LayoutRules.from_constraint_engine(pc)

    print(f"Rules: {args.zone} + {servicing_type}")
    print(f"  Min lot area: {rules.min_lot_area} m²")
    print(f"  Min frontage: {rules.min_frontage} m")
    print(f"  Min depth: {rules.min_depth} m")
    print(f"  ROW width: {rules.row_width} m")
    print(f"  Service type: {rules.service_type.value}")
    print()

    # ── Generate Layouts ──
    gen = LayoutGenerator(parcel, rules)

    if args.patterns == "all":
        patterns = list(RoadPattern)
    else:
        pattern_names = [p.strip() for p in args.patterns.split(",")]
        patterns = [RoadPattern(p) for p in pattern_names if p in [rp.value for rp in RoadPattern]]

    print(f"Generating {len(patterns)} layout patterns: {', '.join(p.value for p in patterns)}")
    print()

    results = []
    for pattern in patterns:
        result = gen.generate_layout(pattern, road_length=args.road_length)
        results.append(result)

    # ── Check & Score ──
    checker = LotChecker(rules, parcel.constraint_areas)
    scorer = LayoutScorer(rules)

    for result in results:
        checker.check_layout(result)
        scorer.score_layout(result)

    # Rank
    global sorted_results
    sorted_results = sorted(results, key=lambda r: r.score.total_score, reverse=True)

    # ── Print Results ──
    print(export_summary(sorted_results))

    # Per-lot details for top result
    if sorted_results:
        print_lot_details(sorted_results[0], rules)

    # ── Export ──
    if args.export:
        for i, result in enumerate(sorted_results):
            prefix = f"{args.export}_{result.name}_{result.pattern.value}"
            if args.format in ("geojson", "all"):
                path = f"{prefix}.geojson"
                export_geojson(result, path)
                print(f"  Exported: {path}")
            if args.format in ("dxf", "all"):
                path = f"{prefix}.dxf"
                export_dxf(result, path)
                print(f"  Exported: {path}")
            if args.format in ("json", "all"):
                from models import layout_result_to_json
                path = f"{prefix}_full.json"
                layout_result_to_json(result, path)
                print(f"  Exported: {path}")


if __name__ == "__main__":
    main()