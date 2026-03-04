"""Tests for CLAW Phase 5 -- Evaluator module.

Covers the complete Evaluator subsystem:
  1. PromptResult dataclass -- field creation and defaults
  2. PhaseResult dataclass -- field creation and defaults
  3. EvaluationReport dataclass -- field creation and stats
  4. EVALUATION_PHASES constant -- structure validation
  5. ADDITIONAL_PROMPTS constant -- structure validation
  6. Evaluator initialization -- prompt_dir, repository, phase lookup
  7. get_prompt_content -- filesystem loading (.md, .txt, precedence)
  8. get_phase_for_prompt -- reverse lookup
  9. get_all_prompt_names -- ordered listing
  10. run_prompt -- no-dispatcher pending path, missing prompt error path
  11. run_phase -- valid phases, unknown phases, partial failure
  12. run_battery -- full mode, quick mode, episode logging, stats

NO mocks, NO placeholders, NO cached responses, NO simulation. All tests use real
SQLite in-memory databases via the ``db_engine`` / ``repository`` fixtures from conftest,
and real temporary prompt files on disk via pytest ``tmp_path``.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from claw.core.models import Project
from claw.evaluator import (
    ADDITIONAL_PROMPTS,
    EVALUATION_PHASES,
    EvaluationReport,
    Evaluator,
    PhaseResult,
    PromptResult,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _uid() -> str:
    return str(uuid.uuid4())


async def _create_project_in_db(repository) -> str:
    """Create a real project in the DB and return its id.

    The episodes table has a foreign key to projects(id), so any test
    that logs episodes via the repository must first insert a project.
    """
    project = Project(
        name="evaluator-test-project",
        repo_path="/tmp/repo",
        tech_stack={"language": "python"},
    )
    await repository.create_project(project)
    return project.id


ALL_PROMPT_NAMES: list[str] = [
    "project-context", "workspace-scan",
    "deepdive", "agonyofdefeatures", "driftx",
    "claim-gate", "outcome-audit", "assumption-registry",
    "debt-tracker", "endUXRedo", "regression-scan",
    "docsRedo", "handoff",
    "app__mitigen",
    "ironclad", "sotappr", "ultrathink", "interview",
]

PHASE_NAMES: list[str] = [
    "orientation",
    "deep_analysis",
    "truth_verification",
    "quality_assessment",
    "documentation",
    "remediation_planning",
]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def prompt_dir(tmp_path: Path) -> str:
    """Create a temporary prompts directory with real .md files for all 18 prompts."""
    prompts = tmp_path / "prompts"
    prompts.mkdir()
    for name in ALL_PROMPT_NAMES:
        (prompts / f"{name}.md").write_text(
            f"# {name}\n\nEvaluate the codebase for {name} analysis.\n"
        )
    return str(prompts)


@pytest.fixture
def empty_prompt_dir(tmp_path: Path) -> str:
    """Create an empty temporary prompts directory (no prompt files)."""
    prompts = tmp_path / "empty_prompts"
    prompts.mkdir()
    return str(prompts)


@pytest.fixture
def evaluator_with_prompts(prompt_dir: str) -> Evaluator:
    """Evaluator with a real prompt directory containing all prompt files, no dispatcher."""
    return Evaluator(repository=None, dispatcher=None, prompt_dir=prompt_dir)


@pytest.fixture
def evaluator_no_prompts(empty_prompt_dir: str) -> Evaluator:
    """Evaluator with an empty prompt directory, no dispatcher."""
    return Evaluator(repository=None, dispatcher=None, prompt_dir=empty_prompt_dir)


# ===========================================================================
# Module 1: PromptResult dataclass
# ===========================================================================


class TestPromptResultDataclass:
    """Tests for PromptResult creation and default values."""

    def test_create_with_all_fields(self) -> None:
        """PromptResult with all fields explicitly set retains each value."""
        result = PromptResult(
            prompt_name="deepdive",
            phase="deep_analysis",
            output="Analysis output text here",
            agent_id="claude-code",
            duration_seconds=12.5,
            success=True,
            error=None,
        )
        assert result.prompt_name == "deepdive"
        assert result.phase == "deep_analysis"
        assert result.output == "Analysis output text here"
        assert result.agent_id == "claude-code"
        assert result.duration_seconds == 12.5
        assert result.success is True
        assert result.error is None

    def test_default_values(self) -> None:
        """PromptResult with only required fields uses correct defaults."""
        result = PromptResult(prompt_name="claim-gate", phase="truth_verification")
        assert result.prompt_name == "claim-gate"
        assert result.phase == "truth_verification"
        assert result.output == ""
        assert result.agent_id is None
        assert result.duration_seconds == 0.0
        assert result.success is True
        assert result.error is None


# ===========================================================================
# Module 2: PhaseResult dataclass
# ===========================================================================


class TestPhaseResultDataclass:
    """Tests for PhaseResult creation and default values."""

    def test_create_with_defaults(self) -> None:
        """PhaseResult with only phase_name uses correct defaults."""
        phase = PhaseResult(phase_name="orientation")
        assert phase.phase_name == "orientation"
        assert phase.prompt_results == []
        assert phase.success is True

    def test_create_with_prompt_results(self) -> None:
        """PhaseResult populated with PromptResult objects retains them."""
        pr1 = PromptResult(prompt_name="project-context", phase="orientation")
        pr2 = PromptResult(prompt_name="workspace-scan", phase="orientation")
        phase = PhaseResult(
            phase_name="orientation",
            prompt_results=[pr1, pr2],
            success=True,
        )
        assert phase.phase_name == "orientation"
        assert len(phase.prompt_results) == 2
        assert phase.prompt_results[0].prompt_name == "project-context"
        assert phase.prompt_results[1].prompt_name == "workspace-scan"
        assert phase.success is True


# ===========================================================================
# Module 3: EvaluationReport dataclass
# ===========================================================================


class TestEvaluationReportDataclass:
    """Tests for EvaluationReport creation and statistics."""

    def test_create_empty_report(self) -> None:
        """EvaluationReport with only required fields uses correct defaults."""
        pid = _uid()
        report = EvaluationReport(project_id=pid, repo_path="/tmp/test-repo")
        assert report.project_id == pid
        assert report.repo_path == "/tmp/test-repo"
        assert report.mode == "full"
        assert report.phases == []
        assert report.total_prompts == 0
        assert report.successful_prompts == 0
        assert report.failed_prompts == 0
        assert report.total_duration_seconds == 0.0
        assert report.created_at is None

    def test_create_report_with_phases_and_stats(self) -> None:
        """EvaluationReport with phases and summary stats retains all values."""
        pid = _uid()
        pr_ok = PromptResult(prompt_name="deepdive", phase="deep_analysis", success=True)
        pr_fail = PromptResult(
            prompt_name="driftx", phase="deep_analysis",
            success=False, error="file not found",
        )
        phase = PhaseResult(
            phase_name="deep_analysis",
            prompt_results=[pr_ok, pr_fail],
            success=False,
        )
        report = EvaluationReport(
            project_id=pid,
            repo_path="/tmp/repo",
            mode="full",
            phases=[phase],
            total_prompts=2,
            successful_prompts=1,
            failed_prompts=1,
            total_duration_seconds=5.3,
            created_at="2026-03-03T00:00:00+00:00",
        )
        assert len(report.phases) == 1
        assert report.total_prompts == 2
        assert report.successful_prompts == 1
        assert report.failed_prompts == 1
        assert report.total_duration_seconds == 5.3
        assert report.created_at == "2026-03-03T00:00:00+00:00"


# ===========================================================================
# Module 4: EVALUATION_PHASES constant
# ===========================================================================


class TestEvaluationPhasesConstant:
    """Tests validating the EVALUATION_PHASES constant structure."""

    def test_six_phases_exist(self) -> None:
        """EVALUATION_PHASES contains exactly 6 phases."""
        assert len(EVALUATION_PHASES) == 6

    def test_total_prompt_count_across_phases(self) -> None:
        """Total number of prompts across all 6 phases is 14."""
        total = sum(len(prompts) for _, prompts in EVALUATION_PHASES)
        assert total == 14

    def test_phase_names_match(self) -> None:
        """Phase names in EVALUATION_PHASES match the expected list."""
        phase_names = [name for name, _ in EVALUATION_PHASES]
        assert phase_names == PHASE_NAMES

    def test_additional_prompts_has_four_items(self) -> None:
        """ADDITIONAL_PROMPTS contains exactly 4 prompts."""
        assert len(ADDITIONAL_PROMPTS) == 4
        assert ADDITIONAL_PROMPTS == ["ironclad", "sotappr", "ultrathink", "interview"]


# ===========================================================================
# Module 5: Evaluator initialization
# ===========================================================================


class TestEvaluatorInit:
    """Tests for Evaluator.__init__ with various argument combinations."""

    def test_init_with_no_args(self) -> None:
        """Evaluator with no args uses project-relative prompt_dir."""
        ev = Evaluator()
        assert ev.repository is None
        assert ev.dispatcher is None
        # prompt_dir should be set (default points to project_root/prompts/)
        assert ev.prompt_dir is not None
        assert str(ev.prompt_dir).endswith("prompts")

    def test_init_with_custom_prompt_dir(self, prompt_dir: str) -> None:
        """Evaluator with custom prompt_dir uses the provided path."""
        ev = Evaluator(prompt_dir=prompt_dir)
        assert str(ev.prompt_dir) == prompt_dir

    def test_init_with_repository(self, repository) -> None:
        """Evaluator with a real repository stores the reference."""
        ev = Evaluator(repository=repository)
        assert ev.repository is repository

    def test_prompt_to_phase_lookup_built_correctly(self) -> None:
        """Internal _prompt_to_phase dict maps all 18 prompts to their phases."""
        ev = Evaluator()
        # 14 phase prompts + 4 additional = 18
        assert len(ev._prompt_to_phase) == 18

        # Spot-check phase assignments
        assert ev._prompt_to_phase["project-context"] == "orientation"
        assert ev._prompt_to_phase["workspace-scan"] == "orientation"
        assert ev._prompt_to_phase["deepdive"] == "deep_analysis"
        assert ev._prompt_to_phase["agonyofdefeatures"] == "deep_analysis"
        assert ev._prompt_to_phase["driftx"] == "deep_analysis"
        assert ev._prompt_to_phase["claim-gate"] == "truth_verification"
        assert ev._prompt_to_phase["outcome-audit"] == "truth_verification"
        assert ev._prompt_to_phase["assumption-registry"] == "truth_verification"
        assert ev._prompt_to_phase["debt-tracker"] == "quality_assessment"
        assert ev._prompt_to_phase["endUXRedo"] == "quality_assessment"
        assert ev._prompt_to_phase["regression-scan"] == "quality_assessment"
        assert ev._prompt_to_phase["docsRedo"] == "documentation"
        assert ev._prompt_to_phase["handoff"] == "documentation"
        assert ev._prompt_to_phase["app__mitigen"] == "remediation_planning"

        # Additional prompts mapped to "additional"
        for name in ADDITIONAL_PROMPTS:
            assert ev._prompt_to_phase[name] == "additional"


# ===========================================================================
# Module 6: get_prompt_content
# ===========================================================================


class TestGetPromptContent:
    """Tests for Evaluator.get_prompt_content -- filesystem-based loading."""

    def test_returns_none_when_prompt_dir_does_not_exist(self, tmp_path: Path) -> None:
        """Returns None when the prompt directory path does not exist at all."""
        nonexistent = str(tmp_path / "nonexistent_dir")
        ev = Evaluator(prompt_dir=nonexistent)
        result = ev.get_prompt_content("deepdive")
        assert result is None

    def test_loads_md_file(self, tmp_path: Path) -> None:
        """Loads a .md file when it exists in the prompt directory."""
        prompts = tmp_path / "prompts_md"
        prompts.mkdir()
        (prompts / "deepdive.md").write_text("# Deep Dive\n\nAnalyze the codebase.")
        ev = Evaluator(prompt_dir=str(prompts))
        content = ev.get_prompt_content("deepdive")
        assert content is not None
        assert "# Deep Dive" in content
        assert "Analyze the codebase." in content

    def test_loads_txt_when_md_missing(self, tmp_path: Path) -> None:
        """Falls back to .txt file when .md does not exist."""
        prompts = tmp_path / "prompts_txt"
        prompts.mkdir()
        (prompts / "deepdive.txt").write_text("Deep Dive text prompt.")
        ev = Evaluator(prompt_dir=str(prompts))
        content = ev.get_prompt_content("deepdive")
        assert content is not None
        assert "Deep Dive text prompt." in content

    def test_prefers_md_over_txt(self, tmp_path: Path) -> None:
        """When both .md and .txt exist, .md takes precedence."""
        prompts = tmp_path / "prompts_both"
        prompts.mkdir()
        (prompts / "deepdive.md").write_text("MD content -- preferred")
        (prompts / "deepdive.txt").write_text("TXT content -- fallback")
        ev = Evaluator(prompt_dir=str(prompts))
        content = ev.get_prompt_content("deepdive")
        assert content is not None
        assert "MD content -- preferred" in content
        assert "TXT content" not in content

    def test_returns_none_for_nonexistent_prompt(self, prompt_dir: str) -> None:
        """Returns None for a prompt name that does not match any file."""
        ev = Evaluator(prompt_dir=prompt_dir)
        result = ev.get_prompt_content("nonexistent-prompt-xyz")
        assert result is None


# ===========================================================================
# Module 7: get_phase_for_prompt
# ===========================================================================


class TestGetPhaseForPrompt:
    """Tests for Evaluator.get_phase_for_prompt -- reverse phase lookup."""

    def test_returns_correct_phase_for_deepdive(self) -> None:
        """'deepdive' maps to 'deep_analysis'."""
        ev = Evaluator()
        assert ev.get_phase_for_prompt("deepdive") == "deep_analysis"

    def test_returns_additional_for_ironclad(self) -> None:
        """'ironclad' maps to 'additional'."""
        ev = Evaluator()
        assert ev.get_phase_for_prompt("ironclad") == "additional"

    def test_returns_none_for_unknown_prompt(self) -> None:
        """Unknown prompt name returns None."""
        ev = Evaluator()
        assert ev.get_phase_for_prompt("unknown-prompt-xyz") is None


# ===========================================================================
# Module 8: get_all_prompt_names
# ===========================================================================


class TestGetAllPromptNames:
    """Tests for Evaluator.get_all_prompt_names -- ordered listing."""

    def test_returns_eighteen_total_names(self) -> None:
        """Returns 18 names total (14 phase + 4 additional)."""
        ev = Evaluator()
        names = ev.get_all_prompt_names()
        assert len(names) == 18

    def test_first_two_are_orientation_prompts(self) -> None:
        """First two prompt names are the orientation phase prompts."""
        ev = Evaluator()
        names = ev.get_all_prompt_names()
        assert names[0] == "project-context"
        assert names[1] == "workspace-scan"

    def test_last_four_are_additional_prompts(self) -> None:
        """Last four prompt names are the additional (non-phase) prompts."""
        ev = Evaluator()
        names = ev.get_all_prompt_names()
        assert names[-4:] == ["ironclad", "sotappr", "ultrathink", "interview"]

    def test_all_expected_names_present(self) -> None:
        """Every expected prompt name is present in the returned list."""
        ev = Evaluator()
        names = ev.get_all_prompt_names()
        assert names == ALL_PROMPT_NAMES


# ===========================================================================
# Module 9: run_prompt (no dispatcher)
# ===========================================================================


class TestRunPromptNoDispatcher:
    """Tests for Evaluator.run_prompt when dispatcher is None.

    This exercises the real code path where prompts are recorded as 'pending'
    when no dispatcher is available. This is NOT mocking -- it is the actual
    production code path for running without a dispatcher.
    """

    @pytest.mark.asyncio
    async def test_prompt_not_found_returns_error(
        self, evaluator_no_prompts: Evaluator
    ) -> None:
        """When prompt file does not exist, returns PromptResult with success=False."""
        pid = _uid()
        result = await evaluator_no_prompts.run_prompt("deepdive", pid, "/tmp/repo")
        assert isinstance(result, PromptResult)
        assert result.prompt_name == "deepdive"
        assert result.success is False
        assert result.error is not None
        assert result.output == ""

    @pytest.mark.asyncio
    async def test_prompt_found_no_dispatcher_returns_pending(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """When prompt file exists but no dispatcher, returns pending PromptResult."""
        pid = _uid()
        result = await evaluator_with_prompts.run_prompt("deepdive", pid, "/tmp/repo")
        assert isinstance(result, PromptResult)
        assert result.prompt_name == "deepdive"
        assert result.phase == "deep_analysis"
        assert result.success is True
        assert result.agent_id is None
        assert result.output == ""
        assert result.error is None

    @pytest.mark.asyncio
    async def test_error_message_references_prompt_name(
        self, evaluator_no_prompts: Evaluator
    ) -> None:
        """Error message includes the prompt name for debugging."""
        pid = _uid()
        result = await evaluator_no_prompts.run_prompt("deepdive", pid, "/tmp/repo")
        assert "deepdive" in result.error

    @pytest.mark.asyncio
    async def test_pending_result_has_positive_duration(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """Even pending prompts record a duration (>= 0)."""
        pid = _uid()
        result = await evaluator_with_prompts.run_prompt("project-context", pid, "/tmp/repo")
        assert result.duration_seconds >= 0.0

    @pytest.mark.asyncio
    async def test_prompt_not_found_error_mentions_search_paths(
        self, evaluator_no_prompts: Evaluator
    ) -> None:
        """Error message includes the .md and .txt paths that were searched."""
        pid = _uid()
        result = await evaluator_no_prompts.run_prompt("deepdive", pid, "/tmp/repo")
        assert ".md" in result.error
        assert ".txt" in result.error


# ===========================================================================
# Module 10: run_phase
# ===========================================================================


class TestRunPhase:
    """Tests for Evaluator.run_phase -- phase-level execution."""

    @pytest.mark.asyncio
    async def test_valid_phase_with_prompt_files_all_succeed(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """Valid phase with all prompt files present: all prompts succeed (pending)."""
        pid = _uid()
        phase_result = await evaluator_with_prompts.run_phase(
            "orientation", pid, "/tmp/repo"
        )
        assert isinstance(phase_result, PhaseResult)
        assert phase_result.phase_name == "orientation"
        assert phase_result.success is True
        assert len(phase_result.prompt_results) == 2
        for pr in phase_result.prompt_results:
            assert pr.success is True

    @pytest.mark.asyncio
    async def test_valid_phase_without_prompt_files_all_fail(
        self, evaluator_no_prompts: Evaluator
    ) -> None:
        """Valid phase with missing prompt files: all prompts fail."""
        pid = _uid()
        phase_result = await evaluator_no_prompts.run_phase(
            "orientation", pid, "/tmp/repo"
        )
        assert phase_result.phase_name == "orientation"
        assert phase_result.success is False
        assert len(phase_result.prompt_results) == 2
        for pr in phase_result.prompt_results:
            assert pr.success is False
            assert pr.error is not None

    @pytest.mark.asyncio
    async def test_unknown_phase_returns_failure(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """Unknown phase name returns PhaseResult with success=False and no prompts."""
        pid = _uid()
        phase_result = await evaluator_with_prompts.run_phase(
            "nonexistent_phase", pid, "/tmp/repo"
        )
        assert phase_result.phase_name == "nonexistent_phase"
        assert phase_result.success is False
        assert len(phase_result.prompt_results) == 0

    @pytest.mark.asyncio
    async def test_phase_success_requires_all_prompts_succeed(
        self, tmp_path: Path
    ) -> None:
        """Phase success is True only when ALL prompts in the phase succeed."""
        # Create a prompts dir with only ONE of the two orientation prompts
        prompts = tmp_path / "partial_prompts"
        prompts.mkdir()
        (prompts / "project-context.md").write_text("# Project Context\n\nContent here.")
        # workspace-scan is missing intentionally

        ev = Evaluator(prompt_dir=str(prompts))
        pid = _uid()
        phase_result = await ev.run_phase("orientation", pid, "/tmp/repo")
        assert phase_result.phase_name == "orientation"
        # First prompt succeeds (file exists), second fails (file missing)
        assert phase_result.prompt_results[0].success is True
        assert phase_result.prompt_results[1].success is False
        # Phase overall must be False because not all prompts succeeded
        assert phase_result.success is False

    @pytest.mark.asyncio
    async def test_deep_analysis_phase_has_three_prompts(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """deep_analysis phase runs exactly 3 prompts."""
        pid = _uid()
        phase_result = await evaluator_with_prompts.run_phase(
            "deep_analysis", pid, "/tmp/repo"
        )
        assert len(phase_result.prompt_results) == 3
        names = [pr.prompt_name for pr in phase_result.prompt_results]
        assert names == ["deepdive", "agonyofdefeatures", "driftx"]

    @pytest.mark.asyncio
    async def test_remediation_phase_has_one_prompt(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """remediation_planning phase runs exactly 1 prompt."""
        pid = _uid()
        phase_result = await evaluator_with_prompts.run_phase(
            "remediation_planning", pid, "/tmp/repo"
        )
        assert len(phase_result.prompt_results) == 1
        assert phase_result.prompt_results[0].prompt_name == "app__mitigen"


# ===========================================================================
# Module 11: run_battery -- full mode
# ===========================================================================


class TestRunBatteryFullMode:
    """Tests for Evaluator.run_battery in full mode (all phases + additional)."""

    @pytest.mark.asyncio
    async def test_full_mode_runs_seven_phases(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """Full mode runs 7 phases: 6 standard + 1 additional."""
        pid = _uid()
        report = await evaluator_with_prompts.run_battery(pid, "/tmp/repo", mode="full")
        assert isinstance(report, EvaluationReport)
        assert len(report.phases) == 7
        phase_names = [p.phase_name for p in report.phases]
        expected = PHASE_NAMES + ["additional"]
        assert phase_names == expected

    @pytest.mark.asyncio
    async def test_full_mode_counts_total_prompts_correctly(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """Full mode total_prompts = 14 (phases) + 4 (additional) = 18."""
        pid = _uid()
        report = await evaluator_with_prompts.run_battery(pid, "/tmp/repo", mode="full")
        assert report.total_prompts == 18

    @pytest.mark.asyncio
    async def test_full_mode_all_succeed_when_files_present(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """When all prompt files exist, all 18 prompts succeed."""
        pid = _uid()
        report = await evaluator_with_prompts.run_battery(pid, "/tmp/repo", mode="full")
        assert report.successful_prompts == 18
        assert report.failed_prompts == 0

    @pytest.mark.asyncio
    async def test_full_mode_all_fail_when_no_files(
        self, evaluator_no_prompts: Evaluator
    ) -> None:
        """When no prompt files exist, all 18 prompts fail."""
        pid = _uid()
        report = await evaluator_no_prompts.run_battery(pid, "/tmp/repo", mode="full")
        assert report.total_prompts == 18
        assert report.failed_prompts == 18
        assert report.successful_prompts == 0

    @pytest.mark.asyncio
    async def test_full_mode_records_created_at(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """Full mode sets created_at to a non-None ISO timestamp."""
        pid = _uid()
        report = await evaluator_with_prompts.run_battery(pid, "/tmp/repo", mode="full")
        assert report.created_at is not None
        # Should be a valid ISO format string (contains 'T' separator)
        assert "T" in report.created_at

    @pytest.mark.asyncio
    async def test_full_mode_duration_is_positive(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """Full mode total_duration_seconds is a positive number."""
        pid = _uid()
        report = await evaluator_with_prompts.run_battery(pid, "/tmp/repo", mode="full")
        assert report.total_duration_seconds > 0.0

    @pytest.mark.asyncio
    async def test_full_mode_report_mode_field(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """Report mode field is 'full'."""
        pid = _uid()
        report = await evaluator_with_prompts.run_battery(pid, "/tmp/repo", mode="full")
        assert report.mode == "full"

    @pytest.mark.asyncio
    async def test_full_mode_report_preserves_project_and_path(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """Report retains the project_id and repo_path from the call."""
        pid = _uid()
        repo_path = "/tmp/my-test-repo"
        report = await evaluator_with_prompts.run_battery(pid, repo_path, mode="full")
        assert report.project_id == pid
        assert report.repo_path == repo_path


# ===========================================================================
# Module 12: run_battery -- quick mode
# ===========================================================================


class TestRunBatteryQuickMode:
    """Tests for Evaluator.run_battery in quick mode (orientation + deep_analysis only)."""

    @pytest.mark.asyncio
    async def test_quick_mode_runs_two_phases(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """Quick mode runs only 2 phases: orientation and deep_analysis."""
        pid = _uid()
        report = await evaluator_with_prompts.run_battery(pid, "/tmp/repo", mode="quick")
        assert len(report.phases) == 2
        phase_names = [p.phase_name for p in report.phases]
        assert phase_names == ["orientation", "deep_analysis"]

    @pytest.mark.asyncio
    async def test_quick_mode_does_not_include_additional(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """Quick mode does not include the additional prompts phase."""
        pid = _uid()
        report = await evaluator_with_prompts.run_battery(pid, "/tmp/repo", mode="quick")
        phase_names = [p.phase_name for p in report.phases]
        assert "additional" not in phase_names

    @pytest.mark.asyncio
    async def test_quick_mode_total_prompts_is_five(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """Quick mode total_prompts = 2 (orientation) + 3 (deep_analysis) = 5."""
        pid = _uid()
        report = await evaluator_with_prompts.run_battery(pid, "/tmp/repo", mode="quick")
        assert report.total_prompts == 5

    @pytest.mark.asyncio
    async def test_quick_mode_report_mode_field(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """Report mode field is 'quick'."""
        pid = _uid()
        report = await evaluator_with_prompts.run_battery(pid, "/tmp/repo", mode="quick")
        assert report.mode == "quick"

    @pytest.mark.asyncio
    async def test_quick_mode_all_succeed_when_files_present(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """Quick mode with all prompt files: 5 succeed, 0 fail."""
        pid = _uid()
        report = await evaluator_with_prompts.run_battery(pid, "/tmp/repo", mode="quick")
        assert report.successful_prompts == 5
        assert report.failed_prompts == 0

    @pytest.mark.asyncio
    async def test_quick_mode_duration_is_positive(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """Quick mode total_duration_seconds is positive."""
        pid = _uid()
        report = await evaluator_with_prompts.run_battery(pid, "/tmp/repo", mode="quick")
        assert report.total_duration_seconds > 0.0


# ===========================================================================
# Module 13: run_battery with repository (episode logging)
# ===========================================================================


class TestRunBatteryWithRepository:
    """Tests for Evaluator.run_battery episode logging via a real Repository.

    Each test creates a real project in the in-memory DB first so that the
    episodes table FK constraint on project_id is satisfied.
    """

    @pytest.mark.asyncio
    async def test_full_mode_logs_episode_when_repository_provided(
        self, repository, prompt_dir: str
    ) -> None:
        """Full mode logs an evaluation_battery_complete episode to the DB."""
        pid = await _create_project_in_db(repository)
        ev = Evaluator(repository=repository, dispatcher=None, prompt_dir=prompt_dir)
        report = await ev.run_battery(pid, "/tmp/repo", mode="full")

        # Verify the episode was logged by querying the episodes table
        rows = await repository.engine.fetch_all(
            "SELECT * FROM episodes WHERE project_id = ? AND event_type = ?",
            [pid, "evaluation_battery_complete"],
        )
        assert len(rows) >= 1
        row = rows[0]
        assert row["project_id"] == pid
        assert row["event_type"] == "evaluation_battery_complete"
        assert row["cycle_level"] == "meso"

    @pytest.mark.asyncio
    async def test_full_mode_logs_pending_episodes_for_each_prompt(
        self, repository, prompt_dir: str
    ) -> None:
        """Each prompt without a dispatcher logs an evaluation_prompt_pending episode."""
        pid = await _create_project_in_db(repository)
        ev = Evaluator(repository=repository, dispatcher=None, prompt_dir=prompt_dir)
        await ev.run_battery(pid, "/tmp/repo", mode="full")

        # All 18 prompts should have pending episodes
        rows = await repository.engine.fetch_all(
            "SELECT * FROM episodes WHERE project_id = ? AND event_type = ?",
            [pid, "evaluation_prompt_pending"],
        )
        assert len(rows) == 18

    @pytest.mark.asyncio
    async def test_missing_prompt_logs_error_episode(
        self, repository, empty_prompt_dir: str
    ) -> None:
        """Missing prompt files log evaluation_prompt_error episodes."""
        pid = await _create_project_in_db(repository)
        ev = Evaluator(repository=repository, dispatcher=None, prompt_dir=empty_prompt_dir)
        await ev.run_prompt("deepdive", pid, "/tmp/repo")

        rows = await repository.engine.fetch_all(
            "SELECT * FROM episodes WHERE project_id = ? AND event_type = ?",
            [pid, "evaluation_prompt_error"],
        )
        assert len(rows) == 1
        assert rows[0]["project_id"] == pid

    @pytest.mark.asyncio
    async def test_quick_mode_logs_battery_complete_episode(
        self, repository, prompt_dir: str
    ) -> None:
        """Quick mode also logs an evaluation_battery_complete episode."""
        pid = await _create_project_in_db(repository)
        ev = Evaluator(repository=repository, dispatcher=None, prompt_dir=prompt_dir)
        await ev.run_battery(pid, "/tmp/repo", mode="quick")

        rows = await repository.engine.fetch_all(
            "SELECT * FROM episodes WHERE project_id = ? AND event_type = ?",
            [pid, "evaluation_battery_complete"],
        )
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_quick_mode_logs_five_pending_episodes(
        self, repository, prompt_dir: str
    ) -> None:
        """Quick mode logs 5 pending episodes (2 orientation + 3 deep_analysis)."""
        pid = await _create_project_in_db(repository)
        ev = Evaluator(repository=repository, dispatcher=None, prompt_dir=prompt_dir)
        await ev.run_battery(pid, "/tmp/repo", mode="quick")

        rows = await repository.engine.fetch_all(
            "SELECT * FROM episodes WHERE project_id = ? AND event_type = ?",
            [pid, "evaluation_prompt_pending"],
        )
        assert len(rows) == 5

    @pytest.mark.asyncio
    async def test_battery_complete_episode_data_contains_mode(
        self, repository, prompt_dir: str
    ) -> None:
        """The evaluation_battery_complete episode event_data contains the mode."""
        import json

        pid = await _create_project_in_db(repository)
        ev = Evaluator(repository=repository, dispatcher=None, prompt_dir=prompt_dir)
        await ev.run_battery(pid, "/tmp/repo", mode="full")

        rows = await repository.engine.fetch_all(
            "SELECT * FROM episodes WHERE project_id = ? AND event_type = ?",
            [pid, "evaluation_battery_complete"],
        )
        assert len(rows) == 1
        event_data = json.loads(rows[0]["event_data"])
        assert event_data["mode"] == "full"
        assert event_data["total_prompts"] == 18
        assert event_data["successful_prompts"] == 18
        assert event_data["failed_prompts"] == 0
        assert "duration_seconds" in event_data

    @pytest.mark.asyncio
    async def test_error_episode_data_contains_prompt_name(
        self, repository, empty_prompt_dir: str
    ) -> None:
        """The evaluation_prompt_error episode event_data contains prompt details."""
        import json

        pid = await _create_project_in_db(repository)
        ev = Evaluator(repository=repository, dispatcher=None, prompt_dir=empty_prompt_dir)
        await ev.run_prompt("claim-gate", pid, "/tmp/repo")

        rows = await repository.engine.fetch_all(
            "SELECT * FROM episodes WHERE project_id = ? AND event_type = ?",
            [pid, "evaluation_prompt_error"],
        )
        assert len(rows) == 1
        event_data = json.loads(rows[0]["event_data"])
        assert event_data["prompt_name"] == "claim-gate"
        assert event_data["phase"] == "truth_verification"
        assert "error" in event_data


# ===========================================================================
# Module 14: Cross-cutting / edge case tests
# ===========================================================================


class TestEvaluatorEdgeCases:
    """Cross-cutting edge cases and boundary condition tests."""

    @pytest.mark.asyncio
    async def test_run_prompt_for_each_additional_prompt(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """Each of the 4 additional prompts can be run individually."""
        pid = _uid()
        for name in ADDITIONAL_PROMPTS:
            result = await evaluator_with_prompts.run_prompt(name, pid, "/tmp/repo")
            assert result.prompt_name == name
            assert result.phase == "additional"
            assert result.success is True

    @pytest.mark.asyncio
    async def test_run_prompt_phase_field_matches_lookup(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """PromptResult.phase matches get_phase_for_prompt for all standard prompts."""
        pid = _uid()
        ev = evaluator_with_prompts
        for phase_name, prompt_names in EVALUATION_PHASES:
            for prompt_name in prompt_names:
                result = await ev.run_prompt(prompt_name, pid, "/tmp/repo")
                assert result.phase == phase_name
                assert result.phase == ev.get_phase_for_prompt(prompt_name)

    @pytest.mark.asyncio
    async def test_unknown_prompt_phase_is_unknown(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """A prompt not in any phase gets phase='unknown' in the PromptResult."""
        pid = _uid()
        result = await evaluator_with_prompts.run_prompt(
            "totally-bogus-prompt", pid, "/tmp/repo"
        )
        assert result.phase == "unknown"

    @pytest.mark.asyncio
    async def test_multiple_evaluators_use_different_session_ids(
        self, prompt_dir: str
    ) -> None:
        """Each Evaluator instance gets a unique session_id."""
        ev1 = Evaluator(prompt_dir=prompt_dir)
        ev2 = Evaluator(prompt_dir=prompt_dir)
        assert ev1._session_id != ev2._session_id

    def test_prompt_content_strips_whitespace(self, tmp_path: Path) -> None:
        """get_prompt_content strips leading/trailing whitespace from file content."""
        prompts = tmp_path / "strip_prompts"
        prompts.mkdir()
        (prompts / "test-prompt.md").write_text("   \n  Content here  \n  \n")
        ev = Evaluator(prompt_dir=str(prompts))
        content = ev.get_prompt_content("test-prompt")
        assert content == "Content here"

    @pytest.mark.asyncio
    async def test_full_battery_additional_phase_is_last(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """In full mode, the additional phase is always the last phase."""
        pid = _uid()
        report = await evaluator_with_prompts.run_battery(pid, "/tmp/repo", mode="full")
        assert report.phases[-1].phase_name == "additional"
        assert len(report.phases[-1].prompt_results) == 4

    @pytest.mark.asyncio
    async def test_full_battery_successful_plus_failed_equals_total(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """successful_prompts + failed_prompts always equals total_prompts."""
        pid = _uid()
        report = await evaluator_with_prompts.run_battery(pid, "/tmp/repo", mode="full")
        assert report.successful_prompts + report.failed_prompts == report.total_prompts

    @pytest.mark.asyncio
    async def test_quick_battery_successful_plus_failed_equals_total(
        self, evaluator_no_prompts: Evaluator
    ) -> None:
        """Holds for quick mode with all failures too."""
        pid = _uid()
        report = await evaluator_no_prompts.run_battery(pid, "/tmp/repo", mode="quick")
        assert report.successful_prompts + report.failed_prompts == report.total_prompts

    @pytest.mark.asyncio
    async def test_run_all_phases_individually(
        self, evaluator_with_prompts: Evaluator
    ) -> None:
        """Every standard phase can be run individually and returns correct prompt count."""
        pid = _uid()
        expected_counts = {
            "orientation": 2,
            "deep_analysis": 3,
            "truth_verification": 3,
            "quality_assessment": 3,
            "documentation": 2,
            "remediation_planning": 1,
        }
        for phase_name, expected_count in expected_counts.items():
            result = await evaluator_with_prompts.run_phase(phase_name, pid, "/tmp/repo")
            assert len(result.prompt_results) == expected_count, (
                f"Phase '{phase_name}' expected {expected_count} prompts, "
                f"got {len(result.prompt_results)}"
            )
            assert result.success is True

    @pytest.mark.asyncio
    async def test_full_battery_with_partial_prompt_files(
        self, tmp_path: Path
    ) -> None:
        """Battery with only some prompt files reports correct success/failure split."""
        prompts = tmp_path / "partial"
        prompts.mkdir()
        # Only create orientation prompts (2 files)
        (prompts / "project-context.md").write_text("# Project Context\n\nContent.")
        (prompts / "workspace-scan.md").write_text("# Workspace Scan\n\nContent.")

        ev = Evaluator(prompt_dir=str(prompts))
        pid = _uid()
        report = await ev.run_battery(pid, "/tmp/repo", mode="full")

        # 2 succeed (orientation), 16 fail (12 other phase + 4 additional)
        assert report.successful_prompts == 2
        assert report.failed_prompts == 16
        assert report.total_prompts == 18
        assert report.successful_prompts + report.failed_prompts == report.total_prompts

    def test_session_id_is_valid_uuid(self) -> None:
        """Each evaluator's session_id is a valid UUID string."""
        ev = Evaluator()
        # Should not raise ValueError
        parsed = uuid.UUID(ev._session_id)
        assert str(parsed) == ev._session_id
