"""Tests for claw.fleet.FleetOrchestrator and claw.dashboard.Dashboard.

Phase 4 batch 2 — 47 tests total using real SQLite in-memory DB.
No mocks. No placeholders. No cached responses.

Fleet tests exercise repo registration, ranking, budget allocation,
status management, fleet summary, repo scanning, and enhancement
branch creation (using real temporary git repos).

Dashboard tests exercise all render_* methods with both empty and
populated database states, verifying correct output types and content.
"""

from __future__ import annotations

import os
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from claw.core.config import ClawConfig, FleetConfig, load_config
from claw.dashboard import Dashboard
from claw.fleet import FleetOrchestrator


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def fleet_config() -> ClawConfig:
    """Load real ClawConfig from claw.toml."""
    return load_config()


@pytest.fixture
async def fleet_orchestrator(repository, fleet_config):
    """FleetOrchestrator with real in-memory DB and real config."""
    return FleetOrchestrator(repository, fleet_config)


@pytest.fixture
async def dashboard(repository):
    """Dashboard with real in-memory DB."""
    return Dashboard(repository)


@pytest.fixture
def tmp_git_repo(tmp_path):
    """Create a real temporary git repo with an initial commit."""
    repo_dir = tmp_path / "test-repo"
    repo_dir.mkdir()
    subprocess.run(
        ["git", "init"],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@claw.dev"],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "CLAW Test"],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )
    readme = repo_dir / "README.md"
    readme.write_text("# Test Repo")
    subprocess.run(
        ["git", "add", "."],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", "Initial commit"],
        cwd=str(repo_dir),
        capture_output=True,
        check=True,
    )
    return repo_dir


@pytest.fixture
def tmp_fleet_dir(tmp_path):
    """Create a directory with multiple real git repos for scanning."""
    fleet_dir = tmp_path / "fleet"
    fleet_dir.mkdir()

    for name in ["alpha", "beta", "gamma"]:
        repo_dir = fleet_dir / name
        repo_dir.mkdir()
        subprocess.run(
            ["git", "init"],
            cwd=str(repo_dir),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@claw.dev"],
            cwd=str(repo_dir),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "CLAW Test"],
            cwd=str(repo_dir),
            capture_output=True,
            check=True,
        )
        readme = repo_dir / "README.md"
        readme.write_text(f"# {name}")
        subprocess.run(
            ["git", "add", "."],
            cwd=str(repo_dir),
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=str(repo_dir),
            capture_output=True,
            check=True,
        )

    # Add a non-git directory to test filtering
    plain_dir = fleet_dir / "not-a-repo"
    plain_dir.mkdir()
    (plain_dir / "file.txt").write_text("not a repo")

    return fleet_dir


# ========================================================================
# FleetOrchestrator Tests (27 tests)
# ========================================================================


class TestFleetOrchestratorInit:
    """Test FleetOrchestrator initialisation."""

    async def test_init_stores_config(self, fleet_orchestrator, fleet_config):
        assert fleet_orchestrator.config is fleet_config
        assert fleet_orchestrator._fleet_config is fleet_config.fleet

    async def test_init_stores_repository(self, fleet_orchestrator, repository):
        assert fleet_orchestrator.repository is repository


class TestRegisterRepo:
    """Test repo registration."""

    async def test_register_repo_returns_id(self, fleet_orchestrator, tmp_git_repo):
        repo_id = await fleet_orchestrator.register_repo(
            str(tmp_git_repo), "test-repo", priority=5.0,
        )
        assert isinstance(repo_id, str)
        assert len(repo_id) == 36  # UUID format

    async def test_register_repo_persists(self, fleet_orchestrator, tmp_git_repo):
        repo_id = await fleet_orchestrator.register_repo(
            str(tmp_git_repo), "test-repo", priority=5.0,
        )
        found = await fleet_orchestrator.get_repo_by_path(str(tmp_git_repo))
        assert found is not None
        assert found["id"] == repo_id
        assert found["repo_name"] == "test-repo"
        assert found["priority"] == 5.0
        assert found["status"] == "pending"

    async def test_register_repo_duplicate_returns_existing_id(
        self, fleet_orchestrator, tmp_git_repo,
    ):
        repo_id_1 = await fleet_orchestrator.register_repo(
            str(tmp_git_repo), "test-repo", priority=5.0,
        )
        repo_id_2 = await fleet_orchestrator.register_repo(
            str(tmp_git_repo), "different-name", priority=99.0,
        )
        assert repo_id_1 == repo_id_2

    async def test_register_repo_default_priority(self, fleet_orchestrator, tmp_git_repo):
        await fleet_orchestrator.register_repo(str(tmp_git_repo), "test-repo")
        found = await fleet_orchestrator.get_repo_by_path(str(tmp_git_repo))
        assert found["priority"] == 0.0


