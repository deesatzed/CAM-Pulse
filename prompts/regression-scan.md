# Regression Scan — Risk Surface Identification

Analyze the repository and identify areas where changes are most likely to cause regressions. Map the fragile surfaces, untested boundaries, and shared state that make breaking changes likely.

## Instructions

Think like a QA engineer whose job is to predict what will break next. Examine code coupling, test gaps, shared state, and change patterns to identify the highest-risk areas.

## Required Output Sections

### 1. Recently Changed Files Without Tests

If git history is available, identify files with recent changes that lack corresponding tests:

| File | Recent Changes | Test File Exists? | Test Coverage | Risk |
|------|---------------|-------------------|---------------|------|
| `src/api/auth.py` | 15 changes in last month | YES | Partial — no edge cases | HIGH |
| `src/core/processor.py` | 8 changes in last month | NO | None | CRITICAL |

If no git history is available, identify source files that have no corresponding test file.

### 2. Public API Surfaces Without Contracts

Identify every public interface that external consumers depend on:

| Interface | Type | Has Contract? | Breaking Change Risk |
|-----------|------|--------------|---------------------|
| `POST /api/v1/users` | REST API | No schema validation | HIGH — any field change breaks clients |
| `class DataProcessor` | Python class | No abstract base | MEDIUM — method signature changes possible |
| `claw evaluate` | CLI command | No arg validation | MEDIUM — flag changes break scripts |

"Contract" means: schema validation, type annotations, interface definition, API spec (OpenAPI), or documentation that declares the stable surface.

### 3. Shared State Analysis

Find all mutable state shared between components:

| Shared State | Location | Writers | Readers | Protection | Risk |
|-------------|----------|---------|---------|------------|------|
| `_cache` dict | `cache.py:5` | `updater.py`, `api.py` | `renderer.py`, `api.py` | None (no lock) | HIGH |
| `config` global | `settings.py:1` | `main.py` (startup only) | All modules | Read-only after init | LOW |
| `users` table | `schema.sql` | `auth.py`, `admin.py` | `api.py`, `reports.py` | DB transactions | MEDIUM |

Flag any shared state without synchronization or clear ownership.

### 4. Coupling Hotspots

Identify files/modules that are imported by the most other files:

| File | Imported By (count) | Type of Coupling | Fragility |
|------|-------------------|-----------------|-----------|
| `src/utils.py` | 28 files | Utility functions | HIGH — any change ripples everywhere |
| `src/models/user.py` | 15 files | Data model | HIGH — schema change breaks all consumers |
| `src/config.py` | 22 files | Configuration | MEDIUM — mostly read-only |

### 5. Migration and Data Safety Risks

| Risk | Location | Description | Impact |
|------|----------|-------------|--------|
| No migration rollback | `migrations/` | Migrations have no `down()` method | Data loss on failed deploy |
| Destructive migration | `migrations/005.py` | `DROP COLUMN` without data backup | Irreversible data loss |
| Schema drift | `models.py` vs `schema.sql` | ORM model differs from actual schema | Silent data corruption |

### 6. Backwards Compatibility Risks

| Component | Change Type | Who Breaks | Mitigation Exists? |
|-----------|------------|------------|-------------------|
| `/api/v1/users` response | Field removed | All API consumers | NO — no versioning |
| `Config` class constructor | New required param | All instantiation sites | NO — no default value |
| `output.json` format | Key renamed | Downstream pipelines | NO — no schema contract |

### 7. Regression Risk Summary

| Risk Level | Count | Areas |
|------------|-------|-------|
| CRITICAL | N | Untested high-change files, destructive migrations |
| HIGH | N | Uncontracted APIs, shared mutable state |
| MEDIUM | N | Coupling hotspots, missing edge case tests |
| LOW | N | Well-tested stable code |

### Top 10 Regression Risks

For each:

1. **What could break** — specific scenario
2. **Where** — file paths involved
3. **Trigger** — what change would cause the regression
4. **Detection** — would existing tests catch it? (yes/no)
5. **Mitigation** — what test or guard to add

## Output Format

Use the exact section headers and tables above. Prioritize findings that have the highest likelihood of causing production issues.

Focus on actionable findings with file path evidence.
