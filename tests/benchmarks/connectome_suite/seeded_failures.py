from __future__ import annotations

from types import SimpleNamespace

from claw.core.models import FitBucket, SlotRisk, TransferMode
from claw.web.dashboard_server import _build_retrograde_payload


def _packet(
    *,
    slot_name: str,
    slot_id: str,
    risk: SlotRisk,
    selected_component_id: str,
    selected_transfer: TransferMode,
    runner_component_id: str,
    runner_transfer: TransferMode,
) -> SimpleNamespace:
    return SimpleNamespace(
        packet_id=f"pkt_{slot_id}",
        slot=SimpleNamespace(slot_id=slot_id, name=slot_name, risk=risk),
        selected=SimpleNamespace(
            component_id=selected_component_id,
            transfer_mode=selected_transfer,
            fit_bucket=FitBucket.WILL_HELP,
        ),
        runner_ups=[
            SimpleNamespace(
                component_id=runner_component_id,
                transfer_mode=runner_transfer,
                why_fit=["native async lock semantics", "lower adaptation burden"],
            )
        ],
    )


SEEDED_RETROGRADE_CASES = [
    {
        "id": "critical_pattern_transfer_failure",
        "payload": lambda: _build_retrograde_payload(
            run_id="run_seed_1",
            root="test:test_parallel_refresh_single_lock",
            failing_outcome=SimpleNamespace(
                id="out_1",
                packet_id="pkt_slot_refresh",
                slot_id="slot_refresh",
                success=False,
                verifier_findings=["race in refresh state"],
            ),
            packet=_packet(
                slot_name="token_refresh",
                slot_id="slot_refresh",
                risk=SlotRisk.CRITICAL,
                selected_component_id="comp_sync_wrapper",
                selected_transfer=TransferMode.PATTERN_TRANSFER,
                runner_component_id="comp_async_lock",
                runner_transfer=TransferMode.DIRECT_FIT,
            ),
            pair=SimpleNamespace(component_id="comp_sync_wrapper"),
            landing=SimpleNamespace(id="land_1", file_path="app/auth/session.py"),
            slot_execution=SimpleNamespace(
                slot_id="slot_refresh",
                retry_count=2,
                current_step="verifying",
                blocked_wait_ms=0,
                family_wait_ms=0,
            ),
            runner_up=SimpleNamespace(
                component_id="comp_async_lock",
                transfer_mode=TransferMode.DIRECT_FIT,
                why_fit=["native async lock semantics", "lower adaptation burden"],
            ),
            relevant_audits=[],
            relevant_events=[],
            task_description="Fix token refresh races in the OAuth client",
        ),
        "expected_top_kinds": {"counterfactual", "federation", "component", "slot"},
    },
    {
        "id": "banned_family_wait_failure",
        "payload": lambda: _build_retrograde_payload(
            run_id="run_seed_2",
            root=None,
            failing_outcome=SimpleNamespace(
                id="out_2",
                packet_id="pkt_slot_client",
                slot_id="slot_client",
                success=False,
                verifier_findings=["rate limit burst"],
            ),
            packet=_packet(
                slot_name="api_client",
                slot_id="slot_client",
                risk=SlotRisk.NORMAL,
                selected_component_id="comp_throttle_old",
                selected_transfer=TransferMode.HEURISTIC_FALLBACK,
                runner_component_id="comp_throttle_new",
                runner_transfer=TransferMode.DIRECT_FIT,
            ),
            pair=SimpleNamespace(component_id="comp_throttle_old"),
            landing=SimpleNamespace(id="land_2", file_path="app/sync/client.py"),
            slot_execution=SimpleNamespace(
                slot_id="slot_client",
                retry_count=3,
                current_step="blocked",
                blocked_wait_ms=0,
                family_wait_ms=12000,
            ),
            runner_up=SimpleNamespace(
                component_id="comp_throttle_new",
                transfer_mode=TransferMode.DIRECT_FIT,
                why_fit=["direct rate-limit policy", "lower fallback burden"],
            ),
            relevant_audits=[
                SimpleNamespace(id="audit_1", action_type="ban_family", reason="family caused repeated bursts"),
            ],
            relevant_events=[
                SimpleNamespace(id="evt_1", event_type="retry_delta", payload={"violations": ["burst", "retry storm"]}),
            ],
            task_description="Fix rate limit bursts in external sync",
        ),
        "expected_top_kinds": {"action", "slot_execution", "retry"},
    },
    {
        "id": "critical_proof_gate_failure",
        "payload": lambda: _build_retrograde_payload(
            run_id="run_seed_3",
            root="verifier:static-analysis",
            failing_outcome=SimpleNamespace(
                id="out_3",
                packet_id="pkt_slot_exec",
                slot_id="slot_exec",
                success=False,
                verifier_findings=["semgrep: shell=true in critical exec path", "codeql: tainted subprocess flow"],
            ),
            packet=_packet(
                slot_name="external_execution",
                slot_id="slot_exec",
                risk=SlotRisk.CRITICAL,
                selected_component_id="comp_shell_runner",
                selected_transfer=TransferMode.DIRECT_FIT,
                runner_component_id="comp_safe_runner",
                runner_transfer=TransferMode.DIRECT_FIT,
            ),
            pair=SimpleNamespace(component_id="comp_shell_runner"),
            landing=SimpleNamespace(id="land_3", file_path="src/claw/cli/_monolith.py"),
            slot_execution=SimpleNamespace(
                slot_id="slot_exec",
                retry_count=1,
                current_step="verifying",
                blocked_wait_ms=0,
                family_wait_ms=0,
            ),
            runner_up=SimpleNamespace(
                component_id="comp_safe_runner",
                transfer_mode=TransferMode.DIRECT_FIT,
                why_fit=["avoids shell invocation", "lower policy burden"],
            ),
            relevant_audits=[],
            relevant_events=[
                SimpleNamespace(
                    id="evt_pf_1",
                    event_type="proof_gate_failed",
                    payload={
                        "gates": {
                            "semgrep": {"status": "failed", "details": ["shell=true"], "findings": ["shell=true"]},
                            "codeql": {"status": "failed", "details": ["tainted subprocess"], "findings": ["tainted subprocess"]},
                        }
                    },
                )
            ],
            task_description="Harden subprocess execution in a critical path",
        ),
        "expected_top_kinds": {"proof_gate", "outcome", "component", "slot"},
    },
    {
        "id": "waived_proof_gate_negative_memory_failure",
        "payload": lambda: _build_retrograde_payload(
            run_id="run_seed_4",
            root="verifier:waived-static-analysis",
            failing_outcome=SimpleNamespace(
                id="out_4",
                packet_id="pkt_slot_sandbox",
                slot_id="slot_sandbox",
                success=False,
                verifier_findings=["semgrep: unsafe shell call"],
                negative_memory_updates=["shell wrapper remains unsafe even after waiver"],
            ),
            packet=_packet(
                slot_name="sandboxing",
                slot_id="slot_sandbox",
                risk=SlotRisk.CRITICAL,
                selected_component_id="comp_shell_wrapper",
                selected_transfer=TransferMode.PATTERN_TRANSFER,
                runner_component_id="comp_safe_wrapper",
                runner_transfer=TransferMode.DIRECT_FIT,
            ),
            pair=SimpleNamespace(component_id="comp_shell_wrapper"),
            landing=SimpleNamespace(id="land_4", file_path="src/claw/security/policy.py"),
            slot_execution=SimpleNamespace(
                slot_id="slot_sandbox",
                retry_count=2,
                current_step="verifying",
                blocked_wait_ms=0,
                family_wait_ms=0,
            ),
            runner_up=SimpleNamespace(
                component_id="comp_safe_wrapper",
                transfer_mode=TransferMode.DIRECT_FIT,
                why_fit=["avoids shell invocation", "policy-aligned implementation"],
            ),
            relevant_audits=[
                SimpleNamespace(id="audit_waive", action_type="waive_proof_gate", reason="local mode waiver"),
            ],
            relevant_events=[
                SimpleNamespace(
                    id="evt_pf_2",
                    event_type="proof_gate_failed",
                    payload={"gates": {"semgrep": {"status": "failed", "details": ["unsafe shell call"], "findings": ["unsafe shell call"]}}},
                ),
                SimpleNamespace(
                    id="evt_retry_2",
                    event_type="retry_delta",
                    payload={"violations": ["unsafe shell call"]},
                ),
            ],
            task_description="Harden sandbox execution wrapper",
        ),
        "expected_top_kinds": {"proof_gate", "action", "negative_memory"},
    },
]