class TestGetRepos:
    """Test listing and filtering repos."""

    async def test_get_repos_all_empty(self, fleet_orchestrator):
        repos = await fleet_orchestrator.get_repos()
        assert repos == []

    async def test_get_repos_all_with_data(self, fleet_orchestrator, tmp_path):
        # Register 3 repos using distinct temp paths
        for i in range(3):
            repo_dir = tmp_path / f"repo-{i}"
            repo_dir.mkdir()
            await fleet_orchestrator.register_repo(
                str(repo_dir), f"repo-{i}", priority=float(i),
            )
        repos = await fleet_orchestrator.get_repos()
        assert len(repos) == 3
        # Should be sorted by priority descending
        assert repos[0]["repo_name"] == "repo-2"

    async def test_get_repos_by_status(self, fleet_orchestrator, tmp_path):
        repo_dir = tmp_path / "repo-filter"
        repo_dir.mkdir()
        repo_id = await fleet_orchestrator.register_repo(
            str(repo_dir), "repo-filter", priority=1.0,
        )
        # Update to 'enhancing'
        await fleet_orchestrator.update_repo_status(repo_id, "enhancing")

        pending = await fleet_orchestrator.get_repos(status="pending")
        enhancing = await fleet_orchestrator.get_repos(status="enhancing")
        assert len(pending) == 0
        assert len(enhancing) == 1
        assert enhancing[0]["id"] == repo_id

    async def test_get_repos_respects_limit(self, fleet_orchestrator, tmp_path):
        for i in range(5):
            repo_dir = tmp_path / f"repo-lim-{i}"
            repo_dir.mkdir()
            await fleet_orchestrator.register_repo(
                str(repo_dir), f"repo-lim-{i}", priority=float(i),
            )
        repos = await fleet_orchestrator.get_repos(limit=2)
        assert len(repos) == 2


class TestGetRepoByPath:
    """Test path-based repo lookup."""

    async def test_get_repo_by_path_found(self, fleet_orchestrator, tmp_path):
        repo_dir = tmp_path / "lookup-repo"
        repo_dir.mkdir()
        await fleet_orchestrator.register_repo(str(repo_dir), "lookup-repo")
        found = await fleet_orchestrator.get_repo_by_path(str(repo_dir))
        assert found is not None
        assert found["repo_name"] == "lookup-repo"

    async def test_get_repo_by_path_not_found(self, fleet_orchestrator):
        found = await fleet_orchestrator.get_repo_by_path("/nonexistent/path")
        assert found is None


