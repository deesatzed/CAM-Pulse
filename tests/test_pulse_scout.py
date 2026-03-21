"""Tests for CAM-PULSE X-Scout URL extraction and normalization."""

from claw.pulse.scout import XScout
from claw.pulse.models import PulseDiscovery


class TestExtractGithubUrls:
    def test_extracts_single_url(self):
        text = "Check out https://github.com/anthropics/claude-code for the CLI tool"
        urls = XScout.extract_github_urls(text)
        assert urls == ["https://github.com/anthropics/claude-code"]

    def test_extracts_multiple_urls(self):
        text = """
        Found these repos:
        - https://github.com/openai/whisper
        - https://github.com/huggingface/transformers
        - https://github.com/langchain-ai/langchain
        """
        urls = XScout.extract_github_urls(text)
        assert len(urls) == 3
        assert "https://github.com/openai/whisper" in urls
        assert "https://github.com/huggingface/transformers" in urls
        assert "https://github.com/langchain-ai/langchain" in urls

    def test_deduplicates_urls(self):
        text = """
        https://github.com/user/repo mentioned twice
        also https://github.com/user/repo here again
        """
        urls = XScout.extract_github_urls(text)
        assert len(urls) == 1

    def test_skips_non_repo_paths(self):
        text = """
        https://github.com/topics/python
        https://github.com/explore
        https://github.com/trending
        https://github.com/settings
        """
        urls = XScout.extract_github_urls(text)
        assert urls == []

    def test_strips_git_suffix(self):
        text = "Clone https://github.com/user/repo.git for the code"
        urls = XScout.extract_github_urls(text)
        assert urls == ["https://github.com/user/repo"]

    def test_strips_trailing_punctuation(self):
        text = "See https://github.com/user/repo, and https://github.com/user/repo2."
        urls = XScout.extract_github_urls(text)
        assert len(urls) == 2
        assert "https://github.com/user/repo" in urls
        assert "https://github.com/user/repo2" in urls

    def test_handles_url_without_scheme(self):
        text = "Visit github.com/owner/myproject for details"
        urls = XScout.extract_github_urls(text)
        assert urls == ["https://github.com/owner/myproject"]

    def test_empty_text(self):
        assert XScout.extract_github_urls("") == []

    def test_no_github_urls(self):
        text = "Check out gitlab.com/user/repo instead"
        assert XScout.extract_github_urls(text) == []


class TestCanonicalGithubUrl:
    def test_basic_normalization(self):
        assert XScout.canonical_github_url("https://github.com/User/Repo") == "https://github.com/user/repo"

    def test_strips_git_suffix(self):
        assert XScout.canonical_github_url("https://github.com/user/repo.git") == "https://github.com/user/repo"

    def test_strips_deep_paths(self):
        url = "https://github.com/user/repo/tree/main/src"
        assert XScout.canonical_github_url(url) == "https://github.com/user/repo"

    def test_strips_query_and_fragment(self):
        url = "https://github.com/user/repo?tab=readme#install"
        assert XScout.canonical_github_url(url) == "https://github.com/user/repo"

    def test_strips_trailing_slash(self):
        assert XScout.canonical_github_url("https://github.com/user/repo/") == "https://github.com/user/repo"

    def test_lowercase(self):
        assert XScout.canonical_github_url("https://github.com/OpenAI/Whisper") == "https://github.com/openai/whisper"


class TestExtractHandleNearUrl:
    def test_finds_handle_before_url(self):
        text = "@developer just shared https://github.com/dev/tool"
        handle = XScout._extract_handle_near_url(text, "https://github.com/dev/tool")
        assert handle == "developer"

    def test_no_handle_found(self):
        text = "No handle here https://github.com/dev/tool"
        handle = XScout._extract_handle_near_url(text, "https://github.com/dev/tool")
        assert handle == ""

    def test_url_not_in_text(self):
        text = "some text without the url"
        handle = XScout._extract_handle_near_url(text, "https://github.com/dev/tool")
        assert handle == ""

    def test_closest_handle_picked(self):
        text = "@first some text @second then https://github.com/dev/tool"
        handle = XScout._extract_handle_near_url(text, "https://github.com/dev/tool")
        assert handle == "second"


class TestXScoutCheckApiKey:
    def test_no_key_set(self, monkeypatch):
        from claw.core.config import PulseConfig
        monkeypatch.delenv("XAI_API_KEY", raising=False)
        config = PulseConfig(xai_model="grok-3")
        scout = XScout(config)
        ok, msg = scout.check_api_key()
        assert ok is False
        assert "not set" in msg

    def test_no_model_configured(self, monkeypatch):
        from claw.core.config import PulseConfig
        monkeypatch.setenv("XAI_API_KEY", "test-key-123")
        config = PulseConfig(xai_model="")
        scout = XScout(config)
        ok, msg = scout.check_api_key()
        assert ok is False
        assert "not configured" in msg

    def test_key_and_model_set(self, monkeypatch):
        from claw.core.config import PulseConfig
        monkeypatch.setenv("XAI_API_KEY", "test-key-12345678")
        config = PulseConfig(xai_model="grok-3")
        scout = XScout(config)
        ok, msg = scout.check_api_key()
        assert ok is True
        assert "test-key" in msg
        assert "grok-3" in msg


class TestExtractDiscoveriesFromResponse:
    def test_parses_text_content(self, monkeypatch):
        from claw.core.config import PulseConfig
        monkeypatch.setenv("XAI_API_KEY", "test")
        config = PulseConfig(xai_model="grok-3")
        scout = XScout(config)

        response = {
            "output": [
                {
                    "content": [
                        {"text": "Found https://github.com/cool/project — an AI agent framework"}
                    ]
                }
            ]
        }
        discoveries = scout._extract_discoveries_from_response(response, "AI agent", "scan123")
        assert len(discoveries) == 1
        assert discoveries[0].canonical_url == "https://github.com/cool/project"
        assert discoveries[0].keywords_matched == ["AI agent"]
        assert discoveries[0].scan_id == "scan123"

    def test_parses_string_content(self, monkeypatch):
        from claw.core.config import PulseConfig
        monkeypatch.setenv("XAI_API_KEY", "test")
        config = PulseConfig(xai_model="grok-3")
        scout = XScout(config)

        response = {
            "output": [
                {"content": "Here's https://github.com/owner/repo1 and https://github.com/owner/repo2"}
            ]
        }
        discoveries = scout._extract_discoveries_from_response(response, "tool", "s1")
        assert len(discoveries) == 2

    def test_parses_top_level_text(self, monkeypatch):
        from claw.core.config import PulseConfig
        monkeypatch.setenv("XAI_API_KEY", "test")
        config = PulseConfig(xai_model="grok-3")
        scout = XScout(config)

        response = {
            "output": [],
            "text": "Check https://github.com/user/repo"
        }
        discoveries = scout._extract_discoveries_from_response(response, "kw", "s2")
        assert len(discoveries) == 1

    def test_empty_response(self, monkeypatch):
        from claw.core.config import PulseConfig
        monkeypatch.setenv("XAI_API_KEY", "test")
        config = PulseConfig(xai_model="grok-3")
        scout = XScout(config)

        response = {"output": []}
        discoveries = scout._extract_discoveries_from_response(response, "kw", "s3")
        assert discoveries == []
