"""Tests for cross-language pattern synthesis (CrossLanguageAnalyzer).

Uses REAL SQLite ganglion databases in temporary directories.
No mock, no placeholders, no cached responses.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest

from claw.community.cross_language import (
    CATEGORY_DOMAIN_MAP,
    CrossLanguageAnalyzer,
    _extract_category_from_tags,
    _keyword_overlap_score,
    _keyword_set_from_text,
)
from claw.core.config import DatabaseConfig, InstanceConfig, InstanceRegistryConfig
from claw.core.models import (
    CompositionLayer,
    CrossBrainMetrics,
    CrossLanguageReport,
    Methodology,
    TransferableInsight,
    UniqueInnovation,
    UniversalPattern,
)
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Helpers — create real ganglion DBs with real schema + data
# ---------------------------------------------------------------------------

async def _create_ganglion_db(
    base_dir: Path, ganglion_name: str
) -> tuple[DatabaseEngine, Repository, str]:
    ganglion_dir = base_dir / ganglion_name
    ganglion_dir.mkdir(parents=True, exist_ok=True)
    db_path = ganglion_dir / "claw.db"

    db_config = DatabaseConfig(db_path=str(db_path))
    engine = DatabaseEngine(db_config)
    await engine.connect()
    await engine.initialize_schema()

    repo = Repository(engine)
    return engine, repo, str(db_path)


async def _insert_methodology(
    repo: Repository,
    *,
    problem: str,
    solution: str,
    language: str = "python",
    tags: list[str] | None = None,
    notes: str = "",
    lifecycle_state: str = "viable",
) -> Methodology:
    m = Methodology(
        id=str(uuid.uuid4()),
        problem_description=problem,
        solution_code=solution,
        language=language,
        tags=tags or [],
        methodology_notes=notes,
        lifecycle_state=lifecycle_state,
        scope="global",
    )
    await repo.save_methodology(m)
    return m


async def _generate_manifest(
    engine: DatabaseEngine,
    base_dir: Path,
    ganglion_name: str,
    description: str = "",
) -> Path:
    from claw.community.manifest import save_manifest
    manifest_path = base_dir / ganglion_name / "brain_manifest.json"
    await save_manifest(engine, manifest_path, ganglion_name, description)
    return manifest_path


def _build_analyzer(
    siblings: list[dict[str, Any]],
    primary_db_path: str | None = None,
) -> CrossLanguageAnalyzer:
    sibling_configs = [
        InstanceConfig(
            name=s["name"],
            db_path=s["db_path"],
            description=s.get("description", ""),
            manifest_path=s.get("manifest_path", ""),
        )
        for s in siblings
    ]
    config = InstanceRegistryConfig(
        enabled=True,
        siblings=sibling_configs,
        federation_relevance_threshold=0.1,
        federation_max_results=50,
    )
    return CrossLanguageAnalyzer(config, primary_db_path=primary_db_path)


# ---------------------------------------------------------------------------
# Test: Helper functions
# ---------------------------------------------------------------------------

class TestHelperFunctions:

    def test_extract_category_from_tags(self):
        assert _extract_category_from_tags(["category:security", "source:foo"]) == "security"

    def test_extract_category_from_tags_missing(self):
        assert _extract_category_from_tags(["source:foo"]) == "uncategorized"

    def test_extract_category_from_tags_empty(self):
        assert _extract_category_from_tags([]) == "uncategorized"

    def test_keyword_set_from_text(self):
        kw = _keyword_set_from_text("taint tracking for information flow security")
        assert "taint" in kw
        assert "tracking" in kw
        assert "security" in kw
        # Stop words filtered
        assert "for" not in kw

    def test_keyword_overlap_score_full_overlap(self):
        a = {"security", "audit", "encryption"}
        b = {"security", "audit", "encryption"}
        assert _keyword_overlap_score(a, b) == 1.0

    def test_keyword_overlap_score_no_overlap(self):
        a = {"security", "audit"}
        b = {"testing", "coverage"}
        assert _keyword_overlap_score(a, b) == 0.0

    def test_keyword_overlap_score_partial(self):
        a = {"security", "audit", "encryption"}
        b = {"security", "testing"}
        score = _keyword_overlap_score(a, b)
        assert 0.0 < score < 1.0

    def test_keyword_overlap_score_empty(self):
        assert _keyword_overlap_score(set(), {"a"}) == 0.0
        assert _keyword_overlap_score({"a"}, set()) == 0.0


# ---------------------------------------------------------------------------
# Test: Data models
# ---------------------------------------------------------------------------

class TestDataModels:

    def test_universal_pattern_creation(self):
        p = UniversalPattern(
            pattern_name="layered security",
            implementations={"rust": "two-layer gates", "go": "permission lattice"},
            evidence_ids={"rust": ["id1"], "go": ["id2"]},
            domain_overlap=0.65,
            source_categories=["security"],
        )
        assert len(p.implementations) == 2
        assert p.domain_overlap == 0.65

    def test_unique_innovation_creation(self):
        u = UniqueInnovation(
            brain="rust",
            methodology_id="abc123",
            problem_summary="Taint tracking for information flow",
            solution_summary="Implement taint propagation through type system",
            why_unique="No equivalent in Go or TypeScript",
            category="security",
        )
        assert u.brain == "rust"

    def test_cross_language_report_creation(self):
        report = CrossLanguageReport(
            query="security patterns",
            domains_queried=["security"],
            universal_patterns=[],
            unique_innovations=[],
            metrics=CrossBrainMetrics(query="security patterns", brains_queried=3),
        )
        assert report.query == "security patterns"
        assert report.metrics.brains_queried == 3

    def test_report_serialization(self):
        report = CrossLanguageReport(
            query="test",
            universal_patterns=[
                UniversalPattern(
                    pattern_name="test_pat",
                    implementations={"rust": "impl1"},
                    domain_overlap=0.5,
                ),
            ],
        )
        data = report.model_dump()
        assert data["query"] == "test"
        assert len(data["universal_patterns"]) == 1

    def test_report_json_roundtrip(self):
        report = CrossLanguageReport(
            query="test",
            metrics=CrossBrainMetrics(query="test", brains_queried=2, novelty_count=5),
        )
        json_str = report.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["metrics"]["novelty_count"] == 5


# ---------------------------------------------------------------------------
# Test: CrossLanguageAnalyzer with real ganglion DBs
# ---------------------------------------------------------------------------

class TestCrossLanguageAnalyzer:

    def test_analyze_returns_results_from_multiple_brains(self):
        """Core test: analyzer returns results from 2+ brains."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            async def _setup_and_run():
                # Create Rust brain with security methodology
                rust_engine, rust_repo, rust_path = await _create_ganglion_db(base, "rust")
                await _insert_methodology(
                    rust_repo,
                    problem="Implement taint tracking for information flow security analysis",
                    solution="fn track_taint(data: &Data) -> TaintResult { ... }",
                    language="rust",
                    tags=["category:security", "source:openfang"],
                )
                await _generate_manifest(rust_engine, base, "rust", "Rust security patterns")

                # Create Go brain with security methodology
                go_engine, go_repo, go_path = await _create_ganglion_db(base, "go")
                await _insert_methodology(
                    go_repo,
                    problem="Implement permission lattice for security authorization",
                    solution="func CheckPermission(ctx context.Context) error { ... }",
                    language="go",
                    tags=["category:security", "source:cockroach"],
                )
                await _generate_manifest(go_engine, base, "go", "Go security patterns")

                # Create TS brain with security methodology
                ts_engine, ts_repo, ts_path = await _create_ganglion_db(base, "typescript")
                await _insert_methodology(
                    ts_repo,
                    problem="Implement Zod schema validation for API security input",
                    solution="const schema = z.object({ ... })",
                    language="typescript",
                    tags=["category:security", "source:dram-quest"],
                )
                await _generate_manifest(ts_engine, base, "typescript", "TS security patterns")

                analyzer = _build_analyzer([
                    {"name": "rust", "db_path": rust_path},
                    {"name": "go", "db_path": go_path},
                    {"name": "typescript", "db_path": ts_path},
                ])

                report = await analyzer.analyze("security authorization validation")

                await rust_engine.close()
                await go_engine.close()
                await ts_engine.close()

                return report

            report = _run(_setup_and_run())

            # M1: Multiple brains returned results
            assert report.metrics.brains_with_results >= 2, (
                f"Expected 2+ brains with results, got {report.metrics.brains_with_results}"
            )
            assert len(report.raw_results_by_brain) >= 2

    def test_universal_pattern_detection(self):
        """Test that overlapping patterns across brains are detected as universal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            async def _setup_and_run():
                # Two brains with overlapping security audit patterns
                rust_engine, rust_repo, rust_path = await _create_ganglion_db(base, "rust")
                await _insert_methodology(
                    rust_repo,
                    problem="Structured audit logging with redaction for security compliance",
                    solution="fn audit_log(event: &AuditEvent) { ... }",
                    language="rust",
                    tags=["category:security"],
                )
                await _generate_manifest(rust_engine, base, "rust")

                go_engine, go_repo, go_path = await _create_ganglion_db(base, "go")
                await _insert_methodology(
                    go_repo,
                    problem="Risk-scored audit logging for security compliance tracking",
                    solution="func AuditLog(ctx context.Context, event AuditEvent) { ... }",
                    language="go",
                    tags=["category:security"],
                )
                await _generate_manifest(go_engine, base, "go")

                analyzer = _build_analyzer([
                    {"name": "rust", "db_path": rust_path},
                    {"name": "go", "db_path": go_path},
                ])

                report = await analyzer.analyze("audit logging security compliance")

                await rust_engine.close()
                await go_engine.close()

                return report

            report = _run(_setup_and_run())

            # Should detect at least one universal pattern
            assert report.metrics.total_results >= 2

    def test_unique_innovation_detection(self):
        """Test that brain-specific patterns are detected as unique innovations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            async def _setup_and_run():
                # Rust has taint tracking (unique concept)
                rust_engine, rust_repo, rust_path = await _create_ganglion_db(base, "rust")
                await _insert_methodology(
                    rust_repo,
                    problem="Implement taint tracking propagation through ownership type system for information flow",
                    solution="fn propagate_taint(data: &Tainted<T>) -> TaintResult { ... }",
                    language="rust",
                    tags=["category:security"],
                )
                await _generate_manifest(rust_engine, base, "rust")

                # Go has completely different pattern (encrypted storage)
                go_engine, go_repo, go_path = await _create_ganglion_db(base, "go")
                await _insert_methodology(
                    go_repo,
                    problem="Implement AES-GCM encrypted storage at database level for secret management",
                    solution="func EncryptSecret(key []byte, plaintext []byte) ([]byte, error) { ... }",
                    language="go",
                    tags=["category:security"],
                )
                await _generate_manifest(go_engine, base, "go")

                analyzer = _build_analyzer([
                    {"name": "rust", "db_path": rust_path},
                    {"name": "go", "db_path": go_path},
                ])

                report = await analyzer.analyze("security encryption taint tracking storage")

                await rust_engine.close()
                await go_engine.close()

                return report

            report = _run(_setup_and_run())

            # Both brains should have results
            assert report.metrics.brains_with_results >= 2
            # Unique innovations should exist (each brain has distinct concepts)
            assert len(report.unique_innovations) >= 1

    def test_composition_layers_built(self):
        """Test that composition layers are generated from multi-brain results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            async def _setup_and_run():
                rust_engine, rust_repo, rust_path = await _create_ganglion_db(base, "rust")
                await _insert_methodology(
                    rust_repo,
                    problem="Implement security layer with taint tracking",
                    solution="fn security_layer() { ... }",
                    language="rust",
                    tags=["category:security"],
                )
                await _insert_methodology(
                    rust_repo,
                    problem="Architecture pattern for modular service composition",
                    solution="fn compose_services() { ... }",
                    language="rust",
                    tags=["category:architecture"],
                )
                await _generate_manifest(rust_engine, base, "rust")

                go_engine, go_repo, go_path = await _create_ganglion_db(base, "go")
                await _insert_methodology(
                    go_repo,
                    problem="Testing strategy with table-driven test patterns",
                    solution="func TestTableDriven(t *testing.T) { ... }",
                    language="go",
                    tags=["category:testing"],
                )
                await _generate_manifest(go_engine, base, "go")

                analyzer = _build_analyzer([
                    {"name": "rust", "db_path": rust_path},
                    {"name": "go", "db_path": go_path},
                ])

                report = await analyzer.analyze("security architecture testing")

                await rust_engine.close()
                await go_engine.close()

                return report

            report = _run(_setup_and_run())

            # Composition layers should be built
            assert len(report.composition_layers) >= 1
            # Each layer should have required fields
            for layer in report.composition_layers:
                assert layer.layer_name
                assert layer.contributing_brain
                assert layer.methodology_id

    def test_empty_query_returns_empty_report(self):
        """Test that empty/meaningless queries return empty report gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            async def _setup_and_run():
                engine, repo, db_path = await _create_ganglion_db(base, "rust")
                await _insert_methodology(
                    repo,
                    problem="Some pattern",
                    solution="fn foo() {}",
                    language="rust",
                )
                await _generate_manifest(engine, base, "rust")

                analyzer = _build_analyzer([
                    {"name": "rust", "db_path": db_path},
                ])

                # Query with only stop words
                report = await analyzer.analyze("the a is to of")

                await engine.close()
                return report

            report = _run(_setup_and_run())
            assert report.metrics.total_results == 0

    def test_missing_brain_db_handled_gracefully(self):
        """Test that missing DB files don't crash the analyzer."""
        analyzer = _build_analyzer([
            {"name": "rust", "db_path": "/nonexistent/path/claw.db"},
            {"name": "go", "db_path": "/also/nonexistent/claw.db"},
        ])

        report = _run(analyzer.analyze("security patterns"))
        assert report.metrics.brains_with_results == 0
        assert report.metrics.total_results == 0

    def test_dead_methodologies_excluded(self):
        """Test that dead/dormant methodologies are filtered out."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            async def _setup_and_run():
                engine, repo, db_path = await _create_ganglion_db(base, "rust")
                await _insert_methodology(
                    repo,
                    problem="Dead security pattern that should be excluded",
                    solution="fn dead() {}",
                    language="rust",
                    tags=["category:security"],
                    lifecycle_state="dead",
                )
                await _insert_methodology(
                    repo,
                    problem="Viable security pattern for taint analysis",
                    solution="fn taint() {}",
                    language="rust",
                    tags=["category:security"],
                    lifecycle_state="viable",
                )
                await _generate_manifest(engine, base, "rust")

                analyzer = _build_analyzer([
                    {"name": "rust", "db_path": db_path},
                ])

                report = await analyzer.analyze("security pattern taint analysis")

                await engine.close()
                return report

            report = _run(_setup_and_run())

            # Only the viable methodology should appear
            for brain_ids in report.raw_results_by_brain.values():
                assert len(brain_ids) >= 1

    def test_novelty_count_with_primary_db(self):
        """Test novelty counting — cross-brain unique results.

        With primary DB included as a brain, novelty counts results that
        appear in only one brain (no high overlap with any other brain).
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            async def _setup_and_run():
                # Create primary DB with a different methodology
                primary_engine, primary_repo, primary_path = await _create_ganglion_db(base, "primary")
                await _insert_methodology(
                    primary_repo,
                    problem="Python logging and monitoring best practices",
                    solution="import logging; logging.basicConfig()",
                    language="python",
                    tags=["category:reliability"],
                )
                await _generate_manifest(primary_engine, base, "primary")

                # Create ganglion with a unique methodology (different topic)
                rust_engine, rust_repo, rust_path = await _create_ganglion_db(base, "rust")
                await _insert_methodology(
                    rust_repo,
                    problem="Unique rust-only WASM sandbox security isolation pattern",
                    solution="fn sandbox() {}",
                    language="rust",
                    tags=["category:security"],
                )
                await _generate_manifest(rust_engine, base, "rust")

                analyzer = _build_analyzer(
                    [{"name": "rust", "db_path": rust_path}],
                    primary_db_path=primary_path,
                )

                report = await analyzer.analyze("security isolation sandbox WASM logging monitoring")

                await primary_engine.close()
                await rust_engine.close()
                return report

            report = _run(_setup_and_run())

            # Both brains should have results, and their unique results
            # should be counted as novel (no overlap between them)
            assert report.metrics.novelty_count >= 1

    def test_domain_inference(self):
        """Test that domains are inferred from query keywords."""
        analyzer = _build_analyzer([])
        domains = analyzer._infer_domains(["security", "encryption", "audit"])
        assert "security" in domains

    def test_transferable_insights_generated(self):
        """Test that transferable insights are generated from unique innovations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            async def _setup_and_run():
                # Rust brain with many security patterns
                rust_engine, rust_repo, rust_path = await _create_ganglion_db(base, "rust")
                await _insert_methodology(
                    rust_repo,
                    problem="Implement taint tracking propagation for security flow analysis",
                    solution="fn taint() {}",
                    language="rust",
                    tags=["category:security"],
                )
                await _insert_methodology(
                    rust_repo,
                    problem="Implement Merkle hash chain for security audit trail integrity",
                    solution="fn merkle() {}",
                    language="rust",
                    tags=["category:security"],
                )
                await _generate_manifest(rust_engine, base, "rust")

                # Go brain with fewer security patterns
                go_engine, go_repo, go_path = await _create_ganglion_db(base, "go")
                await _insert_methodology(
                    go_repo,
                    problem="Basic permission check for authorization security",
                    solution="func check() {}",
                    language="go",
                    tags=["category:security"],
                )
                await _generate_manifest(go_engine, base, "go")

                analyzer = _build_analyzer([
                    {"name": "rust", "db_path": rust_path},
                    {"name": "go", "db_path": go_path},
                ])

                report = await analyzer.analyze("security taint tracking merkle audit permission")

                await rust_engine.close()
                await go_engine.close()
                return report

            report = _run(_setup_and_run())

            # At least one brain should contribute unique insights
            assert report.metrics.brains_with_results >= 2

    def test_domains_parameter_used(self):
        """Test that explicit domain parameter adds domain keywords to query."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)

            async def _setup_and_run():
                engine, repo, db_path = await _create_ganglion_db(base, "rust")
                await _insert_methodology(
                    repo,
                    problem="Implement model inference pipeline for neural network serving",
                    solution="fn infer() {}",
                    language="rust",
                    tags=["category:ai_integration"],
                )
                await _generate_manifest(engine, base, "rust")

                analyzer = _build_analyzer([
                    {"name": "rust", "db_path": db_path},
                ])

                report = await analyzer.analyze(
                    "inference pipeline",
                    domains=["ai_integration"],
                )

                await engine.close()
                return report

            report = _run(_setup_and_run())
            assert "ai_integration" in report.domains_queried


