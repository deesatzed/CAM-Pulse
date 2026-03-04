"""Fleet orchestration for CLAW.

Manages enhancement runs across multiple repositories in the fleet. Handles
repo discovery, registration, priority-based ranking, budget allocation, and
enhancement branch creation.

The FleetOrchestrator operates at the Macro Claw level — it scans the repo
fleet, ranks repos by enhancement potential, allocates budgets, and coordinates
the meso-level evaluation cycles for each repo.

All data is persisted to the ``fleet_repos`` table via the Repository/Engine
layer. Git operations use gitpython when available, falling back to subprocess.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

from claw.core.config import ClawConfig
from claw.db.repository import Repository

logger = logging.getLogger("claw.fleet")

# Attempt to import gitpython; fall back to subprocess-based git operations
try:
    import git as gitpython

    HAS_GITPYTHON = True
except ImportError:
    HAS_GITPYTHON = False
    logger.info("gitpython not available; git operations will use subprocess")


class FleetOrchestrator:
    """Orchestrates enhancement runs across a fleet of repositories.

    Responsibilities:
        - Scan directories for git repositories
        - Register and track repos in the fleet_repos table
        - Rank repos by priority, staleness, and evaluation score
        - Allocate token/cost budgets across repos
        - Create enhancement branches for agent work
        - Provide fleet-wide summary statistics

    Usage::

        orchestrator = FleetOrchestrator(repository, config)
        repos = await orchestrator.scan_repos("/path/to/repos")
        for repo_info in repos:
            await orchestrator.register_repo(repo_info["path"], repo_info["name"])
        ranked = await orchestrator.rank_repos()
        allocations = await orchestrator.allocate_budget(total_budget_usd=50.0)
    """

    def __init__(self, repository: Repository, config: ClawConfig) -> None:
        """Initialize the FleetOrchestrator.

        Args:
            repository: Data access layer for database operations.
            config: CLAW configuration containing fleet settings.
        """
        self.repository = repository
        self.config = config
        self._fleet_config = config.fleet
        logger.info(
            "FleetOrchestrator initialized: branch_prefix='%s', "
            "max_concurrent=%d, max_cost_per_repo=$%.2f",
            self._fleet_config.enhancement_branch_prefix,
            self._fleet_config.max_concurrent_repos,
            self._fleet_config.max_cost_per_repo_usd,
        )

    # -------------------------------------------------------------------
    # Repo Discovery
    # -------------------------------------------------------------------

    async def scan_repos(self, base_path: str) -> list[dict[str, Any]]:
        """Scan a directory tree for git repositories.

        Walks the directory looking for ``.git`` directories. For each repo
        found, extracts the repo name from the directory name and gathers
        basic metadata.

        Args:
            base_path: Root directory to scan for git repositories.

        Returns:
            List of dicts with keys: ``path``, ``name``, ``has_remote``,
            ``default_branch``, ``last_commit_date``.

        Raises:
            FileNotFoundError: If base_path does not exist.
            NotADirectoryError: If base_path is not a directory.
        """
        base = Path(base_path).resolve()
        if not base.exists():
            raise FileNotFoundError(f"Scan path does not exist: {base}")
        if not base.is_dir():
            raise NotADirectoryError(f"Scan path is not a directory: {base}")

        discovered: list[dict[str, Any]] = []

        logger.info("Scanning for git repos under: %s", base)

        for entry in sorted(base.iterdir()):
            if not entry.is_dir():
                continue

            git_dir = entry / ".git"
            if not git_dir.exists():
                continue

            repo_path = str(entry)
            repo_name = entry.name

            repo_info: dict[str, Any] = {
                "path": repo_path,
                "name": repo_name,
                "has_remote": False,
                "default_branch": None,
                "last_commit_date": None,
            }

            # Extract metadata via gitpython or subprocess
            try:
                repo_info.update(self._get_repo_metadata(repo_path))
            except Exception as exc:
                logger.warning(
                    "Failed to read metadata for %s: %s", repo_path, exc,
                )

            discovered.append(repo_info)

        logger.info("Discovered %d git repositories under %s", len(discovered), base)
        return discovered

    def _get_repo_metadata(self, repo_path: str) -> dict[str, Any]:
        """Extract git metadata from a repository.

        Args:
            repo_path: Absolute path to the repository root.

        Returns:
            Dict with ``has_remote``, ``default_branch``, ``last_commit_date``.
        """
        metadata: dict[str, Any] = {
            "has_remote": False,
            "default_branch": None,
            "last_commit_date": None,
        }

        if HAS_GITPYTHON:
            try:
                repo = gitpython.Repo(repo_path)

                # Check for remotes
                if repo.remotes:
                    metadata["has_remote"] = True

                # Determine default branch
                try:
                    metadata["default_branch"] = repo.active_branch.name
                except TypeError:
                    # Detached HEAD state
                    metadata["default_branch"] = None

                # Get last commit date
                if repo.head.is_valid():
                    last_commit = repo.head.commit
                    metadata["last_commit_date"] = datetime.fromtimestamp(
                        last_commit.committed_date, tz=UTC
                    ).isoformat()

            except gitpython.InvalidGitRepositoryError:
                logger.warning("Invalid git repo (gitpython): %s", repo_path)
            except Exception as exc:
                logger.warning("gitpython error for %s: %s", repo_path, exc)
        else:
            # Subprocess fallback
            try:
                # Check remotes
                result = subprocess.run(
                    ["git", "remote"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    metadata["has_remote"] = True

                # Get current branch
                result = subprocess.run(
                    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    branch = result.stdout.strip()
                    if branch != "HEAD":
                        metadata["default_branch"] = branch

                # Get last commit date
                result = subprocess.run(
                    ["git", "log", "-1", "--format=%aI"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0 and result.stdout.strip():
                    metadata["last_commit_date"] = result.stdout.strip()

            except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
                logger.warning("Subprocess git error for %s: %s", repo_path, exc)

        return metadata

    # -------------------------------------------------------------------
    # Registration & Retrieval
    # -------------------------------------------------------------------

    async def register_repo(
        self,
        repo_path: str,
        repo_name: str,
        priority: float = 0.0,
    ) -> str:
        """Register a repository in the fleet tracking table.

        If the repo already exists (by path), the existing record is returned
        without modification. Use ``update_repo_status`` to change fields.

        Args:
            repo_path: Absolute path to the repository root.
            repo_name: Human-readable name for the repository.
            priority: Initial priority score (higher = processed sooner).

        Returns:
            The repo ID (UUID string) of the registered or existing record.
        """
        resolved_path = str(Path(repo_path).resolve())

        # Check if already registered
        existing = await self.get_repo_by_path(resolved_path)
        if existing:
            logger.info(
                "Repo already registered: %s (id=%s)",
                resolved_path, existing["id"],
            )
            return existing["id"]

        repo_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()

        await self.repository.engine.execute(
            """INSERT INTO fleet_repos
               (id, repo_path, repo_name, priority, status,
                budget_allocated_usd, budget_used_usd,
                tasks_created, tasks_completed,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, 'pending', 0.0, 0.0, 0, 0, ?, ?)""",
            [repo_id, resolved_path, repo_name, priority, now, now],
        )

        logger.info(
            "Registered fleet repo: name='%s', path='%s', id=%s, priority=%.2f",
            repo_name, resolved_path, repo_id, priority,
        )
        return repo_id

    async def get_repos(
        self,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List fleet repositories, optionally filtered by status.

        Args:
            status: Filter by status (e.g., ``'pending'``, ``'enhancing'``).
                    If None, returns all repos.
            limit: Maximum number of repos to return.

        Returns:
            List of fleet repo dicts ordered by priority descending.
        """
        if status:
            rows = await self.repository.engine.fetch_all(
                "SELECT * FROM fleet_repos WHERE status = ? ORDER BY priority DESC LIMIT ?",
                [status, limit],
            )
        else:
            rows = await self.repository.engine.fetch_all(
                "SELECT * FROM fleet_repos ORDER BY priority DESC LIMIT ?",
                [limit],
            )

        logger.debug(
            "Retrieved %d fleet repos (status=%s, limit=%d)",
            len(rows), status or "all", limit,
        )
        return rows

    async def get_repo_by_path(self, repo_path: str) -> Optional[dict[str, Any]]:
        """Look up a fleet repository by its filesystem path.

        Args:
            repo_path: Absolute path to the repository root.

        Returns:
            The fleet repo dict if found, None otherwise.
        """
        resolved_path = str(Path(repo_path).resolve())
        row = await self.repository.engine.fetch_one(
            "SELECT * FROM fleet_repos WHERE repo_path = ?",
            [resolved_path],
        )
        return row

    # -------------------------------------------------------------------
    # Ranking
    # -------------------------------------------------------------------

    async def rank_repos(self) -> list[dict[str, Any]]:
        """Rank all fleet repositories by composite score.

        Scoring formula (weighted sum):
            - Priority weight (40%): normalized priority value
            - Staleness weight (30%): days since last evaluation (more stale = higher score)
            - Evaluation score weight (30%): inverse of existing evaluation score
              (lower-scored repos get prioritized for re-evaluation)

        Repos with status ``'completed'`` or ``'skipped'`` are excluded.

        Returns:
            List of repo dicts with an added ``rank_score`` field, sorted
            descending by rank_score.
        """
        rows = await self.repository.engine.fetch_all(
            """SELECT * FROM fleet_repos
               WHERE status NOT IN ('completed', 'skipped')
               ORDER BY priority DESC""",
        )

        if not rows:
            logger.info("No rankable repos found in fleet")
            return []

        now = datetime.now(UTC)

        # Compute normalization ranges
        priorities = [row["priority"] for row in rows]
        max_priority = max(priorities) if priorities else 1.0
        min_priority = min(priorities) if priorities else 0.0
        priority_range = max_priority - min_priority if max_priority != min_priority else 1.0

        ranked: list[dict[str, Any]] = []

        for row in rows:
            repo = dict(row)

            # Priority component (0.0 - 1.0, normalized)
            priority_norm = (repo["priority"] - min_priority) / priority_range

            # Staleness component (days since last evaluation)
            staleness_score = 0.0
            if repo.get("last_evaluated_at"):
                try:
                    last_eval = datetime.fromisoformat(repo["last_evaluated_at"])
                    if last_eval.tzinfo is None:
                        last_eval = last_eval.replace(tzinfo=UTC)
                    days_since = (now - last_eval).total_seconds() / 86400.0
                    # Cap staleness at 365 days and normalize
                    staleness_score = min(days_since / 365.0, 1.0)
                except (ValueError, TypeError):
                    staleness_score = 1.0  # Unparseable date = treat as very stale
            else:
                # Never evaluated = maximum staleness
                staleness_score = 1.0

            # Evaluation score component (inverse: low-scored repos rank higher)
            eval_score_component = 0.0
            if repo.get("evaluation_score") is not None:
                # Invert: a repo with score 0.2 (poor) gets eval_component 0.8
                eval_score_component = 1.0 - min(repo["evaluation_score"], 1.0)
            else:
                # Never evaluated = high priority
                eval_score_component = 1.0

            # Weighted composite
            rank_score = (
                0.40 * priority_norm
                + 0.30 * staleness_score
                + 0.30 * eval_score_component
            )

            repo["rank_score"] = round(rank_score, 4)
            ranked.append(repo)

        # Sort by rank_score descending
        ranked.sort(key=lambda r: r["rank_score"], reverse=True)

        logger.info(
            "Ranked %d repos. Top: %s (score=%.4f), Bottom: %s (score=%.4f)",
            len(ranked),
            ranked[0]["repo_name"] if ranked else "N/A",
            ranked[0]["rank_score"] if ranked else 0.0,
            ranked[-1]["repo_name"] if ranked else "N/A",
            ranked[-1]["rank_score"] if ranked else 0.0,
        )

        return ranked

    # -------------------------------------------------------------------
    # Budget Allocation
    # -------------------------------------------------------------------

    async def allocate_budget(
        self,
        total_budget_usd: float,
        strategy: str = "proportional",
    ) -> dict[str, Any]:
        """Allocate a total USD budget across fleet repositories.

        Supports two strategies:
            - ``"proportional"``: Budget is distributed proportional to each
              repo's priority score. Repos with higher priority get more budget.
            - ``"equal"``: Budget is split equally across all eligible repos.

        Each repo's allocation is capped at ``config.fleet.max_cost_per_repo_usd``.

        Args:
            total_budget_usd: Total budget to distribute across repos.
            strategy: Allocation strategy — ``"proportional"`` or ``"equal"``.

        Returns:
            Dict with ``strategy``, ``total_budget_usd``, ``allocated_usd``,
            ``repos_allocated`` count, and ``allocations`` list of per-repo
            dicts with ``repo_id``, ``repo_name``, ``allocated_usd``.

        Raises:
            ValueError: If strategy is not recognized or budget is negative.
        """
        if total_budget_usd < 0:
            raise ValueError(f"Budget must be non-negative, got {total_budget_usd}")

        if strategy not in ("proportional", "equal"):
            raise ValueError(
                f"Unknown budget strategy: '{strategy}'. "
                f"Supported: 'proportional', 'equal'."
            )

        # Fetch repos eligible for budget allocation (not completed/skipped)
        repos = await self.repository.engine.fetch_all(
            """SELECT * FROM fleet_repos
               WHERE status NOT IN ('completed', 'skipped')
               ORDER BY priority DESC""",
        )

        if not repos:
            logger.info("No eligible repos for budget allocation")
            return {
                "strategy": strategy,
                "total_budget_usd": total_budget_usd,
                "allocated_usd": 0.0,
                "repos_allocated": 0,
                "allocations": [],
            }

        max_per_repo = self._fleet_config.max_cost_per_repo_usd
        allocations: list[dict[str, Any]] = []
        total_allocated = 0.0
        now = datetime.now(UTC).isoformat()

        if strategy == "equal":
            per_repo = total_budget_usd / len(repos)
            capped_per_repo = min(per_repo, max_per_repo)

            for repo in repos:
                allocation = capped_per_repo
                allocations.append({
                    "repo_id": repo["id"],
                    "repo_name": repo["repo_name"],
                    "allocated_usd": round(allocation, 4),
                })

                # Persist allocation to database
                await self.repository.engine.execute(
                    """UPDATE fleet_repos
                       SET budget_allocated_usd = ?, updated_at = ?
                       WHERE id = ?""",
                    [allocation, now, repo["id"]],
                )
                total_allocated += allocation

        elif strategy == "proportional":
            # Compute proportional shares based on priority
            total_priority = sum(max(r["priority"], 0.01) for r in repos)

            for repo in repos:
                priority = max(repo["priority"], 0.01)
                share = priority / total_priority
                allocation = min(share * total_budget_usd, max_per_repo)

                allocations.append({
                    "repo_id": repo["id"],
                    "repo_name": repo["repo_name"],
                    "allocated_usd": round(allocation, 4),
                })

                # Persist allocation to database
                await self.repository.engine.execute(
                    """UPDATE fleet_repos
                       SET budget_allocated_usd = ?, updated_at = ?
                       WHERE id = ?""",
                    [allocation, now, repo["id"]],
                )
                total_allocated += allocation

        result = {
            "strategy": strategy,
            "total_budget_usd": total_budget_usd,
            "allocated_usd": round(total_allocated, 4),
            "repos_allocated": len(allocations),
            "allocations": allocations,
        }

        logger.info(
            "Budget allocation complete: strategy='%s', total=$%.2f, "
            "allocated=$%.2f across %d repos",
            strategy, total_budget_usd, total_allocated, len(allocations),
        )

        return result

    # -------------------------------------------------------------------
    # Status Management
    # -------------------------------------------------------------------

    async def update_repo_status(
        self,
        repo_id: str,
        status: str,
        **kwargs: Any,
    ) -> None:
        """Update a fleet repository's status and optional fields.

        Args:
            repo_id: UUID of the fleet repo to update.
            status: New status value. Must be one of: ``'pending'``,
                    ``'evaluating'``, ``'enhancing'``, ``'completed'``,
                    ``'failed'``, ``'skipped'``.
            **kwargs: Additional fields to update. Supported keys:
                      ``enhancement_branch``, ``last_evaluated_at``,
                      ``evaluation_score``, ``budget_used_usd``,
                      ``tasks_created``, ``tasks_completed``.

        Raises:
            ValueError: If status is not a valid fleet repo status.
        """
        valid_statuses = {
            "pending", "evaluating", "enhancing", "completed", "failed", "skipped",
        }
        if status not in valid_statuses:
            raise ValueError(
                f"Invalid fleet repo status: '{status}'. "
                f"Valid: {sorted(valid_statuses)}"
            )

        now = datetime.now(UTC).isoformat()

        # Build dynamic SET clause from kwargs
        set_parts = ["status = ?", "updated_at = ?"]
        params: list[Any] = [status, now]

        allowed_fields = {
            "enhancement_branch",
            "last_evaluated_at",
            "evaluation_score",
            "budget_used_usd",
            "tasks_created",
            "tasks_completed",
            "budget_allocated_usd",
        }

        for field, value in kwargs.items():
            if field in allowed_fields:
                set_parts.append(f"{field} = ?")
                params.append(value)
            else:
                logger.warning(
                    "Ignoring unknown field '%s' in update_repo_status", field,
                )

        params.append(repo_id)

        query = f"UPDATE fleet_repos SET {', '.join(set_parts)} WHERE id = ?"
        await self.repository.engine.execute(query, params)

        logger.info(
            "Updated fleet repo %s: status='%s', extra_fields=%s",
            repo_id, status, list(kwargs.keys()),
        )

    # -------------------------------------------------------------------
    # Fleet Summary
    # -------------------------------------------------------------------

    async def get_fleet_summary(self) -> dict[str, Any]:
        """Get summary statistics for the entire fleet.

        Returns:
            Dict with:
                - ``total_repos``: Total number of registered repos
                - ``by_status``: Dict mapping status -> count
                - ``total_budget_allocated_usd``: Sum of all allocated budgets
                - ``total_budget_used_usd``: Sum of all used budgets
                - ``total_tasks_created``: Sum of tasks created across repos
                - ``total_tasks_completed``: Sum of tasks completed across repos
                - ``completion_rate``: Fraction of tasks completed (0.0-1.0)
        """
        # Count by status
        status_rows = await self.repository.engine.fetch_all(
            "SELECT status, COUNT(*) as cnt FROM fleet_repos GROUP BY status",
        )
        by_status = {row["status"]: row["cnt"] for row in status_rows}

        # Aggregate totals
        totals_row = await self.repository.engine.fetch_one(
            """SELECT
                   COUNT(*) as total_repos,
                   COALESCE(SUM(budget_allocated_usd), 0.0) as total_allocated,
                   COALESCE(SUM(budget_used_usd), 0.0) as total_used,
                   COALESCE(SUM(tasks_created), 0) as total_tasks_created,
                   COALESCE(SUM(tasks_completed), 0) as total_tasks_completed
               FROM fleet_repos""",
        )

        total_repos = totals_row["total_repos"] if totals_row else 0
        total_allocated = totals_row["total_allocated"] if totals_row else 0.0
        total_used = totals_row["total_used"] if totals_row else 0.0
        total_tasks_created = totals_row["total_tasks_created"] if totals_row else 0
        total_tasks_completed = totals_row["total_tasks_completed"] if totals_row else 0

        completion_rate = 0.0
        if total_tasks_created > 0:
            completion_rate = total_tasks_completed / total_tasks_created

        summary = {
            "total_repos": total_repos,
            "by_status": by_status,
            "total_budget_allocated_usd": round(total_allocated, 4),
            "total_budget_used_usd": round(total_used, 4),
            "total_tasks_created": total_tasks_created,
            "total_tasks_completed": total_tasks_completed,
            "completion_rate": round(completion_rate, 4),
        }

        logger.info(
            "Fleet summary: %d repos, $%.2f allocated, $%.2f used, "
            "%d/%d tasks (%.1f%% complete)",
            total_repos, total_allocated, total_used,
            total_tasks_completed, total_tasks_created,
            completion_rate * 100,
        )

        return summary

    # -------------------------------------------------------------------
    # Git Branch Operations
    # -------------------------------------------------------------------

    async def create_enhancement_branch(
        self,
        repo_path: str,
        branch_prefix: Optional[str] = None,
    ) -> str:
        """Create an enhancement branch in a repository.

        Creates a new branch named ``{prefix}/{timestamp}`` from the current
        HEAD. The branch is checked out after creation.

        All agent work goes to enhancement branches — never directly to main.

        Args:
            repo_path: Absolute path to the repository root.
            branch_prefix: Branch name prefix. Defaults to the configured
                           ``fleet.enhancement_branch_prefix`` (``claw/enhancement``).

        Returns:
            The full branch name that was created (e.g.,
            ``claw/enhancement/20260303T120000``).

        Raises:
            RuntimeError: If branch creation fails.
        """
        if branch_prefix is None:
            branch_prefix = self._fleet_config.enhancement_branch_prefix

        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        branch_name = f"{branch_prefix}/{timestamp}"

        if HAS_GITPYTHON:
            try:
                repo = gitpython.Repo(repo_path)
                new_branch = repo.create_head(branch_name)
                new_branch.checkout()
                logger.info(
                    "Created enhancement branch '%s' in %s (gitpython)",
                    branch_name, repo_path,
                )
                return branch_name
            except Exception as exc:
                raise RuntimeError(
                    f"Failed to create branch '{branch_name}' in {repo_path}: {exc}"
                ) from exc
        else:
            # Subprocess fallback
            try:
                result = subprocess.run(
                    ["git", "checkout", "-b", branch_name],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode != 0:
                    raise RuntimeError(
                        f"git checkout -b failed (rc={result.returncode}): "
                        f"{result.stderr.strip()}"
                    )
                logger.info(
                    "Created enhancement branch '%s' in %s (subprocess)",
                    branch_name, repo_path,
                )
                return branch_name
            except subprocess.TimeoutExpired as exc:
                raise RuntimeError(
                    f"Timed out creating branch '{branch_name}' in {repo_path}"
                ) from exc
            except FileNotFoundError as exc:
                raise RuntimeError(
                    f"git command not found. Install git to create branches."
                ) from exc
