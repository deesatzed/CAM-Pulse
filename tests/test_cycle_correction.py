"""Tests for the inner correction loop in MicroClaw.

Validates that:
- Failed verifications trigger correction attempts with feedback
- Non-correctable failures skip the correction loop
- The correction budget (max_correction_attempts) is respected
- Workspace is restored between correction attempts
- Correction feedback is injected into the agent prompt
- First-attempt successes bypass the correction loop entirely
"""

from __future__ import annotations

import pytest

from claw.core.models import (
    CorrectionFeedback,
    ContextBrief,
    Project,
    Task,
    TaskContext,
    TaskOutcome,
    TaskStatus,
    VerificationResult,
)
from claw.cycle import (
    MicroClaw,
    _is_correctable_failure,
    _restore_workspace,
    _snapshot_workspace_content,
)


class TestCorrectionFeedbackModel:
    """Tests for the CorrectionFeedback Pydantic model."""

    def test_defaults(self):
        fb = CorrectionFeedback()
        assert fb.attempt_number == 0
        assert fb.violations == []
        assert fb.test_output == ""
        assert fb.diff == ""
        assert fb.quality_score == 0.0
        assert fb.failure_reason is None
        assert fb.failure_detail is None

    def test_with_values(self):
        fb = CorrectionFeedback(
            attempt_number=2,
            violations=[{"check": "test_execution", "detail": "3 failed"}],
            test_output="FAILED test_foo - AssertionError",
            diff="*** app.py",
            quality_score=0.3,
            failure_reason="tests_failed",
            failure_detail="3 of 5 tests failed",
        )
        assert fb.attempt_number == 2
        assert len(fb.violations) == 1
        assert fb.violations[0]["check"] == "test_execution"

    def test_task_context_carries_correction(self):
        fb = CorrectionFeedback(attempt_number=1)
        task = Task(
            project_id="p1",
            title="test",
            description="test task",
        )
        ctx = TaskContext(task=task, correction_feedback=fb)
        assert ctx.correction_feedback is not None
        assert ctx.correction_feedback.attempt_number == 1

    def test_context_brief_carries_correction(self):
        fb = CorrectionFeedback(attempt_number=2)
        task = Task(
            project_id="p1",
            title="test",
            description="test task",
        )
        brief = ContextBrief(task=task, correction_feedback=fb)
        assert brief.correction_feedback is not None
        assert brief.correction_feedback.attempt_number == 2


