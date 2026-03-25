"""Verifier for CLAW — 7-check audit gate on agent output.

Adapted from ralfed's Sentinel agent. Performs a separate audit pass on any
agent's TaskOutcome. If any check fails, the outcome is rejected and
violations are fed back to the agent for retry.

7 Checks + Metric Enforcement:
1. Dependency Jail — blocks unauthorized package imports in diff
2. Style Match — verifies code follows project conventions
3. Chaos Check — verifies edge case handling (no bare except, no eval/exec, no hardcoded credentials)
4. Placeholder Scan — rejects TODOs, stubs, NotImplementedError, FIXME, HACK, XXX
5. Drift Alignment — semantic similarity between task intent and output (using EmbeddingEngine)
6. Claim Validation — detects and verifies unsubstantiated claims
7. LLM Deep Review — optional LLM pass when all rule-based checks pass
+  Minimum Test Count — rejects builds with fewer tests than spec requires
+  Metric Expectations — enforces min_coverage_pct, min/max_files_changed, etc.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shlex
from pathlib import Path
from typing import Any, Optional

from claw.core.config import PromptLoader
from claw.core.models import (
    MetricExpectation,
    TaskContext,
    TaskOutcome,
    VerificationResult,
)
from claw.db.embeddings import EmbeddingEngine

logger = logging.getLogger("claw.verifier")


# ---------------------------------------------------------------------------
# Safety Enforcer keyword sets (from GrokFlow safety/enforcer.py via ralfed)
# ---------------------------------------------------------------------------

DESTRUCTIVE_KEYWORDS = {
    "delete", "drop", "remove", "destroy", "erase", "purge",
    "truncate", "clear", "wipe", "kill", "terminate", "shutdown",
}

CRITICAL_KEYWORDS = {
    "deploy", "publish", "release", "migrate", "upgrade",
    "downgrade", "restart", "reboot", "format",
}

# Protected path patterns — code should not modify these
PROTECTED_PATTERNS = [
    r'.*\.git/.*',
    r'.*\.env\b',
    r'.*\.ssh/.*',
    r'.*password.*',
    r'.*secret.*',
    r'.*credential.*',
    r'/etc/.*',
    r'/usr/.*',
]

# ---------------------------------------------------------------------------
# Claim definitions (from GrokFlow core/evidence.py via ralfed)
# ---------------------------------------------------------------------------

CLAIM_PATTERNS = [
    {"claims": ["production ready", "prod ready", "ready for production"], "evidence": "Full pipeline validated"},
    {"claims": ["tested", "tests pass", "all tests pass"], "evidence": "Tests exist and pass"},
    {"claims": ["fixed", "resolved", "bug fixed"], "evidence": "Repro steps no longer fail"},
    {"claims": ["done", "complete", "completed", "finished"], "evidence": "Acceptance criteria met"},
    {"claims": ["refactored", "refactor"], "evidence": "Behavior unchanged, tests pass"},
    {"claims": ["optimized", "faster", "performance improved"], "evidence": "Benchmark before/after"},
    {"claims": ["secure", "hardened"], "evidence": "Security scan clean"},
    {"claims": ["no side effects", "side-effect free"], "evidence": "Pure function verification"},
    {"claims": ["thread safe", "thread-safe"], "evidence": "Concurrency test evidence"},
    {"claims": ["backward compatible", "backwards compatible"], "evidence": "API compatibility test"},
]


def _scan_for_cam_runtime_imports(workspace_dir: Path) -> list[str]:
    hits: list[str] = []
    for path in workspace_dir.rglob("*.py"):
        try:
            rel = path.relative_to(workspace_dir)
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "import claw" in text or "from claw" in text:
            hits.append(str(rel))
            if len(hits) >= 10:
                break
    return hits

# ---------------------------------------------------------------------------
# Placeholder patterns
# ---------------------------------------------------------------------------

PLACEHOLDER_PATTERNS = [
    r'\bTODO\b',
    r'\bFIXME\b',
    r'\bHACK\b',
    r'\bXXX\b',
    r'\bpass\b\s*#',             # `pass  # placeholder`
    r'raise\s+NotImplementedError',
    r'\.\.\.\s*$',               # Ellipsis as implementation
    r'#\s*(?:implement|placeholder|stub)',
]

ALLOWED_ACCEPTANCE_COMMANDS = {
    "cargo",
    "go",
    "make",
    "mypy",
    "node",
    "npm",
    "npx",
    "pnpm",
    "poetry",
    "pytest",
    "python",
    "python3",
    "ruff",
    "tox",
    "uv",
    "yarn",
}

BLOCKED_SHELL_PATTERNS = ("&&", "||", "|", ";", "`", "$(")


class Verifier:
    """7-check audit gate, with optional LLM deep check.

    Accepts a TaskOutcome (from any of the 4 agents) and a TaskContext
    describing the task. Returns a VerificationResult with approved/rejected
    status, violations, and recommendations.

    Injected dependencies:
        embedding_engine: For drift alignment check (check 5).
        banned_dependencies: List of packages that must not appear in code.
        drift_threshold: Minimum cosine similarity for drift check (0.0-1.0).
        llm_client: Async LLM client (required for check 7).
    """

    _DEFAULT_DEEP_CHECK_PROMPT = (
        "Review this diff against the task. Does it fully solve the task? "
        "Return JSON: {\"verdict\": \"PASS\"|\"FAIL\", \"gaps\": [...], "
        "\"severity\": \"none\"|\"low\"|\"medium\"|\"high\"|\"critical\"}"
    )

    def __init__(
        self,
        embedding_engine: Optional[EmbeddingEngine] = None,
        banned_dependencies: Optional[list[str]] = None,
        drift_threshold: float = 0.40,
        llm_client: Optional[Any] = None,
        min_test_count: int = 0,
    ):
        self.embedding_engine = embedding_engine
        self.banned_dependencies = set(d.lower() for d in (banned_dependencies or []))
        self.drift_threshold = drift_threshold
        self.llm_client = llm_client
        self.min_test_count = min_test_count
        self._prompt_loader = PromptLoader()

    # ===================================================================
    # Main entry point
    # ===================================================================

    async def verify(
        self,
        outcome: TaskOutcome,
        task_context: TaskContext,
        workspace_dir: Optional[str] = None,
    ) -> VerificationResult:
        """Run all 7 audit checks on an agent's output.

        Args:
            outcome: The TaskOutcome produced by the agent.
            task_context: The TaskContext describing the task.
            workspace_dir: Optional path to the target repo (for test running).

        Returns:
            VerificationResult with approved/rejected, violations, recommendations.
        """
        task_desc = f"{task_context.task.title}: {task_context.task.description}"
        diff = outcome.diff
        approach_summary = outcome.approach_summary
        self_audit = outcome.self_audit

        all_violations: list[dict[str, str]] = []
        all_recommendations: list[str] = []

        # Run all 7 checks (6 rule-based + 1 optional LLM)
        checks: list[tuple[str, Any, tuple]] = [
            ("dependency_jail", self._check_dependency_jail, (diff,)),
            ("style_match", self._check_style_match, (diff,)),
            ("chaos_check", self._check_chaos, (diff,)),
            ("placeholder_scan", self._check_placeholders, (diff,)),
            ("drift_alignment", self._check_drift_alignment, (task_desc, approach_summary)),
            ("claim_validation", self._check_claims, (approach_summary, outcome, self_audit)),
        ]

        for check_name, check_fn, args in checks:
            try:
                violations, recommendations = await check_fn(*args)
                all_violations.extend(violations)
                all_recommendations.extend(recommendations)
                logger.debug("Check '%s': %d violations", check_name, len(violations))
            except Exception as e:
                logger.warning("Check '%s' failed: %s", check_name, e)
                all_recommendations.append(f"Check '{check_name}' could not be executed: {e}")

        # Optional 7th check: LLM deep review
        # Only runs when llm_client is configured AND all 6 rule-based checks passed
        tokens_used = 0
        if self.llm_client is not None and len(all_violations) == 0:
            deep_violations, deep_recommendations, tokens_used = await self._check_llm_deep(
                task_desc, approach_summary, diff
            )
            all_violations.extend(deep_violations)
            all_recommendations.extend(deep_recommendations)

        # Run tests if workspace_dir is provided and no violations so far
        tests_before: Optional[int] = None
        tests_after: Optional[int] = None
        full_test_output = ""
        if workspace_dir and len(all_violations) == 0:
            try:
                test_passed, test_output, test_count = await self.run_tests(workspace_dir)
                tests_after = test_count
                full_test_output = test_output
                if not test_passed:
                    all_violations.append({
                        "check": "test_execution",
                        "detail": f"Tests failed in workspace: {test_output[:500]}",
                    })
            except Exception as e:
                logger.warning("Test execution failed: %s", e)
                all_recommendations.append(f"Test execution could not be completed: {e}")

        # Check minimum test count requirement
        if tests_after is not None and len(all_violations) == 0:
            min_required = self._extract_minimum_test_requirement(task_context)
            if min_required > 0 and tests_after < min_required:
                all_violations.append({
                    "check": "minimum_test_count",
                    "detail": f"Insufficient tests: {tests_after} found, {min_required} required by spec.",
                })

        # Run coverage measurement if coverage metrics are expected
        metrics = self._collect_metric_expectations(task_context)
        has_coverage_metric = any(m.metric == "min_coverage_pct" for m in metrics)
        if has_coverage_metric and workspace_dir and len(all_violations) == 0:
            cov_output = await self._run_coverage(workspace_dir)
            if cov_output:
                full_test_output = full_test_output + "\n" + cov_output

        # Check metric expectations (coverage, file count, etc.)
        if len(all_violations) == 0:
            metric_violations, metric_recs = self._check_metric_expectations(
                task_context,
                tests_after=tests_after,
                test_output=full_test_output,
                files_changed=outcome.files_changed,
            )
            all_violations.extend(metric_violations)
            all_recommendations.extend(metric_recs)

        # Run explicit acceptance checks (if provided) after tests pass.
        acceptance_checks = list(task_context.task.acceptance_checks)
        if not acceptance_checks and task_context.action_template is not None:
            acceptance_checks = list(task_context.action_template.acceptance_checks)

        if acceptance_checks and len(all_violations) == 0:
            if not workspace_dir:
                all_recommendations.append(
                    "Acceptance checks were provided but workspace_dir was not set; skipped."
                )
            else:
                acc_violations, acc_recommendations = await self._run_acceptance_checks(
                    workspace_dir=workspace_dir,
                    acceptance_checks=acceptance_checks,
                )
                all_violations.extend(acc_violations)
                all_recommendations.extend(acc_recommendations)

        expectation_checks_ok = len([v for v in all_violations if v.get("check") in {"test_execution", "acceptance_checks"}]) == 0
        expectation_score, expectation_findings, expectation_violations, expectation_recommendations = (
            self._assess_expectation_match(
                task_context,
                workspace_dir=workspace_dir,
                acceptance_checks_ok=expectation_checks_ok,
            )
        )
        all_violations.extend(expectation_violations)
        all_recommendations.extend(expectation_recommendations)

        approved = len(all_violations) == 0

        # Compute a quality score (0.0-1.0) based on violations and recommendations
        quality_score = self._compute_quality_score(all_violations, all_recommendations)

        return VerificationResult(
            approved=approved,
            violations=all_violations,
            recommendations=all_recommendations,
            quality_score=quality_score,
            expectation_match_score=expectation_score,
            expectation_findings=expectation_findings,
            tests_before=tests_before,
            tests_after=tests_after,
            test_output=full_test_output,
        )

    def _assess_expectation_match(
        self,
        task_context: TaskContext,
        workspace_dir: Optional[str],
        acceptance_checks_ok: bool,
    ) -> tuple[Optional[float], list[str], list[dict[str, str]], list[str]]:
        contract = task_context.expectation_contract
        if contract is None:
            return None, [], [], []

        findings: list[str] = []
        violations: list[dict[str, str]] = []
        recommendations: list[str] = []
        matched = 0
        total = 0

        workspace = Path(workspace_dir) if workspace_dir else None
        repo_exists = bool(workspace and workspace.exists())
        repo_nonempty = bool(repo_exists and any(p.is_file() for p in workspace.rglob("*")))
        has_readme = bool(
            repo_exists and any((workspace / name).exists() for name in ("README.md", "README.rst", "README.txt", "README"))
        )
        has_cli = bool(
            repo_exists and (
                (workspace / "app" / "cli.py").exists()
                or (workspace / "src" / "app" / "cli.py").exists()
                or (workspace / "main.py").exists()
            )
        )
        cam_runtime_hits = _scan_for_cam_runtime_imports(workspace) if repo_exists and workspace else []

        def mark(clause: str, ok: bool, hard: bool = False) -> None:
            nonlocal matched, total
            total += 1
            if ok:
                matched += 1
                findings.append(f"MATCH {clause}")
            else:
                findings.append(f"GAP {clause}")
                if hard:
                    violations.append({"check": "expectation_contract", "detail": clause})
                else:
                    recommendations.append(f"Expectation gap: {clause}")

        for clause in contract.expected_outcome:
            text = clause.lower()
            if "acceptance checks pass" in text or "verifiable" in text:
                mark(clause, acceptance_checks_ok)
            elif "repository change" in text or "runnable standalone repository" in text or "requested capability" in text:
                mark(clause, repo_nonempty)
            else:
                mark(clause, repo_exists)

        for clause in contract.expected_ux:
            text = clause.lower()
            if "cli" in text or "help or usage" in text:
                mark(clause, has_cli)
            elif "documentation" in text or "operator" in text:
                mark(clause, has_readme)
            elif "preserved" in text:
                mark(clause, acceptance_checks_ok)
            else:
                mark(clause, repo_nonempty)

        for clause in contract.constraints:
            text = clause.lower()
            if "cam runtime" in text:
                mark(clause, len(cam_runtime_hits) == 0, hard=True)
            elif "materially change" in text:
                mark(clause, repo_nonempty, hard=True)
            else:
                mark(clause, True)

        if cam_runtime_hits:
            findings.append("GAP CAM runtime imports found in: " + ", ".join(cam_runtime_hits[:5]))

        score = round(matched / total, 3) if total else None
        return score, findings, violations, recommendations

    # ===================================================================
    # Check 1: Dependency Jail
    # ===================================================================

    async def _check_dependency_jail(
        self, diff: str
    ) -> tuple[list[dict[str, str]], list[str]]:
        """Block unauthorized package imports.

        Scans the diff for import statements that reference banned packages
        or packages that look like new dependencies not in the approved list.
        """
        violations: list[dict[str, str]] = []
        recommendations: list[str] = []

        if not diff:
            return violations, recommendations

        # Find all import statements in the diff (new lines only)
        import_pattern = re.compile(
            r'^\+\s*(?:import|from)\s+(\w+)', re.MULTILINE
        )

        for match in import_pattern.finditer(diff):
            package = match.group(1).lower()

            if package in self.banned_dependencies:
                violations.append({
                    "check": "dependency_jail",
                    "detail": f"Banned dependency detected: '{package}'. "
                              f"This package is not authorized for this project.",
                })

        # Check for destructive operations in new code
        for line in diff.split("\n"):
            if not line.startswith("+"):
                continue
            line_lower = line.lower()
            for keyword in DESTRUCTIVE_KEYWORDS:
                # Only flag if it looks like a function call or command
                if re.search(rf'\b{keyword}\s*\(', line_lower):
                    violations.append({
                        "check": "dependency_jail",
                        "detail": f"Destructive operation detected: '{keyword}' call in new code.",
                    })
                    break

        return violations, recommendations

    # ===================================================================
    # Check 2: Style Match
    # ===================================================================

    async def _check_style_match(
        self, diff: str
    ) -> tuple[list[dict[str, str]], list[str]]:
        """Verify code follows basic style conventions."""
        violations: list[dict[str, str]] = []
        recommendations: list[str] = []

        if not diff:
            return violations, recommendations

        new_lines = [l[1:] for l in diff.split("\n") if l.startswith("+") and not l.startswith("+++")]

        # Check for mixing tabs and spaces
        has_tabs = any("\t" in line for line in new_lines)
        has_spaces = any(line.startswith("    ") for line in new_lines)
        if has_tabs and has_spaces:
            violations.append({
                "check": "style_match",
                "detail": "Mixed tabs and spaces detected in new code.",
            })

        # Check for extremely long lines
        for line in new_lines:
            if len(line) > 200:
                recommendations.append(
                    f"Line exceeds 200 characters ({len(line)} chars). Consider breaking it up."
                )
                break  # One warning is enough

        # Check for wildcard imports
        if any(re.search(r'from\s+\S+\s+import\s+\*', line) for line in new_lines):
            violations.append({
                "check": "style_match",
                "detail": "Wildcard import (from X import *) detected. Use explicit imports.",
            })

        return violations, recommendations

    # ===================================================================
    # Check 3: Chaos Check (Happy Path Bias counter)
    # ===================================================================

    async def _check_chaos(
        self, diff: str
    ) -> tuple[list[dict[str, str]], list[str]]:
        """Verify edge case handling in new code."""
        violations: list[dict[str, str]] = []
        recommendations: list[str] = []

        if not diff:
            return violations, recommendations

        new_lines = [l[1:] for l in diff.split("\n") if l.startswith("+") and not l.startswith("+++")]
        code_block = "\n".join(new_lines)

        # Check for bare except
        if re.search(r'except\s*:', code_block):
            violations.append({
                "check": "chaos_check",
                "detail": "Bare 'except:' found. Catch specific exceptions to avoid masking bugs.",
            })

        # Check for eval/exec
        if re.search(r'\b(?:eval|exec)\s*\(', code_block):
            violations.append({
                "check": "chaos_check",
                "detail": "eval() or exec() detected. These are security risks.",
            })

        # Check for hardcoded credentials
        credential_patterns = [
            r'password\s*=\s*["\'][^"\']+["\']',
            r'api_key\s*=\s*["\'][^"\']+["\']',
            r'secret\s*=\s*["\'][^"\']+["\']',
            r'token\s*=\s*["\'][^"\']+["\']',
        ]
        for pattern in credential_patterns:
            if re.search(pattern, code_block, re.IGNORECASE):
                violations.append({
                    "check": "chaos_check",
                    "detail": "Possible hardcoded credential detected. Use environment variables.",
                })
                break

        # Check for no None/empty checks before operations
        # (Heuristic: functions that access .attribute without None check)
        if re.search(r'\.split\(|\.strip\(|\.lower\(', code_block):
            if not re.search(r'if\s+\w+\s+is\s+not\s+None|if\s+\w+:', code_block):
                recommendations.append(
                    "Code accesses string methods without apparent None checks. "
                    "Consider adding null safety."
                )

        return violations, recommendations

    # ===================================================================
    # Check 4: Placeholder Scan
    # ===================================================================

    async def _check_placeholders(
        self, diff: str
    ) -> tuple[list[dict[str, str]], list[str]]:
        """Reject code containing TODOs, stubs, or unimplemented sections."""
        violations: list[dict[str, str]] = []
        recommendations: list[str] = []

        if not diff:
            return violations, recommendations

        new_lines = [l[1:] for l in diff.split("\n") if l.startswith("+") and not l.startswith("+++")]

        for i, line in enumerate(new_lines):
            for pattern in PLACEHOLDER_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    violations.append({
                        "check": "placeholder_scan",
                        "detail": f"Placeholder/stub detected on new line {i + 1}: {line.strip()[:80]}",
                    })
                    break

        return violations, recommendations

    # ===================================================================
    # Check 5: Drift Alignment
    # ===================================================================

    async def _check_drift_alignment(
        self, task_description: str, approach_summary: str
    ) -> tuple[list[dict[str, str]], list[str]]:
        """Check semantic alignment between task intent and agent's approach.

        Uses sentence-transformers embeddings to compute cosine similarity
        between the original task description and the agent's approach summary.
        """
        violations: list[dict[str, str]] = []
        recommendations: list[str] = []

        if not task_description or not approach_summary:
            recommendations.append("Drift check skipped: missing task description or approach summary.")
            return violations, recommendations

        if self.embedding_engine is None:
            recommendations.append("Drift check skipped: no embedding engine configured.")
            return violations, recommendations

        try:
            similarity = await self._compute_alignment(task_description, approach_summary)
            logger.info("Drift alignment score: %.3f (threshold: %.3f)", similarity, self.drift_threshold)

            if similarity < self.drift_threshold:
                severity = self._drift_severity(similarity)
                guidance = self._drift_guidance(similarity, severity)

                violations.append({
                    "check": "drift_alignment",
                    "detail": (
                        f"Task drift detected (severity: {severity}). "
                        f"Alignment score: {similarity:.3f} "
                        f"(threshold: {self.drift_threshold:.3f}). "
                        f"The agent's approach may not address the original task. "
                        f"{guidance}"
                    ),
                })
            elif similarity < self.drift_threshold + 0.1:
                recommendations.append(
                    f"Drift alignment borderline ({similarity:.3f}). "
                    f"Review that the approach fully addresses the task."
                )

        except Exception as e:
            logger.warning("Drift alignment check failed: %s", e)
            recommendations.append(f"Drift check could not be executed: {e}")

        return violations, recommendations

    async def _compute_alignment(self, task_desc: str, approach: str) -> float:
        """Compute cosine similarity between task and approach embeddings.

        The EmbeddingEngine.encode() is synchronous (CPU-bound), so we run
        it in an executor to avoid blocking the event loop.
        """
        loop = asyncio.get_running_loop()
        task_vec = await loop.run_in_executor(None, self.embedding_engine.encode, task_desc)
        approach_vec = await loop.run_in_executor(None, self.embedding_engine.encode, approach)
        return self.embedding_engine.cosine_similarity(task_vec, approach_vec)

    def _drift_severity(self, similarity: float) -> str:
        """Determine drift severity from similarity score."""
        if similarity < 0.1:
            return "CRITICAL"
        if similarity < 0.2:
            return "HIGH"
        if similarity < 0.3:
            return "MEDIUM"
        return "LOW"

    def _drift_guidance(self, similarity: float, severity: str) -> str:
        """Generate corrective guidance based on drift severity."""
        if severity == "CRITICAL":
            return "The approach appears completely unrelated to the task. Restart from the task description."
        if severity == "HIGH":
            return "Significant divergence from task intent. Re-read the task and refocus the approach."
        if severity == "MEDIUM":
            return "Partial drift detected. Ensure all task requirements are addressed."
        return "Minor drift. Verify edge cases and secondary requirements."

    # ===================================================================
    # Check 6: Claim Validation
    # ===================================================================

    async def _check_claims(
        self, approach_summary: str, outcome: TaskOutcome, self_audit: str = ""
    ) -> tuple[list[dict[str, str]], list[str]]:
        """Detect and validate claims in the agent's output.

        Scans the approach summary for claims like "tested", "production ready",
        "fixed", etc., and validates them against actual evidence from the
        TaskOutcome. Cross-checks with the agent's self-audit.
        """
        violations: list[dict[str, str]] = []
        recommendations: list[str] = []

        if not approach_summary:
            return violations, recommendations

        text = approach_summary.lower()

        for claim_def in CLAIM_PATTERNS:
            for phrase in claim_def["claims"]:
                pattern = r"\b" + re.escape(phrase) + r"\b"
                if re.search(pattern, text):
                    # Claim detected — validate against evidence
                    evidence = claim_def["evidence"]
                    verdict = await self._validate_claim(phrase, outcome)

                    if verdict == "BLOCK":
                        violations.append({
                            "check": "claim_validation",
                            "detail": (
                                f"Unsubstantiated claim: '{phrase}'. "
                                f"Required evidence: {evidence}. "
                                f"No supporting evidence found in build output."
                            ),
                        })
                    elif verdict == "PARTIAL":
                        recommendations.append(
                            f"Claim '{phrase}' is only partially substantiated. "
                            f"Required: {evidence}."
                        )
                    break  # One match per claim definition

        # Cross-check self-audit against actual check results
        if self_audit:
            await self._cross_check_self_audit(self_audit, outcome, violations, recommendations)

        return violations, recommendations

    async def _cross_check_self_audit(
        self,
        self_audit: str,
        outcome: TaskOutcome,
        violations: list[dict[str, str]],
        recommendations: list[str],
    ) -> None:
        """Cross-check agent's self-audit claims against actual evidence.

        If the agent claims YES to a self-audit question but evidence
        contradicts it, add a compounding violation.
        """
        audit_lower = self_audit.lower()

        # Check: agent claims "no placeholders" but placeholders were found
        placeholder_violations = [v for v in violations if v.get("check") == "placeholder_scan"]
        if placeholder_violations and ("yes" in audit_lower) and ("placeholder" in audit_lower or "todo" in audit_lower):
            violations.append({
                "check": "claim_validation",
                "detail": (
                    "Self-audit contradiction: Agent claimed no placeholders/TODOs "
                    "in self-audit, but placeholder scan found violations."
                ),
            })

        # Check: agent claims error handling but bare except found
        chaos_violations = [v for v in violations if v.get("check") == "chaos_check" and "except:" in v.get("detail", "")]
        if chaos_violations and ("yes" in audit_lower) and ("error handling" in audit_lower):
            violations.append({
                "check": "claim_validation",
                "detail": (
                    "Self-audit contradiction: Agent claimed error handling "
                    "in self-audit, but bare 'except:' was detected."
                ),
            })

    async def _validate_claim(self, claim_phrase: str, outcome: TaskOutcome) -> str:
        """Validate a specific claim against outcome evidence.

        Returns:
            "PASS", "PARTIAL", or "BLOCK"
        """
        # "tested" / "tests pass" — check if tests actually passed
        test_claims = {"tested", "tests pass", "all tests pass"}
        if claim_phrase in test_claims:
            if outcome.tests_passed:
                return "PASS"
            return "BLOCK"

        # "fixed" / "resolved" — check if tests passed (proxy for fix verification)
        fix_claims = {"fixed", "resolved", "bug fixed"}
        if claim_phrase in fix_claims:
            if outcome.tests_passed and outcome.files_changed:
                return "PARTIAL"  # Fixed but no specific repro verification
            return "BLOCK"

        # "done" / "complete" — check tests + files changed
        done_claims = {"done", "complete", "completed", "finished"}
        if claim_phrase in done_claims:
            if outcome.tests_passed and outcome.files_changed:
                return "PARTIAL"  # Complete but no acceptance criteria check
            return "BLOCK"

        # "production ready" — always BLOCK unless full pipeline validated
        production_claims = {"production ready", "prod ready", "ready for production"}
        if claim_phrase in production_claims:
            return "BLOCK"

        # Other claims — partial by default
        return "PARTIAL"

    # ===================================================================
    # Check 7: LLM Deep Review (optional)
    # ===================================================================

    async def _check_llm_deep(
        self, task_desc: str, approach_summary: str, diff: str
    ) -> tuple[list[dict[str, str]], list[str], int]:
        """Call an LLM to review the diff against the task.

        Only executed when llm_client is configured and all rule-based checks
        passed. Uses a different model family than the executing agent to
        provide an independent perspective.

        Returns:
            (violations, recommendations, tokens_used)
        """
        violations: list[dict[str, str]] = []
        recommendations: list[str] = []

        if not self.llm_client:
            recommendations.append(
                "LLM deep check skipped: no llm_client configured."
            )
            return violations, recommendations, 0

        if not diff:
            recommendations.append("LLM deep check skipped: no diff to review.")
            return violations, recommendations, 0

        try:
            from claw.llm.client import LLMMessage

            # Build the prompt
            prompt_template = self._prompt_loader.load(
                "verifier_deep_check.txt", default=self._DEFAULT_DEEP_CHECK_PROMPT
            )
            prompt = (
                prompt_template
                .replace("{task_description}", task_desc or "(no task description)")
                .replace("{diff}", diff[:8000])  # Truncate to avoid token limits
                .replace("{approach_summary}", approach_summary or "(no approach summary)")
            )

            messages = [
                LLMMessage(role="user", content=prompt),
            ]

            # The llm_client.complete() is async in CLAW
            # The model must be user-selected via config; we pass
            # the model from llm_client config or require it set externally.
            # We use complete_json for structured output if available,
            # otherwise fall back to complete + parse.
            model = getattr(self.llm_client, '_verifier_model', None)
            if model is None:
                # Fallback: use the first fallback model or raise
                config = getattr(self.llm_client, 'config', None)
                if config and config.fallback_models:
                    model = config.fallback_models[0]
                else:
                    recommendations.append(
                        "LLM deep check skipped: no verifier model configured. "
                        "Set llm_client._verifier_model or configure fallback_models."
                    )
                    return violations, recommendations, 0

            response = await self.llm_client.complete(messages, model=model)

            # Parse the JSON response
            result = self._parse_deep_check_response(response.content)
            if result:
                if result.get("verdict") == "FAIL":
                    gaps = result.get("gaps", [])
                    severity = result.get("severity", "medium")
                    for gap in gaps[:5]:  # Limit to 5 gaps
                        violations.append({
                            "check": "llm_deep_review",
                            "detail": f"[{severity}] {gap}",
                        })
                    if not gaps:
                        violations.append({
                            "check": "llm_deep_review",
                            "detail": f"LLM deep review returned FAIL (severity: {severity}) but no specific gaps listed.",
                        })
                else:
                    logger.info("LLM deep check PASSED (model=%s)", model)

            return violations, recommendations, response.tokens_used

        except Exception as e:
            logger.warning("LLM deep check failed: %s", e)
            recommendations.append(f"LLM deep check could not be executed: {e}")
            return violations, recommendations, 0

    def _parse_deep_check_response(self, content: str) -> Optional[dict]:
        """Parse the LLM deep check JSON response."""
        # Try extracting JSON from markdown code fence
        fence_pattern = r"```(?:json)?\s*\n?(.*?)\n?```"
        match = re.search(fence_pattern, content, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1).strip())
                if isinstance(data, dict) and "verdict" in data:
                    return data
            except (json.JSONDecodeError, TypeError):
                pass

        # Fallback: try parsing the whole content as JSON
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "verdict" in data:
                return data
        except (json.JSONDecodeError, TypeError):
            pass

        logger.warning("Could not parse LLM deep check response")
        return None

    # ===================================================================
    # Test execution
    # ===================================================================

    async def run_tests(
        self, workspace_dir: str
    ) -> tuple[bool, str, int]:
        """Run the appropriate test command for the project.

        Detects the project type from config files and runs:
        - Python: pytest
        - Node.js: npm test
        - Otherwise: skip (return pass with 0 tests)

        Args:
            workspace_dir: Path to the repository root.

        Returns:
            (passed, output_text, test_count)
            - passed: True if all tests passed (exit code 0)
            - output_text: Full test runner output
            - test_count: Number of tests collected
        """
        workspace = Path(workspace_dir)
        if not workspace.is_dir():
            raise FileNotFoundError(f"Workspace directory not found: {workspace_dir}")

        cmd, args = self._detect_test_command(workspace)
        if cmd is None:
            logger.info("No test runner detected for %s, skipping test check", workspace_dir)
            return True, "No test runner detected — skipped", 0

        proc = await asyncio.create_subprocess_exec(
            cmd,
            *args,
            cwd=str(workspace),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        output = stdout.decode("utf-8", errors="replace")
        error_output = stderr.decode("utf-8", errors="replace")
        full_output = output + error_output

        passed = proc.returncode == 0

        test_count = self._parse_test_count(output)

        logger.info(
            "Tests %s in %s (%d tests, exit code %d, runner=%s)",
            "passed" if passed else "failed",
            workspace_dir,
            test_count,
            proc.returncode,
            cmd,
        )

        return passed, full_output, test_count

    async def _run_coverage(self, workspace_dir: str) -> Optional[str]:
        """Run pytest with --cov to measure code coverage.

        Returns the coverage output text, or None if coverage could not be measured.
        """
        workspace = Path(workspace_dir)

        # Only run for Python projects
        if not any((workspace / f).exists() for f in ("pyproject.toml", "setup.py", "requirements.txt")):
            return None

        # Detect the package name for --cov argument
        cov_target = None
        for candidate in ("app", "src"):
            if (workspace / candidate).is_dir():
                cov_target = candidate
                break
        if cov_target is None:
            # Try any directory with __init__.py
            for p in workspace.iterdir():
                if p.is_dir() and (p / "__init__.py").exists() and p.name not in ("tests", "test"):
                    cov_target = p.name
                    break
        if cov_target is None:
            return None

        try:
            proc = await asyncio.create_subprocess_exec(
                "pytest",
                f"--cov={cov_target}",
                "--cov-report=term",
                "--tb=no",
                "-q",
                cwd=str(workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            output = stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")
            logger.info("Coverage run complete for %s (exit code %d)", workspace_dir, proc.returncode)
            return output
        except Exception as e:
            logger.warning("Coverage measurement failed: %s", e)
            return None

    @staticmethod
    def _detect_test_command(workspace: Path) -> tuple[Optional[str], list[str]]:
        """Detect the right test runner for a project.

        Returns (command, args) or (None, []) if no runner found.
        """
        # Python projects
        if (workspace / "pyproject.toml").exists() or (workspace / "setup.py").exists():
            return "pytest", ["--tb=short"]
        if (workspace / "requirements.txt").exists():
            # Check if tests dir exists
            if any((workspace / d).exists() for d in ["tests", "test"]):
                return "pytest", ["--tb=short"]

        # Node.js projects
        if (workspace / "package.json").exists():
            return "npm", ["test", "--if-present"]

        # Go projects
        if (workspace / "go.mod").exists():
            return "go", ["test", "./..."]

        # Rust projects
        if (workspace / "Cargo.toml").exists():
            return "cargo", ["test"]

        # No recognized project type
        return None, []

    async def regression_scan(
        self, tests_before: int, tests_after: int
    ) -> tuple[bool, str]:
        """Compare test counts before/after to detect regressions.

        A regression is detected if:
        - Test count decreased (tests were removed or broken)
        - test_after is 0 and test_before was > 0 (all tests disappeared)

        Args:
            tests_before: Number of tests before the change.
            tests_after: Number of tests after the change.

        Returns:
            (regression_detected, detail_message)
        """
        if tests_after < tests_before:
            diff = tests_before - tests_after
            return True, (
                f"Test regression detected: {diff} test(s) lost "
                f"(before: {tests_before}, after: {tests_after}). "
                f"Investigate whether tests were removed or broken."
            )

        if tests_before > 0 and tests_after == 0:
            return True, (
                f"Critical regression: all {tests_before} tests disappeared. "
                f"The test suite may have been deleted or broken."
            )

        return False, (
            f"No regression detected (before: {tests_before}, after: {tests_after})."
        )

    async def _run_acceptance_checks(
        self,
        workspace_dir: str,
        acceptance_checks: list[str],
    ) -> tuple[list[dict[str, str]], list[str]]:
        """Execute allowlisted acceptance commands in the workspace."""
        violations: list[dict[str, str]] = []
        recommendations: list[str] = []

        workspace = Path(workspace_dir)
        if not workspace.is_dir():
            violations.append({
                "check": "acceptance_checks",
                "detail": f"Workspace directory not found for acceptance checks: {workspace_dir}",
            })
            return violations, recommendations

        for raw_command in acceptance_checks:
            command = (raw_command or "").strip()
            if not command:
                continue

            tokens, blocked_reason = self._validate_acceptance_command(command)
            if blocked_reason:
                if "not allowlisted" in blocked_reason:
                    recommendations.append(
                        f"Manual acceptance check required: {command} ({blocked_reason})"
                    )
                else:
                    violations.append({
                        "check": "acceptance_checks",
                        "detail": f"Blocked acceptance check '{command}': {blocked_reason}",
                    })
                continue

            assert tokens is not None  # For type checkers; blocked_reason handled above.

            try:
                proc = await asyncio.create_subprocess_exec(
                    *tokens,
                    cwd=str(workspace),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                try:
                    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=180)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.communicate()
                    violations.append({
                        "check": "acceptance_checks",
                        "detail": f"Acceptance check timed out after 180s: {command}",
                    })
                    continue

                output = (
                    stdout.decode("utf-8", errors="replace")
                    + stderr.decode("utf-8", errors="replace")
                ).strip()
                if proc.returncode != 0:
                    violations.append({
                        "check": "acceptance_checks",
                        "detail": (
                            f"Acceptance check failed (exit {proc.returncode}): {command}. "
                            f"Output: {output[:500]}"
                        ),
                    })
                else:
                    logger.info("Acceptance check passed: %s", command)
            except Exception as e:
                violations.append({
                    "check": "acceptance_checks",
                    "detail": f"Acceptance check execution error for '{command}': {e}",
                })

        return violations, recommendations

    @staticmethod
    def _validate_acceptance_command(command: str) -> tuple[Optional[list[str]], Optional[str]]:
        """Parse and validate a single acceptance command string."""
        if any(pattern in command for pattern in BLOCKED_SHELL_PATTERNS):
            return None, "shell chaining/redirection is not allowed"

        try:
            tokens = shlex.split(command)
        except ValueError as e:
            return None, f"could not parse command: {e}"

        if not tokens:
            return None, "empty command"

        executable = Path(tokens[0]).name
        if executable not in ALLOWED_ACCEPTANCE_COMMANDS:
            return None, f"command '{executable}' is not allowlisted"

        if executable in {"python", "python3"} and any(t in {"-c", "--command"} for t in tokens[1:]):
            return None, "inline python execution (-c/--command) is not allowed"

        if executable == "node" and any(t in {"-e", "--eval"} for t in tokens[1:]):
            return None, "inline node execution (-e/--eval) is not allowed"

        return tokens, None

    # ===================================================================
    # Quality scoring
    # ===================================================================

    def _compute_quality_score(
        self,
        violations: list[dict[str, str]],
        recommendations: list[str],
    ) -> float:
        """Compute a quality score from 0.0 to 1.0.

        Each violation deducts 0.15 from a perfect 1.0 score.
        Each recommendation deducts 0.03.
        Score is clamped to [0.0, 1.0].
        """
        score = 1.0
        score -= len(violations) * 0.15
        score -= len(recommendations) * 0.03
        return max(0.0, min(1.0, score))

    # ===================================================================
    # Helpers
    # ===================================================================

    @staticmethod
    def _parse_test_count(pytest_output: str) -> int:
        """Parse the number of tests from pytest output.

        Handles formats like:
        - "5 passed"
        - "3 passed, 1 failed"
        - "10 passed, 2 failed, 1 error"
        - "no tests ran"
        """
        total = 0

        # Match patterns like "5 passed", "3 failed", "1 error", "2 skipped"
        count_pattern = re.compile(r'(\d+)\s+(?:passed|failed|error|errors|skipped|warnings?|deselected)')
        for match in count_pattern.finditer(pytest_output):
            total += int(match.group(1))

        return total

    def _extract_minimum_test_requirement(self, task_context: "TaskContext") -> int:
        """Extract minimum test count from task description or config.

        Checks (in order):
        1. Explicit count patterns in task description ("22-28 tests", "at least 20 tests")
        2. Count of listed test topics after "tests covering:"
        3. Config fallback (self.min_test_count)
        """
        desc = task_context.task.description or ""

        # Pattern 1: "22-28 tests" or "22 to 28 tests" → take the lower bound
        range_match = re.search(r'(\d+)\s*[-–to]+\s*\d+\s+tests?', desc, re.IGNORECASE)
        if range_match:
            return int(range_match.group(1))

        # Pattern 2: "at least N tests" / "minimum N tests" / "require N tests"
        explicit_match = re.search(
            r'(?:at\s+least|minimum|require[sd]?|no\s+fewer\s+than)\s+(\d+)\s+tests?',
            desc, re.IGNORECASE,
        )
        if explicit_match:
            return int(explicit_match.group(1))

        # Pattern 3: Count comma-separated items after "tests covering:"
        covering_match = re.search(r'tests?\s+covering\s*:\s*(.+?)(?:\.|$)', desc, re.IGNORECASE)
        if covering_match:
            items = [item.strip() for item in covering_match.group(1).split(',') if item.strip()]
            if items:
                return len(items)

        # Fallback to config
        return self.min_test_count

    # ===================================================================
    # Metric expectations
    # ===================================================================

    @staticmethod
    def _parse_coverage_pct(test_output: str) -> Optional[float]:
        """Extract total coverage percentage from pytest-cov output.

        Looks for the TOTAL line: 'TOTAL   101   14   86%'
        """
        match = re.search(r'^TOTAL\s+\d+\s+\d+\s+(\d+)%', test_output, re.MULTILINE)
        if match:
            return float(match.group(1))
        return None

    @staticmethod
    def _extract_metrics_from_description(desc: str) -> list["MetricExpectation"]:
        """Auto-extract metric expectations from task description text.

        Recognizes patterns like:
        - "greater than 90 percent coverage" / ">90% coverage"
        - "at least 20 tests" (handled separately by _extract_minimum_test_requirement)
        - "no more than 500 lines"
        """
        metrics: list[MetricExpectation] = []

        # Coverage: "greater than N percent coverage" / ">N% coverage" / "at least N% coverage"
        cov_patterns = [
            r'(?:greater\s+than|more\s+than|>\s*|above)\s*(\d+)\s*(?:percent|%)\s*coverage',
            r'(?:at\s+least|minimum|>=?\s*)\s*(\d+)\s*(?:percent|%)\s*coverage',
            r'coverage\s*(?:target|goal|>=?|of\s+at\s+least)\s*[:=]?\s*(\d+)\s*(?:percent|%)',
        ]
        for pat in cov_patterns:
            m = re.search(pat, desc, re.IGNORECASE)
            if m:
                metrics.append(MetricExpectation(
                    name="code_coverage",
                    metric="min_coverage_pct",
                    operator="gte",
                    value=float(m.group(1)),
                    hard=True,
                ))
                break

        return metrics

    def _collect_metric_expectations(self, task_context: "TaskContext") -> list["MetricExpectation"]:
        """Gather metric expectations from contract and task description."""
        metrics: list[MetricExpectation] = []

        # From expectation_contract.metric_expectations (explicit)
        contract = task_context.expectation_contract
        if contract is not None and hasattr(contract, "metric_expectations"):
            metrics.extend(contract.metric_expectations)

        # Auto-extracted from description (implicit)
        desc = task_context.task.description or ""
        auto = self._extract_metrics_from_description(desc)
        # Don't duplicate — skip auto metrics whose metric type is already explicit
        explicit_types = {m.metric for m in metrics}
        for m in auto:
            if m.metric not in explicit_types:
                metrics.append(m)

        return metrics

    @staticmethod
    def _evaluate_metric(
        expectation: "MetricExpectation",
        actual: float,
    ) -> bool:
        """Evaluate a single metric against its expectation."""
        op = expectation.operator
        val = expectation.value
        if op == "gte":
            return actual >= val
        elif op == "gt":
            return actual > val
        elif op == "lte":
            return actual <= val
        elif op == "lt":
            return actual < val
        elif op == "eq":
            return actual == val
        return True

    def _check_metric_expectations(
        self,
        task_context: "TaskContext",
        tests_after: Optional[int],
        test_output: str,
        files_changed: list[str],
    ) -> tuple[list[dict[str, str]], list[str]]:
        """Evaluate all metric expectations and return violations/recommendations."""
        violations: list[dict[str, str]] = []
        recommendations: list[str] = []

        metrics = self._collect_metric_expectations(task_context)
        if not metrics:
            return violations, recommendations

        # Build a map of available actuals
        actuals: dict[str, Optional[float]] = {
            "min_test_count": float(tests_after) if tests_after is not None else None,
            "min_coverage_pct": self._parse_coverage_pct(test_output),
            "min_files_changed": float(len(files_changed)),
            "max_files_changed": float(len(files_changed)),
        }

        for m in metrics:
            actual = actuals.get(m.metric)
            if actual is None:
                recommendations.append(
                    f"Metric '{m.name}' ({m.metric}) could not be measured — skipped."
                )
                continue

            if not self._evaluate_metric(m, actual):
                detail = (
                    f"Metric '{m.name}' failed: actual={actual:.0f}, "
                    f"expected {m.operator} {m.value:.0f}."
                )
                if m.hard:
                    violations.append({"check": "metric_expectation", "detail": detail})
                else:
                    recommendations.append(detail)

        return violations, recommendations
