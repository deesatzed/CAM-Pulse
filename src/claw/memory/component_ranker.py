"""Per-slot component ranking for CAM-SEQ."""

from __future__ import annotations

import re
from typing import Optional

from claw.core.models import (
    AdaptationBurden,
    CandidateSummary,
    ComponentCard,
    ComponentFit,
    CompiledRecipe,
    FitBucket,
    GovernancePolicy,
    SlotRisk,
    SlotSpec,
    TransferMode,
)


def _tokens(*parts: str) -> set[str]:
    tokens: set[str] = set()
    for part in parts:
        tokens.update(tok for tok in re.findall(r"[a-z0-9_]+", part.lower()) if len(tok) >= 3)
    return tokens


def _bucket_from_score(score: float) -> FitBucket:
    if score >= 0.75:
        return FitBucket.WILL_HELP
    if score >= 0.55:
        return FitBucket.MAY_HELP
    if score >= 0.35:
        return FitBucket.STRETCH
    return FitBucket.NO_HELP


def _transfer_mode(slot: SlotSpec, card: ComponentCard, score: float) -> TransferMode:
    if slot.abstract_job in card.abstract_jobs:
        return TransferMode.DIRECT_FIT
    if score >= 0.45:
        return TransferMode.PATTERN_TRANSFER
    return TransferMode.HEURISTIC_FALLBACK


def rank_components_for_slot(
    slot: SlotSpec,
    candidates: list[ComponentCard],
    *,
    fit_rows: Optional[list[ComponentFit]] = None,
    compiled_recipes: Optional[list[CompiledRecipe]] = None,
    governance_policies: Optional[list[GovernancePolicy]] = None,
    target_language: Optional[str] = None,
    target_stack_hints: Optional[list[str]] = None,
) -> list[CandidateSummary]:
    fit_by_component = {row.component_id: row for row in (fit_rows or [])}
    ranked: list[tuple[float, CandidateSummary]] = []
    stack = {item.lower() for item in (target_stack_hints or slot.target_stack or [])}
    slot_terms = _tokens(slot.name, slot.abstract_job, " ".join(slot.constraints), " ".join(slot.target_stack))

    for card in candidates:
        score = 0.15
        basis: list[str] = []
        why_fit: list[str] = []
        failure_modes = list(card.non_applicability[:3])
        matching_recipes = [
            recipe
            for recipe in (compiled_recipes or [])
            if recipe.is_active
            and card.receipt.family_barcode in set(recipe.recipe_json.get("preferred_families") or [])
        ]
        matching_family_policies = [
            policy
            for policy in (governance_policies or [])
            if policy.status == "active"
            and policy.policy_kind == "family_policy"
            and policy.family_barcode
            and policy.family_barcode == card.receipt.family_barcode
        ]

        if slot.abstract_job in card.abstract_jobs:
            score += 0.35
            basis.append("abstract_job_match")
            why_fit.append("same abstract job")

        if slot.name.replace("_", " ") in card.title.lower() or slot.name in card.component_type.lower():
            score += 0.12
            basis.append("slot_name_match")
            why_fit.append("slot intent matches title/type")

        if target_language and card.language and card.language.lower() == target_language.lower():
            score += 0.12
            basis.append("language_match")
            why_fit.append("same language")
        elif slot.target_stack and card.language and card.language.lower() in {s.lower() for s in slot.target_stack}:
            score += 0.10
            basis.append("stack_language_match")
            why_fit.append("language fits target stack")

        overlap = slot_terms & _tokens(card.title, card.component_type, " ".join(card.abstract_jobs), " ".join(card.keywords), " ".join(card.applicability))
        if overlap:
            score += min(0.18, 0.03 * len(overlap))
            basis.append("text_overlap")
            why_fit.append(f"shared terms: {', '.join(sorted(list(overlap))[:4])}")

        stack_overlap = stack & {item.lower() for item in [*card.frameworks, *card.dependencies]}
        if stack_overlap:
            score += min(0.10, 0.03 * len(stack_overlap))
            basis.append("framework_match")
            why_fit.append(f"stack match: {', '.join(sorted(stack_overlap)[:3])}")

        constraint_conflicts = {c.lower() for c in slot.constraints} & {c.lower() for c in card.non_applicability}
        if constraint_conflicts:
            score -= 0.35
            basis.append("constraint_conflict")
            why_fit.append("conflicts with stated constraints")

        if card.receipt.provenance_precision.value == "precise_symbol":
            score += 0.08
            basis.append("precise_receipt")
        elif card.receipt.provenance_precision.value == "symbol":
            score += 0.05
            basis.append("symbol_receipt")

        if card.test_evidence:
            score += 0.05
            basis.append("test_evidence")
            why_fit.append("has test evidence")

        score += min(0.08, 0.02 * card.success_count)
        score -= min(0.08, 0.02 * card.failure_count)

        fit_row = fit_by_component.get(card.id)
        if fit_row is not None:
            score += min(0.12, fit_row.confidence * 0.15)
            basis.extend([b for b in fit_row.confidence_basis if b not in basis][:3])
            if fit_row.notes:
                failure_modes.extend(fit_row.notes[:2])

        if matching_recipes:
            best_recipe_bonus = 0.0
            for recipe in matching_recipes:
                slot_order = recipe.recipe_json.get("slot_order") or []
                if slot.name in slot_order or slot.abstract_job in slot_order:
                    best_recipe_bonus = max(best_recipe_bonus, 0.14)
                else:
                    best_recipe_bonus = max(best_recipe_bonus, 0.08)
            score += best_recipe_bonus
            basis.append("recipe_family_preference")
            why_fit.append("matches active compiled recipe family")

        if matching_family_policies:
            highest = max(
                (
                    0.30
                    if policy.severity == "high"
                    else 0.18
                    if policy.severity == "medium"
                    else 0.10
                )
                for policy in matching_family_policies
            )
            score -= highest
            basis.append("governance_family_policy")
            why_fit.append("family is governed and requires extra scrutiny")
            for policy in matching_family_policies[:2]:
                if policy.reason:
                    failure_modes.append(policy.reason)
                if policy.recommendation:
                    failure_modes.append(policy.recommendation)

        score = max(0.0, min(score, 0.98))
        fit_bucket = _bucket_from_score(score)
        transfer_mode = _transfer_mode(slot, card, score)
        if slot.risk == SlotRisk.CRITICAL and fit_bucket == FitBucket.STRETCH:
            basis.append("critical_slot_penalty")

        burden = AdaptationBurden.LOW
        if transfer_mode == TransferMode.PATTERN_TRANSFER or slot.constraints:
            burden = AdaptationBurden.MEDIUM
        if fit_bucket in {FitBucket.STRETCH, FitBucket.NO_HELP} or constraint_conflicts:
            burden = AdaptationBurden.HIGH

        ranked.append(
            (
                score,
                CandidateSummary(
                    component_id=card.id,
                    title=card.title,
                    fit_bucket=fit_bucket,
                    transfer_mode=transfer_mode,
                    confidence=score,
                    confidence_basis=list(dict.fromkeys(basis)),
                    receipt=card.receipt,
                    why_fit=why_fit[:4],
                    known_failure_modes=list(dict.fromkeys(failure_modes))[:4],
                    prior_success_count=card.success_count,
                    prior_failure_count=card.failure_count,
                    deduped_lineage_count=1,
                    adaptation_burden=burden,
                ),
            )
        )

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [summary for _score, summary in ranked]