class TestIsCorrectableFailure:
    """Tests for the _is_correctable_failure() classifier."""

    def test_test_failure_is_correctable(self):
        outcome = TaskOutcome(tests_passed=False)
        verification = VerificationResult(
            approved=False,
            violations=[{"check": "test_execution", "detail": "Tests failed"}],
        )
        assert _is_correctable_failure(outcome, verification) is True

    def test_placeholder_violation_is_correctable(self):
        outcome = TaskOutcome(tests_passed=True)
        verification = VerificationResult(
            approved=False,
            violations=[{"check": "placeholder_scan", "detail": "Found TODO"}],
        )
        assert _is_correctable_failure(outcome, verification) is True

    def test_drift_violation_is_correctable(self):
        outcome = TaskOutcome()
        verification = VerificationResult(
            approved=False,
            violations=[{"check": "drift_alignment", "detail": "0.2 < threshold"}],
        )
        assert _is_correctable_failure(outcome, verification) is True

    def test_budget_exceeded_not_correctable(self):
        outcome = TaskOutcome(failure_reason="budget_exceeded")
        verification = VerificationResult(approved=False)
        assert _is_correctable_failure(outcome, verification) is False

    def test_no_agent_not_correctable(self):
        outcome = TaskOutcome(failure_reason="no_agent")
        verification = VerificationResult(approved=False)
        assert _is_correctable_failure(outcome, verification) is False

    def test_no_workspace_changes_not_correctable(self):
        outcome = TaskOutcome(failure_reason="no_workspace_changes")
        verification = VerificationResult(approved=False)
        assert _is_correctable_failure(outcome, verification) is False

    def test_http_error_not_correctable(self):
        outcome = TaskOutcome(failure_reason="http_500")
        verification = VerificationResult(approved=False)
        assert _is_correctable_failure(outcome, verification) is False

    def test_timeout_not_correctable(self):
        outcome = TaskOutcome(failure_reason="timeout")
        verification = VerificationResult(approved=False)
        assert _is_correctable_failure(outcome, verification) is False

    def test_approved_with_no_violations_not_correctable(self):
        """Approved results should not have violations."""
        outcome = TaskOutcome()
        verification = VerificationResult(approved=False, violations=[])
        assert _is_correctable_failure(outcome, verification) is False

    def test_environment_setup_violation_not_correctable(self):
        """environment_setup violations cannot be fixed by agent — don't retry."""
        outcome = TaskOutcome()
        verification = VerificationResult(
            approved=False,
            violations=[{
                "check": "environment_setup",
                "detail": "command_not_found: exit code 127 running 'ng'",
            }],
        )
        assert _is_correctable_failure(outcome, verification) is False

    def test_environment_setup_mixed_with_test_failure_not_correctable(self):
        """If any violation is environment_setup, the whole set is non-correctable."""
        outcome = TaskOutcome()
        verification = VerificationResult(
            approved=False,
            violations=[
                {"check": "test_execution", "detail": "Tests failed"},
                {"check": "environment_setup", "detail": "ModuleNotFoundError"},
            ],
        )
        assert _is_correctable_failure(outcome, verification) is False

    def test_test_execution_without_env_issue_is_correctable(self):
        """Normal test failures (no environment_setup) should still be correctable."""
        outcome = TaskOutcome()
        verification = VerificationResult(
            approved=False,
            violations=[{"check": "test_execution", "detail": "AssertionError in test_foo"}],
        )
        assert _is_correctable_failure(outcome, verification) is True


