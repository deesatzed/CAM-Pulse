"""Integration tests for ganglion cross-search (federation) with real SQLite databases.

Validates that the Federation class can:
    1. Create a ganglion DB for a language brain (e.g. "typescript")
    2. Insert a methodology into that ganglion via the full schema + Repository
    3. Query from Federation and confirm the ganglion result appears
    4. Handle manifest-based relevance scoring
    5. Handle language filtering
    6. Handle multiple ganglia with deduplication

All tests use REAL SQLite databases in temporary directories.
No mock, no placeholders, no cached responses.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pytest

from claw.community.federation import Federation, FederationResult, _extract_keywords
from claw.community.manifest import generate_manifest, save_manifest
from claw.core.config import DatabaseConfig, InstanceConfig, InstanceRegistryConfig
from claw.core.models import Methodology
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository


# ---------------------------------------------------------------------------
# Helpers — create real ganglion DBs with real schema + data
# ---------------------------------------------------------------------------

async def _create_ganglion_db(
    base_dir: Path, ganglion_name: str
) -> tuple[DatabaseEngine, Repository, str]:
    """Create a real ganglion SQLite DB with full schema.

    Returns (engine, repository, db_path_str).
    """
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
    """Insert a real methodology into the ganglion's DB."""
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


async def _generate_and_save_manifest(
    engine: DatabaseEngine,
    base_dir: Path,
    ganglion_name: str,
    description: str = "",
) -> Path:
    """Generate and save a manifest for a ganglion."""
    manifest_path = base_dir / ganglion_name / "brain_manifest.json"
    await save_manifest(engine, manifest_path, ganglion_name, description)
    return manifest_path


def _build_federation(
    siblings: list[dict[str, Any]],
    enabled: bool = True,
    relevance_threshold: float = 0.2,
    max_results: int = 3,
) -> Federation:
    """Build a Federation from a list of sibling dicts."""
    sibling_configs = []
    for s in siblings:
        sibling_configs.append(InstanceConfig(
            name=s["name"],
            db_path=s["db_path"],
            description=s.get("description", ""),
            manifest_path=s.get("manifest_path", ""),
        ))
    config = InstanceRegistryConfig(
        enabled=enabled,
        siblings=sibling_configs,
        federation_relevance_threshold=relevance_threshold,
        federation_max_results=max_results,
    )
    return Federation(config)


# ---------------------------------------------------------------------------
# Test: Manifest generation from real ganglion DB
# ---------------------------------------------------------------------------

class TestManifestGeneration:
    """Validate that generate_manifest() reads real data from a ganglion DB."""

    @pytest.mark.asyncio
    async def test_manifest_reflects_inserted_methodologies(self):
        """Manifest counts and language breakdown must match DB contents."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            engine, repo, _ = await _create_ganglion_db(tmp_path, "typescript")
            try:
                await _insert_methodology(
                    repo,
                    problem="TypeScript generics for reusable API client",
                    solution="Use generic type parameters with constraint interfaces",
                    language="typescript",
                    tags=["generics", "api", "category:type-system"],
                )
                await _insert_methodology(
                    repo,
                    problem="Next.js server components data fetching patterns",
                    solution="Use async server components with direct DB queries",
                    language="typescript",
                    tags=["nextjs", "server-components", "category:data-fetching"],
                )

                manifest = await generate_manifest(engine, "typescript", "TypeScript patterns")

                assert manifest["total_methodologies"] == 2
                assert "typescript" in manifest["language_breakdown"]
                assert manifest["language_breakdown"]["typescript"] == 2
                assert manifest["instance_name"] == "typescript"
                assert len(manifest["domain_keywords"]) > 0
            finally:
                await engine.close()

    @pytest.mark.asyncio
    async def test_manifest_saved_to_disk(self):
        """save_manifest should write a valid JSON file."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            engine, repo, _ = await _create_ganglion_db(tmp_path, "go")
            try:
                await _insert_methodology(
                    repo,
                    problem="Go goroutine pool for concurrent HTTP requests",
                    solution="Use buffered channel as semaphore with sync.WaitGroup",
                    language="go",
                    tags=["goroutine", "concurrency", "category:parallelism"],
                )

                manifest_path = await _generate_and_save_manifest(
                    engine, tmp_path, "go", "Go language patterns"
                )

                assert manifest_path.exists()
                data = json.loads(manifest_path.read_text())
                assert data["total_methodologies"] == 1
                assert data["instance_name"] == "go"
            finally:
                await engine.close()