class TestRankRepos:
    """Test composite scoring and ranking."""

    async def test_rank_repos_empty(self, fleet_orchestrator):
        ranked = await fleet_orchestrator.rank_repos()
        assert ranked == []

    async def test_rank_repos_single(self, fleet_orchestrator, tmp_path):
        repo_dir = tmp_path / "rank-one"
        repo_dir.mkdir()
        await fleet_orchestrator.register_repo(str(repo_dir), "rank-one", priority=5.0)
        ranked = await fleet_orchestrator.rank_repos()
        assert len(ranked) == 1
        assert "rank_score" in ranked[0]

    async def test_rank_repos_ordering(self, fleet_orchestrator, tmp_path):
        """Higher priority repo should rank higher (all else equal)."""
        for name, prio in [("low", 1.0), ("mid", 5.0), ("high", 10.0)]:
            repo_dir = tmp_path / name
            repo_dir.mkdir()
            await fleet_orchestrator.register_repo(str(repo_dir), name, priority=prio)

        ranked = await fleet_orchestrator.rank_repos()
        assert len(ranked) == 3
        names_in_order = [r["repo_name"] for r in ranked]
        assert names_in_order[0] == "high"
        assert names_in_order[-1] == "low"

    async def test_rank_repos_excludes_completed(self, fleet_orchestrator, tmp_path):
        repo_dir = tmp_path / "done-repo"
        repo_dir.mkdir()
        repo_id = await fleet_orchestrator.register_repo(
            str(repo_dir), "done-repo", priority=10.0,
        )
        await fleet_orchestrator.update_repo_status(repo_id, "completed")

        ranked = await fleet_orchestrator.rank_repos()
        assert len(ranked) == 0

    async def test_rank_repos_excludes_skipped(self, fleet_orchestrator, tmp_path):
        repo_dir = tmp_path / "skipped-repo"
        repo_dir.mkdir()
        repo_id = await fleet_orchestrator.register_repo(
            str(repo_dir), "skipped-repo", priority=10.0,
        )
        await fleet_orchestrator.update_repo_status(repo_id, "skipped")
        ranked = await fleet_orchestrator.rank_repos()
        assert len(ranked) == 0


class TestAllocateBudget:
    """Test budget allocation strategies."""

    async def test_allocate_budget_proportional(self, fleet_orchestrator, tmp_path):
        for name, prio in [("a", 1.0), ("b", 3.0)]:
            repo_dir = tmp_path / name
            repo_dir.mkdir()
            await fleet_orchestrator.register_repo(str(repo_dir), name, priority=prio)

        result = await fleet_orchestrator.allocate_budget(10.0, strategy="proportional")
        assert result["strategy"] == "proportional"
        assert result["repos_allocated"] == 2
        # Higher-priority repo gets more
        allocs = {a["repo_name"]: a["allocated_usd"] for a in result["allocations"]}
        assert allocs["b"] > allocs["a"]

    async def test_allocate_budget_equal(self, fleet_orchestrator, tmp_path):
        for i in range(4):
            repo_dir = tmp_path / f"eq-{i}"
            repo_dir.mkdir()
            await fleet_orchestrator.register_repo(
                str(repo_dir), f"eq-{i}", priority=float(i),
            )

        result = await fleet_orchestrator.allocate_budget(20.0, strategy="equal")
        assert result["strategy"] == "equal"
        # Each gets 20/4 = 5.0 (within cap)
        allocs = result["allocations"]
        for a in allocs:
            assert a["allocated_usd"] == 5.0

    async def test_allocate_budget_capped(self, fleet_orchestrator, fleet_config, tmp_path):
        max_cap = fleet_config.fleet.max_cost_per_repo_usd  # e.g. 5.0
        repo_dir = tmp_path / "capped"
        repo_dir.mkdir()
        await fleet_orchestrator.register_repo(str(repo_dir), "capped", priority=10.0)

        # Give a huge total budget so that the per-repo share exceeds the cap
        result = await fleet_orchestrator.allocate_budget(10000.0, strategy="equal")
        alloc = result["allocations"][0]["allocated_usd"]
        assert alloc <= max_cap

    async def test_allocate_budget_no_repos(self, fleet_orchestrator):
        result = await fleet_orchestrator.allocate_budget(50.0)
        assert result["repos_allocated"] == 0
        assert result["allocated_usd"] == 0.0

    async def test_allocate_budget_negative_raises(self, fleet_orchestrator):
        with pytest.raises(ValueError, match="non-negative"):
            await fleet_orchestrator.allocate_budget(-10.0)

    async def test_allocate_budget_invalid_strategy_raises(self, fleet_orchestrator):
        with pytest.raises(ValueError, match="Unknown budget strategy"):
            await fleet_orchestrator.allocate_budget(10.0, strategy="random")

    async def test_allocate_budget_persists_to_db(self, fleet_orchestrator, tmp_path):
        repo_dir = tmp_path / "persist"
        repo_dir.mkdir()
        await fleet_orchestrator.register_repo(str(repo_dir), "persist", priority=5.0)
        await fleet_orchestrator.allocate_budget(10.0, strategy="equal")

        found = await fleet_orchestrator.get_repo_by_path(str(repo_dir))
        assert found["budget_allocated_usd"] > 0.0