class TestWorkspaceSnapshotRestore:
    """Tests for content-based workspace snapshot and restore."""

    def test_snapshot_captures_file_contents(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "a.py").write_text("original\n", encoding="utf-8")
        (workspace / "sub").mkdir()
        (workspace / "sub" / "b.py").write_text("hello\n", encoding="utf-8")

        snap = _snapshot_workspace_content(str(workspace))
        assert snap["a.py"] == b"original\n"
        assert snap["sub/b.py"] == b"hello\n"

    def test_snapshot_ignores_git_and_pycache(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / ".git").mkdir()
        (workspace / ".git" / "config").write_text("gitdata", encoding="utf-8")
        (workspace / "__pycache__").mkdir()
        (workspace / "__pycache__" / "x.pyc").write_bytes(b"\x00")
        (workspace / "real.py").write_text("code\n", encoding="utf-8")

        snap = _snapshot_workspace_content(str(workspace))
        assert "real.py" in snap
        assert ".git/config" not in snap
        assert "__pycache__/x.pyc" not in snap

    def test_snapshot_empty_workspace(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        snap = _snapshot_workspace_content(str(workspace))
        assert snap == {}

    def test_snapshot_none_workspace(self):
        snap = _snapshot_workspace_content(None)
        assert snap == {}

    def test_restore_reverts_modified_files(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "a.py").write_text("original\n", encoding="utf-8")

        snap = _snapshot_workspace_content(str(workspace))

        # Modify
        (workspace / "a.py").write_text("modified\n", encoding="utf-8")
        assert (workspace / "a.py").read_text() == "modified\n"

        # Restore
        _restore_workspace(str(workspace), snap)
        assert (workspace / "a.py").read_text() == "original\n"

    def test_restore_removes_added_files(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "a.py").write_text("original\n", encoding="utf-8")

        snap = _snapshot_workspace_content(str(workspace))

        # Add a new file
        (workspace / "new.py").write_text("added\n", encoding="utf-8")
        assert (workspace / "new.py").exists()

        # Restore
        _restore_workspace(str(workspace), snap)
        assert not (workspace / "new.py").exists()
        assert (workspace / "a.py").read_text() == "original\n"

    def test_restore_recreates_deleted_files(self, tmp_path):
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "a.py").write_text("original\n", encoding="utf-8")

        snap = _snapshot_workspace_content(str(workspace))

        # Delete
        (workspace / "a.py").unlink()
        assert not (workspace / "a.py").exists()

        # Restore
        _restore_workspace(str(workspace), snap)
        assert (workspace / "a.py").read_text() == "original\n"

    def test_snapshot_excludes_node_modules(self, tmp_path):
        """node_modules must be excluded so auto-installed deps survive restore."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        nm = workspace / "node_modules" / ".bin"
        nm.mkdir(parents=True)
        (nm / "ng").write_text("#!/bin/sh\necho ng", encoding="utf-8")
        (workspace / "app.js").write_text("code\n", encoding="utf-8")

        snap = _snapshot_workspace_content(str(workspace))
        assert "app.js" in snap
        assert "node_modules/.bin/ng" not in snap

    def test_restore_preserves_node_modules(self, tmp_path):
        """Restore should NOT delete node_modules even though it wasn't in snapshot."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "app.js").write_text("code\n", encoding="utf-8")

        snap = _snapshot_workspace_content(str(workspace))

        # Simulate auto-install creating node_modules after snapshot
        nm = workspace / "node_modules" / ".bin"
        nm.mkdir(parents=True)
        (nm / "ng").write_text("#!/bin/sh\necho ng", encoding="utf-8")

        # Agent also added a file
        (workspace / "new.js").write_text("agent code\n", encoding="utf-8")

        _restore_workspace(str(workspace), snap)

        # Agent's file should be removed
        assert not (workspace / "new.js").exists()
        # But node_modules should survive
        assert (nm / "ng").exists()

    def test_snapshot_excludes_venv(self, tmp_path):
        """venv/.venv must be excluded from snapshot/restore."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        venv = workspace / ".venv" / "bin"
        venv.mkdir(parents=True)
        (venv / "python").write_text("#!/bin/sh", encoding="utf-8")
        (workspace / "main.py").write_text("print('hi')\n", encoding="utf-8")

        snap = _snapshot_workspace_content(str(workspace))
        assert "main.py" in snap
        assert ".venv/bin/python" not in snap

    def test_restore_preserves_venv(self, tmp_path):
        """Restore should NOT delete .venv even though it wasn't in snapshot."""
        workspace = tmp_path / "ws"
        workspace.mkdir()
        (workspace / "main.py").write_text("code\n", encoding="utf-8")

        snap = _snapshot_workspace_content(str(workspace))

        # Simulate pip install creating venv after snapshot
        venv = workspace / "venv" / "lib"
        venv.mkdir(parents=True)
        (venv / "site.py").write_text("site", encoding="utf-8")

        _restore_workspace(str(workspace), snap)

        # venv should survive
        assert (venv / "site.py").exists()


