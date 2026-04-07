"""Tests for GapAnalyzer — coverage matrix, sparse detection, repo scoring, snapshots.

Uses real in-memory and temp-file SQLite databases — no mocks.
"""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

import aiosqlite
import pytest
import pytest_asyncio

from claw.community.gap_analyzer import GapAnalyzer
from claw.core.config import (
    DatabaseConfig,
    GapAnalyzerConfig,
    InstanceConfig,
    InstanceRegistryConfig,
)
from claw.core.models import CoverageMatrix
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository


async def _create_sibling_db(path: str, methodologies: list[dict]) -> None:
    """Create a sibling ganglion DB at path with seeded methodologies."""
    async with aiosqlite.connect(path) as conn:
        await conn.execute("""
            CREATE TABLE methodologies (
                id TEXT PRIMARY KEY,
                problem_description TEXT NOT NULL DEFAULT '',
                solution_code TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
                language TEXT,
                lifecycle_state TEXT NOT NULL DEFAULT 'viable'
            )
        """)
        for m in methodologies:
            await conn.execute(
                "INSERT INTO methodologies (id, tags, language, lifecycle_state) VALUES (?, ?, ?, ?)",
                [
                    str(uuid.uuid4()),
                    json.dumps(m.get("tags", [])),
                    m.get("language"),
                    m.get("state", "viable"),
                ],
            )
        await conn.commit()


@pytest_asyncio.fixture
async def primary_setup(tmp_path):
    """Primary DB engine + repository + path."""
    db_path = str(tmp_path / "primary.db")
    cfg = DatabaseConfig(db_path=db_path)
    engine = DatabaseEngine(cfg)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    repo = Repository(engine)
    yield repo, engine, db_path
    await engine.close()


async def _seed(engine, tags, language="python", state="viable"):
    mid = str(uuid.uuid4())
    await engine.execute(
        """INSERT INTO methodologies
           (id, problem_description, solution_code, tags, language, lifecycle_state)
           VALUES (?, ?, ?, ?, ?, ?)""",
        [mid, "p", "s", json.dumps(tags), language, state],
    )
    return mid


# ---------------------------------------------------------------------------
# Coverage matrix tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coverage_matrix_primary_only(primary_setup):
    """Matrix from primary DB alone (no siblings)."""
    repo, engine, db_path = primary_setup

    await _seed(engine, ["category:security"], "python")
    await _seed(engine, ["category:testing"], "python")

    instances_cfg = InstanceRegistryConfig(
        enabled=False,
        instance_name="general",
    )
    analyzer = GapAnalyzer(repo, instances_cfg, db_path)
    matrix = await analyzer.compute_coverage_matrix()

    assert "security" in matrix.matrix
    assert matrix.matrix["security"]["general"] == 1
    assert matrix.matrix["testing"]["general"] == 1


@pytest.mark.asyncio
async def test_coverage_matrix_with_siblings(primary_setup, tmp_path):
    """Matrix aggregates primary + sibling ganglia."""
    repo, engine, db_path = primary_setup

    await _seed(engine, ["category:security"], "python")

    # Create sibling
    sib_path = str(tmp_path / "go_brain.db")
    await _create_sibling_db(sib_path, [
        {"tags": ["category:security"], "language": "go"},
        {"tags": ["category:cli_ux"], "language": "go"},
        {"tags": ["category:cli_ux"], "language": "go"},
    ])

    instances_cfg = InstanceRegistryConfig(
        enabled=True,
        instance_name="general",
        siblings=[
            InstanceConfig(name="go", db_path=sib_path, description="Go brain"),
        ],
    )
    analyzer = GapAnalyzer(repo, instances_cfg, db_path)
    matrix = await analyzer.compute_coverage_matrix()

    assert matrix.matrix["security"]["general"] == 1
    assert matrix.matrix["security"]["go"] == 1
    assert matrix.matrix["cli_ux"]["go"] == 2
    assert "general" in matrix.total_by_brain
    assert "go" in matrix.total_by_brain


