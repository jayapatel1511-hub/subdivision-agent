"""
Subdivision Agent — Lot Checker & Buildable Envelope.

Checks every lot against the rule set and generates buildable/service
envelopes. The checker is what separates a "pretty picture" from a
"this layout will actually get approved" assessment.
"""

from __future__ import annotations

import math
from typing import Optional

from shapely.geometry import Polygon, LineString, Point, MultiPolygon
from shapely.ops import unary_union

from models import Lot, LayoutRules, LayoutResult, LayoutWarning, WarningLevel, ServiceType


class LotChecker:
    """Check every lot in a layout against the rules."""

    def __init__(self, rules: LayoutRules, constraint_areas: list = None):
        self.rules = rules
        self.constraint_areas = constraint_areas or []

    def check_lot(self, lot: Lot) -> Lot:
        """Run all checks on a single lot. Returns the lot with check results filled in."""
        # Compute basic properties first
        lot.compute_properties()

        # ── Area check ──
        lot.passes_area = lot.area >= self.rules.min_lot_area

        # ── Frontage check ──
        lot.passes_frontage = lot.frontage >= self.rules.min_frontage

        # Apply corner lot frontage reduction
        if lot.lot_type.value == "corner" and self.rules.corner_lot_frontage_reduction > 0:
            reduced_min = self.rules.min_frontage * (1 - self.rules.corner_lot_frontage_reduction)
            lot.passes_frontage = lot.frontage >= reduced_min

        # ── Depth check ──
        lot.passes_depth = lot.depth >= self.rules.min_depth

        # ── Width check ──
        width_passes = lot.width_min >= self.rules.min_width * 0.9  # 10% tolerance
        lot.warnings = getattr(lot, 'warnings', [])
        if not width_passes:
            lot.warnings.append(f"Narrow width: {lot.width_min:.1f}m (min {self.rules.min_width:.1f}m)")

        # ── Shape quality check ──
        # Compactness: 4πA/P² — circle=1.0, square≈0.787, <0.4 is poor
        lot.passes_shape = lot.shape_quality >= 0.35

        # ── Buildable envelope ──
        lot.buildable_envelope = self._compute_buildable_envelope(lot)
        lot.passes_buildable = (
            lot.buildable_envelope is not None
            and lot.buildable_envelope.area >= self.rules.min_buildable_envelope
        )

        # ── Access check ──
        lot.passes_access = lot.frontage_line is not None and lot.frontage >= self.rules.min_frontage * 0.5

        # ── Service feasibility ──
        lot.passes_service = self._check_service_feasibility(lot)

        # ── Constraint overlap ──
        lot.constraint_conflicts = self._check_constraint_conflicts(lot)

        # ── Overall pass ──
        lot.passes_all = (
            lot.passes_area
            and lot.passes_frontage
            and lot.passes_depth
            and lot.passes_shape
            and lot.passes_buildable
            and lot.passes_access
            and lot.passes_service
        )

        # ── Warnings for near-misses ──
        if lot.passes_area and lot.area < self.rules.min_lot_area * 1.1:
            lot.warnings.append(f"Tight area: {lot.area:.0f}m² (min {self.rules.min_lot_area:.0f}m²)")
        if lot.passes_frontage and lot.frontage < self.rules.min_frontage * 1.1:
            lot.warnings.append(f"Tight frontage: {lot.frontage:.1f}m (min {self.rules.min_frontage:.1f}m)")

        return lot

    def check_layout(self, result: LayoutResult) -> LayoutResult:
        """Check all lots in a layout result."""
        for lot in result.lots:
            self.check_lot(lot)

        # Add layout-level warnings
        failed = [l for l in result.lots if not l.passes_all]
        if failed:
            result.warnings.append(LayoutWarning(
                level=WarningLevel.CAUTION,
                message=f"{len(failed)} lots fail compliance checks",
            ))

        irregular = [l for l in result.lots if l.lot_type.value in ("irregular", "flag", "remainder")]
        if len(irregular) > len(result.lots) * self.rules.max_irregular_lot_pct:
            result.warnings.append(LayoutWarning(
                level=WarningLevel.CAUTION,
                message=f"Too many irregular lots: {len(irregular)}/{len(result.lots)} "
                         f"(max {self.rules.max_irregular_lot_pct*100:.0f}%)",
            ))

        # Check density cap
        if self.rules.max_density is not None and result.gross_area > 0:
            density = len(result.lots) / (result.gross_area / 10000)
            if density > self.rules.max_density:
                result.warnings.append(LayoutWarning(
                    level=WarningLevel.FAIL,
                    message=f"Density {density:.1f} units/ha exceeds max {self.rules.max_density:.1f}",
                ))

        return result

    def _compute_buildable_envelope(self, lot: Lot) -> Optional[Polygon]:
        """Compute the buildable envelope inside a lot after applying setbacks.

        The buildable envelope = lot geometry minus:
        - Front setback
        - Rear setback
        - Side setbacks (both sides)
        - Flankage setback (for corner lots)
        """
        if lot.geometry is None or lot.geometry.is_empty:
            return None

        # Buffer inward by setbacks
        # Use a simplified approach: buffer the lot inward by the minimum setback
        min_setback = min(self.rules.front_setback, self.rules.rear_setback,
                          self.rules.side_setback)

        try:
            # Negative buffer = shrink inward
            envelope = lot.geometry.buffer(-min_setback, join_style=2)
            if envelope.is_empty or not isinstance(envelope, Polygon):
                return None
        except Exception:
            return None

        # For unserviced lots, subtract service reserve
        if self.rules.service_type in (ServiceType.WELL_SEPTIC, ServiceType.MUNICIPAL_WATER_SEPTIC):
            if self.rules.septic_reserve_pct > 0:
                # The buildable envelope must still have room after reserving
                # septic area. Reduce envelope further by the reserve percentage.
                min_after_reserve = lot.area * (1 - self.rules.septic_reserve_pct)
                if envelope.area < min_after_reserve * 0.5:
                    return None  # Not enough room for building + septic

        return envelope

    def _check_service_feasibility(self, lot: Lot) -> bool:
        """Check if the lot can support the assumed service type.

        This is a 2D shape check, not a pipe drawing:
        - Municipal: just needs minimum area and frontage (already checked)
        - Septic: needs enough area for drain field reserve
        - Well: needs isolation from septic and boundaries
        """
        if self.rules.service_type == ServiceType.MUNICIPAL_WATER_SEWER:
            return True  # Already covered by min area/frontage

        if self.rules.service_type in (ServiceType.WELL_SEPTIC, ServiceType.MUNICIPAL_WATER_SEPTIC):
            # Need enough area for septic field reserve
            if self.rules.septic_reserve_pct > 0:
                reserve_area = lot.area * self.rules.septic_reserve_pct
                if reserve_area < 100:  # Absolute minimum septic field area
                    return False

            # Well protection: lot must be wider than 2× well protection radius
            if self.rules.well_protection_radius > 0:
                if lot.width_min < self.rules.well_protection_radius * 1.5:
                    return False

        if self.rules.service_type == ServiceType.FUTURE_MUNICIPAL:
            return True  # Design for future, check as municipal

        if self.rules.service_type == ServiceType.UNKNOWN:
            # Conservative: check as unserviced
            if lot.area < self.rules.min_lot_area * 1.2:  # 20% margin
                return False

        return True

    def _check_constraint_conflicts(self, lot: Lot) -> list[str]:
        """Check if the lot overlaps with any constraint areas."""
        conflicts = []
        for ca in self.constraint_areas:
            if lot.geometry.intersects(ca.geometry):
                overlap_pct = lot.geometry.intersection(ca.geometry).area / lot.area * 100
                if overlap_pct > 5:  # >5% overlap is a conflict
                    conflicts.append(f"{ca.name}: {overlap_pct:.0f}% overlap")
        return conflicts


