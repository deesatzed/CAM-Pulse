# Project Context Brief

Analyze the repository and produce a concise project context brief covering the following areas.

## Instructions

Examine the entire codebase — source files, configuration, documentation, scripts, and CI definitions. Do NOT speculate; only report what you can confirm from the code.

## Required Output Sections

### 1. Project Identity

| Field | Value |
|-------|-------|
| **Name** | Project name (from package manifest or README) |
| **Purpose** | One-sentence description of what this project does |
| **Language(s)** | Primary and secondary languages with approximate LOC |
| **Framework(s)** | Web framework, CLI framework, etc. |
| **License** | License type or "NONE FOUND" |

### 2. Runtime Entrypoints

List every way this project is started or invoked. For each entrypoint provide:

- **File path** (e.g., `src/main.py`)
- **Command** (e.g., `python -m app serve`)
- **Purpose** (e.g., "Starts the HTTP API server")

### 3. Tech Stack

List all major technologies, organized by layer:

- **Runtime** — language version, runtime (Node, CPython, JVM, etc.)
- **Application** — frameworks, ORMs, template engines
- **Data** — databases, caches, message queues, file storage
- **Infrastructure** — containerization, orchestration, cloud services
- **Tooling** — linters, formatters, type checkers, bundlers

### 4. Key Dependencies

List the top 10 dependencies by importance (not alphabetically). For each:

- Package name and pinned version (or range)
- What it does in this project
- Whether it appears actively maintained (last release date if determinable)

### 5. Build and Run Commands

Provide exact shell commands for:

- Installing dependencies
- Running in development mode
- Running tests
- Building for production
- Deploying (if deployment config exists)

If any of these are missing or unclear, state "NOT DEFINED" explicitly.

### 6. Deployment Setup

Describe any deployment configuration found:

- Dockerfiles, docker-compose files
- CI/CD pipeline definitions (GitHub Actions, GitLab CI, etc.)
- Infrastructure-as-code (Terraform, Pulumi, etc.)
- Environment variable requirements

If no deployment setup exists, state "NO DEPLOYMENT CONFIGURATION FOUND."

## Output Format

Use the exact section headers above. Use markdown tables where specified. Keep the total output to approximately one page (roughly 400-600 words).

Focus on actionable findings with file path evidence.
