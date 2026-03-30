"""Tests for CAG (Cache-Augmented Generation) integration into the agent interface.

Validates that the CAG retrieval path is correctly wired into
AgentInterface._build_openrouter_prompt() and _resolve_cag_context().

All tests use REAL Pydantic model objects -- no mocks, no placeholders,
no cached responses.
"""
from __future__ import annotations

import pytest

from claw.agents.interface import AgentInterface
from claw.agents.claude import ClaudeCodeAgent
from claw.core.models import AgentMode, Task, TaskContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task_context(task_type: str, title: str = "test task", description: str = "test description") -> TaskContext:
    """Create a real TaskContext with the given task_type."""
    task = Task(
        project_id="test-project",
        title=title,
        description=description,
        task_type=task_type,
    )
    return TaskContext(task=task)


def _make_agent() -> ClaudeCodeAgent:
    """Create a real ClaudeCodeAgent for testing base class behavior.

    Uses CLI mode so can_use_internal_workspace_executor() returns False,
    which keeps prompt output simpler for knowledge injection tests.
    """
    return ClaudeCodeAgent(mode=AgentMode.CLI)


# ---------------------------------------------------------------------------
# Test: _resolve_cag_context returns corpus for mining task
# ---------------------------------------------------------------------------

class TestResolveCagContextMiningTask:
    def test_resolve_cag_context_returns_corpus_for_mining_task(self):
        """mining_extraction task type with a loaded corpus must return the corpus."""
        ctx = _make_task_context("mining_extraction")
        corpus = "=== CAG Corpus ===\nMethodology A\nMethodology B"

        result = AgentInterface._resolve_cag_context(ctx, cag_corpus=corpus)

        assert result is not None
        assert result == corpus


# ---------------------------------------------------------------------------
# Test: _resolve_cag_context returns None for analysis task
# ---------------------------------------------------------------------------

class TestResolveCagContextAnalysisTask:
    def test_resolve_cag_context_returns_none_for_analysis_task(self):
        """analysis task type must NOT receive CAG corpus (not in eligible set)."""
        ctx = _make_task_context("analysis")
        corpus = "=== CAG Corpus ===\nMethodology A"

        result = AgentInterface._resolve_cag_context(ctx, cag_corpus=corpus)

        assert result is None


# ---------------------------------------------------------------------------
# Test: _resolve_cag_context returns None when empty corpus
# ---------------------------------------------------------------------------

class TestResolveCagContextEmptyCorpus:
    def test_resolve_cag_context_returns_none_when_empty_corpus(self):
        """Empty corpus must always return None regardless of task type."""
        ctx = _make_task_context("mining_extraction")

        result = AgentInterface._resolve_cag_context(ctx, cag_corpus="")

        assert result is None

    def test_resolve_cag_context_returns_none_when_default_corpus(self):
        """Default (no argument) corpus must return None."""
        ctx = _make_task_context("mining_extraction")

        result = AgentInterface._resolve_cag_context(ctx)

        assert result is None


# ---------------------------------------------------------------------------
# Test: _resolve_cag_context for bulk_classification
# ---------------------------------------------------------------------------

class TestResolveCagContextBulkClassification:
    def test_resolve_cag_context_bulk_classification(self):
        """bulk_classification task type must return the corpus."""
        ctx = _make_task_context("bulk_classification")
        corpus = "Full corpus content for classification"

        result = AgentInterface._resolve_cag_context(ctx, cag_corpus=corpus)

        assert result is not None
        assert result == corpus


# ---------------------------------------------------------------------------
# Test: _cag_corpus attribute default empty
# ---------------------------------------------------------------------------

class TestCagCorpusAttributeDefault:
    def test_cag_corpus_attribute_default_empty(self):
        """A new AgentInterface subclass instance must have _cag_corpus as empty string."""
        agent = _make_agent()

        assert hasattr(agent, "_cag_corpus")
        assert agent._cag_corpus == ""


# ---------------------------------------------------------------------------
# Test: set_cag_corpus
# ---------------------------------------------------------------------------

class TestSetCagCorpus:
    def test_set_cag_corpus_stores_value(self):
        """set_cag_corpus must store the corpus text on the instance."""
        agent = _make_agent()
        corpus_text = "=== Full Methodology Corpus ===\nPattern 1\nPattern 2\nPattern 3"

        agent.set_cag_corpus(corpus_text)

        assert agent._cag_corpus == corpus_text

    def test_set_cag_corpus_empty_clears(self):
        """Calling set_cag_corpus with empty string disables CAG."""
        agent = _make_agent()
        agent.set_cag_corpus("some corpus")
        assert agent._cag_corpus == "some corpus"

        agent.set_cag_corpus("")
        assert agent._cag_corpus == ""


# ---------------------------------------------------------------------------
# Test: all CAG-eligible task types are recognized
# ---------------------------------------------------------------------------

class TestAllCagEligibleTaskTypes:
    @pytest.mark.parametrize("task_type", [
        "mining_extraction",
        "bulk_classification",
        "pattern_extraction",
        "code_summarization",
        "mining",
        "novelty_detection",
        "synergy_discovery",
    ])
    def test_eligible_task_type_returns_corpus(self, task_type: str):
        """Every task type in CAG_ELIGIBLE_TASK_TYPES must return the corpus."""
        ctx = _make_task_context(task_type)
        corpus = f"corpus for {task_type}"

        result = AgentInterface._resolve_cag_context(ctx, cag_corpus=corpus)

        assert result == corpus


