from __future__ import annotations

from claw.core.models import (
    AdaptationBurden,
    CandidateSummary,
    ComponentCard,
    CoverageState,
    GovernancePolicy,
    Receipt,
    SlotRisk,
    SlotSpec,
)
from claw.memory.component_ranker import rank_components_for_slot
from claw.planning.application_packet import build_application_packet


def _card(component_id: str, family_barcode: str) -> ComponentCard:
    return ComponentCard(
        id=component_id,
        title=component_id,
        component_type="api_client",
        abstract_jobs=["token_refresh_serialization"],
        receipt=Receipt(
            source_barcode=f"src_{component_id}",
            family_barcode=family_barcode,
            lineage_id=f"lin_{component_id}",
            repo="org/service",
            file_path="app/auth.py",
            symbol=component_id,
            content_hash=f"sha256:{component_id}",
            provenance_precision="symbol",
        ),
        language="python",
        applicability=["oauth", "token", "refresh"],
        test_evidence=["tests/test_auth.py"],
        coverage_state=CoverageState.COVERED,
    )


def _slot() -> SlotSpec:
    return SlotSpec(
        slot_id="slot_refresh",
        slot_barcode="slotbc_refresh",
        name="token_refresh",
        abstract_job="token_refresh_serialization",
        risk=SlotRisk.CRITICAL,
        constraints=["async"],
        target_stack=["python", "httpx"],
        proof_expectations=["tests", "verifier"],
    )


def test_policy_benchmark_family_policy_changes_top_candidate():
    slot = _slot()
    governed = _card("comp_governed", "fam_governed")
    direct = _card("comp_safe", "fam_safe")
    policies = [
        GovernancePolicy(
            task_archetype="oauth_session_management",
            family_barcode="fam_governed",
            policy_kind="family_policy",
            severity="high",
            reason="unsafe async lineage",
            recommendation="quarantine family",
        )
    ]
    ranked = rank_components_for_slot(
        slot,
        [governed, direct],
        governance_policies=policies,
        target_language="python",
        target_stack_hints=["httpx"],
    )
    assert ranked[0].component_id == "comp_safe"
    assert ranked[1].component_id == "comp_governed"


def test_policy_benchmark_proof_policy_adds_governance_review_gate():
    slot = _slot()
    candidate = CandidateSummary(
        component_id="comp_safe",
        title="comp_safe",
        fit_bucket="will_help",
        transfer_mode="direct_fit",
        confidence=0.9,
        confidence_basis=["abstract_job_match"],
        receipt=Receipt(
            source_barcode="src_comp_safe",
            family_barcode="fam_safe",
            lineage_id="lin_safe",
            repo="org/service",
            file_path="app/auth.py",
            symbol="comp_safe",
            content_hash="sha256:safe",
            provenance_precision="symbol",
        ),
        why_fit=["same abstract job"],
        adaptation_burden=AdaptationBurden.LOW,
    )
    packet = build_application_packet(
        "plan_bench",
        "oauth_session_management",
        slot,
        [candidate],
        governance_policies=[
            GovernancePolicy(
                task_archetype="oauth_session_management",
                policy_kind="proof_policy",
                severity="medium",
                reason="critical slot needs stronger proof",
                recommendation="require governance review",
            )
        ],
    )
    gate_ids = {gate.gate_id for gate in packet.proof_plan}
    assert "governance_review" in gate_ids
    assert "governance_proof_policy" in packet.review_required_reasons
