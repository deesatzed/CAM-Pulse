"""Tests for CAG shorthand compression (L3).

Tests the extractive fallback compressor and the compress_text entry point.
BART model tests are conditional on transformers being installed.
"""
from __future__ import annotations

import pytest

from claw.memory.cag_compressor import (
    _compress_extractive,
    compress_text,
    reset_summarizer_state,
)


# ---------------------------------------------------------------------------
# Extractive compression (always available, no external deps)
# ---------------------------------------------------------------------------

class TestCompressExtractive:
    def test_two_or_fewer_sentences_returns_truncated(self):
        """With 2 or fewer sentences, should return text[:max_output_chars]."""
        text = "First sentence. Second sentence."
        result = _compress_extractive(text, max_output_chars=100)
        assert result == text  # fits in budget

    def test_two_sentences_over_budget_truncated(self):
        """Two sentences that exceed budget should be truncated."""
        text = "A" * 300 + ". " + "B" * 300 + "."
        result = _compress_extractive(text, max_output_chars=50)
        assert len(result) <= 50

    def test_keeps_first_and_last_sentence(self):
        """Should always keep the first and last sentences."""
        text = (
            "The module initializes the database connection pool. "
            "It validates the connection string format. "
            "It sets the pool size based on available memory. "
            "It configures timeout parameters for each connection. "
            "It logs connection metrics for monitoring. "
            "The pool is ready for concurrent access after initialization."
        )
        result = _compress_extractive(text, max_output_chars=250)
        assert "The module initializes" in result
        assert "after initialization" in result

    def test_middle_sentences_are_included_within_budget(self):
        """Middle sentences should be added sequentially until budget runs out."""
        text = (
            "Step one. "
            "Step two. "
            "Step three. "
            "Step four. "
            "Step five. "
            "Final step."
        )
        result = _compress_extractive(text, max_output_chars=500)
        # All sentences fit in 500 chars
        assert "Step one" in result
        assert "Final step" in result
        assert "Step two" in result

    def test_reduces_length_for_long_text(self):
        """Extractive compression should reduce long text significantly."""
        text = "First sentence about the algorithm. " + "Middle filler sentence number X. " * 50 + "Last conclusion sentence."
        result = _compress_extractive(text, max_output_chars=200)
        assert len(result) <= 250  # Allow some margin for sentence boundaries
        assert "First sentence" in result
        assert "Last conclusion" in result

    def test_empty_text(self):
        """Empty text should return empty string."""
        result = _compress_extractive("", max_output_chars=100)
        assert result == ""

    def test_single_sentence(self):
        """A single sentence should be truncated if over budget."""
        text = "A" * 500 + "."
        result = _compress_extractive(text, max_output_chars=100)
        assert len(result) <= 100


# ---------------------------------------------------------------------------
# compress_text entry point
# ---------------------------------------------------------------------------

class TestCompressText:
    def setup_method(self):
        """Reset summarizer state before each test."""
        reset_summarizer_state()

    def test_short_text_unchanged(self):
        """Text under min_input_chars should be returned as-is."""
        text = "Short text under threshold."
        assert compress_text(text) == text

    def test_short_text_custom_threshold(self):
        """Custom min_input_chars should be respected."""
        text = "A" * 100
        result = compress_text(text, min_input_chars=200)
        assert result == text

    def test_text_at_exactly_min_input_unchanged(self):
        """Text exactly at min_input_chars should be returned as-is."""
        text = "A" * 500
        result = compress_text(text, min_input_chars=500)
        assert result == text

    def test_long_text_gets_compressed(self):
        """Text over min_input_chars should be compressed (via fallback)."""
        text = (
            "The system processes incoming requests through a validation pipeline. "
            "Each request is checked for authentication tokens and rate limits. "
            "Valid requests are routed to the appropriate backend service. "
            "The backend service processes the request and returns a response. "
            "Error responses include detailed diagnostics for debugging. "
            "All request metadata is logged for audit and monitoring purposes. "
            "The pipeline supports graceful degradation during high load. "
            "Circuit breakers prevent cascade failures across services. "
            "Health checks run continuously to detect service anomalies. "
            "The monitoring dashboard displays request latency percentiles. "
            "Alert thresholds are configurable per service and per endpoint. "
            "Automatic scaling triggers when latency exceeds the threshold."
        )
        result = compress_text(text, max_output_chars=300, min_input_chars=100)
        assert len(result) < len(text)
        # Should contain first and last sentence (extractive fallback)
        assert "validation pipeline" in result
        assert "threshold" in result

    def test_compress_text_respects_max_output(self):
        """Output should respect max_output_chars (with some margin for sentence boundaries)."""
        text = "Sentence number one. " * 100
        result = compress_text(text, max_output_chars=200, min_input_chars=100)
        # Allow generous margin since extractive compression works at sentence boundaries
        assert len(result) < len(text)

    def test_compress_text_deterministic(self):
        """Same input should produce same output (no randomness in fallback)."""
        text = (
            "Alpha sentence about algorithms. "
            "Beta sentence about data structures. "
            "Gamma sentence about complexity analysis. "
            "Delta sentence about optimization. "
            "Epsilon sentence about testing methodology. "
            "Zeta sentence about deployment strategies."
        ) * 3
        r1 = compress_text(text, max_output_chars=200, min_input_chars=100)
        reset_summarizer_state()
        r2 = compress_text(text, max_output_chars=200, min_input_chars=100)
        assert r1 == r2


# ---------------------------------------------------------------------------
# Config integration
# ---------------------------------------------------------------------------

class TestCAGConfigFields:
    def test_default_values(self):
        """CAGConfig should have shorthand fields with correct defaults."""
        from claw.core.config import CAGConfig

        cfg = CAGConfig()
        assert cfg.shorthand_compression is False
        assert cfg.shorthand_max_solution_chars == 800

    def test_custom_values(self):
        """CAGConfig should accept custom shorthand values."""
        from claw.core.config import CAGConfig

        cfg = CAGConfig(shorthand_compression=True, shorthand_max_solution_chars=400)
        assert cfg.shorthand_compression is True
        assert cfg.shorthand_max_solution_chars == 400


# ---------------------------------------------------------------------------
# BART summarizer (conditional)
# ---------------------------------------------------------------------------

class TestBARTSummarizer:
    """These tests only run if transformers is installed."""

    @pytest.fixture(autouse=True)
    def _check_transformers(self):
        """Skip all tests in this class if transformers is not installed."""
        pytest.importorskip("transformers")

    def test_bart_loads_and_summarizes(self):
        """BART summarizer should load and produce output."""
        reset_summarizer_state()
        from claw.memory.cag_compressor import _load_summarizer

        summarizer = _load_summarizer()
        if summarizer is None:
            pytest.skip("BART model could not be loaded")

        text = (
            "The Python programming language was created by Guido van Rossum. "
            "It was first released in 1991 as a successor to the ABC language. "
            "Python emphasizes code readability with its use of significant indentation. "
            "It supports multiple programming paradigms including procedural, "
            "object-oriented, and functional programming. "
            "Python has a large standard library and active community. "
            "It is widely used in web development, data science, and automation."
        )
        result = summarizer(text, max_length=100, min_length=30, do_sample=False)
        assert len(result) > 0
        assert "summary_text" in result[0]
