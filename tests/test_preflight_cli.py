from __future__ import annotations

import json

import pytest
import typer


class TestPreflightAnswerHandling:
    def test_apply_answers_to_preflight_resolves_matching_questions_and_blockers(self):
        from claw import cli

        report = {
            "clarifying_questions": [
                {"priority": "must", "question": "What exact acceptance checks or demo outcomes will count as success?"},
                {"priority": "must", "question": "Are there domain constraints such as privacy, compliance, security, or auditability requirements?"},
            ],
            "hard_blockers": [
                "Domain constraints may require explicit compliance, privacy, or audit decisions before execution."
            ],
            "assumptions": [],
        }

        updated = cli._apply_answers_to_preflight(
            report,
            [
                "Acceptance checks: pytest -q and python -m app.cli --help",
                "Compliance: no PHI or PII, standard security only",
            ],
        )

        assert updated["clarifying_questions"] == []
        assert updated["hard_blockers"] == []
        assert len(updated["answered_questions"]) == 2
        assert updated["operator_answers"][0].startswith("Acceptance checks:")

    def test_answer_covers_question_matches_delivery_surface(self):
        from claw import cli

        assert cli._answer_covers_question(
            "What is the required delivery surface: CLI, web app, API, library, or mixed?",
            ["Delivery surface: web app with a small API"],
        ) is True

    def test_merge_preflight_answers_reuses_prior_artifact_answers(self):
        from claw import cli

        merged = cli._merge_preflight_answers(
            {"operator_answers": ["Acceptance checks: pytest -q", "Delivery surface: web app"]},
            ["Delivery surface: web app", "Transfer scope: UX and workflows"],
        )

        assert merged == [
            "Acceptance checks: pytest -q",
            "Delivery surface: web app",
            "Transfer scope: UX and workflows",
        ]

    def test_load_preflight_artifact_reads_json(self, tmp_path):
        from claw import cli

        artifact = tmp_path / "demo-preflight.json"
        artifact.write_text(json.dumps({"operator_answers": ["Acceptance checks: pytest -q"]}), encoding="utf-8")

        loaded = cli._load_preflight_artifact(str(artifact))

        assert loaded is not None
        assert loaded["operator_answers"] == ["Acceptance checks: pytest -q"]
        assert loaded["artifact_path"] == str(artifact)

    @pytest.mark.asyncio
    async def test_create_async_execute_unblocks_when_answers_cover_must_questions(self, tmp_path, monkeypatch):
        from claw import cli

        async def fake_preflight_async(**kwargs):
            report = {
                "artifact_path": str(tmp_path / "data" / "preflights" / "demo.json"),
                "hard_blockers": [],
                "clarifying_questions": [],
                "operator_answers": list(kwargs.get("answers", [])),
                "answered_questions": [
                    {"priority": "must", "question": "What exact acceptance checks or demo outcomes will count as success?"},
                    {"priority": "must", "question": "What is the required delivery surface: CLI, web app, API, library, or mixed?"},
                ],
                "recommended_mode": "proceed_now",
                "complexity": "medium",
                "task_kind": "greenfield_app_creation",
            }
            return report, tmp_path / "data" / "preflights" / "demo.json"

        async def fake_quickstart_async(**kwargs):
            return None

        monkeypatch.setattr(cli, "_run_preflight_async", fake_preflight_async)
        monkeypatch.setattr(cli, "_quickstart_async", fake_quickstart_async)

        await cli._create_async(
            repo_path=tmp_path / "demo",
            request="Build a risky app",
            repo_mode="new",
            title="Risky app",
            priority="high",
            task_type="architecture",
            agent=None,
            spec_items=[],
            execution_steps=[],
            acceptance_checks=[],
            answers=[
                "Acceptance checks: pytest -q and python -m app.cli --help",
                "Delivery surface: web app",
            ],
            preflight_file=None,
            preflight=True,
            auto_preflight=True,
            preflight_live=False,
            accept_preflight_defaults=False,
            preview=False,
            execute=True,
            config_path=None,
        )

    @pytest.mark.asyncio
    async def test_create_async_execute_still_blocks_when_must_questions_remain(self, tmp_path, monkeypatch):
        from claw import cli

        async def fake_preflight_async(**kwargs):
            report = {
                "artifact_path": str(tmp_path / "data" / "preflights" / "demo.json"),
                "hard_blockers": [],
                "clarifying_questions": [
                    {"priority": "must", "question": "Which parts of the source repo must transfer?"}
                ],
                "operator_answers": list(kwargs.get("answers", [])),
                "answered_questions": [],
                "recommended_mode": "proceed_after_answers",
                "complexity": "high",
                "task_kind": "pattern_transfer",
            }
            return report, tmp_path / "data" / "preflights" / "demo.json"

        monkeypatch.setattr(cli, "_run_preflight_async", fake_preflight_async)

        with pytest.raises(typer.Exit) as exc:
            await cli._create_async(
                repo_path=tmp_path / "demo",
                request="Build a risky app",
                repo_mode="new",
                title="Risky app",
                priority="high",
                task_type="architecture",
                agent=None,
                spec_items=[],
            execution_steps=[],
            acceptance_checks=[],
            answers=["Delivery surface: web app"],
            preflight_file=None,
            preflight=True,
            auto_preflight=True,
            preflight_live=False,
            accept_preflight_defaults=False,
                preview=False,
                execute=True,
                config_path=None,
            )

        assert exc.value.exit_code == 2

    @pytest.mark.asyncio
    async def test_run_preflight_async_reuses_prior_answers(self, tmp_path):
        from claw import cli

        report, _ = await cli._run_preflight_async(
            repo_path=tmp_path / "demo",
            request="Apply everything repo-A does to a related healthcare intake app",
            repo_mode="new",
            spec_items=[],
            acceptance_checks=[],
            answers=["Transfer scope: UX and workflows"],
            prior_report={
                "artifact_path": str(tmp_path / "prior.json"),
                "operator_answers": [
                    "Acceptance checks: pytest -q",
                    "Delivery surface: web app",
                    "Compliance: no PHI or PII, standard security only",
                ],
            },
            preferred_agent=None,
            config_path=None,
            live=False,
        )

        assert report["reused_preflight_artifact"] == str(tmp_path / "prior.json")
        assert "Acceptance checks: pytest -q" in report["operator_answers"]
        assert "Transfer scope: UX and workflows" in report["operator_answers"]
        assert all(item.get("priority") != "must" or "time ceiling" not in item.get("question", "").lower() for item in report["answered_questions"])
