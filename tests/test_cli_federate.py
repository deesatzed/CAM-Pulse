"""Tests for the `cam federate` CLI command.

Tests the CLI integration layer using Typer's CliRunner with real config.
No mock, no placeholders, no cached responses.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from claw.cli._monolith import app
from claw.core.config import InstanceConfig, InstanceRegistryConfig
from claw.core.models import (
    CrossBrainMetrics,
    CrossLanguageReport,
    UniversalPattern,
)


runner = CliRunner()


class TestFederateCommand:

    def test_federate_shows_help(self):
        result = runner.invoke(app, ["federate", "--help"])
        assert result.exit_code == 0
        assert "cross-brain" in result.output.lower() or "Cross-brain" in result.output

    def test_federate_requires_query_argument(self):
        result = runner.invoke(app, ["federate"])
        assert result.exit_code != 0

    def test_federate_fails_without_federation_enabled(self):
        """With default config (federation disabled), should fail gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal claw.toml with federation disabled
            config_path = Path(tmpdir) / "claw.toml"
            config_path.write_text("""
[instances]
enabled = false
""")
            result = runner.invoke(app, [
                "federate", "security patterns",
                "--config", str(config_path),
            ])
            assert result.exit_code != 0
            assert "disabled" in result.output.lower() or "Federation" in result.output

    def test_federate_fails_without_siblings(self):
        """With federation enabled but no siblings, should fail gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "claw.toml"
            config_path.write_text("""
[instances]
enabled = true
""")
            result = runner.invoke(app, [
                "federate", "security patterns",
                "--config", str(config_path),
            ])
            assert result.exit_code != 0
            assert "sibling" in result.output.lower() or "No sibling" in result.output


class TestFederateWithRealGanglia:
    """Tests using real ganglion databases if present."""

    CLAW_TOML = Path("/Volumes/WS4TB/a_aSatzClaw/multiclaw/claw.toml")
    RUST_DB = Path("/Volumes/WS4TB/a_aSatzClaw/multiclaw/instances/rust/claw.db")
    GO_DB = Path("/Volumes/WS4TB/a_aSatzClaw/multiclaw/instances/go/claw.db")
    TS_DB = Path("/Volumes/WS4TB/a_aSatzClaw/multiclaw/instances/typescript/claw.db")

    @pytest.mark.skipif(
        not all(p.exists() for p in [CLAW_TOML, RUST_DB, GO_DB, TS_DB]),
        reason="Real config and ganglion DBs not present",
    )
    def test_federate_security_query(self):
        result = runner.invoke(app, [
            "federate",
            "design defense-in-depth security for a multi-tenant AI agent gateway",
            "--config", str(self.CLAW_TOML),
        ])
        assert result.exit_code == 0
        assert "Cross-Brain Pattern Atlas" in result.output
        assert "METRICS" in result.output

    @pytest.mark.skipif(
        not all(p.exists() for p in [CLAW_TOML, RUST_DB, GO_DB, TS_DB]),
        reason="Real config and ganglion DBs not present",
    )
    def test_federate_json_output(self):
        result = runner.invoke(app, [
            "federate",
            "security patterns",
            "--json",
            "--config", str(self.CLAW_TOML),
        ])
        assert result.exit_code == 0
        # Should be valid JSON
        output = result.output
        json_start = output.find('{')
        assert json_start >= 0, f"No JSON in output: {output[:200]}"
        data = json.loads(output[json_start:], strict=False)
        assert "query" in data
        assert "metrics" in data

    @pytest.mark.skipif(
        not all(p.exists() for p in [CLAW_TOML, RUST_DB, GO_DB, TS_DB]),
        reason="Real config and ganglion DBs not present",
    )
    def test_federate_with_trace_flag(self):
        result = runner.invoke(app, [
            "federate",
            "security patterns",
            "--trace",
            "--config", str(self.CLAW_TOML),
        ])
        assert result.exit_code == 0
        assert "Traces written" in result.output or "traces" in result.output.lower()

    @pytest.mark.skipif(
        not all(p.exists() for p in [CLAW_TOML, RUST_DB, GO_DB, TS_DB]),
        reason="Real config and ganglion DBs not present",
    )
    def test_federate_with_domains(self):
        result = runner.invoke(app, [
            "federate",
            "patterns",
            "--domains", "security,architecture",
            "--config", str(self.CLAW_TOML),
        ])
        assert result.exit_code == 0

    @pytest.mark.skipif(
        not all(p.exists() for p in [CLAW_TOML, RUST_DB, GO_DB, TS_DB]),
        reason="Real config and ganglion DBs not present",
    )
    def test_federate_architecture_query(self):
        result = runner.invoke(app, [
            "federate",
            "modular service architecture with middleware and extractors",
            "--config", str(self.CLAW_TOML),
        ])
        assert result.exit_code == 0
        assert "METRICS" in result.output
