# SOTAPPR — State of the Art Practice and Pattern Review

Analyze the repository and compare its implementation against current best practices in its domain. Identify where the project leads, where it lags, and what emerging patterns it should consider adopting.

## Instructions

First determine the project's domain (web API, CLI tool, data pipeline, ML system, mobile app, library, etc.). Then compare its patterns, tooling, and practices against what is considered state-of-the-art for that domain. Be specific — cite actual tools, patterns, and standards, not generic advice.

## Required Output Sections

### 1. Domain Classification

| Aspect | Assessment |
|--------|-----------|
| **Primary domain** | e.g., Python async web API |
| **Secondary domain(s)** | e.g., CLI tooling, data processing |
| **Project maturity** | Prototype / Early / Growing / Mature / Legacy |
| **Team size (inferred)** | Solo / Small (2-5) / Medium (5-15) / Large (15+) |

### 2. Practices Comparison

For each practice area, compare this project against current best practices:

| Practice Area | This Project | Current Best Practice | Gap | Priority |
|--------------|-------------|----------------------|-----|----------|
| **Type safety** | Partial type hints, no strict mode | Full type coverage + `mypy --strict` or pyright | MEDIUM | HIGH |
| **Testing** | pytest, unit only | pytest + hypothesis + integration + mutation testing | SIGNIFICANT | HIGH |
| **Error handling** | Mixed exceptions | Structured errors with error catalog + typed exceptions | MEDIUM | MEDIUM |
| **Dependency management** | requirements.txt | pyproject.toml + uv/pip-tools + lock file | SMALL | LOW |
| **CI/CD** | None | GitHub Actions + auto-test + auto-deploy + auto-release | LARGE | HIGH |

Cover these areas at minimum:
- Type safety and static analysis
- Testing strategy and coverage
- Error handling and observability
- Dependency management and security
- CI/CD and deployment
- Documentation and API specs
- Code formatting and linting
- Security practices
- Performance optimization
- Accessibility (if applicable)

### 3. Where This Project Leads

Identify practices where this project is ahead of or equal to best practices:

| Practice | Implementation | Why It Is Good |
|----------|---------------|----------------|
| Async architecture | Full asyncio throughout | Correct for I/O-bound workload, properly awaited |
| Config management | Pydantic settings with TOML | Type-safe, validated, documented |

### 4. Where This Project Lags

Identify practices where this project is significantly behind:

| Practice | Current State | Best Practice | Impact of Gap | Migration Path |
|----------|-------------|--------------|---------------|----------------|
| No container support | Manual deployment only | Docker + compose + k8s ready | Can't reproduce environments | Add Dockerfile + compose |
| No API versioning | Single unversioned API | Versioned API with deprecation policy | Breaking changes affect all users | Add URL prefix versioning |

### 5. Emerging Patterns to Consider

Patterns and tools gaining adoption in this domain that the project should evaluate:

| Pattern/Tool | What It Does | Adoption Level | Relevance | Effort to Adopt |
|-------------|-------------|---------------|-----------|-----------------|
| Structured logging (structlog) | JSON-formatted logs with context | Mainstream | HIGH — improves debugging | LOW |
| OpenTelemetry | Distributed tracing standard | Growing | MEDIUM — useful if multi-service | MEDIUM |
| Effect systems (result types) | Explicit error handling | Emerging | LOW — Pythonic exceptions work | HIGH |

For each, state honestly whether the adoption effort is justified for this project's scale.

### 6. Tooling Comparison

| Category | Current Tool | Best-in-Class Alternative | Reason to Switch | Reason to Stay |
|----------|-------------|--------------------------|------------------|----------------|
| Formatter | None | `ruff format` | Consistent code style | N/A |
| Linter | None | `ruff check` | Catches bugs early | N/A |
| Type checker | None | `mypy` or `pyright` | Catches type errors | N/A |
| Test runner | `pytest` | `pytest` | Already best choice | - |

### 7. Recommended Adoption Roadmap

Ordered sequence of best-practice adoptions, considering dependencies between them:

| Order | Adoption | Depends On | Benefit |
|-------|----------|-----------|---------|
| 1 | Add ruff for linting + formatting | Nothing | Immediate code quality |
| 2 | Add type annotations | Ruff configured | Catch bugs at edit time |
| 3 | Add CI pipeline | Tests exist | Automated quality gate |
| 4 | Add structured logging | Nothing | Production observability |

## Output Format

Use the exact section headers and tables above. Be specific about tool names and versions. Do not recommend practices that are inappropriate for the project's scale or domain.

Focus on actionable findings with file path evidence.
