"""Tests for the CLI module."""
import subprocess
import sys
import pytest
from app.cli import main, create_parser


class TestCLI:
    """Test CLI functionality."""

    def test_version_exit_code(self):
        """Test that --version returns exit code 0."""
        result = subprocess.run(
            [sys.executable, "-m", "app.cli", "--version"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "medcss-modernizer" in result.stdout

    def test_help_exit_code(self):
        """Test that --help returns exit code 0."""
        result = subprocess.run(
            [sys.executable, "-m", "app.cli", "--help"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Generate modernization reports" in result.stdout

    def test_invalid_argument_exit_code(self):
        """Test that invalid arguments return non-zero exit code."""
        result = subprocess.run(
            [sys.executable, "-m", "app.cli", "--invalid"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        # argparse may report unknown args or missing required args first
        assert (
            "unrecognized arguments" in result.stderr
            or "invalid" in result.stderr.lower()
            or "required" in result.stderr.lower()
        )

    def test_missing_required_args(self):
        """Test that missing required args returns non-zero exit code."""
        result = subprocess.run(
            [sys.executable, "-m", "app.cli"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "required" in result.stderr.lower()

    def test_main_function_with_help(self):
        """Test main function with --help flag."""
        # main should return 0 for help
        ret = main(["--help"])
        assert ret == 0

    def test_main_function_with_version(self):
        """Test main function with --version flag."""
        ret = main(["--version"])
        assert ret == 0

    def test_main_function_with_invalid_args(self):
        """Test main function with invalid arguments."""
        ret = main(["--invalid"])
        assert ret != 0

    def test_parser_creation(self):
        """Test that parser is created correctly."""
        parser = create_parser()
        assert parser.prog == "medcss-modernizer"
        # Test that required args are present
        args = parser.parse_args([
            "--site", "test site",
            "--purpose", "test purpose",
            "--ideas", "test ideas",
        ])
        assert args.site == "test site"
        assert args.purpose == "test purpose"
        assert args.ideas == "test ideas"
        assert args.out == "modernization_report.md"
        assert args.html_out == "landing_page.html"
