"""Tests for named-pack selection in ``claw.community.seeder``.

Complements ``tests/test_seeder.py`` (which covers the older discovery /
load / insert happy paths) by exercising the new ``names`` filter on
:func:`discover_seed_packs`, the :func:`list_available_packs` helper,
and the ``cam kb seed --list-packs`` CLI short-circuit.

The CLI test uses ``unittest.mock`` to prove that ``--list-packs`` never
reaches the database engine — no mocks leak into production code.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from claw.community.seeder import (
    DEFAULT_SEED_PACK,
    discover_seed_packs,
    list_available_packs,
    run_seed,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_fake_pack(directory: Path, stem: str, n_records: int = 2) -> Path:
    """Write a minimal but valid JSONL pack into ``directory``."""
    path = directory / f"{stem}.jsonl"
    lines = []
    for i in range(n_records):
        rec = {
            "id": f"{stem}-{i:03d}",
            "title": f"{stem} rec {i}",
            "modality": "memory_methodology",
            "text": f"Problem {i}\n\nSolution {i}\n\nNotes {i}",
            "metadata": {
                "language": "python",
                "scope": "global",
                "methodology_type": "PATTERN",
                "tags": ["testing"],
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
                "exported_at": "2026-04-10T00:00:00Z",
                "origin_lifecycle": "viable",
                "content_hash": "",
            },
        }
        lines.append(json.dumps(rec))
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.fixture
def fake_seed_dir():
    """Temporary SEED_DIR with three fake packs: core_v1, extras_v1, misc_v1."""
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        _write_fake_pack(tdp, "core_v1", n_records=3)
        _write_fake_pack(tdp, "extras_v1", n_records=2)
        _write_fake_pack(tdp, "misc_v1", n_records=1)
        with patch("claw.community.seeder.SEED_DIR", tdp):
            yield tdp


# ---------------------------------------------------------------------------
# discover_seed_packs — named filter
# ---------------------------------------------------------------------------


def test_discover_seed_packs_with_single_name_returns_one(fake_seed_dir):
    """Filtering by a known stem returns exactly that pack."""
    packs = discover_seed_packs(names=["core_v1"])
    assert len(packs) == 1
    assert packs[0].stem == "core_v1"
    assert packs[0].suffix == ".jsonl"


def test_discover_seed_packs_with_bogus_name_returns_empty(fake_seed_dir):
    """An unknown name filters everything out rather than raising."""
    packs = discover_seed_packs(names=["does_not_exist"])
    assert packs == []


def test_discover_seed_packs_with_multiple_names(fake_seed_dir):
    """Multiple names return only the matches, in filename order."""
    packs = discover_seed_packs(names=["core_v1", "misc_v1", "ghost"])
    stems = [p.stem for p in packs]
    assert stems == ["core_v1", "misc_v1"]  # sorted, ghost dropped


def test_discover_seed_packs_names_none_returns_all(fake_seed_dir):
    """names=None preserves the legacy "all packs" behaviour."""
    packs = discover_seed_packs(names=None)
    assert [p.stem for p in packs] == ["core_v1", "extras_v1", "misc_v1"]


def test_discover_seed_packs_default_pack_is_discoverable():
    """The shipped core_v1 pack must exist and match DEFAULT_SEED_PACK."""
    packs = discover_seed_packs(names=[DEFAULT_SEED_PACK])
    assert len(packs) == 1
    assert packs[0].stem == DEFAULT_SEED_PACK


# ---------------------------------------------------------------------------
# list_available_packs
# ---------------------------------------------------------------------------


def test_list_available_packs_includes_record_counts(fake_seed_dir):
    entries = list_available_packs()
    by_name = {e["name"]: e for e in entries}
    assert by_name["core_v1"]["records"] == 3
    assert by_name["extras_v1"]["records"] == 2
    assert by_name["misc_v1"]["records"] == 1
    for e in entries:
        assert Path(e["path"]).exists()


# ---------------------------------------------------------------------------
# run_seed propagates names filter
# ---------------------------------------------------------------------------


class _FakeEngine:
    """Minimal async engine stub — records calls, never hits SQLite.

    Only implements the subset of methods run_seed / _seed_record touch.
    """

    def __init__(self) -> None:
        self.methodologies: list[list] = []
        self.fts: list[list] = []
        self.embeddings: list[list] = []
        self.community_imports: list[list] = []
        self.conn = self  # _ensure_community_tables uses engine.conn.execute

    async def execute(self, sql: str, params: list | None = None) -> None:
        s = sql.strip().lower()
        if s.startswith("insert into methodologies"):
            self.methodologies.append(params or [])
        elif s.startswith("insert into methodology_fts"):
            self.fts.append(params or [])
        elif s.startswith("insert into methodology_embeddings"):
            self.embeddings.append(params or [])
        elif "community_imports" in s and "insert" in s:
            self.community_imports.append(params or [])
        # CREATE TABLE and other statements intentionally ignored

    async def fetch_one(self, sql: str, params: list | None = None) -> dict | None:
        s = sql.strip().lower()
        if "count(*)" in s and "methodologies" in s:
            # needs_seeding() logic: total count, then origin:seed count
            if "like" in s:
                return {"cnt": 0}  # no seeded rows yet
            return {"cnt": 0}
        if "community_imports" in s and "content_hash" in s:
            return None
        return None

    async def fetch_all(self, sql: str, params: list | None = None) -> list:
        return []

    async def commit(self) -> None:
        pass

    async def close(self) -> None:
        pass


@pytest.mark.asyncio
async def test_run_seed_with_names_only_loads_selected(fake_seed_dir):
    """run_seed(names=[...]) must only ingest records from matching packs."""
    engine = _FakeEngine()

    # Patch cag_staleness to a no-op so we don't need a real config
    with patch("claw.memory.cag_staleness.maybe_mark_cag_stale"):
        result = await run_seed(engine=engine, names=["core_v1"])

    assert result["reason"] == "seeded"
    assert result["imported"] == 3  # core_v1 has 3 fake records
    assert len(engine.methodologies) == 3


@pytest.mark.asyncio
async def test_run_seed_with_bogus_name_returns_no_packs(fake_seed_dir):
    engine = _FakeEngine()
    result = await run_seed(engine=engine, names=["does_not_exist"])
    assert result["reason"] == "no_seed_packs"
    assert result["imported"] == 0
    assert engine.methodologies == []


@pytest.mark.asyncio
async def test_run_seed_respects_cam_skip_auto_seed_env(fake_seed_dir, monkeypatch):
    """CAM_SKIP_AUTO_SEED=1 short-circuits run_seed without any DB work.

    The validation gate sets this env var before invoking `cam status` in a
    subprocess to avoid a 38s Gemini embedding run on an empty copy-dir DB
    (see T7 investigation 2026-04-10). This test locks in that contract.
    """
    monkeypatch.setenv("CAM_SKIP_AUTO_SEED", "1")
    engine = _FakeEngine()

    result = await run_seed(engine=engine, names=["core_v1"])

    assert result["reason"] == "skipped_env"
    assert result["imported"] == 0
    # Critical: the engine must be completely untouched — no tables created,
    # no inserts, no fetches. The short-circuit happens before any I/O.
    assert engine.methodologies == []


@pytest.mark.asyncio
async def test_run_seed_skips_only_when_env_is_exactly_one(fake_seed_dir, monkeypatch):
    """CAM_SKIP_AUTO_SEED=0 or any other value does NOT skip seeding."""
    monkeypatch.setenv("CAM_SKIP_AUTO_SEED", "0")
    engine = _FakeEngine()

    with patch("claw.memory.cag_staleness.maybe_mark_cag_stale"):
        result = await run_seed(engine=engine, names=["core_v1"])

    # "0" is not the opt-out value; seeding proceeds normally.
    assert result["reason"] == "seeded"
    assert result["imported"] == 3


# ---------------------------------------------------------------------------
# CLI --list-packs must not touch the DB
# ---------------------------------------------------------------------------


def test_cli_list_packs_does_not_touch_db(fake_seed_dir):
    """``cam kb seed --list-packs`` is a DB-free short-circuit.

    We patch ``_kb_engine`` (which would create a real ``DatabaseEngine``)
    with an AsyncMock and assert it was never awaited. This also proves
    that the short-circuit happens before any engine setup.
    """
    from claw.cli._monolith import app

    runner = CliRunner()
    kb_engine_mock = AsyncMock()
    # The engine factory would return (engine, repo). If it ever runs,
    # downstream await engine.close() would kick in too — so fail fast.
    kb_engine_mock.return_value = (MagicMock(), MagicMock())

    with patch("claw.cli._monolith._kb_engine", kb_engine_mock):
        result = runner.invoke(app, ["kb", "seed", "--list-packs"])

    assert result.exit_code == 0, result.output
    # The fake SEED_DIR has core_v1, extras_v1, misc_v1
    assert "core_v1" in result.output
    assert "extras_v1" in result.output
    assert "misc_v1" in result.output
    assert "Available seed packs" in result.output
    # Critical: _kb_engine must NEVER be invoked for --list-packs
    kb_engine_mock.assert_not_called()


# ---------------------------------------------------------------------------
# DOMAIN_PACKS / kb bootstrap CLI
# ---------------------------------------------------------------------------


def test_kb_bootstrap_domain_packs_mapping_is_sane():
    """The shipped DOMAIN_PACKS must cover every documented domain and
    always include ``core_v1`` as the foundational pack.
    """
    from claw.community.seeder import DEFAULT_DOMAIN, DOMAIN_PACKS

    assert DEFAULT_DOMAIN == "python"
    assert DEFAULT_DOMAIN in DOMAIN_PACKS
    for domain in ("python", "devsecops", "webdev", "all"):
        assert domain in DOMAIN_PACKS, f"missing domain: {domain}"
        assert "core_v1" in DOMAIN_PACKS[domain], (
            f"domain {domain!r} must always include core_v1 as foundation"
        )


def test_kb_bootstrap_resolves_python_to_correct_packs():
    """python domain resolves to core_v1 + starter_python_v1 (and not polyglot)."""
    from claw.community.seeder import DOMAIN_PACKS

    packs = DOMAIN_PACKS["python"]
    assert packs == ["core_v1", "starter_python_v1"]
    # Defensive: the old "polyglot" name must not leak back in.
    assert not any("polyglot" in p for p in packs)


def test_kb_bootstrap_webdev_supplements_with_python():
    """webdev is small and must be supplemented with the Python starter."""
    from claw.community.seeder import DOMAIN_PACKS

    packs = DOMAIN_PACKS["webdev"]
    assert "starter_webdev_v1" in packs
    assert "starter_python_v1" in packs
    assert "core_v1" in packs


def test_kb_bootstrap_invalid_domain_exits_2():
    """``cam kb bootstrap --domain bogus`` must exit 2 with a clear message."""
    from claw.cli._monolith import app

    runner = CliRunner()
    # The validation happens before _kb_engine is touched, so we can
    # assert exit_code without patching anything DB-related.
    result = runner.invoke(app, ["kb", "bootstrap", "--domain", "bogus"])

    assert result.exit_code == 2, result.output
    assert "Unknown domain" in result.output
    assert "bogus" in result.output
    # Available domains should be listed so the user can recover.
    assert "python" in result.output
    assert "devsecops" in result.output
    assert "webdev" in result.output


def test_kb_bootstrap_missing_pack_fails_cleanly():
    """If the required packs aren't on disk, exit 1 with a helpful error.

    Mocks ``list_available_packs`` to return an empty list so the domain's
    required packs can never be found. This proves the guard triggers before
    the DB engine is touched.
    """
    from claw.cli._monolith import app

    runner = CliRunner()
    kb_engine_mock = AsyncMock()
    kb_engine_mock.return_value = (MagicMock(), MagicMock())

    with patch(
        "claw.community.seeder.list_available_packs",
        return_value=[],  # No packs on disk
    ):
        with patch("claw.cli._monolith._kb_engine", kb_engine_mock):
            result = runner.invoke(app, ["kb", "bootstrap", "--domain", "python"])

    assert result.exit_code == 1, result.output
    assert "Missing seed pack" in result.output or "No seed packs" in result.output
    # Engine must NOT have been created - the missing-pack guard fires first.
    kb_engine_mock.assert_not_called()


def test_kb_bootstrap_missing_pack_lists_available_on_disk():
    """When only some packs are missing, the error lists what IS available."""
    from claw.cli._monolith import app

    runner = CliRunner()
    kb_engine_mock = AsyncMock()
    kb_engine_mock.return_value = (MagicMock(), MagicMock())

    # Only core_v1 present - python domain also needs starter_python_v1.
    partial = [{"name": "core_v1", "path": "/fake/core_v1.jsonl", "records": 3}]
    with patch(
        "claw.community.seeder.list_available_packs",
        return_value=partial,
    ):
        with patch("claw.cli._monolith._kb_engine", kb_engine_mock):
            result = runner.invoke(app, ["kb", "bootstrap", "--domain", "python"])

    assert result.exit_code == 1, result.output
    assert "starter_python_v1" in result.output  # reported as missing
    assert "core_v1" in result.output  # reported as available
    kb_engine_mock.assert_not_called()


def test_kb_bootstrap_idempotent_already_seeded():
    """Second invocation without --force prints 'already bootstrapped' and
    does NOT re-import records.

    We wire up:
      - list_available_packs → reports the packs we need as present
      - _kb_engine → returns a fake engine whose needs_seeding() path
        resolves to False (total methodologies > 0, and at least one
        origin:seed row exists), so run_seed returns reason=already_seeded
      - run_seed must still be called once (we delegate), but report 0 imports
    """
    from claw.cli._monolith import app

    runner = CliRunner()

    # Build an engine whose needs_seeding() is False.
    class _AlreadySeededEngine:
        closed = False

        async def fetch_one(self, sql, params=None):
            s = sql.strip().lower()
            if "count(*)" in s and "methodologies" in s:
                # First call: total count > 0. Second call (LIKE origin:seed): > 0.
                return {"cnt": 5}
            if "community_imports" in s and "content_hash" in s:
                return None
            return None

        async def fetch_all(self, sql, params=None):
            # For the category-breakdown query after short-circuit.
            return []

        async def execute(self, *a, **kw):
            pass

        async def close(self):
            self.closed = True

    fake_engine = _AlreadySeededEngine()

    async def _fake_kb_engine():
        return (fake_engine, MagicMock())

    # Pretend every required pack exists on disk so validation passes.
    on_disk = [
        {"name": "core_v1", "path": "/fake/core_v1.jsonl", "records": 31},
        {"name": "starter_python_v1", "path": "/fake/starter_python_v1.jsonl", "records": 51},
    ]

    with patch("claw.community.seeder.list_available_packs", return_value=on_disk):
        with patch("claw.cli._monolith._kb_engine", _fake_kb_engine):
            # EmbeddingEngine is optional - force it to fail so we skip it.
            with patch(
                "claw.db.embeddings.EmbeddingEngine",
                side_effect=RuntimeError("no embeddings in tests"),
            ):
                result = runner.invoke(
                    app, ["kb", "bootstrap", "--domain", "python"]
                )

    assert result.exit_code == 0, result.output
    assert "Already bootstrapped" in result.output
    assert "--force" in result.output  # tells user how to re-seed
    assert fake_engine.closed, "engine should be closed in the finally block"


def test_kb_bootstrap_default_domain_is_python():
    """Running ``cam kb bootstrap`` with no args must resolve to 'python'.

    We don't actually seed - we just trip the missing-pack guard by
    mocking list_available_packs to [] and check the error message
    names the python packs (proving python was the default).
    """
    from claw.cli._monolith import app

    runner = CliRunner()
    kb_engine_mock = AsyncMock()
    kb_engine_mock.return_value = (MagicMock(), MagicMock())

    with patch("claw.community.seeder.list_available_packs", return_value=[]):
        with patch("claw.cli._monolith._kb_engine", kb_engine_mock):
            result = runner.invoke(app, ["kb", "bootstrap"])

    assert result.exit_code == 1, result.output
    assert "python" in result.output  # error references the python domain
    assert "starter_python_v1" in result.output


# ---------------------------------------------------------------------------
# cam init — top-level first-run wizard
# ---------------------------------------------------------------------------
#
# These tests exercise the full Typer entry point using a real temporary
# SQLite DB plus a real claw.toml written by the test. We patch:
#   - EmbeddingEngine: tests run offline, so vectors are unavailable
#   - claw.community.seeder.run_seed: only when we want to assert the
#     pack list without paying the cost of a real import
# These are test-only patches; production code is not touched.


_INIT_MIN_CLAW_TOML = """\
[database]
db_path = "{db_path}"