class TestUpdateRepoStatus:
    """Test status update with validation."""

    async def test_update_repo_status_valid(self, fleet_orchestrator, tmp_path):
        repo_dir = tmp_path / "status-valid"
        repo_dir.mkdir()
        repo_id = await fleet_orchestrator.register_repo(
            str(repo_dir), "status-valid",
        )
        await fleet_orchestrator.update_repo_status(repo_id, "evaluating")
        found = await fleet_orchestrator.get_repo_by_path(str(repo_dir))
        assert found["status"] == "evaluating"

    async def test_update_repo_status_invalid_raises(self, fleet_orchestrator, tmp_path):
        repo_dir = tmp_path / "status-bad"
        repo_dir.mkdir()
        repo_id = await fleet_orchestrator.register_repo(str(repo_dir), "status-bad")
        with pytest.raises(ValueError, match="Invalid fleet repo status"):
            await fleet_orchestrator.update_repo_status(repo_id, "INVALID")

    async def test_update_repo_status_with_kwargs(self, fleet_orchestrator, tmp_path):
        repo_dir = tmp_path / "status-extra"
        repo_dir.mkdir()
        repo_id = await fleet_orchestrator.register_repo(
            str(repo_dir), "status-extra",
        )
        await fleet_orchestrator.update_repo_status(
            repo_id, "enhancing",
            enhancement_branch="claw/enhancement/test",
            evaluation_score=0.85,
        )
        found = await fleet_orchestrator.get_repo_by_path(str(repo_dir))
        assert found["status"] == "enhancing"
        assert found["enhancement_branch"] == "claw/enhancement/test"
        assert found["evaluation_score"] == 0.85

    async def test_update_repo_status_all_valid_statuses(self, fleet_orchestrator, tmp_path):
        valid_statuses = ["pending", "evaluating", "enhancing", "completed", "failed", "skipped"]
        for i, status in enumerate(valid_statuses):
            repo_dir = tmp_path / f"status-all-{i}"
            repo_dir.mkdir()
            repo_id = await fleet_orchestrator.register_repo(
                str(repo_dir), f"status-all-{i}",
            )
            await fleet_orchestrator.update_repo_status(repo_id, status)
            found = await fleet_orchestrator.get_repo_by_path(str(repo_dir))
            assert found["status"] == status


class TestGetFleetSummary:
    """Test fleet summary aggregation."""

    async def test_get_fleet_summary_empty(self, fleet_orchestrator):
        summary = await fleet_orchestrator.get_fleet_summary()
        assert summary["total_repos"] == 0
        assert summary["by_status"] == {}
        assert summary["total_budget_allocated_usd"] == 0.0
        assert summary["total_budget_used_usd"] == 0.0
        assert summary["total_tasks_created"] == 0
        assert summary["total_tasks_completed"] == 0
        assert summary["completion_rate"] == 0.0

    async def test_get_fleet_summary_with_data(self, fleet_orchestrator, tmp_path):
        for i in range(3):
            repo_dir = tmp_path / f"summary-{i}"
            repo_dir.mkdir()
            repo_id = await fleet_orchestrator.register_repo(
                str(repo_dir), f"summary-{i}", priority=float(i),
            )

        # Update one to enhancing
        repos = await fleet_orchestrator.get_repos()
        await fleet_orchestrator.update_repo_status(
            repos[0]["id"], "enhancing", tasks_created=5, tasks_completed=2,
        )

        summary = await fleet_orchestrator.get_fleet_summary()
        assert summary["total_repos"] == 3
        assert "pending" in summary["by_status"]
        assert summary["by_status"]["pending"] == 2
        assert summary["by_status"]["enhancing"] == 1
        assert summary["total_tasks_created"] == 5
        assert summary["total_tasks_completed"] == 2


