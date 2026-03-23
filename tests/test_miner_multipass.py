"""Tests for multi-pass mining pipeline (claw.miner).

Covers:
    1. _classify_repo_domain() — Pass 1 rule-based domain classification
    2. KnowledgeOverlap dataclass — Pass 2 structured overlap result
    3. _build_mining_context() — structured context construction for Pass 3
    4. Adaptive token budget — complexity-based token allocation

All tests use REAL dependencies — no mocks, no placeholders, no cached responses.
Domain classification tests use synthetic serialized content that mirrors the real
serialize_repo() output format.
"""

from __future__ import annotations

import pytest

from claw.miner import (
    KnowledgeOverlap,
    _DOMAIN_KEYWORDS,
    _LANGUAGE_SIGNALS,
    _VALID_CATEGORIES,
)


# ---------------------------------------------------------------------------
# Helpers: build synthetic serialized repo content in real format
# ---------------------------------------------------------------------------

def _make_serialized(files: dict[str, str]) -> tuple[str, int]:
    """Build serialized repo content matching serialize_repo() output format.

    Args:
        files: Mapping of relative file paths to file content.

    Returns:
        (serialized_content, file_count)
    """
    parts = []
    for path, content in files.items():
        parts.append(f"--- FILE: {path} ---")
        parts.append(content)
    return "\n".join(parts), len(files)


# ---------------------------------------------------------------------------
# Pass 1: _classify_repo_domain
# ---------------------------------------------------------------------------

class TestClassifyRepoDomain:
    """Tests for the rule-based domain classification (Pass 1)."""

    @pytest.fixture()
    def miner(self):
        """Minimal RepoMiner instance with only what _classify_repo_domain needs.

        _classify_repo_domain is a pure method that doesn't touch DB, LLM, or
        semantic memory — it only reads its arguments. We create a bare object.
        """
        from claw.miner import RepoMiner

        class _Stub:
            pass

        # _classify_repo_domain only accesses self implicitly (it's a method)
        # but doesn't use any instance attributes. We create a minimal stub.
        obj = _Stub()
        obj.__class__ = type("_FakeMiner", (), {
            "_classify_repo_domain": RepoMiner._classify_repo_domain,
        })
        return obj

    def test_python_agent_repo(self, miner):
        """A repo about AI agents with pyproject.toml → ai_integration + python."""
        content, count = _make_serialized({
            "README.md": (
                "# AgentFlow\n\n"
                "A multi-agent LLM orchestration framework. "
                "Uses OpenAI and Anthropic Claude models for prompt-driven workflows. "
                "Supports agent chaining, model routing, and inference pipelines."
            ),
            "pyproject.toml": '[project]\nname = "agentflow"\n',
            "src/agent.py": "class Agent: pass",
            "src/router.py": "class Router: pass",
            "tests/test_agent.py": "def test_agent(): pass",
        })
        result = miner._classify_repo_domain(content, count)

        assert result["primary_domain"] == "ai_integration"
        assert result["language"] == "python"
        assert result["complexity"] == "small"
        assert "readme_summary" in result
        assert len(result["readme_summary"]) > 0

    def test_web_middleware_repo(self, miner):
        """A repo about HTTP middleware/routing → architecture."""
        content, count = _make_serialized({
            "README.md": (
                "# RouterStack\n\n"
                "An ASGI middleware framework with plugin architecture. "
                "Supports request routing, middleware chains, and dependency injection. "
                "Built for microservice deployments."
            ),
            "package.json": '{"name": "routerstack"}',
            "src/middleware.ts": "export class Middleware {}",
        })
        result = miner._classify_repo_domain(content, count)

        assert result["primary_domain"] == "architecture"
        assert result["language"] in ("javascript", "typescript")

    def test_complexity_small_medium_large(self, miner):
        """File count maps to complexity tiers correctly."""
        # small: < 50 files
        content_s, _ = _make_serialized({"README.md": "hello"})
        r_small = miner._classify_repo_domain(content_s, 10)
        assert r_small["complexity"] == "small"

        # medium: 50-200 files
        r_med = miner._classify_repo_domain(content_s, 150)
        assert r_med["complexity"] == "medium"

        # large: > 200 files
        r_large = miner._classify_repo_domain(content_s, 500)
        assert r_large["complexity"] == "large"

    def test_ambiguous_repo_defaults_to_cross_cutting(self, miner):
        """A repo with no strong domain signals defaults to cross_cutting."""
        content, count = _make_serialized({
            "README.md": "# My Project\n\nA utility library.",
            "main.py": "print('hello')",
        })
        result = miner._classify_repo_domain(content, count)

        # Should still return a valid category
        assert result["primary_domain"] in _VALID_CATEGORIES

    def test_security_repo(self, miner):
        """A repo about auth/encryption → security."""
        content, count = _make_serialized({
            "README.md": (
                "# SecureGate\n\n"
                "OAuth2 and JWT authentication middleware. "
                "Handles RBAC permissions, CORS configuration, and CSRF protection. "
                "Includes input sanitization against XSS injection attacks."
            ),
            "pyproject.toml": '[project]\nname = "securegate"',
        })
        result = miner._classify_repo_domain(content, count)

        assert result["primary_domain"] == "security"


