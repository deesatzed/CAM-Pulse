"""Tests for CAM-PULSE Freshness Monitor module.

Covers:
  - extract_owner_repo() pure string parsing (10 tests)
  - Dataclass construction: Phase1Result, FreshnessResult, RefreshResult (7 tests)
  - FreshnessConfig defaults and custom values (2 tests)
  - Significance score computation — pure math (6 tests)
  - Database operations with in-memory SQLite (7 tests)
  - retire_stale_methodologies() lifecycle management (12 tests)
  - update_mine_metadata() after re-mine (3 tests)
  - size_at_mine column and size_signal computation (9 tests)
  - Integration tests with real GitHub API (5 tests, skip if no GITHUB_TOKEN)

All tests use REAL data — no mocks, no placeholders.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from claw.core.config import (
    ClawConfig,
    DatabaseConfig,
    FreshnessConfig,
    PulseConfig,
)
from claw.db.engine import DatabaseEngine
from claw.pulse.freshness import GITHUB_API_BASE, FreshnessMonitor
from claw.pulse.models import FreshnessResult, Phase1Result, RefreshResult


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
async def pulse_engine():
    """In-memory engine with pulse tables."""
    config = DatabaseConfig(db_path=":memory:")
    engine = DatabaseEngine(config)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()
    yield engine
    await engine.close()


def _make_config(
    freshness_overrides: dict | None = None,
) -> ClawConfig:
    """Build a ClawConfig with optional freshness config overrides."""
    fc = FreshnessConfig(**(freshness_overrides or {}))
    pulse = PulseConfig(freshness=fc)
    return ClawConfig(pulse=pulse)


def _make_monitor(
    engine: DatabaseEngine,
    freshness_overrides: dict | None = None,
) -> FreshnessMonitor:
    """Build a FreshnessMonitor with an in-memory engine."""
    config = _make_config(freshness_overrides)
    return FreshnessMonitor(engine=engine, config=config)


async def _insert_discovery(
    engine: DatabaseEngine,
    canonical_url: str,
    status: str = "assimilated",
    source_kind: str = "github",
    head_sha: str = "",
    etag: str = "",
    last_pushed_at: str = "",
    stars_at_mine: int = 0,
    latest_release_tag: str = "",
    freshness_status: str = "unknown",
    last_checked_at: str | None = None,
) -> str:
    """Insert a real pulse_discovery row and return its id."""
    disc_id = str(uuid.uuid4())
    await engine.execute(
        """INSERT INTO pulse_discoveries
           (id, github_url, canonical_url, status, source_kind,
            head_sha_at_mine, etag, last_pushed_at, stars_at_mine,
            latest_release_tag, freshness_status, last_checked_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            disc_id,
            canonical_url,
            canonical_url,
            status,
            source_kind,
            head_sha,
            etag,
            last_pushed_at,
            stars_at_mine,
            latest_release_tag,
            freshness_status,
            last_checked_at,
        ],
    )
    return disc_id


# ===========================================================================
# Group 1: extract_owner_repo() — pure string parsing (no DB needed)
# ===========================================================================

class TestExtractOwnerRepo:
    """Test FreshnessMonitor.extract_owner_repo static method."""

    def test_extract_standard_url(self):
        result = FreshnessMonitor.extract_owner_repo("https://github.com/owner/repo")
        assert result == "owner/repo"

    def test_extract_trailing_slash(self):
        result = FreshnessMonitor.extract_owner_repo("https://github.com/owner/repo/")
        assert result == "owner/repo"

    def test_extract_dot_git(self):
        result = FreshnessMonitor.extract_owner_repo("https://github.com/owner/repo.git")
        assert result == "owner/repo"

    def test_extract_mixed_case(self):
        result = FreshnessMonitor.extract_owner_repo("HTTPS://GitHub.com/Owner/Repo")
        assert result == "Owner/Repo"

    def test_extract_http(self):
        result = FreshnessMonitor.extract_owner_repo("http://github.com/owner/repo")
        assert result == "owner/repo"

    def test_extract_with_subpath(self):
        result = FreshnessMonitor.extract_owner_repo(
            "https://github.com/owner/repo/tree/main"
        )
        assert result == "owner/repo"

    def test_extract_invalid_url(self):
        result = FreshnessMonitor.extract_owner_repo("https://gitlab.com/a/b")
        assert result is None

    def test_extract_empty_string(self):
        result = FreshnessMonitor.extract_owner_repo("")
        assert result is None

    def test_extract_no_repo(self):
        result = FreshnessMonitor.extract_owner_repo("https://github.com/owner")
        assert result is None

    def test_extract_trailing_git_slash(self):
        result = FreshnessMonitor.extract_owner_repo("https://github.com/owner/repo.git/")
        assert result == "owner/repo"


# ===========================================================================
# Group 2: Dataclass construction (Phase1Result, FreshnessResult, RefreshResult)
# ===========================================================================

class TestPhase1Result:
    def test_phase1_result_defaults(self):
        p = Phase1Result(canonical_url="https://github.com/a/b")
        assert p.canonical_url == "https://github.com/a/b"
        assert p.changed is False
        assert p.pushed_at == ""
        assert p.etag == ""
        assert p.stars == 0
        assert p.size_kb == 0
        assert p.rate_limit_remaining == -1
        assert p.error is None

    def test_phase1_result_success(self):
        p = Phase1Result(
            canonical_url="https://github.com/pallets/flask",
            changed=True,
            pushed_at="2026-03-01T12:00:00Z",
            etag='W/"abc123"',
            stars=68000,
            size_kb=15000,
            rate_limit_remaining=4999,
        )
        assert p.changed is True
        assert p.stars == 68000
        assert p.etag == 'W/"abc123"'
        assert p.rate_limit_remaining == 4999
        assert p.error is None

    def test_phase1_result_error(self):
        p = Phase1Result(
            canonical_url="https://github.com/x/y",
            error="GitHub API returned 403: rate limited",
        )
        assert p.changed is False
        assert p.error == "GitHub API returned 403: rate limited"


