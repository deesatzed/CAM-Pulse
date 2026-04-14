from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from claw.security.policy_tools import run_critical_slot_policy_checks


@pytest.mark.asyncio
async def test_policy_tools_uses_repo_local_semgrep_config_and_docker_runner(tmp_path: Path):
    workspace = tmp_path
    (workspace / "security").mkdir()
    (workspace / "security" / "semgrep.yml").write_text("rules: []\n", encoding="utf-8")
    (workspace / "scripts").mkdir()
    runner = workspace / "scripts" / "camseq_semgrep.sh"
    runner.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    runner.chmod(0o755)
    target = workspace / "app.py"
    target.write_text("print('hi')\n", encoding="utf-8")

    async def fake_run(args: list[str]):
        if args[0].endswith("camseq_semgrep.sh"):
            return 0, '{"results":[]}', ""
        return 0, "", ""

    with patch("claw.security.policy_tools.shutil.which") as which, patch(
        "claw.security.policy_tools._run_command",
        side_effect=fake_run,
    ):
        which.side_effect = lambda name: "/usr/bin/docker" if name == "docker" else None
        result = await run_critical_slot_policy_checks(str(workspace), [str(target)])

    assert result["semgrep"]["status"] == "pass"


@pytest.mark.asyncio
async def test_policy_tools_defers_codeql_when_not_installed(tmp_path: Path):
    workspace = tmp_path
    (workspace / "security").mkdir()
    (workspace / "security" / "semgrep.yml").write_text("rules: []\n", encoding="utf-8")

    with patch("claw.security.policy_tools.shutil.which", return_value=None):
        result = await run_critical_slot_policy_checks(str(workspace), [])

    assert result["codeql"]["status"] == "deferred"
    assert "deferred" in result["codeql"]["details"][0]
