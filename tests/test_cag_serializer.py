"""Tests for CAG methodology serializer."""
from __future__ import annotations

import json

import pytest

from claw.core.models import Methodology
from claw.memory.cag_serializer import serialize_methodology, serialize_corpus


def _make_methodology(
    id: str = "m-001",
    problem: str = "How to handle retries",
    solution: str = "def retry(fn, n=3): ...",
    notes: str = "Exponential backoff recommended",
    tags: list | None = None,
    lifecycle_state: str = "viable",
    fitness_vector: dict | None = None,
    capability_data: dict | None = None,
) -> Methodology:
    return Methodology(
        id=id,
        problem_description=problem,
        solution_code=solution,
        methodology_notes=notes,
        tags=tags or ["python", "source:github.com/example/repo"],
        lifecycle_state=lifecycle_state,
        fitness_vector=fitness_vector or {"success_rate": 0.8, "retrieval_count": 5},
        capability_data=capability_data or {
            "domain": ["error-handling"],
            "inputs": [{"name": "function", "type": "callable"}],
            "outputs": [{"name": "result", "type": "any"}],
            "activation_triggers": ["retry", "resilience"],
            "composability": {"can_chain": True},
        },
    )


class TestSerializeSingleMethodology:
    def test_contains_id(self):
        m = _make_methodology(id="m-123")
        text = serialize_methodology(m)
        assert "m-123" in text

    def test_contains_problem(self):
        m = _make_methodology(problem="Handle timeout errors")
        text = serialize_methodology(m)
        assert "Handle timeout errors" in text

    def test_contains_solution(self):
        m = _make_methodology(solution="def handle_timeout(): pass")
        text = serialize_methodology(m)
        assert "def handle_timeout(): pass" in text

    def test_contains_domain(self):
        m = _make_methodology()
        text = serialize_methodology(m)
        assert "error-handling" in text

    def test_contains_lifecycle(self):
        m = _make_methodology(lifecycle_state="thriving")
        text = serialize_methodology(m)
        assert "thriving" in text

    def test_contains_fitness_score(self):
        m = _make_methodology(fitness_vector={"success_rate": 0.92})
        text = serialize_methodology(m)
        assert "0.92" in text or "0.9" in text

    def test_long_solution_truncated_with_pointer(self):
        long_code = "x = 1\n" * 500  # >2000 chars
        m = _make_methodology(solution=long_code)
        text = serialize_methodology(m, max_solution_chars=2000)
        assert len(text) < len(long_code) + 500  # much shorter than raw
        assert "[TRUNCATED" in text or "..." in text

    def test_contains_tags(self):
        m = _make_methodology(tags=["python", "retry"])
        text = serialize_methodology(m)
        assert "python" in text
        assert "retry" in text

    def test_contains_activation_triggers(self):
        m = _make_methodology()
        text = serialize_methodology(m)
        assert "retry" in text or "resilience" in text


class TestSerializeCorpus:
    def test_empty_list_returns_header_only(self):
        text = serialize_corpus([])
        assert "CAM Knowledge Base" in text or text.strip() == ""

    def test_single_methodology(self):
        m = _make_methodology(id="m-001")
        text = serialize_corpus([m])
        assert "m-001" in text

    def test_multiple_methodologies_separated(self):
        m1 = _make_methodology(id="m-001", problem="Problem A")
        m2 = _make_methodology(id="m-002", problem="Problem B")
        text = serialize_corpus([m1, m2])
        assert "m-001" in text
        assert "m-002" in text
        assert "Problem A" in text
        assert "Problem B" in text

    def test_max_count_limits_output(self):
        methods = [_make_methodology(id=f"m-{i:03d}") for i in range(100)]
        text = serialize_corpus(methods, max_count=10)
        assert "m-009" in text
        assert "m-010" not in text

    def test_sorted_by_fitness(self):
        """Higher fitness methodologies appear first."""
        m_low = _make_methodology(id="low", fitness_vector={"success_rate": 0.2})
        m_high = _make_methodology(id="high", fitness_vector={"success_rate": 0.9})
        text = serialize_corpus([m_low, m_high])
        assert text.index("high") < text.index("low")
