# End UX Redo — User and Developer Experience Assessment

Analyze the repository and assess the experience quality for both end users and developers. Identify friction points, confusing interfaces, poor error messages, and onboarding barriers.

## Instructions

Evaluate the project from two perspectives: (1) an end user trying to accomplish tasks, and (2) a developer trying to understand, modify, and extend the code. For each issue found, rate its impact and propose a concrete fix.

## Section 1: End User Experience

### 1.1 API / CLI / UI Ergonomics

For every user-facing interface (API endpoints, CLI commands, UI components):

| Interface | Type | Issue | Severity | Fix |
|-----------|------|-------|----------|-----|
| `POST /users` | API | Returns 500 with no body on duplicate email | HIGH | Return 409 with `{"error": "email_exists"}` |
| `claw evaluate` | CLI | No `--help` text for options | MEDIUM | Add help strings to all typer options |

Evaluate:
- Are inputs validated with clear error messages?
- Are success/failure states clearly communicated?
- Are defaults sensible? Are required fields obvious?
- Is the API consistent (naming, response shapes, error formats)?

### 1.2 Error Messages Quality

| Location | Current Message | Problem | Better Message |
|----------|----------------|---------|----------------|
| `auth.py:56` | "Error" | Unhelpful — no context | "Authentication failed: invalid API key format" |
| `db.py:23` | Stack trace dumped to user | Exposes internals | "Database connection failed. Check DB_URL config." |

Check for:
- Generic messages ("Something went wrong") without context
- Stack traces exposed to end users
- Error codes without human-readable explanations
- Missing error handling (silent failures)

### 1.3 Accessibility Issues

If the project has a UI, check for:
- Missing alt text, ARIA labels, keyboard navigation
- Color contrast issues, text sizing
- Screen reader compatibility concerns
- Form labels and error associations

If no UI exists, note "N/A — non-UI project" and skip this section.

## Section 2: Developer Experience

### 2.1 Onboarding Friction

Walk through the new developer experience:

| Step | Action | Friction | Fix |
|------|--------|----------|-----|
| 1 | Clone repo | None | - |
| 2 | Install dependencies | `pip install` fails on missing system dep | Document system prerequisites |
| 3 | Run tests | No test command documented | Add to README and Makefile |

List every step from `git clone` to "running and modifying code" with friction points.

### 2.2 Configuration Complexity

| Config Item | Where Defined | Required? | Default? | Documented? |
|-------------|--------------|-----------|----------|-------------|
| `DATABASE_URL` | `.env` | YES | NO | NO |
| `LOG_LEVEL` | `config.toml` | NO | `INFO` | YES |

Flag:
- Required config with no defaults and no documentation
- Config scattered across multiple files/formats
- Conflicting config sources (env var vs file vs CLI arg)
- Secrets in example files or committed to repo

### 2.3 Documentation Gaps

| Task | Documentation Exists? | Location | Quality |
|------|----------------------|----------|---------|
| Initial setup | YES | README.md | OUTDATED |
| Adding a new feature | NO | - | - |
| Running tests | YES | CONTRIBUTING.md | GOOD |
| Deploying | NO | - | - |
| Debugging common issues | NO | - | - |

### 2.4 Code Navigability

- Can a new developer find where a feature is implemented?
- Are file names and directory structure intuitive?
- Are entry points clearly marked?
- Is there a consistent pattern for adding new functionality?

## Section 3: Priority Fixes

### Ranked by User Impact

| Priority | Issue | Affected Users | Fix Complexity |
|----------|-------|---------------|----------------|
| P0 | Critical UX issue | All users | Description of fix |
| P1 | High-impact issue | Most users | Description of fix |
| P2 | Medium-impact issue | Some users | Description of fix |

List top 15 fixes ordered by: (user impact) x (frequency of occurrence).

## Output Format

Use the exact section headers and tables above. Every issue must include a file path where relevant.

Focus on actionable findings with file path evidence.
