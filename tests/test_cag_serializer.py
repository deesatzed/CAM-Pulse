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


# ---------------------------------------------------------------------------
# L2 Context Pointer Tests
# ---------------------------------------------------------------------------

class TestContextPointers:
    """Tests for L2 context pointer serialization.

    When pointer_threshold > 0 and a solution exceeds that length, the
    serializer emits a compact pointer block instead of truncated code.
    """

    def test_short_solution_no_pointer(self):
        """Solutions under threshold should be included in full."""
        m = _make_methodology(
            id="short-sol",
            solution="def foo(): pass",
        )
        result = serialize_methodology(m, pointer_threshold=2000)
        assert "def foo(): pass" in result
        assert "POINTER" not in result

    def test_long_solution_gets_pointer(self):
        """Solutions over threshold should emit pointer format."""
        m = _make_methodology(
            id="long-sol",
            problem="Complex algorithm for sorting",
            solution="x = 1\n" * 2000,
        )
        result = serialize_methodology(m, pointer_threshold=2000)
        assert "POINTER" in result
        assert "ref:methodology#long-sol" in result
        assert "Complex algorithm" in result
        # The full solution should NOT appear
        assert result.count("x = 1") < 10

    def test_pointer_includes_capability_summary(self):
        """Pointer format should include capability data summary."""
        m = _make_methodology(
            id="cap-sol",
            problem="Pattern matching",
            solution="z = 1\n" * 2000,
            capability_data={
                "domain": ["ml", "nlp"],
                "activation_triggers": ["text input"],
            },
        )
        result = serialize_methodology(m, pointer_threshold=2000)
        assert "POINTER" in result
        assert "domain=ml" in result

    def test_pointer_threshold_zero_disabled(self):
        """With pointer_threshold=0, should use old truncation behavior."""
        m = _make_methodology(
            id="no-ptr",
            problem="test",
            solution="y = 1\n" * 2000,
        )
        result = serialize_methodology(m, max_solution_chars=100, pointer_threshold=0)
        assert "TRUNCATED" in result
        assert "POINTER" not in result

    def test_pointer_saves_chars(self):
        """Pointer format should be significantly shorter than full solution."""
        long_solution = "import os\ndef complex_function():\n    " + "x = 1\n    " * 500
        m = _make_methodology(
            id="savings-test",
            problem="Complex function",
            solution=long_solution,
        )
        full = serialize_methodology(m, max_solution_chars=99999, pointer_threshold=0)
        pointer = serialize_methodology(m, pointer_threshold=2000)
        assert len(pointer) < len(full) * 0.5  # At least 2x shorter

    def test_serialize_corpus_with_pointers(self):
        """serialize_corpus should pass through pointer_threshold."""
        methods = [
            _make_methodology(
                id=f"m{i}",
                problem=f"Problem {i}",
                solution="code\n" * (500 if i % 2 == 0 else 10),
            )
            for i in range(4)
        ]
        result = serialize_corpus(methods, pointer_threshold=2000)
        # Even-indexed have long solutions (500*5=2500 chars) -> should get pointers
        assert "POINTER" in result
        # Odd-indexed have short solutions (10*5=50 chars) -> should be inline
        assert "code" in result

    def test_pointer_includes_methodology_id(self):
        """Pointer block must contain the methodology ID."""
        m = _make_methodology(
            id="ptr-id-check",
            solution="a = 1\n" * 1000,
        )
        result = serialize_methodology(m, pointer_threshold=2000)
        assert "ptr-id-check" in result
        assert "=== METHODOLOGY ptr-id-check ===" in result

    def test_pointer_includes_problem_description(self):
        """Pointer block must preserve the full problem description."""
        m = _make_methodology(
            id="ptr-prob",
            problem="Detect anomalies in time-series sensor data using windowed z-scores",
            solution="b = 1\n" * 1000,
        )
        result = serialize_methodology(m, pointer_threshold=2000)
        assert "Detect anomalies in time-series sensor data using windowed z-scores" in result

    def test_pointer_includes_solution_size(self):
        """Pointer should report the solution size in chars."""
        solution = "c = 1\n" * 1000  # 6000 chars
        m = _make_methodology(
            id="ptr-size",
            solution=solution,
        )
        result = serialize_methodology(m, pointer_threshold=2000)
        assert str(len(solution)) in result

    def test_pointer_truncates_long_notes(self):
        """Notes in pointer format should be truncated to 200 chars."""
        long_notes = "N" * 500
        m = _make_methodology(
            id="ptr-notes",
            notes=long_notes,
            solution="d = 1\n" * 1000,
        )
        result = serialize_methodology(m, pointer_threshold=2000)
        assert "NOTES:" in result
        assert "..." in result
        # Notes portion should not contain the full 500-char string
        notes_line = [l for l in result.split("\n") if l.startswith("NOTES:")][0]
        # 200 chars of content + "NOTES: " prefix + "..."
        assert len(notes_line) < 250

    def test_pointer_with_no_capability_data(self):
        """Pointer should show 'no capability data' when cap data is empty."""
        m = Methodology(
            id="ptr-nocap",
            problem_description="Bare methodology",
            solution_code="e = 1\n" * 1000,
            lifecycle_state="viable",
            capability_data=None,
        )
        result = serialize_methodology(m, pointer_threshold=2000)
        assert "POINTER" in result
        assert "no capability data" in result

    def test_pointer_with_outputs_in_capability(self):
        """Pointer capability summary should include output names."""
        m = _make_methodology(
            id="ptr-out",
            solution="f = 1\n" * 1000,
            capability_data={
                "domain": ["data-processing"],
                "outputs": [{"name": "cleaned_df"}, {"name": "report"}],
                "activation_triggers": ["csv upload", "data cleaning"],
            },
        )
        result = serialize_methodology(m, pointer_threshold=2000)
        assert "POINTER" in result
        assert "outputs=cleaned_df, report" in result

    def test_pointer_does_not_include_io_triggers_lines(self):
        """Pointer format should NOT include the detailed IO/TRIGGERS lines."""
        m = _make_methodology(
            id="ptr-no-io",
            solution="g = 1\n" * 1000,
        )
        result = serialize_methodology(m, pointer_threshold=2000)
        # The full-format IO and TRIGGERS lines should not appear
        assert "IO: inputs=" not in result
        assert "TRIGGERS:" not in result

    def test_default_pointer_threshold_is_disabled(self):
        """Default pointer_threshold=0 means pointers are off."""
        long_sol = "h = 1\n" * 1000
        m = _make_methodology(id="default-check", solution=long_sol)
        # Default call (no pointer_threshold arg)
        result = serialize_methodology(m, max_solution_chars=100)
        assert "TRUNCATED" in result
        assert "POINTER" not in result

    def test_solution_exactly_at_threshold_no_pointer(self):
        """Solution exactly at threshold length should NOT get a pointer."""
        # 2000 chars exactly
        solution = "a" * 2000
        m = _make_methodology(id="exact-thresh", solution=solution)
        result = serialize_methodology(m, pointer_threshold=2000)
        assert "POINTER" not in result
        # Solution should be included in full (it is exactly at max)
        assert "a" * 100 in result

    def test_solution_one_over_threshold_gets_pointer(self):
        """Solution one char over threshold should get a pointer."""
        solution = "a" * 2001
        m = _make_methodology(id="one-over", solution=solution)
        result = serialize_methodology(m, pointer_threshold=2000)
        assert "POINTER" in result
        assert "ref:methodology#one-over" in result


