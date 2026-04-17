"""Tests for the attribution proof feature.

Uses real in-memory SQLite (no mocks).
Validates the system-wide attribution funnel logic.
"""

from __future__ import annotations

import json

from claw.core.models import Methodology, MethodologyUsageEntry, Project, Task

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROJECT_ID: str | None = None
_TASK_COUNTER: int = 0


async def _ensure_project(repository) -> str:
    """Ensure a test project exists and return its ID."""
    global _PROJECT_ID
    if _PROJECT_ID is not None:
        existing = await repository.get_project(_PROJECT_ID)
        if existing is not None:
            return _PROJECT_ID
    p = Project(
        name="test-project",
        repo_path="/tmp/test-repo",
        tech_stack={"language": "python"},
    )
    saved = await repository.create_project(p)
    _PROJECT_ID = saved.id
    return saved.id


async def _ensure_task(repository, task_id_label: str) -> str:
    """Create a real task and return its ID (uses label for title only)."""
    project_id = await _ensure_project(repository)
    t = Task(
        project_id=project_id,
        title=f"Test task {task_id_label}",
        description="Attribution test task",
        priority=5,
        task_type="general",
    )
    saved = await repository.create_task(t)
    return saved.id


async def _insert_methodology(repository, problem: str = "Test problem") -> Methodology:
    """Insert a real methodology and return it."""
    m = Methodology(
        problem_description=problem,
        solution_code="def solve(): pass",
        methodology_notes="Test notes",
        tags=["source:test-repo"],
        language="python",
        lifecycle_state="viable",
    )
    return await repository.save_methodology(m)


