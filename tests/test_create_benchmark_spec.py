"""Tests for create-spec generation and benchmark validation helpers."""

from __future__ import annotations

import json
from pathlib import Path


class TestCreateBenchmarkSpecHelpers:
    def test_build_and_write_create_spec(self, tmp_path, monkeypatch):
        from claw import cli

        monkeypatch.setattr(cli, "ROOT_DIR", tmp_path)
        spec = cli._build_create_spec(
            repo_path=Path("/tmp/new-app"),
            request="Build a new repo for multimodal retrieval.",
            repo_mode="new",
            title="Build new retrieval repo",
            task_type="architecture",
            execution_steps=["uv init", "pytest -q"],
            acceptance_checks=["project boots", "tests pass"],
            spec_items=["Use Gemini embeddings", "Create a CLI"],
        )
        path = cli._write_create_spec(spec)

        assert path.exists()
        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["repo_mode"] == "new"
        assert "baseline_snapshot" in written
        assert written["validation"]["require_repo_exists"] is True
        assert written["benchmark"]["catastrophic_floor_pct"] == -35.0
        assert written["spec_items"][0] == "Use Gemini embeddings"

    def test_validate_create_spec_runs_acceptance_checks(self, tmp_path):
        from claw import cli

        repo_path = tmp_path / "app"
        repo_path.mkdir()
        (repo_path / "README.md").write_text("hello\n", encoding="utf-8")

        spec = cli._build_create_spec(
            repo_path=repo_path,
            request="Create a tiny app.",
            repo_mode="new",
            title="Tiny app",
            task_type="architecture",
            execution_steps=[],
            acceptance_checks=["python -c \"print('ok')\""],
            spec_items=[],
        )
        (repo_path / "README.md").write_text("hello changed\n", encoding="utf-8")

        passed, summary = cli._validate_create_spec(spec, max_minutes=1)
        assert passed is True
        assert summary["checks_run"] == 1
        assert summary["checks"][0]["ok"] is True

    def test_validate_create_spec_reports_failed_check(self, tmp_path):
        from claw import cli

        repo_path = tmp_path / "app"
        repo_path.mkdir()
        (repo_path / "README.md").write_text("hello\n", encoding="utf-8")

        spec = cli._build_create_spec(
            repo_path=repo_path,
            request="Create a tiny app.",
            repo_mode="new",
            title="Tiny app",
            task_type="architecture",
            execution_steps=[],
            acceptance_checks=["python -c \"import sys; sys.exit(3)\""],
            spec_items=[],
        )

        passed, summary = cli._validate_create_spec(spec, max_minutes=1)
        assert passed is False
        assert any("acceptance check failed" in item for item in summary["findings"])

    def test_validate_create_spec_treats_plain_english_checks_as_manual(self, tmp_path):
        from claw import cli

        repo_path = tmp_path / "app"
        repo_path.mkdir()
        (repo_path / "README.md").write_text("hello\n", encoding="utf-8")

        spec = cli._build_create_spec(
            repo_path=repo_path,
            request="Create a tiny app.",
            repo_mode="new",
            title="Tiny app",
            task_type="architecture",
            execution_steps=[],
            acceptance_checks=["CLI runs without crashing", "Reads JSONL knowledge pack"],
            spec_items=[],
        )
        (repo_path / "README.md").write_text("hello changed\n", encoding="utf-8")

        passed, summary = cli._validate_create_spec(spec, max_minutes=1)
        assert passed is True
        assert summary["checks_run"] == 0
        assert len(summary["manual_checks"]) == 2

    def test_validate_create_spec_detects_unchanged_repo(self, tmp_path):
        from claw import cli

        repo_path = tmp_path / "app"
        repo_path.mkdir()
        (repo_path / "README.md").write_text("hello\n", encoding="utf-8")

        spec = cli._build_create_spec(
            repo_path=repo_path,
            request="Change the repo.",
            repo_mode="augment",
            title="Change repo",
            task_type="architecture",
            execution_steps=[],
            acceptance_checks=[],
            spec_items=[],
        )

        passed, summary = cli._validate_create_spec(spec, max_minutes=1)
        assert passed is False
        assert any("unchanged" in item for item in summary["findings"])

    def test_validate_benchmark_against_spec(self):
        from claw import cli

        summary = {
            "best": {
                "hit_rate_lift_pct": -2.5,
            }
        }
        spec = {
            "benchmark": {
                "catastrophic_floor_pct": -10.0,
                "require_non_negative_lift": True,
            }
        }

        passed, findings = cli._validate_benchmark_against_spec(summary, spec)
        assert passed is False
        assert any("non-negative" in item for item in findings)
