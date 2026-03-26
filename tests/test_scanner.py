"""Tests for the pre-assimilation secret scanner.

Covers:
    - Redaction helper
    - ScanResult data model properties
    - TruffleHog subprocess scanner (skipped if binary not installed)
    - Regex fallback scanner (all 11 patterns)
    - TruffleHog JSON parsing (_parse_trufflehog_finding static method)
    - Gate 1 behaviour (critical vs. non-critical decisions)
    - Gate 2 serializer exclusion (miner.serialize_repo exclude_files)
    - SecurityConfig defaults from config schema

All tests use REAL tmp dirs with REAL files -- no mocks, no placeholders.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import stat
from pathlib import Path

import pytest

from claw.security.scanner import (
    ScanResult,
    ScanSeverity,
    SecretFinding,
    SecretScanner,
    _redact_raw,
    _trufflehog_available,
)

# ---------------------------------------------------------------------------
# Conditional skip for TruffleHog-dependent tests
# ---------------------------------------------------------------------------

requires_trufflehog = pytest.mark.skipif(
    not shutil.which("trufflehog"),
    reason="trufflehog binary not installed",
)


# ===========================================================================
# Helpers
# ===========================================================================

def _make_finding(
    severity: str = ScanSeverity.MEDIUM,
    file_path: str = "src/app.py",
    line: int = 1,
    detector: str = "TestDetector",
    source: str = "regex",
) -> SecretFinding:
    """Build a SecretFinding with sensible defaults for data-model tests."""
    return SecretFinding(
        file_path=file_path,
        line=line,
        detector_name=detector,
        severity=severity,
        verified=False,
        redacted_match="***REDACTED***",
        source=source,
    )


def _write_secret_file(
    directory: Path,
    rel_path: str,
    content: str,
) -> Path:
    """Write a file inside *directory* at the given relative path."""
    target = directory / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


# ===========================================================================
# TestRedaction
# ===========================================================================

class TestRedaction:
    """Tests for _redact_raw() helper."""

    def test_redact_short(self):
        """Strings with 10 or fewer chars are fully replaced."""
        assert _redact_raw("abc") == "***REDACTED***"
        assert _redact_raw("1234567890") == "***REDACTED***"

    def test_redact_long(self):
        """Strings longer than 10 chars keep first 4 + '...' + last 4."""
        raw = "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef12"
        result = _redact_raw(raw)
        assert result.startswith("ghp_")
        assert result.endswith("f12")  # last 4 chars = "f12" with preceding char
        # The '...' must be in the middle
        assert "..." in result
        # Total length: 4 + 3 + 4 = 11
        assert len(result) == 11

    def test_redact_medium_boundary(self):
        """Exactly 10 chars is still fully redacted (boundary)."""
        assert _redact_raw("ABCDEFGHIJ") == "***REDACTED***"

    def test_redact_eleven_chars(self):
        """11 chars is the first length that shows partial content."""
        result = _redact_raw("ABCDEFGHIJk")
        assert result == "ABCD...HIJk"


# ===========================================================================
# TestScanResult
# ===========================================================================

class TestScanResult:
    """Tests for ScanResult computed properties."""

    def test_has_critical_true(self):
        result = ScanResult(
            path="/tmp/repo",
            findings=[_make_finding(severity=ScanSeverity.CRITICAL)],
        )
        assert result.has_critical is True
        assert result.critical_count == 1

    def test_has_critical_false(self):
        result = ScanResult(
            path="/tmp/repo",
            findings=[
                _make_finding(severity=ScanSeverity.MEDIUM),
                _make_finding(severity=ScanSeverity.HIGH),
            ],
        )
        assert result.has_critical is False
        assert result.critical_count == 0

    def test_file_paths_set(self):
        result = ScanResult(
            path="/tmp/repo",
            findings=[
                _make_finding(file_path="src/app.py"),
                _make_finding(file_path="config/settings.py"),
                _make_finding(file_path="src/app.py"),  # duplicate path
            ],
        )
        assert result.file_paths_with_secrets == {"src/app.py", "config/settings.py"}
        assert len(result.file_paths_with_secrets) == 2

    def test_empty_result(self):
        result = ScanResult(path="/tmp/repo")
        assert result.has_critical is False
        assert result.has_any is False
        assert result.critical_count == 0
        assert result.file_paths_with_secrets == set()


# ===========================================================================
# TestTruffleHogScanner
# ===========================================================================

class TestTruffleHogScanner:
    """Tests that exercise the real TruffleHog subprocess path.

    Skipped when trufflehog binary is not installed.
    """

    @requires_trufflehog
    async def test_clean_directory(self, tmp_path: Path):
        """An empty directory produces zero findings."""
        scanner = SecretScanner()
        result = await scanner.scan(tmp_path)
        assert result.scanner_used == "trufflehog"
        assert len(result.findings) == 0
        assert result.error is None

    @requires_trufflehog
    async def test_scanner_uses_trufflehog_when_available(self):
        """When trufflehog is on PATH the scanner flags it as available."""
        scanner = SecretScanner()
        assert scanner._trufflehog_available is True

    @requires_trufflehog
    async def test_nonexistent_path_handled(self):
        """Scanning a path that does not exist completes without crash."""
        scanner = SecretScanner()
        result = await scanner.scan(Path("/tmp/nonexistent_path_test_scanner_xyz"))
        # TruffleHog may report an error or simply return 0 findings.
        # Either way the call must not raise.
        assert isinstance(result, ScanResult)

    @requires_trufflehog
    async def test_relative_paths_in_findings(self, tmp_path: Path):
        """If TruffleHog reports a finding, file_path must be relative to scan root."""
        # Write a real AWS-like key pattern. TruffleHog is strict --
        # it may or may not detect synthetic patterns. We verify the
        # result structure regardless.
        _write_secret_file(
            tmp_path,
            "creds.py",
            'AWS_KEY = "AKIAIOSFODNN7EXAMPLE1"\n',
        )
        scanner = SecretScanner()
        result = await scanner.scan(tmp_path)
        assert result.scanner_used == "trufflehog"
        for finding in result.findings:
            # Must NOT start with the tmp_path prefix
            assert not finding.file_path.startswith(str(tmp_path)), (
                f"Expected relative path, got absolute: {finding.file_path}"
            )

    @requires_trufflehog
    async def test_scan_duration_recorded(self, tmp_path: Path):
        """scan_duration_seconds must be populated after a scan."""
        scanner = SecretScanner()
        result = await scanner.scan(tmp_path)
        assert result.scan_duration_seconds >= 0

    @requires_trufflehog
    async def test_no_verification_flag(self, tmp_path: Path):
        """When no_verification=True, scan still works (default behaviour)."""
        scanner = SecretScanner(no_verification=True)
        result = await scanner.scan(tmp_path)
        assert result.error is None

    @requires_trufflehog
    async def test_trufflehog_available_function(self):
        """Module-level _trufflehog_available() returns True when binary is on PATH."""
        assert _trufflehog_available() is True


# ===========================================================================
# TestParseTruffleHogFinding
# ===========================================================================

class TestParseTruffleHogFinding:
    """Test _parse_trufflehog_finding static method directly with crafted dicts.

    This covers the JSON parsing logic that TruffleHog subprocess output
    would produce, without needing real leaked secrets.
    """

    def test_verified_finding_is_critical(self):
        """A verified finding is always severity CRITICAL."""
        obj = {
            "DetectorName": "AWS",
            "Verified": True,
            "Raw": "AKIAIOSFODNN7LONGEXAMPLEKEYVALUE",
            "SourceMetadata": {
                "Data": {
                    "Filesystem": {
                        "file": "/tmp/repo/creds.py",
                        "line": 10,
                    }
                }
            },
        }
        finding = SecretScanner._parse_trufflehog_finding(obj, Path("/tmp/repo"))
        assert finding is not None
        assert finding.severity == ScanSeverity.CRITICAL
        assert finding.verified is True
        assert finding.detector_name == "AWS"
        assert finding.file_path == "creds.py"
        assert finding.line == 10
        assert finding.source == "trufflehog"
        # Redacted match should preserve first/last 4
        assert "..." in finding.redacted_match

    def test_unverified_critical_detector_is_high(self):
        """Unverified finding from a critical detector gets HIGH severity."""
        obj = {
            "DetectorName": "Stripe",
            "Verified": False,
            "Raw": "sk" + "_live_" + "ABCDEFGHIJKLMNOPQRST",
            "SourceMetadata": {
                "Data": {
                    "Filesystem": {
                        "file": "/tmp/repo/pay.py",
                        "line": 5,
                    }
                }
            },
        }
        finding = SecretScanner._parse_trufflehog_finding(obj, Path("/tmp/repo"))
        assert finding is not None
        assert finding.severity == ScanSeverity.HIGH
        assert finding.verified is False
        assert finding.detector_name == "Stripe"

    def test_unverified_noncritical_detector_is_medium(self):
        """Unverified finding from a non-critical detector gets MEDIUM severity."""
        obj = {
            "DetectorName": "SomeCustomDetector",
            "Verified": False,
            "Raw": "some-secret-value-that-is-long-enough",
            "SourceMetadata": {
                "Data": {
                    "Filesystem": {
                        "file": "/tmp/repo/misc.py",
                        "line": 1,
                    }
                }
            },
        }
        finding = SecretScanner._parse_trufflehog_finding(obj, Path("/tmp/repo"))
        assert finding is not None
        assert finding.severity == ScanSeverity.MEDIUM

    def test_relative_path_conversion(self):
        """Absolute file path is converted to relative from base_path."""
        obj = {
            "DetectorName": "Github",
            "Verified": False,
            "Raw": "ghp_TestTokenValue12345678901234567890",
            "SourceMetadata": {
                "Data": {
                    "Filesystem": {
                        "file": "/home/user/project/src/config.py",
                        "line": 42,
                    }
                }
            },
        }
        finding = SecretScanner._parse_trufflehog_finding(
            obj, Path("/home/user/project")
        )
        assert finding is not None
        assert finding.file_path == "src/config.py"

    def test_path_not_relative_to_base(self):
        """When file path cannot be made relative, it's kept as-is."""
        obj = {
            "DetectorName": "AWS",
            "Verified": False,
            "Raw": "AKIAIOSFODNN7LONGEXAMPLEKEYVALUE",
            "SourceMetadata": {
                "Data": {
                    "Filesystem": {
                        "file": "/completely/different/path.py",
                        "line": 1,
                    }
                }
            },
        }
        finding = SecretScanner._parse_trufflehog_finding(
            obj, Path("/tmp/repo")
        )
        assert finding is not None
        assert finding.file_path == "/completely/different/path.py"

    def test_missing_source_metadata(self):
        """Missing SourceMetadata fields default to empty/zero."""
        obj = {
            "DetectorName": "Unknown",
            "Verified": False,
            "Raw": "short",
        }
        finding = SecretScanner._parse_trufflehog_finding(obj, Path("/tmp/repo"))
        assert finding is not None
        assert finding.file_path == ""
        assert finding.line == 0
        assert finding.redacted_match == "***REDACTED***"  # short raw = fully redacted

    def test_short_raw_fully_redacted(self):
        """Short Raw values (<= 10 chars) are fully redacted."""
        obj = {
            "DetectorName": "AWS",
            "Verified": True,
            "Raw": "tiny",
            "SourceMetadata": {"Data": {"Filesystem": {"file": "/tmp/repo/x.py", "line": 1}}},
        }
        finding = SecretScanner._parse_trufflehog_finding(obj, Path("/tmp/repo"))
        assert finding is not None
        assert finding.redacted_match == "***REDACTED***"

    def test_all_critical_detectors_get_high(self):
        """All known critical detector names produce HIGH severity when unverified."""
        from claw.security.scanner import _CRITICAL_DETECTORS

        for detector in _CRITICAL_DETECTORS:
            obj = {
                "DetectorName": detector,
                "Verified": False,
                "Raw": "some-long-enough-credential-value",
                "SourceMetadata": {
                    "Data": {
                        "Filesystem": {"file": "/tmp/repo/f.py", "line": 1}
                    }
                },
            }
            finding = SecretScanner._parse_trufflehog_finding(obj, Path("/tmp/repo"))
            assert finding is not None
            assert finding.severity == ScanSeverity.HIGH, (
                f"Detector {detector} should be HIGH when unverified"
            )


