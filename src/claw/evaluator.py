"""Evaluator -- orchestrates the 17-prompt evaluation battery for CLAW.

The Evaluator runs the full evaluation battery against a repository to
identify issues, gaps, and improvement opportunities. It is the first
stage of the claw cycle:

    Evaluator -> Planner -> Dispatcher -> Agent -> Verifier

The 17 prompts are organized into 6 phases:

1. **Orientation** -- project-context, workspace-scan
2. **Deep Analysis** -- deepdive, agonyofdefeatures, driftx
3. **Truth Verification** -- claim-gate, outcome-audit, assumption-registry
4. **Quality Assessment** -- debt-tracker, endUXRedo, regression-scan
5. **Documentation** -- docsRedo, handoff
6. **Remediation Planning** -- app__mitigen

Additional prompts (not phase-bound): ironclad, sotappr, ultrathink, interview

Each prompt is loaded from the prompts/ directory (as .md or .txt files),
sent to an agent via the Dispatcher, and the result is recorded. If no
Dispatcher is available, prompts are marked as "pending" (not executed).

The Evaluator produces an ``EvaluationReport`` containing all prompt
results organized by phase. The Planner consumes this report to generate
tasks.
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from claw.dispatcher import Dispatcher
    from claw.db.repository import Repository

logger = logging.getLogger("claw.evaluator")


# ---------------------------------------------------------------------------
# Evaluation phases and prompts
# ---------------------------------------------------------------------------

EVALUATION_PHASES: list[tuple[str, list[str]]] = [
    ("orientation", ["project-context", "workspace-scan"]),
    ("deep_analysis", ["deepdive", "agonyofdefeatures", "driftx"]),
    ("truth_verification", ["claim-gate", "outcome-audit", "assumption-registry"]),
    ("quality_assessment", ["debt-tracker", "endUXRedo", "regression-scan"]),
    ("documentation", ["docsRedo", "handoff"]),
    ("remediation_planning", ["app__mitigen"]),
]

ADDITIONAL_PROMPTS: list[str] = ["ironclad", "sotappr", "ultrathink", "interview"]


# ---------------------------------------------------------------------------
# Result data classes
# ---------------------------------------------------------------------------

@dataclass
class PromptResult:
    """Result of executing a single evaluation prompt.

    Attributes:
        prompt_name: Name of the prompt (e.g. "deepdive", "claim-gate").
        phase: Which evaluation phase this prompt belongs to.
        output: The text output produced by the agent, or an empty
                string if the prompt was not executed.
        agent_id: Which agent executed this prompt, or None if pending.
        duration_seconds: Wall-clock seconds taken to execute.
        success: True if the prompt executed without error.
        error: Error message if the prompt failed, None otherwise.
    """

    prompt_name: str
    phase: str
    output: str = ""
    agent_id: Optional[str] = None
    duration_seconds: float = 0.0
    success: bool = True
    error: Optional[str] = None


@dataclass
class PhaseResult:
    """Result of executing all prompts in one evaluation phase.

    Attributes:
        phase_name: Name of the phase (e.g. "orientation", "deep_analysis").
        prompt_results: List of PromptResult objects for each prompt in
                        this phase.
        success: True if all prompts in the phase succeeded.
    """

    phase_name: str
    prompt_results: list[PromptResult] = field(default_factory=list)
    success: bool = True


@dataclass
class EvaluationReport:
    """Complete report from running the evaluation battery.

    Attributes:
        project_id: UUID of the project being evaluated.
        repo_path: Filesystem path to the repository.
        mode: Evaluation mode ("full" or "quick").
        phases: List of PhaseResult objects for each executed phase.
        total_prompts: Total number of prompts that were attempted.
        successful_prompts: Number of prompts that completed successfully.
        failed_prompts: Number of prompts that failed with errors.
        total_duration_seconds: Wall-clock time for the entire battery.
        created_at: ISO-8601 timestamp when the evaluation started.
    """

    project_id: str
    repo_path: str
    mode: str = "full"
    phases: list[PhaseResult] = field(default_factory=list)
    total_prompts: int = 0
    successful_prompts: int = 0
    failed_prompts: int = 0
    total_duration_seconds: float = 0.0
    created_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Evaluator
# ---------------------------------------------------------------------------

class Evaluator:
    """Orchestrates the 17-prompt evaluation battery.

    The Evaluator loads prompt templates from the filesystem, dispatches
    them to agents for execution, and collects the results into a
    structured report.

    Args:
        repository: Data access layer for logging episodes.
        dispatcher: Optional Dispatcher for routing prompts to agents.
                    If None, prompts are recorded as "pending" and not
                    executed against any agent.
        prompt_dir: Path to the directory containing prompt files.
                    Defaults to "prompts/" relative to the project root.
    """

    def __init__(
        self,
        repository: Optional[Repository] = None,
        dispatcher: Optional[Dispatcher] = None,
        prompt_dir: Optional[str] = None,
    ) -> None:
        self.repository = repository
        self.dispatcher = dispatcher

        if prompt_dir is not None:
            self.prompt_dir = Path(prompt_dir)
        else:
            # Default: prompts/ relative to the project root
            # Project root is four levels up from this file
            # (src/claw/evaluator.py -> src/claw -> src -> project_root)
            self.prompt_dir = Path(__file__).parent.parent.parent / "prompts"

        # Build a lookup: prompt_name -> phase_name
        self._prompt_to_phase: dict[str, str] = {}
        for phase_name, prompt_names in EVALUATION_PHASES:
            for prompt_name in prompt_names:
                self._prompt_to_phase[prompt_name] = phase_name

        # Additional prompts do not belong to a specific phase
        for prompt_name in ADDITIONAL_PROMPTS:
            self._prompt_to_phase[prompt_name] = "additional"

        # Generate a session ID for episode logging
        self._session_id = str(uuid.uuid4())

        logger.info(
            "Evaluator initialized: prompt_dir=%s, dispatcher=%s, "
            "total_prompts=%d",
            self.prompt_dir,
            "connected" if dispatcher else "none",
            len(self._prompt_to_phase),
        )

    # -------------------------------------------------------------------
    # Public API
    # -------------------------------------------------------------------

    async def run_battery(
        self, project_id: str, repo_path: str, mode: str = "full"
    ) -> EvaluationReport:
        """Run the full evaluation battery against a repository.

        Args:
            project_id: UUID of the project being evaluated.
            repo_path: Filesystem path to the repository to evaluate.
            mode: Evaluation mode. "full" runs all 6 phases plus
                  additional prompts. "quick" runs only orientation
                  and deep_analysis phases.

        Returns:
            An EvaluationReport containing all phase and prompt results.
        """
        battery_start = time.monotonic()
        created_at = datetime.now(UTC).isoformat()

        logger.info(
            "Starting evaluation battery: project_id=%s, repo_path=%s, mode=%s",
            project_id, repo_path, mode,
        )

        report = EvaluationReport(
            project_id=project_id,
            repo_path=repo_path,
            mode=mode,
            created_at=created_at,
        )

        # Determine which phases to run based on mode
        if mode == "quick":
            phases_to_run = [
                p for p in EVALUATION_PHASES
                if p[0] in ("orientation", "deep_analysis")
            ]
        else:
            phases_to_run = list(EVALUATION_PHASES)

        # Run each phase sequentially
        for phase_name, _prompt_names in phases_to_run:
            phase_result = await self.run_phase(phase_name, project_id, repo_path)
            report.phases.append(phase_result)

        # In full mode, also run additional prompts as a separate phase
        if mode == "full" and ADDITIONAL_PROMPTS:
            additional_phase = PhaseResult(phase_name="additional")
            for prompt_name in ADDITIONAL_PROMPTS:
                prompt_result = await self.run_prompt(
                    prompt_name, project_id, repo_path
                )
                additional_phase.prompt_results.append(prompt_result)

            additional_phase.success = all(
                pr.success for pr in additional_phase.prompt_results
            )
            report.phases.append(additional_phase)

        # Compute summary statistics
        total_duration = time.monotonic() - battery_start
        report.total_duration_seconds = total_duration

        total = 0
        succeeded = 0
        failed = 0
        for phase in report.phases:
            for pr in phase.prompt_results:
                total += 1
                if pr.success:
                    succeeded += 1
                else:
                    failed += 1

        report.total_prompts = total
        report.successful_prompts = succeeded
        report.failed_prompts = failed

        logger.info(
            "Evaluation battery complete: mode=%s, total=%d, "
            "succeeded=%d, failed=%d, duration=%.2fs",
            mode, total, succeeded, failed, total_duration,
        )

        # Log battery completion as an episode
        if self.repository is not None:
            await self.repository.log_episode(
                session_id=self._session_id,
                event_type="evaluation_battery_complete",
                event_data={
                    "mode": mode,
                    "repo_path": repo_path,
                    "total_prompts": total,
                    "successful_prompts": succeeded,
                    "failed_prompts": failed,
                    "duration_seconds": total_duration,
                },
                project_id=project_id,
                cycle_level="meso",
            )

        return report

    async def run_phase(
        self, phase_name: str, project_id: str, repo_path: str
    ) -> PhaseResult:
        """Run all prompts in a single evaluation phase.

        Prompts within a phase are executed sequentially. The phase is
        considered successful only if all its prompts succeed.

        Args:
            phase_name: Name of the phase (e.g. "orientation").
            project_id: UUID of the project being evaluated.
            repo_path: Filesystem path to the repository.

        Returns:
            A PhaseResult containing results for each prompt in the phase.
        """
        # Look up prompts for this phase
        prompt_names: list[str] = []
        for pname, plist in EVALUATION_PHASES:
            if pname == phase_name:
                prompt_names = plist
                break

        if not prompt_names:
            logger.warning(
                "Unknown phase '%s'. No prompts to run.", phase_name,
            )
            return PhaseResult(
                phase_name=phase_name,
                success=False,
            )

        logger.info(
            "Running phase '%s': %d prompt(s) -- %s",
            phase_name, len(prompt_names), ", ".join(prompt_names),
        )

        phase_result = PhaseResult(phase_name=phase_name)

        for prompt_name in prompt_names:
            prompt_result = await self.run_prompt(
                prompt_name, project_id, repo_path
            )
            phase_result.prompt_results.append(prompt_result)

        # Phase succeeds only if all prompts succeeded
        phase_result.success = all(
            pr.success for pr in phase_result.prompt_results
        )

        status = "succeeded" if phase_result.success else "had failures"
        logger.info(
            "Phase '%s' %s: %d/%d prompt(s) succeeded",
            phase_name,
            status,
            sum(1 for pr in phase_result.prompt_results if pr.success),
            len(phase_result.prompt_results),
        )

        return phase_result

    async def run_prompt(
        self, prompt_name: str, project_id: str, repo_path: str
    ) -> PromptResult:
        """Run a single evaluation prompt.

        Loads the prompt content from the filesystem, dispatches it to
        an agent via the Dispatcher (if available), and returns the result.

        If the prompt file does not exist, records an error. If no
        Dispatcher is configured, the prompt is marked as pending with
        an empty output.

        Args:
            prompt_name: Name of the prompt file (without extension).
            project_id: UUID of the project being evaluated.
            repo_path: Filesystem path to the repository.

        Returns:
            A PromptResult with the output (or error information).
        """
        phase = self.get_phase_for_prompt(prompt_name) or "unknown"
        prompt_start = time.monotonic()

        logger.debug(
            "Running prompt '%s' (phase='%s') for project=%s",
            prompt_name, phase, project_id,
        )

        # Load prompt content from file
        content = self.get_prompt_content(prompt_name)
        if content is None:
            duration = time.monotonic() - prompt_start
            error_msg = (
                f"Prompt file not found for '{prompt_name}'. "
                f"Searched in: {self.prompt_dir}/{prompt_name}.md "
                f"and {self.prompt_dir}/{prompt_name}.txt"
            )
            logger.error(error_msg)

            result = PromptResult(
                prompt_name=prompt_name,
                phase=phase,
                output="",
                success=False,
                error=error_msg,
                duration_seconds=duration,
            )

            # Log the error as an episode
            if self.repository is not None:
                await self.repository.log_episode(
                    session_id=self._session_id,
                    event_type="evaluation_prompt_error",
                    event_data={
                        "prompt_name": prompt_name,
                        "phase": phase,
                        "error": error_msg,
                    },
                    project_id=project_id,
                    cycle_level="meso",
                )

            return result

        # If no dispatcher is available, record as pending
        if self.dispatcher is None:
            duration = time.monotonic() - prompt_start
            logger.info(
                "No dispatcher available. Prompt '%s' recorded as pending.",
                prompt_name,
            )

            result = PromptResult(
                prompt_name=prompt_name,
                phase=phase,
                output="",
                agent_id=None,
                success=True,
                error=None,
                duration_seconds=duration,
            )

            if self.repository is not None:
                await self.repository.log_episode(
                    session_id=self._session_id,
                    event_type="evaluation_prompt_pending",
                    event_data={
                        "prompt_name": prompt_name,
                        "phase": phase,
                        "reason": "no_dispatcher",
                    },
                    project_id=project_id,
                    cycle_level="meso",
                )

            return result

        # Dispatch the prompt to an agent for execution
        try:
            from claw.core.models import Task, TaskContext, TaskStatus

            # Serialize repo contents so agents can actually see the source code
            repo_context = ""
            try:
                from claw.miner import serialize_repo
                serialized, file_count = serialize_repo(str(repo_path), max_bytes=50_000)
                repo_context = (
                    f"\n\n## Repository Contents ({file_count} files)\n\n"
                    f"{serialized}\n"
                )
            except Exception as e:
                logger.warning("Could not serialize repo for evaluation: %s", e)
                repo_context = f"\n\n(Repository at {repo_path} — contents not available: {e})\n"

            # Create a transient task for this evaluation prompt
            eval_task = Task(
                project_id=project_id,
                title=f"Evaluate: {prompt_name}",
                description=(
                    f"Run evaluation prompt '{prompt_name}' (phase: {phase}) "
                    f"against repository at {repo_path}.\n"
                    f"{repo_context}\n"
                    f"Prompt content:\n{content}"
                ),
                status=TaskStatus.EVALUATING,
                priority=5,
                task_type="analysis",
            )

            task_context = TaskContext(task=eval_task)

            # Route to an agent
            agent_id = await self.dispatcher.route_task(eval_task, task_context)

            # Execute via the agent
            agent = self.dispatcher.agents.get(agent_id)
            if agent is None:
                raise RuntimeError(
                    f"Dispatcher routed to agent '{agent_id}' but agent is not "
                    f"available in the agent pool"
                )

            outcome = await agent.run(task_context)
            duration = time.monotonic() - prompt_start

            # Determine success based on outcome
            output_text = outcome.approach_summary or outcome.raw_output or ""
            had_failure = outcome.failure_reason is not None

            result = PromptResult(
                prompt_name=prompt_name,
                phase=phase,
                output=output_text,
                agent_id=agent_id,
                duration_seconds=duration,
                success=not had_failure,
                error=outcome.failure_detail if had_failure else None,
            )

            logger.info(
                "Prompt '%s' executed by agent '%s': success=%s (%.2fs)",
                prompt_name, agent_id, result.success, duration,
            )

            # Log as an episode
            if self.repository is not None:
                await self.repository.log_episode(
                    session_id=self._session_id,
                    event_type="evaluation_prompt_complete",
                    event_data={
                        "prompt_name": prompt_name,
                        "phase": phase,
                        "agent_id": agent_id,
                        "success": result.success,
                        "duration_seconds": duration,
                        "output_length": len(output_text),
                    },
                    project_id=project_id,
                    agent_id=agent_id,
                    cycle_level="meso",
                )

            return result

        except Exception as exc:
            duration = time.monotonic() - prompt_start
            error_msg = f"Failed to execute prompt '{prompt_name}': {exc}"
            logger.error(error_msg, exc_info=True)

            result = PromptResult(
                prompt_name=prompt_name,
                phase=phase,
                output="",
                success=False,
                error=error_msg,
                duration_seconds=duration,
            )

            if self.repository is not None:
                await self.repository.log_episode(
                    session_id=self._session_id,
                    event_type="evaluation_prompt_error",
                    event_data={
                        "prompt_name": prompt_name,
                        "phase": phase,
                        "error": error_msg,
                    },
                    project_id=project_id,
                    cycle_level="meso",
                )

            return result

    # -------------------------------------------------------------------
    # Prompt loading
    # -------------------------------------------------------------------

    def get_prompt_content(self, prompt_name: str) -> Optional[str]:
        """Load a prompt template from the filesystem.

        Searches for the prompt file with .md extension first, then .txt.
        Returns the file contents as a string, or None if neither file
        exists.

        Args:
            prompt_name: Name of the prompt (without extension).

        Returns:
            The prompt template content, or None if the file does not exist.
        """
        # Try .md first, then .txt
        for ext in (".md", ".txt"):
            prompt_path = self.prompt_dir / f"{prompt_name}{ext}"
            if prompt_path.exists():
                try:
                    content = prompt_path.read_text(encoding="utf-8").strip()
                    logger.debug(
                        "Loaded prompt '%s' from %s (%d chars)",
                        prompt_name, prompt_path, len(content),
                    )
                    return content
                except OSError as exc:
                    logger.error(
                        "Failed to read prompt file %s: %s",
                        prompt_path, exc,
                    )
                    return None

        logger.debug(
            "Prompt file not found for '%s' in %s (tried .md, .txt)",
            prompt_name, self.prompt_dir,
        )
        return None

    # -------------------------------------------------------------------
    # Prompt metadata
    # -------------------------------------------------------------------

    def get_phase_for_prompt(self, prompt_name: str) -> Optional[str]:
        """Look up which phase a prompt belongs to.

        Args:
            prompt_name: Name of the prompt.

        Returns:
            The phase name (e.g. "orientation", "deep_analysis"), or
            None if the prompt is not part of any known phase.
        """
        return self._prompt_to_phase.get(prompt_name)

    def get_all_prompt_names(self) -> list[str]:
        """Return the names of all 17 evaluation prompts plus additional prompts.

        The prompts are returned in phase order: orientation prompts first,
        then deep_analysis, truth_verification, quality_assessment,
        documentation, remediation_planning, and finally the additional
        prompts.

        Returns:
            An ordered list of prompt name strings.
        """
        names: list[str] = []
        for _phase_name, prompt_names in EVALUATION_PHASES:
            names.extend(prompt_names)
        names.extend(ADDITIONAL_PROMPTS)
        return names
