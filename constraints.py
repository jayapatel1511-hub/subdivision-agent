"""
Subdivision concept design constraint engine.

Loads zoning, servicing, buffer, road, and stormwater constraints
from CSV lookup tables and computes the buildable area for a parcel.
"""

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class ZoneConstraints:
    zone_code: str
    zone_name: str
    min_lot_area_sqm: float
    min_lot_frontage_m: float
    min_lot_depth_m: float
    max_density: Optional[float]  # units/ha, None = no cap
    min_rear_setback_m: float
    min_side_setback_m: float
    min_front_setback_m: float
    min_flankage_setback_m: float
    corner_lot_frontage_reduction_pct: float
    max_lot_coverage_pct: float


@dataclass
class ServicingConstraints:
    servicing_type: str
    min_lot_area_sqm: float
    min_frontage_m: float
    min_depth_m: float
    septic_field_reserve_pct: float
    well_setback_from_septic_m: float
    well_setback_from_boundary_m: float
    well_setback_from_building_m: float
    well_protection_radius_m: float
    drainage_field_length_m: float
    drainage_field_width_m: float
    replacement_field_required: bool
    well_min_depth_m: float
    septic_approval_required: bool


@dataclass
class BufferConstraint:
    feature_type: str
    buffer_width_m: float
    regulation_source: str
    applies_to: str
    measured_from: str
    deductible_from_yield: bool
    notes: str


@dataclass
class RoadStandard:
    road_type: str
    right_of_way_m: float
    carriageway_m: float
    cul_de_sac_bulb_radius_m: Optional[float]
    sidewalk_required: bool
    sidewalk_sides: Optional[str]
    sidewalk_width_m: Optional[float]
    min_grade_pct: Optional[float]
    max_grade_pct: Optional[float]
    horizontal_curve_min_radius_m: Optional[float]
    cul_de_sac_max_length_m: Optional[float]
    max_lot_frontage_no_cul_de_sac_m: Optional[float]


@dataclass
class ParcelConstraints:
    """The full constraint set for a parcel, ready for the engine."""
    zone: ZoneConstraints
    servicing: ServicingConstraints
    buffers: list[BufferConstraint] = field(default_factory=list)
    road: RoadStandard = None

    # Computed effective values
    effective_min_lot_area: float = 0.0
    effective_min_frontage: float = 0.0
    effective_min_depth: float = 0.0

    def compute_effective(self):
        """Take the MORE RESTRICTIVE of zone vs servicing constraints."""
        self.effective_min_lot_area = max(
            self.zone.min_lot_area_sqm,
            self.servicing.min_lot_area_sqm
        )
        self.effective_min_frontage = max(
            self.zone.min_lot_frontage_m,
            self.servicing.min_frontage_m
        )
        self.effective_min_depth = max(
            self.zone.min_lot_depth_m,
            self.servicing.min_depth_m
        )


