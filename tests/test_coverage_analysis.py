"""Tests for coverage analysis repository methods.

Uses real in-memory SQLite — no mocks.
"""

from __future__ import annotations

import json
import uuid

import pytest
import pytest_asyncio

from claw.core.config import DatabaseConfig
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository


@pytest_asyncio.fixture
async def repo():
    """Fresh in-memory DB with schema + migrations."""
    cfg = DatabaseConfig(db_path=":memory:")
    engine = DatabaseEngine(cfg)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    repository = Repository(engine)
    yield repository
    await engine.close()


async def _seed_methodology(engine, *, tags, language="python", state="viable"):
    """Insert a methodology with given tags and language."""
    mid = str(uuid.uuid4())
    tags_json = json.dumps(tags)
    await engine.execute(
        """INSERT INTO methodologies
           (id, problem_description, solution_code, tags, language, lifecycle_state)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [mid, f"Problem for {mid[:8]}", f"Solution for {mid[:8]}", tags_json, language, state],
    )
    return mid


@pytest.mark.asyncio
async def test_coverage_matrix_empty(repo):
    """Empty DB returns empty matrix."""
    matrix = await repo.get_coverage_matrix()
    assert matrix == {}


@pytest.mark.asyncio
async def test_coverage_matrix_single_category(repo):
    """Single methodology with one category tag."""
    await _seed_methodology(repo.engine, tags=["category:security"], language="python")
    matrix = await repo.get_coverage_matrix()
    assert "security" in matrix
    assert matrix["security"]["python"] == 1


@pytest.mark.asyncio
async def test_coverage_matrix_multiple_categories(repo):
    """Multiple methodologies across categories and languages."""
    await _seed_methodology(repo.engine, tags=["category:security"], language="python")
    await _seed_methodology(repo.engine, tags=["category:security"], language="python")
    await _seed_methodology(repo.engine, tags=["category:testing"], language="go")
    await _seed_methodology(repo.engine, tags=["category:architecture"], language="rust")
    await _seed_methodology(repo.engine, tags=["category:security", "category:testing"], language="typescript")

    matrix = await repo.get_coverage_matrix()

    assert matrix["security"]["python"] == 2
    assert matrix["testing"]["go"] == 1
    assert matrix["architecture"]["rust"] == 1
    assert matrix["security"]["typescript"] == 1
    assert matrix["testing"]["typescript"] == 1


@pytest.mark.asyncio
async def test_coverage_matrix_excludes_dead(repo):
    """Dead and dormant methodologies are excluded."""
    await _seed_methodology(repo.engine, tags=["category:security"], language="python", state="dead")
    await _seed_methodology(repo.engine, tags=["category:security"], language="python", state="dormant")
    await _seed_methodology(repo.engine, tags=["category:security"], language="python", state="viable")

    matrix = await repo.get_coverage_matrix()
    assert matrix["security"]["python"] == 1


@pytest.mark.asyncio
async def test_coverage_matrix_null_language(repo):
    """Methodology with NULL language maps to 'unknown'."""
    await _seed_methodology(repo.engine, tags=["category:cli_ux"], language=None)
    matrix = await repo.get_coverage_matrix()
    assert matrix["cli_ux"]["unknown"] == 1


@pytest.mark.asyncio
async def test_snapshot_save_and_load(repo):
    """Save a snapshot and retrieve it."""
    snapshot_id = str(uuid.uuid4())
    data = json.dumps({"security": {"python": 5}})
    sparse = json.dumps([["security", "go"]])
    await repo.save_coverage_snapshot(snapshot_id, data, sparse, 5)

    latest = await repo.get_latest_coverage_snapshot()
    assert latest is not None
    assert latest["id"] == snapshot_id
    assert latest["total_methodologies"] == 5
    assert json.loads(latest["snapshot_data"]) == {"security": {"python": 5}}
    assert json.loads(latest["sparse_cells"]) == [["security", "go"]]


@pytest.mark.asyncio
async def test_snapshot_latest_returns_most_recent(repo):
    """Latest snapshot is the most recently created."""
    # Use explicit timestamps to ensure ordering
    for i in range(3):
        sid = str(uuid.uuid4())
        await repo.engine.execute(
            """INSERT INTO coverage_snapshots
               (id, snapshot_data, sparse_cells, total_methodologies, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            [sid, json.dumps({"count": i}), "[]", i * 10, f"2026-01-0{i + 1}T00:00:00Z"],
        )

    latest = await repo.get_latest_coverage_snapshot()
    assert latest is not None
    assert latest["total_methodologies"] == 20  # Last one (i=2 → 20)


@pytest.mark.asyncio
async def test_coverage_trend(repo):
    """Trend returns snapshots newest-first."""
    for i in range(5):
        sid = str(uuid.uuid4())
        await repo.engine.execute(
            """INSERT INTO coverage_snapshots
               (id, snapshot_data, sparse_cells, total_methodologies, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            [sid, json.dumps({"i": i}), "[]", i, f"2026-01-0{i + 1}T00:00:00Z"],
        )

    trend = await repo.get_coverage_trend(limit=3)
    assert len(trend) == 3
    # Newest first
    assert trend[0]["total_methodologies"] == 4
    assert trend[1]["total_methodologies"] == 3


@pytest.mark.asyncio
async def test_snapshot_no_data(repo):
    """Latest snapshot returns None when no snapshots exist."""
    latest = await repo.get_latest_coverage_snapshot()
    assert latest is None

    trend = await repo.get_coverage_trend()
    assert trend == []
