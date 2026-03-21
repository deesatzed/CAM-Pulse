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
    error: Optional[str] = None