@pytest.mark.asyncio
async def test_sparse_and_empty_detection(primary_setup, tmp_path):
    """Sparse and empty cells are correctly classified."""
    repo, engine, db_path = primary_setup

    # Add 5 security methodologies to primary (above threshold of 3)
    for _ in range(5):
        await _seed(engine, ["category:security"], "python")
    # Add 2 testing methodologies (below threshold)
    for _ in range(2):
        await _seed(engine, ["category:testing"], "python")

    sib_path = str(tmp_path / "ts_brain.db")
    await _create_sibling_db(sib_path, [
        {"tags": ["category:security"], "language": "typescript"},
    ])

    instances_cfg = InstanceRegistryConfig(
        enabled=True,
        instance_name="general",
        siblings=[
            InstanceConfig(name="typescript", db_path=sib_path),
        ],
    )
    gap_cfg = GapAnalyzerConfig(sparse_cell_threshold=3)
    analyzer = GapAnalyzer(repo, instances_cfg, db_path, gap_cfg)
    matrix = await analyzer.compute_coverage_matrix()

    # security/general=5 (adequate), security/typescript=1 (sparse)
    # testing/general=2 (sparse), testing/typescript=0 (empty)
    assert ("security", "typescript") in matrix.sparse_cells
    assert ("testing", "general") in matrix.sparse_cells
    assert ("testing", "typescript") in matrix.empty_cells
    assert ("security", "general") not in matrix.sparse_cells


@pytest.mark.asyncio
async def test_get_sparse_domains_sorted(primary_setup):
    """get_sparse_domains returns sorted by count ascending."""
    repo, engine, db_path = primary_setup

    await _seed(engine, ["category:a"], "python")
    await _seed(engine, ["category:a"], "python")
    await _seed(engine, ["category:b"], "python")

    instances_cfg = InstanceRegistryConfig(enabled=False, instance_name="general")
    gap_cfg = GapAnalyzerConfig(sparse_cell_threshold=5)
    analyzer = GapAnalyzer(repo, instances_cfg, db_path, gap_cfg)
    matrix = await analyzer.compute_coverage_matrix()

    sparse = analyzer.get_sparse_domains(matrix)
    # b=1 should come before a=2
    assert len(sparse) >= 2
    idx_b = next(i for i, (cat, _) in enumerate(sparse) if cat == "b")
    idx_a = next(i for i, (cat, _) in enumerate(sparse) if cat == "a")
    assert idx_b < idx_a


# ---------------------------------------------------------------------------
# Repo gap scoring tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_score_repo_for_gaps_high(primary_setup, tmp_path):
    """Repo matching sparse domain gets high score."""
    repo, engine, db_path = primary_setup

    for _ in range(5):
        await _seed(engine, ["category:security"], "python")

    sib_path = str(tmp_path / "go.db")
    await _create_sibling_db(sib_path, [])  # Empty Go brain

    instances_cfg = InstanceRegistryConfig(
        enabled=True,
        instance_name="general",
        siblings=[InstanceConfig(name="go", db_path=sib_path)],
    )
    analyzer = GapAnalyzer(repo, instances_cfg, db_path)
    matrix = await analyzer.compute_coverage_matrix()

    # Go repo with security focus matches the empty go/security cell
    score = analyzer.score_repo_for_gaps(
        "go-security-lib",
        {"language": "go", "categories": ["security"]},
        matrix,
    )
    assert score > 0

    # Python repo with security (already dense) gets lower score
    score_py = analyzer.score_repo_for_gaps(
        "py-security-lib",
        {"language": "python", "categories": ["security"]},
        matrix,
    )
    # The go repo should score at least as well (go/security is empty)
    assert score >= score_py


@pytest.mark.asyncio
async def test_score_repo_no_gaps(primary_setup):
    """All cells adequate → score is 0."""
    repo, engine, db_path = primary_setup

    for _ in range(5):
        await _seed(engine, ["category:security"], "python")

    instances_cfg = InstanceRegistryConfig(enabled=False, instance_name="general")
    gap_cfg = GapAnalyzerConfig(sparse_cell_threshold=3)
    analyzer = GapAnalyzer(repo, instances_cfg, db_path, gap_cfg)
    matrix = await analyzer.compute_coverage_matrix()

    score = analyzer.score_repo_for_gaps("any-repo", {"language": "python"}, matrix)
    assert score == 0.0


