"""Tests for multi-instance federation infrastructure.

Validates:
- Brain manifest generation and loading
- Manifest relevance scoring
- Cross-instance FTS5 retrieval via read-only DB
- Keyword extraction
- FTS5 query building
- Federation query with multiple siblings
- Graceful fallback when sibling unavailable
- Instance registry config parsing
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import uuid
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from claw.community.manifest import (
    generate_manifest,
    load_manifest,
    save_manifest,
    score_manifest_relevance,
)
from claw.community.federation import (
    Federation,
    FederationResult,
    _build_safe_fts5_query,
    _extract_keywords,
)
from claw.core.config import InstanceConfig, InstanceRegistryConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


class FakeEngine:
    """Real in-memory aiosqlite engine for manifest/federation tests."""

    def __init__(self):
        self._conn = None

    async def connect(self):
        self._conn = await aiosqlite.connect(":memory:")
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS methodologies (
                id TEXT PRIMARY KEY,
                problem_description TEXT NOT NULL,
                solution_code TEXT NOT NULL,
                methodology_notes TEXT,
                source_task_id TEXT,
                tags TEXT NOT NULL DEFAULT '[]',
                language TEXT,
                scope TEXT NOT NULL DEFAULT 'project',
                methodology_type TEXT,
                files_affected TEXT NOT NULL DEFAULT '[]',
                tech_stack TEXT NOT NULL DEFAULT '[]',
                created_at TEXT,
                lifecycle_state TEXT NOT NULL DEFAULT 'embryonic',
                retrieval_count INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                last_retrieved_at TEXT,
                generation INTEGER NOT NULL DEFAULT 0,
                fitness_vector TEXT NOT NULL DEFAULT '{}',
                parent_ids TEXT NOT NULL DEFAULT '[]',
                superseded_by TEXT,
                prism_data TEXT,
                capability_data TEXT,
                novelty_score REAL,
                potential_score REAL
            );
            CREATE TABLE IF NOT EXISTS pulse_discoveries (
                id TEXT PRIMARY KEY,
                github_url TEXT NOT NULL,
                canonical_url TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'discovered',
                UNIQUE(canonical_url)
            );
        """)
        await self._conn.commit()

    @property
    def conn(self):
        return self._conn

    async def execute(self, query, params=None):
        await self._conn.execute(query, params or [])
        await self._conn.commit()

    async def fetch_all(self, query, params=None):
        cursor = await self._conn.execute(query, params or [])
        return [dict(r) for r in await cursor.fetchall()]

    async def fetch_one(self, query, params=None):
        cursor = await self._conn.execute(query, params or [])
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def close(self):
        if self._conn:
            await self._conn.close()