[embeddings]
provider = "google"
model = "gemini-embedding-2-preview"

[local_llm]
provider = "ollama"
kv_cache_quantization = "q8_0"

[governance]
sweep_interval_cycles = 10

[cag]
token_budget_max = 16000
"""


def _write_min_claw_toml(tmp_dir: Path, db_filename: str = "claw.db") -> Path:
    """Write a minimal claw.toml pointing at a tmp-dir-scoped SQLite DB."""
    db_path = tmp_dir / db_filename
    cfg = tmp_dir / "claw.toml"
    cfg.write_text(_INIT_MIN_CLAW_TOML.format(db_path=str(db_path)))
    return cfg


def _init_capture_run_seed():
    """Return an AsyncMock that records the ``names`` it was invoked with.

    The mock resolves to a seeded-style summary so the CLI reports a
    successful import without ever touching the real pack files.
    """
    captured: dict = {"called_with": None, "calls": 0}

    async def _fake_run_seed(engine, embedding_engine=None, force=False, config=None, names=None):
        captured["calls"] += 1
        captured["called_with"] = list(names) if names is not None else None
        return {
            "imported": 2,
            "skipped": 0,
            "rejected": 0,
            "errors": [],
            "details": [],
            "reason": "seeded",
        }

    return _fake_run_seed, captured


def test_cam_init_non_interactive_default_domain(tmp_path):
    """``cam init --non-interactive`` with no --domain defaults to python.

    We verify the wizard actually delegates to ``run_seed`` with the
    python-domain pack list. Embeddings are forced offline so the test
    never reaches out to Gemini.
    """
    from claw.cli._monolith import app
    from claw.community.seeder import DOMAIN_PACKS

    config_path = _write_min_claw_toml(tmp_path)
    fake_run_seed, captured = _init_capture_run_seed()

    runner = CliRunner()
    with patch(
        "claw.db.embeddings.EmbeddingEngine",
        side_effect=RuntimeError("no embeddings in tests"),
    ):
        with patch("claw.community.seeder.run_seed", side_effect=fake_run_seed):
            result = runner.invoke(
                app,
                ["init", "--non-interactive", "--config", str(config_path), "--skip-smoke-test"],
                catch_exceptions=False,
            )

    assert result.exit_code == 0, result.output
    assert captured["calls"] == 1
    # The default domain is python, so exactly the python pack list was requested.
    assert captured["called_with"] == DOMAIN_PACKS["python"]
    assert "python" in result.output
    assert "CAM-PULSE is ready" in result.output


def test_cam_init_non_interactive_with_explicit_domain(tmp_path):
    """``cam init --non-interactive --domain devsecops`` bootstraps devsecops."""
    from claw.cli._monolith import app
    from claw.community.seeder import DOMAIN_PACKS

    config_path = _write_min_claw_toml(tmp_path)
    fake_run_seed, captured = _init_capture_run_seed()

    runner = CliRunner()
    with patch(
        "claw.db.embeddings.EmbeddingEngine",
        side_effect=RuntimeError("no embeddings in tests"),
    ):
        with patch("claw.community.seeder.run_seed", side_effect=fake_run_seed):
            result = runner.invoke(
                app,
                [
                    "init",
                    "--non-interactive",
                    "--domain", "devsecops",
                    "--config", str(config_path),
                    "--skip-smoke-test",
                ],
                catch_exceptions=False,
            )

    assert result.exit_code == 0, result.output
    assert captured["called_with"] == DOMAIN_PACKS["devsecops"]
    assert "devsecops" in result.output


def test_cam_init_non_interactive_missing_config_fails(tmp_path):
    """In --non-interactive mode, a missing claw.toml is a hard failure (exit 1).

    The wizard must refuse to auto-create a config in non-interactive mode —
    CI jobs should not silently generate config files.
    """
    from claw.cli._monolith import app

    # Point --config at a path that does NOT exist.
    missing = tmp_path / "does_not_exist.toml"
    assert not missing.exists()

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["init", "--non-interactive", "--config", str(missing), "--skip-smoke-test"],
        catch_exceptions=False,
    )

    assert result.exit_code == 1, result.output
    assert "No claw.toml found" in result.output
    assert "non-interactive" in result.output.lower()


def test_cam_init_invalid_domain_exits_2(tmp_path):
    """``cam init --non-interactive --domain bogus`` exits 2 with a clear error."""
    from claw.cli._monolith import app

    config_path = _write_min_claw_toml(tmp_path)

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "init",
            "--non-interactive",
            "--domain", "bogus",
            "--config", str(config_path),
            "--skip-smoke-test",
        ],
        catch_exceptions=False,
    )

    assert result.exit_code == 2, result.output
    assert "Invalid --domain" in result.output or "unknown domain" in result.output.lower()
    # The valid list should be surfaced so the user can recover.
    assert "python" in result.output


def test_cam_init_idempotent_already_initialized(tmp_path):
    """Second invocation without --force exits 0 with the idempotency message.

    We simulate an already-populated DB by patching
    ``Repository.count_methodologies`` to return a positive count on the
    very first call. run_seed must NOT be invoked.
    """
    from claw.cli._monolith import app

    config_path = _write_min_claw_toml(tmp_path)
    fake_run_seed, captured = _init_capture_run_seed()

    async def _fake_count() -> int:
        return 42

    runner = CliRunner()
    with patch(
        "claw.db.embeddings.EmbeddingEngine",
        side_effect=RuntimeError("no embeddings in tests"),
    ):
        with patch("claw.community.seeder.run_seed", side_effect=fake_run_seed):
            with patch(
                "claw.db.repository.Repository.count_methodologies",
                new=lambda self: _fake_count(),
            ):
                result = runner.invoke(
                    app,
                    [
                        "init",
                        "--non-interactive",
                        "--config", str(config_path),
                        "--skip-smoke-test",
                    ],
                    catch_exceptions=False,
                )

    assert result.exit_code == 0, result.output
    assert "already initialized" in result.output
    assert "42" in result.output  # reports current count
    assert "--force" in result.output
    # Critical: run_seed must NOT have been called on the idempotent path.
    assert captured["calls"] == 0


def test_cam_init_force_overrides_idempotency(tmp_path):
    """``--force`` must bypass the idempotency check and call run_seed anyway."""
    from claw.cli._monolith import app

    config_path = _write_min_claw_toml(tmp_path)
    fake_run_seed, captured = _init_capture_run_seed()

    async def _fake_count() -> int:
        return 99

    runner = CliRunner()
    with patch(
        "claw.db.embeddings.EmbeddingEngine",
        side_effect=RuntimeError("no embeddings in tests"),
    ):
        with patch("claw.community.seeder.run_seed", side_effect=fake_run_seed):
            with patch(
                "claw.db.repository.Repository.count_methodologies",
                new=lambda self: _fake_count(),
            ):
                result = runner.invoke(
                    app,
                    [
                        "init",
                        "--non-interactive",
                        "--force",
                        "--config", str(config_path),
                        "--skip-smoke-test",
                    ],
                    catch_exceptions=False,
                )

    assert result.exit_code == 0, result.output
    # --force bypasses idempotency and we reach run_seed.
    assert captured["calls"] == 1
    assert "already initialized" not in result.output


def test_cam_init_parse_domain_input_helper_directly():
    """Unit test for the _init_parse_domain_input helper (no CLI indirection)."""
    from claw.cli._monolith import _init_parse_domain_input

    valid = ["all", "devsecops", "python", "webdev"]

    # Single name.
    assert _init_parse_domain_input("python", valid) == ["python"]
    # Single index (1-based).
    assert _init_parse_domain_input("1", valid) == ["all"]
    # Comma-separated names.
    assert _init_parse_domain_input("python,devsecops", valid) == ["python", "devsecops"]
    # Dedup input.
    assert _init_parse_domain_input("python,python", valid) == ["python"]
    # "all" collapses any other selection.
    assert _init_parse_domain_input("python,all,webdev", valid) == ["all"]
    # Unknown token raises.
    with pytest.raises(ValueError):
        _init_parse_domain_input("bogus", valid)
    # Out-of-range index raises.
    with pytest.raises(ValueError):
        _init_parse_domain_input("99", valid)
    # Empty input raises.
    with pytest.raises(ValueError):
        _init_parse_domain_input("   ", valid)
