# Mitigen — Prioritized Remediation Roadmap

Analyze the repository and synthesize all quality, debt, documentation, and architecture findings into a single prioritized remediation roadmap. This is the action plan that tells developers exactly what to fix and in what order.

## Instructions

Review the entire codebase holistically. Identify every issue that needs remediation, then prioritize ruthlessly. Every item must be specific enough for a developer to act on without further investigation. No vague recommendations.

## Priority Definitions

- **P0 — Do Now** — Security vulnerabilities, data loss risks, broken core functionality, blocking issues. These must be fixed before any new feature work.
- **P1 — Do Soon** — Significant quality issues, high-impact bugs, critical missing tests, misleading documentation that could cause user harm. Fix within the next development cycle.
- **P2 — Do Eventually** — Code quality improvements, minor documentation fixes, refactoring opportunities, nice-to-have features. Schedule as capacity allows.

## Required Output

### P0 — Immediate Action Required

For each P0 item:

| # | Issue | Category | Files | Impact |
|---|-------|----------|-------|--------|
| P0-1 | Description | security/data-loss/broken | File paths | What breaks if not fixed |

**Detailed remediation for each P0:**

```
P0-1: [Title]
WHAT: Specific description of the problem
WHERE: Exact file paths and line numbers
WHY: Impact on users, data, or security
FIX: Step-by-step instructions to remediate
  1. Open file X
  2. Change Y to Z
  3. Add test that verifies the fix
VERIFY: How to confirm the fix works
  - Run: specific test command
  - Check: specific behavior to observe
```

### P1 — Next Cycle

For each P1 item:

| # | Issue | Category | Files | Impact |
|---|-------|----------|-------|--------|
| P1-1 | Description | quality/testing/docs | File paths | What improves when fixed |

**Detailed remediation for each P1:**

```
P1-1: [Title]
WHAT: Description
WHERE: File paths
WHY: Impact
FIX: Steps to fix
VERIFY: How to confirm
```

### P2 — Backlog

| # | Issue | Category | Files | Benefit |
|---|-------|----------|-------|---------|
| P2-1 | Description | refactor/cleanup/enhancement | File paths | What improves |

P2 items need one-line fix descriptions, not full remediation plans.

### Dependency Graph

Identify items that depend on other items being fixed first:

```
P0-2 (fix auth) --> P1-3 (add auth tests) --> P1-7 (add API contract tests)
P0-1 (fix data migration) --> P1-1 (add migration rollback)
P1-5 (extract shared util) --> P2-3 (reduce duplication)
```

### Summary Statistics

| Priority | Count | Categories |
|----------|-------|------------|
| P0 | N | List affected categories |
| P1 | N | List affected categories |
| P2 | N | List affected categories |
| **Total** | **N** | - |

### Quick Wins

Items that can be fixed in under 30 minutes with high impact:

| # | Item | Fix | Impact |
|---|------|-----|--------|
| 1 | Reference from above | One-line description | Who benefits |

### Risk If Ignored

For the P0 and P1 items, describe what happens if they remain unfixed:

| Item | 30-Day Risk | 90-Day Risk |
|------|-----------|-----------|
| P0-1 | Specific consequence | Escalated consequence |
| P1-1 | Specific consequence | Escalated consequence |

## Output Format

Use the exact section headers and tables above. Every item must include exact file paths. The remediation steps must be specific enough that a developer can execute them without asking clarifying questions.

Focus on actionable findings with file path evidence.
