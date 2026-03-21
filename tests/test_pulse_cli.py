"""Tests for CAM-PULSE CLI command surface."""

from typer.testing import CliRunner

from claw.cli import app

runner = CliRunner()


class TestPulseCLI:
    def test_pulse_help(self):
        result = runner.invoke(app, ["pulse", "--help"])
        assert result.exit_code == 0
        assert "CAM-PULSE" in result.stdout
        assert "scan" in result.stdout
        assert "daemon" in result.stdout
        assert "status" in result.stdout
        assert "discoveries" in result.stdout
        assert "report" in result.stdout
        assert "preflight" in result.stdout

    def test_pulse_scan_help(self):
        result = runner.invoke(app, ["pulse", "scan", "--help"])
        assert result.exit_code == 0
        assert "--keywords" in result.stdout
        assert "--from-date" in result.stdout
        assert "--dry-run" in result.stdout

    def test_pulse_daemon_help(self):
        result = runner.invoke(app, ["pulse", "daemon", "--help"])
        assert result.exit_code == 0
        assert "--interval" in result.stdout

    def test_pulse_status_help(self):
        result = runner.invoke(app, ["pulse", "status", "--help"])
        assert result.exit_code == 0

    def test_pulse_discoveries_help(self):
        result = runner.invoke(app, ["pulse", "discoveries", "--help"])
        assert result.exit_code == 0
        assert "--limit" in result.stdout

    def test_pulse_scans_help(self):
        result = runner.invoke(app, ["pulse", "scans", "--help"])
        assert result.exit_code == 0

    def test_pulse_report_help(self):
        result = runner.invoke(app, ["pulse", "report", "--help"])
        assert result.exit_code == 0
        assert "--date" in result.stdout

    def test_pulse_preflight_help(self):
        result = runner.invoke(app, ["pulse", "preflight", "--help"])
        assert result.exit_code == 0
