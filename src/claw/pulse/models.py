"""Data models for CAM-PULSE."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class PulseDiscovery:
    """A single GitHub repo discovered via X search."""
    github_url: str
    canonical_url: str
    x_post_url: str = ""
    x_post_text: str = ""
    x_author_handle: str = ""
    keywords_matched: list[str] = field(default_factory=list)
    novelty_score: float = 0.0
    scan_id: str = ""


@dataclass
class PulseScanResult:
    """Aggregated result from a single scan session."""
    scan_id: str
    discoveries: list[PulseDiscovery] = field(default_factory=list)
    novel_count: int = 0
    assimilated_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    cost_usd: float = 0.0
    tokens_used: int = 0
    keywords_used: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class AssimilationResult:
    """Result of assimilating a single discovered repo."""
    discovery: PulseDiscovery
    success: bool = False
    methodology_ids: list[str] = field(default_factory=list)
    findings_count: int = 0
    head_sha: str = ""
    error: Optional[str] = None

@dataclass
class Phase1Result:
    """Result of Phase 1 metadata check (cheap GitHub/HF API call)."""
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
    """Result of full freshness check (Phase 1 + Phase 2 significance scoring)."""
    canonical_url: str
    phase1: Phase1Result | None = None
    significance_score: float = 0.0
    needs_refresh: bool = False
    commits_since_mine: int = 0
    has_new_release: bool = False
    readme_changed: bool = False
    error: str | None = None


@dataclass
class RefreshResult:
    """Result of re-mining a stale repo."""
    canonical_url: str
    success: bool = False
    new_methodology_ids: list[str] = field(default_factory=list)
    retired_methodology_ids: list[str] = field(default_factory=list)
    kept_methodology_ids: list[str] = field(default_factory=list)
    head_sha: str = ""
    error: str | None = None
