"""Data models for the advisor."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(slots=True)
class KnowledgeItem:
    item_id: str
    title: str
    text: str
    modality: str
    source: str
    source_repo: str
    tags: list[str] = field(default_factory=list)
    task_type: str | None = None
    potential_score: float = 0.0
    novelty_score: float = 0.0


@dataclass(slots=True)
class RepoSignal:
    signal_id: str
    category: str
    title: str
    why_now: str
    evidence: list[str]
    improvement: str
    first_step: str
    difficulty: str
    payoff: str
    query_terms: list[str]


@dataclass(slots=True)
class KnowledgeMatch:
    item_id: str
    title: str
    source_repo: str
    score: float
    rationale: str


@dataclass(slots=True)
class Recommendation:
    title: str
    category: str
    why_now: str
    evidence: list[str]
    recommended_change: str
    first_step: str
    difficulty: str
    payoff: str
    confidence: float
    provenance: list[KnowledgeMatch]


@dataclass(slots=True)
class RepoProfile:
    repo_path: Path
    file_count: int
    python_files: list[Path]
    docs_files: list[Path]
    test_files: list[Path]
    ci_files: list[Path]
    has_pyproject: bool
    has_package_json: bool
    has_readme: bool
    has_docs_dir: bool
    has_type_hints: bool
    risky_patterns: list[str]
    top_files: list[str]
