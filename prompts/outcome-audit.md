# Outcome Audit — Quantified Claims Verification

Analyze the repository and find every quantified claim — any statement that includes a number, percentage, benchmark, or measurable target. Measure or estimate the actual value and compare.

## Instructions

Search for numeric claims in all documentation, comments, configs, and marketing materials. For each claim, determine if the number is verifiable from the codebase and what the actual value is. Do not accept claims at face value.

## What Counts as a Quantified Claim

- Performance benchmarks ("handles 10k requests/sec")
- Coverage percentages ("95% test coverage")
- Uptime/reliability targets ("99.9% uptime SLA")
- Scale assertions ("supports 1M concurrent users")
- Size claims ("lightweight at 50KB")
- Speed claims ("deploys in under 2 minutes")
- Completeness claims ("covers all 47 API endpoints")
- Version compatibility ("works with Node 16-20")

## Required Output

### Quantified Claims Table

| # | Claim | Source | Claimed Value | Actual Value | Method | Confidence | Verdict |
|---|-------|--------|--------------|-------------|--------|------------|---------|
| 1 | Test coverage | README.md:30 | 95% | 67% | Ran `pytest --cov` config analysis | HIGH | FALSE |
| 2 | "Handles 10k RPS" | docs/perf.md:5 | 10,000 RPS | ~800 RPS | Single-threaded, no connection pooling, sync DB calls | MEDIUM | FALSE |
| 3 | "50KB bundle" | package.json description | 50KB | Unknown | No build config found to verify | LOW | UNVERIFIABLE |

### Measurement Methods

For each claim you attempted to verify, explain your method:

- **Static analysis** — counted files, lines, endpoints, etc.
- **Configuration review** — checked limits, pool sizes, timeouts in config
- **Architecture inference** — estimated based on patterns (single-thread, sync I/O, etc.)
- **Tool output** — referenced existing reports (coverage.xml, benchmark results)
- **Cannot measure** — explain what would be needed to measure

### Confidence Levels

- **HIGH** — directly measurable from the codebase (file count, dependency count, config values)
- **MEDIUM** — estimable from architecture and patterns (throughput, memory usage)
- **LOW** — requires runtime measurement that cannot be done from code alone
- **NONE** — pure marketing claim with no technical basis to evaluate

### Verdicts Summary

| Verdict | Count | Percentage |
|---------|-------|------------|
| VERIFIED (actual matches or exceeds claim) | N | N% |
| CLOSE (within 20% of claim) | N | N% |
| FALSE (actual is materially different) | N | N% |
| UNVERIFIABLE (cannot measure from code) | N | N% |

### Impact Assessment

For each FALSE claim, assess:

- **Who is affected** — end users, developers, ops team, stakeholders
- **What could go wrong** — capacity planning failures, broken SLAs, misleading metrics
- **Recommended action** — update the claim to match reality, or fix the code to match the claim

## Output Format

Use the exact section headers and tables above. If fewer than 5 quantified claims exist, note that the project lacks quantified assertions and recommend where they should be added.

Focus on actionable findings with file path evidence.
