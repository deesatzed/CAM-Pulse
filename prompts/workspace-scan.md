# Workspace Scan

Analyze the repository and produce a structured workspace inventory covering directory layout, file composition, build systems, and configuration.

## Instructions

Walk the entire file tree. Count files, measure sizes, and identify patterns. Report only what is present — do not infer what should be present.

## Required Output Sections

### 1. Directory Structure

Provide a tree view of the top 3 levels of the repository. Mark directories with their primary purpose:

```
repo-root/
  src/          # Application source
  tests/        # Test suite
  docs/         # Documentation
  ...
```

### 2. File Composition

| File Type | Count | Total Lines | Percentage of Codebase |
|-----------|-------|-------------|----------------------|
| .py       | N     | N           | N%                   |
| .js       | N     | N           | N%                   |
| ...       | ...   | ...         | ...                  |

Include all file types with 3+ occurrences. Sort by line count descending.

### 3. Build Systems Detected

For each build system found, list:

- **System name** (npm, pip, cargo, make, gradle, etc.)
- **Config file(s)** with paths
- **Key scripts/targets defined**
- **Lock file present?** (yes/no)

### 4. Project Structure Classification

Classify the repository as one of:

- **Single project** — one application, one build
- **Monorepo (workspaces)** — multiple packages sharing a root build config
- **Multi-project** — independent projects in subdirectories without shared tooling
- **Hybrid** — combination (explain)

Provide evidence for your classification.

### 5. Configuration Files Inventory

| File | Purpose | Contains Secrets? |
|------|---------|-------------------|
| `.env` | Environment variables | CHECK CONTENTS |
| `docker-compose.yml` | Container orchestration | N/A |
| ... | ... | ... |

List every configuration file found (dotfiles, YAML, TOML, INI, JSON config). Flag any that contain or appear to contain secrets, API keys, or credentials.

### 6. CI/CD Configuration

For each CI/CD config found:

- File path
- Platform (GitHub Actions, GitLab CI, CircleCI, etc.)
- Triggers (push, PR, schedule, manual)
- Jobs defined and what they do

### 7. Anomalies and Flags

List anything unusual:

- Empty directories
- Files larger than 1MB
- Binary files checked into the repo
- Duplicate file names in different directories
- Uncommitted generated files (node_modules, __pycache__, .pyc, dist/ checked in)
- Missing .gitignore entries for common artifacts
- Symlinks

## Output Format

Use the exact section headers and table formats above. If a section has no findings, write "NONE FOUND" under that section. Do not omit sections.

Focus on actionable findings with file path evidence.
