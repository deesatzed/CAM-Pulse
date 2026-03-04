# Debt Tracker — Technical Debt Catalog

Analyze the repository and catalog all technical debt: shortcuts taken, quality compromises, deferred maintenance, and accumulated complexity. Produce a prioritized remediation list.

## Instructions

Technical debt is any code that works today but makes tomorrow harder. Search exhaustively across the entire codebase. Do not limit yourself to TODO comments — most debt is unmarked.

## Debt Categories to Search

### 1. Marked Debt (Explicit)
- `TODO` comments — unfulfilled intentions
- `FIXME` comments — known bugs deferred
- `HACK` / `WORKAROUND` comments — acknowledged shortcuts
- `XXX` / `TEMP` / `TEMPORARY` markers
- `@deprecated` annotations without replacement

### 2. Unmarked Debt (Implicit)
- **Copy-paste duplication** — similar code blocks in 2+ locations
- **Missing abstractions** — repeated patterns that should be a shared utility
- **God objects/functions** — classes or functions doing too many things (>200 lines)
- **Primitive obsession** — using strings/ints where domain types should exist
- **Feature flags never cleaned up** — conditional code for features long since shipped
- **Commented-out code** — dead code kept "just in case"
- **Inconsistent patterns** — same thing done different ways in different places

### 3. Dependency Debt
- **Deprecated APIs** — using library functions marked as deprecated
- **Pinned old versions** — dependencies held back without documented reason
- **Unused dependencies** — declared but never imported
- **Missing dependency locks** — no lock file for reproducible builds

### 4. Test Debt
- **Missing tests for critical paths** — authentication, payment, data mutation
- **Brittle tests** — tests that break on unrelated changes
- **Test-implementation coupling** — tests that verify internal structure not behavior
- **Missing edge case coverage** — only happy path tested
- **Slow test suite** — tests that discourage running them

### 5. Infrastructure Debt
- **Manual deployment steps** — anything not automated
- **Missing monitoring/alerting** — no observability
- **No CI/CD pipeline** — or a broken/incomplete one
- **Missing environment parity** — dev differs from prod

## Required Output

### Debt Inventory

| # | Type | Severity | Location | Description | Remediation |
|---|------|----------|----------|-------------|-------------|
| 1 | Marked (TODO) | HIGH | `api.py:45` | "TODO: add rate limiting" — public API has no rate limiting | Implement rate limiter middleware |
| 2 | Duplication | MEDIUM | `handlers/a.py:20`, `handlers/b.py:35` | 40 lines of identical validation logic | Extract to shared validator |
| 3 | Missing test | HIGH | `payment.py` | Payment processing has zero test coverage | Add unit and integration tests |

### Severity Definitions

- **BLOCKING** — prevents deployment, causes data loss, or is a security vulnerability
- **HIGH** — significant quality/reliability risk, should be fixed in next sprint
- **MEDIUM** — real debt that slows development, fix within next quarter
- **LOW** — cleanup work, improves readability/maintainability

### Summary by Category

| Category | BLOCKING | HIGH | MEDIUM | LOW | Total |
|----------|----------|------|--------|-----|-------|
| Marked (TODO/FIXME) | N | N | N | N | N |
| Duplication | N | N | N | N | N |
| Missing abstractions | N | N | N | N | N |
| Dependency debt | N | N | N | N | N |
| Test debt | N | N | N | N | N |
| Infrastructure debt | N | N | N | N | N |
| **Total** | **N** | **N** | **N** | **N** | **N** |

### Top 10 Remediation Priorities

For each of the top 10 items:

1. **What** — description of the debt
2. **Where** — file paths involved
3. **Why** — impact on reliability, velocity, or security
4. **How** — specific steps to remediate
5. **Verify** — how to confirm the debt is resolved

## Output Format

Use the exact section headers and tables above. Number every debt item for cross-referencing.

Focus on actionable findings with file path evidence.