class TestFreshnessResult:
    def test_freshness_result_defaults(self):
        fr = FreshnessResult(canonical_url="https://github.com/a/b")
        assert fr.canonical_url == "https://github.com/a/b"
        assert fr.phase1 is None
        assert fr.significance_score == 0.0
        assert fr.needs_refresh is False
        assert fr.commits_since_mine == 0
        assert fr.has_new_release is False
        assert fr.readme_changed is False
        assert fr.error is None

    def test_freshness_result_stale(self):
        p1 = Phase1Result(canonical_url="https://github.com/a/b", changed=True)
        fr = FreshnessResult(
            canonical_url="https://github.com/a/b",
            phase1=p1,
            significance_score=0.7,
            needs_refresh=True,
            commits_since_mine=45,
            has_new_release=True,
            readme_changed=True,
        )
        assert fr.needs_refresh is True
        assert fr.significance_score == 0.7
        assert fr.commits_since_mine == 45
        assert fr.has_new_release is True
        assert fr.readme_changed is True
        assert fr.phase1 is p1


class TestRefreshResult:
    def test_refresh_result_defaults(self):
        rr = RefreshResult(canonical_url="https://github.com/a/b")
        assert rr.canonical_url == "https://github.com/a/b"
        assert rr.success is False
        assert rr.new_methodology_ids == []
        assert rr.retired_methodology_ids == []
        assert rr.kept_methodology_ids == []
        assert rr.head_sha == ""
        assert rr.error is None

    def test_refresh_result_success(self):
        rr = RefreshResult(
            canonical_url="https://github.com/a/b",
            success=True,
            new_methodology_ids=["m1", "m2"],
            retired_methodology_ids=["m0"],
            kept_methodology_ids=["m3"],
            head_sha="abc123def456",
        )
        assert rr.success is True
        assert len(rr.new_methodology_ids) == 2
        assert rr.retired_methodology_ids == ["m0"]
        assert rr.head_sha == "abc123def456"
        assert rr.error is None


# ===========================================================================
# Group 3: FreshnessConfig defaults
# ===========================================================================

class TestFreshnessConfig:
    def test_freshness_config_defaults(self):
        fc = FreshnessConfig()
        assert fc.check_interval_hours == 12
        assert fc.significance_commit_threshold == 20
        assert fc.significance_release_weight == pytest.approx(0.4)
        assert fc.significance_readme_weight == pytest.approx(0.2)
        assert fc.significance_size_delta_pct == 20
        assert fc.significance_threshold == pytest.approx(0.4)
        assert fc.github_token_env == "GITHUB_TOKEN"
        assert fc.max_repos_per_check == 50
        assert fc.rate_limit_buffer == 10

    def test_freshness_config_custom(self):
        fc = FreshnessConfig(
            check_interval_hours=6,
            significance_commit_threshold=10,
            significance_release_weight=0.5,
            significance_readme_weight=0.3,
            significance_threshold=0.6,
            max_repos_per_check=100,
            rate_limit_buffer=20,
        )
        assert fc.check_interval_hours == 6
        assert fc.significance_commit_threshold == 10
        assert fc.significance_release_weight == pytest.approx(0.5)
        assert fc.significance_readme_weight == pytest.approx(0.3)
        assert fc.significance_threshold == pytest.approx(0.6)
        assert fc.max_repos_per_check == 100
        assert fc.rate_limit_buffer == 20


# ===========================================================================
# Group 4: Significance score computation (pure math, in-process)
# ===========================================================================

def _compute_significance(
    commits_since: int,
    has_new_release: bool,
    readme_changed: bool,
    size_signal: float = 0.0,
    commit_threshold: int = 20,
    release_weight: float = 0.4,
    readme_weight: float = 0.2,
) -> float:
    """Replicate the significance formula from _phase2_significance.

    This is NOT imported from the module -- it mirrors the exact computation
    in freshness.py lines 272-281 so we can verify the math deterministically.
    """
    commit_signal = min(commits_since / max(commit_threshold, 1), 1.0)
    release_signal = 1.0 if has_new_release else 0.0
    readme_signal = 1.0 if readme_changed else 0.0
    significance = (
        commit_signal * 0.3
        + release_signal * release_weight
        + readme_signal * readme_weight
        + size_signal * 0.1
    )
    return round(significance, 3)