# ===========================================================================
# TestRegexFallback
# ===========================================================================

class TestRegexFallback:
    """Tests for the regex-based fallback scanner.

    Forces regex path by setting scanner._trufflehog_available = False.
    """

    async def _scan_regex(self, tmp_path: Path) -> ScanResult:
        """Create a scanner forced to regex mode and scan the tmp dir."""
        scanner = SecretScanner()
        scanner._trufflehog_available = False
        return await scanner.scan(tmp_path)

    async def test_aws_key(self, tmp_path: Path):
        _write_secret_file(tmp_path, "config.py", 'KEY = "AKIAIOSFODNN7EXAMPLE1"\n')
        result = await self._scan_regex(tmp_path)
        assert result.scanner_used == "regex"
        assert result.has_any is True
        aws = [f for f in result.findings if f.detector_name == "AWS_AccessKey"]
        assert len(aws) >= 1
        assert aws[0].severity == ScanSeverity.HIGH
        assert aws[0].source == "regex"

    async def test_github_pat(self, tmp_path: Path):
        # ghp_ + 36 alphanumeric characters
        pat = "ghp_" + "A" * 36
        _write_secret_file(tmp_path, "token.py", f'TOKEN = "{pat}"\n')
        result = await self._scan_regex(tmp_path)
        gh = [f for f in result.findings if f.detector_name == "GitHub_PAT"]
        assert len(gh) >= 1
        assert gh[0].severity == ScanSeverity.HIGH

    async def test_slack_token(self, tmp_path: Path):
        _write_secret_file(
            tmp_path,
            "slack.py",
            'SLACK = "xoxb-1234567890-abcdefghij"\n',
        )
        result = await self._scan_regex(tmp_path)
        slack = [f for f in result.findings if f.detector_name == "Slack_Token"]
        assert len(slack) >= 1
        assert slack[0].severity == ScanSeverity.HIGH

    async def test_stripe_live_key(self, tmp_path: Path):
        key = "sk_live_" + "A" * 24
        _write_secret_file(tmp_path, "billing.py", f'STRIPE_KEY = "{key}"\n')
        result = await self._scan_regex(tmp_path)
        stripe = [f for f in result.findings if f.detector_name == "Stripe_LiveKey"]
        assert len(stripe) >= 1
        assert stripe[0].severity == ScanSeverity.CRITICAL

    async def test_sendgrid_key(self, tmp_path: Path):
        # SG. + 22+ chars . + 22+ chars
        key = "SG." + "a" * 22 + "." + "B" * 22
        _write_secret_file(tmp_path, "email.py", f'SG_KEY = "{key}"\n')
        result = await self._scan_regex(tmp_path)
        sg = [f for f in result.findings if f.detector_name == "SendGrid_Key"]
        assert len(sg) >= 1
        assert sg[0].severity == ScanSeverity.HIGH

    async def test_pem_private_key(self, tmp_path: Path):
        _write_secret_file(
            tmp_path,
            "key.py",
            '# some code\nPEM = "-----BEGIN RSA PRIVATE KEY-----"\n',
        )
        result = await self._scan_regex(tmp_path)
        pem = [f for f in result.findings if f.detector_name == "PrivateKey_Header"]
        assert len(pem) >= 1
        assert pem[0].severity == ScanSeverity.CRITICAL

    async def test_gcp_service_account(self, tmp_path: Path):
        sa_json = '{\n  "type": "service_account",\n  "project_id": "my-project"\n}\n'
        _write_secret_file(tmp_path, "gcp_sa.json", sa_json)
        result = await self._scan_regex(tmp_path)
        gcp = [f for f in result.findings if f.detector_name == "GCP_ServiceAccount"]
        assert len(gcp) >= 1
        assert gcp[0].severity == ScanSeverity.CRITICAL

    async def test_generic_secret_env(self, tmp_path: Path):
        _write_secret_file(
            tmp_path,
            "settings.py",
            'DEPLOY_SECRET = "mysupersecretvalue123"\n',
        )
        result = await self._scan_regex(tmp_path)
        gen = [f for f in result.findings if f.detector_name == "Generic_Secret"]
        assert len(gen) >= 1
        assert gen[0].severity == ScanSeverity.MEDIUM

    async def test_skip_dirs(self, tmp_path: Path):
        """Secrets inside __pycache__/ (or other skip dirs) must NOT be detected."""
        _write_secret_file(
            tmp_path,
            "__pycache__/foo.py",
            'KEY = "AKIAIOSFODNN7EXAMPLE1"\n',
        )
        result = await self._scan_regex(tmp_path)
        assert result.has_any is False, (
            f"Expected 0 findings in __pycache__, got {result.findings}"
        )

    async def test_line_numbers_correct(self, tmp_path: Path):
        """Secret placed on line 5 must be reported as line 5."""
        content = "# line 1\n# line 2\n# line 3\n# line 4\nAKIAIOSFODNN7EXAMPLE1\n"
        _write_secret_file(tmp_path, "deep.py", content)
        result = await self._scan_regex(tmp_path)
        aws = [f for f in result.findings if f.detector_name == "AWS_AccessKey"]
        assert len(aws) >= 1
        assert aws[0].line == 5

    async def test_github_oauth_token(self, tmp_path: Path):
        """GitHub OAuth token pattern gho_ + 36+ chars."""
        pat = "gho_" + "B" * 36
        _write_secret_file(tmp_path, "oauth.py", f'OAUTH = "{pat}"\n')
        result = await self._scan_regex(tmp_path)
        gh = [f for f in result.findings if f.detector_name == "GitHub_OAuth"]
        assert len(gh) >= 1
        assert gh[0].severity == ScanSeverity.HIGH

    async def test_openai_key(self, tmp_path: Path):
        """OpenAI key pattern sk- + 20+ alphanumeric chars."""
        key = "sk-" + "a" * 24
        _write_secret_file(tmp_path, "openai.py", f'OPENAI_KEY = "{key}"\n')
        result = await self._scan_regex(tmp_path)
        oai = [f for f in result.findings if f.detector_name == "OpenAI_Key"]
        assert len(oai) >= 1
        assert oai[0].severity == ScanSeverity.MEDIUM

    async def test_bearer_token(self, tmp_path: Path):
        """Bearer token pattern."""
        token = "Bearer " + "a" * 24
        _write_secret_file(tmp_path, "auth.py", f'AUTH = "{token}"\n')
        result = await self._scan_regex(tmp_path)
        bt = [f for f in result.findings if f.detector_name == "Bearer_Token"]
        assert len(bt) >= 1
        assert bt[0].severity == ScanSeverity.MEDIUM

    async def test_pem_ec_private_key(self, tmp_path: Path):
        """EC PRIVATE KEY variant also detected."""
        _write_secret_file(
            tmp_path,
            "ec_key.py",
            'PEM = "-----BEGIN EC PRIVATE KEY-----"\n',
        )
        result = await self._scan_regex(tmp_path)
        pem = [f for f in result.findings if f.detector_name == "PrivateKey_Header"]
        assert len(pem) >= 1
        assert pem[0].severity == ScanSeverity.CRITICAL

    async def test_non_scannable_extension_skipped(self, tmp_path: Path):
        """A .png file containing a secret pattern must NOT be scanned."""
        _write_secret_file(tmp_path, "image.png", "AKIAIOSFODNN7EXAMPLE1\n")
        result = await self._scan_regex(tmp_path)
        assert result.has_any is False

    async def test_multiple_findings_single_file(self, tmp_path: Path):
        """Multiple secret patterns in one file produce multiple findings."""
        content = (
            'AWS_KEY = "AKIAIOSFODNN7EXAMPLE1"\n'
            'STRIPE = "' + "sk" + "_live_" + "ABCDEFGHIJKLMNOPQRSTwxyz" + '"\n'
        )
        _write_secret_file(tmp_path, "multi.py", content)
        result = await self._scan_regex(tmp_path)
        detectors = {f.detector_name for f in result.findings}
        assert "AWS_AccessKey" in detectors
        assert "Stripe_LiveKey" in detectors

    async def test_regex_scan_not_a_directory(self):
        """Passing a non-directory path sets result.error."""
        result = SecretScanner._scan_regex(Path("/tmp/nonexistent_path_scanner_xyz"))
        assert result.error is not None
        assert "not a directory" in result.error

    async def test_redacted_match_present(self, tmp_path: Path):
        """Each finding has a non-empty redacted_match."""
        key = "sk_live_" + "Z" * 24
        _write_secret_file(tmp_path, "pay.py", f'KEY = "{key}"\n')
        result = await self._scan_regex(tmp_path)
        assert result.has_any is True
        for f in result.findings:
            assert f.redacted_match  # non-empty
            assert "***REDACTED***" in f.redacted_match or "..." in f.redacted_match

    async def test_env_extension_file_scanned(self, tmp_path: Path):
        """A file with .env extension (e.g. config.env) is scanned.

        Note: bare '.env' files are NOT scanned because Path('.env').suffix
        returns '' (empty string). The .env entry in _SCAN_EXTENSIONS matches
        files like 'config.env' or 'production.env' where .env is the suffix.
        """
        _write_secret_file(
            tmp_path,
            "config.env",
            'DEPLOY_SECRET = "mysupersecretvalue123"\n',
        )
        result = await self._scan_regex(tmp_path)
        gen = [f for f in result.findings if f.detector_name == "Generic_Secret"]
        assert len(gen) >= 1

    async def test_bare_dotenv_not_scanned_by_suffix(self, tmp_path: Path):
        """Bare .env dotfile has no suffix -- scanner skips it via extension filter.

        This documents a known edge case: Path('.env').suffix == '' (empty).
        The _SCAN_EXTENSIONS set includes '.env' for files like 'config.env'.
        """
        _write_secret_file(
            tmp_path,
            ".env",
            'DEPLOY_SECRET = "mysupersecretvalue123"\n',
        )
        result = await self._scan_regex(tmp_path)
        gen = [f for f in result.findings if f.detector_name == "Generic_Secret"]
        assert len(gen) == 0, (
            "Bare .env should NOT be scanned -- Path('.env').suffix is empty"
        )

    async def test_nested_skip_dir(self, tmp_path: Path):
        """Secrets in nested skip dirs like src/node_modules/ are skipped."""
        _write_secret_file(
            tmp_path,
            "src/node_modules/pkg/index.js",
            'var key = "AKIAIOSFODNN7EXAMPLE1";\n',
        )
        result = await self._scan_regex(tmp_path)
        assert result.has_any is False

    async def test_scan_duration_recorded(self, tmp_path: Path):
        """Regex scan records a non-negative duration."""
        _write_secret_file(tmp_path, "empty.py", "# nothing\n")
        result = await self._scan_regex(tmp_path)
        assert result.scan_duration_seconds >= 0

    async def test_finding_file_path_is_relative(self, tmp_path: Path):
        """Regex findings must have relative file paths, not absolute."""
        _write_secret_file(tmp_path, "secrets.py", "AKIAIOSFODNN7EXAMPLE1\n")
        result = await self._scan_regex(tmp_path)
        for f in result.findings:
            assert not f.file_path.startswith("/"), (
                f"Expected relative path, got: {f.file_path}"
            )

    async def test_unreadable_file_skipped(self, tmp_path: Path):
        """Files that cannot be read (PermissionError) are silently skipped."""
        target = _write_secret_file(tmp_path, "locked.py", "AKIAIOSFODNN7EXAMPLE1\n")
        # Remove read permission
        target.chmod(0o000)
        try:
            result = await self._scan_regex(tmp_path)
            # Should not crash, and should skip the unreadable file
            assert result.error is None
        finally:
            # Restore permissions for cleanup
            target.chmod(stat.S_IRUSR | stat.S_IWUSR)


