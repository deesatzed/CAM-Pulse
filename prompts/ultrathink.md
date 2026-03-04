# Ultrathink — Multi-Perspective Codebase Analysis

Analyze the repository from four distinct professional perspectives simultaneously. Each perspective has different priorities and sees different problems. Synthesize all four into a unified action plan.

## Instructions

Read the entire codebase four times, each time through a different lens. Do not let one perspective dominate. Each perspective is equally valid. After completing all four analyses, merge the findings into a single prioritized plan that respects all four viewpoints.

## Perspective 1: Security Researcher

Your goal is to find vulnerabilities that could be exploited.

### Attack Surface Inventory

| Surface | Location | Exposure | Current Protection |
|---------|----------|----------|-------------------|
| HTTP endpoints | `src/api/` | Public internet | Auth middleware on most routes |
| File upload | `src/upload.py` | Authenticated users | Size limit only |
| Database queries | `src/db/` | Internal | Parameterized queries (mostly) |

### Vulnerability Assessment

| # | Vulnerability | Type | Location | Severity | Exploitability |
|---|-------------|------|----------|----------|---------------|
| S1 | User input passed to SQL without parameterization | SQL Injection | `search.py:34` | CRITICAL | Easy |
| S2 | JWT secret hardcoded | Auth Bypass | `config.py:12` | CRITICAL | Easy if code leaks |
| S3 | No rate limiting on login | Brute Force | `auth.py:56` | HIGH | Easy |

For each vulnerability:
- **Attack scenario** — how an attacker exploits this
- **Impact** — what they gain (data access, privilege escalation, denial of service)
- **Fix** — specific code change to remediate

## Perspective 2: Performance Engineer

Your goal is to find bottlenecks, waste, and scalability limits.

### Resource Usage Analysis

| Resource | Usage Pattern | Location | Concern |
|----------|-------------|----------|---------|
| Memory | Loads entire dataset into memory | `loader.py:45` | OOM on large datasets |
| CPU | Synchronous crypto operations | `auth.py:89` | Blocks event loop |
| Disk I/O | Writes temp files for every request | `handler.py:23` | Disk contention |
| Network | Sequential API calls | `client.py:12` | Latency stacking |

### Bottleneck Identification

| # | Bottleneck | Location | Current Performance | Expected Impact | Fix |
|---|-----------|----------|-------------------|-----------------|-----|
| P1 | N+1 database query | `views.py:78` | O(n) queries per page load | 10x slower as data grows | Add eager loading / join |
| P2 | No connection pooling | `db.py:5` | New connection per query | Connection overhead dominates | Add connection pool |
| P3 | Unbounded cache | `cache.py:1` | Grows forever | Memory exhaustion | Add LRU eviction |

### Scalability Limits

| Component | Current Limit | What Triggers It | Scaling Path |
|-----------|--------------|-----------------|--------------|
| SQLite writes | ~50 concurrent writes | Multiple workers | PostgreSQL or write queue |
| In-process cache | Single process | Horizontal scaling | Redis / Memcached |

## Perspective 3: New Hire (Day 1 Onboarding)

Your goal is to understand the codebase well enough to make a safe change.

### First Impressions

- Can I understand what this project does within 5 minutes of reading? (YES/NO + why)
- Can I run the project locally within 30 minutes? (YES/NO + blockers)
- Can I find where a specific feature is implemented? (YES/NO + navigation difficulty)
- Can I run the tests and understand what they cover? (YES/NO + issues)

### Confusion Points

| # | Confusion | Location | What Would Help |
|---|-----------|----------|-----------------|
| N1 | Purpose of this module unclear | `src/core/engine.py` | Module-level docstring explaining role |
| N2 | Multiple ways to do the same thing | `src/utils/` vs `src/helpers/` | Consolidate or document when to use which |
| N3 | Circular import pattern | `models.py` <-> `services.py` | Refactor dependency direction |

### Missing Orientation Materials

| Material | Exists? | Quality |
|----------|---------|---------|
| Architecture overview / diagram | YES/NO | - |
| Getting started guide | YES/NO | - |
| Code style guide | YES/NO | - |
| Decision log (ADRs) | YES/NO | - |
| Glossary of domain terms | YES/NO | - |

## Perspective 4: Ops Engineer (Production Readiness)

Your goal is to assess whether this can run reliably in production.

### Production Readiness Checklist

| Requirement | Status | Evidence |
|-------------|--------|----------|
| Health check endpoint | YES/NO | File path |
| Graceful shutdown | YES/NO | Signal handling code |
| Structured logging | YES/NO | Logging configuration |
| Metrics / monitoring | YES/NO | Instrumentation code |
| Error alerting | YES/NO | Alert configuration |
| Backup strategy | YES/NO | Backup scripts/config |
| Disaster recovery | YES/NO | Recovery documentation |
| Configuration via env vars | YES/NO | Config loading code |
| Secret management | YES/NO | How secrets are handled |
| Resource limits | YES/NO | Memory/CPU limits defined |

### Operational Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|-----------|--------|------------|
| O1 | No log rotation | HIGH | Disk fills up | Add logrotate config |
| O2 | No circuit breaker for external APIs | MEDIUM | Cascading failure | Add circuit breaker pattern |
| O3 | No database connection limit | HIGH | Connection exhaustion | Add pool with max connections |

## Unified Action Plan

Merge all four perspectives into a single prioritized list. Tag each item with which perspectives flagged it:

| Priority | Action | Perspectives | Location | Impact |
|----------|--------|-------------|----------|--------|
| 1 | Fix SQL injection in search | Security, Ops | `search.py:34` | Critical vulnerability |
| 2 | Add connection pooling | Performance, Ops | `db.py:5` | Reliability + performance |
| 3 | Add architecture docs | New Hire, Ops | `docs/` | Onboarding + incident response |
| 4 | Add rate limiting | Security, Performance | `api/middleware/` | Abuse prevention |

Items flagged by 3+ perspectives should be prioritized highest. Items flagged by only 1 perspective should be evaluated for domain-specific importance.

## Output Format

Use the exact section headers and tables above. Complete all four perspectives before synthesizing. Every finding must include file paths.

Focus on actionable findings with file path evidence.