# ---------------------------------------------------------------------------
# Snapshot and trend tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_take_snapshot(primary_setup):
    """take_snapshot persists and returns matrix."""
    repo, engine, db_path = primary_setup

    await _seed(engine, ["category:security"], "python")

    instances_cfg = InstanceRegistryConfig(enabled=False, instance_name="general")
    analyzer = GapAnalyzer(repo, instances_cfg, db_path)

    matrix = await analyzer.take_snapshot()
    assert "security" in matrix.matrix

    # Verify persistence
    latest = await repo.get_latest_coverage_snapshot()
    assert latest is not None
    data = json.loads(latest["snapshot_data"])
    assert "security" in data


@pytest.mark.asyncio
async def test_trend_summary_no_snapshots(primary_setup):
    """Trend with no snapshots returns informative message."""
    repo, engine, db_path = primary_setup
    instances_cfg = InstanceRegistryConfig(enabled=False, instance_name="general")
    analyzer = GapAnalyzer(repo, instances_cfg, db_path)

    summary = await analyzer.get_trend_summary()
    assert "No coverage snapshots" in summary


@pytest.mark.asyncio
async def test_trend_summary_single_snapshot(primary_setup):
    """Trend with one snapshot returns basic info."""
    repo, engine, db_path = primary_setup

    await _seed(engine, ["category:security"], "python")

    instances_cfg = InstanceRegistryConfig(enabled=False, instance_name="general")
    analyzer = GapAnalyzer(repo, instances_cfg, db_path)

    await analyzer.take_snapshot()
    summary = await analyzer.get_trend_summary()
    assert "No prior snapshot for comparison" in summary


@pytest.mark.asyncio
async def test_trend_summary_two_snapshots(primary_setup):
    """Trend with two snapshots shows delta."""
    repo, engine, db_path = primary_setup

    await _seed(engine, ["category:security"], "python")
    instances_cfg = InstanceRegistryConfig(enabled=False, instance_name="general")
    analyzer = GapAnalyzer(repo, instances_cfg, db_path)

    await analyzer.take_snapshot()

    # Add more data
    await _seed(engine, ["category:testing"], "python")
    await analyzer.take_snapshot()

    summary = await analyzer.get_trend_summary()
    assert "Coverage trend" in summary
    assert "Total methodologies" in summary


# ---------------------------------------------------------------------------
# Determinism tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compute_matrix_deterministic(primary_setup):
    """Same data produces same matrix."""
    repo, engine, db_path = primary_setup

    await _seed(engine, ["category:security"], "python")
    await _seed(engine, ["category:testing"], "go")

    instances_cfg = InstanceRegistryConfig(enabled=False, instance_name="general")
    analyzer = GapAnalyzer(repo, instances_cfg, db_path)

    m1 = await analyzer.compute_coverage_matrix()
    m2 = await analyzer.compute_coverage_matrix()
    assert m1.matrix == m2.matrix
    assert m1.sparse_cells == m2.sparse_cells
    assert m1.empty_cells == m2.empty_cells


@pytest.mark.asyncio
async def test_sibling_missing_db(primary_setup, tmp_path):
    """Missing sibling DB is handled gracefully."""
    repo, engine, db_path = primary_setup

    await _seed(engine, ["category:security"], "python")

    instances_cfg = InstanceRegistryConfig(
        enabled=True,
        instance_name="general",
        siblings=[
            InstanceConfig(
                name="missing",
                db_path=str(tmp_path / "nonexistent.db"),
            ),
        ],
    )
    analyzer = GapAnalyzer(repo, instances_cfg, db_path)
    matrix = await analyzer.compute_coverage_matrix()

    # Should still work with just primary data
    assert "security" in matrix.matrix
    assert "missing" in matrix.total_by_brain  # Brain is known but has 0 counts