# ===========================================================================
# TestGate1Behavior
# ===========================================================================

class TestGate1Behavior:
    """Test ScanResult-based decision logic (Gate 1 -- block on critical)."""

    def test_clean_result_allows_mining(self):
        """Zero findings means has_critical is False -- mining proceeds."""
        result = ScanResult(path="/tmp/repo", findings=[], scanner_used="regex")
        assert result.has_critical is False
        assert result.has_any is False

    def test_critical_result_blocks(self):
        """CRITICAL finding sets has_critical True -- mining should be blocked."""
        result = ScanResult(
            path="/tmp/repo",
            findings=[_make_finding(severity=ScanSeverity.CRITICAL)],
        )
        assert result.has_critical is True

    def test_noncritical_allows(self):
        """Only HIGH/MEDIUM findings -- has_critical is False, mining may proceed."""
        result = ScanResult(
            path="/tmp/repo",
            findings=[
                _make_finding(severity=ScanSeverity.HIGH),
                _make_finding(severity=ScanSeverity.MEDIUM),
                _make_finding(severity=ScanSeverity.LOW),
            ],
        )
        assert result.has_critical is False
        assert result.has_any is True

    async def test_scan_respects_trufflehog_flag(self, tmp_path: Path):
        """When _trufflehog_available is False, scanner falls back to regex."""
        scanner = SecretScanner()
        scanner._trufflehog_available = False
        result = await scanner.scan(tmp_path)
        assert result.scanner_used == "regex"

    def test_mixed_severities_critical_detected(self):
        """Even one CRITICAL among many non-critical triggers has_critical."""
        result = ScanResult(
            path="/tmp/repo",
            findings=[
                _make_finding(severity=ScanSeverity.LOW),
                _make_finding(severity=ScanSeverity.MEDIUM),
                _make_finding(severity=ScanSeverity.CRITICAL),
                _make_finding(severity=ScanSeverity.HIGH),
            ],
        )
        assert result.has_critical is True
        assert result.critical_count == 1


