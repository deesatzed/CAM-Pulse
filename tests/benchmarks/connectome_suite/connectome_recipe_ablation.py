from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from claw.core.models import (
    ApplicationPacket,
    ComponentCard,
    ComponentFit,
    CoverageState,
    Receipt,
    SlotRisk,
    SlotSpec,
)
from claw.memory.component_ranker import rank_components_for_slot
from claw.planning.application_packet import build_application_packet
from claw.web.dashboard_server import _auto_distill_compiled_recipe


def _slot() -> SlotSpec:
    return SlotSpec(
        slot_id="slot_refresh",
        slot_barcode="slot_refresh_bc",
        name="token_refresh",
        abstract_job="token_refresh_serialization",
        risk=SlotRisk.CRITICAL,
        constraints=["async"],
        target_stack=["python", "fastapi"],
        proof_expectations=["tests", "verifier"],
    )


def _card(component_id: str, family_barcode: str, abstract_jobs: list[str], *, title: str) -> ComponentCard:
    return ComponentCard(
        id=component_id,
        title=title,
        component_type="helper",
        abstract_jobs=abstract_jobs,
        receipt=Receipt(
            source_barcode=f"src_{component_id}",
            family_barcode=family_barcode,
            lineage_id=f"lin_{component_id}",
            repo="org/service",
            file_path="app/auth.py",
            symbol=title,
            content_hash=f"sha256:{component_id}",
            provenance_precision="symbol",
        ),
        language="python",
        frameworks=["fastapi"],
        dependencies=["httpx"],
        applicability=["python", "oauth", "async"],
        keywords=["oauth", "token", "refresh"],
        test_evidence=["pytest"],
        coverage_state=CoverageState.COVERED,
        success_count=1,
        failure_count=0,
    )


def _fit(component_id: str, confidence: float) -> ComponentFit:
    return ComponentFit(
        component_id=component_id,
        task_archetype="oauth_session_management",
        component_type="helper",
        slot_signature="token_refresh",
        fit_bucket="will_help",
        transfer_mode="direct_fit",
        confidence=confidence,
        confidence_basis=["prior_pair_success"],
        success_count=3,
        failure_count=0,
        evidence_count=3,
        notes=["learned from repeated success"],
    )


async def run_connectome_recipe_ablation() -> dict[str, object]:
    slot = _slot()
    transfer_card = _card(
        "comp_transfer",
        "fam_transfer",
        ["authenticated_api_client"],
        title="token refresh wrapper",
    )
    transfer_card.failure_count = 2
    direct_card = _card(
        "comp_direct",
        "fam_direct",
        ["authenticated_api_client"],
        title="async refresh coordinator",
    )
    candidates = [transfer_card, direct_card]

    baseline_ranked = rank_components_for_slot(
        slot,
        candidates,
        fit_rows=[],
        compiled_recipes=[],
        governance_policies=[],
        target_language="python",
        target_stack_hints=["fastapi"],
    )
    learned_ranked = rank_components_for_slot(
        slot,
        candidates,
        fit_rows=[_fit("comp_direct", 0.92)],
        compiled_recipes=[],
        governance_policies=[],
        target_language="python",
        target_stack_hints=["fastapi"],
    )

    learned_packet: ApplicationPacket = build_application_packet(
        "plan_recipe",
        "oauth_session_management",
        slot,
        learned_ranked,
        governance_policies=[],
    )

    repo = AsyncMock()
    connectome = MagicMock(task_archetype="oauth_session_management")
    repo.get_compiled_recipe = AsyncMock(side_effect=[None, MagicMock(sample_size=1), MagicMock(sample_size=2)])
    repo.save_compiled_recipe = AsyncMock(side_effect=lambda recipe: recipe)

    await _auto_distill_compiled_recipe(repo, connectome, [learned_packet])
    await _auto_distill_compiled_recipe(repo, connectome, [learned_packet])
    active_recipe = await _auto_distill_compiled_recipe(repo, connectome, [learned_packet])

    recipe_ranked = rank_components_for_slot(
        slot,
        candidates,
        fit_rows=[],
        compiled_recipes=[active_recipe],
        governance_policies=[],
        target_language="python",
        target_stack_hints=["fastapi"],
    )

    return {
        "baseline_selected": baseline_ranked[0].component_id,
        "learned_selected": learned_ranked[0].component_id,
        "recipe_selected": recipe_ranked[0].component_id,
        "recipe_active": active_recipe.is_active,
        "recipe_sample_size": active_recipe.sample_size,
        "recipe_confidence_basis": recipe_ranked[0].confidence_basis,
    }