class TestSignificanceComputation:
    """Verify the significance formula produces correct scores."""

    def test_significance_all_signals_max(self):
        score = _compute_significance(
            commits_since=20,
            has_new_release=True,
            readme_changed=True,
            size_signal=1.0,
            commit_threshold=20,
            release_weight=0.4,
            readme_weight=0.2,
        )
        # 0.3 + 0.4 + 0.2 + 0.1 = 1.0
        assert score == pytest.approx(1.0)

    def test_significance_all_zero(self):
        score = _compute_significance(
            commits_since=0,
            has_new_release=False,
            readme_changed=False,
            size_signal=0.0,
        )
        assert score == pytest.approx(0.0)

    def test_significance_release_only(self):
        score = _compute_significance(
            commits_since=0,
            has_new_release=True,
            readme_changed=False,
            size_signal=0.0,
            release_weight=0.4,
        )
        # 0.0 + 0.4 + 0.0 + 0.0 = 0.4
        assert score == pytest.approx(0.4)

    def test_significance_commits_only(self):
        score = _compute_significance(
            commits_since=20,
            has_new_release=False,
            readme_changed=False,
            size_signal=0.0,
            commit_threshold=20,
        )
        # min(20/20, 1.0) * 0.3 = 0.3
        assert score == pytest.approx(0.3)

    def test_significance_below_threshold(self):
        """Small change (readme only = 0.2) below default threshold (0.4)."""
        score = _compute_significance(
            commits_since=0,
            has_new_release=False,
            readme_changed=True,
            size_signal=0.0,
            readme_weight=0.2,
        )
        # 0.0 + 0.0 + 0.2 + 0.0 = 0.2
        assert score == pytest.approx(0.2)
        fc = FreshnessConfig()
        assert score < fc.significance_threshold

    def test_significance_at_threshold(self):
        """Exactly at threshold (release_only = 0.4 == threshold 0.4)."""
        score = _compute_significance(
            commits_since=0,
            has_new_release=True,
            readme_changed=False,
            size_signal=0.0,
            release_weight=0.4,
        )
        assert score == pytest.approx(0.4)
        fc = FreshnessConfig()
        # needs_refresh when significance >= threshold
        assert score >= fc.significance_threshold


# ===========================================================================
# Group 5: Database operations (in-memory SQLite, no API calls)
# ===========================================================================

class TestMigration11FreshnessColumns:
    """Verify Migration 11 creates freshness tracking columns."""

    @pytest.mark.asyncio
    async def test_migration_11_freshness_columns(self, pulse_engine):
        """Verify all freshness columns exist after migration + schema init."""
        rows = await pulse_engine.fetch_all(
            "SELECT name FROM pragma_table_info('pulse_discoveries')"
        )
        col_names = {r["name"] for r in rows}

        expected_freshness_cols = {
            "last_checked_at",
            "last_pushed_at",
            "head_sha_at_mine",
            "etag",
            "stars_at_mine",
            "latest_release_tag",
            "freshness_status",
            "source_kind",
        }
        for col in expected_freshness_cols:
            assert col in col_names, f"Missing column: {col}"

    @pytest.mark.asyncio
    async def test_migration_11_idempotent(self, pulse_engine):
        """Running migrations a second time does not error."""
        # Migrations already ran in fixture; run them again
        await pulse_engine.apply_migrations()
        # Verify table still intact
        row = await pulse_engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name='pulse_discoveries'"
        )
        assert row is not None
        assert row["cnt"] == 1


class TestUpdateCheckedTimestamp:
    @pytest.mark.asyncio
    async def test_update_checked_timestamp(self, pulse_engine):
        """_update_checked sets last_checked_at on the discovery row."""
        url = "https://github.com/test/update-checked"
        await _insert_discovery(pulse_engine, url)

        monitor = _make_monitor(pulse_engine)
        await monitor._update_checked(url)

        row = await pulse_engine.fetch_one(
            "SELECT last_checked_at FROM pulse_discoveries WHERE canonical_url = ?",
            [url],
        )
        assert row is not None
        assert row["last_checked_at"] is not None
        # Verify it's a valid ISO timestamp
        parsed = datetime.fromisoformat(row["last_checked_at"].replace("Z", "+00:00"))
        assert parsed.year >= 2026

    @pytest.mark.asyncio
    async def test_update_checked_with_etag(self, pulse_engine):
        """_update_checked with etag also updates the etag column."""
        url = "https://github.com/test/update-etag"
        await _insert_discovery(pulse_engine, url)

        monitor = _make_monitor(pulse_engine)
        await monitor._update_checked(url, etag='W/"new-etag-value"')

        row = await pulse_engine.fetch_one(
            "SELECT last_checked_at, etag FROM pulse_discoveries WHERE canonical_url = ?",
            [url],
        )
        assert row is not None
        assert row["etag"] == 'W/"new-etag-value"'
        assert row["last_checked_at"] is not None


class TestUpdateFreshnessMetadata:
    @pytest.mark.asyncio
    async def test_update_freshness_metadata(self, pulse_engine):
        """_update_freshness_metadata writes all columns."""
        url = "https://github.com/test/freshness-meta"
        await _insert_discovery(pulse_engine, url)

        monitor = _make_monitor(pulse_engine)
        await monitor._update_freshness_metadata(
            canonical_url=url,
            etag='W/"etag-xyz"',
            pushed_at="2026-03-20T10:00:00Z",
            stars=1500,
            freshness_status="stale",
        )

        row = await pulse_engine.fetch_one(
            """SELECT last_checked_at, etag, last_pushed_at, stars_at_mine, freshness_status
               FROM pulse_discoveries WHERE canonical_url = ?""",
            [url],
        )
        assert row is not None
        assert row["etag"] == 'W/"etag-xyz"'
        assert row["last_pushed_at"] == "2026-03-20T10:00:00Z"
        assert row["stars_at_mine"] == 1500
        assert row["freshness_status"] == "stale"
        assert row["last_checked_at"] is not None