class TestActWithCorrection:
    """Integration tests for the inner correction loop in MicroClaw."""

    async def test_first_attempt_success_no_correction_needed(
        self, claw_context, sample_project, sample_task, tmp_path
    ):
        """When first attempt passes verification, no correction loop runs."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        workspace = tmp_path / "repo"
        workspace.mkdir()

        call_count = 0

        class SuccessAgent:
            workspace_dir = str(workspace)

            async def run(self, task_ctx, **kwargs):
                nonlocal call_count
                call_count += 1
                (workspace / "app.py").write_text("print('ok')\n", encoding="utf-8")
                return TaskOutcome(
                    approach_summary="Built it right first time",
                    tests_passed=True,
                    raw_output="done",
                )

        ctx.agents["codex"] = SuccessAgent()

        micro = MicroClaw(ctx, sample_project.id)
        task_ctx = TaskContext(task=sample_task)
        decision = ("codex", task_ctx)

        result = await micro._act_with_correction(decision)
        agent_id, _, outcome, verification = result

        assert verification.approved is True
        assert call_count == 1  # Only one attempt, no correction

    async def test_correction_fixes_failing_agent(
        self, claw_context, sample_project, sample_task, tmp_path
    ):
        """Agent fails first attempt, succeeds on correction retry."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        workspace = tmp_path / "repo"
        workspace.mkdir()

        call_count = 0

        class FixableAgent:
            workspace_dir = str(workspace)

            async def run(self, task_ctx, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    # First attempt: write buggy code with a TODO
                    (workspace / "app.py").write_text(
                        "# TODO: implement properly\nraise NotImplementedError\n",
                        encoding="utf-8",
                    )
                    return TaskOutcome(
                        approach_summary="Initial attempt",
                        tests_passed=False,
                        raw_output="# TODO: implement properly\nraise NotImplementedError",
                    )
                else:
                    # Correction attempt: fix it
                    (workspace / "app.py").write_text(
                        "def main():\n    print('working')\n",
                        encoding="utf-8",
                    )
                    return TaskOutcome(
                        approach_summary="Fixed implementation",
                        tests_passed=True,
                        raw_output="done",
                    )

        ctx.agents["codex"] = FixableAgent()

        micro = MicroClaw(ctx, sample_project.id)
        task_ctx = TaskContext(task=sample_task)
        decision = ("codex", task_ctx)

        result = await micro._act_with_correction(decision)
        agent_id, _, outcome, verification = result

        # Should succeed on second attempt
        assert call_count == 2
        assert verification.approved is True

    async def test_non_correctable_failure_skips_correction(
        self, claw_context, sample_project, sample_task, tmp_path
    ):
        """Infrastructure failures (no agent, budget, etc.) skip the correction loop."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        workspace = tmp_path / "repo"
        workspace.mkdir()

        call_count = 0

        class NoChangeAgent:
            workspace_dir = str(workspace)

            async def run(self, task_ctx, **kwargs):
                nonlocal call_count
                call_count += 1
                # Agent doesn't modify workspace — not correctable
                return TaskOutcome(
                    approach_summary="Did nothing",
                    tests_passed=True,
                    raw_output="nothing changed",
                )

        ctx.agents["codex"] = NoChangeAgent()

        micro = MicroClaw(ctx, sample_project.id)
        task_ctx = TaskContext(task=sample_task)
        decision = ("codex", task_ctx)

        result = await micro._act_with_correction(decision)
        agent_id, _, outcome, verification = result

        # Should only run once — no_workspace_changes is not correctable
        assert call_count == 1
        assert outcome.failure_reason == "no_workspace_changes"

    async def test_max_correction_attempts_respected(
        self, claw_context, sample_project, sample_task, tmp_path
    ):
        """Correction loop stops after max_correction_attempts."""
        ctx = claw_context
        # Set low budget for testing
        ctx.config.orchestrator.max_correction_attempts = 2
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        workspace = tmp_path / "repo"
        workspace.mkdir()

        call_count = 0

        class AlwaysFailAgent:
            workspace_dir = str(workspace)

            async def run(self, task_ctx, **kwargs):
                nonlocal call_count
                call_count += 1
                # Always writes a placeholder
                (workspace / "app.py").write_text(
                    "# TODO: fix this\n", encoding="utf-8"
                )
                return TaskOutcome(
                    approach_summary=f"Attempt {call_count}",
                    tests_passed=True,
                    raw_output="# TODO: fix this",
                )

        ctx.agents["codex"] = AlwaysFailAgent()

        micro = MicroClaw(ctx, sample_project.id)
        task_ctx = TaskContext(task=sample_task)
        decision = ("codex", task_ctx)

        result = await micro._act_with_correction(decision)
        _, _, outcome, verification = result

        # Should run exactly max_correction_attempts times
        assert call_count == 2
        assert verification.approved is False

    async def test_workspace_restored_between_attempts(
        self, claw_context, sample_project, sample_task, tmp_path
    ):
        """Workspace is restored to original state between correction attempts."""
        ctx = claw_context
        ctx.config.orchestrator.max_correction_attempts = 3
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        workspace = tmp_path / "repo"
        workspace.mkdir()
        (workspace / "original.py").write_text("original\n", encoding="utf-8")

        workspace_states = []

        class TrackingAgent:
            workspace_dir = str(workspace)

            async def run(self, task_ctx, **kwargs):
                # Record what files exist at the start of each attempt
                files = sorted(f.name for f in workspace.iterdir() if f.is_file())
                workspace_states.append(files)
                # Add a file and write a placeholder (will trigger violation)
                (workspace / "added.py").write_text("# TODO\n", encoding="utf-8")
                (workspace / "original.py").write_text("modified\n", encoding="utf-8")
                return TaskOutcome(
                    approach_summary="Modified workspace",
                    tests_passed=True,
                    raw_output="# TODO: placeholder",
                )

        ctx.agents["codex"] = TrackingAgent()

        micro = MicroClaw(ctx, sample_project.id)
        task_ctx = TaskContext(task=sample_task)
        decision = ("codex", task_ctx)

        await micro._act_with_correction(decision)

        # First attempt sees original state
        assert workspace_states[0] == ["original.py"]
        # Subsequent attempts should ALSO see original state (workspace restored)
        for i, state in enumerate(workspace_states[1:], 1):
            assert state == ["original.py"], (
                f"Attempt {i + 1} saw {state} instead of ['original.py'] — "
                f"workspace was not restored"
            )

    async def test_correction_feedback_injected_into_context(
        self, claw_context, sample_project, sample_task, tmp_path
    ):
        """Correction feedback is set on TaskContext before retry."""
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        workspace = tmp_path / "repo"
        workspace.mkdir()

        received_feedback = []

        class FeedbackCheckAgent:
            workspace_dir = str(workspace)

            async def run(self, task_ctx, **kwargs):
                # Capture the correction feedback on each call
                received_feedback.append(task_ctx.correction_feedback)
                if task_ctx.correction_feedback is None:
                    # First attempt: fail with placeholder
                    (workspace / "app.py").write_text("# TODO\n", encoding="utf-8")
                    return TaskOutcome(
                        approach_summary="First attempt",
                        tests_passed=True,
                        raw_output="# TODO: placeholder",
                    )
                else:
                    # Correction attempt: succeed
                    (workspace / "app.py").write_text(
                        "def main(): pass\n", encoding="utf-8"
                    )
                    return TaskOutcome(
                        approach_summary="Fixed",
                        tests_passed=True,
                        raw_output="done",
                    )

        ctx.agents["codex"] = FeedbackCheckAgent()

        micro = MicroClaw(ctx, sample_project.id)
        task_ctx = TaskContext(task=sample_task)
        decision = ("codex", task_ctx)

        await micro._act_with_correction(decision)

        # First call: no feedback
        assert received_feedback[0] is None
        # Second call: feedback present with violations
        assert received_feedback[1] is not None
        assert received_feedback[1].attempt_number == 1
        assert len(received_feedback[1].violations) > 0


class TestVerificationResultTestOutput:
    """Verify that VerificationResult carries test_output."""

    def test_default_empty(self):
        vr = VerificationResult()
        assert vr.test_output == ""

    def test_carries_output(self):
        vr = VerificationResult(test_output="FAILED test_foo - AssertionError")
        assert "FAILED" in vr.test_output