# ---------------------------------------------------------------------------
# Test: non-eligible task types are rejected
# ---------------------------------------------------------------------------

class TestNonEligibleTaskTypes:
    @pytest.mark.parametrize("task_type", [
        "analysis",
        "refactoring",
        "bug_fix",
        "code_review",
        "testing",
        "documentation",
        "",
    ])
    def test_non_eligible_task_type_returns_none(self, task_type: str):
        """Task types not in CAG_ELIGIBLE_TASK_TYPES must return None."""
        ctx = _make_task_context(task_type)
        corpus = "should not be used"

        result = AgentInterface._resolve_cag_context(ctx, cag_corpus=corpus)

        assert result is None


# ---------------------------------------------------------------------------
# Test: task with None task_type
# ---------------------------------------------------------------------------

class TestNoneTaskType:
    def test_none_task_type_returns_none(self):
        """Task with task_type=None must return None (not eligible)."""
        task = Task(
            project_id="test-project",
            title="no type task",
            description="test",
            task_type=None,
        )
        ctx = TaskContext(task=task)
        corpus = "should not be used"

        result = AgentInterface._resolve_cag_context(ctx, cag_corpus=corpus)

        assert result is None


# ---------------------------------------------------------------------------
# Test: CAG corpus appears in prompt for eligible tasks
# ---------------------------------------------------------------------------

class TestCagCorpusInPrompt:
    def test_cag_corpus_injected_into_prompt(self):
        """When CAG corpus is set and task is eligible, prompt must contain corpus text."""
        agent = _make_agent()
        corpus_text = "=== FULL CAG CORPUS: Pattern Alpha, Pattern Beta ==="
        agent.set_cag_corpus(corpus_text)

        ctx = _make_task_context("mining_extraction", title="Mine patterns", description="Extract patterns from codebase")
        prompt = agent._build_openrouter_prompt(ctx)

        assert "CAG: full methodology corpus" in prompt
        assert "Pattern Alpha" in prompt
        assert "Pattern Beta" in prompt
        assert "END KNOWLEDGE BASE" in prompt

    def test_cag_corpus_not_injected_for_non_eligible(self):
        """When CAG corpus is set but task is not eligible, prompt must NOT contain corpus."""
        agent = _make_agent()
        corpus_text = "=== SHOULD NOT APPEAR ==="
        agent.set_cag_corpus(corpus_text)

        ctx = _make_task_context("analysis", title="Analyze code", description="Review code quality")
        prompt = agent._build_openrouter_prompt(ctx)

        assert "SHOULD NOT APPEAR" not in prompt
        assert "CAG: full methodology corpus" not in prompt

    def test_cag_corpus_not_in_prompt_when_empty(self):
        """When no CAG corpus is set, prompt must not contain CAG section."""
        agent = _make_agent()
        # _cag_corpus is "" by default

        ctx = _make_task_context("mining_extraction")
        prompt = agent._build_openrouter_prompt(ctx)

        assert "CAG: full methodology corpus" not in prompt


# ---------------------------------------------------------------------------
# Test: CAG corpus respects budget limit
# ---------------------------------------------------------------------------

class TestCagCorpusBudgetLimit:
    def test_cag_corpus_truncated_to_budget(self):
        """CAG corpus injection must respect the knowledge budget."""
        agent = _make_agent()
        # Create a corpus larger than 8000 chars (the minimum budget)
        large_corpus = "X" * 20000
        agent.set_cag_corpus(large_corpus)

        ctx = _make_task_context("mining_extraction")
        prompt = agent._build_openrouter_prompt(ctx)

        # The corpus text in the prompt must be shorter than the full 20000 chars
        # Budget is at least 8000 chars; the prompt should contain at most
        # 8000 X chars from the corpus, not the full 20000
        x_count_in_prompt = prompt.count("X")
        assert x_count_in_prompt <= 8000
        assert x_count_in_prompt > 0


# ---------------------------------------------------------------------------
# Test: CAG path does not break HybridSearch fallback
# ---------------------------------------------------------------------------

class TestHybridSearchFallbackPreserved:
    def test_hybrid_search_still_works_without_cag(self):
        """Without CAG corpus, the standard HybridSearch path must still function.

        We verify by checking that _resolve_knowledge_source still returns
        the correct values when called on a task with no CAG corpus.
        """
        ctx = _make_task_context("analysis")
        # No context with past_solutions, should get empty
        methods, budget = AgentInterface._resolve_knowledge_source(ctx, context=None)
        assert methods == []
        assert budget == 0

    def test_cag_replaces_hybrid_search_for_eligible_task(self):
        """For eligible tasks with CAG corpus, HybridSearch section must NOT appear."""
        agent = _make_agent()
        agent.set_cag_corpus("CAG corpus content here")

        ctx = _make_task_context("mining_extraction")
        prompt = agent._build_openrouter_prompt(ctx)

        # CAG path should be present
        assert "CAG: full methodology corpus" in prompt
        # Standard HybridSearch header should NOT be present (CAG replaces it)
        assert "Retrieved Knowledge (from PULSE-mined methodologies)" not in prompt