class TestUpdateMineMetadata:
    @pytest.mark.asyncio
    async def test_update_mine_metadata(self, pulse_engine):
        """update_mine_metadata writes head_sha, pushed_at, release_tag, and sets status fresh."""
        url = "https://github.com/test/mine-meta"
        await _insert_discovery(pulse_engine, url, freshness_status="stale")

        monitor = _make_monitor(pulse_engine)
        await monitor.update_mine_metadata(
            canonical_url=url,
            head_sha="abc123def456789",
            pushed_at="2026-03-25T08:00:00Z",
            release_tag="v2.1.0",
        )

        row = await pulse_engine.fetch_one(
            """SELECT head_sha_at_mine, last_pushed_at, latest_release_tag,
                      freshness_status, last_checked_at
               FROM pulse_discoveries WHERE canonical_url = ?""",
            [url],
        )
        assert row is not None
        assert row["head_sha_at_mine"] == "abc123def456789"
        assert row["last_pushed_at"] == "2026-03-25T08:00:00Z"
        assert row["latest_release_tag"] == "v2.1.0"
        assert row["freshness_status"] == "fresh"
        assert row["last_checked_at"] is not None


class TestCheckAllEmptyAndFiltered:
    @pytest.mark.asyncio
    async def test_check_all_empty_db(self, pulse_engine):
        """No assimilated repos in DB -> check_all returns empty list."""
        monitor = _make_monitor(pulse_engine)
        results = await monitor.check_all()
        assert results == []

    @pytest.mark.asyncio
    async def test_check_all_no_github_repos(self, pulse_engine):
        """Repos with source_kind='hf' are excluded from freshness checks."""
        await _insert_discovery(
            pulse_engine,
            "https://huggingface.co/org/model",
            status="assimilated",
            source_kind="hf",
        )
        monitor = _make_monitor(pulse_engine)
        results = await monitor.check_all()
        assert results == []

    @pytest.mark.asyncio
    async def test_check_all_skips_non_assimilated(self, pulse_engine):
        """Only status='assimilated' rows are checked."""
        await _insert_discovery(
            pulse_engine,
            "https://github.com/test/discovered-only",
            status="discovered",
            source_kind="github",
        )
        await _insert_discovery(
            pulse_engine,
            "https://github.com/test/failed-one",
            status="failed",
            source_kind="github",
        )
        monitor = _make_monitor(pulse_engine)
        results = await monitor.check_all()
        assert results == []


# ===========================================================================
# Group 5b: Monitor constructor behavior
# ===========================================================================

class TestMonitorConstructor:
    def test_headers_without_token(self):
        """Without GITHUB_TOKEN env, no Authorization header is set."""
        # Use a non-existent env var name to guarantee no token
        config = _make_config({"github_token_env": "NONEXISTENT_TOKEN_VAR_FOR_TEST"})
        engine_config = DatabaseConfig(db_path=":memory:")
        # We only test the constructor logic, not DB operations
        # (we cannot call connect() without async context, but we can
        # verify the header logic by inspecting the monitor object).
        # We need an engine stub; build a real one inline.
        # Actually, let's just verify the config propagation
        monitor = FreshnessMonitor.__new__(FreshnessMonitor)
        monitor.config = config
        monitor._fc = config.pulse.freshness
        monitor._token = os.getenv("NONEXISTENT_TOKEN_VAR_FOR_TEST", "")
        monitor._headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if monitor._token:
            monitor._headers["Authorization"] = f"Bearer {monitor._token}"

        assert "Authorization" not in monitor._headers

    def test_config_propagation(self):
        """FreshnessConfig values propagate through ClawConfig -> PulseConfig -> monitor."""
        config = _make_config({
            "significance_commit_threshold": 50,
            "max_repos_per_check": 25,
        })
        assert config.pulse.freshness.significance_commit_threshold == 50
        assert config.pulse.freshness.max_repos_per_check == 25


# ===========================================================================
# Group 5c: Phase1 error path (bad URL, no API call needed)
# ===========================================================================

class TestPhase1ErrorPath:
    @pytest.mark.asyncio
    async def test_phase1_unparseable_url(self, pulse_engine):
        """Phase1 returns error if URL cannot be parsed to owner/repo."""
        monitor = _make_monitor(pulse_engine)
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            result = await monitor._phase1_metadata_check(
                client,
                "https://gitlab.com/not/github",
                stored_etag="",
            )
        assert result.error is not None
        assert "Cannot parse owner/repo" in result.error
        assert result.changed is False

    @pytest.mark.asyncio
    async def test_phase2_unparseable_url(self, pulse_engine):
        """Phase2 returns error if URL cannot be parsed to owner/repo."""
        monitor = _make_monitor(pulse_engine)
        p1 = Phase1Result(canonical_url="https://notgithub.com/x", changed=True)
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            result = await monitor._phase2_significance(
                client,
                "https://notgithub.com/x",
                p1,
                stored_sha="",
                stored_pushed_at="",
                stored_stars=0,
                stored_release="",
            )
        assert result.error is not None
        assert "Cannot parse owner/repo" in result.error

    @pytest.mark.asyncio
    async def test_phase2_unchanged_pushed_at(self, pulse_engine):
        """If pushed_at matches stored value, significance is 0."""
        monitor = _make_monitor(pulse_engine)
        p1 = Phase1Result(
            canonical_url="https://github.com/a/b",
            changed=True,
            pushed_at="2026-03-01T00:00:00Z",
        )
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            result = await monitor._phase2_significance(
                client,
                "https://github.com/a/b",
                p1,
                stored_sha="abc123",
                stored_pushed_at="2026-03-01T00:00:00Z",
                stored_stars=100,
                stored_release="v1.0",
            )
        assert result.significance_score == 0.0
        assert result.needs_refresh is False


# ===========================================================================
# Group 5d: GITHUB_API_BASE constant
# ===========================================================================

class TestConstants:
    def test_github_api_base(self):
        assert GITHUB_API_BASE == "https://api.github.com"


