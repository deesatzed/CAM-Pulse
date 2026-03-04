"""Tests for CLAW cycle orchestration."""

import pytest

from claw.core.models import Project, Task, TaskStatus
from claw.cycle import MicroClaw


class TestMicroClaw:
    async def test_grab_returns_task(self, claw_context, sample_project, sample_task):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        assert grabbed is not None
        assert grabbed.title == sample_task.title

    async def test_grab_returns_none_when_empty(self, claw_context, sample_project):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        assert grabbed is None

    async def test_grab_respects_priority(self, claw_context, sample_project):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)

        low = Task(project_id=sample_project.id, title="Low", description="low pri", priority=1)
        high = Task(project_id=sample_project.id, title="High", description="high pri", priority=10)
        await ctx.repository.create_task(low)
        await ctx.repository.create_task(high)

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        assert grabbed.title == "High"

    async def test_evaluate_builds_context(self, claw_context, sample_project, sample_task):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        assert task_ctx.task.id == sample_task.id
        assert isinstance(task_ctx.forbidden_approaches, list)

    async def test_decide_routes_to_available_agent(self, claw_context, sample_project, sample_task):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        micro = MicroClaw(ctx, sample_project.id)
        grabbed = await micro.grab()
        task_ctx = await micro.evaluate(grabbed)
        agent_id, decided_ctx = await micro.decide(task_ctx)

        # No agents in test context, but decide handles gracefully
        # The important thing is it doesn't crash
        assert isinstance(agent_id, str)

    async def test_full_cycle_status_tracking(self, claw_context, sample_project, sample_task):
        ctx = claw_context
        await ctx.repository.create_project(sample_project)
        await ctx.repository.create_task(sample_task)

        micro = MicroClaw(ctx, sample_project.id)

        # Grab sets nothing yet
        grabbed = await micro.grab()
        assert grabbed is not None

        # Evaluate moves to EVALUATING
        task_ctx = await micro.evaluate(grabbed)
        got = await ctx.repository.get_task(sample_task.id)
        assert got.status == TaskStatus.EVALUATING

        # Decide moves to DISPATCHED
        agent_id, decided_ctx = await micro.decide(task_ctx)
        got = await ctx.repository.get_task(sample_task.id)
        assert got.status == TaskStatus.DISPATCHED