# ===========================================================================
# TestGate2Serializer
# ===========================================================================

class TestGate2Serializer:
    """Test serialize_repo exclude_files parameter (Gate 2 -- file exclusion)."""

    def test_exclude_files_skipped(self, tmp_path: Path):
        """Files in exclude_files set are omitted from serialized output."""
        _write_secret_file(tmp_path, "main.py", "def main(): pass\n")
        _write_secret_file(tmp_path, "config.py", "SECRET = 'shhh'\n")
        _write_secret_file(tmp_path, "utils.py", "def helper(): pass\n")

        from claw.miner import serialize_repo

        content, count = serialize_repo(tmp_path, exclude_files={"config.py"})
        assert "--- FILE: config.py ---" not in content
        assert "--- FILE: main.py ---" in content
        assert "--- FILE: utils.py ---" in content
        assert count == 2

    def test_no_excludes_normal(self, tmp_path: Path):
        """Without exclude_files all eligible files are serialized."""
        _write_secret_file(tmp_path, "main.py", "def main(): pass\n")
        _write_secret_file(tmp_path, "config.py", "x = 1\n")

        from claw.miner import serialize_repo

        content, count = serialize_repo(tmp_path)
        assert "--- FILE: main.py ---" in content
        assert "--- FILE: config.py ---" in content
        assert count == 2

    def test_exclude_nonexistent_file(self, tmp_path: Path):
        """Excluding a file that does not exist causes no error."""
        _write_secret_file(tmp_path, "main.py", "def main(): pass\n")

        from claw.miner import serialize_repo

        content, count = serialize_repo(
            tmp_path,
            exclude_files={"nonexistent.py"},
        )
        assert "--- FILE: main.py ---" in content
        assert count == 1

    def test_exclude_nested_path(self, tmp_path: Path):
        """Excluding a nested path like 'src/secrets.py' works correctly."""
        _write_secret_file(tmp_path, "src/secrets.py", "KEY = 'abc'\n")
        _write_secret_file(tmp_path, "src/main.py", "def run(): pass\n")

        from claw.miner import serialize_repo

        content, count = serialize_repo(
            tmp_path,
            exclude_files={"src/secrets.py"},
        )
        assert "--- FILE: src/secrets.py ---" not in content
        assert "--- FILE: src/main.py ---" in content
        assert count == 1