# ---------------------------------------------------------------------------
# Test: Federation FTS5 cross-search
# ---------------------------------------------------------------------------

class TestFederationQuery:
    """Core federation tests: query sibling ganglia via FTS5."""

    @pytest.mark.asyncio
    async def test_federation_finds_methodology_in_sibling(self):
        """Federation.query() should find a methodology stored in a sibling ganglion DB."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            ts_engine, ts_repo, ts_db_path = await _create_ganglion_db(tmp_path, "typescript")
            try:
                m = await _insert_methodology(
                    ts_repo,
                    problem="React hooks custom state management with useReducer",
                    solution="Implement useReducer with context for global state without Redux",
                    language="typescript",
                    tags=["react", "hooks", "state-management", "category:architecture"],
                    notes="Works well for medium-complexity apps",
                )

                manifest_path = await _generate_and_save_manifest(
                    ts_engine, tmp_path, "typescript", "TypeScript patterns"
                )

                federation = _build_federation(
                    siblings=[{
                        "name": "typescript",
                        "db_path": ts_db_path,
                        "description": "TypeScript patterns",
                        "manifest_path": str(manifest_path),
                    }],
                    relevance_threshold=0.0,
                )

                results = await federation.query(
                    "react hooks state management useReducer",
                    language="typescript",
                    max_total=5,
                )

                assert len(results) >= 1, (
                    f"Expected at least 1 federation result, got {len(results)}"
                )
                assert isinstance(results[0], FederationResult)
                assert results[0].methodology.id == m.id
                assert results[0].source_instance == "typescript"
            finally:
                await ts_engine.close()

    @pytest.mark.asyncio
    async def test_federation_respects_language_filter(self):
        """Federation should filter results by language when specified."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            engine, repo, db_path = await _create_ganglion_db(tmp_path, "mixed")
            try:
                ts_meth = await _insert_methodology(
                    repo,
                    problem="TypeScript async error handling patterns",
                    solution="Use Result type pattern with discriminated unions",
                    language="typescript",
                    tags=["error-handling", "async", "category:patterns"],
                )
                py_meth = await _insert_methodology(
                    repo,
                    problem="Python async error handling patterns",
                    solution="Use contextlib.suppress and structured exception hierarchies",
                    language="python",
                    tags=["error-handling", "async", "category:patterns"],
                )

                manifest_path = await _generate_and_save_manifest(
                    engine, tmp_path, "mixed", "Mixed language patterns"
                )

                federation = _build_federation(
                    siblings=[{
                        "name": "mixed",
                        "db_path": db_path,
                        "manifest_path": str(manifest_path),
                    }],
                    relevance_threshold=0.0,
                )

                results = await federation.query(
                    "async error handling patterns",
                    language="typescript",
                    max_total=10,
                )

                result_ids = {r.methodology.id for r in results}
                assert ts_meth.id in result_ids, "TypeScript methodology should appear"
                assert py_meth.id not in result_ids, "Python methodology should be filtered out"
            finally:
                await engine.close()

    @pytest.mark.asyncio
    async def test_federation_excludes_dead_methodologies(self):
        """Dead/dormant methodologies should be excluded from federation results."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            engine, repo, db_path = await _create_ganglion_db(tmp_path, "rust")
            try:
                alive = await _insert_methodology(
                    repo,
                    problem="Rust borrow checker patterns for complex data structures",
                    solution="Use Rc RefCell for interior mutability",
                    language="rust",
                    tags=["borrow-checker", "category:memory"],
                    lifecycle_state="viable",
                )
                dead = await _insert_methodology(
                    repo,
                    problem="Rust borrow checker deprecated pattern obsolete approach",
                    solution="Old approach that no longer works",
                    language="rust",
                    tags=["borrow-checker", "category:memory"],
                    lifecycle_state="dead",
                )

                manifest_path = await _generate_and_save_manifest(
                    engine, tmp_path, "rust", "Rust patterns"
                )

                federation = _build_federation(
                    siblings=[{
                        "name": "rust",
                        "db_path": db_path,
                        "manifest_path": str(manifest_path),
                    }],
                    relevance_threshold=0.0,
                )

                results = await federation.query("borrow checker patterns", max_total=10)
                result_ids = {r.methodology.id for r in results}

                assert alive.id in result_ids, "Viable methodology should appear"
                assert dead.id not in result_ids, "Dead methodology should be excluded"
            finally:
                await engine.close()

    @pytest.mark.asyncio
    async def test_federation_disabled_returns_empty(self):
        """When federation is disabled, query returns empty."""
        federation = _build_federation(
            siblings=[{
                "name": "test",
                "db_path": "/nonexistent/path.db",
            }],
            enabled=False,
        )
        results = await federation.query("anything at all here")
        assert results == []

    @pytest.mark.asyncio
    async def test_federation_no_siblings_returns_empty(self):
        """When there are no siblings, query returns empty."""
        federation = _build_federation(siblings=[], enabled=True)
        results = await federation.query("anything at all here")
        assert results == []

    @pytest.mark.asyncio
    async def test_federation_missing_db_skips_gracefully(self):
        """Federation should gracefully skip siblings with missing DB files."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Create manifest but no actual DB
            manifest = {
                "manifest_version": "1.0",
                "total_methodologies": 5,
                "domain_keywords": ["testing", "patterns"],
                "top_categories": {"testing": 3},
                "language_breakdown": {"python": 5},
                "lifecycle_distribution": {"viable": 5},
            }
            manifest_dir = tmp_path / "ghost"
            manifest_dir.mkdir(parents=True)
            manifest_path = manifest_dir / "brain_manifest.json"
            manifest_path.write_text(json.dumps(manifest))

            federation = _build_federation(
                siblings=[{
                    "name": "ghost",
                    "db_path": str(tmp_path / "ghost" / "claw.db"),
                    "manifest_path": str(manifest_path),
                }],
                relevance_threshold=0.0,
            )

            results = await federation.query("testing patterns here")
            assert results == []


