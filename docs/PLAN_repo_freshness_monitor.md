# Repo Freshness Monitor — Detect & Re-mine Significantly Changed GitHub Repos

**Date:** 2026-03-25
**Status:** Planned (not yet implemented)
**Branch:** main @ c069595

---

## Context

CAM mines a GitHub repo once and stores methodologies forever. If that repo ships a major rewrite, new architecture, or breaking API changes, CAM's knowledge becomes stale — but it has no way to know. The current `--force` flag on `cam pulse ingest` is manual-only.

We need an efficient, automated way to:
1. Detect when previously-mined repos have significant updates (not every trivial push)
2. Re-mine only those repos, retiring stale methodologies and adding new ones
3. Do this cheaply — GitHub's conditional requests (ETag/304) cost 0 rate-limit points for unchanged repos

## Current State (Gaps)

| Aspect | Current | Gap |
|--------|---------|-----|
| Repo tracking | URL + status + discovered_at | No last-updated timestamp |
| Change detection | None | No commit SHA, stars, or push-date tracking |
| Refresh logic | Manual `--force` flag only | No automatic re-mine schedule |
| GitHub metadata | None | No API integration for repo state |
| Methodology staleness | Lifecycle state only | No "invalidate if source repo changed" |

## Design: Two-Phase Architecture

### Phase 1 — Cheap Metadata Check (1 API call per repo, 0 if cached)
- `GET /repos/{owner}/{repo}` with `If-None-Match: {stored_etag}`
- 304 Not Modified → repo unchanged, update `last_checked_at`, done
- 200 → compare `pushed_at` against stored value
- If `pushed_at` unchanged → done (metadata-only change like description edit)
- If `pushed_at` changed → proceed to Phase 2

### Phase 2 — Significance Scoring (2-3 calls, only for changed repos)
- Commit count since last mine: `GET /repos/{owner}/{repo}/compare/{stored_sha}...HEAD` → `ahead_by`
- Release check: `GET /repos/{owner}/{repo}/releases/latest` → compare tag
- README change: `GET /repos/{owner}/{repo}/commits?path=README.md&since={last_pushed_at}&per_page=1`
- Size delta from Phase 1 metadata

**Significance score** (0.0–1.0):
```
commit_signal = min(commits_since_mine / commit_threshold, 1.0)
release_signal = 1.0 if new_release else 0.0
readme_signal  = 1.0 if readme_changed else 0.0
size_signal    = min(abs(size_delta) / size_threshold, 1.0)

significance = commit_signal * 0.3 + release_signal * 0.4 + readme_signal * 0.2 + size_signal * 0.1
```

Only repos with `significance >= threshold` (default 0.4) trigger re-mine.

### Re-mine Flow
1. Mark discovery as `freshness_status = 'refreshing'`
2. Reuse existing `PulseAssimilator.assimilate()` (clone → mine → store)
3. Capture HEAD SHA after clone via `git rev-parse HEAD`
4. After mining, compare new methodologies against old ones from same repo:
   - Old with no new counterpart → transition lifecycle to `declining`
   - Old with close new match → mark `superseded_by`, transition to `declining`
   - New genuinely novel patterns → stored normally (existing dedup handles near-duplicates)
5. Update freshness metadata: `head_sha_at_mine`, `last_pushed_at`, `etag`, `stars_at_mine`, `latest_release_tag`

### Rate Limit Strategy
- **Unauthenticated**: 60 req/hr — check ~50 repos per run (Phase 1 costs 0 for cached)
- **Authenticated** (`GITHUB_TOKEN`): 5,000 req/hr — check hundreds
- `rate_limit_buffer` config: stop when `X-RateLimit-Remaining < buffer`

## Files to Modify

### 1. `src/claw/core/config.py` — Add FreshnessConfig
Add after `PulseProfileConfig` (line 214), wire into `PulseConfig` (line 238):
```python
class FreshnessConfig(BaseModel):
    check_interval_hours: int = 12
    significance_commit_threshold: int = 20
    significance_release_weight: float = 0.4
    significance_readme_weight: float = 0.2
    significance_size_delta_pct: int = 20
    significance_threshold: float = 0.4
    github_token_env: str = "GITHUB_TOKEN"
    max_repos_per_check: int = 50
    rate_limit_buffer: int = 10
```
Add `freshness: FreshnessConfig = Field(default_factory=FreshnessConfig)` to `PulseConfig`.

### 2. `claw.toml` — Add `[pulse.freshness]` section
Insert after existing `[pulse.profile]` block (~line 211):
```toml
[pulse.freshness]
check_interval_hours = 12
significance_commit_threshold = 20
significance_threshold = 0.4
github_token_env = "GITHUB_TOKEN"
max_repos_per_check = 50
```

### 3. `src/claw/db/engine.py` — Migration 11: freshness columns
Add after Migration 10 (line 349). Pattern: check column existence via `pragma_table_info`, then `ALTER TABLE ADD COLUMN`:
- `last_checked_at TEXT`
- `last_pushed_at TEXT`
- `head_sha_at_mine TEXT`
- `etag TEXT`
- `stars_at_mine INTEGER`
- `latest_release_tag TEXT`
- `freshness_status TEXT DEFAULT 'unknown'` (separate from existing `status` to avoid CHECK constraint migration)

