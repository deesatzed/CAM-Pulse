# Assumption Registry — Implicit Assumptions Audit

Analyze the repository and identify every implicit assumption baked into the code. These are unstated beliefs the code relies on that could break when conditions change.

## Instructions

Read the code looking for decisions that assume a particular environment, data shape, timing, or behavior without explicitly checking or documenting the assumption. The most dangerous assumptions are the ones nobody wrote down.

## Categories of Assumptions to Find

### 1. Environment Assumptions
- Hardcoded file paths (e.g., `/tmp/`, `C:\Users\`)
- Platform-specific code without platform checks
- Assumed available system commands (`curl`, `git`, `docker`)
- Assumed network availability or latency
- Assumed disk space or memory availability

### 2. Data Shape Assumptions
- Assumed JSON structure without validation
- Assumed database column existence without migration checks
- Assumed non-null values without null checks
- Assumed string encoding (UTF-8 without declaration)
- Assumed numeric ranges without bounds checking

### 3. Concurrency Assumptions
- Assumed single-threaded execution
- Shared mutable state without synchronization
- Assumed operation ordering without explicit sequencing
- Race conditions in file access, DB writes, or cache updates

### 4. Security Assumptions
- Assumed trusted input (no sanitization)
- Assumed internal network (no auth on internal APIs)
- Assumed HTTPS without enforcement
- Hardcoded credentials or API keys
- Assumed permission levels

### 5. Timing Assumptions
- Hardcoded timeouts or sleep durations
- Assumed operation completion speed
- Assumed clock synchronization between services
- Assumed retry counts or backoff strategies

### 6. Business Logic Assumptions
- Magic numbers without explanation
- Hardcoded business rules (tax rates, limits, thresholds)
- Assumed user behavior or input patterns
- Assumed feature flag states

## Required Output

### Assumptions Registry Table

| # | Assumption | Location | Category | Risk | Documented? | Mitigation |
|---|-----------|----------|----------|------|-------------|------------|
| 1 | Max file size is 10MB | `upload.py:23` `MAX_SIZE = 10_485_760` | Data Shape | MEDIUM | NO | Add config option, document limit |
| 2 | Redis is on localhost:6379 | `cache.py:5` | Environment | HIGH | NO | Use env var, add connection check |
| 3 | Only one worker writes to this table | `sync.py:78` | Concurrency | HIGH | NO | Add row-level locking |

### Risk Ratings

- **LOW** — assumption is reasonable and unlikely to break (e.g., UTF-8 text)
- **MEDIUM** — assumption could break in foreseeable scenarios (e.g., single-server assumption)
- **HIGH** — assumption is fragile and will break under real-world conditions (e.g., no input validation on user-supplied data)

### Magic Numbers Inventory

| Value | Location | Apparent Meaning | Should Be |
|-------|----------|-----------------|-----------|
| `3600` | `token.py:15` | Token expiry in seconds (1 hour) | Named constant + config |
| `0.85` | `scorer.py:42` | Unknown threshold | Named constant + documentation |
| `100` | `paginator.py:8` | Default page size | Config with documented default |

### Summary

| Risk Level | Count | Documented | Undocumented |
|------------|-------|------------|--------------|
| HIGH | N | N | N |
| MEDIUM | N | N | N |
| LOW | N | N | N |
| **Total** | **N** | **N** | **N** |

### Priority Fixes

List the top 10 assumptions that should be addressed first, ordered by risk. For each:

1. What the assumption is
2. Where it lives (file:line)
3. What could go wrong
4. How to fix it (add validation, make configurable, add documentation)

## Output Format

Use the exact section headers and tables above. Aim for a minimum of 20 assumptions in a non-trivial codebase.

Focus on actionable findings with file path evidence.