# ===========================================================================
# TestConfigFields
# ===========================================================================

class TestConfigFields:
    """Test SecurityConfig fields for secret scanning."""

    def test_security_config_defaults(self):
        """SecurityConfig has correct defaults for all 5 secret_scan fields."""
        from claw.core.config import SecurityConfig

        cfg = SecurityConfig()
        assert cfg.secret_scan_enabled is True
        assert cfg.secret_scan_fail_on_critical is True
        assert cfg.secret_scan_timeout_seconds == 60
        assert cfg.secret_scan_no_verification is True
        assert cfg.secret_scan_filter_in_serializer is True

    def test_config_loads_from_toml(self):
        """load_config() returns a ClawConfig with security scanner fields populated."""
        from claw.core.config import load_config

        config = load_config()
        sec = config.security
        assert hasattr(sec, "secret_scan_enabled")
        assert hasattr(sec, "secret_scan_fail_on_critical")
        assert hasattr(sec, "secret_scan_timeout_seconds")
        assert hasattr(sec, "secret_scan_no_verification")
        assert hasattr(sec, "secret_scan_filter_in_serializer")
        # Verify they are the expected types
        assert isinstance(sec.secret_scan_enabled, bool)
        assert isinstance(sec.secret_scan_timeout_seconds, int)


