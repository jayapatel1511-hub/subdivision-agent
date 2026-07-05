"""
Subdivision Agent — Export Module.

Export layout results to DXF and GeoJSON for import into Civil 3D / QGIS / etc.
"""

from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import mapping

from models import LayoutResult, Lot, RoadSegment, LotType, layout_result_to_dict

def export_geojson(result: LayoutResult, path: str = None) -> dict:
    """Export a LayoutResult as GeoJSON FeatureCollection.

    Each lot and road is a Feature with properties including
    area, frontage, compliance, and type.
    """
    features = []

    # Lots
    for lot in result.lots:
        geom = mapping(lot.geometry)
        feature = {
            "type": "Feature",
            "geometry": geom,
            "properties": {
                "layer": "lots",
                "lot_id": lot.id,
                "lot_type": lot.lot_type.value,
                "is_residential": lot.is_residential,
                "area_sqm": round(lot.area, 1),
                "frontage_m": round(lot.frontage, 1),
                "depth_m": round(lot.depth, 1),
                "width_min_m": round(lot.width_min, 1),
                "shape_quality": round(lot.shape_quality, 3),
                "passes_all": lot.passes_all if lot.is_residential else None,
                "passes_area": lot.passes_area if lot.is_residential else None,
                "passes_frontage": lot.passes_frontage if lot.is_residential else None,
                "passes_depth": lot.passes_depth if lot.is_residential else None,
                "passes_shape": lot.passes_shape if lot.is_residential else None,
                "passes_buildable": lot.passes_buildable if lot.is_residential else None,
                "passes_service": lot.passes_service if lot.is_residential else None,
                "constraint_conflicts": lot.constraint_conflicts,
                "warnings": lot.warnings,
            }
        }
        features.append(feature)

        # Buildable envelope (if available)
        if lot.buildable_envelope:
            env_geom = mapping(lot.buildable_envelope)
            features.append({
                "type": "Feature",
                "geometry": env_geom,
                "properties": {
                    "layer": "buildable_envelopes",
                    "lot_id": lot.id,
                    "type": "buildable_envelope",
                    "area_sqm": round(lot.buildable_envelope.area, 1),
                }
            })

    # Roads
    for i, road in enumerate(result.roads):
        road_geom = mapping(road.row_polygon)
        features.append({
            "type": "Feature",
            "geometry": road_geom,
            "properties": {
                "layer": "roads",
                "road_id": i,
                "name": road.name,
                "road_type": road.road_type,
                "row_width_m": road.row_width,
                "is_cul_de_sac": road.is_cul_de_sac,
                "is_future_stub": road.is_future_stub,
                "length_m": round(road.length, 1),
                "area_sqm": round(road.area, 1),
            }
        })
        # Also export centerline
        cl_geom = mapping(road.centerline)
        features.append({
            "type": "Feature",
            "geometry": cl_geom,
            "properties": {
                "layer": "road_centerlines",
                "road_id": i,
                "name": road.name,
            }
        })

    # Frontage lines
    for lot in result.lots:
        if lot.frontage_line and not lot.frontage_line.is_empty:
            fl_geom = mapping(lot.frontage_line)
            features.append({
                "type": "Feature",
                "geometry": fl_geom,
                "properties": {
                    "layer": "frontage_lines",
                    "lot_id": lot.id,
                    "frontage_m": round(lot.frontage, 1),
                }
            })

    geojson = {
        "type": "FeatureCollection",
        "features": features,
        "properties": {
            "name": result.name,
            "pattern": result.pattern.value,
            "total_lots": result.total_lots,
            "residential_lots": len(result.residential_lots),
            "remainder_lots": len(result.remainder_lots),
            "passing_lots": result.passing_lots,
            "failed_lots": result.failed_lots,
            "gross_area_sqm": round(result.gross_area, 1),
            "road_area_sqm": round(result.road_area, 1),
            "constraint_area_sqm": round(result.constraint_area, 1),
            "passing_lot_area_sqm": round(result.passing_lot_area, 1),
            "failing_lot_area_sqm": round(result.failing_lot_area, 1),
            "remainder_area_sqm": round(result.remainder_area, 1),
            "saleable_land_pct": round(result.saleable_land_pct, 1),
            "developable_used_pct": round(result.developable_used_pct, 1),
            "score": round(result.score.total_score, 1),
        }
    }

    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(geojson, f, indent=2)

    return geojson


