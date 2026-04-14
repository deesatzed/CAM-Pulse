# CAM-SEQ Local Security Setup

Default local mode for CAM-SEQ critical-slot policy uses the project `uv` venv plus Docker.

This path does **not** require:
- editing `~/.zshrc`
- installing CodeQL
- installing Semgrep globally

## Requirements

- project venv at `.venv`
- Docker Desktop running

## One-time setup

```bash
cd /Volumes/WS4TB/RNACAM/CAM-Pulse
source .venv/bin/activate
export CLAW_SECURITY_USE_DOCKER=1
```

Optional persistent repo-local env file:

```bash
cp .env.example .env
```

Then set in `.env`:

```bash
CLAW_SECURITY_USE_DOCKER=1
```

## Verify Docker is available

```bash
docker ps
```

## Verify CAM-SEQ Docker Semgrep path

```bash
./scripts/camseq_semgrep.sh "$PWD" "$PWD/security/semgrep.yml" src/claw/security/policy_tools.py
```

This runs the repo-local Semgrep rules inside Docker.

## Advanced mode only

CodeQL is optional and is **not** required for the default local path.
Use CodeQL only if you want a heavier managed or advanced local security lane.