### 4. `src/claw/db/schema.sql` — Update CREATE TABLE
Add the 7 new columns to `pulse_discoveries` definition for fresh databases.

### 5. `src/claw/pulse/models.py` — Add freshness dataclasses
```python
@dataclass
class Phase1Result:
    canonical_url: str
    changed: bool = False
    pushed_at: str = ""
    etag: str = ""
    stars: int = 0
    size_kb: int = 0
    rate_limit_remaining: int = -1
    error: str | None = None

@dataclass
class FreshnessResult:
    canonical_url: str
    phase1: Phase1Result
    significance_score: float = 0.0
    needs_refresh: bool = False
    commits_since_mine: int = 0
    has_new_release: bool = False
    readme_changed: bool = False
    error: str | None = None

@dataclass
class RefreshResult:
    canonical_url: str
    success: bool = False
    new_methodology_ids: list[str] = field(default_factory=list)
    retired_methodology_ids: list[str] = field(default_factory=list)
    kept_methodology_ids: list[str] = field(default_factory=list)
    error: str | None = None
```

### 6. `src/claw/pulse/freshness.py` — NEW: Core module
**`FreshnessMonitor` class** with:
- `__init__(engine, config)` — reads `GITHUB_TOKEN` from env, builds httpx client
- `check_all() -> list[FreshnessResult]` — queries assimilated discoveries, runs Phase 1 + Phase 2
- `_phase1_metadata_check(canonical_url, stored_etag) -> Phase1Result` — GitHub REST API with ETag
- `_phase2_significance_score(canonical_url, metadata) -> float` — commit/release/readme/size scoring
- `_extract_owner_repo(canonical_url) -> str` — parse `https://github.com/owner/repo` → `owner/repo`
- `_update_freshness_metadata(canonical_url, ...)` — SQL UPDATE
- `refresh_repo(canonical_url, assimilator) -> RefreshResult` — orchestrate re-mine + methodology lifecycle
- `_retire_stale_methodologies(canonical_url, new_ids)` — find old methodologies by `source_repos`, transition to declining

Uses `httpx.AsyncClient` (same pattern as `scout.py:26` and `interface.py:288`).

### 7. `src/claw/pulse/assimilator.py` — Add SHA capture hook
- Add `on_clone_ready: Callable[[Path], Awaitable[None]] | None = None` parameter to `assimilate()` (line 46)
- After `clone_path = await self._clone_repo(...)` (line 62), call `await on_clone_ready(clone_path)` if provided
- Add `_get_head_sha(clone_path) -> str` static helper (runs `git rev-parse HEAD`)

### 8. `src/claw/cli.py` — Add CLI commands
Add to `pulse_app` Typer group (after existing pulse commands, before `self_enhance_app`):

**`cam pulse freshness`** — Check all tracked repos for staleness
- Options: `--verbose`, `--auto-refresh` (check + re-mine stale repos)
- Display rich Table: URL | Last Checked | Days Stale | Significance | Status

**`cam pulse refresh [URL]`** — Re-mine a specific repo or all stale
- Options: `--all` (refresh all stale repos), `--force` (skip significance check)
- Reports: new/retired/kept methodology counts per repo

### 9. `tests/test_freshness.py` — NEW: Test suite
**Unit tests (no API calls)**:
- FreshnessConfig defaults and overrides
- `_extract_owner_repo()` parsing (standard URL, trailing slash, mixed case)
- Significance score computation with known inputs (pure math)
- Phase1Result/FreshnessResult/RefreshResult construction
- Migration 11 idempotency (run twice, no error)
- Freshness metadata SQL round-trip (write → read → verify)

**Integration tests (marked `@pytest.mark.skipif(not GITHUB_TOKEN)`):**
- Phase 1 check against a known public repo (e.g., `pallets/flask`)
- ETag caching: second call returns 304
- Commit comparison for known SHA range

**Methodology lifecycle tests (in-memory DB):**
- Insert methodologies with `source_repos` containing test URL
- Run refresh, verify old methodologies transition to `declining`
- Verify `superseded_by` set correctly

Target: ≥20 tests covering all code paths.

## Implementation Order
1. Config (config.py + claw.toml)
2. Models (pulse/models.py)
3. Schema migration (engine.py + schema.sql)
4. Core module (pulse/freshness.py)
5. Assimilator hook (assimilator.py)
6. CLI commands (cli.py)
7. Tests (test_freshness.py)
8. Validate: `pytest tests/ -q` — all 2028+ pass, no regressions

## Verification
1. `pytest tests/test_freshness.py -v` — all new tests pass
2. `pytest tests/ -q` — full suite, no regressions
3. `cam pulse freshness` with real tracked repos — shows freshness table
4. Manual: `cam pulse refresh https://github.com/some/repo` with a repo that has changed — verify re-mine produces updated methodologies
