# Handoff Packet — Continuation-Ready Project Brief

Analyze the repository and generate a comprehensive handoff document that enables a new developer to take over this project with minimal ramp-up time.

## Instructions

Write this as if you are handing this project to a competent developer who has never seen this codebase. They need to understand the project state, make safe changes, and avoid known pitfalls — all within their first day.

## Required Output Sections

### 1. Project State Summary

| Aspect | Status |
|--------|--------|
| **Overall health** | HEALTHY / NEEDS WORK / FRAGILE / CRITICAL |
| **Code quality** | Rating 1-10 with one-line justification |
| **Test coverage** | Percentage or qualitative assessment |
| **Documentation** | GOOD / ADEQUATE / POOR / MISSING |
| **Deployment** | AUTOMATED / SEMI-MANUAL / MANUAL / NONE |
| **Active development?** | YES (recent commits) / STALE / ABANDONED |

### 2. What Works

List every feature or subsystem that is fully functional and reliable:

| Component | Status | Confidence | Notes |
|-----------|--------|------------|-------|
| User authentication | WORKING | HIGH | OAuth + email login both tested |
| Data export | WORKING | MEDIUM | Works for CSV, PDF untested |

### 3. What Is Broken

List every known issue, bug, or failure:

| Issue | Location | Severity | Workaround |
|-------|----------|----------|------------|
| Memory leak in worker | `worker.py:89` | HIGH | Restart worker every 4 hours |
| CSS broken on mobile | `styles/main.css` | MEDIUM | None |

### 4. What Is In Progress

List any incomplete work, partially implemented features, or active branches:

| Work Item | Status | Branch/Location | What Remains |
|-----------|--------|----------------|--------------|
| API v2 migration | 60% done | `feature/api-v2` | 3 endpoints not migrated |
| Caching layer | Started | `src/cache.py` | Only read-through implemented |

### 5. Architecture Decisions and Rationale

Document the key design decisions and why they were made (or your best inference):

| Decision | Rationale | Trade-offs | Would Reconsider? |
|----------|-----------|------------|-------------------|
| SQLite over PostgreSQL | Single-server deployment, simplicity | No concurrent writes, no replication | YES if scaling needed |
| Monolith over microservices | Small team, shared data model | Harder to scale independently | NO — appropriate for size |

### 6. Known Gotchas

Things that will trip up a new developer:

| Gotcha | Context | How to Avoid |
|--------|---------|-------------|
| Tests fail if run in parallel | Shared SQLite test database | Run with `-p no:xdist` |
| `.env` file is required but not in repo | Contains API keys | Copy `.env.example` and fill in values |
| Build fails on Apple Silicon | Native dependency issue | Use `arch -x86_64` prefix |

### 7. Key Files Map

The most important files a new developer should read first:

| Order | File | Purpose | Read Time |
|-------|------|---------|-----------|
| 1 | `README.md` | Project overview | 5 min |
| 2 | `src/main.py` | Application entry point | 10 min |
| 3 | `src/models.py` | Data model definitions | 15 min |
| 4 | `src/config.py` | All configuration | 5 min |

### 8. Development Workflow

Step-by-step instructions for common tasks:

- **Running locally** — exact commands
- **Running tests** — exact commands with expected output
- **Making a change** — branch strategy, where to add code, how to test
- **Deploying** — exact steps or "deployment not configured"

### 9. External Dependencies and Services

| Service | Purpose | Required for Dev? | Credentials Location |
|---------|---------|-------------------|---------------------|
| PostgreSQL | Primary database | YES | `DATABASE_URL` in `.env` |
| Stripe API | Payment processing | NO (stubbed in dev) | `STRIPE_KEY` in `.env` |
| AWS S3 | File storage | NO (local filesystem in dev) | AWS config in `.env` |

### 10. Immediate Priorities

If the new developer has one week, what should they do first?

| Priority | Action | Why | Files Involved |
|----------|--------|-----|---------------|
| 1 | Fix X | Blocking Y users | `file.py` |
| 2 | Add tests for Z | Zero coverage on critical path | `module/` |
| 3 | Update dependency A | Known vulnerability | `requirements.txt` |

## Output Format

Use the exact section headers and tables above. Write in clear, direct language. Avoid jargon unless defined. Every file reference must use full paths.

Focus on actionable findings with file path evidence.