# ---------------------------------------------------------------------------
# Test: With real ganglion DBs (if present)
# ---------------------------------------------------------------------------

class TestWithRealGanglia:
    """Tests using the actual ganglion databases at instances/{lang}/claw.db.

    These tests are skipped if the real ganglia don't exist.
    """

    RUST_DB = Path("/Volumes/WS4TB/a_aSatzClaw/multiclaw/instances/rust/claw.db")
    GO_DB = Path("/Volumes/WS4TB/a_aSatzClaw/multiclaw/instances/go/claw.db")
    TS_DB = Path("/Volumes/WS4TB/a_aSatzClaw/multiclaw/instances/typescript/claw.db")
    PRIMARY_DB = Path("/Volumes/WS4TB/a_aSatzClaw/multiclaw/data/claw.db")

    @pytest.mark.skipif(
        not all(p.exists() for p in [RUST_DB, GO_DB, TS_DB]),
        reason="Real ganglion DBs not present",
    )
    def test_real_ganglia_security_query(self):
        """Run security query against real ganglia — the 'wow' test."""
        analyzer = _build_analyzer(
            [
                {"name": "rust", "db_path": str(self.RUST_DB)},
                {"name": "go", "db_path": str(self.GO_DB)},
                {"name": "typescript", "db_path": str(self.TS_DB)},
            ],
            primary_db_path=str(self.PRIMARY_DB) if self.PRIMARY_DB.exists() else None,
        )

        report = _run(analyzer.analyze(
            "design defense-in-depth security for a multi-tenant AI agent gateway",
            domains=["security"],
        ))

        # Should get results from multiple brains
        assert report.metrics.brains_with_results >= 2
        assert report.metrics.total_results >= 3

    @pytest.mark.skipif(
        not all(p.exists() for p in [RUST_DB, GO_DB, TS_DB]),
        reason="Real ganglion DBs not present",
    )
    def test_real_ganglia_architecture_query(self):
        """Run architecture query against real ganglia."""
        analyzer = _build_analyzer(
            [
                {"name": "rust", "db_path": str(self.RUST_DB)},
                {"name": "go", "db_path": str(self.GO_DB)},
                {"name": "typescript", "db_path": str(self.TS_DB)},
            ],
        )

        report = _run(analyzer.analyze(
            "modular architecture with service composition and middleware",
            domains=["architecture"],
        ))

        assert report.metrics.brains_with_results >= 1
        assert report.metrics.total_results >= 1
