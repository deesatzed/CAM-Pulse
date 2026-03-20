#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  camify_overlay_clone.sh --repo <repo-to-camify> [options]

Required:
  --repo <repo>             Git URL or local path of the repository to CAM-ify.

Options:
  --workspace <dir>         Workspace root to create. Default: ./tmp/camify_<repo_slug>_<timestamp>
  --cam-source <source>     CAM source git URL/path. Default: current repo origin (or current path)
  --cam-dir-name <name>     CAM clone directory name. Default: cam-core
  --repo-dir-name <name>    Target repo clone directory name. Default: target-repo
  --overlay-name <name>     Overlay directory name. Default: cam-overlay
  --branch <name>           Branch to checkout in CAM clone. Default: current branch when available
  --dry-run                 Print planned actions without cloning or writing files.
  -h, --help                Show this help.

Example:
  ./scripts/camify_overlay_clone.sh \
    --repo https://github.com/acme/service-a.git \
    --workspace /tmp/camify_service_a
USAGE
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

slugify() {
  local raw="$1"
  raw="${raw##*/}"
  raw="${raw%.git}"
  raw="${raw//[^A-Za-z0-9._-]/-}"
  raw="${raw//./-}"
  raw="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]')"
  echo "$raw"
}

write_file() {
  local path="$1"
  local content="$2"
  mkdir -p "$(dirname "$path")"
  printf "%s" "$content" > "$path"
}

REPO_SOURCE=""
WORKSPACE=""
CAM_SOURCE=""
CAM_DIR_NAME="cam-core"
REPO_DIR_NAME="target-repo"
OVERLAY_NAME="cam-overlay"
CAM_BRANCH=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --repo)
      REPO_SOURCE="${2:-}"
      shift 2
      ;;
    --workspace)
      WORKSPACE="${2:-}"
      shift 2
      ;;
    --cam-source)
      CAM_SOURCE="${2:-}"
      shift 2
      ;;
    --cam-dir-name)
      CAM_DIR_NAME="${2:-}"
      shift 2
      ;;
    --repo-dir-name)
      REPO_DIR_NAME="${2:-}"
      shift 2
      ;;
    --overlay-name)
      OVERLAY_NAME="${2:-}"
      shift 2
      ;;
    --branch)
      CAM_BRANCH="${2:-}"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$REPO_SOURCE" ]]; then
  echo "ERROR: --repo is required" >&2
  usage
  exit 1
fi

require_cmd git

if [[ -z "$CAM_SOURCE" ]]; then
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    CAM_SOURCE="$(git config --get remote.origin.url || true)"
    if [[ -z "$CAM_SOURCE" ]]; then
      CAM_SOURCE="$(pwd)"
    fi
  else
    CAM_SOURCE="$(pwd)"
  fi
fi

if [[ -z "$CAM_BRANCH" ]]; then
  CAM_BRANCH="$(git branch --show-current 2>/dev/null || true)"
fi

REPO_SLUG="$(slugify "$REPO_SOURCE")"
if [[ -z "$REPO_SLUG" ]]; then
  REPO_SLUG="target"
fi

if [[ -z "$WORKSPACE" ]]; then
  WORKSPACE="$(pwd)/tmp/camify_${REPO_SLUG}_$(date +%Y%m%d-%H%M%S)"
fi

CAM_PATH="${WORKSPACE}/${CAM_DIR_NAME}"
TARGET_PATH="${WORKSPACE}/${REPO_DIR_NAME}"
OVERLAY_PATH="${WORKSPACE}/${OVERLAY_NAME}"

PLAN_DOC="${WORKSPACE}/CAMIFY_PLAN.md"
RUNBOOK_DOC="${WORKSPACE}/CAMIFY_RUNBOOK.md"

