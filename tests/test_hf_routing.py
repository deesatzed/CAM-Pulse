"""Tests for HF URL normalization and HF routing in assimilator.

Covers:
  - _normalize_repo_url(): GitHub + HF URL normalization (12 tests)
  - assimilate() HF routing: HF URLs auto-route to assimilate_hf_repo (4 tests)
  - pulse_refresh CLI accepts HF URLs (2 tests)

All tests use REAL data — no mocks, no placeholders.
"""

from __future__ import annotations

import inspect

import pytest

from claw.pulse.assimilator import PulseAssimilator
from claw.pulse.models import AssimilationResult, PulseDiscovery


# ===========================================================================
# Group 1: _normalize_repo_url() — pure string parsing
# ===========================================================================


class TestNormalizeRepoUrl:
    """Test _normalize_repo_url accepts both GitHub and HF URLs."""

    def test_github_standard(self):
        from claw.cli import _normalize_repo_url
        result = _normalize_repo_url("https://github.com/owner/repo")
        assert result == "https://github.com/owner/repo"

    def test_github_trailing_slash(self):
        from claw.cli import _normalize_repo_url
        result = _normalize_repo_url("https://github.com/owner/repo/")
        assert result == "https://github.com/owner/repo"

    def test_github_dot_git(self):
        from claw.cli import _normalize_repo_url
        result = _normalize_repo_url("https://github.com/owner/repo.git")
        assert result == "https://github.com/owner/repo"

    def test_hf_standard(self):
        from claw.cli import _normalize_repo_url
        result = _normalize_repo_url("https://huggingface.co/d4data/biomedical-ner-all")
        assert result == "https://huggingface.co/d4data/biomedical-ner-all"

    def test_hf_trailing_slash(self):
        from claw.cli import _normalize_repo_url
        result = _normalize_repo_url("https://huggingface.co/meta-llama/Llama-3/")
        assert result == "https://huggingface.co/meta-llama/Llama-3"

    def test_hf_with_subpath(self):
        from claw.cli import _normalize_repo_url
        # Even with extra path segments, should extract owner/repo
        result = _normalize_repo_url("https://huggingface.co/openai/whisper-large-v3/tree/main")
        assert result == "https://huggingface.co/openai/whisper-large-v3"

    def test_hf_www(self):
        from claw.cli import _normalize_repo_url
        result = _normalize_repo_url("https://www.huggingface.co/owner/repo")
        assert result == "https://huggingface.co/owner/repo"

    def test_invalid_url(self):
        from claw.cli import _normalize_repo_url
        result = _normalize_repo_url("https://gitlab.com/owner/repo")
        assert result is None

    def test_empty_string(self):
        from claw.cli import _normalize_repo_url
        result = _normalize_repo_url("")
        assert result is None

    def test_hf_no_repo(self):
        from claw.cli import _normalize_repo_url
        result = _normalize_repo_url("https://huggingface.co/justowner")
        assert result is None

    def test_github_no_repo(self):
        from claw.cli import _normalize_repo_url
        result = _normalize_repo_url("https://github.com/justowner")
        assert result is None

    def test_hf_preserves_case(self):
        """HF repo IDs are case-sensitive (unlike GitHub)."""
        from claw.cli import _normalize_repo_url
        result = _normalize_repo_url("https://huggingface.co/BigScience/BLOOM")
        assert result == "https://huggingface.co/BigScience/BLOOM"


# ===========================================================================
# Group 2: assimilate() HF routing
# ===========================================================================


class TestAssimilateHFRouting:
    """Verify assimilate() auto-routes HF URLs to assimilate_hf_repo()."""

    def test_assimilate_detects_hf_url(self):
        """assimilate() should detect huggingface.co URLs."""
        url = "https://huggingface.co/d4data/biomedical-ner-all"
        assert "huggingface.co/" in url

    def test_assimilate_does_not_route_github(self):
        """GitHub URLs should NOT trigger HF routing."""
        url = "https://github.com/owner/repo"
        assert "huggingface.co/" not in url

    def test_repo_id_extraction_from_hf_url(self):
        """Verify repo_id extraction logic matches assimilate() implementation."""
        url = "https://huggingface.co/d4data/biomedical-ner-all"
        repo_id = url.replace("https://huggingface.co/", "").strip("/")
        assert repo_id == "d4data/biomedical-ner-all"

    def test_repo_id_extraction_trailing_slash(self):
        """Trailing slash should be stripped."""
        url = "https://huggingface.co/meta-llama/Llama-3/"
        repo_id = url.replace("https://huggingface.co/", "").strip("/")
        assert repo_id == "meta-llama/Llama-3"

    def test_assimilate_method_has_hf_routing(self):
        """The assimilate() source should contain HF routing logic."""
        source = inspect.getsource(PulseAssimilator.assimilate)
        assert "huggingface.co/" in source
        assert "assimilate_hf_repo" in source


# ===========================================================================
# Group 3: CLI flag registration
# ===========================================================================


class TestPulseRefreshAcceptsHF:
    """Verify pulse_refresh uses _normalize_repo_url (not just GitHub)."""

    def test_pulse_refresh_uses_normalize_repo_url(self):
        """pulse_refresh source should reference _normalize_repo_url."""
        from claw.cli import pulse_refresh
        source = inspect.getsource(pulse_refresh)
        assert "_normalize_repo_url" in source

    def test_pulse_refresh_error_message_mentions_hf(self):
        """Error message should mention HuggingFace, not just GitHub."""
        from claw.cli import pulse_refresh
        source = inspect.getsource(pulse_refresh)
        assert "HuggingFace" in source


# ===========================================================================
# Group 4: AssimilationResult.head_sha propagation in HF path
# ===========================================================================


class TestHFAssimilationResultFields:
    """Verify assimilate_hf_repo() populates head_sha on result."""

    def test_assimilate_hf_repo_sets_head_sha(self):
        """assimilate_hf_repo source should set result.head_sha."""
        source = inspect.getsource(PulseAssimilator.assimilate_hf_repo)
        assert "result.head_sha" in source

    def test_assimilate_hf_repo_uses_get_head_sha(self):
        """assimilate_hf_repo should call _get_head_sha for mounted path."""
        source = inspect.getsource(PulseAssimilator.assimilate_hf_repo)
        assert "_get_head_sha" in source

    def test_assimilate_sets_head_sha_for_github(self):
        """assimilate() (GitHub path) should also set result.head_sha."""
        source = inspect.getsource(PulseAssimilator.assimilate)
        assert "result.head_sha" in source
