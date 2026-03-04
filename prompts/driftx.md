# DriftX — Adversarial Documentation Drift Audit

Analyze the repository and identify every place where documentation, comments, or claims diverge from what the code actually does. Score the overall drift.

## Instructions

Compare claims against reality systematically. Read the documentation, then read the code it describes. Believe the code, not the docs. Be adversarial — assume every claim is wrong until you verify it.

## Required Output Sections

### 1. README Drift

For each section of the README:

| README Claim | Actual State | Drift Type | Severity |
|-------------|-------------|------------|----------|
| "Supports PostgreSQL and MySQL" | Only PostgreSQL adapter exists | OVERSTATED | HIGH |
| "Run `npm start` to launch" | Package.json has no `start` script | STALE | CRITICAL |

Drift types: STALE (was once true), OVERSTATED (partially true), FALSE (never true), ASPIRATIONAL (planned but not built)

### 2. Comment Drift

Find comments that contradict the code they annotate:

| File:Line | Comment Says | Code Does | Drift |
|-----------|-------------|-----------|-------|
| `src/auth.py:45` | "Validates JWT token" | Function is empty, returns True | FALSE |
| `src/db.py:12` | "Connection pool size: 10" | Hardcoded to 25 | STALE |

Scan for:
- Commented-out code with no explanation
- TODO/FIXME comments older than 6 months (check git blame if possible)
- Docstrings that describe different parameters than the function accepts
- Type hints that disagree with runtime behavior

### 3. Dead Code Paths

| Location | Type | Last Referenced | Safe to Remove? |
|----------|------|-----------------|-----------------|
| `src/legacy/old_api.py` | Entire file | No imports found | YES |
| `src/utils.py:format_v1()` | Function | Called nowhere | YES |

Types: unused function, unused import, unused variable, unreachable branch, unused file, unused dependency

### 4. Unused Exports and Interfaces

List every public export (exported function, class, constant, API endpoint) that has no consumers within the codebase:

- File path and export name
- Whether it appears in documentation
- Whether external consumers might depend on it

### 5. Ghost Configuration

Find config references that point to nothing:

| Config Key | Defined In | Referenced By | Actual Effect |
|-----------|-----------|---------------|---------------|
| `REDIS_URL` | `.env.example` | Nothing imports it | NONE — dead config |
| `FEATURE_X_ENABLED` | `config.yaml` | `feature_x.py` was deleted | NONE — orphaned |

### 6. Overall Drift Score

Calculate a drift percentage:

```
drift_score = (drifted_items / total_items_audited) * 100
```

| Category | Items Audited | Items Drifted | Drift % |
|----------|--------------|---------------|---------|
| README sections | N | N | N% |
| Code comments | N | N | N% |
| Dead code paths | N/A | N found | N/A |
| Config references | N | N | N% |
| **Overall** | **N** | **N** | **N%** |

Interpret the score:
- 0-10%: Well-maintained documentation
- 11-25%: Normal drift, needs cleanup sprint
- 26-50%: Significant drift, documentation is unreliable
- 51-100%: Critical drift, documentation is actively misleading

## Output Format

Use the exact section headers and tables above. Every finding must reference specific file paths and line numbers.

Focus on actionable findings with file path evidence.