echo "CAM-ify Bootstrap"
echo "  CAM source:     ${CAM_SOURCE}"
echo "  Target source:  ${REPO_SOURCE}"
echo "  Workspace:      ${WORKSPACE}"
echo "  CAM clone:      ${CAM_PATH}"
echo "  Target clone:   ${TARGET_PATH}"
echo "  Overlay root:   ${OVERLAY_PATH}"
if [[ -n "$CAM_BRANCH" ]]; then
  echo "  CAM branch:     ${CAM_BRANCH}"
fi

if [[ "$DRY_RUN" == "1" ]]; then
  echo
  echo "Dry run complete. No files or clones were created."
  exit 0
fi

mkdir -p "$WORKSPACE"

if [[ -e "$CAM_PATH" || -e "$TARGET_PATH" || -e "$OVERLAY_PATH" ]]; then
  echo "ERROR: workspace contains existing output paths. Use a new --workspace." >&2
  exit 1
fi

git clone "$CAM_SOURCE" "$CAM_PATH"
if [[ -n "$CAM_BRANCH" ]]; then
  (
    cd "$CAM_PATH"
    git checkout "$CAM_BRANCH" >/dev/null 2>&1 || true
  )
fi

git clone "$REPO_SOURCE" "$TARGET_PATH"

mkdir -p \
  "$OVERLAY_PATH/profiles/${REPO_SLUG}" \
  "$OVERLAY_PATH/prompts" \
  "$OVERLAY_PATH/verifiers" \
  "$OVERLAY_PATH/memory" \
  "$OVERLAY_PATH/contracts"

PROFILE_TOML_CONTENT="[repo]\nslug = \"${REPO_SLUG}\"\npath = \"${TARGET_PATH}\"\n\n[mode]\ndefault = \"observe\"\nallowed = [\"observe\", \"advise\", \"supervised_execute\", \"bounded_autonomous\"]\n\n[guards]\nnamespace_guard = true\nrollback_required = true\nrequire_verification = true\n\n[verification]\nbaseline_commands = [\"pytest -q\"]\n"
write_file "$OVERLAY_PATH/profiles/${REPO_SLUG}/profile.toml" "$PROFILE_TOML_CONTENT"

PLAN_CONTENT="# CAM-ify Plan (${REPO_SLUG})\n\n## Objective\nApply CAM-style learning + reasoning capabilities to one target repo without mutating CAM core behavior.\n\n## Non-Destructive Strategy\n1. Keep CAM core in '${CAM_PATH}'.\n2. Keep target repo in '${TARGET_PATH}'.\n3. Keep all repo-specific intelligence in '${OVERLAY_PATH}'.\n4. Use progressive autonomy: observe -> advise -> supervised_execute -> bounded_autonomous.\n\n## First Tasks\n- Build repo fingerprint and risk map.\n- Define acceptance/verification contracts.\n- Add repo-scoped memory tagging.\n- Run observe-only loop before any writes.\n\n## Safety Rules\n- No write outside target repo.\n- No new top-level namespace without explicit allow.\n- Rollback checkpoint required before writes.\n- Fail closed when verification fails.\n"
write_file "$PLAN_DOC" "$PLAN_CONTENT"

RUNBOOK_CONTENT="# CAM-ify Runbook (${REPO_SLUG})\n\n## Workspace\n- CAM clone: ${CAM_PATH}\n- Target repo: ${TARGET_PATH}\n- Overlay: ${OVERLAY_PATH}\n\n## Suggested Startup\n\`\`\`bash\ncd ${CAM_PATH}\nsource .venv/bin/activate 2>/dev/null || true\n\`\`\`\n\n## Initial Workflow\n1. Observe mode assessment of target repo.\n2. Create repo-specific contract in '${OVERLAY_PATH}/contracts/'.\n3. Add verifier commands in profile.toml.\n4. Move to advise mode only after baseline checks pass.\n"
write_file "$RUNBOOK_DOC" "$RUNBOOK_CONTENT"

echo
echo "Bootstrap complete."
echo "  Plan:    ${PLAN_DOC}"
echo "  Runbook: ${RUNBOOK_DOC}"
echo "  Profile: ${OVERLAY_PATH}/profiles/${REPO_SLUG}/profile.toml"