# ===========================================================================
# TestScanSeverity
# ===========================================================================

class TestScanSeverity:
    """Test ScanSeverity constants."""

    def test_severity_values(self):
        assert ScanSeverity.CRITICAL == "critical"
        assert ScanSeverity.HIGH == "high"
        assert ScanSeverity.MEDIUM == "medium"
        assert ScanSeverity.LOW == "low"


# ===========================================================================
# TestSecretFinding
# ===========================================================================

class TestSecretFinding:
    """Test SecretFinding dataclass construction."""

    def test_finding_fields(self):
        finding = SecretFinding(
            file_path="src/app.py",
            line=42,
            detector_name="AWS_AccessKey",
            severity=ScanSeverity.HIGH,
            verified=False,
            redacted_match="AKIA...PLE1",
            source="regex",
        )
        assert finding.file_path == "src/app.py"
        assert finding.line == 42
        assert finding.detector_name == "AWS_AccessKey"
        assert finding.severity == "high"
        assert finding.verified is False
        assert finding.redacted_match == "AKIA...PLE1"
        assert finding.source == "regex"

    def test_finding_verified_trufflehog(self):
        finding = SecretFinding(
            file_path="creds.yaml",
            line=10,
            detector_name="Stripe",
            severity=ScanSeverity.CRITICAL,
            verified=True,
            redacted_match="sk_l...wxyz",
            source="trufflehog",
        )
        assert finding.verified is True
        assert finding.source == "trufflehog"