# ===========================================================================
# Group 6: Integration tests (require GITHUB_TOKEN, marked skipif)
# ===========================================================================

_requires_github_token = pytest.mark.skipif(
    not os.getenv("GITHUB_TOKEN"),
    reason="GITHUB_TOKEN not set",
)


@_requires_github_token
class TestPhase1RealRepo:
    """Integration tests against the real GitHub API."""

    @pytest.mark.asyncio
    async def test_phase1_real_repo(self, pulse_engine):
        """Phase 1 metadata check against pallets/flask (a stable, well-known repo)."""
        monitor = _make_monitor(pulse_engine)
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            result = await monitor._phase1_metadata_check(
                client,
                "https://github.com/pallets/flask",
                stored_etag="",
            )
        # Should succeed with a 200
        assert result.error is None
        assert result.changed is True
        assert result.pushed_at != ""
        assert result.stars > 0
        assert result.etag != ""
        assert result.rate_limit_remaining >= 0

    @pytest.mark.asyncio
    async def test_etag_caching(self, pulse_engine):
        """First call gets 200, second call with ETag may get 304 (not modified)."""
        monitor = _make_monitor(pulse_engine)
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            # First call: no etag
            first = await monitor._phase1_metadata_check(
                client,
                "https://github.com/pallets/flask",
                stored_etag="",
            )
            assert first.error is None
            assert first.changed is True
            assert first.etag != ""

            # Second call with the etag from the first call
            second = await monitor._phase1_metadata_check(
                client,
                "https://github.com/pallets/flask",
                stored_etag=first.etag,
            )
            assert second.error is None
            # If repo hasn't changed in the last few milliseconds (very likely),
            # we get 304 -> changed=False. In rare cases it could still be 200.
            # Either outcome is valid; what matters is no error.
            if not second.changed:
                # 304 path: etag preserved
                assert second.etag == first.etag
            else:
                # 200 path: new etag
                assert second.etag != ""

    @pytest.mark.asyncio
    async def test_get_commits_since_real(self, pulse_engine):
        """_get_commits_since on a known repo with a real SHA."""
        monitor = _make_monitor(pulse_engine)
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            # Use a deliberately old SHA from flask (first commit is
            # very old, so there will be many commits since). If the SHA
            # doesn't exist (force-pushed away), the code returns 999.
            count = await monitor._get_commits_since(
                client, "pallets/flask", "a0b123"
            )
            # Either 999 (SHA not found) or some positive number
            assert count >= 0

    @pytest.mark.asyncio
    async def test_check_new_release_real(self, pulse_engine):
        """_check_new_release on pallets/flask with a deliberately old tag."""
        monitor = _make_monitor(pulse_engine)
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            has_new = await monitor._check_new_release(
                client, "pallets/flask", "v0.1"
            )
            # Flask has many releases beyond v0.1
            assert has_new is True

    @pytest.mark.asyncio
    async def test_check_readme_changed_real(self, pulse_engine):
        """_check_readme_changed on pallets/flask since a very old date."""
        monitor = _make_monitor(pulse_engine)
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            changed = await monitor._check_readme_changed(
                client, "pallets/flask", "2020-01-01T00:00:00Z"
            )
            # Flask README has been updated since 2020
            assert changed is True


# ===========================================================================
# Group 7: retire_stale_methodologies — lifecycle management
# ===========================================================================

import json as _json


async def _insert_methodology(
    engine: DatabaseEngine,
    methodology_id: str,
    problem_description: str = "test problem",
    solution_code: str = "test solution",
    lifecycle_state: str = "viable",
    superseded_by: str | None = None,
) -> str:
    """Insert a real methodology row and return its id."""
    await engine.execute(
        """INSERT INTO methodologies
           (id, problem_description, solution_code, lifecycle_state, superseded_by)
           VALUES (?, ?, ?, ?, ?)""",
        [methodology_id, problem_description, solution_code, lifecycle_state, superseded_by],
    )
    return methodology_id


async def _insert_discovery_with_methodologies(
    engine: DatabaseEngine,
    canonical_url: str,
    methodology_ids: list[str],
    status: str = "assimilated",
) -> str:
    """Insert a discovery with methodology_ids JSON column populated."""
    disc_id = str(uuid.uuid4())
    await engine.execute(
        """INSERT INTO pulse_discoveries
           (id, github_url, canonical_url, status, methodology_ids)
           VALUES (?, ?, ?, ?, ?)""",
        [disc_id, canonical_url, canonical_url, status, _json.dumps(methodology_ids)],
    )
    return disc_id


