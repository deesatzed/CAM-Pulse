"""Tests for community knowledge sharing infrastructure.

Validates:
- CommunityPacker: field stripping, hash computation, manifest, secret sanitization
- CommunityValidator: all 7 gates
- CommunityImporter: quarantine flow, dedup, approve/reject
- Fitness history logging
"""

from __future__ import annotations

import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import pytest

from claw.community.packer import (
    _sanitize_text,
    _strip_capability_data,
    compute_content_hash,
    pack_methodologies,
)
from claw.community.validator import (
    GateResult,
    ValidationResult,
    _gate_content_safety,
    _gate_field_allowlist,
    _gate_lifecycle_reset,
    _gate_manifest_hash,
    _gate_schema,
    validate_record,
)
from claw.community.importer import (
    _ensure_tables,
    approve_all,
    approve_one,
    import_records,
    list_quarantined,
    reject_one,
)
from claw.memory.fitness import log_fitness_change


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _make_record(
    record_id: str = "test-1",
    text: str = "A pattern for handling retries with exponential backoff",
    modality: str = "memory_methodology",
    extra_meta: dict | None = None,
    extra_community: dict | None = None,
) -> dict[str, Any]:
    """Create a valid community record for testing."""
    content_hash = compute_content_hash(record_id, text)
    cm = {
        "pack_format_version": "1.0",
        "instance_id": "a" * 64,
        "contributor_alias": "tester",
        "exported_at": "2026-03-26T00:00:00Z",
        "origin_lifecycle": "viable",
        "content_hash": content_hash,
        "source_repo_urls": ["test-repo"],
    }
    if extra_community:
        cm.update(extra_community)

    meta = {
        "language": "python",
        "scope": "global",
        "methodology_type": "PATTERN",
        "tags": ["retry", "resilience"],
        "success_count": 5,
        "retrieval_count": 10,
        "novelty_score": 0.8,
        "potential_score": 0.7,
        "created_at": "2026-03-20T00:00:00Z",
    }
    if extra_meta:
        meta.update(extra_meta)

    return {
        "id": record_id,
        "title": text[:80],
        "modality": modality,
        "text": text,
        "metadata": meta,
        "community_meta": cm,
    }


