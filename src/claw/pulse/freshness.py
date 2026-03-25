"""Repo Freshness Monitor for CAM-PULSE.

Detects when previously-mined repos have significant updates and
scores the significance to decide whether re-mining is warranted.

Two-phase architecture:
  Phase 1 — Cheap metadata check (1 API call, 0 if ETag cached)
  Phase 2 — Significance scoring (2-3 calls, only for changed repos)

Supports both GitHub and Hugging Face repos.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import UTC, datetime
from typing import Optional

import httpx

from claw.core.config import ClawConfig
from claw.db.engine import DatabaseEngine
from claw.pulse.models import FreshnessResult, Phase1Result

logger = logging.getLogger("claw.pulse.freshness")

GITHUB_API_BASE = "https://api.github.com"


class FreshnessMonitor:
    """Monitors tracked repos for significant changes."""

    def __init__(self, engine: DatabaseEngine, config: ClawConfig):
        self.engine = engine
        self.config = config
        self._fc = config.pulse.freshness
        self._token = os.getenv(self._fc.github_token_env, "")
        self._headers: dict[str, str] = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            self._headers["Authorization"] = f"Bearer {self._token}"

    @staticmethod
    def extract_owner_repo(canonical_url: str) -> str | None:
        """Parse 'https://github.com/owner/repo' -> 'owner/repo'.

        Handles trailing slashes, .git suffix, mixed case.
        Returns None if URL doesn't match expected pattern.
        """
        url = canonical_url.strip().rstrip("/")
        if url.endswith(".git"):
            url = url[:-4]

        prefixes = ["https://github.com/", "http://github.com/"]
        for prefix in prefixes:
            if url.lower().startswith(prefix.lower()):
                path = url[len(prefix):]
                parts = path.split("/")
                if len(parts) >= 2:
                    return f"{parts[0]}/{parts[1]}"
        return None

    async def check_all(self) -> list[FreshnessResult]:
        """Check all assimilated discoveries for staleness.

        Queries pulse_discoveries with status='assimilated', runs Phase 1 + Phase 2
        on each, respecting rate limits. Handles both GitHub and HF repos.
        """
        results: list[FreshnessResult] = []

        # ----- GitHub repos -----
        rows = await self.engine.fetch_all(
            """SELECT canonical_url, etag, last_pushed_at, head_sha_at_mine,
                      stars_at_mine, latest_release_tag, freshness_status
               FROM pulse_discoveries
               WHERE status = 'assimilated'
                 AND (source_kind = 'github' OR source_kind IS NULL)
               ORDER BY last_checked_at ASC NULLS FIRST
               LIMIT ?""",
            [self._fc.max_repos_per_check],
        )

        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            for row in rows:
                canonical_url = row["canonical_url"]
                stored_etag = row["etag"] or ""
                stored_pushed_at = row["last_pushed_at"] or ""
                stored_sha = row["head_sha_at_mine"] or ""
                stored_stars = row["stars_at_mine"] or 0
                stored_release = row["latest_release_tag"] or ""

                # Phase 1: metadata check
                p1 = await self._phase1_metadata_check(
                    client, canonical_url, stored_etag
                )

                if p1.error:
                    results.append(FreshnessResult(
                        canonical_url=canonical_url,
                        phase1=p1,
                        error=p1.error,
                    ))
                    await self._update_checked(canonical_url)
                    continue

                # Rate limit check
                if 0 < p1.rate_limit_remaining < self._fc.rate_limit_buffer:
                    logger.warning(
                        "Rate limit approaching (%d remaining), stopping checks",
                        p1.rate_limit_remaining,
                    )
                    break

                if not p1.changed:
                    # 304 Not Modified or pushed_at unchanged
                    results.append(FreshnessResult(
                        canonical_url=canonical_url,
                        phase1=p1,
                        significance_score=0.0,
                        needs_refresh=False,
                    ))
                    await self._update_checked(canonical_url, etag=p1.etag)
                    continue

                # Phase 2: significance scoring
                fr = await self._phase2_significance(
                    client, canonical_url, p1,
                    stored_sha=stored_sha,
                    stored_pushed_at=stored_pushed_at,
                    stored_stars=stored_stars,
                    stored_release=stored_release,
                )

                # Update metadata
                await self._update_freshness_metadata(
                    canonical_url,
                    etag=p1.etag,
                    pushed_at=p1.pushed_at,
                    stars=p1.stars,
                    freshness_status="stale" if fr.needs_refresh else "fresh",
                    size_kb=p1.size_kb,
                )

                results.append(fr)

        # ----- HF repos -----
        hf_rows = await self.engine.fetch_all(
            """SELECT canonical_url, etag, head_sha_at_mine, freshness_status
               FROM pulse_discoveries
               WHERE status = 'assimilated' AND source_kind = 'hf_repo'
               ORDER BY last_checked_at ASC NULLS FIRST
               LIMIT ?""",
            [self._fc.max_repos_per_check],
        )

        for row in hf_rows:
            canonical_url = row["canonical_url"]
            stored_sha = row["head_sha_at_mine"] or row["etag"] or ""

            p1 = await self._phase1_hf_check(canonical_url, stored_sha)

            if p1.error:
                results.append(FreshnessResult(
                    canonical_url=canonical_url,
                    phase1=p1,
                    error=p1.error,
                ))
                await self._update_checked(canonical_url)
                continue

            if not p1.changed:
                results.append(FreshnessResult(
                    canonical_url=canonical_url,
                    phase1=p1,
                    significance_score=0.0,
                    needs_refresh=False,
                ))
                await self._update_checked(canonical_url, etag=p1.etag)
                continue

            # HF repos: any SHA change is significant (no commit counting)
            results.append(FreshnessResult(
                canonical_url=canonical_url,
                phase1=p1,
                significance_score=1.0,
                needs_refresh=True,
            ))
            await self._update_freshness_metadata(
                canonical_url,
                etag=p1.etag,
                pushed_at=p1.pushed_at,
                stars=p1.stars,
                freshness_status="stale",
                size_kb=p1.size_kb,
            )

        return results

    async def _phase1_metadata_check(
        self,
        client: httpx.AsyncClient,
        canonical_url: str,
        stored_etag: str,
    ) -> Phase1Result:
        """Phase 1: cheap metadata check via GitHub REST API.

        Uses If-None-Match/ETag for zero-cost checks on unchanged repos.
        """
        owner_repo = self.extract_owner_repo(canonical_url)
        if not owner_repo:
            return Phase1Result(
                canonical_url=canonical_url,
                error=f"Cannot parse owner/repo from: {canonical_url}",
            )

        headers = dict(self._headers)
        if stored_etag:
            headers["If-None-Match"] = stored_etag

        url = f"{GITHUB_API_BASE}/repos/{owner_repo}"

        try:
            resp = await client.get(url, headers=headers)

            rate_remaining = int(resp.headers.get("X-RateLimit-Remaining", -1))

            if resp.status_code == 304:
                # Not Modified -- repo hasn't changed
                return Phase1Result(
                    canonical_url=canonical_url,
                    changed=False,
                    etag=stored_etag,
                    rate_limit_remaining=rate_remaining,
                )

            if resp.status_code == 200:
                data = resp.json()
                new_etag = resp.headers.get("ETag", "")
                pushed_at = data.get("pushed_at", "")
                stars = data.get("stargazers_count", 0)
                size_kb = data.get("size", 0)

                return Phase1Result(
                    canonical_url=canonical_url,
                    changed=True,  # 200 means metadata changed; caller compares pushed_at
                    pushed_at=pushed_at,
                    etag=new_etag,
                    stars=stars,
                    size_kb=size_kb,
                    rate_limit_remaining=rate_remaining,
                )

            # Error response
            return Phase1Result(
                canonical_url=canonical_url,
                error=f"GitHub API returned {resp.status_code}: {resp.text[:200]}",
                rate_limit_remaining=rate_remaining,
            )

        except httpx.HTTPError as e:
            return Phase1Result(
                canonical_url=canonical_url,
                error=f"HTTP error: {e}",
            )

    async def _phase1_hf_check(
        self, canonical_url: str, stored_sha: str
    ) -> Phase1Result:
        """Phase 1 check for HF repos via huggingface_hub API."""
        try:
            from huggingface_hub import HfApi

            # Extract repo_id from URL like https://huggingface.co/owner/repo
            repo_id = canonical_url.replace("https://huggingface.co/", "").strip("/")
            if not repo_id or "/" not in repo_id:
                return Phase1Result(
                    canonical_url=canonical_url,
                    error=f"Cannot parse HF repo ID from: {canonical_url}",
                )

            api = HfApi()
            loop = asyncio.get_running_loop()
            info = await loop.run_in_executor(None, lambda: api.repo_info(repo_id))

            current_sha = getattr(info, "sha", "") or ""
            last_modified = getattr(info, "last_modified", None)
            pushed_at = last_modified.isoformat() if last_modified else ""

            changed = current_sha != stored_sha if stored_sha else False

            return Phase1Result(
                canonical_url=canonical_url,
                changed=changed,
                pushed_at=pushed_at,
                etag=current_sha,  # Use SHA as etag equivalent
                stars=getattr(info, "likes", 0) or 0,
            )

        except ImportError:
            return Phase1Result(
                canonical_url=canonical_url,
                error="huggingface_hub not installed",
            )
        except Exception as e:
            return Phase1Result(
                canonical_url=canonical_url,
                error=f"HF API error: {e}",
            )

    async def _phase2_significance(
        self,
        client: httpx.AsyncClient,
        canonical_url: str,
        p1: Phase1Result,
        stored_sha: str,
        stored_pushed_at: str,
        stored_stars: int,
        stored_release: str,
    ) -> FreshnessResult:
        """Phase 2: compute significance score for changed repos."""
        owner_repo = self.extract_owner_repo(canonical_url)
        if not owner_repo:
            return FreshnessResult(
                canonical_url=canonical_url,
                phase1=p1,
                error=f"Cannot parse owner/repo: {canonical_url}",
            )

        # If pushed_at hasn't actually changed, not significant
        if p1.pushed_at == stored_pushed_at:
            return FreshnessResult(
                canonical_url=canonical_url,
                phase1=p1,
                significance_score=0.0,
                needs_refresh=False,
            )

        commits_since = 0
        has_new_release = False
        readme_changed = False

        # Signal 1: Commit count since last mine
        if stored_sha:
            commits_since = await self._get_commits_since(
                client, owner_repo, stored_sha
            )

        # Signal 2: New release
        has_new_release = await self._check_new_release(
            client, owner_repo, stored_release
        )

        # Signal 3: README changed
        if stored_pushed_at:
            readme_changed = await self._check_readme_changed(
                client, owner_repo, stored_pushed_at
            )

        # Signal 4: Size delta (requires size_at_mine in pulse_discoveries)
        size_signal = 0.0
        stored_size = await self._get_stored_size(canonical_url)
        if stored_size and stored_size > 0 and p1.size_kb > 0:
            size_pct = self._fc.significance_size_delta_pct or 20
            delta_pct = abs(p1.size_kb - stored_size) * 100.0 / stored_size
            size_signal = min(delta_pct / max(size_pct, 1), 1.0)

        # Compute significance score
        commit_threshold = self._fc.significance_commit_threshold
        commit_signal = min(commits_since / max(commit_threshold, 1), 1.0)
        release_signal = 1.0 if has_new_release else 0.0
        readme_signal = 1.0 if readme_changed else 0.0

        significance = (
            commit_signal * 0.3
            + release_signal * self._fc.significance_release_weight
            + readme_signal * self._fc.significance_readme_weight
            + size_signal * 0.1
        )

        needs_refresh = significance >= self._fc.significance_threshold

        logger.info(
            "Freshness %s: significance=%.2f (commits=%d, release=%s, readme=%s) -> %s",
            canonical_url, significance, commits_since,
            has_new_release, readme_changed,
            "REFRESH" if needs_refresh else "skip",
        )

        return FreshnessResult(
            canonical_url=canonical_url,
            phase1=p1,
            significance_score=round(significance, 3),
            needs_refresh=needs_refresh,
            commits_since_mine=commits_since,
            has_new_release=has_new_release,
            readme_changed=readme_changed,
        )

    async def _get_commits_since(
        self, client: httpx.AsyncClient, owner_repo: str, base_sha: str
    ) -> int:
        """Get commit count since a given SHA via compare endpoint."""
        url = f"{GITHUB_API_BASE}/repos/{owner_repo}/compare/{base_sha}...HEAD"
        try:
            resp = await client.get(url, headers=self._headers)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("ahead_by", 0)
            elif resp.status_code == 404:
                # SHA no longer exists (force push, rebased, etc.)
                logger.warning("Base SHA %s not found for %s", base_sha, owner_repo)
                return 999  # Treat as very stale
        except httpx.HTTPError as e:
            logger.warning("Compare failed for %s: %s", owner_repo, e)
        return 0

    async def _check_new_release(
        self, client: httpx.AsyncClient, owner_repo: str, stored_tag: str
    ) -> bool:
        """Check if there's a newer release than the stored tag."""
        url = f"{GITHUB_API_BASE}/repos/{owner_repo}/releases/latest"
        try:
            resp = await client.get(url, headers=self._headers)
            if resp.status_code == 200:
                data = resp.json()
                latest_tag = data.get("tag_name", "")
                return latest_tag != stored_tag and latest_tag != ""
            # 404 = no releases, that's fine
        except httpx.HTTPError as e:
            logger.warning("Release check failed for %s: %s", owner_repo, e)
        return False

    async def _check_readme_changed(
        self, client: httpx.AsyncClient, owner_repo: str, since: str
    ) -> bool:
        """Check if README.md was modified since a given date."""
        url = f"{GITHUB_API_BASE}/repos/{owner_repo}/commits"
        params = {"path": "README.md", "since": since, "per_page": "1"}
        try:
            resp = await client.get(url, headers=self._headers, params=params)
            if resp.status_code == 200:
                commits = resp.json()
                return len(commits) > 0
        except httpx.HTTPError as e:
            logger.warning("README check failed for %s: %s", owner_repo, e)
        return False

    # ----- Seed existing repos -----

    async def seed_existing_repos(self) -> int:
        """Populate freshness metadata for assimilated repos with NULL values.

        Uses GitHub API to fetch current metadata for repos that were assimilated
        before the freshness system existed.
        """
        rows = await self.engine.fetch_all(
            """SELECT canonical_url FROM pulse_discoveries
               WHERE status = 'assimilated'
                 AND (head_sha_at_mine IS NULL OR head_sha_at_mine = '')
                 AND (source_kind = 'github' OR source_kind IS NULL)
               LIMIT ?""",
            [self._fc.max_repos_per_check],
        )

        if not rows:
            return 0

        seeded = 0
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            for row in rows:
                canonical_url = row["canonical_url"]
                owner_repo = self.extract_owner_repo(canonical_url)
                if not owner_repo:
                    continue

                url = f"{GITHUB_API_BASE}/repos/{owner_repo}"
                try:
                    resp = await client.get(url, headers=self._headers)
                    if resp.status_code == 200:
                        data = resp.json()
                        etag = resp.headers.get("ETag", "")
                        pushed_at = data.get("pushed_at", "")
                        stars = data.get("stargazers_count", 0)
                        default_branch = data.get("default_branch", "main")

                        # Get HEAD SHA via refs endpoint
                        head_sha = ""
                        ref_url = f"{GITHUB_API_BASE}/repos/{owner_repo}/git/ref/heads/{default_branch}"
                        ref_resp = await client.get(ref_url, headers=self._headers)
                        if ref_resp.status_code == 200:
                            ref_data = ref_resp.json()
                            head_sha = ref_data.get("object", {}).get("sha", "")

                        # Get latest release tag
                        release_tag = ""
                        rel_url = f"{GITHUB_API_BASE}/repos/{owner_repo}/releases/latest"
                        rel_resp = await client.get(rel_url, headers=self._headers)
                        if rel_resp.status_code == 200:
                            release_tag = rel_resp.json().get("tag_name", "")

                        size_kb = data.get("size", 0)
                        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                        await self.engine.execute(
                            """UPDATE pulse_discoveries
                               SET head_sha_at_mine = ?,
                                   last_pushed_at = ?,
                                   etag = ?,
                                   stars_at_mine = ?,
                                   latest_release_tag = ?,
                                   last_checked_at = ?,
                                   freshness_status = 'fresh',
                                   source_kind = 'github',
                                   size_at_mine = ?
                               WHERE canonical_url = ?""",
                            [head_sha, pushed_at, etag, stars, release_tag, now, size_kb, canonical_url],
                        )
                        seeded += 1

                        # Rate limit check
                        remaining = int(resp.headers.get("X-RateLimit-Remaining", -1))
                        if 0 < remaining < self._fc.rate_limit_buffer:
                            logger.warning("Rate limit approaching, stopping seed at %d repos", seeded)
                            break

                except Exception as e:
                    logger.warning("Failed to seed %s: %s", canonical_url, e)
                    continue

        return seeded

    # ----- Database operations -----

    async def _update_checked(
        self, canonical_url: str, etag: str | None = None
    ) -> None:
        """Update last_checked_at timestamp (and optionally etag)."""
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if etag:
            await self.engine.execute(
                "UPDATE pulse_discoveries SET last_checked_at = ?, etag = ? WHERE canonical_url = ?",
                [now, etag, canonical_url],
            )
        else:
            await self.engine.execute(
                "UPDATE pulse_discoveries SET last_checked_at = ? WHERE canonical_url = ?",
                [now, canonical_url],
            )

    async def _update_freshness_metadata(
        self,
        canonical_url: str,
        etag: str = "",
        pushed_at: str = "",
        stars: int = 0,
        freshness_status: str = "unknown",
        size_kb: int = 0,
    ) -> None:
        """Update all freshness metadata columns after a check."""
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        await self.engine.execute(
            """UPDATE pulse_discoveries
               SET last_checked_at = ?,
                   etag = ?,
                   last_pushed_at = ?,
                   stars_at_mine = ?,
                   freshness_status = ?,
                   size_at_mine = CASE WHEN ? > 0 THEN ? ELSE size_at_mine END
               WHERE canonical_url = ?""",
            [now, etag, pushed_at, stars, freshness_status, size_kb, size_kb, canonical_url],
        )

    async def retire_stale_methodologies(
        self,
        canonical_url: str,
        new_methodology_ids: list[str],
    ) -> tuple[list[str], list[str]]:
        """Transition old methodologies from a re-mined repo to 'declining'.

        Finds methodologies previously mined from this repo (stored in
        pulse_discoveries.methodology_ids), compares against the new set,
        and transitions old ones that have no counterpart in the new set.

        Args:
            canonical_url: The repo URL that was re-mined.
            new_methodology_ids: IDs of methodologies produced by the re-mine.

        Returns:
            Tuple of (retired_ids, kept_ids).
        """
        import json as _json

        # Find old methodology IDs from the discovery record
        row = await self.engine.fetch_one(
            "SELECT methodology_ids FROM pulse_discoveries WHERE canonical_url = ?",
            [canonical_url],
        )
        if not row or not row["methodology_ids"]:
            return [], []

        try:
            old_ids = _json.loads(row["methodology_ids"])
        except (_json.JSONDecodeError, TypeError):
            return [], []

        if not isinstance(old_ids, list):
            return [], []

        new_set = set(new_methodology_ids)
        retired: list[str] = []
        kept: list[str] = []

        for old_id in old_ids:
            if old_id in new_set:
                kept.append(old_id)
                continue

            # Transition to declining with superseded_by pointing to first new methodology
            superseded_by = new_methodology_ids[0] if new_methodology_ids else None
            try:
                await self.engine.execute(
                    "UPDATE methodologies SET lifecycle_state = 'declining', superseded_by = ? WHERE id = ?",
                    [superseded_by, old_id],
                )
                retired.append(old_id)
                logger.info(
                    "Retired methodology %s (superseded_by=%s) from %s",
                    old_id, superseded_by, canonical_url,
                )
            except Exception as e:
                logger.warning("Failed to retire methodology %s: %s", old_id, e)

        return retired, kept

    async def preview_retirement(
        self,
        canonical_url: str,
        new_methodology_ids: list[str],
    ) -> tuple[list[str], list[str]]:
        """Preview which methodologies WOULD be retired (read-only, no DB writes).

        Same logic as retire_stale_methodologies() but only reads.
        Returns (would_retire_ids, would_keep_ids).
        """
        import json as _json

        row = await self.engine.fetch_one(
            "SELECT methodology_ids FROM pulse_discoveries WHERE canonical_url = ?",
            [canonical_url],
        )
        if not row or not row["methodology_ids"]:
            return [], []

        try:
            old_ids = _json.loads(row["methodology_ids"])
        except (_json.JSONDecodeError, TypeError):
            return [], []

        if not isinstance(old_ids, list):
            return [], []

        new_set = set(new_methodology_ids)
        would_retire: list[str] = []
        would_keep: list[str] = []

        for old_id in old_ids:
            if old_id in new_set:
                would_keep.append(old_id)
            else:
                would_retire.append(old_id)

        return would_retire, would_keep

    async def _get_stored_size(self, canonical_url: str) -> int:
        """Get the stored size_at_mine for a repo, or 0 if not set."""
        row = await self.engine.fetch_one(
            "SELECT size_at_mine FROM pulse_discoveries WHERE canonical_url = ?",
            [canonical_url],
        )
        if row and row["size_at_mine"]:
            return int(row["size_at_mine"])
        return 0

    async def update_mine_metadata(
        self,
        canonical_url: str,
        head_sha: str,
        pushed_at: str = "",
        release_tag: str = "",
        size_kb: int = 0,
    ) -> None:
        """Update metadata after a successful re-mine."""
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        await self.engine.execute(
            """UPDATE pulse_discoveries
               SET head_sha_at_mine = ?,
                   last_pushed_at = ?,
                   latest_release_tag = ?,
                   last_checked_at = ?,
                   freshness_status = 'fresh',
                   size_at_mine = CASE WHEN ? > 0 THEN ? ELSE size_at_mine END
               WHERE canonical_url = ?""",
            [head_sha, pushed_at, release_tag, now, size_kb, size_kb, canonical_url],
        )