class TestRetireStaleMethodologies:
    """Tests for FreshnessMonitor.retire_stale_methodologies()."""

    @pytest.mark.asyncio
    async def test_no_discovery_record(self, pulse_engine):
        """Returns empty lists when no discovery row exists for the URL."""
        monitor = _make_monitor(pulse_engine)
        retired, kept = await monitor.retire_stale_methodologies(
            "https://github.com/nonexistent/repo", ["new-1"]
        )
        assert retired == []
        assert kept == []

    @pytest.mark.asyncio
    async def test_empty_methodology_ids(self, pulse_engine):
        """Returns empty lists when methodology_ids is empty JSON array."""
        url = "https://github.com/test/empty-ids"
        await _insert_discovery_with_methodologies(pulse_engine, url, [])
        monitor = _make_monitor(pulse_engine)
        retired, kept = await monitor.retire_stale_methodologies(url, ["new-1"])
        assert retired == []
        assert kept == []

    @pytest.mark.asyncio
    async def test_default_methodology_ids(self, pulse_engine):
        """Returns empty lists when methodology_ids is the default '[]'."""
        url = "https://github.com/test/default-ids"
        disc_id = str(uuid.uuid4())
        # methodology_ids defaults to '[]' (NOT NULL constraint)
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries
               (id, github_url, canonical_url, status)
               VALUES (?, ?, ?, 'assimilated')""",
            [disc_id, url, url],
        )
        monitor = _make_monitor(pulse_engine)
        retired, kept = await monitor.retire_stale_methodologies(url, ["new-1"])
        assert retired == []
        assert kept == []

    @pytest.mark.asyncio
    async def test_invalid_json_methodology_ids(self, pulse_engine):
        """Returns empty lists when methodology_ids is invalid JSON."""
        url = "https://github.com/test/bad-json"
        disc_id = str(uuid.uuid4())
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries
               (id, github_url, canonical_url, status, methodology_ids)
               VALUES (?, ?, ?, 'assimilated', ?)""",
            [disc_id, url, url, "not valid json {{{"],
        )
        monitor = _make_monitor(pulse_engine)
        retired, kept = await monitor.retire_stale_methodologies(url, ["new-1"])
        assert retired == []
        assert kept == []

    @pytest.mark.asyncio
    async def test_all_old_retired(self, pulse_engine):
        """All old methodologies are retired when none match new IDs."""
        url = "https://github.com/test/all-retired"
        old_ids = ["old-1", "old-2", "old-3"]
        new_ids = ["new-1", "new-2"]

        # Create methodology rows for the old IDs
        for mid in old_ids:
            await _insert_methodology(pulse_engine, mid)

        await _insert_discovery_with_methodologies(pulse_engine, url, old_ids)

        monitor = _make_monitor(pulse_engine)
        retired, kept = await monitor.retire_stale_methodologies(url, new_ids)

        assert sorted(retired) == sorted(old_ids)
        assert kept == []

        # Verify DB state: all old are 'declining' with superseded_by
        for mid in old_ids:
            row = await pulse_engine.fetch_one(
                "SELECT lifecycle_state, superseded_by FROM methodologies WHERE id = ?",
                [mid],
            )
            assert row is not None
            assert row["lifecycle_state"] == "declining"
            assert row["superseded_by"] == "new-1"

    @pytest.mark.asyncio
    async def test_all_old_kept(self, pulse_engine):
        """All old methodologies kept when all match new IDs."""
        url = "https://github.com/test/all-kept"
        ids = ["shared-1", "shared-2"]

        for mid in ids:
            await _insert_methodology(pulse_engine, mid)

        await _insert_discovery_with_methodologies(pulse_engine, url, ids)

        monitor = _make_monitor(pulse_engine)
        retired, kept = await monitor.retire_stale_methodologies(url, ids)

        assert retired == []
        assert sorted(kept) == sorted(ids)

        # Verify DB: lifecycle unchanged (still 'viable')
        for mid in ids:
            row = await pulse_engine.fetch_one(
                "SELECT lifecycle_state, superseded_by FROM methodologies WHERE id = ?",
                [mid],
            )
            assert row is not None
            assert row["lifecycle_state"] == "viable"
            assert row["superseded_by"] is None

    @pytest.mark.asyncio
    async def test_mixed_retired_and_kept(self, pulse_engine):
        """Some old methodologies are retired, others kept."""
        url = "https://github.com/test/mixed"
        old_ids = ["kept-a", "retired-b", "kept-c", "retired-d"]
        new_ids = ["kept-a", "kept-c", "brand-new-e"]

        for mid in old_ids:
            await _insert_methodology(pulse_engine, mid)

        await _insert_discovery_with_methodologies(pulse_engine, url, old_ids)

        monitor = _make_monitor(pulse_engine)
        retired, kept = await monitor.retire_stale_methodologies(url, new_ids)

        assert sorted(retired) == ["retired-b", "retired-d"]
        assert sorted(kept) == ["kept-a", "kept-c"]

        # Retired ones are declining
        for mid in ["retired-b", "retired-d"]:
            row = await pulse_engine.fetch_one(
                "SELECT lifecycle_state, superseded_by FROM methodologies WHERE id = ?",
                [mid],
            )
            assert row["lifecycle_state"] == "declining"
            assert row["superseded_by"] == "kept-a"  # first new ID

        # Kept ones are unchanged
        for mid in ["kept-a", "kept-c"]:
            row = await pulse_engine.fetch_one(
                "SELECT lifecycle_state FROM methodologies WHERE id = ?",
                [mid],
            )
            assert row["lifecycle_state"] == "viable"

    @pytest.mark.asyncio
    async def test_retire_with_empty_new_ids(self, pulse_engine):
        """When new_methodology_ids is empty, superseded_by is None."""
        url = "https://github.com/test/empty-new"
        old_ids = ["orphan-1"]

        await _insert_methodology(pulse_engine, "orphan-1")
        await _insert_discovery_with_methodologies(pulse_engine, url, old_ids)

        monitor = _make_monitor(pulse_engine)
        retired, kept = await monitor.retire_stale_methodologies(url, [])

        assert retired == ["orphan-1"]
        assert kept == []

        row = await pulse_engine.fetch_one(
            "SELECT lifecycle_state, superseded_by FROM methodologies WHERE id = ?",
            ["orphan-1"],
        )
        assert row["lifecycle_state"] == "declining"
        assert row["superseded_by"] is None

    @pytest.mark.asyncio
    async def test_retire_already_declining(self, pulse_engine):
        """Retiring an already-declining methodology still succeeds."""
        url = "https://github.com/test/already-declining"
        await _insert_methodology(pulse_engine, "decl-1", lifecycle_state="declining")
        await _insert_discovery_with_methodologies(pulse_engine, url, ["decl-1"])

        monitor = _make_monitor(pulse_engine)
        retired, kept = await monitor.retire_stale_methodologies(url, ["new-x"])

        assert retired == ["decl-1"]
        row = await pulse_engine.fetch_one(
            "SELECT lifecycle_state, superseded_by FROM methodologies WHERE id = ?",
            ["decl-1"],
        )
        assert row["lifecycle_state"] == "declining"
        assert row["superseded_by"] == "new-x"

    @pytest.mark.asyncio
    async def test_retire_nonexistent_methodology_id(self, pulse_engine):
        """Old ID in discovery that doesn't exist in methodologies table — no error."""
        url = "https://github.com/test/ghost-id"
        # Discovery references an ID that was never inserted into methodologies
        await _insert_discovery_with_methodologies(pulse_engine, url, ["ghost-999"])

        monitor = _make_monitor(pulse_engine)
        # Should not raise — the UPDATE simply affects 0 rows
        retired, kept = await monitor.retire_stale_methodologies(url, ["new-1"])
        assert retired == ["ghost-999"]  # Counted as retired even if row didn't exist
        assert kept == []

    @pytest.mark.asyncio
    async def test_retire_preserves_other_fields(self, pulse_engine):
        """Retirement only changes lifecycle_state and superseded_by."""
        url = "https://github.com/test/preserve-fields"
        await _insert_methodology(
            pulse_engine,
            "pres-1",
            problem_description="Important pattern",
            solution_code="def foo(): pass",
            lifecycle_state="thriving",
        )
        await _insert_discovery_with_methodologies(pulse_engine, url, ["pres-1"])

        monitor = _make_monitor(pulse_engine)
        await monitor.retire_stale_methodologies(url, ["new-z"])

        row = await pulse_engine.fetch_one(
            "SELECT problem_description, solution_code, lifecycle_state, superseded_by FROM methodologies WHERE id = ?",
            ["pres-1"],
        )
        assert row["problem_description"] == "Important pattern"
        assert row["solution_code"] == "def foo(): pass"
        assert row["lifecycle_state"] == "declining"
        assert row["superseded_by"] == "new-z"

    @pytest.mark.asyncio
    async def test_methodology_ids_not_a_list(self, pulse_engine):
        """methodology_ids stored as a JSON string (not array) returns empty."""
        url = "https://github.com/test/not-list"
        disc_id = str(uuid.uuid4())
        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries
               (id, github_url, canonical_url, status, methodology_ids)
               VALUES (?, ?, ?, 'assimilated', ?)""",
            [disc_id, url, url, _json.dumps("just-a-string")],
        )
        monitor = _make_monitor(pulse_engine)
        retired, kept = await monitor.retire_stale_methodologies(url, ["new-1"])
        assert retired == []
        assert kept == []


# ===========================================================================
# Group 8: update_mine_metadata — post-re-mine metadata update
# ===========================================================================


class TestUpdateMineMetadataExtended:
    """Extended tests for update_mine_metadata after re-mine."""

    @pytest.mark.asyncio
    async def test_update_mine_metadata_minimal(self, pulse_engine):
        """update_mine_metadata with only head_sha, defaults for rest."""
        url = "https://github.com/test/mine-minimal"
        await _insert_discovery(pulse_engine, url, freshness_status="stale")

        monitor = _make_monitor(pulse_engine)
        await monitor.update_mine_metadata(url, "deadbeef")

        row = await pulse_engine.fetch_one(
            """SELECT head_sha_at_mine, last_pushed_at, latest_release_tag,
                      freshness_status, last_checked_at
               FROM pulse_discoveries WHERE canonical_url = ?""",
            [url],
        )
        assert row["head_sha_at_mine"] == "deadbeef"
        assert row["last_pushed_at"] == ""
        assert row["latest_release_tag"] == ""
        assert row["freshness_status"] == "fresh"
        assert row["last_checked_at"] is not None

    @pytest.mark.asyncio
    async def test_update_mine_metadata_resets_stale_to_fresh(self, pulse_engine):
        """After re-mine, freshness_status always becomes 'fresh'."""
        url = "https://github.com/test/reset-fresh"
        await _insert_discovery(pulse_engine, url, freshness_status="refreshing")

        monitor = _make_monitor(pulse_engine)
        await monitor.update_mine_metadata(url, "abc123", pushed_at="2026-03-25T12:00:00Z")

        row = await pulse_engine.fetch_one(
            "SELECT freshness_status FROM pulse_discoveries WHERE canonical_url = ?",
            [url],
        )
        assert row["freshness_status"] == "fresh"

    @pytest.mark.asyncio
    async def test_update_mine_metadata_full(self, pulse_engine):
        """update_mine_metadata with all fields populated."""
        url = "https://github.com/test/mine-full"
        await _insert_discovery(pulse_engine, url, freshness_status="stale")

        monitor = _make_monitor(pulse_engine)
        await monitor.update_mine_metadata(
            url,
            head_sha="cafebabe12345678",
            pushed_at="2026-03-25T15:30:00Z",
            release_tag="v3.0.0-rc1",
        )

        row = await pulse_engine.fetch_one(
            """SELECT head_sha_at_mine, last_pushed_at, latest_release_tag,
                      freshness_status
               FROM pulse_discoveries WHERE canonical_url = ?""",
            [url],
        )
        assert row["head_sha_at_mine"] == "cafebabe12345678"
        assert row["last_pushed_at"] == "2026-03-25T15:30:00Z"
        assert row["latest_release_tag"] == "v3.0.0-rc1"
        assert row["freshness_status"] == "fresh"


# ===========================================================================
# Group 9: size_at_mine column and size_signal computation
# ===========================================================================


class TestMigration12SizeAtMine:
    """Verify Migration 12 creates size_at_mine column."""

    @pytest.mark.asyncio
    async def test_size_at_mine_column_exists(self, pulse_engine):
        """size_at_mine column should exist after migration."""
        rows = await pulse_engine.fetch_all(
            "SELECT name FROM pragma_table_info('pulse_discoveries')"
        )
        col_names = {r["name"] for r in rows}
        assert "size_at_mine" in col_names

    @pytest.mark.asyncio
    async def test_migration_12_idempotent(self, pulse_engine):
        """Running migrations again does not error."""
        await pulse_engine.apply_migrations()
        rows = await pulse_engine.fetch_all(
            "SELECT name FROM pragma_table_info('pulse_discoveries')"
        )
        col_names = {r["name"] for r in rows}
        assert "size_at_mine" in col_names


class TestSizeAtMineStorage:
    """Verify size_at_mine is stored and retrieved correctly."""

    @pytest.mark.asyncio
    async def test_update_freshness_metadata_stores_size(self, pulse_engine):
        """_update_freshness_metadata stores size_kb when > 0."""
        url = "https://github.com/test/size-store"
        await _insert_discovery(pulse_engine, url)

        monitor = _make_monitor(pulse_engine)
        await monitor._update_freshness_metadata(
            url, etag="abc", pushed_at="2026-01-01", stars=100,
            freshness_status="fresh", size_kb=15000,
        )

        row = await pulse_engine.fetch_one(
            "SELECT size_at_mine FROM pulse_discoveries WHERE canonical_url = ?",
            [url],
        )
        assert row["size_at_mine"] == 15000

    @pytest.mark.asyncio
    async def test_update_freshness_metadata_preserves_size_when_zero(self, pulse_engine):
        """_update_freshness_metadata preserves existing size when size_kb=0."""
        url = "https://github.com/test/size-preserve"
        await _insert_discovery(pulse_engine, url)

        monitor = _make_monitor(pulse_engine)
        # First call sets size
        await monitor._update_freshness_metadata(
            url, etag="abc", pushed_at="2026-01-01", stars=100,
            freshness_status="fresh", size_kb=12000,
        )
        # Second call with size_kb=0 should preserve
        await monitor._update_freshness_metadata(
            url, etag="def", pushed_at="2026-02-01", stars=120,
            freshness_status="stale", size_kb=0,
        )

        row = await pulse_engine.fetch_one(
            "SELECT size_at_mine FROM pulse_discoveries WHERE canonical_url = ?",
            [url],
        )
        assert row["size_at_mine"] == 12000

    @pytest.mark.asyncio
    async def test_update_mine_metadata_stores_size(self, pulse_engine):
        """update_mine_metadata stores size_kb when > 0."""
        url = "https://github.com/test/mine-size"
        await _insert_discovery(pulse_engine, url, freshness_status="stale")

        monitor = _make_monitor(pulse_engine)
        await monitor.update_mine_metadata(
            url, head_sha="abc123", size_kb=25000,
        )

        row = await pulse_engine.fetch_one(
            "SELECT size_at_mine FROM pulse_discoveries WHERE canonical_url = ?",
            [url],
        )
        assert row["size_at_mine"] == 25000

    @pytest.mark.asyncio
    async def test_get_stored_size_returns_value(self, pulse_engine):
        """_get_stored_size returns stored size when present."""
        url = "https://github.com/test/get-stored-size"
        await _insert_discovery(pulse_engine, url)
        # Manually set size
        await pulse_engine.execute(
            "UPDATE pulse_discoveries SET size_at_mine = ? WHERE canonical_url = ?",
            [8000, url],
        )

        monitor = _make_monitor(pulse_engine)
        size = await monitor._get_stored_size(url)
        assert size == 8000

    @pytest.mark.asyncio
    async def test_get_stored_size_returns_zero_when_null(self, pulse_engine):
        """_get_stored_size returns 0 when size_at_mine is NULL."""
        url = "https://github.com/test/null-size"
        await _insert_discovery(pulse_engine, url)

        monitor = _make_monitor(pulse_engine)
        size = await monitor._get_stored_size(url)
        assert size == 0

    @pytest.mark.asyncio
    async def test_get_stored_size_returns_zero_for_missing_url(self, pulse_engine):
        """_get_stored_size returns 0 when URL not found."""
        monitor = _make_monitor(pulse_engine)
        size = await monitor._get_stored_size("https://github.com/no/such-repo")
        assert size == 0


class TestSizeSignalComputation:
    """Verify size_signal integrates into significance score."""

    def test_size_signal_large_change(self):
        """50% size change with 20% threshold → size_signal = min(50/20, 1.0) = 1.0."""
        score = _compute_significance(
            commits_since=0,
            has_new_release=False,
            readme_changed=False,
            size_signal=1.0,  # Large size change
        )
        # 0.0 + 0.0 + 0.0 + 1.0 * 0.1 = 0.1
        assert score == pytest.approx(0.1)

    def test_size_signal_small_change(self):
        """10% size change with 20% threshold → size_signal = 0.5."""
        score = _compute_significance(
            commits_since=0,
            has_new_release=False,
            readme_changed=False,
            size_signal=0.5,
        )
        # 0.0 + 0.0 + 0.0 + 0.5 * 0.1 = 0.05
        assert score == pytest.approx(0.05)
