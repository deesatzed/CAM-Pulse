"""Regression benchmark tests for standalone Forge."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class TestStandaloneForgeBenchmark:
    def test_fixture_benchmark_writes_summary(self, tmp_path):
        module = _load_module(
            "forge_benchmark_regression",
            Path("apps/embedding_forge/benchmark_regression.py").resolve(),
        )

        summary = module.run_fixture_benchmark(
            repo_path=Path("tests/fixtures/embedding_forge/repo"),
            note_path=Path("tests/fixtures/embedding_forge/note.md"),
            knowledge_pack_path=Path("tests/fixtures/embedding_forge/knowledge_pack.jsonl"),
            out_dir=tmp_path / "benchmark",
        )

        assert summary["benchmark"] == "fixture_regression"
        assert summary["docs_total"] >= 5
        assert len(summary["candidates"]) == 4
        assert "best" in summary

        best = summary["best"]
        assert best["forge_dim"] > 0
        assert best["hit_rate_lift_pct"] >= summary["catastrophic_floor_pct"]

        written = json.loads((tmp_path / "benchmark" / "benchmark_summary.json").read_text(encoding="utf-8"))
        assert written["best"]["hit_rate_lift_pct"] == best["hit_rate_lift_pct"]