async def _seed_engine(engine: FakeEngine, records: list[dict[str, Any]]):
    """Insert methodology records into a FakeEngine."""
    for r in records:
        await engine.execute(
            """INSERT INTO methodologies (
                id, problem_description, solution_code, methodology_notes,
                tags, language, scope, methodology_type, lifecycle_state,
                success_count, failure_count, retrieval_count,
                novelty_score, potential_score, capability_data, tech_stack
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                r.get("id", str(uuid.uuid4())),
                r.get("problem_description", ""),
                r.get("solution_code", ""),
                r.get("methodology_notes", ""),
                json.dumps(r.get("tags", [])),
                r.get("language", "python"),
                r.get("scope", "global"),
                r.get("methodology_type", "PATTERN"),
                r.get("lifecycle_state", "viable"),
                r.get("success_count", 3),
                r.get("failure_count", 0),
                r.get("retrieval_count", 5),
                r.get("novelty_score", 0.7),
                r.get("potential_score", 0.6),
                json.dumps(r.get("capability_data", {})),
                json.dumps(r.get("tech_stack", [])),
            ],
        )


def _create_sibling_db(
    db_path: Path,
    records: list[dict[str, Any]],
) -> None:
    """Create a real SQLite DB at db_path with FTS5 and populated data."""
    import sqlite3

    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS methodologies (
            id TEXT PRIMARY KEY,
            problem_description TEXT NOT NULL,
            solution_code TEXT NOT NULL,
            methodology_notes TEXT,
            source_task_id TEXT,
            tags TEXT NOT NULL DEFAULT '[]',
            language TEXT,
            scope TEXT NOT NULL DEFAULT 'project',
            methodology_type TEXT,
            files_affected TEXT NOT NULL DEFAULT '[]',
            tech_stack TEXT NOT NULL DEFAULT '[]',
            created_at TEXT,
            lifecycle_state TEXT NOT NULL DEFAULT 'embryonic',
            retrieval_count INTEGER NOT NULL DEFAULT 0,
            success_count INTEGER NOT NULL DEFAULT 0,
            failure_count INTEGER NOT NULL DEFAULT 0,
            last_retrieved_at TEXT,
            generation INTEGER NOT NULL DEFAULT 0,
            fitness_vector TEXT NOT NULL DEFAULT '{}',
            parent_ids TEXT NOT NULL DEFAULT '[]',
            superseded_by TEXT,
            prism_data TEXT,
            capability_data TEXT,
            novelty_score REAL,
            potential_score REAL
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS methodology_fts
        USING fts5(methodology_id, content, tokenize='porter ascii')
    """)

    for r in records:
        mid = r.get("id", str(uuid.uuid4()))
        conn.execute(
            """INSERT INTO methodologies (
                id, problem_description, solution_code, methodology_notes,
                tags, language, scope, methodology_type, lifecycle_state,
                success_count, failure_count, retrieval_count,
                novelty_score, potential_score, capability_data, tech_stack
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                mid,
                r.get("problem_description", ""),
                r.get("solution_code", ""),
                r.get("methodology_notes", ""),
                json.dumps(r.get("tags", [])),
                r.get("language", "python"),
                r.get("scope", "global"),
                r.get("methodology_type", "PATTERN"),
                r.get("lifecycle_state", "viable"),
                r.get("success_count", 3),
                r.get("failure_count", 0),
                r.get("retrieval_count", 5),
                r.get("novelty_score", 0.7),
                r.get("potential_score", 0.6),
                json.dumps(r.get("capability_data", {})),
                json.dumps(r.get("tech_stack", [])),
            ],
        )
        # Insert into FTS5
        content_parts = [
            r.get("problem_description", ""),
            r.get("solution_code", ""),
            r.get("methodology_notes", ""),
        ]
        conn.execute(
            "INSERT INTO methodology_fts (methodology_id, content) VALUES (?, ?)",
            [mid, " ".join(content_parts)],
        )

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Manifest Tests
# ---------------------------------------------------------------------------

class TestManifestGeneration:
    """Test brain manifest generation from claw.db data."""

    def test_empty_db_generates_manifest(self):
        async def _run_test():
            engine = FakeEngine()
            await engine.connect()
            try:
                m = await generate_manifest(engine, "test", "A test instance")
                assert m["manifest_version"] == "1.0"
                assert m["instance_name"] == "test"
                assert m["instance_description"] == "A test instance"
                assert m["total_methodologies"] == 0
                assert isinstance(m["lifecycle_distribution"], dict)
                assert isinstance(m["top_categories"], dict)
                assert isinstance(m["language_breakdown"], dict)
                assert isinstance(m["domain_keywords"], list)
                assert len(m["fingerprint"]) == 16
            finally:
                await engine.close()
        _run(_run_test())

    def test_populated_db_counts_correctly(self):
        async def _run_test():
            engine = FakeEngine()
            await engine.connect()
            try:
                await _seed_engine(engine, [
                    {"id": "m1", "problem_description": "ML pipeline", "tags": ["category:ai_integration", "source:https://github.com/test/repo1"], "language": "python", "lifecycle_state": "viable"},
                    {"id": "m2", "problem_description": "REST API design", "tags": ["category:architecture", "source:https://github.com/test/repo2"], "language": "python", "lifecycle_state": "thriving"},
                    {"id": "m3", "problem_description": "React components", "tags": ["category:architecture"], "language": "typescript", "lifecycle_state": "viable"},
                    {"id": "m4", "problem_description": "Dead pattern", "tags": [], "language": "python", "lifecycle_state": "dead"},
                ])
                m = await generate_manifest(engine)
                assert m["total_methodologies"] == 4
                assert m["lifecycle_distribution"]["viable"] == 2
                assert m["lifecycle_distribution"]["thriving"] == 1
                assert m["lifecycle_distribution"]["dead"] == 1
                # Dead/dormant excluded from categories
                assert "ai_integration" in m["top_categories"]
                assert "architecture" in m["top_categories"]
                assert m["language_breakdown"]["python"] == 2  # Excludes dead
                assert m["language_breakdown"]["typescript"] == 1
                assert "https://github.com/test/repo1" in m["source_repos"]
                assert m["source_repo_count"] == 2
            finally:
                await engine.close()
        _run(_run_test())

    def test_save_and_load_roundtrip(self):
        async def _run_test():
            engine = FakeEngine()
            await engine.connect()
            try:
                await _seed_engine(engine, [
                    {"id": "m1", "problem_description": "Test", "tags": ["category:testing"], "language": "python", "lifecycle_state": "viable"},
                ])
                with tempfile.TemporaryDirectory() as tmpdir:
                    path = Path(tmpdir) / "manifest.json"
                    saved = await save_manifest(engine, path, "test-inst", "Testing domain")
                    loaded = load_manifest(path)
                    assert loaded is not None
                    assert loaded["instance_name"] == "test-inst"
                    assert loaded["total_methodologies"] == saved["total_methodologies"]
                    assert loaded["fingerprint"] == saved["fingerprint"]
            finally:
                await engine.close()
        _run(_run_test())

    def test_load_missing_manifest_returns_none(self):
        result = load_manifest(Path("/nonexistent/manifest.json"))
        assert result is None

    def test_load_corrupt_manifest_returns_none(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not json {{{")
            f.flush()
            result = load_manifest(Path(f.name))
            assert result is None

    def test_pulse_discoveries_counted(self):
        async def _run_test():
            engine = FakeEngine()
            await engine.connect()
            try:
                await engine.execute(
                    "INSERT INTO pulse_discoveries (id, github_url, canonical_url, status) VALUES (?, ?, ?, ?)",
                    ["p1", "https://github.com/test/repo", "https://github.com/test/repo", "assimilated"],
                )
                await engine.execute(
                    "INSERT INTO pulse_discoveries (id, github_url, canonical_url, status) VALUES (?, ?, ?, ?)",
                    ["p2", "https://github.com/test/repo2", "https://github.com/test/repo2", "failed"],
                )
                m = await generate_manifest(engine)
                assert m["pulse_discoveries_assimilated"] == 1
            finally:
                await engine.close()
        _run(_run_test())


class TestManifestRelevance:
    """Test manifest relevance scoring."""

    def test_high_relevance_for_matching_keywords(self):
        manifest = {
            "domain_keywords": ["quantum", "physics", "qubits", "gates", "error_correction"],
            "top_categories": {"quantum_computing": 50, "algorithms": 20},
            "language_breakdown": {"python": 100},
            "total_methodologies": 200,
            "lifecycle_distribution": {"viable": 80, "thriving": 20},
        }
        score = score_manifest_relevance(manifest, ["quantum", "error_correction"], "python")
        assert score > 0.5

    def test_low_relevance_for_unrelated_keywords(self):
        manifest = {
            "domain_keywords": ["quantum", "physics"],
            "top_categories": {"quantum_computing": 50},
            "language_breakdown": {"python": 100},
            "total_methodologies": 200,
            "lifecycle_distribution": {"viable": 80},
        }
        score = score_manifest_relevance(manifest, ["css", "flexbox", "responsive"], "javascript")
        assert score < 0.3

    def test_empty_manifest_returns_zero(self):
        assert score_manifest_relevance({}, ["test"], "python") == 0.0
        assert score_manifest_relevance(None, ["test"], "python") == 0.0

    def test_empty_keywords_returns_zero(self):
        manifest = {"domain_keywords": ["test"], "top_categories": {}, "language_breakdown": {}}
        assert score_manifest_relevance(manifest, [], "python") == 0.0

    def test_language_match_boosts_score(self):
        manifest = {
            "domain_keywords": ["web"],
            "top_categories": {"web_design": 50},
            "language_breakdown": {"typescript": 100},
            "total_methodologies": 100,
            "lifecycle_distribution": {"viable": 50},
        }
        score_ts = score_manifest_relevance(manifest, ["web"], "typescript")
        score_py = score_manifest_relevance(manifest, ["web"], "python")
        assert score_ts > score_py

    def test_maturity_contributes_to_score(self):
        small = {
            "domain_keywords": ["ai"],
            "top_categories": {"ai": 5},
            "language_breakdown": {"python": 10},
            "total_methodologies": 10,
            "lifecycle_distribution": {"embryonic": 10},
        }
        large = {
            "domain_keywords": ["ai"],
            "top_categories": {"ai": 200},
            "language_breakdown": {"python": 200},
            "total_methodologies": 300,
            "lifecycle_distribution": {"viable": 100, "thriving": 50},
        }
        assert score_manifest_relevance(large, ["ai"], "python") > score_manifest_relevance(small, ["ai"], "python")


# ---------------------------------------------------------------------------
# Keyword Extraction Tests
# ---------------------------------------------------------------------------

class TestKeywordExtraction:
    def test_extracts_meaningful_words(self):
        kw = _extract_keywords("Implement quantum error correction for stabilizer codes")
        assert "quantum" in kw
        assert "error" in kw
        assert "correction" in kw
        assert "stabilizer" in kw
        assert "codes" in kw

    def test_filters_stop_words(self):
        kw = _extract_keywords("The quick brown fox jumps over the lazy dog")
        assert "the" not in kw
        assert "over" not in kw
        assert "quick" in kw
        assert "brown" in kw

    def test_deduplicates(self):
        kw = _extract_keywords("retry retry retry backoff backoff")
        assert kw.count("retry") == 1
        assert kw.count("backoff") == 1

    def test_max_limit(self):
        long_text = " ".join(f"word{i}" for i in range(100))
        kw = _extract_keywords(long_text, max_keywords=10)
        assert len(kw) <= 10

    def test_empty_input(self):
        assert _extract_keywords("") == []
        assert _extract_keywords("a b") == []  # All too short


class TestFTS5QueryBuilder:
    def test_builds_or_query(self):
        q = _build_safe_fts5_query(["quantum", "physics", "gates"])
        assert '"quantum"' in q
        assert '"physics"' in q
        assert '"gates"' in q
        assert "OR" in q

    def test_strips_special_chars(self):
        q = _build_safe_fts5_query(["test@123", "hello-world"])
        assert "@" not in q
        assert "-" not in q

    def test_filters_short_tokens(self):
        q = _build_safe_fts5_query(["ab", "cd", "testing"])
        assert '"testing"' in q
        # ab and cd are < 3 chars

    def test_empty_returns_empty(self):
        assert _build_safe_fts5_query([]) == ""
        assert _build_safe_fts5_query(["ab"]) == ""


# ---------------------------------------------------------------------------
# Federation Tests (with real SQLite files)
# ---------------------------------------------------------------------------

class TestFederationQuery:
    """Test cross-instance retrieval using real on-disk SQLite DBs."""

    def test_query_returns_results_from_sibling(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sibling_db = Path(tmpdir) / "quantum" / "claw.db"
            sibling_db.parent.mkdir()
            manifest_path = Path(tmpdir) / "quantum" / "brain_manifest.json"

            _create_sibling_db(sibling_db, [
                {
                    "id": "q1",
                    "problem_description": "Quantum error correction using stabilizer codes",
                    "solution_code": "def stabilizer_decode(syndrome): ...",
                    "methodology_notes": "Implements surface code decoding for quantum error correction",
                    "tags": ["category:quantum_computing"],
                    "language": "python",
                    "lifecycle_state": "viable",
                },
                {
                    "id": "q2",
                    "problem_description": "Qubit state tomography",
                    "solution_code": "def tomography(measurements): ...",
                    "methodology_notes": "Reconstruct qubit state from measurement data",
                    "tags": ["category:quantum_computing"],
                    "language": "python",
                    "lifecycle_state": "viable",
                },
            ])

            # Write manifest
            manifest = {
                "manifest_version": "1.0",
                "instance_name": "quantum-physics",
                "total_methodologies": 2,
                "domain_keywords": ["quantum", "error", "correction", "qubits", "gates"],
                "top_categories": {"quantum_computing": 2},
                "language_breakdown": {"python": 2},
                "lifecycle_distribution": {"viable": 2},
            }
            manifest_path.write_text(json.dumps(manifest))

            config = InstanceRegistryConfig(
                enabled=True,
                federation_relevance_threshold=0.1,
                federation_max_results=3,
                siblings=[
                    InstanceConfig(
                        name="quantum-physics",
                        db_path=str(sibling_db),
                        description="Quantum computing patterns",
                        manifest_path=str(manifest_path),
                    ),
                ],
            )

            federation = Federation(config)
            results = _run(federation.query("quantum error correction stabilizer"))
            assert len(results) >= 1
            assert results[0].source_instance == "quantum-physics"
            assert results[0].methodology.id in ("q1", "q2")

    def test_query_skips_low_relevance_sibling(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sibling_db = Path(tmpdir) / "web" / "claw.db"
            sibling_db.parent.mkdir()
            manifest_path = Path(tmpdir) / "web" / "brain_manifest.json"

            _create_sibling_db(sibling_db, [
                {
                    "id": "w1",
                    "problem_description": "CSS flexbox layout",
                    "solution_code": ".container { display: flex; }",
                    "methodology_notes": "Responsive flexbox pattern",
                    "language": "css",
                    "lifecycle_state": "viable",
                },
            ])

            manifest = {
                "manifest_version": "1.0",
                "instance_name": "web-design",
                "total_methodologies": 1,
                "domain_keywords": ["css", "flexbox", "responsive", "html"],
                "top_categories": {"web_design": 1},
                "language_breakdown": {"css": 1},
                "lifecycle_distribution": {"viable": 1},
            }
            manifest_path.write_text(json.dumps(manifest))

            config = InstanceRegistryConfig(
                enabled=True,
                federation_relevance_threshold=0.5,  # High threshold
                federation_max_results=3,
                siblings=[
                    InstanceConfig(
                        name="web-design",
                        db_path=str(sibling_db),
                        description="Web design patterns",
                        manifest_path=str(manifest_path),
                    ),
                ],
            )

            federation = Federation(config)
            # Query about quantum computing — should NOT match web-design
            results = _run(federation.query("quantum error correction"))
            assert len(results) == 0

    def test_query_handles_missing_db(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "ghost_manifest.json"
            manifest = {
                "manifest_version": "1.0",
                "domain_keywords": ["test"],
                "top_categories": {"test": 1},
                "language_breakdown": {"python": 1},
                "total_methodologies": 10,
                "lifecycle_distribution": {"viable": 5},
            }
            manifest_path.write_text(json.dumps(manifest))

            config = InstanceRegistryConfig(
                enabled=True,
                federation_relevance_threshold=0.0,
                siblings=[
                    InstanceConfig(
                        name="ghost",
                        db_path="/nonexistent/claw.db",
                        description="Missing DB",
                        manifest_path=str(manifest_path),
                    ),
                ],
            )

            federation = Federation(config)
            results = _run(federation.query("test pattern"))
            assert results == []

    def test_query_skips_dead_methodologies(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sibling_db = Path(tmpdir) / "sibling.db"
            manifest_path = Path(tmpdir) / "manifest.json"

            _create_sibling_db(sibling_db, [
                {
                    "id": "d1",
                    "problem_description": "Dead pattern for testing lifecycle filter",
                    "solution_code": "pass",
                    "methodology_notes": "Should be filtered out",
                    "language": "python",
                    "lifecycle_state": "dead",
                },
            ])

            manifest = {
                "manifest_version": "1.0",
                "domain_keywords": ["testing", "pattern"],
                "top_categories": {"testing": 1},
                "language_breakdown": {"python": 1},
                "total_methodologies": 1,
                "lifecycle_distribution": {"dead": 1},
            }
            manifest_path.write_text(json.dumps(manifest))

            config = InstanceRegistryConfig(
                enabled=True,
                federation_relevance_threshold=0.0,
                siblings=[
                    InstanceConfig(
                        name="dead-inst",
                        db_path=str(sibling_db),
                        manifest_path=str(manifest_path),
                    ),
                ],
            )

            federation = Federation(config)
            results = _run(federation.query("testing lifecycle filter pattern"))
            assert len(results) == 0

    def test_query_filters_by_language(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sibling_db = Path(tmpdir) / "multi.db"
            manifest_path = Path(tmpdir) / "manifest.json"

            _create_sibling_db(sibling_db, [
                {
                    "id": "py1",
                    "problem_description": "Database connection pooling pattern",
                    "solution_code": "import asyncpg",
                    "methodology_notes": "Python async DB pooling",
                    "language": "python",
                    "lifecycle_state": "viable",
                },
                {
                    "id": "rs1",
                    "problem_description": "Database connection pooling pattern",
                    "solution_code": "use sqlx::Pool",
                    "methodology_notes": "Rust async DB pooling",
                    "language": "rust",
                    "lifecycle_state": "viable",
                },
            ])

            manifest = {
                "manifest_version": "1.0",
                "domain_keywords": ["database", "pooling", "connection"],
                "top_categories": {"database": 2},
                "language_breakdown": {"python": 1, "rust": 1},
                "total_methodologies": 2,
                "lifecycle_distribution": {"viable": 2},
            }
            manifest_path.write_text(json.dumps(manifest))

            config = InstanceRegistryConfig(
                enabled=True,
                federation_relevance_threshold=0.0,
                siblings=[
                    InstanceConfig(
                        name="multi-lang",
                        db_path=str(sibling_db),
                        manifest_path=str(manifest_path),
                    ),
                ],
            )

            federation = Federation(config)
            results = _run(federation.query("database connection pooling", language="rust"))
            assert all(r.methodology.language == "rust" for r in results)

    def test_disabled_federation_returns_empty(self):
        config = InstanceRegistryConfig(enabled=False, siblings=[
            InstanceConfig(name="test", db_path="/tmp/test.db"),
        ])
        federation = Federation(config)
        results = _run(federation.query("anything"))
        assert results == []

    def test_no_siblings_returns_empty(self):
        config = InstanceRegistryConfig(enabled=True, siblings=[])
        federation = Federation(config)
        results = _run(federation.query("anything"))
        assert results == []

    def test_query_multiple_siblings(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Sibling 1: quantum
            q_db = Path(tmpdir) / "quantum.db"
            q_manifest = Path(tmpdir) / "q_manifest.json"
            _create_sibling_db(q_db, [
                {
                    "id": "q1",
                    "problem_description": "Quantum circuit optimization algorithm",
                    "solution_code": "def optimize_circuit(gates): ...",
                    "methodology_notes": "Optimize quantum circuits by gate merging",
                    "language": "python",
                    "lifecycle_state": "viable",
                },
            ])
            q_manifest.write_text(json.dumps({
                "manifest_version": "1.0",
                "domain_keywords": ["quantum", "circuit", "optimization"],
                "top_categories": {"quantum": 1},
                "language_breakdown": {"python": 1},
                "total_methodologies": 1,
                "lifecycle_distribution": {"viable": 1},
            }))

            # Sibling 2: optimization (also relevant)
            o_db = Path(tmpdir) / "optim.db"
            o_manifest = Path(tmpdir) / "o_manifest.json"
            _create_sibling_db(o_db, [
                {
                    "id": "o1",
                    "problem_description": "Algorithm optimization with dynamic programming",
                    "solution_code": "def dp_optimize(problem): ...",
                    "methodology_notes": "Optimization via memoization and DP",
                    "language": "python",
                    "lifecycle_state": "thriving",
                },
            ])
            o_manifest.write_text(json.dumps({
                "manifest_version": "1.0",
                "domain_keywords": ["optimization", "algorithm", "dynamic", "programming"],
                "top_categories": {"algorithms": 1},
                "language_breakdown": {"python": 1},
                "total_methodologies": 1,
                "lifecycle_distribution": {"thriving": 1},
            }))

            config = InstanceRegistryConfig(
                enabled=True,
                federation_relevance_threshold=0.0,
                federation_max_results=5,
                siblings=[
                    InstanceConfig(name="quantum", db_path=str(q_db), manifest_path=str(q_manifest)),
                    InstanceConfig(name="optim", db_path=str(o_db), manifest_path=str(o_manifest)),
                ],
            )

            federation = Federation(config)
            results = _run(federation.query("quantum circuit optimization algorithm"))
            assert len(results) >= 1
            sources = {r.source_instance for r in results}
            # At least one sibling should contribute
            assert len(sources) >= 1

    def test_dedup_across_instances(self):
        """If somehow two siblings have the same methodology ID, deduplicate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            shared_record = {
                "id": "shared-1",
                "problem_description": "Shared retry pattern across instances",
                "solution_code": "def retry(fn): ...",
                "methodology_notes": "Exponential backoff retry",
                "language": "python",
                "lifecycle_state": "viable",
            }

            db1 = Path(tmpdir) / "inst1.db"
            db2 = Path(tmpdir) / "inst2.db"
            m1 = Path(tmpdir) / "m1.json"
            m2 = Path(tmpdir) / "m2.json"

            _create_sibling_db(db1, [shared_record])
            _create_sibling_db(db2, [shared_record])

            manifest_data = {
                "manifest_version": "1.0",
                "domain_keywords": ["retry", "backoff", "pattern"],
                "top_categories": {"resilience": 1},
                "language_breakdown": {"python": 1},
                "total_methodologies": 1,
                "lifecycle_distribution": {"viable": 1},
            }
            m1.write_text(json.dumps(manifest_data))
            m2.write_text(json.dumps(manifest_data))

            config = InstanceRegistryConfig(
                enabled=True,
                federation_relevance_threshold=0.0,
                federation_max_results=5,
                siblings=[
                    InstanceConfig(name="inst1", db_path=str(db1), manifest_path=str(m1)),
                    InstanceConfig(name="inst2", db_path=str(db2), manifest_path=str(m2)),
                ],
            )

            federation = Federation(config)
            results = _run(federation.query("retry backoff exponential pattern"))
            ids = [r.methodology.id for r in results]
            assert ids.count("shared-1") <= 1  # Deduped


class TestSiblingSummaries:
    def test_summaries_for_existing_and_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            existing_db = Path(tmpdir) / "exists.db"
            existing_manifest = Path(tmpdir) / "manifest.json"
            _create_sibling_db(existing_db, [])
            existing_manifest.write_text(json.dumps({
                "manifest_version": "1.0",
                "total_methodologies": 42,
                "top_categories": {"testing": 10},
                "language_breakdown": {"python": 30},
            }))

            config = InstanceRegistryConfig(
                enabled=True,
                siblings=[
                    InstanceConfig(name="exists", db_path=str(existing_db), manifest_path=str(existing_manifest)),
                    InstanceConfig(name="missing", db_path="/nonexistent/claw.db", manifest_path="/nonexistent/m.json"),
                ],
            )

            federation = Federation(config)
            summaries = _run(federation.get_sibling_summaries())
            assert len(summaries) == 2
            assert summaries[0]["db_exists"] is True
            assert summaries[0]["total_methodologies"] == 42
            assert summaries[1]["db_exists"] is False
            assert summaries[1]["total_methodologies"] == 0


# ---------------------------------------------------------------------------
# Config Tests
# ---------------------------------------------------------------------------

class TestInstanceConfig:
    def test_default_config(self):
        config = InstanceRegistryConfig()
        assert config.enabled is False
        assert config.siblings == []
        assert config.federation_confidence_threshold == 0.3

    def test_config_with_siblings(self):
        config = InstanceRegistryConfig(
            enabled=True,
            instance_name="main",
            siblings=[
                InstanceConfig(name="quantum", db_path="/data/quantum.db", description="Quantum stuff"),
                InstanceConfig(name="web", db_path="/data/web.db"),
            ],
        )
        assert len(config.siblings) == 2
        assert config.siblings[0].name == "quantum"
        assert config.siblings[1].description == ""

    def test_instance_config_requires_name_and_path(self):
        with pytest.raises(Exception):
            InstanceConfig()  # Missing required fields