# ---------------------------------------------------------------------------
# Test: Multi-ganglion federation
# ---------------------------------------------------------------------------

class TestMultiGanglionFederation:
    """Test federation across multiple ganglion siblings."""

    @pytest.mark.asyncio
    async def test_query_across_two_ganglia(self):
        """Federation should merge results from multiple sibling ganglia."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            ts_engine, ts_repo, ts_db = await _create_ganglion_db(tmp_path, "typescript")
            ts_meth = await _insert_methodology(
                ts_repo,
                problem="TypeScript API client error handling with retry logic",
                solution="Use axios interceptors with exponential backoff",
                language="typescript",
                tags=["api", "error-handling", "retry", "category:resilience"],
            )
            ts_manifest = await _generate_and_save_manifest(
                ts_engine, tmp_path, "typescript", "TypeScript patterns"
            )

            go_engine, go_repo, go_db = await _create_ganglion_db(tmp_path, "go")
            go_meth = await _insert_methodology(
                go_repo,
                problem="Go HTTP client error handling with retry logic",
                solution="Use custom Transport with backoff and context cancellation",
                language="go",
                tags=["api", "error-handling", "retry", "category:resilience"],
            )
            go_manifest = await _generate_and_save_manifest(
                go_engine, tmp_path, "go", "Go patterns"
            )

            try:
                federation = _build_federation(
                    siblings=[
                        {
                            "name": "typescript",
                            "db_path": ts_db,
                            "manifest_path": str(ts_manifest),
                        },
                        {
                            "name": "go",
                            "db_path": go_db,
                            "manifest_path": str(go_manifest),
                        },
                    ],
                    relevance_threshold=0.0,
                    max_results=10,
                )

                results = await federation.query(
                    "API error handling retry logic", max_total=10,
                )

                result_ids = {r.methodology.id for r in results}
                source_names = {r.source_instance for r in results}

                assert len(results) >= 2, f"Expected results from 2 ganglia, got {len(results)}"
                assert ts_meth.id in result_ids, "Should find TypeScript methodology"
                assert go_meth.id in result_ids, "Should find Go methodology"
                assert "typescript" in source_names
                assert "go" in source_names
            finally:
                await ts_engine.close()
                await go_engine.close()

    @pytest.mark.asyncio
    async def test_deduplication_across_ganglia(self):
        """If the same methodology ID exists in multiple ganglia, it should appear only once."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            shared_id = str(uuid.uuid4())

            eng1, repo1, db1 = await _create_ganglion_db(tmp_path, "ganglion_a")
            m1 = Methodology(
                id=shared_id,
                problem_description="Shared cross-language concurrency pattern",
                solution_code="Use worker pool with bounded channel",
                language="go",
                tags=["concurrency", "category:parallelism"],
                scope="global",
            )
            await repo1.save_methodology(m1)
            mf1 = await _generate_and_save_manifest(eng1, tmp_path, "ganglion_a")

            eng2, repo2, db2 = await _create_ganglion_db(tmp_path, "ganglion_b")
            m2 = Methodology(
                id=shared_id,
                problem_description="Shared cross-language concurrency pattern",
                solution_code="Use worker pool with bounded channel",
                language="go",
                tags=["concurrency", "category:parallelism"],
                scope="global",
            )
            await repo2.save_methodology(m2)
            mf2 = await _generate_and_save_manifest(eng2, tmp_path, "ganglion_b")

            try:
                federation = _build_federation(
                    siblings=[
                        {"name": "ganglion_a", "db_path": db1, "manifest_path": str(mf1)},
                        {"name": "ganglion_b", "db_path": db2, "manifest_path": str(mf2)},
                    ],
                    relevance_threshold=0.0,
                    max_results=10,
                )

                results = await federation.query("concurrency worker pool pattern", max_total=10)
                matching = [r for r in results if r.methodology.id == shared_id]
                assert len(matching) == 1, (
                    f"Expected exactly 1 result for shared ID, got {len(matching)}"
                )
            finally:
                await eng1.close()
                await eng2.close()