class LayoutScorer:
    """Score and rank layout options.

    Total Score = w_yield × yield_score
                + w_quality × quality_score
                + w_road × road_efficiency
                + w_constraint × constraint_score
                + w_service × service_score
                + w_future × future_score
                − p_irregular × irregular_count
                − p_road × total_road_length
                − p_approval × failed_lot_count
    """

    def __init__(self, rules: LayoutRules):
        self.rules = rules

    def score_layout(self, result: LayoutResult) -> LayoutResult:
        """Compute all scores for a layout result."""
        r = result
        w = self.rules  # weights

        # ── Lot Yield Score ──
        # How many lots relative to theoretical max
        theoretical_max = r.gross_area / (w.min_lot_area * 1.2)  # 20% buffer for roads etc
        if theoretical_max > 0:
            r.score.lot_yield_score = min(r.passing_lots / theoretical_max, 1.0) * 100
        else:
            r.score.lot_yield_score = 0

        # ── Lot Quality Score ──
        # Average shape quality of passing lots
        passing_lots = [l for l in r.lots if l.passes_all]
        if passing_lots:
            avg_shape = sum(l.shape_quality for l in passing_lots) / len(passing_lots)
            avg_area_ratio = sum(l.area / w.min_lot_area for l in passing_lots) / len(passing_lots)
            # Quality = geometric mean of shape quality and area adequacy
            r.score.lot_quality_score = math.sqrt(avg_shape * min(avg_area_ratio, 2.0)) * 50
        else:
            r.score.lot_quality_score = 0

        # ── Road Efficiency Score ──
        # Lots per metre of road — more is better
        if r.total_road_length > 0:
            lpm = r.lots_per_road_metre
            # Target: 0.08 lots/metre (good efficiency)
            r.score.road_efficiency_score = min(lpm / 0.08, 1.0) * 100
        else:
            # Existing road pattern — no new road needed, max efficiency
            r.score.road_efficiency_score = 100

        # ── Constraint Avoidance Score ──
        # How few lots have constraint conflicts
        lots_with_conflicts = sum(1 for l in r.lots if l.constraint_conflicts)
        if r.total_lots > 0:
            conflict_free_ratio = 1 - (lots_with_conflicts / r.total_lots)
            r.score.constraint_avoidance_score = conflict_free_ratio * 100
        else:
            r.score.constraint_avoidance_score = 0

        # ── Service Feasibility Score ──
        # How many lots pass service check
        service_passing = sum(1 for l in r.lots if l.passes_service)
        if r.total_lots > 0:
            r.score.service_feasibility_score = (service_passing / r.total_lots) * 100
        else:
            r.score.service_feasibility_score = 0

        # ── Future Expansion Score ──
        # Does the layout leave room for future phases?
        # Remainder area as % of gross
        if r.gross_area > 0:
            remainder_pct = r.remaining_developable / r.gross_area
            # Sweet spot: 10-20% remainder is good for future
            if 0.05 < remainder_pct < 0.25:
                r.score.future_expansion_score = 100
            elif remainder_pct >= 0.25:
                r.score.future_expansion_score = 50  # Too much leftover = inefficient
            else:
                r.score.future_expansion_score = 20  # Packed tight
        else:
            r.score.future_expansion_score = 0

        # ── Penalties ──
        r.score.irregular_lot_penalty = r.irregular_lot_count * w.p_irregular_lot * 10
        r.score.long_road_penalty = r.total_road_length * w.p_long_road
        r.score.approval_risk_penalty = r.failed_lots * w.p_approval_risk * 10

        # ── Total Score ──
        r.score.total_score = (
            w.w_lot_yield * r.score.lot_yield_score
            + w.w_lot_quality * r.score.lot_quality_score
            + w.w_road_efficiency * r.score.road_efficiency_score
            + w.w_constraint_avoidance * r.score.constraint_avoidance_score
            + w.w_service_feasibility * r.score.service_feasibility_score
            + w.w_future_expansion * r.score.future_expansion_score
            - r.score.irregular_lot_penalty
            - r.score.long_road_penalty
            - r.score.approval_risk_penalty
        )

        # ── Explanation ──
        r.score.explanation = self._generate_explanation(r)

        return r

    def rank_layouts(self, results: list[LayoutResult]) -> list[LayoutResult]:
        """Score and rank layouts by total score (descending)."""
        scored = [self.score_layout(r) for r in results]
        scored.sort(key=lambda r: r.score.total_score, reverse=True)
        return scored

    def _generate_explanation(self, result: LayoutResult) -> str:
        """Generate a human-readable explanation of why this layout scores as it does."""
        s = result.score
        lines = []

        # Overall assessment
        if s.total_score >= 70:
            lines.append(f"Option {result.name} scores {s.total_score:.0f} — strong layout.")
        elif s.total_score >= 40:
            lines.append(f"Option {result.name} scores {s.total_score:.0f} — acceptable but has issues.")
        else:
            lines.append(f"Option {result.name} scores {s.total_score:.0f} — weak layout, reconsider.")

        # Strengths
        strengths = []
        if s.lot_yield_score >= 60:
            strengths.append(f"good yield ({result.passing_lots} passing lots)")
        if s.lot_quality_score >= 60:
            strengths.append("good lot quality")
        if s.road_efficiency_score >= 70:
            strengths.append("efficient road use")
        if s.constraint_avoidance_score >= 80:
            strengths.append("clean constraint avoidance")
        if s.service_feasibility_score >= 80:
            strengths.append("service-feasible")
        if strengths:
            lines.append(f"  Strengths: {', '.join(strengths)}.")

        # Weaknesses
        weaknesses = []
        if s.lot_yield_score < 40:
            weaknesses.append("low yield")
        if s.lot_quality_score < 40:
            weaknesses.append("poor lot shapes")
        if s.road_efficiency_score < 40:
            weaknesses.append("inefficient road layout")
        if s.approval_risk_penalty > 5:
            weaknesses.append(f"{result.failed_lots} lots failing compliance")
        if s.irregular_lot_penalty > 5:
            weaknesses.append(f"{result.irregular_lot_count} irregular lots")
        if weaknesses:
            lines.append(f"  Weaknesses: {', '.join(weaknesses)}.")

        # Specific callouts
        if result.failed_lots > 0:
            fail_reasons = {}
            for lot in result.lots:
                if not lot.passes_all:
                    reasons = []
                    if not lot.passes_area: reasons.append("area")
                    if not lot.passes_frontage: reasons.append("frontage")
                    if not lot.passes_depth: reasons.append("depth")
                    if not lot.passes_shape: reasons.append("shape")
                    if not lot.passes_buildable: reasons.append("buildable")
                    if not lot.passes_service: reasons.append("service")
                    for r in reasons:
                        fail_reasons[r] = fail_reasons.get(r, 0) + 1
            if fail_reasons:
                reason_str = ", ".join(f"{v}× {k}" for k, v in sorted(fail_reasons.items(), key=lambda x: -x[1]))
                lines.append(f"  Lot failures: {reason_str}.")

        if result.remaining_developable > result.gross_area * 0.15:
            lines.append(f"  {result.remaining_developable:.0f}m² leftover — consider future phase.")

        return " ".join(lines)