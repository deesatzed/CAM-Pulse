from __future__ import annotations

from claw.core.models import (
    ApplicationPacket,
    ComponentCard,
    ComponentFit,
    CoverageState,
    FitBucket,
    GovernancePolicy,
    Receipt,
    SlotRisk,
    SlotSpec,
    TransferMode,
)
from claw.memory.component_ranker import rank_components_for_slot
from claw.planning.application_packet import build_application_packet


def _slot() -> SlotSpec:
    return SlotSpec(
        slot_id="slot_refresh",
        slot_barcode="slotbc_refresh",
        name="token_refresh",
        abstract_job="token_refresh_serialization",
        risk=SlotRisk.CRITICAL,
        constraints=["async", "review_required"],
        target_stack=["python", "fastapi"],
        proof_expectations=["tests", "verifier", "human_review"],
    )


def _card(
    component_id: str,
    *,
    title: str,
    abstract_jobs: list[str],
    family_barcode: str,
    language: str = "python",
    frameworks: list[str] | None = None,
    dependencies: list[str] | None = None,
    applicability: list[str] | None = None,
    test_evidence: list[str] | None = None,
    non_applicability: list[str] | None = None,
    keywords: list[str] | None = None,
    success_count: int = 2,
    failure_count: int = 0,
) -> ComponentCard:
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
        language=language,
        frameworks=frameworks or ["fastapi"],
        dependencies=dependencies or ["httpx"],
        non_applicability=non_applicability or [],
        applicability=applicability or ["python", "oauth", "async"],
        keywords=keywords or ["oauth", "token", "refresh"],
        test_evidence=test_evidence or ["pytest"],
        coverage_state=CoverageState.COVERED,
        success_count=success_count,
        failure_count=failure_count,
    )


def _fit(component_id: str, confidence: float) -> ComponentFit:
    return ComponentFit(
        component_id=component_id,
        task_archetype="oauth_session_management",
        component_type="helper",
        slot_signature="token_refresh",
        fit_bucket=FitBucket.WILL_HELP,
        transfer_mode=TransferMode.DIRECT_FIT,
        confidence=confidence,
        confidence_basis=["prior_pair_success"],
        success_count=3,
        failure_count=0,
        evidence_count=3,
        notes=["learned from repeated success"],
    )


def _family_policy(family_barcode: str) -> GovernancePolicy:
    return GovernancePolicy(
        task_archetype="oauth_session_management",
        family_barcode=family_barcode,
        policy_kind="family_policy",
        severity="high",
        reason="family fails async refresh paths",
        recommendation="prefer direct-fit async implementations",
    )


def run_multi_layer_ablation() -> dict[str, object]:
    slot = _slot()
    direct_fit_card = _card(
        "comp_direct",
        title="token refresh async adapter",
        abstract_jobs=["async_refresh_adapter"],
        family_barcode="fam_async_direct",
        language="typescript",
        frameworks=[],
        dependencies=[],
        applicability=[],
        test_evidence=[],
        keywords=[],
    )
    transfer_card = _card(
        "comp_transfer",
        title="token refresh wrapper",
        abstract_jobs=["authenticated_api_client"],
        family_barcode="fam_sync_wrapper",
        frameworks=[],
        dependencies=[],
        applicability=[],
        test_evidence=[],
        non_applicability=["async wrapper mismatch"],
        keywords=[],
        success_count=1,
    )
    candidates = [transfer_card, direct_fit_card]

    baseline_ranked = rank_components_for_slot(slot, candidates, fit_rows=[], governance_policies=[], target_language="python", target_stack_hints=["fastapi"])
    fit_ranked = rank_components_for_slot(slot, candidates, fit_rows=[_fit("comp_direct", 0.92)], governance_policies=[], target_language="python", target_stack_hints=["fastapi"])
    governed_ranked = rank_components_for_slot(slot, candidates, fit_rows=[_fit("comp_direct", 0.92)], governance_policies=[_family_policy("fam_sync_wrapper")], target_language="python", target_stack_hints=["fastapi"])

    baseline_packet: ApplicationPacket = build_application_packet("plan_base", "oauth_session_management", slot, baseline_ranked, governance_policies=[])
    governed_packet: ApplicationPacket = build_application_packet("plan_gov", "oauth_session_management", slot, governed_ranked, governance_policies=[_family_policy("fam_sync_wrapper")])

    return {
        "baseline_selected": baseline_ranked[0].component_id,
        "fit_selected": fit_ranked[0].component_id,
        "governed_selected": governed_ranked[0].component_id,
        "baseline_packet_review_reasons": baseline_packet.review_required_reasons,
        "governed_packet_review_reasons": governed_packet.review_required_reasons,
        "baseline_transfer_mode": str(baseline_packet.selected.transfer_mode),
        "governed_transfer_mode": str(governed_packet.selected.transfer_mode),
    }
