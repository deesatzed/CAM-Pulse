# Claim Gate — Assertion Verification

Analyze the repository and find every claim, assertion, or promise made in the codebase. Verify each against the actual code. This is a truth audit.

## Instructions

A "claim" is any statement that asserts something is true about the project. Claims appear in READMEs, docstrings, comments, error messages, marketing copy, changelogs, and even variable names that imply behavior. Find them all and verify them.

## Where to Find Claims

1. **README and docs/** — feature lists, architecture descriptions, setup instructions
2. **Docstrings** — function/class/module descriptions
3. **Comments** — inline assertions ("this is thread-safe", "handles all edge cases")
4. **TODO/FIXME/HACK markers** — implicit claims about what needs fixing
5. **Version strings** — semantic versioning claims, "v1.0 stable"
6. **CI/CD configs** — "runs on Python 3.9-3.12" (do tests actually pass on all?)
7. **Package metadata** — description, keywords, classifiers
8. **Error messages** — "Invalid email format" (does it actually validate email format?)

## Verdict Definitions

- **VERIFIED** — claim is accurate based on code evidence
- **PARTIAL** — claim is directionally correct but incomplete or overstated
- **FALSE** — claim is contradicted by the code
- **UNVERIFIABLE** — cannot be confirmed or denied from the codebase alone (needs runtime testing, external service check, etc.)

## Required Output

### Claims Registry

| # | Claim | Source | Verdict | Evidence |
|---|-------|--------|---------|----------|
| 1 | "Supports Python 3.9+" | README.md:15 | PARTIAL | pyproject.toml requires >=3.11, contradicts claim |
| 2 | "All endpoints are authenticated" | docs/api.md:8 | FALSE | `/health` and `/metrics` have no auth middleware (`src/routes.py:22,45`) |
| 3 | "Thread-safe singleton" | `src/cache.py:5` comment | VERIFIED | Uses `threading.Lock` correctly at line 12 |

### Verdicts by Category

| Category | VERIFIED | PARTIAL | FALSE | UNVERIFIABLE | Total |
|----------|----------|---------|-------|-------------|-------|
| README claims | N | N | N | N | N |
| Docstring claims | N | N | N | N | N |
| Comment assertions | N | N | N | N | N |
| TODO/FIXME items | N | N | N | N | N |
| Version/metadata | N | N | N | N | N |
| Error messages | N | N | N | N | N |
| **Total** | **N** | **N** | **N** | **N** | **N** |

### Critical FALSE Claims

For each FALSE verdict, provide:

1. **The claim** — exact quote and location
2. **What the code actually does** — with file:line references
3. **Impact** — what breaks if someone trusts this claim
4. **Fix** — update the claim or update the code (recommend which)

### TODO/FIXME Audit

| Marker | File:Line | Age (if determinable) | Still Relevant? | Priority |
|--------|-----------|----------------------|-----------------|----------|
| TODO: add caching | `src/api.py:88` | Unknown | YES — no caching exists | HIGH |
| FIXME: race condition | `src/worker.py:34` | Unknown | YES — no lock added | CRITICAL |
| HACK: temporary workaround | `src/parse.py:12` | Unknown | Unclear | MEDIUM |

## Output Format

Use the exact section headers and tables above. List a minimum of 15 claims if the codebase is non-trivial. Every verdict must cite file paths.

Focus on actionable findings with file path evidence.
