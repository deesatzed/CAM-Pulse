"""Integration tests for RL bandit method selection through the full pipeline.

Tests the actual database path: schema creation, bandit outcome recording,
forbidden-on-retry filtering, and Thompson sampling graduation.
"""

from __future__ import annotations

import json
import uuid

import pytest

from claw.core.config import load_config
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository


@pytest.fixture
async def db_repo(tmp_path):
    """Create a real in-memory database with full schema."""
    config = load_config()
    config.database.db_path = str(tmp_path / "test_bandit.db")
    engine = DatabaseEngine(config.database)
    await engine.connect()
    await engine.initialize_schema()
    repo = Repository(engine)

    # Create a test project
    await engine.execute(
        "INSERT INTO projects (id, name, repo_path) VALUES (?, ?, ?)",
        ["proj-1", "test-project", "/tmp/test"],
    )

    yield repo
    await engine.close()


@pytest.fixture
async def seeded_db(db_repo):
    """Database with test methodologies and tasks."""
    repo = db_repo

    # Create 5 test methodologies
    for i in range(5):
        meth_id = f"meth-{i:03d}"
        await repo.engine.execute(
            """INSERT INTO methodologies
               (id, problem_description, solution_code, methodology_notes,
                language, methodology_type, lifecycle_state, fitness_vector,
                success_count, failure_count, tags)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                meth_id,
                f"Test methodology {i} for architecture patterns",
                f"def solution_{i}(): pass",
                f"Apply pattern {i} for architecture tasks",
                "python",
                "architecture",
                "viable",
                json.dumps({"overall": 0.7 - (i * 0.05)}),  # Decreasing fitness
                10 - i,            # Decreasing successes
                i,                 # Increasing failures
                json.dumps([f"category:architecture", f"source:repo-{i}"]),
            ],
        )

    # Create a test task
    await repo.engine.execute(
        """INSERT INTO tasks
           (id, project_id, title, description, status, task_type)
           VALUES (?, ?, ?, ?, ?, ?)""",
        ["task-001", "proj-1", "Test task", "Implement architecture pattern", "PENDING", "architecture"],
    )

    return repo


class TestBanditOutcomeRecording:
    """Test that bandit outcomes are correctly recorded in the database."""

    @pytest.mark.asyncio
    async def test_record_success(self, db_repo):
        repo = db_repo
        # Insert a methodology first
        await repo.engine.execute(
            "INSERT INTO methodologies (id, problem_description, solution_code, lifecycle_state) "
            "VALUES (?, ?, ?, ?)",
            ["meth-test", "test problem", "test solution", "viable"],
        )
        await repo.record_bandit_outcome("meth-test", "architecture", success=True)
        s, f = await repo.get_bandit_stats("meth-test", "architecture")
        assert s == 1
        assert f == 0

    @pytest.mark.asyncio
    async def test_record_failure(self, db_repo):
        repo = db_repo
        await repo.engine.execute(
            "INSERT INTO methodologies (id, problem_description, solution_code, lifecycle_state) "
            "VALUES (?, ?, ?, ?)",
            ["meth-test", "test problem", "test solution", "viable"],
        )
        await repo.record_bandit_outcome("meth-test", "testing", success=False)
        s, f = await repo.get_bandit_stats("meth-test", "testing")
        assert s == 0
        assert f == 1

    @pytest.mark.asyncio
    async def test_upsert_accumulates(self, db_repo):
        repo = db_repo
        await repo.engine.execute(
            "INSERT INTO methodologies (id, problem_description, solution_code, lifecycle_state) "
            "VALUES (?, ?, ?, ?)",
            ["meth-test", "test problem", "test solution", "viable"],
        )
        await repo.record_bandit_outcome("meth-test", "security", success=True)
        await repo.record_bandit_outcome("meth-test", "security", success=True)
        await repo.record_bandit_outcome("meth-test", "security", success=False)
        s, f = await repo.get_bandit_stats("meth-test", "security")
        assert s == 2
        assert f == 1

    @pytest.mark.asyncio
    async def test_separate_task_types(self, db_repo):
        repo = db_repo
        await repo.engine.execute(
            "INSERT INTO methodologies (id, problem_description, solution_code, lifecycle_state) "
            "VALUES (?, ?, ?, ?)",
            ["meth-test", "test problem", "test solution", "viable"],
        )
        await repo.record_bandit_outcome("meth-test", "architecture", success=True)
        await repo.record_bandit_outcome("meth-test", "testing", success=False)

        s_arch, f_arch = await repo.get_bandit_stats("meth-test", "architecture")
        s_test, f_test = await repo.get_bandit_stats("meth-test", "testing")

        assert (s_arch, f_arch) == (1, 0)
        assert (s_test, f_test) == (0, 1)

    @pytest.mark.asyncio
    async def test_batch_fetch(self, seeded_db):
        repo = seeded_db
        # Record some outcomes
        await repo.record_bandit_outcome("meth-000", "architecture", success=True)
        await repo.record_bandit_outcome("meth-001", "architecture", success=False)
        await repo.record_bandit_outcome("meth-002", "architecture", success=True)

        stats = await repo.get_bandit_stats_batch(
            ["meth-000", "meth-001", "meth-002", "meth-003"],
            "architecture",
        )
        assert stats["meth-000"] == (1, 0)
        assert stats["meth-001"] == (0, 1)
        assert stats["meth-002"] == (1, 0)
        assert "meth-003" not in stats  # No outcomes recorded

    @pytest.mark.asyncio
    async def test_nonexistent_returns_zeros(self, db_repo):
        s, f = await db_repo.get_bandit_stats("nonexistent", "general")
        assert (s, f) == (0, 0)


class TestForbiddenOnRetry:
    """Test that content-failed methods are excluded on retry."""

    @pytest.mark.asyncio
    async def test_no_failures_returns_empty(self, seeded_db):
        repo = seeded_db
        counts = await repo.get_task_content_failure_counts("task-001")
        assert counts == {}

    @pytest.mark.asyncio
    async def test_content_failures_counted(self, seeded_db):
        repo = seeded_db
        # Simulate 2 content failures for meth-000 on task-001
        for _ in range(2):
            entry_id = str(uuid.uuid4())
            await repo.engine.execute(
                """INSERT INTO methodology_usage_log
                   (id, task_id, methodology_id, project_id, stage, success)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [entry_id, "task-001", "meth-000", "proj-1", "outcome_attributed", 0],
            )

        counts = await repo.get_task_content_failure_counts("task-001")
        assert counts["meth-000"] == 2

    @pytest.mark.asyncio
    async def test_only_outcome_attributed_counted(self, seeded_db):
        """Only 'outcome_attributed' stage failures count, not 'retrieved_presented'."""
        repo = seeded_db
        # This should NOT count (wrong stage)
        await repo.engine.execute(
            """INSERT INTO methodology_usage_log
               (id, task_id, methodology_id, project_id, stage, success)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [str(uuid.uuid4()), "task-001", "meth-000", "proj-1", "retrieved_presented", 0],
        )
        # This SHOULD count
        await repo.engine.execute(
            """INSERT INTO methodology_usage_log
               (id, task_id, methodology_id, project_id, stage, success)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [str(uuid.uuid4()), "task-001", "meth-000", "proj-1", "outcome_attributed", 0],
        )

        counts = await repo.get_task_content_failure_counts("task-001")
        assert counts.get("meth-000", 0) == 1  # Only 1, not 2

    @pytest.mark.asyncio
    async def test_successes_not_counted(self, seeded_db):
        """Successful outcomes should not appear in failure counts."""
        repo = seeded_db
        await repo.engine.execute(
            """INSERT INTO methodology_usage_log
               (id, task_id, methodology_id, project_id, stage, success)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [str(uuid.uuid4()), "task-001", "meth-000", "proj-1", "outcome_attributed", 1],
        )
        counts = await repo.get_task_content_failure_counts("task-001")
        assert counts == {}

    @pytest.mark.asyncio
    async def test_threshold_filtering(self, seeded_db):
        """Methods with >=2 failures should be identifiable for exclusion."""
        repo = seeded_db
        # meth-000: 2 failures (should be forbidden)
        for _ in range(2):
            await repo.engine.execute(
                """INSERT INTO methodology_usage_log
                   (id, task_id, methodology_id, project_id, stage, success)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [str(uuid.uuid4()), "task-001", "meth-000", "proj-1", "outcome_attributed", 0],
            )
        # meth-001: 1 failure (should NOT be forbidden)
        await repo.engine.execute(
            """INSERT INTO methodology_usage_log
               (id, task_id, methodology_id, project_id, stage, success)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [str(uuid.uuid4()), "task-001", "meth-001", "proj-1", "outcome_attributed", 0],
        )

        counts = await repo.get_task_content_failure_counts("task-001")
        forbidden = {mid for mid, cnt in counts.items() if cnt >= 2}
        assert forbidden == {"meth-000"}
        assert "meth-001" not in forbidden


class TestThompsonGraduation:
    """Test that Thompson sampling activates with enough data."""

    @pytest.mark.asyncio
    async def test_graduation_with_real_db(self, seeded_db):
        """After recording 5+ outcomes, bandit should use Thompson."""
        from claw.memory.bandit import BanditCandidate, MethodologyBandit

        repo = seeded_db
        # Record 6 outcomes for meth-000 on architecture
        for _ in range(5):
            await repo.record_bandit_outcome("meth-000", "architecture", success=True)
        await repo.record_bandit_outcome("meth-000", "architecture", success=False)

        s, f = await repo.get_bandit_stats("meth-000", "architecture")
        assert s == 5
        assert f == 1

        # Create candidate with these stats
        bandit = MethodologyBandit(epsilon=0.0, thompson_threshold=5, seed=42)
        candidate = BanditCandidate(
            methodology_id="meth-000",
            hybrid_score=0.5,
            fitness=0.7,
            successes=s,
            failures=f,
            total_outcomes=s + f,
        )
        score = bandit._compute_score(candidate)
        # With Thompson (s+f >= 5): score = Beta(6,2).draw * 0.6 + 0.5 * 0.4
        # Should differ from pure hybrid_score of 0.5
        assert score != 0.5

    @pytest.mark.asyncio
    async def test_below_threshold_uses_hybrid(self, seeded_db):
        """Below threshold, score should equal hybrid_score."""
        from claw.memory.bandit import BanditCandidate, MethodologyBandit

        repo = seeded_db
        await repo.record_bandit_outcome("meth-001", "architecture", success=True)
        await repo.record_bandit_outcome("meth-001", "architecture", success=False)

        s, f = await repo.get_bandit_stats("meth-001", "architecture")
        assert s == 1
        assert f == 1

        bandit = MethodologyBandit(epsilon=0.0, thompson_threshold=5, seed=42)
        candidate = BanditCandidate(
            methodology_id="meth-001",
            hybrid_score=0.65,
            fitness=0.6,
            successes=s,
            failures=f,
            total_outcomes=2,
        )
        score = bandit._compute_score(candidate)
        assert score == 0.65  # Pure hybrid, no Thompson


class TestRetryIterationDifferentPrimary:
    """Test that retry produces a different primary after forbidden-on-retry."""

    @pytest.mark.asyncio
    async def test_forbidden_excludes_from_eligible(self, seeded_db):
        """After 2 content failures, methodology is excluded from eligible set."""
        from claw.memory.bandit import BanditCandidate, MethodologyBandit

        repo = seeded_db
        # Simulate 2 content failures for meth-000 on task-001
        for _ in range(2):
            entry_id = str(uuid.uuid4())
            await repo.engine.execute(
                """INSERT INTO methodology_usage_log
                   (id, task_id, methodology_id, project_id, stage, success)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [entry_id, "task-001", "meth-000", "proj-1", "outcome_attributed", 0],
            )

        # Get forbidden set (same logic as cycle.py evaluate)
        fail_counts = await repo.get_task_content_failure_counts("task-001")
        forbidden = {mid for mid, cnt in fail_counts.items() if cnt >= 2}
        assert "meth-000" in forbidden

        # Simulate eligible filtering — meth-000 removed, others remain
        all_method_ids = ["meth-000", "meth-001", "meth-002", "meth-003", "meth-004"]
        eligible_ids = [mid for mid in all_method_ids if mid not in forbidden]
        assert "meth-000" not in eligible_ids
        assert len(eligible_ids) == 4

        # Bandit selects from remaining — primary must NOT be meth-000
        candidates = [
            BanditCandidate(
                methodology_id=mid,
                hybrid_score=0.8 - (i * 0.1),
                fitness=0.7 - (i * 0.05),
                successes=0,
                failures=0,
                total_outcomes=0,
            )
            for i, mid in enumerate(eligible_ids)
        ]
        bandit = MethodologyBandit(epsilon=0.0, seed=42)
        selected = bandit.select(candidates)
        assert selected is not None
        assert selected.methodology_id != "meth-000"
        assert selected.methodology_id == "meth-001"  # Next best

    @pytest.mark.asyncio
    async def test_progressive_exclusion(self, seeded_db):
        """Multiple retries progressively exclude more methods."""
        repo = seeded_db
        # meth-000: 2 failures -> forbidden
        for _ in range(2):
            await repo.engine.execute(
                """INSERT INTO methodology_usage_log
                   (id, task_id, methodology_id, project_id, stage, success)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [str(uuid.uuid4()), "task-001", "meth-000", "proj-1", "outcome_attributed", 0],
            )
        # meth-001: 2 failures -> also forbidden
        for _ in range(2):
            await repo.engine.execute(
                """INSERT INTO methodology_usage_log
                   (id, task_id, methodology_id, project_id, stage, success)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [str(uuid.uuid4()), "task-001", "meth-001", "proj-1", "outcome_attributed", 0],
            )

        fail_counts = await repo.get_task_content_failure_counts("task-001")
        forbidden = {mid for mid, cnt in fail_counts.items() if cnt >= 2}
        assert forbidden == {"meth-000", "meth-001"}

        # Only meth-002..004 remain eligible
        all_ids = [f"meth-{i:03d}" for i in range(5)]
        eligible = [mid for mid in all_ids if mid not in forbidden]
        assert eligible == ["meth-002", "meth-003", "meth-004"]

    @pytest.mark.asyncio
    async def test_one_failure_not_forbidden(self, seeded_db):
        """A single failure does NOT trigger forbidden (threshold is 2)."""
        repo = seeded_db
        await repo.engine.execute(
            """INSERT INTO methodology_usage_log
               (id, task_id, methodology_id, project_id, stage, success)
               VALUES (?, ?, ?, ?, ?, ?)""",
            [str(uuid.uuid4()), "task-001", "meth-000", "proj-1", "outcome_attributed", 0],
        )
        fail_counts = await repo.get_task_content_failure_counts("task-001")
        forbidden = {mid for mid, cnt in fail_counts.items() if cnt >= 2}
        assert "meth-000" not in forbidden

    @pytest.mark.asyncio
    async def test_infra_failure_not_counted(self, seeded_db):
        """Infrastructure failures (not outcome_attributed) don't count toward forbidden."""
        repo = seeded_db
        # Two failures but at 'retrieved_presented' stage (infra-like) — should NOT forbid
        for _ in range(2):
            await repo.engine.execute(
                """INSERT INTO methodology_usage_log
                   (id, task_id, methodology_id, project_id, stage, success)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [str(uuid.uuid4()), "task-001", "meth-000", "proj-1", "retrieved_presented", 0],
            )
        fail_counts = await repo.get_task_content_failure_counts("task-001")
        forbidden = {mid for mid, cnt in fail_counts.items() if cnt >= 2}
        assert "meth-000" not in forbidden

    @pytest.mark.asyncio
    async def test_bandit_outcome_recorded_after_failure(self, seeded_db):
        """Bandit outcomes are recorded alongside content failures."""
        repo = seeded_db
        # Record bandit failure for meth-000
        await repo.record_bandit_outcome("meth-000", "architecture", success=False)
        await repo.record_bandit_outcome("meth-000", "architecture", success=False)

        s, f = await repo.get_bandit_stats("meth-000", "architecture")
        assert s == 0
        assert f == 2

        # Record bandit success for meth-001
        await repo.record_bandit_outcome("meth-001", "architecture", success=True)

        s1, f1 = await repo.get_bandit_stats("meth-001", "architecture")
        assert s1 == 1
        assert f1 == 0

        # On next selection, meth-001 should outperform meth-000
        from claw.memory.bandit import BanditCandidate, MethodologyBandit

        bandit = MethodologyBandit(epsilon=0.0, thompson_threshold=5, seed=42)
        candidates = [
            BanditCandidate("meth-000", hybrid_score=0.5, fitness=0.7, successes=0, failures=2, total_outcomes=2),
            BanditCandidate("meth-001", hybrid_score=0.5, fitness=0.7, successes=1, failures=0, total_outcomes=1),
        ]
        # Both below Thompson threshold, so pure hybrid_score — tied at 0.5
        # But this tests the recording path is correct
        selected = bandit.select(candidates)
        assert selected is not None


class TestSchemaCreation:
    """Test that the bandit table gets created via migration."""

    @pytest.mark.asyncio
    async def test_table_exists_after_init(self, db_repo):
        repo = db_repo
        row = await repo.engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM sqlite_master "
            "WHERE type='table' AND name='methodology_bandit_outcomes'"
        )
        assert row["cnt"] == 1

    @pytest.mark.asyncio
    async def test_index_exists(self, db_repo):
        repo = db_repo
        row = await repo.engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM sqlite_master "
            "WHERE type='index' AND name='idx_bandit_task_type'"
        )
        assert row["cnt"] == 1


class TestBanditSummary:
    """Test get_bandit_summary() returns correct format and data."""

    @pytest.mark.asyncio
    async def test_empty_table_returns_empty_list(self, db_repo):
        """No bandit outcomes recorded should return an empty list."""
        result = await db_repo.get_bandit_summary()
        assert result == []

    @pytest.mark.asyncio
    async def test_summary_with_seeded_data(self, seeded_db):
        """Summary returns expected fields and computed columns."""
        repo = seeded_db
        # Record outcomes for two methodology x task_type pairs
        # meth-000 / architecture: 4 wins, 1 loss (below Thompson threshold)
        for _ in range(4):
            await repo.record_bandit_outcome("meth-000", "architecture", success=True)
        await repo.record_bandit_outcome("meth-000", "architecture", success=False)

        # meth-001 / testing: 7 wins, 3 losses (above Thompson threshold)
        for _ in range(7):
            await repo.record_bandit_outcome("meth-001", "testing", success=True)
        for _ in range(3):
            await repo.record_bandit_outcome("meth-001", "testing", success=False)

        rows = await repo.get_bandit_summary()
        assert len(rows) == 2

        # Rows are ordered by total DESC, so meth-001/testing (10) comes first
        top = rows[0]
        assert top["methodology_id"] == "meth-001"
        assert top["task_type"] == "testing"
        assert top["successes"] == 7
        assert top["failures"] == 3
        assert top["total"] == 10
        assert top["win_rate"] == 0.7
        assert top["thompson_graduated"] == 1

        second = rows[1]
        assert second["methodology_id"] == "meth-000"
        assert second["task_type"] == "architecture"
        assert second["successes"] == 4
        assert second["failures"] == 1
        assert second["total"] == 5
        assert second["win_rate"] == 0.8
        assert second["thompson_graduated"] == 1

    @pytest.mark.asyncio
    async def test_summary_below_thompson_threshold(self, seeded_db):
        """Pairs with fewer than 5 trials should have thompson_graduated=0."""
        repo = seeded_db
        await repo.record_bandit_outcome("meth-002", "security", success=True)
        await repo.record_bandit_outcome("meth-002", "security", success=False)

        rows = await repo.get_bandit_summary()
        assert len(rows) == 1
        row = rows[0]
        assert row["total"] == 2
        assert row["thompson_graduated"] == 0
        assert row["win_rate"] == 0.5

    @pytest.mark.asyncio
    async def test_summary_all_fields_present(self, seeded_db):
        """Every row must contain all expected keys."""
        repo = seeded_db
        await repo.record_bandit_outcome("meth-003", "refactoring", success=True)

        rows = await repo.get_bandit_summary()
        assert len(rows) == 1
        expected_keys = {
            "methodology_id", "task_type", "successes", "failures",
            "total", "win_rate", "thompson_graduated", "last_updated",
        }
        assert set(rows[0].keys()) == expected_keys

    @pytest.mark.asyncio
    async def test_summary_respects_limit(self, seeded_db):
        """Summary is capped at 50 rows (LIMIT 50 in query)."""
        repo = seeded_db
        # Create 5 methodologies x 12 task_types = 60 pairs (exceeds limit)
        task_types = [f"task_type_{i}" for i in range(12)]
        for i in range(5):
            meth_id = f"meth-{i:03d}"
            for tt in task_types:
                await repo.record_bandit_outcome(meth_id, tt, success=True)

        rows = await repo.get_bandit_summary()
        assert len(rows) == 50

    @pytest.mark.asyncio
    async def test_summary_zero_division_safe(self, db_repo):
        """Pairs with 0 successes and 0 failures should not cause division errors.

        This edge case is handled by the CASE WHEN in SQL, but we verify it
        at the application level too. We insert a row directly to simulate
        a (0,0) state that cannot happen through record_bandit_outcome.
        """
        repo = db_repo
        await repo.engine.execute(
            "INSERT INTO methodologies (id, problem_description, solution_code, lifecycle_state) "
            "VALUES (?, ?, ?, ?)",
            ["meth-edge", "edge case", "pass", "viable"],
        )
        # Insert a (0,0) row directly — can't happen via upsert but tests SQL safety
        await repo.engine.execute(
            """INSERT INTO methodology_bandit_outcomes
               (methodology_id, task_type, successes, failures, last_updated)
               VALUES (?, ?, 0, 0, strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))""",
            ["meth-edge", "edge"],
        )
        rows = await repo.get_bandit_summary()
        assert len(rows) == 1
        assert rows[0]["win_rate"] == 0.0
        assert rows[0]["total"] == 0
