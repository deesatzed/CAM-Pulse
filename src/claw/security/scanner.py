"""Pre-assimilation secret scanning for CAM-PULSE.

Primary gate: TruffleHog subprocess scan on cloned/mounted repos.
Fallback: Regex-based scanning when TruffleHog binary is unavailable.
Secondary gate: File-level filter for serialize_repo() exclusion.

Usage:
    scanner = SecretScanner()
    result = await scanner.scan(Path("/path/to/cloned/repo"))
    if result.has_critical:
        # Block assimilation
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger("claw.security.scanner")


# ---------------------------------------------------------------------------
# Severity levels
# ---------------------------------------------------------------------------

class ScanSeverity:
    """Severity of a detected secret."""

    CRITICAL = "critical"  # Verified or high-value (private keys, Stripe, GCP SA)
    HIGH = "high"          # Known detector pattern, unverified
    MEDIUM = "medium"      # Regex fallback or generic pattern
    LOW = "low"            # Entropy-based or very generic


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class SecretFinding:
    """A single detected secret in a scanned repo."""

    file_path: str           # Relative path within the repo
    line: int                # Line number (0 if unknown)
    detector_name: str       # e.g. "Github", "AWS", "Slack"
    severity: str            # ScanSeverity value
    verified: bool           # True if TruffleHog verified the credential is live
    redacted_match: str      # First/last 4 chars only, middle redacted
    source: str              # "trufflehog" or "regex"


@dataclass
class ScanResult:
    """Aggregate result from scanning a repo for secrets."""

    path: str
    findings: list[SecretFinding] = field(default_factory=list)
    scanner_used: str = ""    # "trufflehog" or "regex"
    scan_duration_seconds: float = 0.0
    error: Optional[str] = None

    @property
    def has_critical(self) -> bool:
        return any(f.severity == ScanSeverity.CRITICAL for f in self.findings)

    @property
    def has_any(self) -> bool:
        return len(self.findings) > 0

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == ScanSeverity.CRITICAL)

    @property
    def file_paths_with_secrets(self) -> set[str]:
        """Set of relative file paths containing any secret findings."""
        return {f.file_path for f in self.findings}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _redact_raw(raw: str) -> str:
    """Redact a raw secret value, keeping first/last 4 chars."""
    if len(raw) <= 10:
        return "***REDACTED***"
    return raw[:4] + "..." + raw[-4:]


def _trufflehog_available() -> bool:
    """Check if trufflehog binary is on PATH."""
    return shutil.which("trufflehog") is not None


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

# TruffleHog detector names that indicate critical (high-value) secrets
_CRITICAL_DETECTORS: frozenset = frozenset({
    "AWS", "AWSSessionKey", "Azure", "GCP",
    "Github", "GitHubApp", "GitLab",
    "Slack", "SlackWebhook",
    "Stripe", "StripeApiKey",
    "SendGrid", "Twilio",
    "PrivateKey",
    "Shopify",
    "DigitalOcean",
    "Heroku",
    "NpmToken",
    "PyPI",
    "DockerHub",
})

# Code file extensions for regex fallback (matches miner.py)
_SCAN_EXTENSIONS: set[str] = {
    ".py", ".js", ".ts", ".tsx", ".jsx",
    ".go", ".rs", ".java",
    ".md", ".yaml", ".yml", ".toml", ".json", ".sql",
    ".env", ".cfg", ".ini", ".conf", ".sh", ".bash",
    ".rb", ".php", ".cs", ".kt", ".swift",
}

# Directories to skip during regex fallback
_SCAN_SKIP_DIRS: set[str] = {
    ".git", "node_modules", "__pycache__", ".venv",
    "venv", "dist", "build", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", "egg-info",
    ".next", ".nuxt", "coverage", ".cache",
    "target",
}

# Regex fallback patterns (used when trufflehog binary unavailable)
_FALLBACK_PATTERNS: list[tuple[str, re.Pattern, str]] = [
    ("AWS_AccessKey", re.compile(r"AKIA[0-9A-Z]{16}"), ScanSeverity.HIGH),
    ("GitHub_PAT", re.compile(r"ghp_[A-Za-z0-9]{36,}"), ScanSeverity.HIGH),
    ("GitHub_OAuth", re.compile(r"gho_[A-Za-z0-9]{36,}"), ScanSeverity.HIGH),
    ("Slack_Token", re.compile(r"xox[bporas]-[A-Za-z0-9\-]{10,}"), ScanSeverity.HIGH),
    ("OpenAI_Key", re.compile(r"sk-[a-zA-Z0-9]{20,}"), ScanSeverity.MEDIUM),
    ("Bearer_Token", re.compile(r"Bearer\s+[a-zA-Z0-9._\-]{20,}"), ScanSeverity.MEDIUM),
    ("PrivateKey_Header", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----"), ScanSeverity.CRITICAL),
    ("SendGrid_Key", re.compile(r"SG\.[A-Za-z0-9_\-]{22,}\.[A-Za-z0-9_\-]{22,}"), ScanSeverity.HIGH),
    ("Stripe_LiveKey", re.compile(r"sk_live_[A-Za-z0-9]{20,}"), ScanSeverity.CRITICAL),
    ("GCP_ServiceAccount", re.compile(r'"type"\s*:\s*"service_account"'), ScanSeverity.CRITICAL),
    ("Generic_Secret", re.compile(r"[A-Z_]{4,}_SECRET\s*=\s*['\"][^\s'\"]{10,}['\"]"), ScanSeverity.MEDIUM),
]


class SecretScanner:
    """Pre-assimilation secret scanner.

    Primary: Runs ``trufflehog filesystem <path> --json --no-verification``
    Fallback: Regex patterns when TruffleHog binary is unavailable.
    """

    def __init__(
        self,
        timeout_seconds: int = 60,
        no_verification: bool = True,
        fail_on_critical: bool = True,
    ):
        self.timeout_seconds = timeout_seconds
        self.no_verification = no_verification
        self.fail_on_critical = fail_on_critical
        self._trufflehog_available = _trufflehog_available()

    async def scan(self, path: Path) -> ScanResult:
        """Scan a directory for secrets.

        Uses TruffleHog if available, falls back to regex patterns.
        """
        if self._trufflehog_available:
            return await self._scan_trufflehog(path)
        logger.warning("trufflehog binary not found, using regex fallback")
        return self._scan_regex(path)

    async def _scan_trufflehog(self, path: Path) -> ScanResult:
        """Run TruffleHog subprocess and parse JSON output."""
        start = time.monotonic()
        result = ScanResult(path=str(path), scanner_used="trufflehog")

        cmd = ["trufflehog", "filesystem", str(path), "--json"]
        if self.no_verification:
            cmd.append("--no-verification")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            result.error = f"TruffleHog timed out after {self.timeout_seconds}s"
            result.scan_duration_seconds = time.monotonic() - start
            return result
        except FileNotFoundError:
            result.error = "trufflehog binary not found"
            result.scan_duration_seconds = time.monotonic() - start
            return result

        # Parse NDJSON output (one JSON object per line)
        for line in stdout.decode("utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                finding = self._parse_trufflehog_finding(obj, path)
                if finding:
                    result.findings.append(finding)
            except json.JSONDecodeError:
                logger.debug("Skipping non-JSON TruffleHog output: %s", line[:100])

        result.scan_duration_seconds = time.monotonic() - start
        logger.info(
            "TruffleHog scan of %s: %d findings (%d critical) in %.1fs",
            path, len(result.findings), result.critical_count,
            result.scan_duration_seconds,
        )
        return result

    @staticmethod
    def _parse_trufflehog_finding(
        obj: dict, base_path: Path
    ) -> Optional[SecretFinding]:
        """Parse a single TruffleHog JSON finding into a SecretFinding."""
        detector_name = obj.get("DetectorName", "Unknown")
        verified = obj.get("Verified", False)
        raw = obj.get("Raw", "")

        # Determine severity
        if verified:
            severity = ScanSeverity.CRITICAL
        elif detector_name in _CRITICAL_DETECTORS:
            severity = ScanSeverity.HIGH
        else:
            severity = ScanSeverity.MEDIUM

        # Extract file path
        source_meta = obj.get("SourceMetadata", {}).get("Data", {})
        fs_meta = source_meta.get("Filesystem", {})
        abs_file = fs_meta.get("file", "")
        line_num = fs_meta.get("line", 0)

        # Convert to relative path
        try:
            rel_path = str(Path(abs_file).relative_to(base_path))
        except ValueError:
            rel_path = abs_file

        return SecretFinding(
            file_path=rel_path,
            line=line_num,
            detector_name=detector_name,
            severity=severity,
            verified=verified,
            redacted_match=_redact_raw(raw),
            source="trufflehog",
        )

    @staticmethod
    def _scan_regex(path: Path) -> ScanResult:
        """Fallback regex scan when TruffleHog is not available."""
        start = time.monotonic()
        result = ScanResult(path=str(path), scanner_used="regex")

        root = Path(path)
        if not root.is_dir():
            result.error = f"Path is not a directory: {path}"
            result.scan_duration_seconds = time.monotonic() - start
            return result

        for filepath in root.rglob("*"):
            if not filepath.is_file():
                continue
            rel = filepath.relative_to(root)
            # Skip excluded directories
            if any(part in _SCAN_SKIP_DIRS for part in rel.parts):
                continue
            # Only scan known file extensions
            if filepath.suffix.lower() not in _SCAN_EXTENSIONS:
                continue

            try:
                content = filepath.read_text(encoding="utf-8", errors="replace")
            except (OSError, PermissionError):
                continue

            for detector_name, pattern, severity in _FALLBACK_PATTERNS:
                for match in pattern.finditer(content):
                    line_num = content[:match.start()].count("\n") + 1
                    result.findings.append(SecretFinding(
                        file_path=str(rel),
                        line=line_num,
                        detector_name=detector_name,
                        severity=severity,
                        verified=False,
                        redacted_match=_redact_raw(match.group()),
                        source="regex",
                    ))

        result.scan_duration_seconds = time.monotonic() - start
        logger.info(
            "Regex scan of %s: %d findings (%d critical) in %.1fs",
            path, len(result.findings), result.critical_count,
            result.scan_duration_seconds,
        )
        return result
