"""
Subdivision Agent — Lot Checker & Buildable Envelope.

Checks every residential lot against the rule set and generates buildable/service
envelopes. Remainder lots are NOT checked for compliance — they're reported separately.

The checker is what separates a "pretty picture" from a
"this layout will actually get approved" assessment.
"""

from __future__ import annotations

import math
from typing import Optional

from shapely.geometry import Polygon, LineString, Point, MultiPolygon
from shapely.ops import unary_union

from models import Lot, LotType, LayoutRules, LayoutResult, LayoutWarning, WarningLevel, ServiceType


class LotChecker:
    """Check every residential lot in a layout against the rules."""

    def __init__(self, rules: LayoutRules, constraint_areas: list = None):
        self.rules = rules
        self.constraint_areas = constraint_areas or []

    def check_lot(self, lot: Lot) -> Lot:
        """Run all checks on a single lot. Returns the lot with check results filled in.

        Only residential lots (RESIDENTIAL, CORNER, IRREGULAR) are meaningfully checked.
        Remainder lots get a skip marker — they don't count as failed residential.
        """
        # Always compute properties
        lot.compute_properties()

        # Remainder and infrastructure lots are NOT checked for residential compliance
        if not lot.is_residential:
            lot.passes_all = False  # Not a passing residential lot
            # Set all checks to False — these lots are excluded from yield
            lot.passes_area = False
            lot.passes_frontage = False
            lot.passes_depth = False
            lot.passes_shape = False
            lot.passes_buildable = False
            lot.passes_access = False
            lot.passes_service = False
            return lot

        # ── Area check ──
        lot.passes_area = lot.area >= self.rules.min_lot_area

        # ── Frontage check ──
        lot.passes_frontage = lot.frontage >= self.rules.min_frontage

        # Apply corner lot frontage reduction
        if lot.lot_type == LotType.CORNER and self.rules.corner_lot_frontage_reduction > 0:
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
        """Check all lots in a layout result. Only residential lots are checked
        for compliance. Remainder lots are marked but not counted as failures.
        After checking, compute_area_metrics() is called to fill in saleable
        land % and other area breakdowns.
        """
        for lot in result.lots:
            self.check_lot(lot)

        # Layout-level warnings — only count residential lots
        failed_residential = [l for l in result.lots if l.is_residential and not l.passes_all]
        if failed_residential:
            result.warnings.append(LayoutWarning(
                level=WarningLevel.CAUTION,
                message=f"{len(failed_residential)} residential lots fail compliance checks",
            ))

        remainder_lots = result.remainder_lots
        if remainder_lots:
            result.warnings.append(LayoutWarning(
                level=WarningLevel.INFO,
                message=f"{len(remainder_lots)} remainder pieces ({sum(l.area for l in remainder_lots):.0f}m²) not counted in yield",
            ))

        irregular_residential = [l for l in result.lots if l.lot_type == LotType.IRREGULAR]
        total_residential = len(result.residential_lots)
        if total_residential > 0 and len(irregular_residential) > total_residential * self.rules.max_irregular_lot_pct:
            result.warnings.append(LayoutWarning(
                level=WarningLevel.CAUTION,
                message=f"Too many irregular lots: {len(irregular_residential)}/{total_residential} "
                        f"(max {self.rules.max_irregular_lot_pct*100:.0f}%)",
            ))

        # Check density cap — residential lots only
        if self.rules.max_density is not None and result.gross_area > 0:
            density = result.passing_lots / (result.gross_area / 10000)
            if density > self.rules.max_density:
                result.warnings.append(LayoutWarning(
                    level=WarningLevel.FAIL,
                    message=f"Density {density:.1f} units/ha exceeds max {self.rules.max_density:.1f}",
                ))

        # Compute area metrics AFTER all lots are checked
        result.compute_area_metrics()

        return result

    def _compute_buildable_envelope(self, lot: Lot) -> Optional[Polygon]:
        """Compute the buildable envelope inside a lot after applying setbacks."""
        if lot.geometry is None or lot.geometry.is_empty:
            return None

        min_setback = min(self.rules.front_setback, self.rules.rear_setback,
                          self.rules.side_setback)

        try:
            envelope = lot.geometry.buffer(-min_setback, join_style=2)
            if envelope.is_empty or not isinstance(envelope, Polygon):
                return None
        except Exception:
            return None

        # For unserviced lots, subtract service reserve
        if self.rules.service_type in (ServiceType.WELL_SEPTIC, ServiceType.MUNICIPAL_WATER_SEPTIC):
            if self.rules.septic_reserve_pct > 0:
                min_after_reserve = lot.area * (1 - self.rules.septic_reserve_pct)
                if envelope.area < min_after_reserve * 0.5:
                    return None

        return envelope

    def _check_service_feasibility(self, lot: Lot) -> bool:
        """Check if the lot can support the assumed service type.

        This is a 2D shape check, not a pipe drawing:
        - Municipal: just needs minimum area and frontage (already checked)
        - Septic: needs enough area for drain field reserve
        - Well: needs isolation from septic and boundaries
        """
        if self.rules.service_type == ServiceType.MUNICIPAL_WATER_SEWER:
            return True

        if self.rules.service_type in (ServiceType.WELL_SEPTIC, ServiceType.MUNICIPAL_WATER_SEPTIC):
            if self.rules.septic_reserve_pct > 0:
                reserve_area = lot.area * self.rules.septic_reserve_pct
                if reserve_area < 100:
                    return False
            if self.rules.well_protection_radius > 0:
                if lot.width_min < self.rules.well_protection_radius * 1.5:
                    return False

        if self.rules.service_type == ServiceType.FUTURE_MUNICIPAL:
            return True

        if self.rules.service_type == ServiceType.UNKNOWN:
            if lot.area < self.rules.min_lot_area * 1.2:
                return False

        return True

    def _check_constraint_conflicts(self, lot: Lot) -> list[str]:
        """Check if the lot overlaps with any constraint areas."""
        conflicts = []
        for ca in self.constraint_areas:
            if lot.geometry.intersects(ca.geometry):
                overlap_pct = lot.geometry.intersection(ca.geometry).area / lot.area * 100
                if overlap_pct > 5:
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
                − p_approval × failed_residential_count
    """

    def __init__(self, rules: LayoutRules):
        self.rules = rules

    def score_layout(self, result: LayoutResult) -> LayoutResult:
        """Compute all scores for a layout result.

        Scoring uses ONLY residential lots for yield, quality, and penalties.
        Remainder lots are excluded from yield but reported separately.
        """
        r = result
        w = self.rules

        residential = r.residential_lots
        passing = [l for l in residential if l.passes_all]
        failing = [l for l in residential if not l.passes_all]

        # ── Lot Yield Score ──
        # Passing residential lots relative to theoretical max
        theoretical_max = r.gross_area / (w.min_lot_area * 1.2)
        if theoretical_max > 0:
            r.score.lot_yield_score = min(len(passing) / theoretical_max, 1.0) * 100
        else:
            r.score.lot_yield_score = 0

        # ── Lot Quality Score ──
        # Average shape quality of passing residential lots
        if passing:
            avg_shape = sum(l.shape_quality for l in passing) / len(passing)
            avg_area_ratio = sum(l.area / w.min_lot_area for l in passing) / len(passing)
            r.score.lot_quality_score = math.sqrt(avg_shape * min(avg_area_ratio, 2.0)) * 50
        else:
            r.score.lot_quality_score = 0

        # ── Road Efficiency Score ──
        if r.total_road_length > 0:
            lpm = len(residential) / r.total_road_length
            r.score.road_efficiency_score = min(lpm / 0.08, 1.0) * 100
        else:
            r.score.road_efficiency_score = 100

        # ── Constraint Avoidance Score ──
        lots_with_conflicts = sum(1 for l in residential if l.constraint_conflicts)
        if len(residential) > 0:
            conflict_free_ratio = 1 - (lots_with_conflicts / len(residential))
            r.score.constraint_avoidance_score = conflict_free_ratio * 100
        else:
            r.score.constraint_avoidance_score = 0

        # ── Service Feasibility Score ──
        service_passing = sum(1 for l in residential if l.passes_service)
        if len(residential) > 0:
            r.score.service_feasibility_score = (service_passing / len(residential)) * 100
        else:
            r.score.service_feasibility_score = 0

        # ── Future Expansion Score ──
        # Remainder area as % of gross — sweet spot 10-20%
        if r.gross_area > 0:
            remainder_pct = r.remainder_area / r.gross_area
            if 0.05 < remainder_pct < 0.25:
                r.score.future_expansion_score = 100
            elif remainder_pct >= 0.25:
                r.score.future_expansion_score = 50
            else:
                r.score.future_expansion_score = 20
        else:
            r.score.future_expansion_score = 0

        # ── Penalties ──
        # Irregular count = IRREGULAR residential lots only (not remainders)
        irregular_count = sum(1 for l in residential if l.lot_type == LotType.IRREGULAR)
        r.score.irregular_lot_penalty = irregular_count * w.p_irregular_lot * 10
        r.score.long_road_penalty = r.total_road_length * w.p_long_road
        # Approval risk = failed RESIDENTIAL lots only (not remainders)
        r.score.approval_risk_penalty = len(failing) * w.p_approval_risk * 10

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
        failed_residential = [l for l in result.lots if l.is_residential and not l.passes_all]
        if failed_residential:
            fail_reasons = {}
            for lot in failed_residential:
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

        remainder = result.remainder_lots
        if remainder:
            lines.append(f"  Remainder: {len(remainder)} pieces ({result.remainder_area:.0f}m²) — excluded from yield.")

        if result.remaining_developable > result.gross_area * 0.15:
            lines.append(f"  {result.remaining_developable:.0f}m² leftover — consider future phase.")

        return " ".join(lines)