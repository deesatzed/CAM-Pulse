"""Tests for the seed knowledge loader."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claw.community.seeder import (
    SEED_TAG,
    _compute_content_hash,
    _seed_record,
    discover_seed_packs,
    load_seed_records,
    needs_seeding,
    run_seed,
)


# --- Fixtures ---

def _make_seed_record(
    text: str = "Problem statement\n\nSolution code\n\nNotes",
    tags: list[str] | None = None,
    record_id: str = "test-record-001",
) -> dict[str, Any]:
    """Build a minimal seed-format record."""
    return {
        "id": record_id,
        "title": text[:40],
        "modality": "memory_methodology",
        "text": text,
        "metadata": {
            "language": "python",
            "scope": "global",
            "methodology_type": "PATTERN",
            "tags": tags or ["testing"],
            "success_count": 0,
            "retrieval_count": 0,
            "novelty_score": 0.5,
            "potential_score": 0.5,
            "capability_data": {},
        },
        "community_meta": {
            "pack_format_version": "1.0",
            "instance_id": "a" * 64,
            "contributor_alias": "cam-seed",
            "exported_at": "2026-03-31T00:00:00Z",
            "origin_lifecycle": "viable",
            "content_hash": "",
        },
    }


class FakeEngine:
    """Minimal async engine for testing seeder without real SQLite."""

    def __init__(self) -> None:
        self._rows: dict[str, list[dict]] = {
            "methodologies": [],
            "methodology_fts": [],
            "methodology_embeddings": [],
            "community_imports": [],
        }
        self.conn = self  # _ensure_community_tables uses engine.conn.execute

    async def execute(self, sql: str, params: list | None = None) -> None:
        sql_lower = sql.strip().lower()
        if sql_lower.startswith("insert into methodologies"):
            self._rows["methodologies"].append({"sql": sql, "params": params})
        elif sql_lower.startswith("insert into methodology_fts"):
            self._rows["methodology_fts"].append({"sql": sql, "params": params})
        elif sql_lower.startswith("insert into methodology_embeddings"):
            self._rows["methodology_embeddings"].append({"sql": sql, "params": params})
        elif "community_imports" in sql_lower and "insert" in sql_lower:
            self._rows["community_imports"].append({"sql": sql, "params": params})
        elif sql_lower.startswith("create table"):
            pass  # Schema creation — ignore
        else:
            pass  # Other queries

    async def fetch_one(self, sql: str, params: list | None = None) -> dict | None:
        sql_lower = sql.strip().lower()
        if "count(*)" in sql_lower and "methodologies" in sql_lower:
            if "origin:seed" in str(params):
                seed_count = sum(
                    1 for r in self._rows["methodologies"]
                    if r.get("params") and '"origin:seed"' in str(r["params"])
                )
                return {"cnt": seed_count}
            return {"cnt": len(self._rows["methodologies"])}
        if "community_imports" in sql_lower and "content_hash" in sql_lower:
            if params:
                for r in self._rows["community_imports"]:
                    if r.get("params") and params[0] in str(r["params"]):
                        return {"id": "exists"}
            return None
        return None

    async def fetch_all(self, sql: str, params: list | None = None) -> list:
        return []

    async def commit(self) -> None:
        pass

    async def close(self) -> None:
        pass


# --- Tests ---


def test_discover_seed_packs_finds_real_packs():
    """The actual src/claw/data/seed/ should have at least one pack."""
    packs = discover_seed_packs()
    assert len(packs) >= 1
    assert all(p.suffix == ".jsonl" for p in packs)


def test_discover_seed_packs_empty_dir():
    """An empty directory should return no packs."""
    with tempfile.TemporaryDirectory() as td:
        with patch("claw.community.seeder.SEED_DIR", Path(td)):
            packs = discover_seed_packs()
            assert packs == []


def test_load_seed_records_parses_jsonl():
    """Records should be parsed and tagged with origin:seed."""
    with tempfile.TemporaryDirectory() as td:
        pack_path = Path(td) / "test.jsonl"
        record = _make_seed_record()
        pack_path.write_text(json.dumps(record) + "\n")

        records = load_seed_records([pack_path])
        assert len(records) == 1
        assert SEED_TAG in records[0]["metadata"]["tags"]


def test_load_seed_records_skips_bad_lines():
    """Malformed JSON lines should be skipped, not crash."""
    with tempfile.TemporaryDirectory() as td:
        pack_path = Path(td) / "test.jsonl"
        record = _make_seed_record()
        pack_path.write_text(
            json.dumps(record) + "\n"
            + "this is not json\n"
            + json.dumps(_make_seed_record(record_id="rec-2")) + "\n"
        )

        records = load_seed_records([pack_path])
        assert len(records) == 2  # bad line skipped


def test_load_seed_records_from_real_pack():
    """Load records from the actual shipped seed pack."""
    packs = discover_seed_packs()
    if not packs:
        pytest.skip("No seed packs available")
    records = load_seed_records(packs)
    assert len(records) > 0
    for r in records:
        assert SEED_TAG in r["metadata"]["tags"]
        assert r.get("text")  # all records have text


def test_compute_content_hash_deterministic():
    """Same record should produce the same hash."""
    r = _make_seed_record()
    h1 = _compute_content_hash(r)
    h2 = _compute_content_hash(r)
    assert h1 == h2
    assert len(h1) == 64  # SHA-256 hex


def test_compute_content_hash_differs_for_different_records():
    r1 = _make_seed_record(text="Problem A\n\nSolution A")
    r2 = _make_seed_record(text="Problem B\n\nSolution B")
    assert _compute_content_hash(r1) != _compute_content_hash(r2)


@pytest.mark.asyncio
async def test_needs_seeding_empty_db():
    engine = FakeEngine()
    assert await needs_seeding(engine) is True


@pytest.mark.asyncio
async def test_needs_seeding_force():
    engine = FakeEngine()
    # Even with records, force=True returns True
    engine._rows["methodologies"].append({"params": ['"origin:seed"']})
    assert await needs_seeding(engine, force=True) is True


@pytest.mark.asyncio
async def test_needs_seeding_with_seeds_returns_false():
    """If seed records exist, no seeding needed."""
    engine = FakeEngine()
    # Simulate existing seed record
    engine._rows["methodologies"].append({"params": ['["origin:seed"]']})
    assert await needs_seeding(engine) is False


@pytest.mark.asyncio
async def test_seed_record_writes_three_tables():
    """_seed_record should write to methodologies, FTS5, and community_imports."""
    engine = FakeEngine()
    record = _make_seed_record()
    record["community_meta"]["content_hash"] = _compute_content_hash(record)

    new_id = await _seed_record(record, engine, embedding_engine=None)

    assert new_id is not None
    assert len(engine._rows["methodologies"]) == 1
    assert len(engine._rows["methodology_fts"]) == 1
    assert len(engine._rows["community_imports"]) == 1
    # No embedding without engine
    assert len(engine._rows["methodology_embeddings"]) == 0


@pytest.mark.asyncio
async def test_seed_record_idempotent():
    """Second call with same content_hash should be skipped."""
    engine = FakeEngine()
    record = _make_seed_record()
    record["community_meta"]["content_hash"] = _compute_content_hash(record)

    id1 = await _seed_record(record, engine)
    assert id1 is not None

    # Simulate the hash being in community_imports
    # The first call added it, so the FakeEngine should have it
    id2 = await _seed_record(record, engine)
    assert id2 is None  # Skipped due to dedup


@pytest.mark.asyncio
async def test_seed_record_sets_viable_lifecycle():
    """Seed records should start with lifecycle_state='viable'."""
    engine = FakeEngine()
    record = _make_seed_record()
    record["community_meta"]["content_hash"] = _compute_content_hash(record)

    await _seed_record(record, engine)

    params = engine._rows["methodologies"][0]["params"]
    # lifecycle_state is at index 9 in the INSERT params
    assert params[9] == "viable"


@pytest.mark.asyncio
async def test_seed_record_sets_global_scope():
    """Seed records should have scope='global'."""
    engine = FakeEngine()
    record = _make_seed_record()
    record["community_meta"]["content_hash"] = _compute_content_hash(record)

    await _seed_record(record, engine)

    params = engine._rows["methodologies"][0]["params"]
    # scope is at index 6 in the INSERT params
    assert params[6] == "global"


@pytest.mark.asyncio
async def test_run_seed_no_packs():
    """run_seed with no packs should return reason='no_seed_packs'."""
    engine = FakeEngine()
    with patch("claw.community.seeder.SEED_DIR", Path("/nonexistent")):
        result = await run_seed(engine)
    assert result["reason"] == "no_seed_packs"
    assert result["imported"] == 0


@pytest.mark.asyncio
async def test_run_seed_already_seeded():
    """run_seed should skip if seeds already exist."""
    engine = FakeEngine()
    engine._rows["methodologies"].append({"params": ['["origin:seed"]']})

    result = await run_seed(engine)
    assert result["reason"] == "already_seeded"
    assert result["imported"] == 0


def test_lifecycle_seed_protection():
    """Seed-tagged methodologies should not decay below viable."""
    from claw.core.models import Methodology
    from claw.memory.lifecycle import evaluate_transition

    m = Methodology(
        problem_description="test",
        solution_code="test",
        tags=["origin:seed"],
        lifecycle_state="viable",
        success_count=0,
        failure_count=5,  # Would normally trigger decline
        retrieval_count=10,
    )
    # Should NOT transition to declining despite failure_count > success_count
    new_state = evaluate_transition(m)
    assert new_state is None


def test_lifecycle_seed_rehabilitates_from_declining():
    """Seed methodology in declining state should be rehabilitated to viable."""
    from claw.core.models import Methodology
    from claw.memory.lifecycle import evaluate_transition

    m = Methodology(
        problem_description="test",
        solution_code="test",
        tags=["origin:seed"],
        lifecycle_state="declining",
    )
    new_state = evaluate_transition(m)
    assert new_state == "viable"


def test_lifecycle_seed_can_promote_to_thriving():
    """Seed methodology with high fitness can still be promoted."""
    from claw.core.models import Methodology
    from claw.memory.lifecycle import evaluate_transition

    m = Methodology(
        problem_description="test",
        solution_code="test",
        tags=["origin:seed"],
        lifecycle_state="viable",
        success_count=5,
        failure_count=0,
        retrieval_count=10,
        fitness_vector={"total": 0.85, "outcome_ema": 0.85},
    )
    new_state = evaluate_transition(m)
    assert new_state == "thriving"


def test_lifecycle_non_seed_still_decays():
    """Non-seed methodologies should still decay normally."""
    from claw.core.models import Methodology
    from claw.memory.lifecycle import evaluate_transition

    m = Methodology(
        problem_description="test",
        solution_code="test",
        tags=["testing"],  # No origin:seed
        lifecycle_state="viable",
        success_count=0,
        failure_count=5,
        retrieval_count=10,
    )
    new_state = evaluate_transition(m)
    assert new_state == "declining"
