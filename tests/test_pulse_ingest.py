"""Tests for cam pulse ingest — URL normalization and prescreened ingestion."""

from claw.cli import _normalize_github_url


class TestNormalizeGithubUrl:
    def test_basic_url(self):
        assert _normalize_github_url("https://github.com/owner/repo") == "https://github.com/owner/repo"

    def test_trailing_slash(self):
        assert _normalize_github_url("https://github.com/owner/repo/") == "https://github.com/owner/repo"

    def test_dot_git_suffix(self):
        assert _normalize_github_url("https://github.com/owner/repo.git") == "https://github.com/owner/repo"

    def test_uppercase_normalized(self):
        assert _normalize_github_url("https://github.com/Owner/Repo") == "https://github.com/owner/repo"

    def test_www_prefix(self):
        assert _normalize_github_url("https://www.github.com/owner/repo") == "https://github.com/owner/repo"

    def test_query_params_stripped(self):
        assert _normalize_github_url("https://github.com/owner/repo?tab=readme") == "https://github.com/owner/repo"

    def test_fragment_stripped(self):
        assert _normalize_github_url("https://github.com/owner/repo#readme") == "https://github.com/owner/repo"

    def test_extra_path_segments(self):
        assert _normalize_github_url("https://github.com/owner/repo/tree/main/src") == "https://github.com/owner/repo"

    def test_invalid_not_github(self):
        assert _normalize_github_url("https://gitlab.com/owner/repo") is None

    def test_invalid_no_repo(self):
        assert _normalize_github_url("https://github.com/owner") is None

    def test_invalid_empty(self):
        assert _normalize_github_url("") is None

    def test_hyphen_underscore_dot(self):
        assert _normalize_github_url("https://github.com/0xK3vin/MegaMemory") == "https://github.com/0xk3vin/megamemory"

    def test_heroui(self):
        assert _normalize_github_url("https://github.com/heroui-inc/heroui") == "https://github.com/heroui-inc/heroui"

    def test_claude_peers_mcp(self):
        assert _normalize_github_url("https://github.com/louislva/claude-peers-mcp") == "https://github.com/louislva/claude-peers-mcp"

    def test_whitespace_stripped(self):
        assert _normalize_github_url("  https://github.com/owner/repo  ") == "https://github.com/owner/repo"