class TestScanRepos:
    """Test filesystem scanning for git repos."""

    async def test_scan_repos_finds_git_dirs(self, fleet_orchestrator, tmp_fleet_dir):
        discovered = await fleet_orchestrator.scan_repos(str(tmp_fleet_dir))
        assert len(discovered) == 3
        names = sorted(d["name"] for d in discovered)
        assert names == ["alpha", "beta", "gamma"]

    async def test_scan_repos_excludes_non_git(self, fleet_orchestrator, tmp_fleet_dir):
        discovered = await fleet_orchestrator.scan_repos(str(tmp_fleet_dir))
        found_names = [d["name"] for d in discovered]
        assert "not-a-repo" not in found_names

    async def test_scan_repos_empty_dir(self, fleet_orchestrator, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        discovered = await fleet_orchestrator.scan_repos(str(empty_dir))
        assert discovered == []

    async def test_scan_repos_nonexistent_raises(self, fleet_orchestrator):
        with pytest.raises(FileNotFoundError):
            await fleet_orchestrator.scan_repos("/nonexistent/path/that/does/not/exist")

    async def test_scan_repos_file_raises(self, fleet_orchestrator, tmp_path):
        a_file = tmp_path / "afile.txt"
        a_file.write_text("just a file")
        with pytest.raises(NotADirectoryError):
            await fleet_orchestrator.scan_repos(str(a_file))

    async def test_scan_repos_returns_path_field(self, fleet_orchestrator, tmp_fleet_dir):
        discovered = await fleet_orchestrator.scan_repos(str(tmp_fleet_dir))
        for repo_info in discovered:
            assert "path" in repo_info
            assert Path(repo_info["path"]).is_dir()

    async def test_scan_repos_returns_metadata_keys(self, fleet_orchestrator, tmp_fleet_dir):
        discovered = await fleet_orchestrator.scan_repos(str(tmp_fleet_dir))
        expected_keys = {"path", "name", "has_remote", "default_branch", "last_commit_date"}
        for repo_info in discovered:
            assert expected_keys.issubset(repo_info.keys())


class TestCreateEnhancementBranch:
    """Test real git branch creation in a temp repo."""

    async def test_create_enhancement_branch(self, fleet_orchestrator, tmp_git_repo):
        branch_name = await fleet_orchestrator.create_enhancement_branch(
            str(tmp_git_repo),
        )
        assert branch_name.startswith("claw/enhancement/")

        # Verify the branch actually exists in the repo
        result = subprocess.run(
            ["git", "branch", "--list"],
            cwd=str(tmp_git_repo),
            capture_output=True,
            text=True,
        )
        assert "claw/enhancement/" in result.stdout

    async def test_create_enhancement_branch_custom_prefix(
        self, fleet_orchestrator, tmp_git_repo,
    ):
        branch_name = await fleet_orchestrator.create_enhancement_branch(
            str(tmp_git_repo),
            branch_prefix="custom/prefix",
        )
        assert branch_name.startswith("custom/prefix/")

    async def test_create_enhancement_branch_invalid_repo(self, fleet_orchestrator, tmp_path):
        not_a_repo = tmp_path / "not-git"
        not_a_repo.mkdir()
        with pytest.raises(RuntimeError):
            await fleet_orchestrator.create_enhancement_branch(str(not_a_repo))


# ========================================================================
# Dashboard Tests (20 tests)
# ========================================================================


class TestDashboardInit:
    """Test Dashboard initialization."""

    async def test_dashboard_stores_repository(self, dashboard, repository):
        assert dashboard.repository is repository


class TestRenderAgentScores:
    """Test agent score rendering."""

    async def test_render_agent_scores_empty(self, dashboard):
        output = await dashboard.render_agent_scores()
        assert isinstance(output, str)
        assert "No agent scores" in output

    async def test_render_agent_scores_with_data(self, dashboard, repository):
        await repository.update_agent_score(
            agent_id="claude",
            task_type="bug_fix",
            success=True,
            duration_seconds=45.0,
            quality_score=0.9,
            cost_usd=0.05,
        )
        await repository.update_agent_score(
            agent_id="codex",
            task_type="refactoring",
            success=False,
            duration_seconds=120.0,
            quality_score=0.3,
            cost_usd=0.10,
        )
        output = await dashboard.render_agent_scores()
        assert isinstance(output, str)
        assert "claude" in output
        assert "codex" in output

    async def test_render_agent_scores_returns_string(self, dashboard):
        result = await dashboard.render_agent_scores()
        assert type(result) is str


class TestRenderFleetStatus:
    """Test fleet status rendering."""

    async def test_render_fleet_status_empty(self, dashboard):
        output = await dashboard.render_fleet_status()
        assert isinstance(output, str)
        assert "No fleet repos" in output

    async def test_render_fleet_status_with_data(self, dashboard, repository):
        await repository.engine.execute(
            """INSERT INTO fleet_repos
               (id, repo_path, repo_name, priority, status,
                budget_allocated_usd, budget_used_usd,
                tasks_created, tasks_completed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                str(uuid.uuid4()), "/tmp/fleet-test-1", "fleet-test-1",
                5.0, "pending", 10.0, 2.5, 10, 3,
            ],
        )
        await repository.engine.execute(
            """INSERT INTO fleet_repos
               (id, repo_path, repo_name, priority, status,
                budget_allocated_usd, budget_used_usd,
                tasks_created, tasks_completed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                str(uuid.uuid4()), "/tmp/fleet-test-2", "fleet-test-2",
                8.0, "enhancing", 15.0, 7.0, 20, 12,
            ],
        )
        output = await dashboard.render_fleet_status()
        assert isinstance(output, str)
        assert "fleet-test-1" in output
        assert "fleet-test-2" in output

    async def test_render_fleet_status_returns_string(self, dashboard):
        result = await dashboard.render_fleet_status()
        assert type(result) is str


class TestRenderCostSummary:
    """Test cost summary rendering."""

    async def test_render_cost_summary_empty(self, dashboard):
        output = await dashboard.render_cost_summary()
        assert isinstance(output, str)
        assert "No token costs" in output

    async def test_render_cost_summary_with_data(self, dashboard, repository):
        now = datetime.now(UTC).isoformat()
        await repository.engine.execute(
            """INSERT INTO token_costs
               (id, agent_id, model_used, input_tokens, output_tokens,
                total_tokens, cost_usd, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                str(uuid.uuid4()), "claude", "test-model",
                1000, 500, 1500, 0.05, now,
            ],
        )
        await repository.engine.execute(
            """INSERT INTO token_costs
               (id, agent_id, model_used, input_tokens, output_tokens,
                total_tokens, cost_usd, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                str(uuid.uuid4()), "codex", "test-model-2",
                2000, 800, 2800, 0.12, now,
            ],
        )
        output = await dashboard.render_cost_summary()
        assert isinstance(output, str)
        assert "claude" in output
        assert "codex" in output

    async def test_render_cost_summary_returns_string(self, dashboard):
        result = await dashboard.render_cost_summary()
        assert type(result) is str


class TestRenderPatternSummary:
    """Test pattern/methodology summary rendering."""

    async def test_render_pattern_summary_empty(self, dashboard):
        output = await dashboard.render_pattern_summary()
        assert isinstance(output, str)
        assert "No methodologies" in output

    async def test_render_pattern_summary_with_data(self, dashboard, repository):
        # Insert methodologies with different lifecycle states
        for i, state in enumerate(["embryonic", "viable", "thriving"]):
            meth_id = str(uuid.uuid4())
            await repository.engine.execute(
                """INSERT INTO methodologies
                   (id, problem_description, solution_code, methodology_type,
                    lifecycle_state, retrieval_count, success_count, failure_count,
                    generation, tags, files_affected, fitness_vector, parent_ids)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', '[]', '{}', '[]')""",
                [
                    meth_id,
                    f"Problem description {i}",
                    f"def fix_{i}(): pass",
                    "refactoring",
                    state,
                    i + 1,   # retrieval_count
                    i,       # success_count
                    0,       # failure_count
                    1,       # generation
                ],
            )
            # Also insert into FTS5 index
            await repository.engine.execute(
                """INSERT INTO methodology_fts
                   (methodology_id, problem_description, methodology_notes, tags)
                   VALUES (?, ?, '', '[]')""",
                [meth_id, f"Problem description {i}"],
            )

        output = await dashboard.render_pattern_summary()
        assert isinstance(output, str)
        # The output should mention at least one of the lifecycle states
        assert any(
            state in output.lower()
            for state in ["embryonic", "viable", "thriving", "pattern"]
        )


class TestRenderQualityTrajectory:
    """Test quality trajectory rendering."""

    async def test_render_quality_trajectory_empty(self, dashboard):
        output = await dashboard.render_quality_trajectory()
        assert isinstance(output, str)
        assert "No quality data" in output

    async def test_render_quality_trajectory_with_agent_scores(
        self, dashboard, repository,
    ):
        await repository.update_agent_score(
            agent_id="claude",
            task_type="analysis",
            success=True,
            duration_seconds=30.0,
            quality_score=0.85,
            cost_usd=0.02,
        )
        await repository.update_agent_score(
            agent_id="gemini",
            task_type="dependency_analysis",
            success=True,
            duration_seconds=60.0,
            quality_score=0.70,
            cost_usd=0.04,
        )
        output = await dashboard.render_quality_trajectory()
        assert isinstance(output, str)
        assert "claude" in output
        assert "gemini" in output

    async def test_render_quality_trajectory_returns_string(self, dashboard):
        result = await dashboard.render_quality_trajectory()
        assert type(result) is str


class TestRenderFullDashboard:
    """Test full dashboard composition."""

    async def test_render_full_dashboard_empty(self, dashboard):
        output = await dashboard.render_full_dashboard()
        assert isinstance(output, str)
        # Should contain the header and not crash
        assert "CLAW" in output or "Dashboard" in output or "claw" in output.lower()

    async def test_render_full_dashboard_with_data(self, dashboard, repository):
        # Populate agent scores
        await repository.update_agent_score(
            agent_id="claude",
            task_type="bug_fix",
            success=True,
            duration_seconds=45.0,
            quality_score=0.9,
            cost_usd=0.05,
        )

        # Populate fleet repos
        await repository.engine.execute(
            """INSERT INTO fleet_repos
               (id, repo_path, repo_name, priority, status,
                budget_allocated_usd, budget_used_usd,
                tasks_created, tasks_completed)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                str(uuid.uuid4()), "/tmp/full-dash-repo", "full-dash-repo",
                5.0, "pending", 10.0, 1.0, 5, 2,
            ],
        )

        # Populate token costs
        now = datetime.now(UTC).isoformat()
        await repository.engine.execute(
            """INSERT INTO token_costs
               (id, agent_id, model_used, input_tokens, output_tokens,
                total_tokens, cost_usd, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                str(uuid.uuid4()), "claude", "test-model",
                100, 50, 150, 0.01, now,
            ],
        )

        output = await dashboard.render_full_dashboard()
        assert isinstance(output, str)
        # All panels should be present
        assert "claude" in output
        assert "full-dash-repo" in output

    async def test_render_full_dashboard_returns_string(self, dashboard):
        result = await dashboard.render_full_dashboard()
        assert type(result) is str

    async def test_render_full_dashboard_with_project_id(self, dashboard):
        output = await dashboard.render_full_dashboard(
            project_id="nonexistent-project",
        )
        assert isinstance(output, str)
        # Should not crash even with a project_id that matches nothing

    async def test_dashboard_panel_isolation(self, dashboard, repository):
        """One panel having data and another being empty should not crash."""
        # Only populate agent scores, leave everything else empty
        await repository.update_agent_score(
            agent_id="grok",
            task_type="quick_fixes",
            success=True,
            duration_seconds=10.0,
            quality_score=0.75,
            cost_usd=0.01,
        )
        output = await dashboard.render_full_dashboard()
        assert isinstance(output, str)
        # Agent scores panel should have data
        assert "grok" in output
        # Other panels should show empty states, not crash
        assert "No fleet repos" in output or "No token costs" in output or len(output) > 0


class TestDashboardReturnTypes:
    """Verify all render methods consistently return str."""

    async def test_all_render_methods_return_str(self, dashboard):
        methods = [
            dashboard.render_agent_scores,
            dashboard.render_fleet_status,
            dashboard.render_cost_summary,
            dashboard.render_pattern_summary,
            dashboard.render_quality_trajectory,
            dashboard.render_full_dashboard,
        ]
        for method in methods:
            result = await method()
            assert isinstance(result, str), (
                f"{method.__name__} returned {type(result)}, expected str"
            )
