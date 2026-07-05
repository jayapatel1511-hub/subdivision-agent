#!/usr/bin/env python3
"""
Subdivision Agent — 2D Concept Layout Optimizer.

Generate, score, and rank subdivision layout options from a parcel boundary,
access point, constraints, and zoning/servicing rules.

Usage:
    # Quick run with defaults
    python main.py --parcel 300x200 --zone R-2 --servicing serviced

    # With constraints
    python main.py --parcel 300x200 --zone R-1 --servicing unserviced \\
                   --conditions watercourse_river,wetland

    # Specific access point
    python main.py --parcel 300x200 --zone R-2 --servicing serviced \\
                   --access 0,150,east

    # Full control
    python main.py --parcel 400x250 --zone R-1 --servicing unserviced \\
                   --conditions watercourse_river \\
                   --road-length 180 --patterns single_road,cul_de_sac,t_road \\
                   --export dxf,geojson --output-dir output/
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

from shapely.geometry import Polygon, LineString, Point
from shapely import affinity

from models import (
    Parcel, LayoutRules, LayoutResult, Lot, RoadSegment, LayoutScore,
    RoadPattern, LotType, LayoutWarning, WarningLevel, ServiceType,
    AccessPoint, ConstraintArea, layout_result_to_json,
)
from constraints import ConstraintEngine
from generator import LayoutGenerator
from checker import LotChecker, LayoutScorer
from export import export_geojson, export_dxf, export_summary


# ── Parcel Generators ──────────────────────────────────────────────────────

def make_rectangular_parcel(width: float, depth: float,
                             origin: tuple = (0, 0)) -> Polygon:
    """Create a simple rectangular parcel."""
    x, y = origin
    return Polygon([
        (x, y),
        (x + width, y),
        (x + width, y + depth),
        (x, y + depth),
    ])


def make_irregular_parcel(coords: list[tuple[float, float]]) -> Polygon:
    """Create a parcel from coordinate list."""
    return Polygon(coords)


def make_access_point(x: float, y: float, direction: str = "east") -> AccessPoint:
    """Create an access point with a cardinal direction."""
    directions = {
        "east": (1, 0),
        "west": (-1, 0),
        "north": (0, 1),
        "south": (0, -1),
        "ne": (0.707, 0.707),
        "nw": (-0.707, 0.707),
        "se": (0.707, -0.707),
        "sw": (-0.707, -0.707),
    }
    dx, dy = directions.get(direction.lower(), (1, 0))
    return AccessPoint(point=(x, y), direction=(dx, dy))


def add_constraint_watercourse(parcel: Polygon, side: str = "north",
                                buffer_m: float = 30.0) -> ConstraintArea:
    """Add a watercourse buffer along one side of the parcel."""
    bounds = parcel.bounds
    if side == "north":
        line = LineString([(bounds[0], bounds[3]), (bounds[2], bounds[3])])
    elif side == "south":
        line = LineString([(bounds[0], bounds[1]), (bounds[2], bounds[1])])
    elif side == "east":
        line = LineString([(bounds[2], bounds[1]), (bounds[2], bounds[3])])
    elif side == "west":
        line = LineString([(bounds[0], bounds[1]), (bounds[0], bounds[3])])
    else:
        line = LineString([(bounds[0], bounds[3]), (bounds[2], bounds[3])])

    buffered = line.buffer(buffer_m, cap_style=2)
    clipped = buffered.intersection(parcel)
    if clipped.is_empty:
        clipped = buffered

    return ConstraintArea(
        name=f"watercourse_{side}",
        geometry=clipped,
        deductible=True,
        buffer_m=0,  # Already buffered
        source="HRM LUB",
    )


def add_constraint_wetland(parcel: Polygon, center: tuple[float, float] = None,
                            radius: float = 40.0, buffer_m: float = 30.0) -> ConstraintArea:
    """Add a wetland constraint (circular no-build zone with buffer)."""
    if center is None:
        center = (parcel.centroid.x, parcel.centroid.y)

    wetland = Point(center).buffer(radius)
    wetland_in_parcel = wetland.intersection(parcel)
    if wetland_in_parcel.is_empty:
        wetland_in_parcel = wetland

    return ConstraintArea(
        name="wetland",
        geometry=wetland_in_parcel,
        deductible=True,
        buffer_m=buffer_m,
        source="HRM LUB",
    )


# ── Main Pipeline ─────────────────────────────────────────────────────────

def run_subdivision(parcel: Polygon, rules: LayoutRules,
                    access_points: list[AccessPoint],
                    constraint_areas: list[ConstraintArea] = None,
                    patterns: list[RoadPattern] = None,
                    road_length: float = None) -> list[LayoutResult]:
    """Full pipeline: generate → check → score → rank."""
    constraint_areas = constraint_areas or []
    patterns = patterns or [RoadPattern.SINGLE_ROAD, RoadPattern.CUL_DE_SAC,
                            RoadPattern.T_ROAD, RoadPattern.SPINE_BRANCH]

    # Create Parcel object
    p = Parcel(
        geometry=parcel,
        access_points=access_points,
        constraint_areas=constraint_areas,
    )

    # Generate layouts
    generator = LayoutGenerator(p, rules)
    results = []
    for pattern in patterns:
        try:
            result = generator.generate_layout(pattern, road_length)
            results.append(result)
        except Exception as e:
            print(f"  ⚠ {pattern.value} failed: {e}", file=sys.stderr)
            continue

    # Check and score
    checker = LotChecker(rules, constraint_areas)
    scorer = LayoutScorer(rules)

    checked = []
    for result in results:
        result = checker.check_layout(result)
        result = scorer.score_layout(result)
        checked.append(result)

    # Rank by total score
    checked.sort(key=lambda r: r.score.total_score, reverse=True)

    return checked


def parse_args():
    parser = argparse.ArgumentParser(
        description="Subdivision concept layout optimizer — 2D lot-and-road generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Parcel input
    parser.add_argument("--parcel", default="300x200",
                        help="Parcel dimensions as WxH (e.g. 300x200). "
                             "Use coords for irregular: '0,0;300,0;280,200;0,180'")
    parser.add_argument("--zone", default="R-2",
                        help="HRM zone code (default: R-2)")
    parser.add_argument("--servicing", default="serviced",
                        choices=["serviced", "serviced_water_only", "unserviced",
                                 "unserviced_bedrock", "small_lot_variance"],
                        help="Servicing assumption")
    parser.add_argument("--road-type", default="local_residential",
                        help="Road type from HRM standards")
    parser.add_argument("--conditions", default="",
                        help="Comma-separated conditions: watercourse_river,wetland,steep_slope")
    parser.add_argument("--access", default=None,
                        help="Access point: x,y,direction (e.g. 0,100,east)")
    parser.add_argument("--road-length", type=float, default=None,
                        help="Override road length in metres")
    parser.add_argument("--patterns", default=None,
                        help="Comma-separated patterns: existing_road,single_road,cul_de_sac,loop_road,t_road,spine_branch")
    parser.add_argument("--lot-width", type=float, default=None,
                        help="Target lot width in metres")
    parser.add_argument("--lot-depth", type=float, default=None,
                        help="Target lot depth in metres")

    # Output
    parser.add_argument("--export", default="summary",
                        help="Export formats: summary,geojson,dxf,json (comma-separated)")
    parser.add_argument("--output-dir", default="output",
                        help="Output directory")

    return parser.parse_args()


def main():
    args = parse_args()

    # ── Build parcel ──
    if "x" in args.parcel and ";" not in args.parcel:
        # Rectangular parcel: WxH
        w, h = map(float, args.parcel.lower().split("x"))
        parcel = make_rectangular_parcel(w, h)
        print(f"Parcel: {w:.0f}m × {h:.0f}m = {parcel.area:.0f} m² ({parcel.area/10000:.2f} ha)")
    else:
        # Irregular polygon from coordinates
        coords = []
        for pair in args.parcel.split(";"):
            x, y = map(float, pair.split(","))
            coords.append((x, y))
        parcel = make_irregular_parcel(coords)
        print(f"Parcel: {parcel.area:.0f} m² ({parcel.area/10000:.2f} ha)")

    # ── Load constraints ──
    engine = ConstraintEngine(municipality="hrm")
    pc = engine.resolve(args.zone, args.servicing, args.road_type)
    rules = LayoutRules.from_constraint_engine(pc)

    # Override with CLI args
    if args.lot_width:
        rules.lot_width_target = args.lot_width
    if args.lot_depth:
        rules.lot_depth_target = args.lot_depth

    print(f"\nRules: {args.zone} + {args.servicing}")
    print(f"  Min lot area: {rules.min_lot_area:.0f} m²")
    print(f"  Min frontage: {rules.min_frontage:.1f} m")
    print(f"  Min depth: {rules.min_depth:.1f} m")
    print(f"  ROW width: {rules.row_width:.1f} m")
    print(f"  Service type: {rules.service_type.value}")

    # ── Access point ──
    bounds = parcel.bounds
    if args.access:
        parts = args.access.split(",")
        ax, ay = float(parts[0]), float(parts[1])
        adir = parts[2] if len(parts) > 2 else "east"
        access = make_access_point(ax, ay, adir)
    else:
        # Default: center of south boundary, facing north
        mid_x = (bounds[0] + bounds[2]) / 2
        access = make_access_point(mid_x, bounds[1], "north")

    # ── Constraints ──
    constraints = []
    if args.conditions:
        for cond in args.conditions.split(","):
            cond = cond.strip().lower()
            if cond.startswith("watercourse"):
                side = cond.split("_")[-1] if "_" in cond and cond.split("_")[-1] in ("north", "south", "east", "west") else "north"
                buffer_m = 30.0
                constraints.append(add_constraint_watercourse(parcel, side, buffer_m))
            elif cond == "wetland":
                constraints.append(add_constraint_wetland(parcel))
            # Add more condition types as needed

    if constraints:
        print(f"\nConstraints: {len(constraints)}")
        for c in constraints:
            print(f"  {c.name}: {c.geometry.area:.0f} m²")

    # ── Patterns ──
    pattern_map = {p.value: p for p in RoadPattern}
    if args.patterns:
        patterns = [pattern_map[p.strip()] for p in args.patterns.split(",")
                     if p.strip() in pattern_map]
    else:
        patterns = [RoadPattern.SINGLE_ROAD, RoadPattern.CUL_DE_SAC,
                    RoadPattern.T_ROAD, RoadPattern.SPINE_BRANCH]

    print(f"\nGenerating {len(patterns)} layout patterns: {', '.join(p.value for p in patterns)}")

    # ── Run ──
    results = run_subdivision(
        parcel=parcel,
        rules=rules,
        access_points=[access],
        constraint_areas=constraints,
        patterns=patterns,
        road_length=args.road_length,
    )

    # ── Output ──
    print("\n" + "=" * 70)
    print(export_summary(results))

    # Detailed lot info for best layout
    if results:
        best = results[0]
        print(f"\n{'─' * 70}")
        print(f"LOT DETAILS — Option {best.name} (recommended)")
        print(f"{'─' * 70}")
        for lot in best.lots:
            status = "✓" if lot.passes_all else "✗"
            print(f"  Lot {lot.id:>3} [{lot.lot_type.value:>10}] {status} "
                  f"Area={lot.area:>7.0f}m²  Front={lot.frontage:>5.1f}m  "
                  f"Depth={lot.depth:>5.1f}m  Shape={lot.shape_quality:.2f}  "
                  f"{'  '.join(lot.constraint_conflicts) if lot.constraint_conflicts else ''}")

    # Export
    export_formats = args.export.split(",")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    for fmt in export_formats:
        fmt = fmt.strip().lower()
        if fmt == "geojson" and results:
            for r in results:
                path = output_dir / f"layout_{r.name}_{r.pattern.value}.geojson"
                export_geojson(r, str(path))
                print(f"  Exported: {path}")
        elif fmt == "dxf" and results:
            for r in results:
                path = output_dir / f"layout_{r.name}_{r.pattern.value}.dxf"
                try:
                    export_dxf(r, str(path))
                    print(f"  Exported: {path}")
                except Exception as e:
                    print(f"  DXF export failed: {e}")
        elif fmt == "json" and results:
            for r in results:
                path = output_dir / f"layout_{r.name}_{r.pattern.value}.json"
                layout_result_to_json(r, str(path))
                print(f"  Exported: {path}")

    return results


if __name__ == "__main__":
    main()