# ---------------------------------------------------------------------------
# Test: Relevance scoring
# ---------------------------------------------------------------------------

class TestFederationRelevanceScoring:
    """Test manifest-based relevance scoring integration."""

    @pytest.mark.asyncio
    async def test_high_threshold_filters_irrelevant_siblings(self):
        """With a high relevance threshold, unrelated ganglia should be skipped."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            engine, repo, db_path = await _create_ganglion_db(tmp_path, "quantum")
            await _insert_methodology(
                repo,
                problem="Quantum error correction with surface codes",
                solution="Implement stabilizer measurements on topological qubits",
                language="python",
                tags=["quantum", "error-correction", "category:quantum-computing"],
            )
            manifest_path = await _generate_and_save_manifest(
                engine, tmp_path, "quantum", "Quantum computing patterns"
            )

            try:
                federation = _build_federation(
                    siblings=[{
                        "name": "quantum",
                        "db_path": db_path,
                        "manifest_path": str(manifest_path),
                    }],
                    relevance_threshold=0.9,
                )

                results = await federation.query("react component optimization hooks")
                assert len(results) == 0, (
                    f"Expected 0 results with high relevance threshold, got {len(results)}"
                )
            finally:
                await engine.close()

    @pytest.mark.asyncio
    async def test_low_threshold_includes_relevant(self):
        """With threshold 0.0, related ganglia return results."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            engine, repo, db_path = await _create_ganglion_db(tmp_path, "misc")
            await _insert_methodology(
                repo,
                problem="Database migration rollback strategies",
                solution="Use versioned migration scripts with undo capability",
                language="python",
                tags=["database", "migration", "category:devops"],
            )
            manifest_path = await _generate_and_save_manifest(
                engine, tmp_path, "misc", "Miscellaneous patterns"
            )

            try:
                federation = _build_federation(
                    siblings=[{
                        "name": "misc",
                        "db_path": db_path,
                        "manifest_path": str(manifest_path),
                    }],
                    relevance_threshold=0.0,
                )

                results = await federation.query("database migration rollback strategies")
                assert len(results) >= 1
            finally:
                await engine.close()


# ---------------------------------------------------------------------------
# Test: End-to-end lifecycle
# ---------------------------------------------------------------------------

