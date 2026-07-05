"""
Subdivision Agent — CLI and interactive intake.

Usage:
    python intake.py --pid 12345
    python intake.py --boundary parcel.geojson --zone R-2 --servicing serviced
"""

import argparse
from constraints import ConstraintEngine


def print_constraints(pc):
    """Pretty-print the resolved constraints for user review."""
    print("\n" + "=" * 70)
    print("  SUBDIVISION CONSTRAINT SUMMARY")
    print("=" * 70)

    print(f"\n📐 Zone: {pc.zone.zone_code} — {pc.zone.zone_name}")
    print(f"   Min lot area:      {pc.effective_min_lot_area:.0f} m²")
    print(f"   Min lot frontage:  {pc.effective_min_frontage:.1f} m")
    print(f"   Min lot depth:     {pc.effective_min_depth:.0f} m")
    if pc.zone.max_density:
        print(f"   Max density:       {pc.zone.max_density:.0f} units/ha")
    else:
        print(f"   Max density:       No cap")
    print(f"   Front setback:     {pc.zone.min_front_setback_m:.1f} m")
    print(f"   Rear setback:      {pc.zone.min_rear_setback_m:.1f} m")
    print(f"   Side setback:      {pc.zone.min_side_setback_m:.1f} m")
    print(f"   Flankage setback:  {pc.zone.min_flankage_setback_m:.1f} m")
    print(f"   Max lot coverage:  {pc.zone.max_lot_coverage_pct:.0f}%")

    print(f"\n🔌 Servicing: {pc.servicing.servicing_type}")
    if pc.servicing.septic_field_reserve_pct > 0:
        print(f"   ⚠️  Septic reserve:  {pc.servicing.septic_field_reserve_pct:.0f}% of field area for replacement")
    if pc.servicing.well_protection_radius_m > 0:
        print(f"   ⚠️  Well protection: {pc.servicing.well_protection_radius_m:.0f}m radius around well")
        print(f"       Well ↔ septic:   {pc.servicing.well_setback_from_septic_m:.1f}m")
        print(f"       Well ↔ boundary: {pc.servicing.well_setback_from_boundary_m:.1f}m")
    if pc.servicing.septic_approval_required:
        print(f"   ⚠️  NS Environment septic approval REQUIRED")
    if pc.servicing.replacement_field_required:
        print(f"   ⚠️  Replacement septic field REQUIRED")

    if pc.road:
        print(f"\n🛣️  Road: {pc.road.road_type}")
        print(f"   ROW width:         {pc.road.right_of_way_m:.0f}m")
        print(f"   Carriageway:        {pc.road.carriageway_m:.0f}m")
        if pc.road.cul_de_sac_bulb_radius_m:
            print(f"   Cul-de-sac bulb:    {pc.road.cul_de_sac_bulb_radius_m:.0f}m radius")
        if pc.road.sidewalk_required:
            print(f"   Sidewalk:           Yes ({pc.road.sidewalk_sides} side(s), {pc.road.sidewalk_width_m}m)")
        else:
            print(f"   Sidewalk:           No")

    if pc.buffers:
        print(f"\n🌿 Environmental Buffers ({len(pc.buffers)} active):")
        for b in pc.buffers:
            print(f"   • {b.feature_type}: {b.buffer_width_m:.0f}m buffer from {b.measured_from}")
            print(f"     ({b.regulation_source})")
            if b.deductible_from_yield:
                print(f"     ⚠️  DEDUCTIBLE from buildable area")

    print(f"\n{'=' * 70}")
    print(f"  EFFECTIVE MINIMUMS (zone vs servicing, more restrictive wins):")
    print(f"    Lot area:     {pc.effective_min_lot_area:.0f} m²")
    print(f"    Lot frontage: {pc.effective_min_frontage:.1f} m")
    print(f"    Lot depth:    {pc.effective_min_depth:.0f} m")
    print(f"{'=' * 70}\n")


def interactive_intake(engine: ConstraintEngine):
    """Walk the user through the intake, auto-suggesting based on zone."""
    print("\n🏗️  Subdivision Concept Design — Intake")
    print("-" * 40)

    # Zone selection
    zones = engine.list_zones()
    print(f"\nAvailable zones: {', '.join(zones)}")
    zone_code = input(f"Zone code [R-2]: ").strip() or "R-2"

    # Servicing type
    servicing_types = engine.list_servicing_types()
    print(f"\nServicing types: {', '.join(servicing_types)}")
    servicing = input(f"Servicing type [serviced]: ").strip() or "serviced"

    # Road type
    road_types = engine.list_road_types()
    print(f"\nRoad types: {', '.join(road_types)}")
    road_type = input(f"Road type [local_residential]: ").strip() or "local_residential"

    # Environmental conditions
    buffer_types = engine.list_buffer_types()
    print(f"\nEnvironmental conditions on site (comma-separated):")
    print(f"  Options: {', '.join(buffer_types)}")
    conditions_input = input("Conditions [none]: ").strip()
    conditions = [c.strip() for c in conditions_input.split(",") if c.strip()] if conditions_input else []

    # Resolve
    pc = engine.resolve(zone_code, servicing, road_type, conditions)
    print_constraints(pc)

    return pc


def main():
    parser = argparse.ArgumentParser(description="Subdivision concept design intake")
    parser.add_argument("--zone", default="R-2", help="Zone code (e.g. R-2, C-1, MU-1)")
    parser.add_argument("--servicing", default="serviced", help="Servicing type")
    parser.add_argument("--road", default="local_residential", help="Road type")
    parser.add_argument("--conditions", default="", help="Comma-separated environmental conditions")
    parser.add_argument("--interactive", action="store_true", help="Interactive intake mode")
    args = parser.parse_args()

    engine = ConstraintEngine(municipality="hrm")
    engine.load()

    if args.interactive:
        interactive_intake(engine)
    else:
        conditions = [c.strip() for c in args.conditions.split(",") if c.strip()] if args.conditions else []
        pc = engine.resolve(args.zone, args.servicing, args.road, conditions)
        print_constraints(pc)


if __name__ == "__main__":
    main()