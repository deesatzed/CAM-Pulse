from __future__ import annotations

from claw.core.models import AdaptationBurden, CandidateSummary, FitBucket, GovernancePolicy, Receipt, SlotRisk, SlotSpec, TransferMode
from claw.planning.application_packet import build_application_packet, build_packet_summary


def _candidate(component_id: str, fit_bucket: str, transfer_mode: str, confidence: float = 0.8):
    return CandidateSummary(
        component_id=component_id,
        title=component_id,
        fit_bucket=fit_bucket,
        transfer_mode=transfer_mode,
        confidence=confidence,
        confidence_basis=["test"],
        receipt=Receipt(
            source_barcode=f"src_{component_id}",
            family_barcode="fam_x",
            lineage_id="lin_1",
            repo="org/service",
            file_path="app/file.py",
            symbol=component_id,
            content_hash=f"sha256:{component_id}",
            provenance_precision="symbol",
        ),
        why_fit=["same abstract job"],
        adaptation_burden=AdaptationBurden.LOW,
    )


def test_build_packet_with_runner_up():
    slot = SlotSpec(
        slot_id="slot_1",
        slot_barcode="slot_bc_1",
        name="token_refresh",
        abstract_job="token_refresh_serialization",
        risk=SlotRisk.CRITICAL,
        constraints=["async"],
        target_stack=["python"],
        proof_expectations=["tests", "verifier"],
    )
    packet = build_application_packet(
        "plan_1",
        "oauth_session_management",
        slot,
        [
            _candidate("comp_a", FitBucket.WILL_HELP.value, TransferMode.DIRECT_FIT.value, 0.9),
            _candidate("comp_b", FitBucket.MAY_HELP.value, TransferMode.PATTERN_TRANSFER.value, 0.6),
        ],
    )
    summary = build_packet_summary(packet)
    assert packet.selected.component_id == "comp_a"
    assert packet.runner_ups
    assert packet.reviewer_required is True
    assert summary.selected_component_id == "comp_a"


def test_build_packet_marks_weak_when_only_stretch_exists():
    slot = SlotSpec(
        slot_id="slot_2",
        slot_barcode="slot_bc_2",
        name="token_refresh",
        abstract_job="token_refresh_serialization",
        risk=SlotRisk.CRITICAL,
        constraints=[],
        target_stack=["python"],
        proof_expectations=["tests"],
    )
    packet = build_application_packet(
        "plan_1",
        "oauth_session_management",
        slot,
        [_candidate("comp_c", FitBucket.STRETCH.value, TransferMode.PATTERN_TRANSFER.value, 0.42)],
    )
    assert packet.coverage_state.value == "weak"
    assert packet.review_required_reasons


def test_build_packet_escalates_from_governance_policies():
    slot = SlotSpec(
        slot_id="slot_3",
        slot_barcode="slot_bc_3",
        name="token_refresh",
        abstract_job="token_refresh_serialization",
        risk=SlotRisk.NORMAL,
        constraints=[],
        target_stack=["python"],
        proof_expectations=["tests"],
    )
    packet = build_application_packet(
        "plan_1",
        "oauth_session_management",
        slot,
        [_candidate("comp_d", FitBucket.WILL_HELP.value, TransferMode.DIRECT_FIT.value, 0.88)],
        governance_policies=[
            GovernancePolicy(
                task_archetype="oauth_session_management",
                policy_kind="proof_policy",
                severity="medium",
                reason="repeated reverify pressure",
                recommendation="require governance review",
            ),
            GovernancePolicy(
                task_archetype="oauth_session_management",
                family_barcode="fam_x",
                policy_kind="family_policy",
                severity="high",
                reason="family is unstable in async refresh paths",
                recommendation="quarantine until direct-fit evidence improves",
            ),
        ],
    )
    assert "governance_proof_policy" in packet.review_required_reasons
    assert "governance_family_policy" in packet.review_required_reasons
    assert any(gate.gate_id == "governance_review" for gate in packet.proof_plan)
    assert packet.risk_notes
