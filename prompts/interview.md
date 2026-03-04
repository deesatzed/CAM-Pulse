# Interview — Requirements Discovery Questionnaire

Analyze the repository and generate a list of questions that would need to be asked to the original developer (or product owner) to fully understand the project's intent, priorities, constraints, and non-obvious design decisions.

## Instructions

Read the entire codebase and identify every area where the code's intent is ambiguous, where design decisions are unexplained, where trade-offs are unclear, or where behavior seems inconsistent. For each gap, formulate a specific question. Do not ask generic questions — every question must be grounded in something you observed in the code.

## Required Output Sections

### 1. Intent Questions

These clarify what the project is trying to achieve and for whom.

| # | Question | Triggered By | File Evidence |
|---|----------|-------------|---------------|
| I1 | "Who is the primary user of this system — developers, end users, or operators?" | Multiple UIs exist (CLI + web + API) with no clear primary | `cli.py`, `web/app.py`, `api/routes.py` |
| I2 | "Is feature X intended for production use or was it a prototype?" | Feature has no tests and hardcoded values | `src/feature_x.py` |

Ask about:
- Target users and their technical level
- Core use case vs secondary use cases
- Which features are essential vs experimental
- What success looks like for this project

### 2. Priority Questions

These clarify what matters most when making trade-offs.

| # | Question | Triggered By | File Evidence |
|---|----------|-------------|---------------|
| P1 | "Is data consistency or availability more important when the DB is slow?" | No timeout or retry strategy — unclear which failure mode is preferred | `db.py:45` — no error handling on writes |
| P2 | "Should we optimize for throughput or latency?" | Some paths are batched, others are real-time, no clear pattern | `worker.py` vs `api.py` |

Ask about:
- Performance vs correctness trade-offs
- Feature completeness vs shipping speed
- Backwards compatibility requirements
- Acceptable downtime and data loss tolerance

### 3. Constraint Questions

These uncover limitations, requirements, and boundaries not visible in code.

| # | Question | Triggered By | File Evidence |
|---|----------|-------------|---------------|
| C1 | "Is there a maximum budget for external API calls per month?" | API calls have no rate limiting or cost tracking | `client.py` — unlimited calls to paid API |
| C2 | "Must this run on specific hardware or OS?" | Platform-specific code found but not documented | `native/build.sh` — Linux-only commands |

Ask about:
- Hardware/infrastructure constraints
- Budget constraints for services and APIs
- Compliance or regulatory requirements
- User data privacy requirements
- Supported platforms and browsers
- Maximum acceptable latency/response times

### 4. Design Decision Questions

These clarify why specific technical choices were made.

| # | Question | Triggered By | File Evidence |
|---|----------|-------------|---------------|
| D1 | "Why SQLite instead of PostgreSQL? Is this a permanent choice?" | Comments suggest scaling concerns but DB choice seems deliberate | `db.py:1` — SQLite chosen, `TODO` about scaling at line 45 |
| D2 | "Why is authentication handled differently in the API vs CLI?" | Two auth mechanisms, unclear if intentional | `api/auth.py` (JWT) vs `cli/auth.py` (API key) |

Ask about:
- Database and storage choices
- Framework and library selections
- Architectural patterns (monolith, microservices, etc.)
- Authentication and authorization strategy
- Deployment model decisions
- Anything that appears to be an unusual or non-standard choice

### 5. History Questions

These uncover context that only someone who was there would know.

| # | Question | Triggered By | File Evidence |
|---|----------|-------------|---------------|
| H1 | "What was the legacy system this replaced, and what constraints did migration impose?" | Legacy compatibility code with no documentation | `src/compat/` directory with adapter patterns |
| H2 | "Were there known issues with the previous approach to X that drove this design?" | Over-engineered solution to what seems like a simple problem | `src/retry_manager.py` — 200-line retry system for simple HTTP calls |

Ask about:
- Previous versions or systems this replaced
- Past incidents that influenced design
- Abandoned approaches and why they failed
- Team expertise that shaped technology choices

### 6. Future Questions

These clarify direction and planned evolution.

| # | Question | Triggered By | File Evidence |
|---|----------|-------------|---------------|
| F1 | "Is multi-tenancy planned? The data model has no tenant isolation." | Single-tenant design with no separation | `models.py` — no tenant_id on any table |
| F2 | "Which of the TODOs are actually planned vs aspirational?" | 47 TODO comments, unclear which matter | Various files |

Ask about:
- Planned features and scaling direction
- Migration plans for current technical debt
- Expected user growth and load increases
- Integration plans with other systems

### 7. Question Priority Matrix

Rank all questions by how critical the answer is to making safe changes:

| Priority | Questions | Why Critical |
|----------|-----------|-------------|
| MUST ANSWER before any changes | I1, C1, D1 | Risk of breaking unknown requirements |
| SHOULD ANSWER before major changes | P1, D2, H1 | Risk of wrong architectural direction |
| NICE TO KNOW | F1, F2, H2 | Improves planning but not blocking |

## Output Format

Use the exact section headers and tables above. Generate a minimum of 20 questions for a non-trivial codebase. Every question must reference specific code that triggered it.

Focus on actionable findings with file path evidence.
