"""
Subdivision Agent — Data Models.

Clean 2D concept-layout objects. No pipes, no profiles, no grading.
Just parcel, rules, lots, roads, and scoring.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from shapely.geometry import Polygon, MultiPolygon, LineString, Point, MultiLineString, MultiPoint
from shapely.ops import unary_union

# ── Geometry Helpers (polygon-native) ───────────────────────────────────────

def poly_area(geom) -> float:
    """Area of a polygon or multi-polygon."""
    if geom is None or geom.is_empty:
        return 0.0
    return geom.area

def poly_intersects(a, b) -> bool:
    """Do two geometries intersect?"""
    if a is None or b is None or a.is_empty or b.is_empty:
        return False
    return a.intersects(b)

def poly_difference(a, b):
    """Subtract b from a. Returns None if result is empty."""
    if a is None or b is None or a.is_empty:
        return a
    result = a.difference(b)
    if result.is_empty:
        return None
    return result

def poly_union(geoms: list):
    """Union of multiple geometries."""
    if not geoms:
        return Polygon()
    return unary_union(geoms)

def poly_buffer(line, width, cap_style=2, join_style=2):
    """Buffer a line by width (half on each side)."""
    return line.buffer(width, cap_style=cap_style, join_style=join_style)

def frontage_length(lot, road_row, tolerance: float = 0.6) -> float:
    """Length of the lot's boundary that abuts the road ROW polygon.

    This is the *legal* frontage — the length of the lot line shared with
    (or within `tolerance` of) the road right-of-way. Lots are carved with a
    small 0.5 m offset from the ROW, so an exact `lot.intersection(row)`
    would be empty; we therefore measure the portion of the lot's boundary
    that falls within `tolerance` of the ROW polygon. A lot with no boundary
    near any ROW (landlocked) returns 0.0, making such lots self-detecting.
    """
    if lot is None or road_row is None or lot.is_empty or road_row.is_empty:
        return 0.0
    try:
        boundary = lot.boundary
        if boundary is None or boundary.is_empty:
            return 0.0
        # Portion of the lot boundary lying within `tolerance` of the ROW.
        near = boundary.intersection(road_row.buffer(tolerance))
        if near.is_empty:
            return 0.0
        if isinstance(near, LineString):
            return near.length
        if isinstance(near, (MultiLineString, MultiPoint)):
            return sum(g.length for g in near.geoms if hasattr(g, 'length'))
        # Point or other degenerate — negligible frontage
        return 0.0
    except Exception:
        return 0.0

def compactness(poly) -> float:
    """4πA/P² — 1.0 = circle, ~0.787 = square, <0.35 = noodle."""
    if poly is None or poly.is_empty:
        return 0.0
    area = poly.area
    perimeter = poly.length
    if perimeter <= 0:
        return 0.0
    return (4 * 3.14159265 * area) / (perimeter ** 2)

def split_polygon(polygon, line) -> list[Polygon]:
    """Split a polygon by a line, returning the resulting pieces."""
    try:
        result = split(polygon, line)
        polys = []
        for geom in result.geoms:
            if isinstance(geom, Polygon) and not geom.is_empty:
                polys.append(geom)
        return polys
    except Exception:
        return [polygon] if isinstance(polygon, Polygon) else []

def minimum_rotated_rectangle_area(poly) -> float:
    """Area of the minimum rotated rectangle that bounds this polygon."""
    if poly is None or poly.is_empty:
        return 0.0
    return poly.minimum_rotated_rectangle.area

# ── Enums ──────────────────────────────────────────────────────────────────

class ServiceType(str, Enum):
    MUNICIPAL_WATER_SEWER = "municipal_water_sewer"
    MUNICIPAL_WATER_SEPTIC = "municipal_water_septic"
    WELL_SEPTIC = "well_septic"
    FUTURE_MUNICIPAL = "future_municipal"
    UNKNOWN = "unknown"

class RoadPattern(str, Enum):
    EXISTING_ROAD = "existing_road"        # lots along existing road, no new road
    SINGLE_ROAD = "single_road"            # one internal road
    CUL_DE_SAC = "cul_de_sac"              # single road with bulb
    LOOP_ROAD = "loop_road"                 # connected loop
    T_ROAD = "t_road"                      # T-intersection internal road
    SPINE_BRANCH = "spine_branch"          # spine road with side branches
    CLUSTER = "cluster"                     # cluster layout around common space
    LARGE_LOT_RURAL = "large_lot_rural"     # rural, well-separated lots

class LayoutGoal(str, Enum):
    MAXIMIZE_LOTS = "maximize_lots"
    MAXIMIZE_QUALITY = "maximize_quality"
    MAXIMIZE_LOTS_WITH_GOOD_QUALITY = "maximize_lots_with_good_quality"
    PRESERVE_AREA = "preserve_area"

class LotType(str, Enum):
    RESIDENTIAL = "residential"     # A normal lot carved from developable area
    CORNER = "corner"               # Corner lot (frontage on two roads)
    REMAINDER = "remainder"          # Leftover developable area not in a generated lot
    ROAD_ROW = "road_row"           # Road right-of-way polygon (not a lot)
    CONSTRAINT = "constraint"        # Constraint area polygon (not a lot)
    OPEN_SPACE = "open_space"       # Dedicated open space (not a lot)
    IRREGULAR = "irregular"         # Lot that fails shape quality check but is residential

class WarningLevel(str, Enum):
    INFO = "info"
    CAUTION = "caution"
    FAIL = "fail"

class ParcelShape(str, Enum):
    """Shape classification for dispatch in the generator."""
    RECTANGLE = "rectangle"
    CONVEX = "convex"
    CONCAVE = "concave"
    L_SHAPE = "l_shape"
    CORRIDOR = "corridor"
    MULTI_PART = "multi_part"

# ── Core Geometric Objects ──────────────────────────────────────────────────

@dataclass
class AccessPoint:
    """Where the parcel connects to an existing road."""
    point: tuple[float, float]        # (x, y)
    direction: tuple[float, float]    # unit vector pointing into parcel
    road_name: str = ""
    source: str = "geojson"           # "geojson" or "derived"

@dataclass
class ConstraintArea:
    """A no-build or restricted-build zone on the parcel."""
    name: str
    geometry: Polygon
    deductible: bool = True           # Does this reduce buildable area?
    buffer_m: float = 0.0             # Buffer width to apply around geometry
    source: str = ""                  # Regulation reference

@dataclass
class RoadSegment:
    """A 2D road centerline with ROW width."""
    centerline: LineString
    row_width: float                   # ROW width in metres
    road_type: str = "local_residential"
    is_cul_de_sac: bool = False
    is_future_stub: bool = False
    name: str = ""

    @property
    def row_polygon(self) -> Polygon:
        """Generate the ROW polygon from centerline + width."""
        return self.centerline.buffer(self.row_width / 2, cap_style=2, join_style=2)

    @property
    def length(self) -> float:
        return self.centerline.length

    @property
    def area(self) -> float:
        return self.row_polygon.area

@dataclass
class Lot:
    """A single lot in a subdivision layout."""
    id: int
    geometry: Polygon
    frontage_line: LineString           # The road-frontage edge
    road_segment_id: int = -1           # Which road serves this lot
    lot_type: LotType = LotType.RESIDENTIAL
    access_point: Optional[Point] = None
    # The road right-of-way polygon adjacent to this lot. When set,
    # `frontage` is measured as the length of the lot's boundary abutting
    # this polygon (the legal frontage), not the construction segment.
    road_row_polygon: Optional[Polygon] = None

    # Computed properties (filled by checker)
    area: float = 0.0
    frontage: float = 0.0
    depth: float = 0.0
    width_min: float = 0.0
    width_avg: float = 0.0
    buildable_envelope: Optional[Polygon] = None
    service_reserve: Optional[Polygon] = None

    # Check results
    passes_area: bool = False
    passes_frontage: bool = False
    passes_depth: bool = False
    passes_shape: bool = False
    passes_buildable: bool = False
    passes_access: bool = False
    passes_service: bool = False
    passes_all: bool = False
    constraint_conflicts: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    shape_quality: float = 0.0   # 4πA/P² — 1.0 = circle, <0.5 = noodle

    def compute_properties(self):
        """Fill in geometric properties from the polygon."""
        self.area = self.geometry.area
        # Frontage: the legal frontage is the length of the lot's boundary
        # abutting the road ROW polygon. Fall back to the construction
        # `frontage_line` length when no ROW polygon is attached (e.g. for
        # remainder lots). A lot with no ROW contact gets frontage 0.0 —
        # this makes landlocked lots self-detecting in the access check.
        if self.road_row_polygon is not None:
            self.frontage = frontage_length(self.geometry, self.road_row_polygon)
        else:
            self.frontage = self.frontage_line.length if self.frontage_line else 0.0
        # Depth / width from the minimum rotated rectangle, which reflects
        # the lot's actual orientation rather than the axis-aligned bbox or
        # the area/frontage approximation (which over-estimates depth on
        # wide shallow lots and under-estimates it on narrow deep ones).
        try:
            mrr = self.geometry.minimum_rotated_rectangle
        except Exception:
            mrr = None
        if mrr is not None and not mrr.is_empty and hasattr(mrr, 'exterior'):
            mrr_w = list(mrr.exterior.coords)
            edge_lengths = []
            for i in range(len(mrr_w) - 1):
                dx = mrr_w[i + 1][0] - mrr_w[i][0]
                dy = mrr_w[i + 1][1] - mrr_w[i][1]
                edge_lengths.append(math.hypot(dx, dy))
            if len(edge_lengths) >= 2:
                # A rectangle has two distinct side lengths (each repeated)
                self.width_min = min(edge_lengths)
                self.depth = max(edge_lengths)
            else:
                self.width_min = min(edge_lengths) if edge_lengths else 0.0
                self.depth = self.area / self.frontage if self.frontage > 0 else 0.0
        else:
            # Degenerate geometry — fall back to axis-aligned bbox
            bounds = self.geometry.bounds
            self.width_min = min(bounds[2] - bounds[0], bounds[3] - bounds[1])
            self.depth = self.area / self.frontage if self.frontage > 0 else 0.0
        # shape quality: compactness ratio (4π × area / perimeter²)
        self.shape_quality = compactness(self.geometry)

    @property
    def is_residential(self) -> bool:
        """Is this a lot type that should be checked as a residential lot?"""
        return self.lot_type in (LotType.RESIDENTIAL, LotType.CORNER, LotType.IRREGULAR)

    @property
    def is_infrastructure(self) -> bool:
        """Is this an infrastructure element (road, constraint, open space)?"""
        return self.lot_type in (LotType.ROAD_ROW, LotType.CONSTRAINT, LotType.OPEN_SPACE)

# ── Configuration Objects ───────────────────────────────────────────────────

@dataclass
class LayoutRules:
    """All regulation-derived parameters for this layout run."""
    # Lot minimums (effective — already max of zone vs servicing)
    min_lot_area: float = 460.0       # m²
    min_frontage: float = 18.0        # m
    min_depth: float = 30.0           # m
    min_width: float = 18.0           # m (typically = frontage)
    min_buildable_envelope: float = 200.0  # m² — usable area after setbacks

    # Setbacks
    front_setback: float = 6.0        # m
    rear_setback: float = 7.5         # m
    side_setback: float = 1.5         # m
    flankage_setback: float = 3.0     # m (corner lot side facing street)

    # Road
    row_width: float = 16.0           # m
    carriageway_width: float = 8.0    # m
    cul_de_sac_bulb_radius: float = 15.0  # m
    cul_de_sac_max_length: float = 200.0   # m
    sidewalk_required: bool = True
    sidewalk_width: float = 1.5       # m

    # Density
    max_density: Optional[float] = 30.0  # units/ha, None = no cap
    max_lot_coverage: float = 0.45    # %

    # Servicing
    service_type: ServiceType = ServiceType.MUNICIPAL_WATER_SEWER
    septic_reserve_pct: float = 0.0  # 0 for serviced, 0.5 for unserviced
    well_protection_radius: float = 0.0  # 0 for serviced, 30 for unserviced

    # Design preferences
    lot_width_target: float = 20.0    # m — preferred lot width
    lot_depth_target: float = 35.0    # m — preferred lot depth
    max_irregular_lot_pct: float = 0.15  # max % of lots that can be irregular
    flag_lots_allowed: bool = False
    corner_lot_frontage_reduction: float = 0.0  # % reduction for corner lots
    private_road_min_width: float = 10.0  # m (NS reg)
    open_space_dedication_pct: float = 0.05  # 5% for parkland

    # Irregular parcel feature flag
    allow_irregular_carving: bool = True  # feature flag kill switch

    # Scoring weights
    w_lot_yield: float = 1.0
    w_lot_quality: float = 0.8
    w_road_efficiency: float = 0.6
    w_constraint_avoidance: float = 0.7
    w_service_feasibility: float = 0.5
    w_future_expansion: float = 0.3
    p_irregular_lot: float = 0.4
    p_long_road: float = 0.002        # per metre
    p_approval_risk: float = 0.3      # per failed lot

    @classmethod
    def from_constraint_engine(cls, pc) -> "LayoutRules":
        """Build LayoutRules from a ParcelConstraints object."""
        # Map servicing type string → ServiceType enum
        service_map = {
            "serviced": ServiceType.MUNICIPAL_WATER_SEWER,
            "serviced_water_only": ServiceType.MUNICIPAL_WATER_SEPTIC,
            "unserviced": ServiceType.WELL_SEPTIC,
            "unserviced_bedrock": ServiceType.WELL_SEPTIC,
            "small_lot_variance": ServiceType.MUNICIPAL_WATER_SEWER,
        }
        svc = service_map.get(pc.servicing.servicing_type, ServiceType.UNKNOWN)

        # Scale lot dimensions based on constraints: targets should comfortably
        # exceed minimums so lots aren't bare-minimum slivers. Also ensure the
        # target dimensions always satisfy the minimum area requirement.
        lot_width_target = max(20.0, pc.effective_min_frontage * 1.2)
        lot_depth_target = max(35.0, pc.effective_min_depth * 1.3)

        # If width × depth still falls short of min area, bump depth to satisfy it
        if lot_width_target * lot_depth_target < pc.effective_min_lot_area:
            lot_depth_target = pc.effective_min_lot_area / lot_width_target

        return cls(
            min_lot_area=pc.effective_min_lot_area,
            min_frontage=pc.effective_min_frontage,
            min_depth=pc.effective_min_depth,
            front_setback=pc.zone.min_front_setback_m,
            rear_setback=pc.zone.min_rear_setback_m,
            side_setback=pc.zone.min_side_setback_m,
            flankage_setback=pc.zone.min_flankage_setback_m,
            row_width=pc.road.right_of_way_m if pc.road else 16.0,
            carriageway_width=pc.road.carriageway_m if pc.road else 8.0,
            cul_de_sac_bulb_radius=pc.road.cul_de_sac_bulb_radius_m if pc.road and pc.road.cul_de_sac_bulb_radius_m else 15.0,
            max_density=pc.zone.max_density,
            max_lot_coverage=pc.zone.max_lot_coverage_pct / 100.0,
            service_type=svc,
            septic_reserve_pct=pc.servicing.septic_field_reserve_pct / 100.0,
            well_protection_radius=pc.servicing.well_protection_radius_m,
            corner_lot_frontage_reduction=pc.zone.corner_lot_frontage_reduction_pct / 100.0,
            lot_width_target=lot_width_target,
            lot_depth_target=lot_depth_target,
        )


# ── Layout Result ──────────────────────────────────────────────────────────

@dataclass
class LayoutScore:
    """Scoring breakdown for a layout option."""
    lot_yield_score: float = 0.0
    lot_quality_score: float = 0.0
    road_efficiency_score: float = 0.0
    constraint_avoidance_score: float = 0.0
    service_feasibility_score: float = 0.0
    future_expansion_score: float = 0.0
    irregular_lot_penalty: float = 0.0
    long_road_penalty: float = 0.0
    approval_risk_penalty: float = 0.0
    total_score: float = 0.0
    explanation: str = ""

@dataclass
class LayoutWarning:
    """A warning about a specific lot or layout issue."""
    level: WarningLevel
    message: str
    lot_id: Optional[int] = None

@dataclass
class LayoutResult:
    """Complete result from a layout generator."""
    name: str
    pattern: RoadPattern
    rules: LayoutRules
    lots: list[Lot] = field(default_factory=list)
    roads: list[RoadSegment] = field(default_factory=list)
    score: LayoutScore = field(default_factory=LayoutScore)
    warnings: list[LayoutWarning] = field(default_factory=list)

    # Parcel-level area metrics
    gross_area: float = 0.0
    net_usable_area: float = 0.0
    area_lost_to_row: float = 0.0
    area_lost_to_constraints: float = 0.0
    remaining_developable: float = 0.0

    # Lot-level area breakdown (filled after checking)
    road_area: float = 0.0
    constraint_area: float = 0.0
    passing_lot_area: float = 0.0
    failing_lot_area: float = 0.0
    remainder_area: float = 0.0
    saleable_land_pct: float = 0.0
    developable_used_pct: float = 0.0

    @property
    def total_lots(self) -> int:
        return len(self.lots)

    @property
    def residential_lots(self) -> list[Lot]:
        """Lots that are residential type (checked for compliance)."""
        return [l for l in self.lots if l.is_residential]

    @property
    def remainder_lots(self) -> list[Lot]:
        """Leftover developable area lots (not checked for compliance)."""
        return [l for l in self.lots if l.lot_type == LotType.REMAINDER]

    @property
    def passing_lots(self) -> int:
        return sum(1 for l in self.lots if l.is_residential and l.passes_all)

    @property
    def failed_lots(self) -> int:
        """Residential lots that fail compliance (NOT remainders)."""
        return sum(1 for l in self.lots if l.is_residential and not l.passes_all)

    @property
    def avg_lot_area(self) -> float:
        residential = self.residential_lots
        if not residential:
            return 0.0
        return sum(l.area for l in residential) / len(residential)

    @property
    def min_lot_area(self) -> float:
        residential = self.residential_lots
        if not residential:
            return 0.0
        return min(l.area for l in residential)

    @property
    def total_road_length(self) -> float:
        return sum(r.length for r in self.roads)

    @property
    def total_road_area(self) -> float:
        return sum(r.area for r in self.roads)

    @property
    def irregular_lot_count(self) -> int:
        return sum(1 for l in self.lots if l.lot_type == LotType.IRREGULAR)

    @property
    def lots_per_road_metre(self) -> float:
        total_road = self.total_road_length
        return len(self.residential_lots) / total_road if total_road > 0 else 0.0

    def compute_area_metrics(self):
        """Fill in all area metrics from lot polygons. Call AFTER checker runs."""
        # Road area
        self.road_area = sum(r.area for r in self.roads)

        # Constraint area
        self.constraint_area = self.area_lost_to_constraints

        # Residential lot areas (passing vs failing)
        self.passing_lot_area = sum(l.area for l in self.lots if l.is_residential and l.passes_all)
        self.failing_lot_area = sum(l.area for l in self.lots if l.is_residential and not l.passes_all)

        # Remainder area
        self.remainder_area = sum(l.area for l in self.lots if l.lot_type == LotType.REMAINDER)

        # Saleable land % = passing residential lot area / gross area
        if self.gross_area > 0:
            self.saleable_land_pct = (self.passing_lot_area / self.gross_area) * 100
        else:
            self.saleable_land_pct = 0.0

        # Developable used % = (passing + failing residential area) / (gross - constraint - road)
        net = self.gross_area - self.constraint_area - self.road_area
        if net > 0:
            self.developable_used_pct = ((self.passing_lot_area + self.failing_lot_area) / net) * 100
        else:
            self.developable_used_pct = 0.0

    def summary(self) -> str:
        """Generate a human-readable summary of this layout option."""
        lines = [
            f"Option {self.name}: {self.passing_lots}/{len(self.residential_lots)} residential lots passing",
            f"  Pattern: {self.pattern.value}",
            f"  Road length: {self.total_road_length:.0f} m",
            f"  Saleable land: {self.saleable_land_pct:.1f}% ({self.passing_lot_area:.0f} m²)",
            f"  Developable used: {self.developable_used_pct:.1f}%",
            f"  Avg lot area: {self.avg_lot_area:.0f} m² (residential)",
            f"  Min lot area: {self.min_lot_area:.0f} m² (residential)",
            f"  Irregular lots: {self.irregular_lot_count}",
            f"  Lots per road metre: {self.lots_per_road_metre:.2f}",
            f"  Score: {self.score.total_score:.1f}",
        ]
        if self.remainder_lots:
            lines.append(f"  Remainder area: {self.remainder_area:.0f} m² ({len(self.remainder_lots)} pieces, not counted in yield)")
        if self.failed_lots > 0:
            lines.append(f"  Failed residential: {self.failed_lots} lots ({self.failing_lot_area:.0f} m²)")
        if self.warnings:
            fail_warnings = [w for w in self.warnings if w.level == WarningLevel.FAIL]
            caution_warnings = [w for w in self.warnings if w.level == WarningLevel.CAUTION]
            if fail_warnings:
                lines.append(f"  ❌ Failures: {len(fail_warnings)}")
                for w in fail_warnings[:3]:
                    lines.append(f"     - {w.message}")
            if caution_warnings:
                lines.append(f"  ⚠️  Cautions: {len(caution_warnings)}")
                for w in caution_warnings[:3]:
                    lines.append(f"     - {w.message}")
        return "\n".join(lines)


# ── Parcel Input ────────────────────────────────────────────────────────────

@dataclass
class Parcel:
    """Input parcel with constraints and access."""
    geometry: Polygon
    access_points: list[AccessPoint] = field(default_factory=list)
    constraint_areas: list[ConstraintArea] = field(default_factory=list)
    pid: str = ""
    zone_code: str = ""
    municipality: str = "hrm"
    source_crs: int = 4326           # CRS the GeoJSON was in
    working_crs: int = 2961          # CRS we compute in (NAD83(CSRS) / UTM 20N)
    shape: ParcelShape = ParcelShape.RECTANGLE

    @property
    def is_irregular(self) -> bool:
        """True if the parcel shape requires the irregular code path."""
        return self.shape not in (ParcelShape.RECTANGLE, ParcelShape.CONVEX)

    @property
    def gross_area(self) -> float:
        return self.geometry.area

    @property
    def buildable_area(self) -> Polygon:
        """Subtract constraint buffers from the parcel to get buildable area."""
        result = self.geometry
        for ca in self.constraint_areas:
            if ca.buffer_m > 0:
                buffered = ca.geometry.buffer(ca.buffer_m)
            else:
                buffered = ca.geometry
            if ca.deductible:
                result = result.difference(buffered)
        return result

    @property
    def buildable_area_sqm(self) -> float:
        return self.buildable_area.area

    @property
    def constraint_area_pct(self) -> float:
        """Percentage of parcel lost to constraints."""
        if self.gross_area == 0:
            return 0.0
        return (1 - self.buildable_area_sqm / self.gross_area) * 100


# ── Serialization ───────────────────────────────────────────────────────────

def layout_result_to_dict(result: LayoutResult) -> dict:
    """Convert a LayoutResult to a JSON-serializable dict."""
    import json
    from shapely.geometry import mapping

    def poly_to_coords(p):
        if p is None:
            return None
        return list(p.exterior.coords) if hasattr(p, 'exterior') else None

    def line_to_coords(l):
        if l is None:
            return None
        return list(l.coords)

    lots_data = []
    for lot in result.lots:
        lots_data.append({
            "id": lot.id,
            "geometry": poly_to_coords(lot.geometry),
            "frontage_line": line_to_coords(lot.frontage_line),
            "lot_type": lot.lot_type.value,
            "area": round(lot.area, 1),
            "frontage": round(lot.frontage, 1),
            "depth": round(lot.depth, 1),
            "width_min": round(lot.width_min, 1),
            "shape_quality": round(lot.shape_quality, 3),
            "passes_all": lot.passes_all,
            "passes_area": lot.passes_area,
            "passes_frontage": lot.passes_frontage,
            "passes_depth": lot.passes_depth,
            "passes_shape": lot.passes_shape,
            "passes_buildable": lot.passes_buildable,
            "passes_service": lot.passes_service,
            "is_residential": lot.is_residential,
            "constraint_conflicts": lot.constraint_conflicts,
            "warnings": lot.warnings,
        })

    roads_data = []
    for road in result.roads:
        roads_data.append({
            "centerline": line_to_coords(road.centerline),
            "row_width": road.row_width,
            "road_type": road.road_type,
            "is_cul_de_sac": road.is_cul_de_sac,
            "is_future_stub": road.is_future_stub,
            "name": road.name,
            "length": round(road.length, 1),
            "area": round(road.area, 1),
        })

    return {
        "name": result.name,
        "pattern": result.pattern.value,
        "total_lots": result.total_lots,
        "residential_lots": len(result.residential_lots),
        "remainder_lots": len(result.remainder_lots),
        "passing_lots": result.passing_lots,
        "failed_lots": result.failed_lots,
        "avg_lot_area": round(result.avg_lot_area, 1),
        "min_lot_area": round(result.min_lot_area, 1),
        "total_road_length": round(result.total_road_length, 1),
        "total_road_area": round(result.total_road_area, 1),
        "gross_area": round(result.gross_area, 1),
        "road_area": round(result.road_area, 1),
        "constraint_area": round(result.constraint_area, 1),
        "passing_lot_area": round(result.passing_lot_area, 1),
        "failing_lot_area": round(result.failing_lot_area, 1),
        "remainder_area": round(result.remainder_area, 1),
        "saleable_land_pct": round(result.saleable_land_pct, 1),
        "developable_used_pct": round(result.developable_used_pct, 1),
        "lots_per_road_metre": round(result.lots_per_road_metre, 2),
        "irregular_lot_count": result.irregular_lot_count,
        "score": {
            "lot_yield_score": round(result.score.lot_yield_score, 2),
            "lot_quality_score": round(result.score.lot_quality_score, 2),
            "road_efficiency_score": round(result.score.road_efficiency_score, 2),
            "constraint_avoidance_score": round(result.score.constraint_avoidance_score, 2),
            "service_feasibility_score": round(result.score.service_feasibility_score, 2),
            "future_expansion_score": round(result.score.future_expansion_score, 2),
            "irregular_lot_penalty": round(result.score.irregular_lot_penalty, 2),
            "long_road_penalty": round(result.score.long_road_penalty, 2),
            "approval_risk_penalty": round(result.score.approval_risk_penalty, 2),
            "total_score": round(result.score.total_score, 2),
            "explanation": result.score.explanation,
        },
        "lots": lots_data,
        "roads": roads_data,
        "warnings": [{"level": w.level.value, "message": w.message, "lot_id": w.lot_id} for w in result.warnings],
    }


def layout_result_to_json(result: LayoutResult, path: str = None) -> str:
    """Convert LayoutResult to JSON, optionally writing to file."""
    data = layout_result_to_dict(result)
    json_str = json.dumps(data, indent=2)
    if path:
        with open(path, 'w') as f:
            f.write(json_str)