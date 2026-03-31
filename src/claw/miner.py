"""Repo Mining for CLAW.

Scans local repositories, extracts patterns/features/ideas via LLM analysis,
stores findings in semantic memory, and generates enhancement tasks.

Usage:
    miner = RepoMiner(repository, llm_client, semantic_memory, config)
    report = await miner.mine_directory("/path/to/repos", project_id)
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import hashlib
import ast
import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from claw.core.config import ClawConfig
from claw.core.models import ActionTemplate, Methodology, Project, Task, TaskStatus
from claw.db.repository import Repository
from claw.llm.client import LLMClient, LLMMessage, LLMResponse
from claw.memory.semantic import SemanticMemory
from claw.memory.cag_staleness import maybe_mark_cag_stale

logger = logging.getLogger("claw.miner")

# Extensions to include when serializing a repo for mining.
_CODE_EXTENSIONS: set[str] = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".java",
    ".md", ".yaml", ".yml", ".toml", ".json", ".sql",
}

# Directories to skip during repo serialization.
_SKIP_DIRS: set[str] = {
    ".git", "node_modules", "__pycache__", ".venv",
    "venv", "dist", "build", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "egg-info",
    ".next", ".nuxt", "coverage", ".cache",
    "target",  # Rust/Java build output
}

# Maximum serialized repo size in bytes (900 KB).
_MAX_REPO_BYTES: int = 900 * 1024

# Maximum bytes to read per file for content hashing (4 KB).
_CONTENT_HASH_CHUNK: int = 4096

# Maximum files to hash during content-level dedup.
_CONTENT_HASH_MAX_FILES: int = 200


def _get_code_extensions(config: ClawConfig | None = None) -> set[str]:
    """Return merged code extensions: base defaults + config extras."""
    merged = set(_CODE_EXTENSIONS)
    if config and config.mining.extra_code_extensions:
        merged |= {ext if ext.startswith(".") else f".{ext}"
                    for ext in config.mining.extra_code_extensions}
    return merged


def _get_skip_dirs(config: ClawConfig | None = None) -> set[str]:
    """Return merged skip dirs: base defaults + config extras."""
    merged = set(_SKIP_DIRS)
    if config and config.mining.extra_skip_dirs:
        merged |= set(config.mining.extra_skip_dirs)
    return merged


def _load_mineignore(base_path: Path) -> list[str]:
    """Load .mineignore patterns from a directory.

    Supports gitignore-style patterns:
      - Lines starting with # are comments
      - Blank lines are ignored
      - Patterns are matched against relative paths
    """
    ignore_file = base_path / ".mineignore"
    if not ignore_file.is_file():
        return []
    try:
        patterns = []
        for line in ignore_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                patterns.append(line)
        return patterns
    except OSError:
        return []


def _is_mineignored(rel_path: str, patterns: list[str]) -> bool:
    """Check if a relative path matches any .mineignore pattern."""
    from fnmatch import fnmatch
    for pattern in patterns:
        # Strip trailing slash for directory patterns
        clean = pattern.rstrip("/")
        # Match against full relative path and individual path components
        if fnmatch(rel_path, pattern) or fnmatch(rel_path, f"**/{pattern}"):
            return True
        # Check if any path component matches exactly
        parts = rel_path.replace("\\", "/").split("/")
        if clean in parts:
            return True
        # Check fnmatch against each component
        for part in parts:
            if fnmatch(part, clean):
                return True
    return False

# Valid categories for findings.
_VALID_CATEGORIES: set[str] = {
    "architecture", "ai_integration", "memory", "code_quality",
    "cli_ux", "testing", "data_processing", "security",
    "algorithm", "cross_cutting", "design_patterns",
}

# Maximum findings per repo.
_MAX_FINDINGS_PER_REPO: int = 15

_CATEGORY_TRIGGER_MAP: dict[str, list[str]] = {
    "architecture": ["missing_packaging", "repo_structure", "entrypoint_clarity"],
    "ai_integration": ["model_integration", "agent_orchestration", "prompt_flow"],
    "memory": ["retrieval_quality", "knowledge_pack", "memory_schema"],
    "code_quality": ["quality_gate", "documentation_gap", "type_safety"],
    "cli_ux": ["cli_entrypoint", "operator_experience", "workflow_clarity"],
    "testing": ["missing_tests", "regression_risk", "verification_gap"],
    "data_processing": ["pipeline_gap", "ingestion_flow", "structured_data_flow"],
    "security": ["dynamic_execution_risk", "input_validation", "compliance_gap"],
    "algorithm": ["scoring_logic", "matching_strategy", "heuristic_refinement"],
    "cross_cutting": ["cross_domain_reuse", "observability_gap", "operationalization"],
}


@dataclass
class MiningFinding:
    """A single extracted pattern/feature/idea from a mined repo."""
    title: str
    description: str
    category: str
    source_repo: str
    source_files: list[str] = field(default_factory=list)
    source_symbols: list[dict[str, str]] = field(default_factory=list)
    implementation_sketch: str = ""
    augmentation_notes: str = ""
    relevance_score: float = 0.5
    language: str = "python"
    execution_steps: list[str] = field(default_factory=list)
    acceptance_checks: list[str] = field(default_factory=list)
    rollback_steps: list[str] = field(default_factory=list)
    preconditions: list[str] = field(default_factory=list)
    action_template_id: Optional[str] = None


@dataclass
class KnowledgeOverlap:
    """Structured result of knowledge-base overlap assessment (Pass 2)."""
    repo_known_titles: list[str] = field(default_factory=list)
    domain_known_titles: list[str] = field(default_factory=list)
    domain_known_categories: list[str] = field(default_factory=list)
    overlap_score: float = 0.0
    suggested_focus: list[str] = field(default_factory=list)


# Domain keyword signals for rule-based classification (Pass 1).
# Each key is a category from _VALID_CATEGORIES; values are keywords to scan for.
_DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "ai_integration": [
        "agent", "llm", "prompt", "model", "openai", "anthropic", "gpt",
        "claude", "gemini", "langchain", "transformer", "inference",
        "chat", "completion", "embedding", "fine-tune", "rag",
    ],
    "architecture": [
        "middleware", "plugin", "router", "pipeline", "microservice",
        "event-driven", "message queue", "dependency injection", "decorator",
        "state machine", "orchestrat", "workflow", "dispatcher",
    ],
    "memory": [
        "embedding", "vector", "rag", "retrieval", "knowledge graph",
        "cache", "index", "faiss", "chromadb", "pinecone", "weaviate",
        "semantic search", "similarity",
    ],
    "code_quality": [
        "lint", "format", "type check", "mypy", "ruff", "eslint",
        "prettier", "refactor", "code review", "static analysis",
    ],
    "cli_ux": [
        "cli", "command line", "terminal", "argparse", "typer", "click",
        "rich", "tui", "interactive", "prompt_toolkit",
    ],
    "testing": [
        "test", "pytest", "jest", "unittest", "fixture", "coverage",
        "property-based", "hypothesis", "mock", "integration test",
    ],
    "data_processing": [
        "etl", "pipeline", "stream", "batch", "transform", "ingest",
        "dataframe", "pandas", "polars", "spark", "parquet", "csv",
    ],
    "security": [
        "auth", "encrypt", "token", "permission", "oauth", "jwt",
        "rbac", "cors", "csrf", "sanitiz", "xss", "injection",
        "certificate", "tls", "ssl",
    ],
    "algorithm": [
        "sort", "search", "graph", "tree", "optimization", "heuristic",
        "dynamic programming", "backtrack", "a-star", "dijkstra",
        "genetic", "bayesian", "monte carlo",
    ],
    "cross_cutting": [
        "logging", "metrics", "observability", "feature flag",
        "config", "telemetry", "tracing", "monitoring",
    ],
    "design_patterns": [
        "protocol", "frozen", "dataclass", "immutable", "idempotent",
        "dependency injection", "precedence", "fallback", "normalize",
        "result normalization", "backward compat", "hybrid protocol",
        "perf_counter", "duration_ms", "structured log",
    ],
}

# Config file names that signal specific languages.
_LANGUAGE_SIGNALS: dict[str, str] = {
    "pyproject.toml": "python", "setup.py": "python", "setup.cfg": "python",
    "requirements.txt": "python", "pipfile": "python",
    "package.json": "javascript", "tsconfig.json": "typescript",
    "cargo.toml": "rust", "go.mod": "go", "go.sum": "go",
    "pom.xml": "java", "build.gradle": "java", "build.gradle.kts": "kotlin",
    "gemfile": "ruby", "mix.exs": "elixir", "project.clj": "clojure",
}


@dataclass
class RepoMiningResult:
    """Results from mining a single repo."""
    repo_name: str
    repo_path: str
    findings: list[MiningFinding] = field(default_factory=list)
    files_analyzed: int = 0
    tokens_used: int = 0
    cost_usd: float = 0.0
    duration_seconds: float = 0.0
    error: Optional[str] = None
    skipped: bool = False
    skip_reason: Optional[str] = None
    methodology_ids: list[str] = field(default_factory=list)
    action_template_ids: list[str] = field(default_factory=list)


@dataclass
class MiningReport:
    """Aggregate results from mining a directory of repos."""
    repos_scanned: int = 0
    total_findings: int = 0
    tasks_generated: int = 0
    total_cost_usd: float = 0.0
    total_tokens: int = 0
    total_duration_seconds: float = 0.0
    repos_skipped: int = 0
    repo_results: list[RepoMiningResult] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)


@dataclass
class RepoCandidate:
    """A discovered repo candidate with metadata for dedup decisions."""
    path: Path
    name: str                # directory name (e.g., "ace-forecaster-v3")
    canonical_name: str      # stripped name (e.g., "ace-forecaster")
    depth: int               # nesting depth from scan root
    source_kind: str = "git" # "git" or "source_tree"
    file_count: int = 0      # number of source files (proxy for completeness)
    last_commit_ts: float = 0.0  # timestamp of last git activity
    total_bytes: int = 0     # approximate source size
    scan_signature: str = "" # lightweight content/mtime signature for incremental mining
    content_hash: str = ""   # SHA-256 of file contents for cross-repo dedup


@dataclass
class RepoScanRecord:
    """Ledger entry for a previously mined repo."""
    repo_path: str
    repo_name: str
    canonical_name: str
    source_kind: str
    scan_signature: str
    file_count: int
    total_bytes: int
    last_commit_ts: float
    last_mined_at: float
    findings_count: int = 0
    tokens_used: int = 0
    content_hash: str = ""
    methodology_ids: list[str] = field(default_factory=list)
    action_template_ids: list[str] = field(default_factory=list)


class RepoScanLedger:
    """Persistent repo-mining ledger used to skip unchanged repos."""

    def __init__(self, path: Path):
        self.path = path
        self._records: dict[str, RepoScanRecord] = {}
        self._content_hash_index: dict[str, str] = {}  # content_hash → repo_path
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.exists():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Failed to load mining ledger %s", self.path)
            return

        raw_records = payload.get("records", {})
        if not isinstance(raw_records, dict):
            return

        for key, value in raw_records.items():
            if not isinstance(value, dict):
                continue
            try:
                self._records[key] = RepoScanRecord(**value)
                # Build content hash reverse index
                ch = value.get("content_hash", "")
                if ch:
                    self._content_hash_index[ch] = key
            except TypeError:
                continue

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "records": {
                key: record.__dict__
                for key, record in sorted(self._records.items())
            },
        }
        self.path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @staticmethod
    def repo_key(repo_path: Path) -> str:
        try:
            return str(repo_path.resolve())
        except OSError:
            return str(repo_path)

    def get_record(self, repo_path: Path) -> Optional[RepoScanRecord]:
        self._load()
        return self._records.get(self.repo_key(repo_path))

    def list_records(self) -> list[RepoScanRecord]:
        self._load()
        return list(self._records.values())

    def should_mine(
        self,
        candidate: RepoCandidate,
        *,
        skip_known: bool = True,
        force_rescan: bool = False,
    ) -> tuple[bool, str]:
        if force_rescan:
            return True, "forced"
        if not skip_known:
            return True, "skip-known disabled"

        existing = self.get_record(candidate.path)
        if existing is None:
            # Check if any OTHER record has the same content_hash
            if candidate.content_hash:
                self._load()
                dup_path = self._content_hash_index.get(candidate.content_hash)
                if dup_path and dup_path != self.repo_key(candidate.path):
                    return False, f"content-duplicate of {dup_path}"
            return True, "new"
        if existing.scan_signature != candidate.scan_signature:
            return True, "changed"
        return False, "unchanged"

    def record_result(self, candidate: RepoCandidate, result: RepoMiningResult) -> None:
        self._load()
        key = self.repo_key(candidate.path)
        self._records[key] = RepoScanRecord(
            repo_path=key,
            repo_name=candidate.name,
            canonical_name=candidate.canonical_name,
            source_kind=candidate.source_kind,
            scan_signature=candidate.scan_signature,
            file_count=candidate.file_count,
            total_bytes=candidate.total_bytes,
            last_commit_ts=candidate.last_commit_ts,
            last_mined_at=time.time(),
            findings_count=len(result.findings),
            tokens_used=result.tokens_used,
            content_hash=candidate.content_hash,
            methodology_ids=list(result.methodology_ids),
            action_template_ids=list(result.action_template_ids),
        )
        # Update content hash index
        if candidate.content_hash:
            self._content_hash_index[candidate.content_hash] = key
        self._save()


# File names that should appear first so the LLM understands the repo's purpose.
_README_NAMES: set[str] = {"readme.md", "readme.rst", "readme.txt", "readme"}

# Config/manifest files that reveal project structure and dependencies.
_CONFIG_NAMES: set[str] = {
    "pyproject.toml", "setup.py", "setup.cfg", "package.json",
    "cargo.toml", "go.mod", "pom.xml", "build.gradle",
}

# Directories containing tests, docs, examples — lower priority.
_LOW_PRIORITY_DIRS: set[str] = {
    "tests", "test", "spec", "specs", "docs", "doc", "examples", "example",
    "benchmarks", "benchmark", "fixtures", "scripts", "tools", "demo",
}


def _file_priority(rel_path: Path) -> int:
    """Return sort priority for a file (lower = earlier in serialization).

    Tier 0: README — the repo's self-description
    Tier 1: Config/manifest files — project structure
    Tier 2: Core source files (src/, lib/, top-level modules)
    Tier 3: Tests, docs, examples, scripts
    """
    name_lower = rel_path.name.lower()
    if name_lower in _README_NAMES:
        return 0
    if name_lower in _CONFIG_NAMES:
        return 1
    if any(part in _LOW_PRIORITY_DIRS for part in rel_path.parts):
        return 3
    return 2


def serialize_repo(
    repo_path: str | Path,
    max_bytes: int = _MAX_REPO_BYTES,
    exclude_files: set[str] | None = None,
    config: ClawConfig | None = None,
) -> tuple[str, int]:
    """Read all source files in a directory and concatenate with file headers.

    Files are ordered by priority: README first, then config files, then core
    source, then tests/docs/examples. This ensures the LLM sees the project's
    self-description and structure before diving into code.

    Filters by common code extensions, skips binary/build directories,
    and limits total size to max_bytes.

    Args:
        repo_path: Absolute path to the repository root.
        max_bytes: Maximum serialized size in bytes.
        exclude_files: Set of relative file paths to skip (from secret scanner).
        config: Optional ClawConfig for extra extensions/skip dirs.

    Returns:
        Tuple of (serialized content, number of files read).
    """
    root = Path(repo_path)
    if not root.is_dir():
        logger.warning("Repo path is not a directory: %s", repo_path)
        return "", 0

    code_exts = _get_code_extensions(config)
    skip_dirs = _get_skip_dirs(config)
    ignore_patterns = _load_mineignore(root)

    # Collect eligible files with priority ordering
    eligible: list[tuple[int, Path, Path]] = []  # (priority, rel_path, abs_path)
    for filepath in root.rglob("*"):
        if not filepath.is_file():
            continue
        rel = filepath.relative_to(root)
        if any(part in skip_dirs for part in rel.parts):
            continue
        if filepath.suffix.lower() not in code_exts:
            continue
        if ignore_patterns and _is_mineignored(str(rel), ignore_patterns):
            continue
        eligible.append((_file_priority(rel), rel, filepath))

    # Sort by priority then alphabetically within each tier
    eligible.sort(key=lambda t: (t[0], str(t[1])))

    parts: list[str] = []
    total_bytes = 0
    file_count = 0

    for _prio, rel, filepath in eligible:
        # Gate 2: Skip files flagged by secret scanner
        if exclude_files and str(rel) in exclude_files:
            logger.info("Skipping file with secret findings: %s", rel)
            continue

        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError) as exc:
            logger.debug("Skipping unreadable file %s: %s", filepath, exc)
            continue

        header = f"--- FILE: {rel} ---\n"
        chunk = header + content + "\n"
        chunk_bytes = len(chunk.encode("utf-8"))

        if total_bytes + chunk_bytes > max_bytes:
            parts.append(
                f"\n--- TRUNCATED: repo serialization exceeded {max_bytes // 1024}KB limit ---\n"
            )
            break

        parts.append(chunk)
        total_bytes += chunk_bytes
        file_count += 1

    return "".join(parts), file_count


def _repair_json(text: str) -> Optional[list]:
    """Attempt to repair common LLM JSON errors.

    Tries progressively more aggressive fixes:
    1. Strip trailing commas before ] or }
    2. Truncate at last valid ] and re-parse
    3. Parse individual objects from the array
    """
    import re as _re

    # Fix 1: Remove trailing commas (e.g., {"a": 1,} or [1, 2,])
    fixed = _re.sub(r",\s*([}\]])", r"\1", text)
    try:
        result = json.loads(fixed)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Fix 2: Truncate at last complete array bracket
    last_bracket = fixed.rfind("]")
    if last_bracket > 0:
        truncated = fixed[:last_bracket + 1]
        try:
            result = json.loads(truncated)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # Fix 3: Extract individual JSON objects and build array
    objects = []
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{" and depth == 0:
            start = i
            depth = 1
        elif ch == "{":
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                fragment = text[start:i + 1]
                try:
                    obj = json.loads(fragment)
                    objects.append(obj)
                except json.JSONDecodeError:
                    pass
                start = None

    if objects:
        return objects

    return None


def parse_findings(llm_response: str, repo_name: str) -> list[MiningFinding]:
    """Extract MiningFinding objects from LLM JSON response.

    Handles ```json fences, validates required fields, filters by
    relevance score, and caps at _MAX_FINDINGS_PER_REPO.

    Args:
        llm_response: Raw text from the LLM containing a JSON array.
        repo_name: Name of the source repo (injected into each finding).

    Returns:
        List of validated MiningFinding objects.
    """
    if not llm_response:
        logger.warning("Empty or None LLM response for %s — returning no findings", repo_name)
        return []
    cleaned = llm_response.strip()

    # Strip markdown code fences if present
    fence_pattern = r"^```(?:json)?\s*\n?(.*?)\n?```$"
    match = re.match(fence_pattern, cleaned, re.DOTALL)
    if match:
        cleaned = match.group(1).strip()

    # Try to find a JSON array in the response
    if not cleaned.startswith("["):
        # Look for array start in the response
        arr_start = cleaned.find("[")
        arr_end = cleaned.rfind("]")
        if arr_start != -1 and arr_end != -1 and arr_end > arr_start:
            cleaned = cleaned[arr_start:arr_end + 1]

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Attempt JSON repair for common LLM errors
        repaired = _repair_json(cleaned)
        if repaired is not None:
            data = repaired
            logger.info("Repaired malformed JSON from LLM (original error: %s)", e)
        else:
            logger.warning("Failed to parse mining findings JSON: %s", e)
            return []

    if not isinstance(data, list):
        logger.warning("Mining findings response is not a JSON array")
        return []

    def _text(value: Any, default: str = "") -> str:
        if value is None:
            return default
        if isinstance(value, str):
            return value
        return str(value)

    findings: list[MiningFinding] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        # Required fields
        title = _text(item.get("title", ""), "").strip()
        description = _text(item.get("description", ""), "").strip()
        if not title or not description:
            continue

        # Category validation
        category = _text(item.get("category", ""), "").strip().lower()
        if category not in _VALID_CATEGORIES:
            category = "cross_cutting"

        # Relevance filter
        try:
            relevance = float(item.get("relevance_score", 0.0))
        except (TypeError, ValueError):
            relevance = 0.0
        if relevance < 0.4:
            continue

        # Clamp relevance to [0.4, 1.0]
        relevance = min(max(relevance, 0.4), 1.0)

        # Source files
        source_files = item.get("source_files", [])
        if not isinstance(source_files, list):
            source_files = []
        source_files = [str(f) for f in source_files if f]

        source_symbols = item.get("source_symbols", [])
        if not isinstance(source_symbols, list):
            source_symbols = []
        normalized_symbols: list[dict[str, str]] = []
        for symbol in source_symbols:
            if isinstance(symbol, dict):
                file_path = str(symbol.get("file_path", "")).strip()
                symbol_name = str(symbol.get("symbol_name", "")).strip()
                symbol_kind = str(symbol.get("symbol_kind", "symbol")).strip() or "symbol"
                if file_path and symbol_name:
                    normalized_symbols.append(
                        {
                            "file_path": file_path,
                            "symbol_name": symbol_name,
                            "symbol_kind": symbol_kind,
                            "note": str(symbol.get("note", "")).strip(),
                        }
                    )

        # Optional execution plan fields
        execution_steps = item.get("execution_steps", [])
        if not isinstance(execution_steps, list):
            execution_steps = []
        execution_steps = [str(s).strip() for s in execution_steps if str(s).strip()]

        acceptance_checks = item.get("acceptance_checks", [])
        if not isinstance(acceptance_checks, list):
            acceptance_checks = []
        acceptance_checks = [str(s).strip() for s in acceptance_checks if str(s).strip()]

        rollback_steps = item.get("rollback_steps", [])
        if not isinstance(rollback_steps, list):
            rollback_steps = []
        rollback_steps = [str(s).strip() for s in rollback_steps if str(s).strip()]

        preconditions = item.get("preconditions", [])
        if not isinstance(preconditions, list):
            preconditions = []
        preconditions = [str(s).strip() for s in preconditions if str(s).strip()]

        finding = MiningFinding(
            title=title[:200],
            description=description[:2000],
            category=category,
            source_repo=repo_name,
            source_files=source_files[:20],
            source_symbols=normalized_symbols[:20],
            implementation_sketch=_text(item.get("implementation_sketch", ""), "")[:2000],
            augmentation_notes=_text(item.get("augmentation_notes", ""), "")[:1000],
            relevance_score=relevance,
            language=_text(item.get("language", "python"), "python")[:20],
            execution_steps=execution_steps[:10],
            acceptance_checks=acceptance_checks[:10],
            rollback_steps=rollback_steps[:10],
            preconditions=preconditions[:10],
        )
        findings.append(finding)

        if len(findings) >= _MAX_FINDINGS_PER_REPO:
            break

    return findings


class RepoMiner:
    """Mines local repositories for patterns, features, and ideas.

    Uses LLMClient.complete() directly (not through agents/Dispatcher)
    since mining is analytical — a single large-context call per repo.

    Args:
        repository: Database access for creating tasks.
        llm_client: OpenRouter client for LLM calls.
        semantic_memory: For storing findings as methodologies.
        config: CLAW config for model selection.
    """

    def __init__(
        self,
        repository: Repository,
        llm_client: LLMClient,
        semantic_memory: SemanticMemory,
        config: ClawConfig,
        governance: Any = None,
        assimilation_engine: Any = None,
        scan_ledger_path: Optional[Path] = None,
    ):
        self.repository = repository
        self.llm_client = llm_client
        self.semantic_memory = semantic_memory
        self.config = config
        self.governance = governance
        self.assimilation_engine = assimilation_engine
        self._prompt_template: Optional[str] = None
        self.scan_ledger = RepoScanLedger(
            scan_ledger_path or _default_scan_ledger_path(config)
        )
        self._assimilation_parallelism = 4

    @staticmethod
    def _extract_symbols_from_file(repo_path: Path, relative_path: str, max_symbols: int = 8) -> list[dict[str, str]]:
        """Extract concrete class/function/module references from a source file."""
        path = repo_path / relative_path
        if not path.is_file():
            return []
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []

        symbols: list[dict[str, str]] = []
        module_name = path.stem
        symbols.append(
            {
                "file_path": relative_path,
                "symbol_name": module_name,
                "symbol_kind": "module",
                "note": "module derived from source file",
            }
        )

        suffix = path.suffix.lower()
        if suffix == ".py":
            try:
                tree = ast.parse(text)
                for node in tree.body:
                    if isinstance(node, ast.ClassDef):
                        symbols.append(
                            {
                                "file_path": relative_path,
                                "symbol_name": node.name,
                                "symbol_kind": "class",
                                "note": "top-level class definition",
                            }
                        )
                    elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        symbols.append(
                            {
                                "file_path": relative_path,
                                "symbol_name": node.name,
                                "symbol_kind": "function",
                                "note": "top-level function definition",
                            }
                        )
            except SyntaxError:
                pass
        else:
            patterns: list[tuple[str, str]] = [
                (r"(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)", "function"),
                (r"class\s+([A-Za-z_][A-Za-z0-9_]*)", "class"),
                (r"(?:const|let|var)\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:async\s*)?\(", "function"),
                (r"func\s+([A-Za-z_][A-Za-z0-9_]*)", "function"),
                (r"type\s+([A-Za-z_][A-Za-z0-9_]*)\s+(?:struct|interface)", "class"),
                (r"\bfn\s+([A-Za-z_][A-Za-z0-9_]*)", "function"),
                (r"\b(?:struct|enum|trait)\s+([A-Za-z_][A-Za-z0-9_]*)", "class"),
                (r"\b(?:class|interface|record)\s+([A-Za-z_][A-Za-z0-9_]*)", "class"),
            ]
            for pattern, kind in patterns:
                for match in re.finditer(pattern, text):
                    symbols.append(
                        {
                            "file_path": relative_path,
                            "symbol_name": match.group(1),
                            "symbol_kind": kind,
                            "note": f"heuristically extracted {kind}",
                        }
                    )

        deduped: list[dict[str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for item in symbols:
            ident = (item["file_path"], item["symbol_name"], item["symbol_kind"])
            if ident in seen:
                continue
            seen.add(ident)
            deduped.append(item)
            if len(deduped) >= max_symbols:
                break
        return deduped

    @staticmethod
    def _score_symbol_relevance(symbol: dict[str, str], finding: MiningFinding) -> int:
        text = " ".join(
            [
                finding.title.lower(),
                finding.description.lower(),
                finding.implementation_sketch.lower(),
                finding.augmentation_notes.lower(),
            ]
        )
        name = symbol.get("symbol_name", "").lower()
        score = 0
        if name and name in text:
            score += 4
        name_tokens = {token for token in re.findall(r"[a-z0-9_]+", name) if len(token) >= 3}
        text_tokens = {token for token in re.findall(r"[a-z0-9_]+", text) if len(token) >= 3}
        score += len(name_tokens & text_tokens)
        kind = symbol.get("symbol_kind", "")
        if kind in {"class", "function"}:
            score += 1
        return score

    def _attach_symbol_provenance(self, findings: list[MiningFinding], repo_path: Path, per_finding_limit: int = 8) -> None:
        """Attach concrete symbol references from mined source files."""
        for finding in findings:
            if finding.source_symbols:
                continue
            candidates: list[dict[str, str]] = []
            for relative_path in finding.source_files:
                candidates.extend(self._extract_symbols_from_file(repo_path, relative_path))
            candidates.sort(key=lambda item: self._score_symbol_relevance(item, finding), reverse=True)
            deduped: list[dict[str, str]] = []
            seen: set[tuple[str, str, str]] = set()
            for item in candidates:
                ident = (item["file_path"], item["symbol_name"], item["symbol_kind"])
                if ident in seen:
                    continue
                seen.add(ident)
                deduped.append(item)
                if len(deduped) >= per_finding_limit:
                    break
            finding.source_symbols = deduped

    def _seed_capability_data_from_finding(self, finding: MiningFinding) -> dict[str, Any]:
        """Create retrieval-friendly seed capability metadata from a mining finding.

        This adds provenance and trigger metadata immediately, before the richer
        LLM-based assimilation pass fills in IO/domain/composability details.
        """
        applicability = [finding.description.strip(), finding.implementation_sketch.strip()]
        applicability = [item for item in applicability if item]

        source_artifacts = [
            {
                "file_path": path,
                "symbol_name": None,
                "symbol_kind": "file",
                "note": f"Mined from {finding.source_repo}",
            }
            for path in finding.source_files
        ]
        for symbol in finding.source_symbols:
            source_artifacts.append(
                {
                    "file_path": symbol.get("file_path", ""),
                    "symbol_name": symbol.get("symbol_name"),
                    "symbol_kind": symbol.get("symbol_kind", "symbol"),
                    "note": symbol.get("note", ""),
                }
            )

        triggers = list(_CATEGORY_TRIGGER_MAP.get(finding.category, []))
        if finding.execution_steps or finding.acceptance_checks:
            triggers.append("has_action_template_candidate")
        if finding.relevance_score >= 0.8:
            triggers.append("high_relevance")

        non_applicability: list[str] = []
        if finding.augmentation_notes.strip():
            non_applicability.append(
                "Requires adaptation to the target repo; do not apply blindly."
            )

        return {
            "schema_version": 2,
            "enrichment_status": "seeded",
            "inputs": [],
            "outputs": [],
            "domain": [finding.category],
            "composability": {
                "can_chain_after": [],
                "can_chain_before": [],
                "standalone": True,
            },
            "capability_type": "validation" if finding.category in {"testing", "security", "code_quality"} else "transformation",
            "source_repos": [finding.source_repo],
            "source_artifacts": source_artifacts,
            "applicability": applicability,
            "non_applicability": non_applicability,
            "activation_triggers": sorted(set(triggers)),
            "dependencies": list(finding.preconditions),
            "risks": [finding.augmentation_notes.strip()] if finding.augmentation_notes.strip() else [],
            "composition_candidates": [],
            "evidence": [f"source_file:{path}" for path in finding.source_files],
            "license_type": getattr(self, "_current_mine_metadata", {}).get("license_type", ""),
        }

    def _get_prompt_template(self) -> str:
        """Load the mining prompt template from prompts/repo-mine.md."""
        if self._prompt_template is None:
            prompt_path = Path(__file__).parent.parent.parent / "prompts" / "repo-mine.md"
            if not prompt_path.exists():
                raise FileNotFoundError(f"Mining prompt not found: {prompt_path}")
            self._prompt_template = prompt_path.read_text(encoding="utf-8")
        return self._prompt_template

    def _get_mining_model(self) -> str:
        """Get the model to use for mining from config.

        Uses the claude agent's model since mining is analytical work.
        Falls back through other agents if claude is not configured.
        """
        for agent_name in ("claude", "gemini", "codex", "grok"):
            agent_cfg = self.config.agents.get(agent_name)
            if agent_cfg and agent_cfg.enabled and agent_cfg.model:
                return agent_cfg.model
        raise ValueError("No model configured in any agent. Set a model in claw.toml.")

    async def mine_directory(
        self,
        base_path: str | Path,
        target_project_id: str,
        max_repos: int = 10,
        min_relevance: float = 0.6,
        generate_tasks: bool = True,
        on_repo_complete: Optional[Any] = None,
        max_depth: int = 6,
        dedup_iterations: bool = True,
        skip_known: bool = True,
        force_rescan: bool = False,
        yield_sort: bool = True,
    ) -> MiningReport:
        """Discover repos in a directory and mine each.

        Args:
            base_path: Root directory to scan for git repos.
            target_project_id: Project ID to create tasks under.
            max_repos: Maximum repos to mine.
            min_relevance: Minimum relevance for task generation.
            generate_tasks: Whether to create enhancement tasks.
            on_repo_complete: Optional callback(repo_name, result) for progress.
            max_depth: Maximum directory depth for repo discovery.
            dedup_iterations: If True, dedup repo iterations by canonical name.

        Returns:
            MiningReport with aggregate results.
        """
        base = Path(base_path).resolve()
        if not base.exists():
            raise FileNotFoundError(f"Directory not found: {base}")
        if not base.is_dir():
            raise NotADirectoryError(f"Not a directory: {base}")

        # Discover repos by looking for .git directories
        candidates = _discover_repos(base, max_depth=max_depth, config=self.config)
        if not candidates:
            logger.info("No git repos found in %s", base)
            return MiningReport()

        # Dedup iterations if requested
        if dedup_iterations:
            candidates, skipped = _dedup_iterations(candidates)
            if skipped:
                logger.info(
                    "Dedup: %d selected, %d skipped",
                    len(candidates), len(skipped),
                )

        mining_plan: list[tuple[RepoCandidate, str]] = []
        skipped_candidates: list[tuple[RepoCandidate, str]] = []
        for candidate in candidates:
            should_mine, reason = self.scan_ledger.should_mine(
                candidate,
                skip_known=skip_known,
                force_rescan=force_rescan,
            )
            if should_mine:
                mining_plan.append((candidate, reason))
            else:
                skipped_candidates.append((candidate, reason))

        # Sort by expected yield before selecting top-N
        if yield_sort and mining_plan:
            mining_plan.sort(
                key=lambda item: _score_yield_priority(item[0], self.scan_ledger),
                reverse=True,
            )
            for cand, _r in mining_plan[:min(5, len(mining_plan))]:
                s = _score_yield_priority(cand, self.scan_ledger)
                age = (time.time() - cand.last_commit_ts) / 86400 if cand.last_commit_ts > 0 else -1
                logger.info(
                    "Yield-priority: %s score=%.1f (files=%d, kind=%s, age=%.0fd)",
                    cand.name, s, cand.file_count, cand.source_kind, age,
                )

        selected_candidates = mining_plan[:max_repos]
        logger.info(
            "Found %d repos to mine in %s (%d skipped as unchanged)",
            len(selected_candidates), base, len(skipped_candidates),
        )

        report = MiningReport()
        start = time.monotonic()
        report.repos_skipped = len(skipped_candidates)

        for candidate, _reason in selected_candidates:
            repo_path = candidate.path
            repo_name = candidate.name
            try:
                result = await self.mine_repo(repo_path, repo_name, target_project_id)
                report.repo_results.append(result)
                report.repos_scanned += 1
                report.total_findings += len(result.findings)
                report.total_cost_usd += result.cost_usd
                report.total_tokens += result.tokens_used
                if not result.error and not result.skipped:
                    self.scan_ledger.record_result(candidate, result)

                if on_repo_complete:
                    on_repo_complete(repo_name, result)

            except Exception as e:
                logger.error("Failed to mine repo %s: %s", repo_name, e)
                report.repo_results.append(RepoMiningResult(
                    repo_name=repo_name,
                    repo_path=str(repo_path),
                    error=str(e),
                ))
                report.repos_scanned += 1

        # Generate tasks from all findings
        if generate_tasks:
            all_findings = []
            for result in report.repo_results:
                all_findings.extend(result.findings)

            tasks = await self._generate_tasks(
                all_findings, target_project_id, min_relevance
            )
            report.tasks = tasks
            report.tasks_generated = len(tasks)

        report.total_duration_seconds = time.monotonic() - start
        if report.total_findings > 0:
            maybe_mark_cag_stale(self.config)
        return report

    async def mine_repo(
        self,
        repo_path: str | Path,
        repo_name: str,
        target_project_id: str,
        metadata: dict[str, str] | None = None,
        secret_scan_files: set[str] | None = None,
    ) -> RepoMiningResult:
        """Mine a single repository for patterns and features.

        Args:
            repo_path: Path to the repo root.
            repo_name: Human-readable repo name.
            target_project_id: Project ID for storing findings.
            metadata: Optional metadata to inject into stored methodologies
                (e.g., license_type from the assimilation pipeline).
            secret_scan_files: Set of relative file paths to exclude from
                serialization (flagged by pre-mine secret scanner).

        Returns:
            RepoMiningResult with findings and metadata.
        """
        self._current_mine_metadata = metadata or {}
        start = time.monotonic()
        repo_path = Path(repo_path)

        # Serialize repo content (Gate 2: exclude files with secrets)
        repo_content, file_count = serialize_repo(
            repo_path, exclude_files=secret_scan_files, config=self.config
        )
        if not repo_content:
            return RepoMiningResult(
                repo_name=repo_name,
                repo_path=str(repo_path),
                error="No source files found",
            )

        logger.info(
            "Serialized %s: %d files, %d bytes",
            repo_name, file_count, len(repo_content.encode()),
        )

        # === PASS 1: Domain Classification (rule-based, free) ===
        domain_info = self._classify_repo_domain(repo_content, file_count)
        logger.info(
            "Pass 1 — domain: %s, language: %s, complexity: %s",
            domain_info["primary_domain"],
            domain_info["language"],
            domain_info["complexity"],
        )

        # === PASS 2: Knowledge Overlap Assessment (embedding search, cheap) ===
        overlap = await self._assess_knowledge_overlap(repo_name, domain_info)
        logger.info(
            "Pass 2 — repo-known: %d, domain-known: %d, overlap: %.2f, focus: %s",
            len(overlap.repo_known_titles),
            len(overlap.domain_known_titles),
            overlap.overlap_score,
            overlap.suggested_focus,
        )

        # === PASS 3: Focused Deep-Dive Mining (LLM call, domain-aware) ===
        template = self._get_prompt_template()
        prompt = template.replace("{repo_content}", repo_content)

        # Build structured context from Pass 1 + Pass 2
        context_lines = self._build_mining_context(domain_info, overlap)
        if context_lines:
            prompt = "\n".join(context_lines) + "\n\n" + prompt

        # Adaptive token budget based on repo complexity
        # Small repos still need enough tokens to extract 6-8 findings
        # with full metadata (title, description, sketch, symbols).
        token_budget = {
            "small": 4096,
            "medium": 6144,
            "large": 8192,
        }.get(domain_info["complexity"], 6144)

        model = self._get_mining_model()
        try:
            response: LLMResponse = await self.llm_client.complete(
                messages=[LLMMessage(role="user", content=prompt)],
                model=model,
                temperature=0.3,
                max_tokens=token_budget,
            )
        except Exception as e:
            duration = time.monotonic() - start
            return RepoMiningResult(
                repo_name=repo_name,
                repo_path=str(repo_path),
                files_analyzed=file_count,
                duration_seconds=duration,
                error=f"LLM call failed: {e}",
            )

        # Parse findings
        findings = parse_findings(response.content, repo_name)
        self._attach_symbol_provenance(findings, Path(repo_path))
        logger.info("Extracted %d findings from %s", len(findings), repo_name)

        # Store each finding in semantic memory
        methodology_ids: list[str] = []
        action_template_ids: list[str] = []
        for finding in findings:
            try:
                methodology_id = await self.store_finding(
                    finding,
                    target_project_id,
                    run_assimilation=False,
                )
                if methodology_id:
                    methodology_ids.append(methodology_id)
                if finding.action_template_id:
                    action_template_ids.append(finding.action_template_id)
            except Exception as e:
                logger.warning("Failed to store finding '%s': %s", finding.title, e)

        if methodology_ids and self.assimilation_engine is not None:
            await self._assimilate_methodologies(methodology_ids)

        duration = time.monotonic() - start
        return RepoMiningResult(
            repo_name=repo_name,
            repo_path=str(repo_path),
            findings=findings,
            files_analyzed=file_count,
            tokens_used=response.tokens_used,
            cost_usd=0.0,  # Cost tracked by token_tracker separately
            duration_seconds=duration,
            methodology_ids=methodology_ids,
            action_template_ids=action_template_ids,
        )

    async def store_finding(
        self,
        finding: MiningFinding,
        target_project_id: str,
        *,
        run_assimilation: bool = True,
    ) -> Optional[str]:
        """Store a mining finding in semantic memory as a Methodology.

        Applies enhanced quality gate and pre-save dedup before storing.

        Args:
            finding: The extracted finding.
            target_project_id: Project to associate with (unused in methodology but tracked via tags).

        Returns:
            The methodology ID, or None if blocked by quality gate or dedup.
        """
        # Enhanced quality gate
        passes, reason = self._enhanced_quality_gate(finding)
        if not passes:
            logger.info("Quality gate blocked finding '%s': %s", finding.title, reason)
            return None

        # Build a rich problem description for embedding
        problem_desc = (
            f"[Mined from {finding.source_repo}] {finding.title}: "
            f"{finding.description}"
        )

        # Build solution code from implementation sketch
        solution = (
            f"## {finding.title}\n\n"
            f"**Category:** {finding.category}\n"
            f"**Source:** {finding.source_repo}\n"
            f"**Relevance:** {finding.relevance_score:.2f}\n\n"
            f"### Description\n{finding.description}\n\n"
            f"### Implementation Sketch\n{finding.implementation_sketch}\n\n"
            f"### Augmentation Notes\n{finding.augmentation_notes}\n"
        )

        tags = [
            "mined",
            f"source:{finding.source_repo}",
            f"category:{finding.category}",
        ]

        methodology = await self.semantic_memory.save_solution(
            problem_description=problem_desc,
            solution_code=solution,
            methodology_notes=finding.augmentation_notes,
            tags=tags,
            language=finding.language,
            scope="global",
            methodology_type="PATTERN",
            files_affected=finding.source_files,
        )

        await self.repository.update_methodology_capability_data(
            methodology.id,
            self._seed_capability_data_from_finding(finding),
        )

        logger.debug("Stored finding '%s' as methodology %s", finding.title, methodology.id)

        # Build a reusable executable action template when the finding includes
        # concrete runbook steps and checks.
        if finding.execution_steps or finding.acceptance_checks:
            action_template = ActionTemplate(
                title=finding.title[:200],
                problem_pattern=finding.description[:2000],
                execution_steps=finding.execution_steps,
                acceptance_checks=finding.acceptance_checks,
                rollback_steps=finding.rollback_steps,
                preconditions=finding.preconditions,
                source_methodology_id=methodology.id,
                source_repo=finding.source_repo,
                confidence=finding.relevance_score,
            )
            await self.repository.create_action_template(action_template)
            finding.action_template_id = action_template.id
            logger.debug(
                "Created action template %s for finding '%s'",
                action_template.id,
                finding.title,
            )

        # Trigger capability assimilation
        if run_assimilation and self.assimilation_engine is not None:
            try:
                await self.assimilation_engine.assimilate(methodology.id)
            except Exception as e:
                logger.warning("Assimilation failed for %s: %s", methodology.id, e)

        return methodology.id

    async def _assimilate_methodologies(self, methodology_ids: list[str]) -> None:
        if self.assimilation_engine is None or not methodology_ids:
            return

        limit = max(1, min(self._assimilation_parallelism, len(methodology_ids)))
        semaphore = asyncio.Semaphore(limit)

        async def _run(methodology_id: str) -> None:
            async with semaphore:
                try:
                    await self.assimilation_engine.assimilate(methodology_id)
                except Exception as e:
                    logger.warning("Assimilation failed for %s: %s", methodology_id, e)

        await asyncio.gather(*(_run(methodology_id) for methodology_id in methodology_ids))

    # ------------------------------------------------------------------
    # Multi-pass mining helpers
    # ------------------------------------------------------------------

    def _classify_repo_domain(
        self, repo_content: str, file_count: int
    ) -> dict[str, Any]:
        """Pass 1: Lightweight domain classification from serialized repo content.

        Uses keyword matching on README + config files (already serialized first
        due to priority ordering) to classify the repo's domain. No LLM call.

        Returns:
            Dict with primary_domain, secondary_domains, language, complexity,
            and readme_summary.
        """
        content_lower = repo_content[:20_000].lower()  # scan first ~20KB

        # --- Extract README section ---
        readme_summary = ""
        readme_marker = "--- file: readme"
        idx = content_lower.find(readme_marker)
        if idx != -1:
            # Find end of README section (next file marker or 3000 chars)
            next_file = repo_content.find("--- FILE:", idx + 10)
            end = next_file if next_file != -1 else min(idx + 3000, len(repo_content))
            readme_summary = repo_content[idx:end].strip()

        # --- Detect language from config files ---
        language = "unknown"
        for config_name, lang in _LANGUAGE_SIGNALS.items():
            if f"--- file: {config_name}" in content_lower or f"/{config_name}" in content_lower:
                language = lang
                break

        # --- Keyword-based domain scoring ---
        scores: dict[str, int] = {}
        scan_text = (readme_summary + "\n" + repo_content[:10_000]).lower()
        for category, keywords in _DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in scan_text)
            if score > 0:
                scores[category] = score

        # Sort by score descending
        ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        primary_domain = ranked[0][0] if ranked else "cross_cutting"
        secondary_domains = [cat for cat, _ in ranked[1:4] if _ >= 2]

        # --- Complexity estimate ---
        if file_count < 50:
            complexity = "small"
        elif file_count <= 200:
            complexity = "medium"
        else:
            complexity = "large"

        return {
            "primary_domain": primary_domain,
            "secondary_domains": secondary_domains,
            "language": language,
            "complexity": complexity,
            "readme_summary": readme_summary[:2000],
        }

    async def _assess_knowledge_overlap(
        self, repo_name: str, domain_info: dict[str, Any]
    ) -> KnowledgeOverlap:
        """Pass 2: Structured assessment of what the KB already covers in this domain.

        Combines repo-specific dedup (what we mined from this repo before) with
        domain-wide semantic search (what we know about similar topics from other repos).

        Returns:
            KnowledgeOverlap with scores and suggested focus categories.
        """
        # Repo-specific: what we already mined from this exact repo
        repo_known = await self._check_already_mined(repo_name)

        # Domain-wide: semantic search using README excerpt
        domain_titles: list[str] = []
        domain_categories: list[str] = []
        readme_excerpt = domain_info.get("readme_summary", "")
        if self.semantic_memory and readme_excerpt.strip():
            try:
                similar = await self.semantic_memory.find_similar(
                    readme_excerpt[:2000], limit=10
                )
                for s in similar:
                    if s.methodology and s.methodology.problem_description:
                        domain_titles.append(s.methodology.problem_description[:120])
                        # Extract category from tags
                        for tag in (s.methodology.tags or []):
                            if tag.startswith("category:"):
                                cat = tag.removeprefix("category:")
                                if cat not in domain_categories:
                                    domain_categories.append(cat)
            except Exception as e:
                logger.debug("Domain overlap search failed: %s", e)

        # Compute overlap score: ratio of covered categories
        all_categories = list(_VALID_CATEGORIES)
        covered = set(domain_categories)
        overlap_score = len(covered) / len(all_categories) if all_categories else 0.0

        # Suggested focus: categories not well-covered AND relevant to this repo
        repo_domains = set(
            [domain_info["primary_domain"]]
            + domain_info.get("secondary_domains", [])
        )
        # Include all categories but prioritize those related to the repo's domain
        suggested = [
            cat for cat in all_categories
            if cat not in covered
        ]
        # Put repo-relevant gaps first
        relevant_gaps = [c for c in suggested if c in repo_domains]
        other_gaps = [c for c in suggested if c not in repo_domains]
        suggested_focus = relevant_gaps + other_gaps

        return KnowledgeOverlap(
            repo_known_titles=repo_known,
            domain_known_titles=domain_titles,
            domain_known_categories=domain_categories,
            overlap_score=round(overlap_score, 2),
            suggested_focus=suggested_focus[:5],  # top 5 gaps
        )

    def _build_mining_context(
        self, domain_info: dict[str, Any], overlap: KnowledgeOverlap
    ) -> list[str]:
        """Build structured context lines for the mining LLM prompt.

        Combines Pass 1 domain classification and Pass 2 overlap assessment
        into directives that guide the mining LLM to focus on novel findings.
        """
        lines: list[str] = []

        # Domain classification (Pass 1)
        lines.append("# Domain Classification")
        lines.append(f"Primary domain: {domain_info['primary_domain']}")
        if domain_info.get("secondary_domains"):
            lines.append(f"Secondary domains: {', '.join(domain_info['secondary_domains'])}")
        lines.append(f"Language: {domain_info['language']}")
        lines.append(f"Complexity: {domain_info['complexity']}")

        # Knowledge overlap (Pass 2)
        if overlap.repo_known_titles:
            lines.append(
                f"\n# Already mined from this repo ({len(overlap.repo_known_titles)} patterns):"
            )
            for title in overlap.repo_known_titles:
                lines.append(f"- {title}")

        if overlap.domain_known_titles:
            lines.append("\n# CLAW knows these related patterns from OTHER repos:")
            for title in overlap.domain_known_titles[:8]:
                lines.append(f"- {title}")

        # Focus directives
        if overlap.suggested_focus:
            lines.append("\n# PRIORITY: Focus mining on these under-represented categories:")
            for cat in overlap.suggested_focus:
                lines.append(f"- {cat}")

        lines.append(
            "\n# Instructions: DO NOT repeat known patterns. "
            "Prioritize novel findings in under-represented categories. "
            "ALSO extract novel implementation techniques from well-covered categories "
            "— e.g. structured logging with perf_counter timing, idempotent operation "
            "patterns, or result normalization even if similar categories exist."
        )
        return lines

    async def _find_domain_knowledge(self, readme_excerpt: str) -> list[str]:
        """Search existing knowledge base for patterns similar to this repo's domain.

        Uses the first ~2000 chars of repo content (typically README) as a semantic
        query to find what we already know in this domain across ALL repos.

        Returns:
            List of methodology titles/descriptions (max 5, truncated to 120 chars).
        """
        if not self.semantic_memory or not readme_excerpt.strip():
            return []
        try:
            similar = await self.semantic_memory.find_similar(
                readme_excerpt[:2000], limit=5
            )
            titles = []
            for s in similar:
                if s.methodology and s.methodology.problem_description:
                    titles.append(s.methodology.problem_description[:120])
            return titles
        except Exception as e:
            logger.debug("Domain knowledge search failed: %s", e)
            return []

    async def _check_already_mined(self, repo_name: str) -> list[str]:
        """Check what CLAW already knows from a repo.

        Searches semantic memory for methodologies tagged with source:{repo_name}.

        Returns:
            List of existing finding titles/descriptions.
        """
        try:
            existing = await self.repository.get_methodologies_by_tag(
                f"source:{repo_name}", limit=50
            )
            titles = [m.problem_description[:200] for m in existing]
            if titles:
                logger.info(
                    "Found %d existing findings from %s", len(titles), repo_name
                )
            return titles
        except Exception as e:
            logger.warning("Failed to check already-mined for %s: %s", repo_name, e)
            return []

    def _enhanced_quality_gate(
        self, finding: MiningFinding
    ) -> tuple[bool, str]:
        """Multi-dimensional quality gate beyond simple relevance.

        Checks:
        1. Relevance score >= 0.4 (existing minimum)
        2. Description length >= configured minimum
        3. Category is valid

        Returns:
            (passes, rejection_reason).
        """
        if finding.relevance_score < 0.4:
            return False, f"relevance too low ({finding.relevance_score:.2f} < 0.4)"

        min_desc = getattr(self.config, "governance", None)
        min_desc_len = 50
        if min_desc and hasattr(min_desc, "mining_min_description_length"):
            min_desc_len = min_desc.mining_min_description_length

        if len(finding.description) < min_desc_len:
            return False, f"description too short ({len(finding.description)} < {min_desc_len})"

        if finding.category not in _VALID_CATEGORIES:
            return False, f"invalid category: {finding.category}"

        return True, ""

    async def _generate_tasks(
        self,
        findings: list[MiningFinding],
        target_project_id: str,
        min_relevance: float = 0.6,
    ) -> list[Task]:
        """Create enhancement tasks from high-relevance findings.

        Args:
            findings: All findings from mining.
            target_project_id: Project to create tasks under.
            min_relevance: Minimum relevance_score to generate a task.

        Returns:
            List of created Task objects.
        """
        tasks: list[Task] = []

        # Filter and sort by relevance
        eligible = [f for f in findings if f.relevance_score >= min_relevance]
        eligible.sort(key=lambda f: f.relevance_score, reverse=True)

        for finding in eligible:
            priority = _relevance_to_priority(finding.relevance_score)
            execution_steps = [s.strip() for s in finding.execution_steps if s.strip()]
            acceptance_checks = [s.strip() for s in finding.acceptance_checks if s.strip()]
            rollback_steps = [s.strip() for s in finding.rollback_steps if s.strip()]
            preconditions = [s.strip() for s in finding.preconditions if s.strip()]

            runbook_sections: list[str] = []
            if preconditions:
                runbook_sections.append(
                    "### Preconditions\n" + "\n".join(f"- {p}" for p in preconditions)
                )
            if execution_steps:
                runbook_sections.append(
                    "### Execution Steps\n" + "\n".join(f"- `{cmd}`" for cmd in execution_steps)
                )
            if acceptance_checks:
                runbook_sections.append(
                    "### Acceptance Checks\n" + "\n".join(f"- `{cmd}`" for cmd in acceptance_checks)
                )
            if rollback_steps:
                runbook_sections.append(
                    "### Rollback\n" + "\n".join(f"- `{cmd}`" for cmd in rollback_steps)
                )

            runbook_text = "\n\n".join(runbook_sections)

            task = Task(
                project_id=target_project_id,
                title=f"[Mined:{finding.source_repo}] {finding.title}"[:200],
                description=(
                    f"## Enhancement from {finding.source_repo}\n\n"
                    f"**Category:** {finding.category}\n"
                    f"**Relevance:** {finding.relevance_score:.2f}\n"
                    f"**Language:** {finding.language}\n\n"
                    f"### What\n{finding.description}\n\n"
                    f"### How\n{finding.implementation_sketch}\n\n"
                    f"### Why\n{finding.augmentation_notes}\n\n"
                    f"### Source Files\n"
                    + "\n".join(f"- `{f}`" for f in finding.source_files)
                    + (f"\n\n{runbook_text}" if runbook_text else "")
                ),
                status=TaskStatus.PENDING,
                priority=priority,
                task_type=finding.category,
                recommended_agent=_category_to_agent(finding.category),
                action_template_id=finding.action_template_id,
                execution_steps=execution_steps,
                acceptance_checks=acceptance_checks,
            )

            try:
                saved = await self.repository.create_task(task)
                tasks.append(saved)
                logger.info(
                    "Created task '%s' (priority=%d) from finding in %s",
                    saved.title[:60], priority, finding.source_repo,
                )
            except Exception as e:
                logger.warning("Failed to create task for '%s': %s", finding.title, e)

        return tasks


def _canonicalize_name(name: str) -> str:
    """Strip version/variant suffixes from a repo directory name.

    Iteratively removes common suffixes like -v2, -final, -backup, _old,
    trailing digits after a dash, etc.

    Examples:
        "ace-forecaster-v3"  -> "ace-forecaster"
        "grokflow-cli-final" -> "grokflow-cli"
        "my-project-2"       -> "my-project"
        "tool-wip"           -> "tool"
        "tool-dev-v2"        -> "tool"
    """
    result = name.lower().strip()
    suffix_re = re.compile(
        r'[-_](v?\d+|final|latest|old|backup|copy|wip|dev|test|staging|prod|new|orig)$'
    )
    while True:
        new = suffix_re.sub('', result)
        if new == result:
            break
        result = new
    return result


def _collect_repo_metadata(
    repo_path: Path,
    code_extensions: set[str] | None = None,
    skip_dirs: set[str] | None = None,
) -> tuple[int, float, int, str, str]:
    """Collect lightweight metadata for a repo (no subprocess calls).

    Returns:
        (file_count, last_commit_ts, total_bytes, scan_signature, content_hash)
    """
    exts = code_extensions or _CODE_EXTENSIONS
    dirs = skip_dirs or _SKIP_DIRS

    file_count = 0
    total_bytes = 0
    latest_source_ts = 0.0
    fingerprint = hashlib.sha1()
    content_hasher = hashlib.sha256()
    content_files_hashed = 0

    try:
        for path in sorted(repo_path.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(repo_path)
            if any(part in dirs for part in rel.parts):
                continue
            if path.suffix.lower() not in exts:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            file_count += 1
            total_bytes += stat.st_size
            latest_source_ts = max(latest_source_ts, stat.st_mtime)
            # Metadata fingerprint (mtime-based, for incremental skip)
            fingerprint.update(str(rel).encode("utf-8", errors="replace"))
            fingerprint.update(b":")
            fingerprint.update(str(stat.st_size).encode())
            fingerprint.update(b":")
            fingerprint.update(str(stat.st_mtime_ns).encode())
            fingerprint.update(b"\n")
            # Content hash (first 4KB per file, for cross-repo dedup)
            if content_files_hashed < _CONTENT_HASH_MAX_FILES:
                try:
                    with open(path, "rb") as fh:
                        chunk = fh.read(_CONTENT_HASH_CHUNK)
                    content_hasher.update(str(rel).encode("utf-8", errors="replace"))
                    content_hasher.update(b":")
                    content_hasher.update(chunk)
                    content_hasher.update(b"\n")
                    content_files_hashed += 1
                except (OSError, PermissionError):
                    pass
    except (PermissionError, OSError):
        pass

    # Use .git directory mtime as proxy for last commit timestamp
    last_commit_ts = 0.0
    git_dir = repo_path / ".git"
    for ref_name in ("refs/heads/main", "refs/heads/master", "HEAD"):
        ref_path = git_dir / ref_name
        try:
            last_commit_ts = max(last_commit_ts, ref_path.stat().st_mtime)
        except OSError:
            pass
    if last_commit_ts == 0.0:
        try:
            last_commit_ts = git_dir.stat().st_mtime
        except OSError:
            pass
    last_commit_ts = max(last_commit_ts, latest_source_ts)
    scan_signature = hashlib.sha1(
        f"{file_count}:{total_bytes}:{last_commit_ts:.6f}:{fingerprint.hexdigest()}".encode("utf-8")
    ).hexdigest()
    content_hash = content_hasher.hexdigest() if content_files_hashed > 0 else ""

    return file_count, last_commit_ts, total_bytes, scan_signature, content_hash


def _discover_repos(
    base: Path,
    max_depth: int = 6,
    config: ClawConfig | None = None,
) -> list[RepoCandidate]:
    """Find repositories or repo-like source trees under a base directory using BFS.

    Scans up to max_depth levels deep using os.scandir() for performance.
    Stops descending into a directory once a repo candidate is found.
    Collects metadata for each repo to support iteration dedup.

    Args:
        base: Root directory to scan.
        max_depth: Maximum directory depth to search (default 6).
        config: Optional ClawConfig for extra extensions/skip dirs.

    Returns:
        List of RepoCandidate objects sorted by canonical_name then name.
    """
    code_exts = _get_code_extensions(config)
    skip_dirs = _get_skip_dirs(config)
    ignore_patterns = _load_mineignore(base)

    candidates: list[RepoCandidate] = []
    seen: set[str] = set()  # resolved path strings for dedup

    # BFS queue: (directory_path, current_depth)
    frontier: list[tuple[Path, int]] = [(base, 0)]

    while frontier:
        next_frontier: list[tuple[Path, int]] = []

        for dir_path, depth in frontier:
            # Check .mineignore against relative path from base
            if ignore_patterns and dir_path != base:
                try:
                    rel_str = str(dir_path.relative_to(base))
                except ValueError:
                    rel_str = dir_path.name
                if _is_mineignored(rel_str, ignore_patterns):
                    continue

            # Check if this directory is a git repo or extracted source tree
            git_marker = dir_path / ".git"
            try:
                is_repo = git_marker.exists()
            except (PermissionError, OSError):
                is_repo = False

            is_source_tree = False
            if not is_repo:
                is_source_tree = _looks_like_source_tree(dir_path, code_exts, skip_dirs)

            if is_repo or (is_source_tree and dir_path != base):
                try:
                    resolved = str(dir_path.resolve())
                except OSError:
                    resolved = str(dir_path)

                if resolved not in seen:
                    seen.add(resolved)
                    name = dir_path.name
                    file_count, last_commit_ts, total_bytes, scan_signature, content_hash = (
                        _collect_repo_metadata(dir_path, code_exts, skip_dirs)
                    )
                    candidates.append(RepoCandidate(
                        path=dir_path,
                        name=name,
                        canonical_name=_canonicalize_name(name),
                        depth=depth,
                        source_kind="git" if is_repo else "source_tree",
                        file_count=file_count,
                        last_commit_ts=last_commit_ts,
                        total_bytes=total_bytes,
                        scan_signature=scan_signature,
                        content_hash=content_hash,
                    ))
                # Don't descend into candidate repos — they're leaf nodes
                continue

            # Not a repo — descend if within depth limit
            if depth >= max_depth:
                continue

            try:
                with os.scandir(dir_path) as entries:
                    for entry in sorted(entries, key=lambda e: e.name):
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        if entry.name.startswith("."):
                            continue
                        if entry.name in skip_dirs:
                            continue
                        next_frontier.append((Path(entry.path), depth + 1))
            except (PermissionError, OSError):
                continue

        frontier = next_frontier

    # Sort by canonical_name, then by name for deterministic ordering
    candidates.sort(key=lambda c: (c.canonical_name, c.name))
    return candidates


def _looks_like_source_tree(
    dir_path: Path,
    code_extensions: set[str] | None = None,
    skip_dirs: set[str] | None = None,
) -> bool:
    """Heuristic for extracted source folders that are not git repos.

    A directory is considered mineable if it has at least one common project
    marker file and at least one code/config/document file near the root, or
    if it contains multiple source files near the root.
    """
    exts = code_extensions or _CODE_EXTENSIONS
    dirs = skip_dirs or _SKIP_DIRS

    marker_names = {
        "README.md", "README.rst", "README.txt",
        "pyproject.toml", "package.json", "Cargo.toml", "go.mod",
        "requirements.txt", "setup.py", "Makefile", "Dockerfile",
    }

    root_code_hits = 0
    nested_code_hits = 0
    has_marker = False

    try:
        with os.scandir(dir_path) as entries:
            for entry in entries:
                name = entry.name
                if name.startswith(".") and name != ".git":
                    continue
                if entry.is_file(follow_symlinks=False):
                    if name in marker_names:
                        has_marker = True
                    _, ext = os.path.splitext(name)
                    if ext.lower() in exts:
                        root_code_hits += 1
                elif entry.is_dir(follow_symlinks=False) and name not in dirs:
                    try:
                        with os.scandir(entry.path) as sub_entries:
                            for sub in sub_entries:
                                if not sub.is_file(follow_symlinks=False):
                                    continue
                                _, ext = os.path.splitext(sub.name)
                                if ext.lower() in exts:
                                    nested_code_hits += 1
                                    if nested_code_hits >= 2:
                                        break
                    except (PermissionError, OSError):
                        continue
                if has_marker and (root_code_hits + nested_code_hits) >= 1:
                    return True
                if root_code_hits >= 2:
                    return True
    except (PermissionError, OSError):
        return False

    return False


def _dedup_iterations(
    candidates: list[RepoCandidate],
) -> tuple[list[RepoCandidate], list[tuple[RepoCandidate, str]]]:
    """Deduplicate repo iterations by canonical name.

    Groups candidates by canonical_name and picks the best version
    based on: last_commit_ts (primary), file_count (secondary),
    total_bytes (tertiary).

    Args:
        candidates: All discovered repo candidates.

    Returns:
        (selected, skipped) where skipped includes (candidate, reason) tuples.
    """
    from collections import defaultdict

    groups: dict[str, list[RepoCandidate]] = defaultdict(list)
    for c in candidates:
        groups[c.canonical_name].append(c)

    selected: list[RepoCandidate] = []
    skipped: list[tuple[RepoCandidate, str]] = []

    for canonical, group in sorted(groups.items()):
        if len(group) == 1:
            selected.append(group[0])
            continue

        # Score: sort by (last_commit_ts, file_count, total_bytes) descending
        group.sort(
            key=lambda c: (c.last_commit_ts, c.file_count, c.total_bytes),
            reverse=True,
        )

        winner = group[0]
        selected.append(winner)

        for loser in group[1:]:
            skipped.append((
                loser,
                f"superseded by {winner.name} ({winner.path})",
            ))

        if len(group) > 1:
            logger.info(
                "Dedup '%s': selected '%s' (%d files, ts=%.0f), skipped %d iterations",
                canonical, winner.name, winner.file_count, winner.last_commit_ts,
                len(group) - 1,
            )

    # Second pass: content hash dedup across different canonical names
    content_groups: dict[str, list[RepoCandidate]] = defaultdict(list)
    for c in selected:
        if c.content_hash:
            content_groups[c.content_hash].append(c)

    content_deduped: list[RepoCandidate] = []
    content_seen: set[str] = set()
    for c in selected:
        if not c.content_hash or c.content_hash not in content_groups:
            content_deduped.append(c)
            continue
        if c.content_hash in content_seen:
            continue  # already processed this group
        content_seen.add(c.content_hash)
        group = content_groups[c.content_hash]
        if len(group) == 1:
            content_deduped.append(group[0])
        else:
            group.sort(
                key=lambda x: (x.last_commit_ts, x.file_count, x.total_bytes),
                reverse=True,
            )
            winner = group[0]
            content_deduped.append(winner)
            for loser in group[1:]:
                skipped.append((loser, f"content-duplicate of {winner.name} ({winner.path})"))
            logger.info(
                "Content dedup: '%s' matches %d other repos, kept '%s'",
                winner.content_hash[:12], len(group) - 1, winner.name,
            )

    content_deduped.sort(key=lambda c: (c.canonical_name, c.name))
    return content_deduped, skipped


def _score_yield_priority(
    candidate: RepoCandidate,
    ledger: "RepoScanLedger",
    *,
    now: float | None = None,
) -> float:
    """Score a repo candidate by expected mining yield.

    Higher score = mine first.  Max theoretical score = 100.

    Factors (data-driven from 90 mined repos — findings/token ratio
    does NOT scale linearly with repo size):
      1. Recency          (0–40)  recently active repos yield better patterns
      2. File-count sweet spot (0–25)  20-500 files is goldilocks
      3. Source kind       (0–10)  git > loose source tree
      4. Canonical sibling (-20)  if another iteration was already mined
      5. Size efficiency   (0–25)  smaller repos are cheaper per finding
    """
    _now = now or time.time()
    score = 0.0

    # --- Factor 1: Recency (0-40 points) ---
    if candidate.last_commit_ts > 0:
        age_days = (_now - candidate.last_commit_ts) / 86400
        if age_days <= 90:
            score += 40.0
        elif age_days <= 365:
            score += 40.0 * (1.0 - (age_days - 90) / 275)
        elif age_days <= 730:
            score += 10.0 * (1.0 - (age_days - 365) / 365)

    # --- Factor 2: File count sweet spot (0-25 points) ---
    fc = candidate.file_count
    if 20 <= fc <= 500:
        score += 25.0
    elif 10 <= fc < 20:
        score += 15.0
    elif 500 < fc <= 2000:
        score += 15.0
    elif fc < 10:
        score += 5.0
    else:
        score += 5.0

    # --- Factor 3: Source kind (0-10 points) ---
    if candidate.source_kind == "git":
        score += 10.0
    else:
        score += 3.0

    # --- Factor 4: Canonical sibling already mined (-20 penalty) ---
    ledger._load()
    for _key, record in ledger._records.items():
        if record.canonical_name == candidate.canonical_name:
            score -= 20.0
            break

    # --- Factor 5: Size efficiency (0-25 points) ---
    if candidate.total_bytes > 0:
        mb = candidate.total_bytes / (1024 * 1024)
        if mb <= 10:
            score += 25.0
        elif mb <= 50:
            score += 20.0
        elif mb <= 200:
            score += 10.0
        else:
            score += 2.0

    return score


def _relevance_to_priority(relevance: float) -> int:
    """Map relevance score to task priority (0-10 scale)."""
    if relevance >= 0.9:
        return 9
    if relevance >= 0.8:
        return 7
    if relevance >= 0.7:
        return 5
    if relevance >= 0.6:
        return 3
    return 1


def _category_to_agent(category: str) -> str:
    """Suggest an agent based on finding category."""
    mapping = {
        "architecture": "claude",
        "ai_integration": "claude",
        "memory": "claude",
        "code_quality": "codex",
        "cli_ux": "codex",
        "testing": "codex",
        "data_processing": "gemini",
        "security": "claude",
        "algorithm": "gemini",
        "cross_cutting": "grok",
    }
    return mapping.get(category, "claude")


def _default_scan_ledger_path(config: ClawConfig) -> Path:
    db_path = str(config.database.db_path)
    if db_path == ":memory:":
        return Path("data") / "mining_registry.json"
    return Path(db_path).resolve().parent / "mining_registry.json"