class ConstraintEngine:
    """Loads constraint CSV tables and resolves the full constraint set for a parcel."""

    def __init__(self, municipality: str = "hrm"):
        self.municipality = municipality
        self.data_dir = Path(__file__).parent / "data" / "zones" / municipality
        self._zones: dict[str, ZoneConstraints] = {}
        self._servicing: dict[str, ServicingConstraints] = {}
        self._buffers: list[BufferConstraint] = []
        self._roads: dict[str, RoadStandard] = {}
        self._loaded = False

    def load(self):
        """Load all CSV constraint tables."""
        self._load_zones()
        self._load_servicing()
        self._load_buffers()
        self._load_roads()
        self._loaded = True

    def _load_zones(self):
        path = self.data_dir / "hrm_zones.csv"
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                zc = ZoneConstraints(
                    zone_code=row["zone_code"],
                    zone_name=row["zone_name"],
                    min_lot_area_sqm=float(row["min_lot_area_sqm"]),
                    min_lot_frontage_m=float(row["min_lot_frontage_m"]),
                    min_lot_depth_m=float(row["min_lot_depth_m"]),
                    max_density=float(row["max_density_units_per_ha"]) if row["max_density_units_per_ha"] else None,
                    min_rear_setback_m=float(row["min_rear_setback_m"]),
                    min_side_setback_m=float(row["min_side_setback_m"]),
                    min_front_setback_m=float(row["min_front_setback_m"]),
                    min_flankage_setback_m=float(row["min_flankage_setback_m"]),
                    corner_lot_frontage_reduction_pct=float(row["corner_lot_frontage_reduction_pct"]),
                    max_lot_coverage_pct=float(row["max_lot_coverage_pct"]),
                )
                self._zones[zc.zone_code] = zc

    def _load_servicing(self):
        path = self.data_dir / "hrm_servicing.csv"
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                sc = ServicingConstraints(
                    servicing_type=row["servicing_type"],
                    min_lot_area_sqm=float(row["min_lot_area_sqm"]),
                    min_frontage_m=float(row["min_frontage_m"]),
                    min_depth_m=float(row["min_depth_m"]),
                    septic_field_reserve_pct=float(row["septic_field_reserve_pct"]),
                    well_setback_from_septic_m=float(row["well_setback_from_septic_m"]),
                    well_setback_from_boundary_m=float(row["well_setback_from_boundary_m"]),
                    well_setback_from_building_m=float(row["well_setback_from_building_m"]),
                    well_protection_radius_m=float(row["well_protection_radius_m"]),
                    drainage_field_length_m=float(row["drainage_field_length_m"]),
                    drainage_field_width_m=float(row["drainage_field_width_m"]),
                    replacement_field_required=row["replacement_field_required"] == "yes",
                    well_min_depth_m=float(row["well_min_depth_m"]),
                    septic_approval_required=row["septic_approval_required"] == "yes",
                )
                self._servicing[sc.servicing_type] = sc

    def _load_buffers(self):
        path = self.data_dir / "hrm_buffers_constraints.csv"
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                bc = BufferConstraint(
                    feature_type=row["feature_type"],
                    buffer_width_m=float(row["buffer_width_m"]),
                    regulation_source=row["regulation_source"],
                    applies_to=row["applies_to"],
                    measured_from=row["measured_from"],
                    deductible_from_yield=row["deductible_from_yield"] == "yes",
                    notes=row["notes"],
                )
                self._buffers.append(bc)

    def _load_roads(self):
        path = self.data_dir / "hrm_road_standards.csv"
        with open(path) as f:
            reader = csv.DictReader(f)
            for row in reader:
                rs = RoadStandard(
                    road_type=row["road_type"],
                    right_of_way_m=float(row["right_of_way_m"]),
                    carriageway_m=float(row["carriageway_m"]),
                    cul_de_sac_bulb_radius_m=float(row["cul_de_sac_bulb_radius_m"]) if row["cul_de_sac_bulb_radius_m"] else None,
                    sidewalk_required=row["sidewalk_required"] == "yes",
                    sidewalk_sides=row.get("sidewalk_sides") or None,
                    sidewalk_width_m=float(row["sidewalk_width_m"]) if row.get("sidewalk_width_m") else None,
                    min_grade_pct=float(row["min_grade_pct"]) if row.get("min_grade_pct") else None,
                    max_grade_pct=float(row["max_grade_pct"]) if row.get("max_grade_pct") else None,
                    horizontal_curve_min_radius_m=float(row["horizontal_curve_min_radius_m"]) if row.get("horizontal_curve_min_radius_m") else None,
                    cul_de_sac_max_length_m=float(row["cul_de_sac_max_length_m"]) if row.get("cul_de_sac_max_length_m") else None,
                    max_lot_frontage_no_cul_de_sac_m=float(row["max_lot_frontage_no_cul_de_sac_m"]) if row.get("max_lot_frontage_no_cul_de_sac_m") else None,
                )
                self._roads[rs.road_type] = rs

    def resolve(self, zone_code: str, servicing_type: str, road_type: str = "local_residential",
                site_conditions: list[str] = None) -> ParcelConstraints:
        """
        Resolve the full constraint set for a parcel.

        Args:
            zone_code: e.g. "R-2", "C-1", "MU-1"
            servicing_type: "serviced", "serviced_water_only", "unserviced", etc.
            road_type: "local_residential", "collector_residential", etc.
            site_conditions: list of environmental conditions present, e.g.
                ["watercourse_river", "wetland", "steep_slope_15pct"]

        Returns:
            ParcelConstraints with zone, servicing, buffers, and road standards.
        """
        if not self._loaded:
            self.load()

        if zone_code not in self._zones:
            raise ValueError(f"Unknown zone code: {zone_code}. Available: {list(self._zones.keys())}")
        if servicing_type not in self._servicing:
            raise ValueError(f"Unknown servicing type: {servicing_type}. Available: {list(self._servicing.keys())}")
        if road_type not in self._roads:
            raise ValueError(f"Unknown road type: {road_type}. Available: {list(self._roads.keys())}")

        pc = ParcelConstraints(
            zone=self._zones[zone_code],
            servicing=self._servicing[servicing_type],
            road=self._roads[road_type],
        )

        # Filter buffers to those relevant to this site
        site_conditions = site_conditions or []
        if site_conditions:
            condition_set = set(site_conditions)
            pc.buffers = [b for b in self._buffers if b.feature_type in condition_set]

        pc.compute_effective()
        return pc

    def list_zones(self) -> list[str]:
        if not self._loaded:
            self.load()
        return list(self._zones.keys())

    def list_servicing_types(self) -> list[str]:
        if not self._loaded:
            self.load()
        return list(self._servicing.keys())

    def list_road_types(self) -> list[str]:
        if not self._loaded:
            self.load()
        return list(self._roads.keys())

    def list_buffer_types(self) -> list[str]:
        if not self._loaded:
            self.load()
        return [b.feature_type for b in self._buffers]