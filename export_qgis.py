"""
Subdivision Agent — QGIS Export Module.

Produces a portable QGIS project folder:
  - Per-layer GeoJSON files (with CRS)
  - QML style files (one per layer)
  - .qgz project file (zip containing project.qgs XML)

The engine stays pure Python; QGIS is the renderer.
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from shapely.geometry import mapping

from models import LayoutResult, Lot, LotType, Parcel


# Layer draw order (bottom to top)
LAYER_ORDER = [
    "parcel_boundary",
    "roads",
    "road_centerlines",
    "remainders",
    "lots_failing",
    "lots_passing",
    "buildable_envelopes",
    "frontage_lines",
]

# Geometry type per layer (QGIS provider geometry attribute)
GEOMETRY_TYPE = {
    "parcel_boundary": "Polygon",
    "roads": "Polygon",
    "road_centerlines": "Line",
    "remainders": "Polygon",
    "lots_failing": "Polygon",
    "lots_passing": "Polygon",
    "buildable_envelopes": "Polygon",
    "frontage_lines": "Line",
}

DEFAULT_CRS = 2961  # NAD83(CSRS) / UTM zone 20N (Nova Scotia)


# ── GeoJSON builders ─────────────────────────────────────────────────────────

def _feature(geom, properties: dict) -> dict:
    return {
        "type": "Feature",
        "geometry": mapping(geom),
        "properties": properties,
    }


def _feature_collection(features: list, crs: int, bbox=None) -> dict:
    fc = {
        "type": "FeatureCollection",
        "crs": {
            "type": "name",
            "properties": {"name": f"urn:ogc:def:crs:EPSG::{crs}"},
        },
        "features": features,
    }
    if bbox is not None:
        fc["bbox"] = list(bbox)
    return fc


def _lot_props(lot: Lot) -> dict:
    return {
        "lot_id": lot.id,
        "lot_type": lot.lot_type.value,
        "area_sqm": round(lot.area, 2),
        "frontage_m": round(lot.frontage, 2),
        "depth_m": round(lot.depth, 2),
        "width_min_m": round(lot.width_min, 2),
        "shape_quality": round(lot.shape_quality, 4),
        "passes_area": lot.passes_area,
        "passes_frontage": lot.passes_frontage,
        "passes_depth": lot.passes_depth,
        "passes_shape": lot.passes_shape,
        "passes_buildable": lot.passes_buildable,
        "passes_service": lot.passes_service,
        "passes_all": lot.passes_all,
    }


def _build_layer_features(result: LayoutResult, parcel: Parcel | None,
                           layer: str) -> list:
    """Return the list of GeoJSON features for a single layer."""
    feats: list = []

    if layer in ("lots_passing", "lots_failing"):
        want_passing = layer == "lots_passing"
        for lot in result.residential_lots:
            if want_passing and not lot.passes_all:
                continue
            if not want_passing and lot.passes_all:
                continue
            feats.append(_feature(lot.geometry, _lot_props(lot)))

    elif layer == "remainders":
        for lot in result.remainder_lots:
            feats.append(_feature(lot.geometry, {
                "lot_id": lot.id,
                "lot_type": lot.lot_type.value,
                "area_sqm": round(lot.area, 2),
                "frontage_m": round(lot.frontage, 2),
                "shape_quality": round(lot.shape_quality, 4),
            }))

    elif layer == "roads":
        for i, road in enumerate(result.roads):
            feats.append(_feature(road.row_polygon, {
                "road_id": i,
                "name": road.name or f"Road {i+1}",
                "road_type": road.road_type,
                "row_width_m": road.row_width,
                "length_m": round(road.length, 2),
                "area_sqm": round(road.area, 2),
            }))

    elif layer == "road_centerlines":
        for i, road in enumerate(result.roads):
            feats.append(_feature(road.centerline, {
                "road_id": i,
                "name": road.name or f"Road {i+1}",
                "length_m": round(road.length, 2),
            }))

    elif layer == "frontage_lines":
        for lot in result.lots:
            if lot.frontage_line and not lot.frontage_line.is_empty:
                feats.append(_feature(lot.frontage_line, {
                    "lot_id": lot.id,
                    "frontage_m": round(lot.frontage, 2),
                }))

    elif layer == "buildable_envelopes":
        for lot in result.lots:
            if lot.buildable_envelope and not lot.buildable_envelope.is_empty:
                feats.append(_feature(lot.buildable_envelope, {
                    "lot_id": lot.id,
                    "area_sqm": round(lot.buildable_envelope.area, 2),
                }))

    elif layer == "parcel_boundary":
        if parcel is not None and parcel.geometry is not None:
            feats.append(_feature(parcel.geometry, {
                "pid": parcel.pid,
                "zone_code": parcel.zone_code,
                "area_sqm": round(parcel.geometry.area, 2),
            }))

    return feats


# ── QML style templates ──────────────────────────────────────────────────────

def _fill_symbol(name, color, outline_color, outline_width,
                 style="solid", outline_style=None, outline_dash=None):
    props = [
        f'<prop k="color" v="{color}"/>',
        f'<prop k="outline_color" v="{outline_color}"/>',
        f'<prop k="outline_width" v="{outline_width}"/>',
        f'<prop k="style" v="{style}"/>',
    ]
    if outline_style:
        props.append(f'<prop k="outline_style" v="{outline_style}"/>')
    if outline_dash:
        props.append(f'<prop k="outline_dash_pattern" v="{outline_dash}"/>')
    return (
        f'<symbol type="fill" name="{name}">'
        f'<layer class="SimpleFill" enabled="1" locked="0">'
        f'{"".join(props)}'
        f'</layer></symbol>'
    )


def _line_symbol(name, color, width, dash=None):
    props = [
        f'<prop k="line_color" v="{color}"/>',
        f'<prop k="line_width" v="{width}"/>',
        f'<prop k="line_style" v="{"dash" if dash else "solid"}"/>',
    ]
    if dash:
        props.append(f'<prop k="dash_pattern" v="{dash}"/>')
    return (
        f'<symbol type="line" name="{name}">'
        f'<layer class="SimpleLine" enabled="1" locked="0">'
        f'{"".join(props)}'
        f'</layer></symbol>'
    )


def _label_rule(expression, field_name="lot_id"):
    """Build a QGIS label block."""
    return (
        '<labeling type="rule-based">'
        '<rule description="label" key="{label}">'
        '<settings>'
        '<text-style fontFamily="Sans Serif" fontSize="8" '
        f'namedStyle="Normal" fontColor="0,0,0,255"/>'
        '<placement placement="centroid"/>'
        f'<fields><field name="{field_name}"/></fields>'
        '</settings>'
        '</rule>'
        '</labeling>'
    )


def _qml(renderer_xml: str, labeling_xml: str = "") -> str:
    return (
        '<!DOCTYPE qgis PUBLIC \'http://mrcc.com/qgis.dtd\' \'SYSTEM\'>\n'
        '<qgis version="3.28">\n'
        f'{renderer_xml}\n'
        f'{labeling_xml}\n'
        '</qgis>'
    )


def _qml_for_layer(layer: str) -> str:
    """Return the QML style XML string for a given layer name."""
    if layer == "lots_passing":
        sym = _fill_symbol("passing", "134,219,108,180",
                           "56,142,60,255", "0.8")
        renderer = (
            '<renderer-v2 type="singleSymbol" symbollevels="0">'
            f'<symbols>{sym}</symbols></renderer-v2>'
        )
        labeling = _label_rule(
            '\'L\' || "lot_id" || COALESCE(CASE WHEN NOT "passes_all" '
            'THEN \' \\u2717\' ELSE \'\' END, \'\')'
        )
        return _qml(renderer, labeling)

    if layer == "lots_failing":
        sym = _fill_symbol("failing", "244,108,88,180",
                           "183,28,28,255", "1.0")
        renderer = (
            '<renderer-v2 type="singleSymbol" symbollevels="0">'
            f'<symbols>{sym}</symbols></renderer-v2>'
        )
        labeling = _label_rule(
            '\'L\' || "lot_id" || COALESCE(CASE WHEN NOT "passes_all" '
            'THEN \' \\u2717\' ELSE \'\' END, \'\')'
        )
        return _qml(renderer, labeling)

    if layer == "remainders":
        sym = _fill_symbol("remainder", "255,167,38,120",
                           "230,126,34,255", "0.6",
                           outline_style="dash", outline_dash="4;2")
        renderer = (
            '<renderer-v2 type="singleSymbol" symbollevels="0">'
            f'<symbols>{sym}</symbols></renderer-v2>'
        )
        labeling = _label_rule('\'R\' || "lot_id"')
        return _qml(renderer, labeling)

    if layer == "roads":
        sym = _fill_symbol("roads", "66,133,244,200",
                           "25,78,163,255", "1.2")
        renderer = (
            '<renderer-v2 type="singleSymbol" symbollevels="0">'
            f'<symbols>{sym}</symbols></renderer-v2>'
        )
        return _qml(renderer)

    if layer == "road_centerlines":
        sym = _line_symbol("centerline", "25,78,163,255", "1.0", dash="8;4")
        renderer = (
            '<renderer-v2 type="singleSymbol" symbollevels="0">'
            f'<symbols>{sym}</symbols></renderer-v2>'
        )
        return _qml(renderer)

    if layer == "frontage_lines":
        sym = _line_symbol("frontage", "216,27,96,255", "1.5")
        renderer = (
            '<renderer-v2 type="singleSymbol" symbollevels="0">'
            f'<symbols>{sym}</symbols></renderer-v2>'
        )
        return _qml(renderer)

    if layer == "buildable_envelopes":
        sym = _fill_symbol("buildable", "255,235,59,80",
                           "255,193,7,200", "0.5",
                           outline_style="dash", outline_dash="3;2")
        renderer = (
            '<renderer-v2 type="singleSymbol" symbollevels="0">'
            f'<symbols>{sym}</symbols></renderer-v2>'
        )
        return _qml(renderer)

    if layer == "parcel_boundary":
        sym = _fill_symbol("parcel", "0,0,0,0",
                           "97,97,97,255", "2.0",
                           style="no")
        renderer = (
            '<renderer-v2 type="singleSymbol" symbollevels="0">'
            f'<symbols>{sym}</symbols></renderer-v2>'
        )
        return _qml(renderer)

    return _qml(
        '<renderer-v2 type="singleSymbol" symbollevels="0">'
        '<symbols><symbol type="fill" name="default">'
        '<layer class="SimpleFill" enabled="1" locked="0">'
        '<prop k="color" v="200,200,200,200"/>'
        '<prop k="outline_color" v="100,100,100,255"/>'
        '<prop k="outline_width" v="0.5"/>'
        '<prop k="style" v="solid"/>'
        '</layer></symbol></symbols></renderer-v2>'
    )


# ── QGS project XML ──────────────────────────────────────────────────────────

def _qgs_layer_xml(layer: str, crs: int, extent) -> str:
    """Build a <maplayer> entry for one layer."""
    geom = GEOMETRY_TYPE.get(layer, "Polygon")
    minx, miny, maxx, maxy = extent
    layer_id = f"{layer}_layer"
    return (
        '<maplayer minimumSize="0" simplifyDrawingTol="1" '
        f'type="vector" name="{layer}" '
        f'geometry="{geom}" layerid="{layer_id}" '
        'provider="ogr" autoRefreshMode="Disabled" refreshOnNotifyEnabled="0" '
        'maxScale="0" minScale="1e+08" readOnly="1" hasScaleBasedVisibilityFlag="0">'
        f'<id>{layer_id}</id>'
        f'<datasource>./{layer}.geojson</datasource>'
        f'<stylesheet>./{layer}.qml</stylesheet>'
        '<extent>'
        f'<xmin>{minx}</xmin><ymin>{miny}</ymin>'
        f'<xmax>{maxx}</xmax><ymax>{maxy}</ymax>'
        '</extent>'
        '<crs><spatialrefsys>'
        f'<wkt>EPSG:{crs}</wkt>'
        f'<srid>{crs}</srid>'
        f'<authid>EPSG:{crs}</authid>'
        '</spatialrefsys></crs>'
        '</maplayer>'
    )


def _qgs_xml(layers: list, crs: int, extent) -> str:
    """Build the full project.qgs XML string."""
    minx, miny, maxx, maxy = extent
    layer_xml = "\n".join(_qgs_layer_xml(l, crs, extent) for l in layers)
    layer_tree = "\n".join(
        f'<layer-tree-layer name="{l}" id="{l}_layer" source="./{l}.geojson"/>'
        for l in layers
    )
    return (
        '<!DOCTYPE qgis PUBLIC \'http://mrcc.com/qgis.dtd\' \'SYSTEM\'>\n'
        '<qgis version="3.28" projectname="Subdivision Layout">\n'
        '<projecttitle>Subdivision Layout</projecttitle>\n'
        '<crs><spatialrefsys>'
        f'<wkt>EPSG:{crs}</wkt>'
        f'<srid>{crs}</srid>'
        f'<authid>EPSG:{crs}</authid>'
        '</spatialrefsys></crs>\n'
        '<extent>'
        f'<xmin>{minx}</xmin><ymin>{miny}</ymin>'
        f'<xmax>{maxx}</xmax><ymax>{maxy}</ymax>'
        '</extent>\n'
        f'<projectlayers>\n{layer_xml}\n</projectlayers>\n'
        f'<layer-tree-group>\n{layer_tree}\n</layer-tree-group>\n'
        '</qgis>'
    )


# ── Main entry point ─────────────────────────────────────────────────────────

def export_qgis(result: LayoutResult, path: str,
                parcel: Parcel | None = None,
                crs: int | None = None) -> str:
    """Export a LayoutResult as a QGIS project folder.

    Creates:
      {path}/                (folder)
        {name}.qgz           (zip with project.qgs)
        {layer}.geojson      (one per layer)
        {layer}.qml          (one per layer)

    Returns the path to the .qgz file.
    """
    if crs is None:
        crs = (parcel.working_crs if parcel is not None else DEFAULT_CRS)

    out_dir = Path(path)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Compute parcel bounds for extent. Prefer parcel geometry; fall back
    # to the union of all lot + road geometries in the result.
    if parcel is not None and parcel.geometry is not None:
        bounds = parcel.geometry.bounds
    elif result.lots:
        from shapely.ops import unary_union
        geoms = [l.geometry for l in result.lots if l.geometry is not None]
        geoms += [r.row_polygon for r in result.roads]
        if geoms:
            bounds = unary_union(geoms).bounds
        else:
            bounds = (0.0, 0.0, 0.0, 0.0)
    else:
        bounds = (0.0, 0.0, 0.0, 0.0)

    # Write per-layer GeoJSON + QML
    written_layers = []
    for layer in LAYER_ORDER:
        feats = _build_layer_features(result, parcel, layer)
        # Skip parcel_boundary if no parcel supplied
        if layer == "parcel_boundary" and not feats:
            continue
        fc = _feature_collection(feats, crs, bbox=bounds)
        geojson_path = out_dir / f"{layer}.geojson"
        with open(geojson_path, "w") as f:
            json.dump(fc, f, indent=2)

        qml_path = out_dir / f"{layer}.qml"
        with open(qml_path, "w") as f:
            f.write(_qml_for_layer(layer))

        written_layers.append(layer)

    # Build and zip the QGS project
    qgs = _qgs_xml(written_layers, crs, bounds)
    qgz_path = out_dir / f"{out_dir.name}.qgz"
    with zipfile.ZipFile(qgz_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.qgs", qgs)

    return str(qgz_path)