class FakeEngine:
    """Lightweight async DB engine for testing (uses real aiosqlite in-memory)."""

    def __init__(self):
        self._conn = None

    async def connect(self):
        import aiosqlite
        self._conn = await aiosqlite.connect(":memory:")
        self._conn.row_factory = aiosqlite.Row
        # Create minimal tables
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
            CREATE TABLE IF NOT EXISTS methodology_fitness_log (
                id TEXT PRIMARY KEY,
                methodology_id TEXT NOT NULL,
                fitness_total REAL NOT NULL,
                fitness_vector TEXT NOT NULL DEFAULT '{}',
                trigger_event TEXT NOT NULL DEFAULT 'recompute',
                created_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
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
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def fetch_one(self, query, params=None):
        cursor = await self._conn.execute(query, params or [])
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def close(self):
        if self._conn:
            await self._conn.close()


# ---------------------------------------------------------------------------
# Packer Tests
# ---------------------------------------------------------------------------

class TestContentHash:
    def test_deterministic(self):
        h1 = compute_content_hash("id-1", "text-1")
        h2 = compute_content_hash("id-1", "text-1")
        assert h1 == h2

    def test_different_inputs(self):
        h1 = compute_content_hash("id-1", "text-1")
        h2 = compute_content_hash("id-2", "text-1")
        assert h1 != h2

    def test_length_64(self):
        h = compute_content_hash("id", "text")
        assert len(h) == 64

    def test_hex_characters(self):
        h = compute_content_hash("id", "text")
        assert all(c in "0123456789abcdef" for c in h)


class TestSanitizeText:
    def test_strips_api_keys(self):
        text = "Use sk-abc1234567890123456789 for auth"
        result = _sanitize_text(text)
        assert "sk-abc" not in result
        assert "[REDACTED]" in result

    def test_strips_bearer_tokens(self):
        text = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.test_data_here"
        result = _sanitize_text(text)
        assert "eyJhbG" not in result

    def test_strips_env_vars(self):
        text = "Set OPENAI_API_KEY=sk-something-very-long-here to use"
        result = _sanitize_text(text)
        assert "sk-something" not in result

    def test_preserves_normal_text(self):
        text = "This is a normal description of a retry pattern"
        result = _sanitize_text(text)
        assert result == text


class TestStripCapabilityData:
    def test_strips_internal_keys(self):
        cap = {
            "domain": ["api_design"],
            "fitness_vector": {"total": 0.8},
            "prism_data": {"scales": []},
            "parent_ids": ["a", "b"],
            "superseded_by": "c",
            "source_task_id": "d",
            "composability": {"can_chain_after": []},
        }
        result = _strip_capability_data(cap)
        assert "domain" in result
        assert "composability" in result
        assert "fitness_vector" not in result
        assert "prism_data" not in result
        assert "parent_ids" not in result
        assert "superseded_by" not in result
        assert "source_task_id" not in result


class TestPackMethodologies:
    def test_pack_with_real_db(self):
        async def run():
            engine = FakeEngine()
            await engine.connect()
            # Insert a test methodology
            await engine.execute(
                """INSERT INTO methodologies
                   (id, problem_description, solution_code, tags, language,
                    scope, methodology_type, lifecycle_state, success_count,
                    capability_data, novelty_score, potential_score, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    "meth-1", "Retry with backoff", "def retry(): pass",
                    json.dumps(["source:test-repo", "retry"]),
                    "python", "global", "PATTERN", "viable", 3,
                    json.dumps({"domain": ["resilience"], "fitness_vector": {"total": 0.8}}),
                    0.85, 0.7, "2026-03-20T00:00:00Z",
                ],
            )
            state_path = Path("/tmp/cam_test_community_state.json")
            state_path.unlink(missing_ok=True)

            records, manifest = await pack_methodologies(
                engine, state_path, min_lifecycle="viable", max_count=10,
            )
            await engine.close()
            return records, manifest

        records, manifest = _run(run())
        assert len(records) == 1
        r = records[0]
        assert r["modality"] == "memory_methodology"
        assert "community_meta" in r
        assert r["community_meta"]["pack_format_version"] == "1.0"
        assert len(r["community_meta"]["instance_id"]) == 64
        assert len(r["community_meta"]["content_hash"]) == 64
        # fitness_vector should be stripped from capability_data
        cap = r["metadata"].get("capability_data", {})
        assert "fitness_vector" not in cap
        assert "domain" in cap
        # Manifest checks
        assert manifest["methodology_count"] == 1
        assert len(manifest["manifest_hash"]) == 64
        assert "python" in manifest["domains"]


# ---------------------------------------------------------------------------
# Validator Tests
# ---------------------------------------------------------------------------

class TestGateSchema:
    def test_valid_record(self):
        r = _make_record()
        g = _gate_schema(r)
        assert g.passed

    def test_missing_fields(self):
        g = _gate_schema({"id": "test"})
        assert not g.passed
        assert "Missing" in g.detail

    def test_invalid_modality(self):
        r = _make_record(modality="invalid_type")
        g = _gate_schema(r)
        assert not g.passed
        assert "modality" in g.detail.lower()

    def test_bad_format_version(self):
        r = _make_record(extra_community={"pack_format_version": "2.0"})
        g = _gate_schema(r)
        assert not g.passed

    def test_invalid_instance_id_length(self):
        r = _make_record(extra_community={"instance_id": "short"})
        g = _gate_schema(r)
        assert not g.passed

    def test_text_too_large(self):
        r = _make_record(text="x" * 33000)
        # Need to recompute hash for the large text
        r["community_meta"]["content_hash"] = compute_content_hash(r["id"], r["text"])
        g = _gate_schema(r)
        assert not g.passed
        assert "32KB" in g.detail


class TestGateFieldAllowlist:
    def test_strips_unknown_metadata_keys(self):
        r = _make_record(extra_meta={"secret_key": "value", "internal_id": 42})
        g, cleaned = _gate_field_allowlist(r)
        assert g.passed
        assert "secret_key" not in cleaned["metadata"]
        assert "internal_id" not in cleaned["metadata"]
        assert "language" in cleaned["metadata"]

    def test_sanitizes_secrets_in_text(self):
        r = _make_record(text="Use sk-test1234567890123456789 here")
        r["community_meta"]["content_hash"] = compute_content_hash(r["id"], r["text"])
        g, cleaned = _gate_field_allowlist(r)
        assert g.passed
        assert "sk-test" not in cleaned["text"]


class TestGateContentSafety:
    def test_safe_text(self):
        g = _gate_content_safety({"text": "Pattern for retry with exponential backoff"})
        assert g.passed

    def test_blocks_exec(self):
        g = _gate_content_safety({"text": "Use exec( code ) to run"})
        assert not g.passed
        assert "exec" in g.detail.lower()

    def test_blocks_eval(self):
        g = _gate_content_safety({"text": "Call eval(user_input)"})
        assert not g.passed

    def test_blocks_subprocess(self):
        g = _gate_content_safety({"text": "import subprocess for shell commands"})
        assert not g.passed

    def test_blocks_os_system(self):
        g = _gate_content_safety({"text": "os.system('rm -rf /')"})
        assert not g.passed

    def test_blocks_shell_pipe(self):
        g = _gate_content_safety({"text": "echo test | bash"})
        assert not g.passed

    def test_blocks_import_injection(self):
        g = _gate_content_safety({"text": "__import__('os')"})
        assert not g.passed


class TestGateManifestHash:
    def test_valid_hash(self):
        r = _make_record()
        g = _gate_manifest_hash(r)
        assert g.passed

    def test_tampered_text(self):
        r = _make_record()
        r["text"] = "TAMPERED TEXT"  # Hash won't match
        g = _gate_manifest_hash(r)
        assert not g.passed
        assert "mismatch" in g.detail.lower()

    def test_missing_hash(self):
        r = _make_record()
        r["community_meta"]["content_hash"] = ""
        g = _gate_manifest_hash(r)
        assert not g.passed


class TestGateLifecycleReset:
    def test_resets_to_embryonic(self):
        r = _make_record()
        g, cleaned = _gate_lifecycle_reset(r)
        overrides = cleaned["_import_overrides"]
        assert overrides["lifecycle_state"] == "embryonic"
        assert overrides["success_count"] == 0
        assert overrides["failure_count"] == 0
        assert overrides["retrieval_count"] == 0
        assert overrides["scope"] == "project"
        assert overrides["generation"] == 0


class TestFullValidation:
    def test_valid_record_passes_all_gates(self):
        async def run():
            engine = FakeEngine()
            await engine.connect()
            await _ensure_tables(engine)
            r = _make_record()
            result = await validate_record(r, engine)
            await engine.close()
            return result

        result = _run(run())
        assert result.passed
        assert len(result.gates) == 7
        assert result.sanitized_record is not None

    def test_schema_failure_short_circuits(self):
        async def run():
            engine = FakeEngine()
            await engine.connect()
            result = await validate_record({"bad": "record"}, engine)
            await engine.close()
            return result

        result = _run(run())
        assert not result.passed
        assert len(result.gates) == 1  # Only schema gate ran

    def test_content_safety_failure_short_circuits(self):
        async def run():
            engine = FakeEngine()
            await engine.connect()
            await _ensure_tables(engine)
            r = _make_record(text="Use eval(user_input) for flexibility")
            r["community_meta"]["content_hash"] = compute_content_hash(r["id"], r["text"])
            result = await validate_record(r, engine)
            await engine.close()
            return result

        result = _run(run())
        assert not result.passed


# ---------------------------------------------------------------------------
# Importer Tests
# ---------------------------------------------------------------------------

class TestImporter:
    def test_import_and_quarantine(self):
        async def run():
            engine = FakeEngine()
            await engine.connect()
            r = _make_record()
            summary = await import_records([r], engine)
            quarantined = await list_quarantined(engine)
            await engine.close()
            return summary, quarantined

        summary, quarantined = _run(run())
        assert summary["imported"] == 1
        assert summary["rejected"] == 0
        assert len(quarantined) == 1

    def test_dedup_rejects_duplicate(self):
        async def run():
            engine = FakeEngine()
            await engine.connect()
            r = _make_record()
            # Import once
            await import_records([r], engine)
            # Import same record again
            summary = await import_records([r], engine)
            await engine.close()
            return summary

        summary = _run(run())
        assert summary["rejected"] == 1  # Gate 5 dedup

    def test_cross_session_dedup(self):
        """Two records with same content_hash in one batch."""
        async def run():
            engine = FakeEngine()
            await engine.connect()
            r1 = _make_record(record_id="id-1")
            r2 = _make_record(record_id="id-1")  # Same ID = same hash
            summary = await import_records([r1, r2], engine)
            await engine.close()
            return summary

        summary = _run(run())
        assert summary["imported"] == 1
        assert summary["skipped"] == 1  # Session dedup

    def test_auto_approve(self):
        async def run():
            engine = FakeEngine()
            await engine.connect()
            r = _make_record()
            summary = await import_records([r], engine, auto_approve=True)
            # Check it went into methodologies
            rows = await engine.fetch_all("SELECT * FROM methodologies")
            await engine.close()
            return summary, rows

        summary, rows = _run(run())
        assert summary["imported"] == 1
        assert len(rows) == 1
        assert rows[0]["lifecycle_state"] == "embryonic"
        assert rows[0]["scope"] == "project"
        tags = json.loads(rows[0]["tags"])
        assert "imported" in tags

    def test_approve_from_quarantine(self):
        async def run():
            engine = FakeEngine()
            await engine.connect()
            r = _make_record()
            await import_records([r], engine)
            count = await approve_all(engine)
            rows = await engine.fetch_all("SELECT * FROM methodologies")
            await engine.close()
            return count, rows

        count, rows = _run(run())
        assert count == 1
        assert len(rows) == 1

    def test_reject_quarantined(self):
        async def run():
            engine = FakeEngine()
            await engine.connect()
            r = _make_record()
            await import_records([r], engine)
            quarantined = await list_quarantined(engine)
            qid = quarantined[0]["id"]
            result = await reject_one(engine, qid)
            remaining = await list_quarantined(engine)
            await engine.close()
            return result, remaining

        result, remaining = _run(run())
        assert result is True
        assert len(remaining) == 0

    def test_approve_one(self):
        async def run():
            engine = FakeEngine()
            await engine.connect()
            r = _make_record()
            await import_records([r], engine)
            quarantined = await list_quarantined(engine)
            qid = quarantined[0]["id"]
            result = await approve_one(engine, qid)
            rows = await engine.fetch_all("SELECT * FROM methodologies")
            await engine.close()
            return result, rows

        result, rows = _run(run())
        assert result is True
        assert len(rows) == 1

    def test_content_safety_rejects(self):
        async def run():
            engine = FakeEngine()
            await engine.connect()
            r = _make_record(text="Use eval(input) to process")
            r["community_meta"]["content_hash"] = compute_content_hash(r["id"], r["text"])
            summary = await import_records([r], engine)
            await engine.close()
            return summary

        summary = _run(run())
        assert summary["rejected"] == 1

    def test_max_records_limit(self):
        async def run():
            engine = FakeEngine()
            await engine.connect()
            records = [_make_record(record_id=f"id-{i}", text=f"Pattern {i} for testing") for i in range(10)]
            for r in records:
                r["community_meta"]["content_hash"] = compute_content_hash(r["id"], r["text"])
            summary = await import_records(records, engine, max_records=3)
            await engine.close()
            return summary

        summary = _run(run())
        assert summary["imported"] == 3


# ---------------------------------------------------------------------------
# Fitness History Tests
# ---------------------------------------------------------------------------

class TestFitnessHistory:
    def test_log_fitness_change(self):
        async def run():
            engine = FakeEngine()
            await engine.connect()
            await log_fitness_change(
                engine, "meth-1", 0.75,
                {"total": 0.75, "efficacy": 0.9},
                trigger_event="outcome_success",
            )
            rows = await engine.fetch_all("SELECT * FROM methodology_fitness_log")
            await engine.close()
            return rows

        rows = _run(run())
        assert len(rows) == 1
        assert rows[0]["methodology_id"] == "meth-1"
        assert rows[0]["fitness_total"] == 0.75
        assert rows[0]["trigger_event"] == "outcome_success"
        vector = json.loads(rows[0]["fitness_vector"])
        assert vector["total"] == 0.75

    def test_multiple_entries(self):
        async def run():
            engine = FakeEngine()
            await engine.connect()
            await log_fitness_change(engine, "meth-1", 0.5, {"total": 0.5}, "outcome_failure")
            await log_fitness_change(engine, "meth-1", 0.6, {"total": 0.6}, "outcome_success")
            await log_fitness_change(engine, "meth-1", 0.7, {"total": 0.7}, "outcome_success")
            rows = await engine.fetch_all(
                "SELECT * FROM methodology_fitness_log WHERE methodology_id = ? ORDER BY created_at",
                ["meth-1"],
            )
            await engine.close()
            return rows

        rows = _run(run())
        assert len(rows) == 3
        assert rows[0]["fitness_total"] == 0.5
        assert rows[2]["fitness_total"] == 0.7

    def test_graceful_failure(self):
        """log_fitness_change should not raise even if table doesn't exist."""
        async def run():
            import aiosqlite

            class BareEngine:
                async def execute(self, query, params=None):
                    raise Exception("Table does not exist")

            engine = BareEngine()
            # Should not raise
            await log_fitness_change(engine, "meth-1", 0.5, {"total": 0.5})

        _run(run())  # No assertion needed — just verify no exception
