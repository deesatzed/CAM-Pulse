"""Tests for smart cross-brain search routing.

Covers:
    1. _detect_query_language — keyword detection per brain
    2. Ambiguous queries return None
    3. Multi-language queries return None (ambiguous)
    4. _QUERY_LANGUAGE_HINTS completeness

All tests use REAL dependencies — no mocks, no placeholders, no cached responses.
"""

from __future__ import annotations

import pytest

from claw.cli._monolith import (
    _QUERY_LANGUAGE_HINTS,
    _detect_query_language,
)


class TestDetectQueryLanguage:
    def test_go_goroutine(self):
        assert _detect_query_language("goroutine concurrency patterns") == "go"

    def test_go_golang(self):
        assert _detect_query_language("golang interface design") == "go"

    def test_rust_borrow_checker(self):
        assert _detect_query_language("borrow checker patterns") == "rust"

    def test_rust_tokio(self):
        assert _detect_query_language("tokio async runtime") == "rust"

    def test_typescript_react(self):
        assert _detect_query_language("react component patterns") == "typescript"

    def test_typescript_hooks(self):
        assert _detect_query_language("custom hooks for state") == "typescript"

    def test_python_pytest(self):
        assert _detect_query_language("pytest fixture patterns") == "python"

    def test_python_django(self):
        assert _detect_query_language("django ORM queries") == "python"

    def test_python_fastapi(self):
        assert _detect_query_language("fastapi dependency injection") == "python"

    def test_ambiguous_returns_none(self):
        """Generic queries with no language hints return None."""
        assert _detect_query_language("error handling patterns") is None
        assert _detect_query_language("design patterns") is None
        assert _detect_query_language("database migration") is None

    def test_mixed_languages_returns_none(self):
        """Queries mentioning multiple languages are ambiguous."""
        # "react" → typescript, "django" → python → 2 languages → None
        result = _detect_query_language("react and django integration")
        assert result is None

    def test_case_insensitive(self):
        assert _detect_query_language("GOROUTINE patterns") == "go"
        assert _detect_query_language("React Hooks") == "typescript"

    def test_hints_cover_all_four_languages(self):
        """All four main brains have at least one keyword mapping."""
        covered_brains = set(_QUERY_LANGUAGE_HINTS.values())
        assert "go" in covered_brains
        assert "rust" in covered_brains
        assert "typescript" in covered_brains
        assert "python" in covered_brains