# ===========================================================================
# TestScannerInit
# ===========================================================================

class TestScannerInit:
    """Test SecretScanner constructor and configuration."""

    def test_default_init(self):
        scanner = SecretScanner()
        assert scanner.timeout_seconds == 60
        assert scanner.no_verification is True
        assert scanner.fail_on_critical is True
        assert isinstance(scanner._trufflehog_available, bool)

    def test_custom_init(self):
        scanner = SecretScanner(
            timeout_seconds=120,
            no_verification=False,
            fail_on_critical=False,
        )
        assert scanner.timeout_seconds == 120
        assert scanner.no_verification is False
        assert scanner.fail_on_critical is False

    async def test_scan_routing_regex(self, tmp_path: Path):
        """When _trufflehog_available=False, scan() routes to _scan_regex."""
        scanner = SecretScanner()
        scanner._trufflehog_available = False
        result = await scanner.scan(tmp_path)
        assert result.scanner_used == "regex"

    @requires_trufflehog
    async def test_scan_routing_trufflehog(self, tmp_path: Path):
        """When _trufflehog_available=True, scan() routes to _scan_trufflehog."""
        scanner = SecretScanner()
        assert scanner._trufflehog_available is True
        result = await scanner.scan(tmp_path)
        assert result.scanner_used == "trufflehog"


