from __future__ import annotations

import time
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from claw.core.models import (
    ApplicationPacket,
    ComponentCard,
    CompiledRecipe,
    CoverageState,
    OutcomeEvent,
    PairEvent,
    Receipt,
    RunActionAudit,
    RunConnectome,
    RunEvent,
    RunSlotExecution,
    TaskPlanRecord,
)
from claw.planning.application_packet import build_packet_summary


class InMemoryBenchmarkRepo:
    def __init__(self, cards: list[ComponentCard]) -> None:
        self.cards = {card.id: card for card in cards}
        self.task_plans: dict[str, TaskPlanRecord] = {}
        self.packets: dict[str, ApplicationPacket] = {}
        self.run_slot_executions: dict[str, list[RunSlotExecution]] = {}
        self.run_connectomes: dict[str, RunConnectome] = {}
        self.connectome_edges: dict[str, list[dict[str, object]]] = {}
        self.run_pairs: dict[str, list[PairEvent]] = {}
        self.run_landings: dict[str, list] = {}
        self.run_outcomes: dict[str, list[OutcomeEvent]] = {}
        self.run_events: dict[str, list[RunEvent]] = {}
        self.run_audits: dict[str, list[RunActionAudit]] = {}
        self.compiled_recipes: dict[str, CompiledRecipe] = {}
        self.engine = SimpleNamespace(fetch_all=self._fetch_all, close=self._close)

    async def _close(self) -> None:
        return None

    async def _fetch_all(self, _query: str, _params=None):
        return []

    async def search_component_cards_text(self, _q: str, limit: int = 8, language: str | None = None):
        cards = [
            SimpleNamespace(id=card.id, family_barcode=card.receipt.family_barcode)
            for card in self.cards.values()
            if language is None or (card.language or "").lower() == language.lower()
        ]
        return cards[:limit]

    async def list_component_cards(self, limit: int = 12, language: str | None = None):
        return await self.search_component_cards_text("", limit=limit, language=language)

    async def get_component_card(self, component_id: str):
        return self.cards.get(component_id)

    async def find_component_fit(self, *_args, **_kwargs):
        return []

    async def list_governance_policies(self, *_, **__):
        return []

    async def list_compiled_recipes(self, task_archetype: str | None = None, active_only: bool = False, limit: int = 50):
        items = list(self.compiled_recipes.values())
        if task_archetype:
            items = [item for item in items if item.task_archetype == task_archetype]
        if active_only:
            items = [item for item in items if item.is_active]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        return items[:limit]

    async def get_compiled_recipe(self, recipe_id: str):
        return self.compiled_recipes.get(recipe_id)

    async def save_compiled_recipe(self, recipe: CompiledRecipe):
        self.compiled_recipes[recipe.id] = recipe
        return recipe

    async def save_application_packet(self, packet: ApplicationPacket):
        self.packets[packet.packet_id] = packet

    async def get_application_packet(self, packet_id: str):
        return self.packets.get(packet_id)

    async def list_packets_for_plan(self, plan_id: str):
        items = [packet for packet in self.packets.values() if packet.plan_id == plan_id]
        return [build_packet_summary(item) for item in items]

    async def save_slot_instance(self, slot, task_archetype: str | None = None):
        return slot

    async def save_task_plan(self, plan: TaskPlanRecord):
        self.task_plans[plan.id] = plan
        return plan

    async def get_task_plan(self, plan_id: str):
        return self.task_plans.get(plan_id)

    async def create_project(self, _project):
        return None

    async def create_task(self, _task):
        return None

    async def save_run_slot_execution(self, execution: RunSlotExecution):
        items = self.run_slot_executions.setdefault(execution.run_id, [])
        for idx, item in enumerate(items):
            if item.slot_id == execution.slot_id:
                items[idx] = execution
                break
        else:
            items.append(execution)
        return execution

    async def list_run_slot_executions(self, run_id: str):
        return list(self.run_slot_executions.get(run_id, []))

    async def save_run_connectome(self, connectome: RunConnectome):
        self.run_connectomes[connectome.run_id] = connectome
        return connectome

    async def get_run_connectome(self, run_id: str):
        return self.run_connectomes.get(run_id)

    async def save_run_connectome_edge(self, connectome_id: str, *, source_node: str, target_node: str, edge_type: str, metadata: dict[str, object] | None = None):
        self.connectome_edges.setdefault(connectome_id, []).append(
            {
                "source_node": source_node,
                "target_node": target_node,
                "edge_type": edge_type,
                "metadata": metadata or {},
            }
        )
        return None

    async def list_run_connectome_edges(self, connectome_id: str):
        return list(self.connectome_edges.get(connectome_id, []))

    async def save_pair_event(self, event: PairEvent):
        self.run_pairs.setdefault(event.run_id, []).append(event)
        return event

    async def list_run_pair_events(self, run_id: str):
        return list(self.run_pairs.get(run_id, []))

    async def save_landing_event(self, event):
        self.run_landings.setdefault(event.run_id, []).append(event)
        return event

    async def list_run_landing_events(self, run_id: str):
        return list(self.run_landings.get(run_id, []))

    async def save_outcome_event(self, event: OutcomeEvent):
        self.run_outcomes.setdefault(event.run_id, []).append(event)
        return event

    async def list_run_outcome_events(self, run_id: str):
        return list(self.run_outcomes.get(run_id, []))

    async def save_run_event(self, event: RunEvent):
        self.run_events.setdefault(event.run_id, []).append(event)
        return event

    async def list_run_events(self, run_id: str):
        return list(self.run_events.get(run_id, []))

    async def save_run_action_audit(self, audit: RunActionAudit):
        self.run_audits.setdefault(audit.run_id, []).append(audit)
        return audit

    async def list_run_action_audits(self, run_id: str):
        return list(self.run_audits.get(run_id, []))

    async def update_component_outcome(self, component_id: str, success: bool):
        card = self.cards[component_id]
        if success:
            card.success_count += 1
        else:
            card.failure_count += 1
        return card