async def _log_usage(
    repository,
    task_id: str,
    methodology_id: str,
    stage: str,
    success: bool | None = None,
    quality_score: float | None = None,
    relevance_score: float | None = None,
) -> None:
    """Insert a methodology_usage_log entry."""
    project_id = await _ensure_project(repository)
    await repository.log_methodology_usage(
        MethodologyUsageEntry(
            task_id=task_id,
            methodology_id=methodology_id,
            project_id=project_id,
            stage=stage,
            agent_id="claude",
            success=success,
            quality_score=quality_score,
            relevance_score=relevance_score,
            notes=f"Test {stage}",
        )
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProofReportEmptyDB:
    """When the DB has no usage entries, proof should return zero counts."""

    async def test_empty_funnel(self, repository):
        stats = await repository.get_methodology_usage_stats()
        assert stats == {}

    async def test_empty_list_methodologies(self, repository):
        methods = await repository.list_methodologies(limit=100, include_dead=True)
        assert methods == []


class TestProofReportFullFunnel:
    """Insert entries at all 3 stages and verify counts + rates."""

    async def test_full_funnel(self, repository):
        m1 = await _insert_methodology(repository, "Auth middleware")
        m2 = await _insert_methodology(repository, "Rate limiter")

        task_id = await _ensure_task(repository, "full-funnel")

        # m1: retrieved -> used -> attributed (success)
        await _log_usage(
            repository, task_id, m1.id, "retrieved_presented",
            relevance_score=0.85,
        )
        await _log_usage(
            repository, task_id, m1.id, "used_in_outcome",
            success=True, quality_score=0.9,
        )
        await _log_usage(
            repository, task_id, m1.id, "outcome_attributed",
            success=True, quality_score=0.9,
        )

        # m2: retrieved -> used -> attributed (failure)
        await _log_usage(
            repository, task_id, m2.id, "retrieved_presented",
            relevance_score=0.7,
        )
        await _log_usage(
            repository, task_id, m2.id, "used_in_outcome",
            success=False, quality_score=0.3,
        )
        await _log_usage(
            repository, task_id, m2.id, "outcome_attributed",
            success=False, quality_score=0.3,
        )

        stats = await repository.get_methodology_usage_stats()
        assert len(stats) == 2

        m1_stats = stats[m1.id]
        assert m1_stats["retrieved_count"] == 1
        assert m1_stats["used_count"] == 1
        assert m1_stats["attributed_success_count"] == 1
        assert m1_stats["attributed_failure_count"] == 0

        m2_stats = stats[m2.id]
        assert m2_stats["retrieved_count"] == 1
        assert m2_stats["used_count"] == 1
        assert m2_stats["attributed_success_count"] == 0
        assert m2_stats["attributed_failure_count"] == 1

    async def test_funnel_rates(self, repository):
        m1 = await _insert_methodology(repository, "Cache pattern")

        # Create 3 real tasks for 3 retrievals
        task_ids = []
        for i in range(3):
            tid = await _ensure_task(repository, f"rates-{i}")
            task_ids.append(tid)

        # Retrieved 3 times, applied 2, succeeded 1
        for tid in task_ids:
            await _log_usage(repository, tid, m1.id, "retrieved_presented")
        for tid in task_ids[:2]:
            await _log_usage(repository, tid, m1.id, "used_in_outcome", success=True)
        await _log_usage(repository, task_ids[0], m1.id, "outcome_attributed", success=True)

        stats = await repository.get_methodology_usage_stats()
        s = stats[m1.id]
        assert s["retrieved_count"] == 3
        assert s["used_count"] == 2
        assert s["attributed_success_count"] == 1


class TestNeverAppliedDetection:
    """Methodologies retrieved but never applied should be flagged."""

    async def test_never_applied(self, repository):
        m1 = await _insert_methodology(repository, "Unused pattern")
        m2 = await _insert_methodology(repository, "Used pattern")

        task_id = await _ensure_task(repository, "never-applied")

        # m1: only retrieved, never applied
        await _log_usage(repository, task_id, m1.id, "retrieved_presented")
        await _log_usage(repository, task_id, m1.id, "retrieved_presented")

        # m2: retrieved AND applied
        await _log_usage(repository, task_id, m2.id, "retrieved_presented")
        await _log_usage(repository, task_id, m2.id, "used_in_outcome", success=True)

        stats = await repository.get_methodology_usage_stats()

        # m1 should be "never applied"
        m1_stats = stats[m1.id]
        assert m1_stats["retrieved_count"] == 2
        assert m1_stats["used_count"] == 0

        # m2 should be applied
        m2_stats = stats[m2.id]
        assert m2_stats["retrieved_count"] == 1
        assert m2_stats["used_count"] == 1


class TestJsonOutputShape:
    """Validate the JSON output structure from the proof data."""

    async def test_json_shape(self, repository):
        m1 = await _insert_methodology(repository, "JSON test pattern")

        task_id = await _ensure_task(repository, "json-shape")

        await _log_usage(
            repository, task_id, m1.id, "retrieved_presented",
            relevance_score=0.8,
        )
        await _log_usage(
            repository, task_id, m1.id, "used_in_outcome",
            success=True, quality_score=0.85,
        )
        await _log_usage(
            repository, task_id, m1.id, "outcome_attributed",
            success=True, quality_score=0.85,
        )

        stats = await repository.get_methodology_usage_stats()
        methods = await repository.list_methodologies(limit=5000, include_dead=True)
        method_map = {m.id: m for m in methods}

        # Build the proof data the same way the CLI does
        total_retrieved = 0
        total_applied = 0
        total_success = 0
        total_failure = 0
        never_applied = []
        per_methodology = []

        for meth_id, s in stats.items():
            retrieved = int(s.get("retrieved_count", 0))
            applied = int(s.get("used_count", 0))
            success = int(s.get("attributed_success_count", 0))
            failure = int(s.get("attributed_failure_count", 0))
            total_retrieved += retrieved
            total_applied += applied
            total_success += success
            total_failure += failure

            meth = method_map.get(meth_id)
            entry = {
                "methodology_id": meth_id,
                "title": meth.problem_description[:80] if meth else meth_id[:8],
                "lifecycle": meth.lifecycle_state if meth else "unknown",
                "retrieved": retrieved,
                "applied": applied,
                "success": success,
                "failure": failure,
                "applied_rate": applied / retrieved if retrieved > 0 else 0.0,
                "success_rate": success / applied if applied > 0 else 0.0,
                "avg_quality": s.get("avg_quality_score"),
                "avg_relevance": s.get("avg_relevance_score"),
            }
            per_methodology.append(entry)
            if retrieved > 0 and applied == 0:
                never_applied.append(entry)

        applied_rate = total_applied / total_retrieved if total_retrieved > 0 else 0.0
        success_rate = total_success / total_applied if total_applied > 0 else 0.0

        proof_data = {
            "funnel": {
                "total_retrieved": total_retrieved,
                "total_applied": total_applied,
                "total_success": total_success,
                "total_failure": total_failure,
                "applied_rate": round(applied_rate, 4),
                "success_rate": round(success_rate, 4),
                "overall_conversion": round(
                    total_success / total_retrieved if total_retrieved > 0 else 0.0, 4
                ),
            },
            "methodology_count": len(stats),
            "never_applied_count": len(never_applied),
            "per_methodology": per_methodology,
            "never_applied": never_applied,
        }

        # Validate JSON is serializable
        json_str = json.dumps(proof_data, default=str)
        parsed = json.loads(json_str)

        # Structural checks
        assert "funnel" in parsed
        funnel = parsed["funnel"]
        assert funnel["total_retrieved"] == 1
        assert funnel["total_applied"] == 1
        assert funnel["total_success"] == 1
        assert funnel["total_failure"] == 0
        assert funnel["applied_rate"] == 1.0
        assert funnel["success_rate"] == 1.0
        assert funnel["overall_conversion"] == 1.0

        assert parsed["methodology_count"] == 1
        assert parsed["never_applied_count"] == 0
        assert len(parsed["per_methodology"]) == 1

        entry = parsed["per_methodology"][0]
        assert entry["methodology_id"] == m1.id
        assert entry["lifecycle"] == "viable"
        assert entry["retrieved"] == 1
        assert entry["applied"] == 1
        assert entry["success"] == 1