class TestFederationEndToEnd:
    """End-to-end scenario: simulate the real federation flow."""

    @pytest.mark.asyncio
    async def test_full_ganglion_lifecycle(self):
        """Simulate: create ganglion -> insert knowledge -> generate manifest -> federated query."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # Step 1: Create "primary" DB (Python brain)
            primary_engine, primary_repo, _primary_db = await _create_ganglion_db(
                tmp_path, "primary"
            )
            await _insert_methodology(
                primary_repo,
                problem="Python decorator pattern for caching function results",
                solution="Use functools.lru_cache or custom decorator with dict-based cache",
                language="python",
                tags=["decorator", "caching", "category:patterns"],
            )

            # Step 2: Create "typescript" ganglion (sibling)
            ts_engine, ts_repo, ts_db = await _create_ganglion_db(tmp_path, "typescript")
            ts_meth1 = await _insert_methodology(
                ts_repo,
                problem="TypeScript decorator pattern for caching API responses",
                solution="Use class decorator with WeakMap-based cache for method results",
                language="typescript",
                tags=["decorator", "caching", "api", "category:patterns"],
            )
            ts_meth2 = await _insert_methodology(
                ts_repo,
                problem="React server component streaming with Suspense boundaries",
                solution="Wrap async data components in Suspense with fallback UI",
                language="typescript",
                tags=["react", "streaming", "suspense", "category:rendering"],
            )

            # Step 3: Generate manifest
            ts_manifest_path = await _generate_and_save_manifest(
                ts_engine, tmp_path, "typescript", "TypeScript & React patterns"
            )

            try:
                # Step 4: Build federation (primary queries siblings)
                federation = _build_federation(
                    siblings=[{
                        "name": "typescript",
                        "db_path": ts_db,
                        "manifest_path": str(ts_manifest_path),
                    }],
                    relevance_threshold=0.0,
                )

                # Step 5: Query for "decorator caching" — should find sibling result
                results = await federation.query("decorator caching pattern", max_total=5)
                assert len(results) >= 1
                result_ids = {r.methodology.id for r in results}
                assert ts_meth1.id in result_ids, (
                    "Federation should return the TypeScript caching methodology"
                )

                # Step 6: Query for "react suspense"
                results2 = await federation.query(
                    "react server component suspense streaming", max_total=5
                )
                assert len(results2) >= 1
                result2_ids = {r.methodology.id for r in results2}
                assert ts_meth2.id in result2_ids

                # Step 7: Verify source attribution
                for r in results:
                    assert r.source_instance == "typescript"
                    assert r.source_db_path == ts_db

            finally:
                await primary_engine.close()
                await ts_engine.close()


# ---------------------------------------------------------------------------
# Test: Keyword extraction
# ---------------------------------------------------------------------------

class TestKeywordExtraction:
    """Test the keyword extraction used by federation queries."""

    def test_extracts_meaningful_keywords(self):
        keywords = _extract_keywords("React hooks custom state management with useReducer")
        assert "react" in keywords
        assert "hooks" in keywords
        assert "usereducer" in keywords
        assert "with" not in keywords

    def test_empty_input(self):
        keywords = _extract_keywords("")
        assert keywords == []

    def test_deduplicates(self):
        keywords = _extract_keywords("react react react hooks hooks")
        assert keywords.count("react") == 1
        assert keywords.count("hooks") == 1

    def test_respects_max_keywords(self):
        long_text = " ".join(f"keyword{i}longword" for i in range(30))
        keywords = _extract_keywords(long_text, max_keywords=5)
        assert len(keywords) <= 5


# ---------------------------------------------------------------------------
# Test: FederationResult data model
# ---------------------------------------------------------------------------

class TestFederationResultModel:
    """Test FederationResult data structure."""

    def test_repr(self):
        m = Methodology(
            id="test-123",
            problem_description="test problem",
            solution_code="test solution",
        )
        fr = FederationResult(
            methodology=m,
            source_instance="typescript",
            source_db_path="/tmp/test.db",
            relevance_score=0.75,
            fts_rank=1.5,
        )
        repr_str = repr(fr)
        assert "test-123" in repr_str
        assert "typescript" in repr_str
        assert "0.750" in repr_str


# ---------------------------------------------------------------------------
# Test: Sibling summaries for CLI
# ---------------------------------------------------------------------------

class TestGetSiblingSummaries:
    """Test the get_sibling_summaries method for CLI status display."""

    @pytest.mark.asyncio
    async def test_summaries_with_real_ganglion(self):
        """Summaries should reflect real ganglion state."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            engine, repo, db_path = await _create_ganglion_db(tmp_path, "rust")
            try:
                await _insert_methodology(
                    repo,
                    problem="Rust async trait patterns with tokio",
                    solution="Use async-trait crate or manual Future boxing",
                    language="rust",
                    tags=["async", "tokio", "category:concurrency"],
                )
                manifest_path = await _generate_and_save_manifest(
                    engine, tmp_path, "rust", "Rust patterns"
                )

                federation = _build_federation(
                    siblings=[{
                        "name": "rust",
                        "db_path": db_path,
                        "description": "Rust language patterns",
                        "manifest_path": str(manifest_path),
                    }],
                )

                summaries = await federation.get_sibling_summaries()
                assert len(summaries) == 1
                s = summaries[0]
                assert s["name"] == "rust"
                assert s["db_exists"] is True
                assert s["total_methodologies"] == 1
                assert "rust" in s["languages"]
            finally:
                await engine.close()

    @pytest.mark.asyncio
    async def test_summaries_with_missing_db(self):
        """Summaries should report db_exists=False for missing DBs."""
        federation = _build_federation(
            siblings=[{
                "name": "ghost",
                "db_path": "/tmp/nonexistent_ganglion/claw.db",
            }],
        )

        summaries = await federation.get_sibling_summaries()
        assert len(summaries) == 1
        assert summaries[0]["db_exists"] is False
        assert summaries[0]["total_methodologies"] == 0
