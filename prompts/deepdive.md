# Deep Dive Technical Analysis

Analyze the repository and produce a comprehensive technical assessment covering architecture, code quality, dependencies, testing, and feature completeness.

## Instructions

Read every source file. Evaluate patterns, not just surface-level metrics. Distinguish between intentional design choices and accidental complexity. Provide file paths for every finding.

## Required Output Sections

### 1. Architecture Patterns

Identify the architectural patterns in use:

- **Overall pattern** (MVC, layered, hexagonal, microservices, monolith, etc.)
- **Data flow** — how data moves from input to output (trace the primary path)
- **Dependency direction** — do dependencies point inward (good) or scatter randomly?
- **Boundary enforcement** — are module boundaries respected or violated?

For each pattern identified, note whether it is applied consistently or only partially.

### 2. Code Quality Assessment

| Metric | Finding | Files of Concern |
|--------|---------|-----------------|
| **Cyclomatic complexity** | Functions with complexity > 10 | List file:function |
| **Duplication** | Blocks of 10+ similar lines | List file pairs |
| **Naming consistency** | Conventions used and violations | List examples |
| **Function length** | Functions > 50 lines | List file:function |
| **File length** | Files > 500 lines | List files |
| **Dead code** | Unreachable or unused code | List locations |

### 3. Error Handling Patterns

- What error handling strategy is used? (exceptions, result types, error codes, mixed)
- Are errors caught and swallowed silently anywhere? (list locations)
- Are error messages user-friendly or developer-friendly?
- Are there unhandled edge cases in critical paths?
- Is there a global error handler or boundary?

### 4. Dependency Health

| Dependency | Current Version | Latest Version | Age Gap | Vulnerability? | Critical? |
|------------|----------------|----------------|---------|---------------|-----------|
| name       | x.y.z          | a.b.c          | N months| yes/no        | yes/no    |

Flag any dependency that is:
- More than 12 months behind latest
- Known to have CVEs
- Unmaintained (no release in 24+ months)
- Pinned to an exact version without justification

### 5. Test Coverage Assessment

- **Test framework(s)** in use
- **Total test count** (if determinable)
- **Coverage percentage** (if measurable or reported)
- **Test types present**: unit, integration, e2e, property-based, snapshot
- **Untested critical paths**: list the most important code paths that lack tests
- **Test quality concerns**: brittle tests, excessive mocking, tests that test implementation not behavior

### 6. Feature Completion Matrix

| Feature | Status | Evidence |
|---------|--------|----------|
| Feature name | COMPLETE / PARTIAL / STUBBED / MISSING | File paths showing implementation state |

List every user-facing feature you can identify. Trace each from its entry point to its data source. Mark implementation completeness honestly.

## Output Format

Use the exact section headers and table formats above. Every finding must include at least one file path as evidence.

Focus on actionable findings with file path evidence.
