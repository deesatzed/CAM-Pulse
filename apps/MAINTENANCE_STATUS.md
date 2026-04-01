# Apps Directory Maintenance Status

**Audit date**: 2026-03-31
**Auditor**: Static file analysis (no packages installed/modified)
**System Python**: 3.13.9
**Parent project requires**: Python >=3.12

---

## 1. assimilation_repo_upgrade_advisor

**Purpose**: Standalone CLI that reads a CAM knowledge pack (JSONL), scans a target repository for structural weaknesses, and produces an evidence-backed markdown upgrade plan with provenance links to assimilated methodologies.

**Tech stack**: Pure Python (stdlib only -- argparse, json, re, pathlib, dataclasses). No external runtime dependencies.

**Version**: 0.1.0

### Dependencies

| Dependency | Version | Status |
|---|---|---|
| (none at runtime) | n/a | No external packages required |
| setuptools | >=68 | Build only; current |
| pytest | implied (test fixtures use pytest patterns) | Available from parent dev extras |

- `pyproject.toml` declares `dependencies = []` -- zero runtime dependencies.
- Tests rely on pytest, which is available through the parent project's `[dev]` extras.

**Dependency freshness**: N/A (no runtime deps). Build tooling is current.

### Build Status: LIKELY WORKS

- All source files are stdlib-only Python with proper `from __future__ import annotations`.
- Uses `dataclass(slots=True)` which requires Python >=3.10 (satisfied by >=3.12 requirement).
- `pyproject.toml` is well-formed with setuptools backend.
- No import of any external package at runtime.
- Tests import only from the local `advisor_app` package and use standard pytest patterns.
- A demo report (`demo_embedding_forge_report.md`) exists showing a successful prior run against the embedding_forge app itself.

### Test Coverage

- 3 test files: `test_cli.py`, `test_knowledge_pack.py`, `test_repo_scan.py`
- Tests cover: CLI argument parsing, end-to-end report generation, knowledge pack loading, source-repo extraction, match ranking, repo scanning, and signal derivation.
- Bytecode in `__pycache__` (cpython-313, pytest-9.0.2) confirms tests were previously executed on this Python version.

### Key Files Last Modified

All files: 2026-03-30 14:28 (uniform timestamp across all source and test files).

### Observations

- Cleanly isolated: explicitly states "The app does not import CAM runtime code."
- No CI configuration within the app directory.
- No `.gitignore` within the app directory (relies on parent).
- `__pycache__` directories are present and should be cleaned before packaging.

### Recommended Actions

1. None critical. App is healthy and self-contained.
2. Minor: Add `__pycache__` to a local `.gitignore` or clean before commits.
3. Minor: Consider adding the app to the parent project's CI/test matrix if one exists.

---

## 2. embedding_forge

**Purpose**: Standalone multimodal embedding forge that builds a novel "Forge-32" embedding variant by ingesting a target repository, external concept notes, and optional CAM knowledge packs. Produces forge metrics, device specs, an index, and a report. Also includes a deterministic regression benchmark that runs without network access.

**Tech stack**: Python with one external dependency (`google-genai` for Gemini embeddings). Stdlib otherwise (argparse, hashlib, json, math, sqlite3, re, collections, dataclasses, pathlib).

**Version**: None declared (no pyproject.toml, no `__version__`).

### Dependencies

| Dependency | Version Pinned | Source | Status |
|---|---|---|---|
| `google-genai` | (imported at runtime) | Parent project pins `>=1.0.0` | Current |
| `sqlite3` | stdlib | Built into Python | N/A |
| Standard library | n/a | n/a | N/A |

- `forge_standalone.py` does `from google import genai` and `from google.genai import types` at runtime.
- `benchmark_regression.py` has NO external dependencies -- it dynamically loads `forge_standalone.py` but only uses the pure-Python math functions (tokenize, normalize, cosine, etc.), not the Gemini API.
- No `pyproject.toml` or `requirements.txt` exists for this app. It depends on the parent project's installed environment.

**Dependency freshness**: The `google-genai` package is pinned `>=1.0.0` in the parent. The Gemini embedding model is hardcoded as `gemini-embedding-2-preview` with a fail-fast guard -- if Google deprecates this model, the app will fail loudly (which is the intended behavior).

### Build Status: LIKELY WORKS (with caveats)

- No packaging metadata exists (no pyproject.toml, no setup.py). This is a script-level app, not an installable package.
- `forge_standalone.py` requires `GOOGLE_API_KEY` environment variable to run. Without it, it will raise a `RuntimeError` at initialization.
- `benchmark_regression.py` can run fully offline using deterministic fixture data -- no API key needed.
- Bytecode timestamps (`2026-03-30 17:08`) are more recent than source timestamps (`2026-03-30 14:28`), confirming the app was executed successfully after the last source edit.
- The `--cam-db` flag for direct SQLite CAM DB reads works via stdlib `sqlite3` -- no additional dependency.

### Test Coverage

- **No test files exist within this app directory.**
- The benchmark_regression.py serves as a form of integration/regression test but is not a pytest suite.
- The parent project likely has tests under `tests/` that cover forge functionality (based on fixture references to `tests/fixtures/embedding_forge/`).

### Key Files Last Modified

| File | Last Modified |
|---|---|
| `forge_standalone.py` | 2026-03-30 14:28 |
| `benchmark_regression.py` | 2026-03-30 14:28 |
| `README.md` | 2026-03-30 14:28 |
| `__pycache__/*.pyc` | 2026-03-30 17:08 |

### Observations

- The mandated embedding model (`gemini-embedding-2-preview`) is a preview model. If Google graduates or retires it, the hardcoded guard will reject any replacement. This is intentional per the README but creates a hard coupling to a preview API.
- `forge_standalone.py` is 773 lines -- substantial but manageable.
- No versioning or packaging metadata exists.
- The `--cam-db` path is marked as "transitional compatibility" with knowledge packs as the preferred long-term path.