# ===========================================================================
# TestEdgeCases
# ===========================================================================

class TestEdgeCases:
    """Edge cases and boundary conditions."""

    async def test_empty_file(self, tmp_path: Path):
        """An empty .py file produces no findings."""
        _write_secret_file(tmp_path, "empty.py", "")
        scanner = SecretScanner()
        scanner._trufflehog_available = False
        result = await scanner.scan(tmp_path)
        assert result.has_any is False

    async def test_binary_like_content(self, tmp_path: Path):
        """File with non-UTF8 bytes does not crash the scanner."""
        target = tmp_path / "weird.py"
        target.write_bytes(b"\x00\x01\x02AKIAIOSFODNN7EXAMPLE1\xff\xfe")
        scanner = SecretScanner()
        scanner._trufflehog_available = False
        result = await scanner.scan(tmp_path)
        # Should parse with errors="replace" and still detect the key
        aws = [f for f in result.findings if f.detector_name == "AWS_AccessKey"]
        assert len(aws) >= 1

    async def test_deeply_nested_file(self, tmp_path: Path):
        """Secret in a deeply nested directory is found."""
        _write_secret_file(
            tmp_path,
            "a/b/c/d/e/secret.py",
            "AKIAIOSFODNN7EXAMPLE1\n",
        )
        scanner = SecretScanner()
        scanner._trufflehog_available = False
        result = await scanner.scan(tmp_path)
        aws = [f for f in result.findings if f.detector_name == "AWS_AccessKey"]
        assert len(aws) >= 1
        # Verify the path is relative and includes all parts
        assert aws[0].file_path == "a/b/c/d/e/secret.py"

    async def test_multiple_skip_dirs(self, tmp_path: Path):
        """Secrets in various skip directories are all ignored."""
        for skip_dir in [".git", "node_modules", ".venv", "dist", "build"]:
            _write_secret_file(
                tmp_path,
                f"{skip_dir}/leaked.py",
                "AKIAIOSFODNN7EXAMPLE1\n",
            )
        # Also add a non-skip file to confirm scanning works
        _write_secret_file(tmp_path, "src/real.py", "# clean\n")
        scanner = SecretScanner()
        scanner._trufflehog_available = False
        result = await scanner.scan(tmp_path)
        # None of the skip-dir files should produce findings
        for f in result.findings:
            parts = Path(f.file_path).parts
            skip_found = any(
                p in {".git", "node_modules", ".venv", "dist", "build"} for p in parts
            )
            assert not skip_found, f"Finding in skip dir: {f.file_path}"

    async def test_generic_secret_single_quotes(self, tmp_path: Path):
        """Generic secret with single quotes is also detected."""
        _write_secret_file(
            tmp_path,
            "env.py",
            "MY_APP_SECRET = 'averylongsecretvalue99'\n",
        )
        scanner = SecretScanner()
        scanner._trufflehog_available = False
        result = await scanner.scan(tmp_path)
        gen = [f for f in result.findings if f.detector_name == "Generic_Secret"]
        assert len(gen) >= 1

    async def test_generic_secret_too_short_value_not_detected(self, tmp_path: Path):
        """Generic secret pattern requires 10+ char value; shorter is not flagged."""
        _write_secret_file(
            tmp_path,
            "short.py",
            'MY_APP_SECRET = "short"\n',  # only 5 chars
        )
        scanner = SecretScanner()
        scanner._trufflehog_available = False
        result = await scanner.scan(tmp_path)
        gen = [f for f in result.findings if f.detector_name == "Generic_Secret"]
        assert len(gen) == 0

    async def test_private_key_openssh(self, tmp_path: Path):
        """OPENSSH PRIVATE KEY variant is also detected."""
        _write_secret_file(
            tmp_path,
            "key.sh",
            'echo "-----BEGIN OPENSSH PRIVATE KEY-----"\n',
        )
        scanner = SecretScanner()
        scanner._trufflehog_available = False
        result = await scanner.scan(tmp_path)
        pem = [f for f in result.findings if f.detector_name == "PrivateKey_Header"]
        assert len(pem) >= 1

    async def test_private_key_bare(self, tmp_path: Path):
        """Bare PRIVATE KEY (no RSA/EC/DSA/OPENSSH prefix) is also detected."""
        _write_secret_file(
            tmp_path,
            "bare.py",
            'KEY = "-----BEGIN PRIVATE KEY-----"\n',
        )
        scanner = SecretScanner()
        scanner._trufflehog_available = False
        result = await scanner.scan(tmp_path)
        pem = [f for f in result.findings if f.detector_name == "PrivateKey_Header"]
        assert len(pem) >= 1
