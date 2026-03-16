"""Target repository scanning."""

from __future__ import annotations

from pathlib import Path

from .models import RepoProfile, RepoSignal

RISK_PATTERNS = {
    "eval(": "Uses eval(), which increases code-execution risk.",
    "exec(": "Uses exec(), which increases code-execution risk.",
    "shell=True": "Uses shell=True in subprocess execution.",
    "pickle.load": "Uses pickle.load(), which can deserialize unsafe data.",
}


def _is_test_file(path: Path) -> bool:
    return path.name.startswith("test_") or path.name.endswith("_test.py") or any(part == "tests" for part in path.parts[:-1])


def _has_type_hints(text: str) -> bool:
    return "->" in text or ": " in text


def scan_repo(repo_path: Path) -> RepoProfile:
    files = [p for p in repo_path.rglob("*") if p.is_file() and ".git" not in p.parts and "__pycache__" not in p.parts]
    python_files = [p for p in files if p.suffix == ".py"]
    docs_files = [p for p in files if p.name.lower().startswith("readme") or p.suffix in {".md", ".rst"}]
    test_files = [p for p in files if _is_test_file(p.relative_to(repo_path))]
    ci_files = [p for p in files if ".github" in p.parts and p.suffix in {".yml", ".yaml"}]
    has_pyproject = any(p.name == "pyproject.toml" for p in files)
    has_package_json = any(p.name == "package.json" for p in files)
    has_readme = any(p.name.lower().startswith("readme") for p in files)
    has_docs_dir = (repo_path / "docs").exists()

    type_hints = False
    risky_patterns: list[str] = []
    for path in python_files[:40]:
        text = path.read_text(encoding="utf-8", errors="ignore")
        type_hints = type_hints or _has_type_hints(text)
        for pattern, explanation in RISK_PATTERNS.items():
            if pattern in text:
                risky_patterns.append(f"{path.relative_to(repo_path)}: {explanation}")

    top_files = [str(p.relative_to(repo_path)) for p in sorted(files)[:12]]
    return RepoProfile(
        repo_path=repo_path,
        file_count=len(files),
        python_files=python_files,
        docs_files=docs_files,
        test_files=test_files,
        ci_files=ci_files,
        has_pyproject=has_pyproject,
        has_package_json=has_package_json,
        has_readme=has_readme,
        has_docs_dir=has_docs_dir,
        has_type_hints=type_hints,
        risky_patterns=risky_patterns,
        top_files=top_files,
    )


def derive_signals(profile: RepoProfile, focus: set[str] | None = None) -> list[RepoSignal]:
    signals: list[RepoSignal] = []

    def allow(category: str) -> bool:
        return not focus or category in focus

    if profile.python_files and not profile.test_files and allow("testing"):
        signals.append(
            RepoSignal(
                signal_id="missing-tests",
                category="testing",
                title="Add automated tests before expanding features",
                why_now="The repo has executable Python code but no automated tests, which blocks safe iteration and regression detection.",
                evidence=[f"Python files: {len(profile.python_files)}", "No test files were found."],
                improvement="Create a lightweight test suite that exercises the public behavior of the repo before further expansion.",
                first_step="Add a tests/ directory and one smoke test covering the primary module entrypoint.",
                difficulty="medium",
                payoff="high",
                query_terms=["testing", "validation", "workflow", "quality checklist", "benchmark"],
            )
        )

    if profile.python_files and not profile.has_pyproject and allow("architecture"):
        signals.append(
            RepoSignal(
                signal_id="missing-packaging",
                category="architecture",
                title="Add package metadata and repeatable developer entrypoints",
                why_now="The repo contains Python source but lacks a pyproject.toml, making setup, checks, and CLI entrypoints less repeatable.",
                evidence=["Python source detected.", "No pyproject.toml found."],
                improvement="Add pyproject metadata and standard commands for install, test, and execution.",
                first_step="Create pyproject.toml with project metadata and a minimal build-system section.",
                difficulty="low",
                payoff="high",
                query_terms=["architecture", "workspace", "cli", "packaging", "workflow step", "verification"],
            )
        )

    if not profile.ci_files and allow("devops"):
        signals.append(
            RepoSignal(
                signal_id="missing-ci",
                category="devops",
                title="Add continuous verification checks",
                why_now="There is no CI workflow in the repository, so tests and static checks are not enforced on change.",
                evidence=["No .github/workflows YAML files found."],
                improvement="Add a minimal CI workflow that runs tests and primary CLI smoke checks on every push.",
                first_step="Create a GitHub Actions workflow that runs the test suite and one CLI invocation.",
                difficulty="medium",
                payoff="high",
                query_terms=["workflow", "verification", "checks", "automation", "ci", "quality"],
            )
        )

    if not profile.has_docs_dir and len(profile.docs_files) <= 1 and allow("code_quality"):
        signals.append(
            RepoSignal(
                signal_id="sparse-docs",
                category="code_quality",
                title="Strengthen operator-facing documentation",
                why_now="The repo has minimal written guidance, which reduces onboarding speed and makes the implementation harder to verify.",
                evidence=[f"Documentation-like files found: {len(profile.docs_files)}", "No docs/ directory found."],
                improvement="Add usage, architecture, and verification docs so the repo can be adopted and changed safely.",
                first_step="Add docs/ with a quickstart and one architecture note describing the main workflow.",
                difficulty="low",
                payoff="medium",
                query_terms=["documentation", "cross-reference", "knowledge", "checklist", "quality"],
            )
        )

    if profile.python_files and not profile.has_type_hints and allow("code_quality"):
        signals.append(
            RepoSignal(
                signal_id="low-typing",
                category="code_quality",
                title="Add lightweight type hints at public boundaries",
                why_now="The repo contains Python code with little visible typing information, which weakens maintainability and tool-assisted validation.",
                evidence=[f"Python files: {len(profile.python_files)}", "No obvious type hints detected in scanned Python files."],
                improvement="Add type hints to public functions and key data structures to improve refactoring safety.",
                first_step="Annotate the main public functions and run a basic static check.",
                difficulty="medium",
                payoff="medium",
                query_terms=["code quality", "schema", "validation", "quality checklist", "typing"],
            )
        )

    if profile.risky_patterns and allow("security"):
        signals.append(
            RepoSignal(
                signal_id="risky-patterns",
                category="security",
                title="Reduce risky dynamic execution patterns",
                why_now="The scan found code patterns associated with higher execution risk or unsafe deserialization.",
                evidence=profile.risky_patterns,
                improvement="Replace risky dynamic execution patterns with constrained or validated alternatives.",
                first_step="Remove or encapsulate the first flagged risky call behind validation and tests.",
                difficulty="medium",
                payoff="high",
                query_terms=["security", "compliance", "protect", "detect", "validation", "input"],
            )
        )

    return signals
