"""CAM Self-Enhancement Pipeline.

Implements the compiler-bootstrap pattern: clone → enhance → validate → swap.

After mining or PULSE ingestion adds new knowledge, CAM assesses whether the
accumulated knowledge justifies rebuilding itself.  When triggered, it creates
an enhanced copy, runs the MesoClaw pipeline against it, validates through
7 gates (validation_gate.py), and swaps into production only if all gates pass.

Usage:
    from claw.reconstruct import ReconstructionPipeline

    pipeline = ReconstructionPipeline(config, db_engine)
    assessment = await pipeline.assess_trigger()
    if assessment.should_trigger:
        result = await pipeline.run()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from claw.core.config import ClawConfig, SelfEnhanceConfig, load_config
from claw.validation_gate import (
    DiffSummary,
    ValidationConfig,
    ValidationReport,
    run_all_gates,
)

logger = logging.getLogger("claw.reconstruct")


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class TriggerAssessment:
    """Result of evaluating whether self-enhancement should run."""
    should_trigger: bool
    reasons: list[str] = field(default_factory=list)
    new_methodologies_count: int = 0
    avg_novelty_score: float = 0.0
    hours_since_last_enhance: float = 0.0
    cooldown_remaining_hours: float = 0.0

    def summary(self) -> str:
        lines = []
        if self.should_trigger:
            lines.append("TRIGGER: Self-enhancement recommended")
        else:
            lines.append("NO TRIGGER: Self-enhancement not needed")
        for r in self.reasons:
            lines.append(f"  - {r}")
        lines.append(
            f"  New methodologies: {self.new_methodologies_count} | "
            f"Avg novelty: {self.avg_novelty_score:.2f} | "
            f"Hours since last: {self.hours_since_last_enhance:.1f}"
        )
        if self.cooldown_remaining_hours > 0:
            lines.append(f"  Cooldown remaining: {self.cooldown_remaining_hours:.1f}h")
        return "\n".join(lines)


@dataclass
class ProtectedFileChange:
    """A change detected in a protected file."""
    file_path: str
    additions: int
    deletions: int


@dataclass
class EnhancementResult:
    """Result of the full self-enhancement pipeline."""
    success: bool
    phase_reached: str  # "clone", "enhance", "validate", "swap", "post_swap", "complete"
    copy_dir: Optional[Path] = None
    backup_dir: Optional[Path] = None
    validation_report: Optional[ValidationReport] = None
    diff_summary: Optional[DiffSummary] = None
    protected_file_changes: list[ProtectedFileChange] = field(default_factory=list)
    tasks_executed: int = 0
    tasks_succeeded: int = 0
    error: Optional[str] = None
    duration_seconds: float = 0.0
    swap_completed: bool = False
    rollback_performed: bool = False

    def summary(self) -> str:
        lines = [
            f"Self-Enhancement Result: {'SUCCESS' if self.success else 'FAILED'}",
            f"Phase reached: {self.phase_reached}",
            f"Duration: {self.duration_seconds:.1f}s",
        ]
        if self.tasks_executed > 0:
            lines.append(
                f"Tasks: {self.tasks_succeeded}/{self.tasks_executed} succeeded"
            )
        if self.protected_file_changes:
            lines.append(
                f"Protected file changes: {len(self.protected_file_changes)} "
                f"(requires human review)"
            )
        if self.validation_report:
            lines.append(f"Validation: {self.validation_report.summary()}")
        if self.error:
            lines.append(f"Error: {self.error}")
        if self.swap_completed:
            lines.append("Swap: COMPLETED (enhanced copy is now live)")
        if self.rollback_performed:
            lines.append("Rollback: PERFORMED (restored from backup)")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# State tracking
# ---------------------------------------------------------------------------

_STATE_FILE = "data/self_enhance_state.json"


def _load_state(live_dir: Path) -> dict[str, Any]:
    """Load self-enhancement state from JSON file."""
    state_path = live_dir / _STATE_FILE
    if state_path.exists():
        try:
            return json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_state(live_dir: Path, state: dict[str, Any]) -> None:
    """Save self-enhancement state."""
    state_path = live_dir / _STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, default=str))


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class ReconstructionPipeline:
    """Orchestrates CAM's self-enhancement cycle.

    The pipeline follows the compiler-bootstrap pattern:
    1. Clone the live install to a workspace copy
    2. Run enhancement (MesoClaw) against the copy
    3. Validate the copy through 7 gates
    4. If validation passes and no protected-file issues, swap
    5. Post-swap validate (quick smoke test)
    6. On failure at any stage, rollback is available
    """

    def __init__(
        self,
        config: ClawConfig,
        db_engine: Any = None,
        live_dir: Optional[Path] = None,
        on_step: Any = None,
    ):
        self.config = config
        self.se_config = config.self_enhance
        self.db_engine = db_engine
        self.live_dir = live_dir or Path.cwd().resolve()
        self.on_step = on_step
        self._state = _load_state(self.live_dir)

    # -----------------------------------------------------------------------
    # Trigger assessment
    # -----------------------------------------------------------------------

    async def assess_trigger(self) -> TriggerAssessment:
        """Evaluate whether self-enhancement should run now.

        Checks:
        1. Cooldown period since last run
        2. Number of new methodologies since last enhance
        3. Average novelty score of new methodologies
        4. Whether self-enhance is enabled
        """
        assessment = TriggerAssessment(should_trigger=False)

        if not self.se_config.enabled:
            assessment.reasons.append("self_enhance.enabled is false in config")
            return assessment

        # Cooldown check
        last_run_iso = self._state.get("last_enhance_completed_at")
        if last_run_iso:
            try:
                last_run = datetime.fromisoformat(last_run_iso)
                now = datetime.now(UTC)
                hours_since = (now - last_run).total_seconds() / 3600
                assessment.hours_since_last_enhance = hours_since
                if hours_since < self.se_config.cooldown_hours:
                    assessment.cooldown_remaining_hours = (
                        self.se_config.cooldown_hours - hours_since
                    )
                    assessment.reasons.append(
                        f"Cooldown active: {assessment.cooldown_remaining_hours:.1f}h remaining "
                        f"(min {self.se_config.cooldown_hours}h between runs)"
                    )
                    return assessment
            except (ValueError, TypeError):
                pass

        # Query DB for new methodologies since last enhance
        last_methodology_count = self._state.get("methodology_count_at_last_enhance", 0)
        new_count = 0
        avg_novelty = 0.0

        if self.db_engine:
            try:
                from claw.db.repository import Repository
                repo = Repository(self.db_engine)
                total_count = await repo.count_methodologies()
                new_count = max(0, total_count - last_methodology_count)
                assessment.new_methodologies_count = new_count

                # Get avg novelty of recent methodologies
                if new_count > 0:
                    rows = await self.db_engine.fetch_all(
                        """SELECT AVG(novelty_score) as avg_nov
                           FROM methodologies
                           WHERE novelty_score IS NOT NULL
                           ORDER BY created_at DESC
                           LIMIT ?""",
                        [new_count],
                    )
                    if rows and rows[0]["avg_nov"] is not None:
                        avg_novelty = float(rows[0]["avg_nov"])
                        assessment.avg_novelty_score = avg_novelty
            except Exception as e:
                assessment.reasons.append(f"DB query error: {e}")

        # Evaluate trigger conditions
        triggered_reasons = []

        if new_count >= self.se_config.min_new_methodologies:
            triggered_reasons.append(
                f"New methodology threshold met: {new_count} >= {self.se_config.min_new_methodologies}"
            )

        if avg_novelty >= self.se_config.min_avg_novelty_score and new_count > 0:
            triggered_reasons.append(
                f"Novelty threshold met: {avg_novelty:.2f} >= {self.se_config.min_avg_novelty_score}"
            )

        if triggered_reasons:
            assessment.should_trigger = True
            assessment.reasons = triggered_reasons
        else:
            assessment.reasons.append(
                f"No trigger conditions met (new_methodologies={new_count}/{self.se_config.min_new_methodologies}, "
                f"avg_novelty={avg_novelty:.2f}/{self.se_config.min_avg_novelty_score})"
            )

        return assessment

    # -----------------------------------------------------------------------
    # Phase 1: Clone
    # -----------------------------------------------------------------------

    def _resolve_workspace_parent(self) -> Path:
        """Determine where to create the enhanced copy.

        Prefers same volume as live_dir for potential atomic rename.
        Falls back to config.workspace_parent if set.
        """
        if self.se_config.workspace_parent:
            return Path(self.se_config.workspace_parent)
        # Same parent directory as live
        return self.live_dir.parent

    def clone(self) -> Path:
        """Phase 1: Create a full copy of the live installation.

        Returns the path to the copy directory.
        Excludes: .git, __pycache__, data/ (DB), .venv, node_modules
        """
        workspace_parent = self._resolve_workspace_parent()
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        copy_dir = workspace_parent / f"cam-self-enhance-{timestamp}"

        logger.info("Cloning live install %s → %s", self.live_dir, copy_dir)

        # Only these top-level directories are part of the CAM source tree.
        # Everything else (cloned repos, evaluation outputs, etc.) is excluded.
        _SOURCE_DIRS = {
            "src", "tests", "scripts", "prompts", "docs",
            "apps", ".github",
        }
        _SOURCE_FILES_EXTS = {
            ".toml", ".cfg", ".ini", ".txt", ".md", ".py", ".sh",
            ".env", ".gitignore", ".json",
        }

        def _ignore(directory: str, contents: list[str]) -> list[str]:
            """Ignore patterns for shutil.copytree."""
            ignored = []
            rel_dir = os.path.relpath(directory, str(self.live_dir))

            for item in contents:
                item_path = os.path.join(directory, item)
                is_dir = os.path.isdir(item_path)

                # Always skip these directories
                if item in (
                    ".git", "__pycache__", ".venv", "venv",
                    "node_modules", ".mypy_cache", ".pytest_cache",
                    ".ruff_cache", "data", "tmp",
                ):
                    ignored.append(item)
                    continue

                # At top level, only copy known source dirs + config files
                if rel_dir == ".":
                    if is_dir and item not in _SOURCE_DIRS:
                        ignored.append(item)
                        continue
                    if not is_dir:
                        _, ext = os.path.splitext(item)
                        if ext not in _SOURCE_FILES_EXTS and item not in (
                            "Makefile", "LICENSE", "Dockerfile",
                        ):
                            ignored.append(item)
                            continue

                # Skip evaluation artifacts anywhere
                if item.endswith("_evaluation.md") or item.endswith("_evaluation.json"):
                    ignored.append(item)
                    continue

            return ignored

        shutil.copytree(
            str(self.live_dir),
            str(copy_dir),
            ignore=_ignore,
            dirs_exist_ok=False,
        )

        # Copy .env for agent API keys
        live_env = self.live_dir / ".env"
        if live_env.exists():
            shutil.copy2(str(live_env), str(copy_dir / ".env"))

        logger.info("Clone complete: %s", copy_dir)
        return copy_dir

    # -----------------------------------------------------------------------
    # Phase 2: Enhance
    # -----------------------------------------------------------------------

    async def enhance(
        self,
        copy_dir: Path,
        mode: str = "autonomous",
        max_tasks: int = 0,
    ) -> tuple[int, int]:
        """Phase 2: Run MicroClaw enhancement against the copy.

        Follows the same pattern as ``cam enhance <repo>``:
        1. Create ClawContext pointing at the copy
        2. Structural analysis → gap identification → task generation
        3. Execute tasks via MicroClaw cycles

        Returns (tasks_executed, tasks_succeeded).
        """
        if max_tasks <= 0:
            max_tasks = self.se_config.max_enhance_tasks

        logger.info("Enhancing copy at %s (mode=%s, max_tasks=%d)", copy_dir, mode, max_tasks)

        from claw.core.factory import ClawFactory
        from claw.core.models import Project
        from claw.cycle import MicroClaw
        from claw.planner import EvaluationResult, Planner

        # Load config from the COPY so enhanced code is self-consistent
        copy_toml = copy_dir / "claw.toml"

        # Create context pointing at the copy
        ctx = await ClawFactory.create(
            workspace_dir=copy_dir,
            config_path=copy_toml if copy_toml.exists() else None,
        )

        try:
            # Create a transient project for the copy
            project = Project(
                name="cam-self-enhance",
                repo_path=str(copy_dir),
            )
            await ctx.repository.create_project(project)

            # Phase 2a: Structural analysis (same as _analyze_repo in cli.py)
            analysis = await self._analyze_copy(copy_dir)

            # Phase 2b: Convert to evaluation results and plan tasks
            planner = Planner(project_id=project.id, repository=ctx.repository)
            eval_results = self._analysis_to_eval_results(analysis, copy_dir.name)
            tasks = await planner.analyze_gaps(eval_results)

            if not tasks:
                logger.info("No enhancement tasks identified for copy")
                return 0, 0

            # Limit tasks
            tasks = tasks[:max_tasks]
            logger.info("Generated %d enhancement tasks", len(tasks))

            # Store tasks in DB
            for task in tasks:
                await ctx.repository.create_task(task)

            # Phase 2c: Execute via MicroClaw cycles
            micro = MicroClaw(ctx=ctx, project_id=project.id)
            executed = 0
            succeeded = 0

            for task in tasks:
                try:
                    result = await micro.run_cycle(on_step=self.on_step)
                    executed += 1

                    # Check verification.approved — result.success only means
                    # "cycle ran without exception", not "verification passed"
                    approved = (
                        result.verification is not None
                        and result.verification.approved
                    )
                    if approved:
                        succeeded += 1
                        quality = result.verification.quality_score if result.verification else 0
                        logger.info("Task %s approved (quality=%.2f)", task.title, quality)
                    else:
                        reason = result.outcome.failure_reason or "verification rejected"
                        logger.warning("Task %s not approved: %s", task.title, reason)

                except Exception as e:
                    executed += 1
                    logger.error("Task %s error: %s", task.title, e)

            logger.info("Enhancement complete: %d/%d tasks succeeded", succeeded, executed)
            return executed, succeeded

        finally:
            try:
                await ctx.close()
            except Exception:
                pass

    async def _analyze_copy(self, copy_dir: Path) -> dict:
        """Structural analysis of the copy (mirrors cli._analyze_repo)."""
        analysis: dict[str, Any] = {
            "has_git": (copy_dir / ".git").exists(),
            "has_readme": any(
                (copy_dir / f).exists() for f in ["README.md", "readme.md", "README"]
            ),
            "has_tests": any(
                (copy_dir / d).exists() for d in ["tests", "test", "spec", "__tests__"]
            ),
            "file_counts": {},
            "total_files": 0,
        }

        # Count files by extension
        src_dir = copy_dir / "src"
        if src_dir.exists():
            for p in src_dir.rglob("*"):
                if p.is_file() and "__pycache__" not in p.parts:
                    ext = p.suffix or "(none)"
                    analysis["file_counts"][ext] = analysis["file_counts"].get(ext, 0) + 1
                    analysis["total_files"] += 1

        return analysis

    @staticmethod
    def _analysis_to_eval_results(analysis: dict, name: str) -> list:
        """Convert structural analysis into EvaluationResult objects for the Planner."""
        from claw.planner import EvaluationResult

        results = []

        if not analysis.get("has_tests"):
            results.append(EvaluationResult(
                prompt_name="self_enhance_analysis",
                findings=[f"{name} has no test directory — add test infrastructure"],
                severity="high",
            ))

        if not analysis.get("has_readme"):
            results.append(EvaluationResult(
                prompt_name="self_enhance_analysis",
                findings=[f"{name} has no README — add documentation"],
                severity="medium",
            ))

        # CAM-specific: look for improvement opportunities
        py_count = analysis.get("file_counts", {}).get(".py", 0)
        if py_count > 0:
            results.append(EvaluationResult(
                prompt_name="self_enhance_analysis",
                findings=[
                    f"Review {py_count} Python files for enhancement opportunities "
                    f"using mined PULSE knowledge",
                ],
                severity="medium",
            ))

        return results

    # -----------------------------------------------------------------------
    # Phase 3: Validate
    # -----------------------------------------------------------------------

    async def validate(self, copy_dir: Path) -> ValidationReport:
        """Phase 3: Run 7-gate validation on the enhanced copy."""
        logger.info("Validating enhanced copy at %s", copy_dir)

        # Get current test count for baseline
        baseline_tests = self._state.get("baseline_test_count", 1997)

        vconfig = ValidationConfig(
            copy_dir=copy_dir,
            live_dir=self.live_dir,
            baseline_test_count=baseline_tests,
        )

        report = await run_all_gates(vconfig)
        logger.info("Validation result: %s", "PASSED" if report.passed else f"FAILED at {report.failed_gate}")
        return report

    def detect_protected_changes(self, copy_dir: Path) -> list[ProtectedFileChange]:
        """Check if any protected files were modified in the enhanced copy."""
        import difflib
        changes = []
        for rel_path in self.se_config.protected_files:
            live_file = self.live_dir / rel_path
            copy_file = copy_dir / rel_path
            if not live_file.exists() or not copy_file.exists():
                continue
            live_content = live_file.read_text(encoding="utf-8", errors="replace")
            copy_content = copy_file.read_text(encoding="utf-8", errors="replace")
            if live_content != copy_content:
                diff = list(difflib.unified_diff(
                    live_content.splitlines(),
                    copy_content.splitlines(),
                    lineterm="",
                ))
                additions = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
                deletions = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
                changes.append(ProtectedFileChange(
                    file_path=rel_path,
                    additions=additions,
                    deletions=deletions,
                ))
        return changes

    # -----------------------------------------------------------------------
    # Phase 4: Swap
    # -----------------------------------------------------------------------

    def create_backup(self) -> Path:
        """Create a backup of the live installation before swap."""
        workspace_parent = self._resolve_workspace_parent()
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        backup_dir = workspace_parent / f"cam-backup-{timestamp}"

        logger.info("Creating backup: %s → %s", self.live_dir, backup_dir)

        def _ignore(directory: str, contents: list[str]) -> list[str]:
            ignored = []
            for item in contents:
                if item in (
                    ".git", "__pycache__", ".venv", "venv",
                    "node_modules", ".mypy_cache", ".pytest_cache",
                    ".ruff_cache",
                ):
                    ignored.append(item)
            return ignored

        shutil.copytree(str(self.live_dir), str(backup_dir), ignore=_ignore)
        return backup_dir

    def swap(self, copy_dir: Path) -> None:
        """Phase 4: Swap the enhanced copy into the live directory.

        Replaces src/ and tests/ in the live dir with the enhanced versions.
        Does NOT touch .git, data/, .env, claw.toml, or other config.
        """
        logger.info("Swapping enhanced copy into live: %s → %s", copy_dir, self.live_dir)

        # Swap src/
        live_src = self.live_dir / "src"
        copy_src = copy_dir / "src"
        if copy_src.exists():
            if live_src.exists():
                shutil.rmtree(str(live_src))
            shutil.copytree(str(copy_src), str(live_src))

        # Swap tests/
        live_tests = self.live_dir / "tests"
        copy_tests = copy_dir / "tests"
        if copy_tests.exists():
            if live_tests.exists():
                shutil.rmtree(str(live_tests))
            shutil.copytree(str(copy_tests), str(live_tests))

        # Swap scripts/ if present
        live_scripts = self.live_dir / "scripts"
        copy_scripts = copy_dir / "scripts"
        if copy_scripts.exists():
            if live_scripts.exists():
                shutil.rmtree(str(live_scripts))
            shutil.copytree(str(copy_scripts), str(live_scripts))

        # Swap pyproject.toml if present
        copy_pyproject = copy_dir / "pyproject.toml"
        if copy_pyproject.exists():
            shutil.copy2(str(copy_pyproject), str(self.live_dir / "pyproject.toml"))

        logger.info("Swap complete")

    # -----------------------------------------------------------------------
    # Phase 5: Post-swap validation
    # -----------------------------------------------------------------------

    async def post_swap_validate(self) -> bool:
        """Phase 5: Quick smoke test after swap.

        Runs syntax check + import smoke + CLI smoke on the live dir.
        Returns True if smoke tests pass.
        """
        logger.info("Running post-swap smoke tests on live dir")

        vconfig = ValidationConfig(
            copy_dir=self.live_dir,  # Now checking live (which has the swapped code)
            live_dir=self.live_dir,
            baseline_test_count=0,  # Don't run full suite, just smoke
        )

        # Run only gates 1, 2, 3, 5 (syntax, config, import, CLI)
        from claw.validation_gate import (
            _gate_syntax_check,
            _gate_config_compatibility,
            _gate_import_smoke,
            _gate_cli_smoke,
        )

        for gate_fn in [_gate_syntax_check, _gate_config_compatibility, _gate_import_smoke, _gate_cli_smoke]:
            result = gate_fn(vconfig)
            if not result.passed:
                logger.error("Post-swap gate FAILED: %s — %s", result.gate_name, result.message)
                return False

        logger.info("Post-swap smoke tests PASSED")
        return True

    # -----------------------------------------------------------------------
    # Phase 6: Rollback
    # -----------------------------------------------------------------------

    def rollback(self, backup_dir: Path) -> None:
        """Phase 6: Restore from backup."""
        logger.info("Rolling back from backup: %s → %s", backup_dir, self.live_dir)

        # Restore src/
        backup_src = backup_dir / "src"
        live_src = self.live_dir / "src"
        if backup_src.exists():
            if live_src.exists():
                shutil.rmtree(str(live_src))
            shutil.copytree(str(backup_src), str(live_src))

        # Restore tests/
        backup_tests = backup_dir / "tests"
        live_tests = self.live_dir / "tests"
        if backup_tests.exists():
            if live_tests.exists():
                shutil.rmtree(str(live_tests))
            shutil.copytree(str(backup_tests), str(live_tests))

        # Restore scripts/
        backup_scripts = backup_dir / "scripts"
        live_scripts = self.live_dir / "scripts"
        if backup_scripts.exists():
            if live_scripts.exists():
                shutil.rmtree(str(live_scripts))
            shutil.copytree(str(backup_scripts), str(live_scripts))

        # Restore pyproject.toml
        backup_pyproject = backup_dir / "pyproject.toml"
        if backup_pyproject.exists():
            shutil.copy2(str(backup_pyproject), str(self.live_dir / "pyproject.toml"))

        logger.info("Rollback complete")

    # -----------------------------------------------------------------------
    # Backup management
    # -----------------------------------------------------------------------

    def cleanup_old_backups(self) -> int:
        """Remove old backups beyond max_backup_count."""
        workspace_parent = self._resolve_workspace_parent()
        backups = sorted(
            workspace_parent.glob("cam-backup-*"),
            key=lambda p: p.name,
            reverse=True,
        )
        removed = 0
        for old_backup in backups[self.se_config.max_backup_count:]:
            logger.info("Removing old backup: %s", old_backup)
            shutil.rmtree(str(old_backup), ignore_errors=True)
            removed += 1
        return removed

    def cleanup_old_copies(self) -> int:
        """Remove old enhancement copies."""
        workspace_parent = self._resolve_workspace_parent()
        copies = sorted(
            workspace_parent.glob("cam-self-enhance-*"),
            key=lambda p: p.name,
            reverse=True,
        )
        # Keep only the most recent one (in case user wants to inspect)
        removed = 0
        for old_copy in copies[1:]:
            logger.info("Removing old copy: %s", old_copy)
            shutil.rmtree(str(old_copy), ignore_errors=True)
            removed += 1
        return removed

    # -----------------------------------------------------------------------
    # Full pipeline
    # -----------------------------------------------------------------------

    async def run(
        self,
        mode: str = "autonomous",
        max_tasks: int = 0,
        skip_swap: bool = False,
        force: bool = False,
    ) -> EnhancementResult:
        """Run the full self-enhancement pipeline.

        Args:
            mode: Operational mode for enhancement agents.
            max_tasks: Max enhancement tasks (0 = use config default).
            skip_swap: If True, stop after validation (don't swap).
            force: If True, skip trigger assessment.

        Returns:
            EnhancementResult with full details.
        """
        start_time = time.monotonic()
        result = EnhancementResult(success=False, phase_reached="init")

        try:
            # Phase 0: Trigger assessment (unless forced)
            if not force:
                assessment = await self.assess_trigger()
                if not assessment.should_trigger:
                    result.phase_reached = "trigger_check"
                    result.error = assessment.summary()
                    result.duration_seconds = time.monotonic() - start_time
                    return result

            # Phase 1: Clone
            result.phase_reached = "clone"
            copy_dir = self.clone()
            result.copy_dir = copy_dir

            # Phase 2: Enhance
            result.phase_reached = "enhance"
            executed, succeeded = await self.enhance(copy_dir, mode=mode, max_tasks=max_tasks)
            result.tasks_executed = executed
            result.tasks_succeeded = succeeded

            if succeeded == 0 and executed > 0:
                result.error = "All enhancement tasks failed"
                result.duration_seconds = time.monotonic() - start_time
                return result

            # Phase 3: Validate
            result.phase_reached = "validate"
            report = await self.validate(copy_dir)
            result.validation_report = report
            result.diff_summary = report.diff_summary

            if not report.passed:
                result.error = f"Validation failed at gate: {report.failed_gate}"
                result.duration_seconds = time.monotonic() - start_time
                return result

            # Check protected files
            protected_changes = self.detect_protected_changes(copy_dir)
            result.protected_file_changes = protected_changes

            if protected_changes and self.se_config.require_user_confirmation:
                result.phase_reached = "protected_review"
                result.error = (
                    f"{len(protected_changes)} protected file(s) modified — "
                    f"requires human review before swap"
                )
                result.duration_seconds = time.monotonic() - start_time
                # Don't swap, but don't mark as failure — user can review and manually swap
                return result

            if skip_swap:
                result.phase_reached = "validate"
                result.success = True
                result.duration_seconds = time.monotonic() - start_time
                return result

            # Phase 4: Swap
            result.phase_reached = "swap"
            backup_dir = self.create_backup()
            result.backup_dir = backup_dir

            self.swap(copy_dir)
            result.swap_completed = True

            # Phase 5: Post-swap validation
            result.phase_reached = "post_swap"
            post_ok = await self.post_swap_validate()

            if not post_ok:
                logger.error("Post-swap validation FAILED — rolling back")
                self.rollback(backup_dir)
                result.rollback_performed = True
                result.swap_completed = False
                result.error = "Post-swap validation failed; rolled back to backup"
                result.duration_seconds = time.monotonic() - start_time
                return result

            # Success — update state
            result.phase_reached = "complete"
            result.success = True

            # Persist state for future trigger assessments
            methodology_count = 0
            if self.db_engine:
                try:
                    from claw.db.repository import Repository
                    repo = Repository(self.db_engine)
                    methodology_count = await repo.count_methodologies()
                except Exception:
                    pass

            self._state["last_enhance_completed_at"] = datetime.now(UTC).isoformat()
            self._state["methodology_count_at_last_enhance"] = methodology_count
            self._state["baseline_test_count"] = (
                report.test_results.total if report.test_results else 0
            )
            self._state["last_backup_dir"] = str(backup_dir)
            _save_state(self.live_dir, self._state)

            # Cleanup old backups
            self.cleanup_old_backups()
            self.cleanup_old_copies()

        except Exception as e:
            result.error = f"Pipeline error in phase '{result.phase_reached}': {e}"
            logger.exception("Self-enhancement pipeline error")

        result.duration_seconds = time.monotonic() - start_time
        return result
