# CAM-ify Overlay Clone Script

Script: `scripts/camify_overlay_clone.sh`

## Purpose

Bootstrap a non-destructive CAM-ify workspace by cloning:
- CAM core
- A target repo to CAM-ify
- An overlay structure for repo-specific CAM behavior

## What It Creates

- Workspace root (auto-generated or `--workspace`)
- CAM clone directory (default: `cam-core`)
- Target repo clone directory (default: `target-repo`)
- Overlay directory (default: `cam-overlay`) with:
  - `profiles/<repo_slug>/profile.toml`
  - `prompts/`
  - `verifiers/`
  - `memory/`
  - `contracts/`
- Docs:
  - `CAMIFY_PLAN.md`
  - `CAMIFY_RUNBOOK.md`

## Required Argument

- `--repo <repo>`: Git URL or local path for the repo to CAM-ify.

## Options

- `--workspace <dir>`: Workspace root path.
- `--cam-source <source>`: CAM source git URL/path. Defaults to current repo origin or current path.
- `--cam-dir-name <name>`: CAM clone folder name. Default `cam-core`.
- `--repo-dir-name <name>`: Target clone folder name. Default `target-repo`.
- `--overlay-name <name>`: Overlay folder name. Default `cam-overlay`.
- `--branch <name>`: CAM branch to checkout.
- `--dry-run`: Preview only, no writes/clones.
- `-h`, `--help`: Help output.

## Example (Real Run)

```bash
./scripts/camify_overlay_clone.sh \
  --repo /path/to/repo-to-camify \
  --cam-source /Users/o2satz/multiclaw \
  --workspace /Users/o2satz/multiclaw/tmp/camify_myrepo
```

## Example (Preview Only)

```bash
./scripts/camify_overlay_clone.sh --repo /path/to/repo --dry-run
```

## Validation Performed

- `bash -n scripts/camify_overlay_clone.sh` passed.
- `scripts/camify_overlay_clone.sh --help` passed.
- `scripts/camify_overlay_clone.sh --repo <local_repo> --dry-run` passed.
- Full smoke run passed with local CAM source and local target repo.

