"""Application packet construction for CAM-SEQ pre-mutation review."""

from __future__ import annotations

import uuid

from claw.core.models import (
    AdaptationStep,
    ApplicationPacket,
    ApplicationPacketSummary,
    CandidateSummary,
    CoverageState,
    ExpectedLandingSite,
    GovernancePolicy,
    PacketStatus,
    ProofGate,
    SlotRisk,
    SlotSpec,
)


def _review_required_reasons(
    slot: SlotSpec,
    selected: CandidateSummary,
    weak: bool,
    governance_policies: list[GovernancePolicy],
) -> list[str]:
    reasons: list[str] = []
    if slot.risk == SlotRisk.CRITICAL:
        reasons.append("critical_slot")
    if weak:
        reasons.append("weak_evidence")
    if selected.transfer_mode.value != "direct_fit":
        reasons.append("non_direct_fit")
    if selected.fit_bucket.value == "stretch" and slot.risk == SlotRisk.CRITICAL:
        reasons.append("critical_slot_no_direct_fit")
    if any(policy.policy_kind == "slot_policy" for policy in governance_policies):
        reasons.append("governance_slot_policy")
    if any(policy.policy_kind == "proof_policy" for policy in governance_policies):
        reasons.append("governance_proof_policy")
    if any(
        policy.policy_kind == "family_policy"
        and policy.family_barcode
        and policy.family_barcode == selected.receipt.family_barcode
        for policy in governance_policies
    ):
        reasons.append("governance_family_policy")
    return reasons


def choose_primary_candidate(slot: SlotSpec, ranked: list[CandidateSummary]) -> tuple[CandidateSummary, bool]:
    if not ranked:
        raise ValueError("cannot build packet without ranked candidates")
    viable = [c for c in ranked if c.fit_bucket.value != "no_help"]
    if not viable:
        return ranked[0], True
    for item in viable:
        if slot.risk == SlotRisk.CRITICAL and item.fit_bucket.value == "stretch":
            continue
        return item, False
    return viable[0], True


def _build_adaptation_plan(slot: SlotSpec, selected: CandidateSummary) -> list[AdaptationStep]:
    steps: list[AdaptationStep] = []
    if selected.transfer_mode.value != "direct_fit":
        steps.append(
            AdaptationStep(
                title="Adapt imported pattern to local conventions",
                rationale="transfer is not direct-fit",
                blocking=True,
            )
        )
    for constraint in slot.constraints[:2]:
        steps.append(
            AdaptationStep(
                title=f"Respect constraint: {constraint}",
                rationale="slot-level constraint captured during planning",
                blocking=constraint in {"async", "review_required"},
            )
        )
    if not steps:
        steps.append(
            AdaptationStep(
                title="Minimal wiring",
                rationale="direct-fit candidate with no special constraints",
                blocking=False,
            )
        )
    return steps[:4]


def _build_proof_plan(slot: SlotSpec, governance_policies: list[GovernancePolicy]) -> list[ProofGate]:
    gates: list[ProofGate] = []
    for expectation in slot.proof_expectations:
        gates.append(
            ProofGate(
                gate_id=expectation,
                gate_type=expectation,
                required=True,
            )
        )
    if slot.risk == SlotRisk.CRITICAL and not any(g.gate_type == "human_review" for g in gates):
        gates.append(ProofGate(gate_id="human_review", gate_type="human_review", required=True))
    if governance_policies:
        details = [
            policy.recommendation or policy.reason
            for policy in governance_policies[:3]
            if (policy.recommendation or policy.reason)
        ]
        gates.append(
            ProofGate(
                gate_id="governance_review",
                gate_type="human_review",
                required=True,
                details=details,
            )
        )
    return gates[:5]


def _expected_landing_sites(slot: SlotSpec) -> list[ExpectedLandingSite]:
    filename = slot.name.replace("_", "/")
    return [
        ExpectedLandingSite(
            file_path=f"app/{filename}.py",
            symbol=slot.name,
            rationale="slot-derived default landing guess",
        )
    ]


def build_application_packet(
    plan_id: str,
    task_archetype: str,
    slot: SlotSpec,
    ranked_candidates: list[CandidateSummary],
    governance_policies: list[GovernancePolicy] | None = None,
) -> ApplicationPacket:
    applicable_policies = [policy for policy in (governance_policies or []) if policy.status == "active"]
    selected, weak = choose_primary_candidate(slot, ranked_candidates)
    runner_ups = [c for c in ranked_candidates if c.component_id != selected.component_id][:2]
    no_viable_runner_up_reason = None if runner_ups else "no_viable_runner_up"
    review_reasons = _review_required_reasons(slot, selected, weak, applicable_policies)
    reviewer_required = bool(review_reasons)
    coverage_state = CoverageState.WEAK if weak else CoverageState.COVERED
    if selected.fit_bucket.value == "stretch":
        coverage_state = CoverageState.WEAK
    negative_memory = list(selected.known_failure_modes[:2])
    risk_notes = ["critical slot requires explicit review"] if slot.risk == SlotRisk.CRITICAL else []
    for policy in applicable_policies:
        if policy.policy_kind == "family_policy" and policy.family_barcode == selected.receipt.family_barcode:
            if policy.reason:
                negative_memory.append(policy.reason)
            if policy.recommendation:
                risk_notes.append(policy.recommendation)
        elif policy.policy_kind in {"slot_policy", "proof_policy"}:
            if policy.recommendation:
                risk_notes.append(policy.recommendation)

    return ApplicationPacket(
        packet_id=f"pkt_{uuid.uuid4().hex[:12]}",
        plan_id=plan_id,
        task_archetype=task_archetype,
        slot=slot,
        status=PacketStatus.REVIEW_REQUIRED if reviewer_required else PacketStatus.DRAFT,
        selected=selected,
        runner_ups=runner_ups,
        no_viable_runner_up_reason=no_viable_runner_up_reason,
        why_selected=selected.why_fit[:4] or ["highest ranked candidate"],
        why_runner_up_lost={
            runner.component_id: ["lower confidence than selected candidate"]
            for runner in runner_ups
        },
        adaptation_plan=_build_adaptation_plan(slot, selected),
        proof_plan=_build_proof_plan(slot, applicable_policies),
        expected_landing_sites=_expected_landing_sites(slot),
        negative_memory=list(dict.fromkeys(negative_memory))[:4],
        risk_notes=list(dict.fromkeys(risk_notes))[:4],
        reviewer_required=reviewer_required,
        review_required_reasons=review_reasons,
        confidence_basis=selected.confidence_basis,
        coverage_state=coverage_state,
    )


def build_packet_summary(packet: ApplicationPacket) -> ApplicationPacketSummary:
    return ApplicationPacketSummary(
        packet_id=packet.packet_id,
        plan_id=packet.plan_id,
        task_archetype=packet.task_archetype,
        slot_id=packet.slot.slot_id,
        slot_name=packet.slot.name,
        status=packet.status,
        selected_component_id=packet.selected.component_id,
        fit_bucket=packet.selected.fit_bucket,
        transfer_mode=packet.selected.transfer_mode,
        confidence=packet.selected.confidence,
        review_required=packet.reviewer_required,
        coverage_state=packet.coverage_state,
    )