class _FakeVerification:
    def __init__(self) -> None:
        self.violations = []
        self.tests_after = 3


class _FakeOutcome:
    def __init__(self, files_changed: list[str]) -> None:
        self.files_changed = files_changed


class _FakeCycleResult:
    def __init__(self, *, files_changed: list[str]) -> None:
        self.success = True
        self.verification = _FakeVerification()
        self.outcome = _FakeOutcome(files_changed)

    def model_dump(self) -> dict[str, object]:
        return {
            "success": self.success,
            "verification": {"violations": self.verification.violations, "tests_after": self.verification.tests_after},
            "outcome": {"files_changed": self.outcome.files_changed},
        }


class _FakeMicroClaw:
    workspace_root: Path | None = None

    def __init__(self, *_, **__) -> None:
        self._current_verification = _FakeVerification()
        self._current_context_brief = None

    async def run_cycle(self, on_step=None):
        if on_step:
            on_step("analyze", "analyzing slot")
            on_step("write", "writing slot changes")
            self._current_verification = _FakeVerification()
            on_step("verify", "verifying slot")
        if self.workspace_root is not None:
            target = self.workspace_root / "app" / "token_refresh.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            existing = target.read_text(encoding="utf-8") if target.exists() else ""
            target.write_text(existing + "# reviewed run mutation\n", encoding="utf-8")
        return _FakeCycleResult(files_changed=["app/token_refresh.py"])


def _component(component_id: str, family_barcode: str, *, title: str, abstract_jobs: list[str]) -> ComponentCard:
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
        success_count=2,
        failure_count=0,
    )