# ---------------------------------------------------------------------------
# L3 Shorthand Compression Tests (serializer integration)
# ---------------------------------------------------------------------------

class TestSerializeWithCompression:
    """Tests for the shorthand compression integration in serializer."""

    def test_short_solution_unchanged_with_compress(self):
        """Solutions under compress_max_chars should pass through unchanged."""
        m = _make_methodology(solution="def foo(): return 42")
        result_raw = serialize_methodology(m, max_solution_chars=2000)
        result_compressed = serialize_methodology(
            m, compress=True, compress_max_chars=800
        )
        # Short solution -- compress flag should not alter it
        assert "def foo(): return 42" in result_compressed
        assert "def foo(): return 42" in result_raw

    def test_compress_reduces_long_solution(self):
        """A long solution should be shorter after compression."""
        # Build a realistically long solution with repetitive sentences
        long_solution = (
            "The retry mechanism uses exponential backoff with jitter. "
            "Each attempt waits longer than the previous one. "
            "The base delay is multiplied by a power of two. "
            "Random jitter prevents thundering herd problems. "
            "The maximum retry count defaults to three attempts. "
            "After exhausting all retries the error is propagated. "
            "Logging captures each attempt for debugging purposes. "
            "The circuit breaker pattern complements retry logic. "
            "When failures exceed a threshold the circuit opens. "
            "Subsequent requests fail immediately without retrying. "
        ) * 6  # ~600 chars * 6 = ~3600 chars
        m = _make_methodology(id="m-compress", solution=long_solution)
        result_raw = serialize_methodology(m, max_solution_chars=5000)
        result_compressed = serialize_methodology(
            m, compress=True, compress_max_chars=400
        )
        # Compressed version should be meaningfully shorter
        assert len(result_compressed) < len(result_raw)

    def test_compress_preserves_metadata(self):
        """Compression should not affect non-solution fields."""
        long_solution = "This is a long solution text. " * 30
        m = _make_methodology(
            id="m-meta-test",
            problem="Test problem for compression",
            solution=long_solution,
            lifecycle_state="thriving",
        )
        result = serialize_methodology(m, compress=True, compress_max_chars=200)
        assert "m-meta-test" in result
        assert "Test problem for compression" in result
        assert "thriving" in result

    def test_compress_flag_in_corpus(self):
        """serialize_corpus should pass compress flag through."""
        long_solution = "The algorithm processes data sequentially. " * 30
        m1 = _make_methodology(id="m-c1", solution=long_solution)
        m2 = _make_methodology(id="m-c2", solution="short")
        corpus_raw = serialize_corpus([m1, m2], max_solution_chars=5000)
        corpus_compressed = serialize_corpus(
            [m1, m2],
            max_solution_chars=5000,
            compress=True,
            compress_max_chars=200,
        )
        # Compressed corpus should be shorter due to m1 compression
        assert len(corpus_compressed) < len(corpus_raw)
        # Both IDs should still be present
        assert "m-c1" in corpus_compressed
        assert "m-c2" in corpus_compressed

    def test_compress_with_notes(self):
        """Long methodology_notes should also be compressed when enabled."""
        long_notes = (
            "This methodology was discovered during a large-scale refactoring. "
            "The original code used synchronous blocking calls throughout. "
            "Converting to async patterns improved throughput dramatically. "
            "Testing showed a reduction in latency under high concurrency. "
            "The approach works best with IO-bound workloads specifically. "
            "CPU-bound tasks see minimal benefit from this pattern overall. "
        ) * 5
        m = _make_methodology(
            id="m-notes",
            solution="def foo(): pass",
            notes=long_notes,
        )
        result_raw = serialize_methodology(m, max_solution_chars=5000)
        result_compressed = serialize_methodology(
            m, compress=True, compress_max_chars=300
        )
        # Notes should be shorter in compressed version
        assert len(result_compressed) < len(result_raw)
        assert "m-notes" in result_compressed

    def test_pointer_takes_precedence_over_compress(self):
        """When pointer_threshold is active and solution exceeds it,
        the pointer path should be used regardless of compress flag."""
        long_solution = "x = 1\n" * 500
        m = _make_methodology(id="m-ptr", solution=long_solution)
        result = serialize_methodology(
            m,
            pointer_threshold=100,
            compress=True,
            compress_max_chars=200,
        )
        # Should use pointer format, not compression
        assert "POINTER" in result
        assert "ref:methodology#m-ptr" in result