def export_dxf(result: LayoutResult, path: str = None) -> str:
    """Export a LayoutResult as DXF for Civil 3D import.

    Layers:
    - LOTS: lot boundaries
    - LOT_NUMBERS: lot ID labels at centroid
    - ROADS: road ROW polygons
    - ROAD_CL: road centerlines
    - FRONTAGE: frontage lines
    - BUILDABLE: buildable envelopes
    - REMAINDER: remainder lot boundaries (yellow dashed)
    """
    import ezdxf
    from ezdxf.enums import TextEntityAlignment

    doc = ezdxf.new(dxfversion='R2018')
    msp = doc.modelspace()

    # Create layers
    for layer_name, color in [
        ('LOTS', 1),          # Red
        ('LOT_NUMBERS', 7),   # White
        ('ROADS', 5),         # Blue
        ('ROAD_CL', 3),       # Green
        ('FRONTAGE', 6),      # Magenta
        ('BUILDABLE', 2),     # Yellow
        ('PARCEL', 8),        # Dark grey
        ('REMAINDER', 40),    # Orange
    ]:
        doc.layers.add(name=layer_name, color=color)

    # Lot boundaries and labels
    for lot in result.lots:
        coords = list(lot.geometry.exterior.coords)
        layer = 'REMAINDER' if lot.lot_type == LotType.REMAINDER else 'LOTS'
        msp.add_lwpolyline(coords, close=True, dxfattribs={'layer': layer})

        # Lot number at centroid
        centroid = lot.geometry.centroid
        label = f"L{lot.id}"
        if lot.is_residential and not lot.passes_all:
            label += " ✗"
        elif lot.lot_type == LotType.REMAINDER:
            label += " R"
        msp.add_text(label, dxfattribs={
            'layer': 'LOT_NUMBERS',
            'height': 2.0,
            'insert': (centroid.x, centroid.y, 0),
        })

        # Buildable envelope
        if lot.buildable_envelope:
            env_coords = list(lot.buildable_envelope.exterior.coords)
            msp.add_lwpolyline(env_coords, close=True, dxfattribs={'layer': 'BUILDABLE'})

    # Frontage lines
    for lot in result.lots:
        if lot.frontage_line and not lot.frontage_line.is_empty:
            coords = list(lot.frontage_line.coords)
            msp.add_lwpolyline(coords, close=False, dxfattribs={'layer': 'FRONTAGE'})

    # Road ROW polygons and centerlines
    for road in result.roads:
        row_coords = list(road.row_polygon.exterior.coords)
        msp.add_lwpolyline(row_coords, close=True, dxfattribs={'layer': 'ROADS'})

        # Centerline
        cl_coords = list(road.centerline.coords)
        msp.add_lwpolyline(cl_coords, close=False, dxfattribs={'layer': 'ROAD_CL'})

    # Save
    if path:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        doc.saveas(path)

    # Return summary text
    res_count = len(result.residential_lots)
    rem_count = len(result.remainder_lots)
    return f"DXF exported: {res_count} residential lots, {rem_count} remainders, {len(result.roads)} roads"


def export_summary(results: list[LayoutResult]) -> str:
    """Generate a text comparison of multiple layout options."""
    lines = ["═" * 70, "SUBDIVISION LAYOUT COMPARISON", "═" * 70, ""]

    # Header
    lines.append(
        f"{'Option':<10} {'Pattern':<16} {'Res':>4} {'Pass':>4} {'Fail':>4} "
        f"{'Rem':>4} {'Road(m)':>8} {'Sale%':>6} {'Dev%':>5} {'Score':>7}"
    )
    lines.append("─" * 70)

    for r in results:
        lines.append(
            f"{r.name:<10} {r.pattern.value:<16} {len(r.residential_lots):>4} {r.passing_lots:>4} "
            f"{r.failed_lots:>4} {len(r.remainder_lots):>4} {r.total_road_length:>8.0f} "
            f"{r.saleable_land_pct:>5.1f}% {r.developable_used_pct:>4.1f}% "
            f"{r.score.total_score:>7.1f}"
        )

    lines.append("")
    lines.append("═" * 70)

    # Top recommendation
    if results:
        best = results[0]
        lines.append("")
        lines.append(f"★ RECOMMENDED: Option {best.name}")
        lines.append(best.summary())
        if best.score.explanation:
            lines.append("")
            lines.append(best.score.explanation)

    # Warnings for all options
    all_warnings = []
    for r in results:
        for w in r.warnings:
            all_warnings.append((r.name, w))

    if all_warnings:
        lines.append("")
        lines.append("⚠ WARNINGS:")
        for name, w in all_warnings[:10]:
            lines.append(f"  Option {name}: [{w.level.value}] {w.message}")

    return "\n".join(lines)