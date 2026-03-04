"""Error knowledge base with cross-task and cross-agent failure pattern analysis.

Tracks attempted approaches per task and analyzes failure patterns
across an entire project and across all agents. Adapted from GrokFlow's
GUKSAnalytics error pattern detection (P10).

Key capabilities:
- Record attempts with error signatures and agent IDs
- Detect duplicate errors within a task
- Detect recurring bugs across tasks (cross-task pattern mining)
- Detect errors where all 4 agents fail the same way (cross-agent failures)
- Calculate urgency for failure patterns
- Provide forbidden approach lists enriched with project-wide patterns
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any, Optional

from claw.core.models import HypothesisEntry, HypothesisOutcome, TaskStatus
from claw.db.repository import Repository

logger = logging.getLogger("claw.memory.error_kb")


# Error category keywords adapted from GrokFlow's _categorize_patterns
# (translated from TypeScript to Python domain)
ERROR_CATEGORIES: dict[str, list[str]] = {
    "type_error": ["typeerror", "type error", "unexpected type", "not callable", "has no attribute"],
    "import_error": ["importerror", "modulenotfounderror", "no module named", "cannot import"],
    "attribute_error": ["attributeerror", "has no attribute", "no such attribute"],
    "value_error": ["valueerror", "invalid literal", "invalid value"],
    "key_error": ["keyerror", "key not found", "missing key"],
    "index_error": ["indexerror", "index out of range", "list index"],
    "connection_error": ["connectionerror", "connection refused", "timeout", "could not connect"],
    "database_error": ["operationalerror", "integrityerror", "programmingerror", "duplicate key"],
    "permission_error": ["permissionerror", "permission denied", "access denied", "unauthorized"],
    "file_error": ["filenotfounderror", "no such file", "is a directory", "not a file"],
    "async_error": ["asyncio", "coroutine", "event loop", "awaitable"],
    "api_error": ["api error", "http error", "status code", "rate limit"],
    "validation_error": ["validationerror", "validation failed", "schema", "pydantic"],
    "syntax_error": ["syntaxerror", "invalid syntax", "unexpected token"],
    "test_failure": ["assertionerror", "assert", "expected", "actual"],
}

# The 4 CLAW agents for cross-agent failure detection
CLAW_AGENT_IDS = {"claude", "codex", "gemini", "grok"}


class FailurePattern:
    """A recurring failure pattern detected across tasks."""

    def __init__(
        self,
        error_signature: str,
        count: int,
        task_ids: set[str],
        category: str,
        urgency: str,
        example_approaches: list[str],
        successful_resolution: Optional[str] = None,
        agent_ids: Optional[set[str]] = None,
    ):
        self.error_signature = error_signature
        self.count = count
        self.task_ids = task_ids
        self.category = category
        self.urgency = urgency
        self.example_approaches = example_approaches
        self.successful_resolution = successful_resolution
        self.agent_ids = agent_ids or set()

    def to_dict(self) -> dict[str, Any]:
        return {
            "error_signature": self.error_signature,
            "count": self.count,
            "task_count": len(self.task_ids),
            "category": self.category,
            "urgency": self.urgency,
            "example_approaches": self.example_approaches[:3],
            "has_resolution": self.successful_resolution is not None,
            "agent_ids": sorted(self.agent_ids),
            "all_agents_failed": self.agent_ids >= CLAW_AGENT_IDS,
        }


class ErrorKB:
    """Error knowledge base: tracks hypotheses and detects cross-task/cross-agent failure patterns.

    Injected dependencies:
        repository: Database access for hypothesis_log queries.
    """

    def __init__(self, repository: Repository):
        self.repository = repository

    async def record_attempt(
        self,
        task_id: str,
        attempt_number: int,
        approach_summary: str,
        outcome: HypothesisOutcome,
        error_signature: Optional[str] = None,
        error_full: Optional[str] = None,
        files_changed: Optional[list[str]] = None,
        duration_seconds: Optional[float] = None,
        model_used: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> HypothesisEntry:
        """Record an attempt in the hypothesis log.

        Args:
            task_id: The task being worked on.
            attempt_number: Which attempt this is.
            approach_summary: What was tried.
            outcome: SUCCESS or FAILURE.
            error_signature: Normalized error for deduplication.
            error_full: Full error text.
            files_changed: Files that were modified.
            duration_seconds: How long the attempt took.
            model_used: Which LLM model was used.
            agent_id: Which CLAW agent executed this attempt.

        Returns:
            The saved HypothesisEntry.
        """
        entry = HypothesisEntry(
            task_id=task_id,
            attempt_number=attempt_number,
            approach_summary=approach_summary,
            outcome=outcome,
            error_signature=error_signature,
            error_full=error_full,
            files_changed=files_changed or [],
            duration_seconds=duration_seconds,
            model_used=model_used,
            agent_id=agent_id,
        )
        return await self.repository.log_hypothesis(entry)

    async def get_forbidden_approaches(self, task_id: str) -> list[str]:
        """Get forbidden approaches for a task (local failures only).

        Args:
            task_id: The task to query.

        Returns:
            List of approach summaries that failed.
        """
        failed = await self.repository.get_failed_approaches(task_id)
        return [
            f"Attempt #{e.attempt_number}: {e.approach_summary}"
            + (f" (error: {e.error_signature})" if e.error_signature else "")
            + (f" [agent: {e.agent_id}]" if e.agent_id else "")
            for e in failed
        ]

    async def has_duplicate_error(self, task_id: str, error_signature: str) -> bool:
        """Check if this exact error has been seen before for this task.

        Args:
            task_id: The task to check.
            error_signature: Normalized error signature.

        Returns:
            True if this error already exists in the hypothesis log.
        """
        return await self.repository.has_duplicate_error(task_id, error_signature)

    async def get_enriched_forbidden_approaches(
        self, task_id: str, project_id: str
    ) -> list[str]:
        """Get forbidden approaches enriched with project-wide failure patterns.

        Combines task-local failures with recurring project-wide patterns.
        This is the cross-task pattern mining capability (Dirac P4 + GrokFlow P10).

        Args:
            task_id: The current task.
            project_id: The project for cross-task analysis.

        Returns:
            Enriched list of forbidden approaches including project patterns.
        """
        # Task-local forbidden approaches
        local = await self.get_forbidden_approaches(task_id)

        # Project-wide recurring patterns
        patterns = await self.get_common_failure_patterns(project_id, min_count=2)

        # Add project patterns as additional context
        project_warnings = []
        for pattern in patterns:
            if pattern.urgency in ("critical", "high"):
                warning = (
                    f"[PROJECT PATTERN - {pattern.urgency.upper()}] "
                    f"Error '{pattern.error_signature[:100]}' has occurred "
                    f"{pattern.count} times across {len(pattern.task_ids)} tasks"
                )
                if pattern.agent_ids:
                    warning += f" (agents: {', '.join(sorted(pattern.agent_ids))})"
                if pattern.successful_resolution:
                    warning += f". Successful resolution: {pattern.successful_resolution}"
                project_warnings.append(warning)

        return local + project_warnings

    async def get_common_failure_patterns(
        self,
        project_id: str,
        min_count: int = 2,
    ) -> list[FailurePattern]:
        """Detect recurring failure patterns across all tasks in a project.

        Adapted from GrokFlow's detect_recurring_bugs(). Groups failures
        by normalized error signature, counts occurrences, calculates urgency,
        and checks for successful resolutions.

        Args:
            project_id: The project to analyze.
            min_count: Minimum occurrence count to report.

        Returns:
            List of FailurePattern sorted by urgency then count.
        """
        # Get all tasks for this project across all statuses
        all_tasks = []
        for status in TaskStatus:
            tasks = await self.repository.get_tasks_by_status(project_id, status)
            all_tasks.extend(tasks)

        if not all_tasks:
            return []

        # Collect all failures across all tasks
        error_groups: dict[str, list[tuple[str, HypothesisEntry]]] = defaultdict(list)
        success_map: dict[str, list[str]] = defaultdict(list)
        agent_map: dict[str, set[str]] = defaultdict(set)

        for task in all_tasks:
            failed = await self.repository.get_failed_approaches(task.id)
            for entry in failed:
                if entry.error_signature:
                    error_groups[entry.error_signature].append((task.id, entry))
                    if entry.agent_id:
                        agent_map[entry.error_signature].add(entry.agent_id)

            # Also check for successful resolutions of the same errors
            # (entries where outcome is SUCCESS for a task that previously had this error)
            hypothesis_count = await self.repository.get_hypothesis_count(task.id)
            if hypothesis_count > 0 and task.status == TaskStatus.DONE:
                for entry in failed:
                    if entry.error_signature:
                        # This task had this error but eventually succeeded
                        success_map[entry.error_signature].append(
                            f"Task '{task.title}' resolved this error"
                        )

        # Build failure patterns
        patterns = []
        for error_sig, occurrences in error_groups.items():
            if len(occurrences) < min_count:
                continue

            task_ids = {task_id for task_id, _ in occurrences}
            approaches = [entry.approach_summary for _, entry in occurrences]
            category = _categorize_error(error_sig)
            urgency = _calculate_urgency(len(occurrences), len(task_ids))
            resolution = success_map.get(error_sig, [None])[0]

            patterns.append(
                FailurePattern(
                    error_signature=error_sig,
                    count=len(occurrences),
                    task_ids=task_ids,
                    category=category,
                    urgency=urgency,
                    example_approaches=approaches,
                    successful_resolution=resolution,
                    agent_ids=agent_map.get(error_sig, set()),
                )
            )

        # Sort by urgency (critical first) then by count
        urgency_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        patterns.sort(key=lambda p: (urgency_order.get(p.urgency, 4), -p.count))

        logger.info(
            "Found %d recurring failure patterns across %d tasks in project %s",
            len(patterns), len(all_tasks), project_id,
        )
        return patterns

    async def get_cross_agent_failures(
        self,
        project_id: Optional[str] = None,
        min_agents: int = 4,
    ) -> list[FailurePattern]:
        """Find errors where all 4 CLAW agents have failed the same way.

        This identifies fundamental problems that are not agent-specific --
        errors that transcend individual agent capabilities and likely require
        human intervention or a fundamentally different approach.

        Args:
            project_id: Optional project scope. None searches all projects.
            min_agents: Minimum number of distinct agents that must have failed.
                Defaults to 4 (all agents).

        Returns:
            List of FailurePattern where at least min_agents distinct agents
            failed with the same error signature, sorted by urgency.
        """
        # Get error signature statistics
        error_stats = await self.repository.get_hypothesis_error_stats(project_id)

        if not error_stats:
            return []

        cross_agent_patterns: list[FailurePattern] = []

        for stat in error_stats:
            error_sig = stat.get("error_signature")
            if not error_sig:
                continue

            # We need to check agent diversity for this error signature.
            # Query all tasks that have this error to gather agent IDs.
            if project_id:
                # Scope to project tasks
                all_tasks = []
                for status in TaskStatus:
                    tasks = await self.repository.get_tasks_by_status(project_id, status)
                    all_tasks.extend(tasks)
            else:
                # All tasks -- use in-progress + done as a broad sweep
                all_tasks = await self.repository.get_in_progress_tasks()

            agent_ids: set[str] = set()
            task_ids: set[str] = set()
            approaches: list[str] = []
            success_found: Optional[str] = None

            for task in all_tasks:
                failed = await self.repository.get_failed_approaches(task.id)
                for entry in failed:
                    if entry.error_signature == error_sig:
                        task_ids.add(task.id)
                        approaches.append(entry.approach_summary)
                        if entry.agent_id:
                            agent_ids.add(entry.agent_id)

                # Check if any task resolved this error
                if task.status == TaskStatus.DONE:
                    for entry in failed:
                        if entry.error_signature == error_sig and success_found is None:
                            success_found = f"Task '{task.title}' eventually resolved this"

            if len(agent_ids) >= min_agents:
                category = _categorize_error(error_sig)
                urgency = "critical"  # Cross-agent failures are always critical

                cross_agent_patterns.append(
                    FailurePattern(
                        error_signature=error_sig,
                        count=len(approaches),
                        task_ids=task_ids,
                        category=category,
                        urgency=urgency,
                        example_approaches=approaches,
                        successful_resolution=success_found,
                        agent_ids=agent_ids,
                    )
                )

        # Sort by count descending (all are critical urgency)
        cross_agent_patterns.sort(key=lambda p: -p.count)

        if cross_agent_patterns:
            logger.warning(
                "Found %d cross-agent failure patterns (all %d+ agents failed)",
                len(cross_agent_patterns), min_agents,
            )

        return cross_agent_patterns


def _categorize_error(error_signature: str) -> str:
    """Categorize an error by its signature.

    Adapted from GrokFlow's _categorize_patterns with Python-domain keywords.

    Args:
        error_signature: Normalized error string.

    Returns:
        Category name string.
    """
    sig_lower = error_signature.lower()

    for category, keywords in ERROR_CATEGORIES.items():
        for keyword in keywords:
            if keyword in sig_lower:
                return category

    return "unknown"


def _calculate_urgency(count: int, num_tasks: int) -> str:
    """Calculate urgency based on frequency and spread.

    Adapted from GrokFlow's _calculate_urgency.

    Args:
        count: Total number of occurrences.
        num_tasks: Number of distinct tasks affected.

    Returns:
        Urgency level: "critical", "high", "medium", or "low".
    """
    if count >= 5 or num_tasks >= 3:
        return "critical"
    if count >= 3 or num_tasks >= 2:
        return "high"
    if count >= 2:
        return "medium"
    return "low"


def normalize_error_for_dedup(error_text: str) -> str:
    """Standalone error normalization for cross-task deduplication.

    Strips the error text and applies normalizations to produce a
    stable signature for grouping equivalent errors:
    - Removes UUIDs
    - Removes quoted strings
    - Removes timestamps (ISO-8601 and common formats)
    - Removes file paths
    - Removes line numbers
    - Collapses whitespace

    Args:
        error_text: Raw error text.

    Returns:
        Normalized error signature.
    """
    sig = error_text.strip()

    # Remove UUIDs
    sig = re.sub(
        r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',
        '<UUID>', sig,
    )

    # Remove quoted strings (single and double)
    sig = re.sub(r"'[^']*'", "'<STR>'", sig)
    sig = re.sub(r'"[^"]*"', '"<STR>"', sig)

    # Remove ISO-8601 timestamps (e.g., 2026-03-03T14:30:00Z, 2026-03-03 14:30:00+00:00)
    sig = re.sub(
        r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?',
        '<TIMESTAMP>', sig,
    )

    # Remove common timestamp formats (e.g., Mar 03 14:30:00)
    sig = re.sub(
        r'(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}',
        '<TIMESTAMP>', sig,
    )

    # Remove file paths (Unix-style: /foo/bar/baz.py and relative: ./foo/bar.py, src/foo.py)
    sig = re.sub(r'(?:/[\w./-]+)+', '<PATH>', sig)
    sig = re.sub(r'\.?/[\w./-]+', '<PATH>', sig)

    # Remove line numbers (e.g., "line 42", ":42:", "Line 123")
    sig = re.sub(r'[Ll]ine\s+\d+', 'line <NUM>', sig)
    sig = re.sub(r':\d+:', ':<NUM>:', sig)

    # Remove standalone numbers
    sig = re.sub(r'\b\d+\b', '<NUM>', sig)

    # Collapse whitespace
    sig = re.sub(r'\s+', ' ', sig).strip()

    # Collapse repeated normalized tokens
    sig = re.sub(r'(<\w+>)\s*\1+', r'\1', sig)

    return sig