def _build_client(repo: InMemoryBenchmarkRepo) -> TestClient:
    from claw.web import dashboard_server
    from claw.web.dashboard_server import app as dash_app

    dashboard_server._state.clear()
    dashboard_server._playground_ctx = None
    dash_app.state.playground_jobs = {}
    dash_app.state.playground_plans = {}

    feature_flags = SimpleNamespace(
        component_cards=True,
        application_packets=True,
        connectome_seq=True,
        critical_slot_policy=False,
        a2a_packets=True,
    )
    config = SimpleNamespace(feature_flags=feature_flags)
    dashboard_server._state["config"] = config
    dashboard_server._state["engine"] = repo.engine
    dashboard_server._state["repository"] = repo
    dashboard_server._state["federation"] = None
    dashboard_server._state["ready"] = True
    return TestClient(dash_app)


def _wait_for_run_completion(client: TestClient, run_id: str, attempts: int = 80) -> dict[str, object]:
    for _ in range(attempts):
        resp = client.get(f"/api/v2/runs/{run_id}")
        data = resp.json()
        if data.get("status") in {"completed", "failed", "error"}:
            return data
        time.sleep(0.05)
    raise AssertionError(f"run {run_id} did not complete in time")


def run_live_reviewed_benchmark() -> dict[str, object]:
    cards = [
        _component("comp_direct", "fam_auth", title="refresh_access_token", abstract_jobs=["token_refresh_serialization"]),
        _component("comp_other", "fam_other", title="oauth_session_helper", abstract_jobs=["authenticated_api_client"]),
    ]
    repo = InMemoryBenchmarkRepo(cards)
    client = _build_client(repo)

    from claw.web import dashboard_server

    fake_ctx = SimpleNamespace(repository=repo, config=SimpleNamespace(feature_flags=SimpleNamespace(
        component_cards=True,
        application_packets=True,
        connectome_seq=True,
        critical_slot_policy=False,
        a2a_packets=True,
    )))

    run_ids: list[str] = []
    with TemporaryDirectory() as tmp_dir:
        workspace = Path(tmp_dir)
        target_file = workspace / "app" / "token_refresh.py"
        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text("def refresh_session():\n    return True\n", encoding="utf-8")
        _FakeMicroClaw.workspace_root = workspace

        with patch("claw.web.dashboard_server._ensure_playground_ctx", new=AsyncMock(return_value=fake_ctx)), patch(
            "claw.cycle.MicroClaw",
            _FakeMicroClaw,
        ):
            for _ in range(4):
                create = client.post(
                    "/api/v2/plans",
                    json={"task_text": "Add OAuth session handling with token refresh", "workspace_dir": str(workspace)},
                ).json()
                slot_ids = [slot["slot_id"] for slot in create["slots"]]
                client.post(f"/api/v2/plans/{create['plan_id']}/approve", json={"slot_ids": slot_ids})
                execute = client.post(f"/api/v2/plans/{create['plan_id']}/execute", json={"approved_slot_ids": slot_ids}).json()
                run_id = execute["session_id"]
                run_ids.append(run_id)
                status = _wait_for_run_completion(client, run_id)
                assert status["status"] == "completed"

            fourth_plan_id = create["plan_id"]
            fourth_plan = client.get(f"/api/v2/plans/{fourth_plan_id}").json()
            fourth_packet = fourth_plan["packets"][0]
            fourth_distill = client.get(f"/api/v2/runs/{run_ids[-1]}/distill").json()
            final_contents = target_file.read_text(encoding="utf-8")
            final_landings = list(repo.run_landings.get(run_ids[-1], []))

    active_recipes = [recipe for recipe in repo.compiled_recipes.values() if recipe.is_active]
    return {
        "run_count": len(run_ids),
        "completed_runs": len(repo.run_connectomes),
        "connectome_count": len(repo.run_connectomes),
        "active_recipe_count": len(active_recipes),
        "fourth_packet_confidence_basis": fourth_packet["confidence_basis"],
        "fourth_packet_selected_component": fourth_packet["selected"]["component_id"],
        "fourth_packet_family_barcode": fourth_packet["selected"]["receipt"]["family_barcode"],
        "fourth_distill_recipe_count": len(fourth_distill["compiled_recipes"]),
        "workspace_mutation_count": final_contents.count("# reviewed run mutation"),
        "final_landing_count": len(final_landings),
    }