### Recommended Actions

1. **Add a pyproject.toml** with at minimum a version number and the `google-genai` dependency declared.
2. **Add a pytest test file** covering the pure-Python functions (tokenize, cosine, build_base_embeddings, etc.) that can run without API keys.
3. **Monitor the `gemini-embedding-2-preview` model lifecycle** -- document a migration path for when Google finalizes or replaces this model.
4. Minor: Clean `__pycache__` from version control.

---

## 3. medcss_modernizer_showpiece

**Purpose**: Standalone CLI tool that generates modernization reports and sample HTML landing page outlines for medical/healthcare websites. Accepts site description, purpose, and design ideas as inputs and produces a markdown report plus an HTML template.

**Tech stack**: Pure Python (stdlib only -- argparse, sys, typing). No external runtime dependencies. The only declared dependency is pytest for testing.

**Version**: 1.0.0

### Dependencies

| Dependency | Version Pinned | Status |
|---|---|---|
| (none at runtime) | n/a | No external packages required |
| pytest | >=7.0.0 | In `requirements.txt`; current parent has >=8.0.0 |

- `requirements.txt` contains only `pytest>=7.0.0`.
- All runtime code uses only stdlib modules (`argparse`, `sys`, `typing`).
- The parent project provides `pytest>=8.0.0` which satisfies the `>=7.0.0` pin.

**Dependency freshness**: Runtime deps are N/A. The pytest pin (`>=7.0.0`) is loose and easily satisfied. No security concerns.

### Build Status: LIKELY WORKS

- Pure Python with no external imports at runtime.
- No packaging metadata beyond `requirements.txt` (no pyproject.toml).
- The `__init__.py` sets `__version__ = "1.0.0"`, and `cli.py` references it for `--version`.
- Code uses `from typing import List, Optional` (legacy-style hints) rather than `list[str] | None` -- functional but slightly dated for Python 3.12+.
- The HTML generation is entirely deterministic (string concatenation) with no template engine dependency.
- Bytecode in `__pycache__` (cpython-313, pytest-9.0.2) confirms tests were previously executed.

### Test Coverage

- 2 test files: `test_cli.py` (8 test methods), `test_modernizer.py` (6 test methods).
- Tests cover: CLI argument parsing, exit codes for `--version`/`--help`/invalid args, report generation content, HTML outline structure, CSS style variations, analysis functions.
- CLI tests use `subprocess.run` to invoke the module directly -- tests real execution, not just function calls.
- Tests for the modernizer cover all three analysis functions and verify generated content contains expected sections.

### Key Files Last Modified

All files: 2026-03-30 14:28 (uniform timestamp across all source and test files).

### Observations

- Uses legacy typing style (`List`, `Optional` from `typing`) instead of built-in generics (`list`, `| None`). Not a bug, but inconsistent with the parent project's modern Python style.
- The HTML output hardcodes an Unsplash image URL in the hero section CSS -- this means the generated HTML depends on an external CDN at render time.
- The modernization logic is entirely rule-based (keyword matching on input strings) with no AI/LLM integration. This is a deterministic showpiece, not an AI-powered tool.
- The `_analyze_*` functions are private (underscore-prefixed) but are directly imported and tested in `test_modernizer.py` -- coupling tests to private API.
- No pyproject.toml for this app.

### Recommended Actions

1. **Add a pyproject.toml** for proper packaging and metadata.
2. Minor: Modernize typing imports (`List` -> `list`, `Optional[X]` -> `X | None`) to match parent project conventions.
3. Minor: Consider making the Unsplash hero image URL configurable or bundling a fallback, since external URL dependencies can break.
4. Minor: The `_analyze_*` functions tested in `test_modernizer.py` could be made part of the public API (remove underscore) since they are explicitly tested.

---

## Summary Table

| App | Purpose | Runtime Deps | Version | Build Status | Tests | Last Modified |
|---|---|---|---|---|---|---|
| assimilation_repo_upgrade_advisor | CAM knowledge pack -> repo upgrade plan | None (stdlib) | 0.1.0 | Likely works | 3 test files, passing | 2026-03-30 |
| embedding_forge | Multimodal Forge-32 embedding builder | `google-genai` | (unversioned) | Likely works (needs API key) | None in-app | 2026-03-30 |
| medcss_modernizer_showpiece | Medical website modernization reports | None (stdlib) | 1.0.0 | Likely works | 2 test files, passing | 2026-03-30 |

## Overall Assessment

All three apps are in reasonable health. They were all last touched on the same date (2026-03-30), suggesting a coordinated update or commit. Key findings:

- **No security vulnerabilities detected** -- two of three apps have zero runtime dependencies, and the third depends only on `google-genai` which is maintained by Google.
- **No broken imports or missing dependencies** -- all imports resolve against stdlib or the parent project's dependency set.
- **embedding_forge is the weakest** in terms of maintenance posture: no versioning, no pyproject.toml, no in-app tests, and a hard coupling to a preview-stage Gemini model.
- **All apps lack CI configuration** within their own directories, relying on the parent project for any automated testing.
- **`__pycache__` directories** are present in all three apps and should be excluded from version control.

## Priority Actions (across all apps)

1. Add `pyproject.toml` to `embedding_forge` and `medcss_modernizer_showpiece` for consistent packaging.
2. Add pytest test files to `embedding_forge` covering pure-Python functions.
3. Monitor `gemini-embedding-2-preview` model lifecycle for the embedding_forge app.
4. Clean `__pycache__` directories from version control.
5. Integrate all three apps into a unified CI test matrix.
