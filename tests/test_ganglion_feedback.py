"""Integration tests for Path C Fix 2 — ganglion write-back feedback loop.

Verifies that SemanticMemory.record_retrieval and record_outcome, when
given a ``source_db_path`` pointing at a sibling ganglion DB, route the
writes to that ganglion's Repository via the GanglionRepositoryPool —
not to the primary repository.

All tests use REAL SQLite databases in temporary directories.
No mocks, no placeholders, no cached responses.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

import pytest

from claw.core.config import DatabaseConfig
from claw.core.models import Methodology
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository
from claw.memory.ganglion_pool import GanglionRepositoryPool
from claw.memory.semantic import SemanticMemory


# ---------------------------------------------------------------------------
# Minimal fixture helpers — real DBs, real schema, no mocks.
# ---------------------------------------------------------------------------


async def _make_db(tmp: Path, name: str) -> tuple[DatabaseEngine, Repository, str]:
    """Create a real SQLite DB at *tmp/name/claw.db* with the full schema."""
    db_dir = tmp / name
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "claw.db"

    engine = DatabaseEngine(DatabaseConfig(db_path=str(db_path)))
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    return engine, Repository(engine), str(db_path.resolve())


async def _insert_embryonic(
    repo: Repository,
    problem: str = "Example problem",
    language: str = "rust",
) -> Methodology:
    """Insert an embryonic methodology matching the state of real mined rows."""
    m = Methodology(
        id=str(uuid.uuid4()),
        problem_description=problem,
        solution_code="fn example() { /* placeholder */ }",
        language=language,
        tags=["category:code_quality"],
        methodology_notes="Example notes",
        lifecycle_state="embryonic",
        success_count=0,
        failure_count=0,
        retrieval_count=0,
        scope="project",
        fitness_vector={},
    )
    await repo.save_methodology(m)
    return m


class _StubEmbeddingEngine:
    """Minimal embedding engine stub — we never call encode in these tests."""
    def __init__(self) -> None:
        self.dim = 4

    async def async_encode(self, text: str):
        return [0.0, 0.0, 0.0, 0.0]

    def encode(self, text: str):
        return [0.0, 0.0, 0.0, 0.0]

    def close(self) -> None:
        pass


class _StubHybridSearch:
    """HybridSearch stub — SemanticMemory calls none of its methods in this test."""
    def __init__(self) -> None:
        pass


def _make_semantic(primary_repo: Repository) -> SemanticMemory:
    """Build a SemanticMemory wired to the primary repository only."""
    return SemanticMemory(
        repository=primary_repo,
        embedding_engine=_StubEmbeddingEngine(),  # type: ignore[arg-type]
        hybrid_search=_StubHybridSearch(),        # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGanglionRepositoryPool:
    """Pool-level behavior tests."""

    @pytest.mark.asyncio
    async def test_primary_path_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            engine, _repo, primary_path = await _make_db(tmp_path, "primary")
            try:
                pool = GanglionRepositoryPool(primary_db_path=primary_path)
                assert pool.is_primary(primary_path) is True
                result = await pool.get_repository(primary_path)
                assert result is None  # Caller uses ctx.repository directly
            finally:
                await engine.close()

    @pytest.mark.asyncio
    async def test_missing_path_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            pool = GanglionRepositoryPool(primary_db_path=None)
            with pytest.raises(FileNotFoundError):
                await pool.get_repository(str(Path(tmp) / "does_not_exist.db"))

    @pytest.mark.asyncio
    async def test_caches_second_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            engine_g, _repo_g, g_path = await _make_db(tmp_path, "rust")
            try:
                pool = GanglionRepositoryPool(primary_db_path=None)
                first = await pool.get_repository(g_path)
                second = await pool.get_repository(g_path)
                assert first is second
                assert len(pool) == 1
            finally:
                await engine_g.close()
                # Pool opened its own engine; close it too
                # (pool.close_all handles this)
                pool_engines = pool._engines  # type: ignore[attr-defined]
                for eng in list(pool_engines.values()):
                    await eng.close()

    @pytest.mark.asyncio
    async def test_close_all_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            engine_g, _repo_g, g_path = await _make_db(tmp_path, "rust")
            try:
                pool = GanglionRepositoryPool()
                await pool.get_repository(g_path)
                await pool.close_all()
                await pool.close_all()  # Must not raise
                assert len(pool) == 0
            finally:
                await engine_g.close()


class TestSemanticMemoryRouting:
    """SemanticMemory._resolve_repository routing behavior."""

    @pytest.mark.asyncio
    async def test_no_source_path_uses_primary(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary_engine, primary_repo, primary_path = await _make_db(tmp_path, "primary")
            try:
                sem = _make_semantic(primary_repo)
                pool = GanglionRepositoryPool(primary_db_path=primary_path)
                sem.set_ganglion_pool(pool)

                resolved = await sem._resolve_repository(None)
                assert resolved is primary_repo
                await pool.close_all()
            finally:
                await primary_engine.close()

    @pytest.mark.asyncio
    async def test_primary_source_path_uses_primary(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary_engine, primary_repo, primary_path = await _make_db(tmp_path, "primary")
            try:
                sem = _make_semantic(primary_repo)
                pool = GanglionRepositoryPool(primary_db_path=primary_path)
                sem.set_ganglion_pool(pool)

                resolved = await sem._resolve_repository(primary_path)
                assert resolved is primary_repo
                await pool.close_all()
            finally:
                await primary_engine.close()

    @pytest.mark.asyncio
    async def test_ganglion_path_uses_ganglion_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary_engine, primary_repo, primary_path = await _make_db(tmp_path, "primary")
            ganglion_engine, _ganglion_repo, ganglion_path = await _make_db(tmp_path, "rust")
            try:
                sem = _make_semantic(primary_repo)
                pool = GanglionRepositoryPool(primary_db_path=primary_path)
                sem.set_ganglion_pool(pool)

                resolved = await sem._resolve_repository(ganglion_path)
                assert resolved is not primary_repo
                assert resolved is not None
                await pool.close_all()
            finally:
                await primary_engine.close()
                await ganglion_engine.close()

    @pytest.mark.asyncio
    async def test_missing_ganglion_falls_back_to_primary(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary_engine, primary_repo, primary_path = await _make_db(tmp_path, "primary")
            try:
                sem = _make_semantic(primary_repo)
                pool = GanglionRepositoryPool(primary_db_path=primary_path)
                sem.set_ganglion_pool(pool)

                missing = str(tmp_path / "ghost" / "claw.db")
                resolved = await sem._resolve_repository(missing)
                assert resolved is primary_repo  # Graceful fallback
                await pool.close_all()
            finally:
                await primary_engine.close()


class TestRecordOutcomeWritesToGanglion:
    """End-to-end: a ganglion-sourced methodology promotes in its *own* DB."""

    @pytest.mark.asyncio
    async def test_success_promotes_embryonic_in_ganglion(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary_engine, primary_repo, primary_path = await _make_db(tmp_path, "primary")
            ganglion_engine, ganglion_repo, ganglion_path = await _make_db(tmp_path, "rust")
            try:
                methodology = await _insert_embryonic(
                    ganglion_repo,
                    problem="Rust lifetime for borrowed config",
                    language="rust",
                )

                # Sanity: primary DB has NO copy of this methodology.
                primary_lookup = await primary_repo.get_methodology(methodology.id)
                assert primary_lookup is None

                sem = _make_semantic(primary_repo)
                pool = GanglionRepositoryPool(primary_db_path=primary_path)
                sem.set_ganglion_pool(pool)

                await sem.record_outcome(
                    methodology.id,
                    success=True,
                    retrieval_relevance=0.75,
                    source_db_path=ganglion_path,
                )

                # Ganglion DB: row should be promoted to viable with success_count=1
                promoted = await ganglion_repo.get_methodology(methodology.id)
                assert promoted is not None
                assert promoted.success_count == 1
                assert promoted.lifecycle_state == "viable"
                assert promoted.fitness_vector  # Non-empty dict

                # Primary DB: still has no copy, no leaks
                leaked = await primary_repo.get_methodology(methodology.id)
                assert leaked is None

                await pool.close_all()
            finally:
                await primary_engine.close()
                await ganglion_engine.close()

    @pytest.mark.asyncio
    async def test_failure_records_to_ganglion_not_primary(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary_engine, primary_repo, primary_path = await _make_db(tmp_path, "primary")
            ganglion_engine, ganglion_repo, ganglion_path = await _make_db(tmp_path, "go")
            try:
                methodology = await _insert_embryonic(
                    ganglion_repo,
                    problem="Go channel deadlock",
                    language="go",
                )
                sem = _make_semantic(primary_repo)
                pool = GanglionRepositoryPool(primary_db_path=primary_path)
                sem.set_ganglion_pool(pool)

                await sem.record_outcome(
                    methodology.id,
                    success=False,
                    retrieval_relevance=0.4,
                    source_db_path=ganglion_path,
                )

                after = await ganglion_repo.get_methodology(methodology.id)
                assert after is not None
                assert after.failure_count == 1
                assert after.success_count == 0
                # Embryonic → no transition on first failure
                assert after.lifecycle_state == "embryonic"

                leaked = await primary_repo.get_methodology(methodology.id)
                assert leaked is None

                await pool.close_all()
            finally:
                await primary_engine.close()
                await ganglion_engine.close()

    @pytest.mark.asyncio
    async def test_record_retrieval_hits_ganglion(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary_engine, primary_repo, primary_path = await _make_db(tmp_path, "primary")
            ganglion_engine, ganglion_repo, ganglion_path = await _make_db(tmp_path, "typescript")
            try:
                m = await _insert_embryonic(
                    ganglion_repo,
                    problem="TS generic constraint pattern",
                    language="typescript",
                )
                before = await ganglion_repo.get_methodology(m.id)
                assert before is not None
                assert before.retrieval_count == 0

                sem = _make_semantic(primary_repo)
                pool = GanglionRepositoryPool(primary_db_path=primary_path)
                sem.set_ganglion_pool(pool)

                await sem.record_retrieval(m.id, source_db_path=ganglion_path)

                after = await ganglion_repo.get_methodology(m.id)
                assert after is not None
                assert after.retrieval_count == 1

                # Primary DB unchanged (no row at all)
                assert await primary_repo.get_methodology(m.id) is None

                await pool.close_all()
            finally:
                await primary_engine.close()
                await ganglion_engine.close()

    @pytest.mark.asyncio
    async def test_primary_sourced_outcome_still_writes_primary(self):
        """Regression guard: pre-Fix-2 callers without source_db_path must still work."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary_engine, primary_repo, primary_path = await _make_db(tmp_path, "primary")
            try:
                m = await _insert_embryonic(
                    primary_repo, problem="Local Python pattern", language="python",
                )
                sem = _make_semantic(primary_repo)
                pool = GanglionRepositoryPool(primary_db_path=primary_path)
                sem.set_ganglion_pool(pool)

                # No source_db_path — legacy call signature
                await sem.record_outcome(m.id, success=True, retrieval_relevance=0.8)

                promoted = await primary_repo.get_methodology(m.id)
                assert promoted is not None
                assert promoted.success_count == 1
                assert promoted.lifecycle_state == "viable"

                await pool.close_all()
            finally:
                await primary_engine.close()

    @pytest.mark.asyncio
    async def test_unknown_methodology_id_logs_and_continues(self):
        """Outcome for an id that doesn't exist in the target DB must not raise."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            primary_engine, primary_repo, primary_path = await _make_db(tmp_path, "primary")
            ganglion_engine, _ganglion_repo, ganglion_path = await _make_db(tmp_path, "misc")
            try:
                sem = _make_semantic(primary_repo)
                pool = GanglionRepositoryPool(primary_db_path=primary_path)
                sem.set_ganglion_pool(pool)

                phantom_id = str(uuid.uuid4())
                await sem.record_outcome(
                    phantom_id,
                    success=True,
                    retrieval_relevance=0.5,
                    source_db_path=ganglion_path,
                )
                # Should complete without raising; methodology simply isn't there
                await pool.close_all()
            finally:
                await primary_engine.close()
                await ganglion_engine.close()
