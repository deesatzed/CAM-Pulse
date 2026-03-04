# Docs Redo — Documentation Quality Audit

Analyze the repository and audit all documentation for accuracy, completeness, and usefulness. Produce a prioritized list of documentation fixes.

## Instructions

Read every piece of documentation in the repository: README, doc files, inline comments, docstrings, type annotations, config file comments, CI/CD descriptions, and commit messages. Evaluate each against the actual code.

## Required Output Sections

### 1. README Assessment

| Section | Exists? | Accurate? | Complete? | Issue |
|---------|---------|-----------|-----------|-------|
| Project description | YES/NO | YES/NO | YES/NO | Description of problem |
| Installation instructions | YES/NO | YES/NO | YES/NO | Missing step X |
| Usage examples | YES/NO | YES/NO | YES/NO | Example uses old API |
| Configuration guide | YES/NO | YES/NO | YES/NO | 3 env vars undocumented |
| Contributing guide | YES/NO | YES/NO | YES/NO | - |
| License | YES/NO | YES/NO | YES/NO | - |
| Changelog | YES/NO | YES/NO | YES/NO | Last entry 6 months ago |

### 2. API Documentation

For every public API (REST endpoints, CLI commands, library functions):

| API | Documented? | Accurate? | Examples? | Issue |
|-----|------------|-----------|-----------|-------|
| `POST /api/users` | YES | NO | NO | Response schema changed, docs not updated |
| `claw evaluate` | YES | YES | YES | - |
| `DataProcessor.run()` | NO | N/A | N/A | Public method with no docstring |

### 3. Inline Documentation Quality

| Metric | Count | Percentage |
|--------|-------|------------|
| Functions with docstrings | N / total | N% |
| Classes with docstrings | N / total | N% |
| Modules with module-level docstrings | N / total | N% |
| Type-annotated function signatures | N / total | N% |

List the 10 most important functions/classes that lack documentation.

### 4. Setup Instructions Walkthrough

Execute the documented setup steps mentally and identify failures:

| Step | Instruction | Works? | Issue |
|------|------------|--------|-------|
| 1 | `git clone ...` | YES | - |
| 2 | `pip install -r requirements.txt` | NO | File is `requirements.txt` but project uses `pyproject.toml` |
| 3 | `python manage.py migrate` | NO | Undocumented prerequisite: database must exist first |

### 5. Environment Variables and Configuration

| Variable/Config | Documented? | Where? | Default Provided? | Required? |
|----------------|-------------|--------|-------------------|-----------|
| `DATABASE_URL` | NO | - | NO | YES |
| `API_KEY` | YES | README | NO | YES |
| `LOG_LEVEL` | YES | .env.example | `INFO` | NO |

List every environment variable or config value the code reads, whether it is documented, and whether a default exists.

### 6. Stale Examples

Find code examples in documentation that no longer work:

| Location | Example | Issue | Fix |
|----------|---------|-------|-----|
| README.md:45 | `from app import create_app` | Module renamed to `src.app` | Update import path |
| docs/api.md:20 | `curl localhost:3000/api` | Port changed to 8080 | Update URL |

### 7. Missing Documentation

List documentation that should exist but does not:

| Topic | Why Needed | Priority |
|-------|-----------|----------|
| Architecture overview | >10 modules with no explanation of how they relate | HIGH |
| Error handling guide | Custom exceptions exist but no guide on when/how they occur | MEDIUM |
| Deployment runbook | Production config exists but no deployment docs | HIGH |

### 8. Prioritized Fix List

| Priority | Fix | Location | Type |
|----------|-----|----------|------|
| P0 | Fix broken setup instructions | README.md | Accuracy |
| P0 | Document required env vars | README.md / .env.example | Completeness |
| P1 | Update API examples to match current code | docs/api.md | Accuracy |
| P1 | Add docstrings to public API | `src/core/*.py` | Completeness |
| P2 | Add architecture diagram | docs/ | New content |

## Output Format

Use the exact section headers and tables above. Every finding must reference specific file paths.

Focus on actionable findings with file path evidence.