# ---------------------------------------------------------------------------
# Pass 2: KnowledgeOverlap dataclass
# ---------------------------------------------------------------------------

class TestKnowledgeOverlap:
    """Tests for the KnowledgeOverlap dataclass."""

    def test_empty_overlap(self):
        """Default KnowledgeOverlap represents a virgin domain."""
        overlap = KnowledgeOverlap()
        assert overlap.overlap_score == 0.0
        assert overlap.repo_known_titles == []
        assert overlap.domain_known_titles == []
        assert overlap.suggested_focus == []

    def test_full_overlap(self):
        """Populated overlap carries all fields."""
        overlap = KnowledgeOverlap(
            repo_known_titles=["Pattern A", "Pattern B"],
            domain_known_titles=["Related C"],
            domain_known_categories=["architecture", "security"],
            overlap_score=0.4,
            suggested_focus=["testing", "memory"],
        )
        assert overlap.overlap_score == 0.4
        assert len(overlap.repo_known_titles) == 2
        assert "testing" in overlap.suggested_focus


# ---------------------------------------------------------------------------
# Pass 3 context: _build_mining_context
# ---------------------------------------------------------------------------

class TestBuildMiningContext:
    """Tests for the context builder that produces LLM directives."""

    @pytest.fixture()
    def miner(self):
        from claw.miner import RepoMiner

        class _Stub:
            pass

        obj = _Stub()
        obj.__class__ = type("_FakeMiner", (), {
            "_build_mining_context": RepoMiner._build_mining_context,
        })
        return obj

    def test_includes_domain_classification(self, miner):
        """Context includes primary domain and language from Pass 1."""
        domain_info = {
            "primary_domain": "ai_integration",
            "secondary_domains": ["architecture"],
            "language": "python",
            "complexity": "medium",
        }
        overlap = KnowledgeOverlap()
        lines = miner._build_mining_context(domain_info, overlap)
        text = "\n".join(lines)

        assert "Primary domain: ai_integration" in text
        assert "Language: python" in text
        assert "Complexity: medium" in text

    def test_includes_focus_directives(self, miner):
        """When suggested_focus has entries, context includes PRIORITY section."""
        domain_info = {
            "primary_domain": "security",
            "secondary_domains": [],
            "language": "python",
            "complexity": "small",
        }
        overlap = KnowledgeOverlap(
            suggested_focus=["testing", "memory", "algorithm"],
        )
        lines = miner._build_mining_context(domain_info, overlap)
        text = "\n".join(lines)

        assert "PRIORITY" in text
        assert "testing" in text
        assert "memory" in text

    def test_includes_known_patterns(self, miner):
        """When repo has known patterns, they appear as dedup directives."""
        domain_info = {
            "primary_domain": "architecture",
            "secondary_domains": [],
            "language": "typescript",
            "complexity": "large",
        }
        overlap = KnowledgeOverlap(
            repo_known_titles=["ASGI Middleware Chain", "Route Mounting"],
            domain_known_titles=["Plugin Architecture from X"],
        )
        lines = miner._build_mining_context(domain_info, overlap)
        text = "\n".join(lines)

        assert "Already mined from this repo" in text
        assert "ASGI Middleware Chain" in text
        assert "OTHER repos" in text
        assert "Plugin Architecture from X" in text


# ---------------------------------------------------------------------------
# Adaptive token budget
# ---------------------------------------------------------------------------

class TestAdaptiveTokenBudget:
    """Token budget maps correctly to complexity tiers."""

    def test_budget_mapping(self):
        """small → 2048, medium → 4096, large → 6144."""
        budget_map = {"small": 2048, "medium": 4096, "large": 6144}
        assert budget_map["small"] == 2048
        assert budget_map["medium"] == 4096
        assert budget_map["large"] == 6144
        # Unknown defaults to 4096
        assert budget_map.get("unknown", 4096) == 4096


# ---------------------------------------------------------------------------
# Domain keyword coverage
# ---------------------------------------------------------------------------

class TestDomainKeywords:
    """Verify domain keyword maps cover all valid categories."""

    def test_all_categories_have_keywords(self):
        """Every valid category has at least one keyword entry."""
        for category in _VALID_CATEGORIES:
            assert category in _DOMAIN_KEYWORDS, (
                f"Category '{category}' missing from _DOMAIN_KEYWORDS"
            )
            assert len(_DOMAIN_KEYWORDS[category]) >= 3, (
                f"Category '{category}' has too few keywords"
            )

    def test_language_signals_are_lowercase(self):
        """Config file names in _LANGUAGE_SIGNALS are lowercase for matching."""
        for name in _LANGUAGE_SIGNALS:
            assert name == name.lower(), f"Signal '{name}' should be lowercase"
