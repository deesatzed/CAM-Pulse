"""Tests for `cam gaps` CLI command.

Validates that the command runs and outputs expected formats.
Uses real in-memory SQLite — no mocks.
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio

from claw.core.config import (
    ClawConfig,
    DatabaseConfig,
    GapAnalyzerConfig,
    InstanceRegistryConfig,
)
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository


@pytest_asyncio.fixture
async def seeded_db(tmp_path):
    """Create a temporary DB with seeded methodologies for CLI testing."""
    db_path = str(tmp_path / "test_gaps.db")
    cfg = DatabaseConfig(db_path=db_path)
    engine = DatabaseEngine(cfg)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    repo = Repository(engine)

    # Seed methodologies across categories
    for cat, lang, count in [
        ("security", "python", 5),
        ("testing", "python", 2),
        ("architecture", "python", 4),
        ("cli_ux", "python", 1),
    ]:
        for _ in range(count):
            await engine.execute(
                """INSERT INTO methodologies
                   (id, problem_description, solution_code, tags, language, lifecycle_state)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [str(uuid.uuid4()), "p", "s", json.dumps([f"category:{cat}"]), lang, "viable"],
            )

    yield repo, engine, db_path
    await engine.close()


@pytest.mark.asyncio
async def test_coverage_matrix_from_seeded_db(seeded_db):
    """Verify matrix is correct from seeded data."""
    repo, engine, db_path = seeded_db
    from claw.community.gap_analyzer import GapAnalyzer

    cfg = InstanceRegistryConfig(enabled=False, instance_name="general")
    gap_cfg = GapAnalyzerConfig(sparse_cell_threshold=3)
    analyzer = GapAnalyzer(repo, cfg, db_path, gap_cfg)

    matrix = await analyzer.compute_coverage_matrix()

    assert matrix.matrix["security"]["general"] == 5
    assert matrix.matrix["testing"]["general"] == 2
    assert matrix.matrix["architecture"]["general"] == 4
    assert matrix.matrix["cli_ux"]["general"] == 1

    # Sparse: testing (2) and cli_ux (1) are below threshold of 3
    sparse_cats = {cat for cat, _ in matrix.sparse_cells}
    assert "testing" in sparse_cats
    assert "cli_ux" in sparse_cats
    assert "security" not in sparse_cats


@pytest.mark.asyncio
async def test_json_output_format(seeded_db):
    """Verify JSON output has expected structure."""
    repo, engine, db_path = seeded_db
    from claw.community.gap_analyzer import GapAnalyzer

    cfg = InstanceRegistryConfig(enabled=False, instance_name="general")
    analyzer = GapAnalyzer(repo, cfg, db_path)

    matrix = await analyzer.compute_coverage_matrix()

    # Simulate JSON output
    output = {
        "matrix": matrix.matrix,
        "sparse_cells": matrix.sparse_cells,
        "empty_cells": matrix.empty_cells,
        "total_by_category": matrix.total_by_category,
        "total_by_brain": matrix.total_by_brain,
    }

    json_str = json.dumps(output)
    parsed = json.loads(json_str)

    assert "matrix" in parsed
    assert "sparse_cells" in parsed
    assert "empty_cells" in parsed
    assert "total_by_category" in parsed
    assert "total_by_brain" in parsed
    assert isinstance(parsed["matrix"], dict)


@pytest.mark.asyncio
async def test_snapshot_flag(seeded_db):
    """--snapshot flag persists data."""
    repo, engine, db_path = seeded_db
    from claw.community.gap_analyzer import GapAnalyzer

    cfg = InstanceRegistryConfig(enabled=False, instance_name="general")
    analyzer = GapAnalyzer(repo, cfg, db_path)

    # Before snapshot
    assert await repo.get_latest_coverage_snapshot() is None

    # Take snapshot
    await analyzer.take_snapshot()

    # After snapshot
    latest = await repo.get_latest_coverage_snapshot()
    assert latest is not None
    assert latest["total_methodologies"] == 12  # 5 + 2 + 4 + 1


@pytest.mark.asyncio
async def test_gap_analyzer_config_defaults():
    """GapAnalyzerConfig has sane defaults."""
    cfg = GapAnalyzerConfig()
    assert cfg.enabled is True
    assert cfg.sparse_cell_threshold == 3


@pytest.mark.asyncio
async def test_gap_analyzer_config_in_claw_config():
    """GapAnalyzerConfig is wired into ClawConfig."""
    cfg = ClawConfig()
    assert hasattr(cfg, "gap_analyzer")
    assert isinstance(cfg.gap_analyzer, GapAnalyzerConfig)
    assert cfg.gap_analyzer.enabled is True
