#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
SOURCE_ROOT="${REPO_ROOT}/awesome-codex-subagents/categories"

STARTER_SET=(
  "multi-agent-coordinator"
  "task-distributor"
  "backend-developer"
  "refactoring-specialist"
  "test-automator"
  "reviewer"
  "security-auditor"
  "dependency-manager"
)

print_usage() {
  cat <<'EOF'
Install Codex subagent TOML files from ./awesome-codex-subagents into Codex agent dirs.

Usage:
  scripts/install_codex_subagents.sh [options] [agent_name ...]

Options:
  --starter           Install a recommended starter bundle.
  --list              List available subagents and exit.
  --local             Install to ./.codex/agents (default).
  --global            Install to ~/.codex/agents.
  --dest DIR          Install to a custom destination directory.
  --source DIR        Use a custom source categories directory.
  -h, --help          Show this help.

Examples:
  scripts/install_codex_subagents.sh --starter
  scripts/install_codex_subagents.sh reviewer backend-developer
  scripts/install_codex_subagents.sh --global security-auditor test-automator
  scripts/install_codex_subagents.sh --list
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

require_source() {
  [[ -d "${SOURCE_ROOT}" ]] || die "source directory not found: ${SOURCE_ROOT}"
}

list_available() {
  require_source
  find "${SOURCE_ROOT}" -type f -name "*.toml" -print \
    | sed 's#.*/##' \
    | sed 's#\.toml$##' \
    | sort -u
}

find_agent_file() {
  local agent="$1"
  local matches
  matches="$(find "${SOURCE_ROOT}" -type f -name "${agent}.toml" -print)"
  if [[ -z "${matches}" ]]; then
    return 1
  fi
  local count
  count="$(printf '%s\n' "${matches}" | sed '/^$/d' | wc -l | tr -d ' ')"
  if [[ "${count}" -gt 1 ]]; then
    echo "error: multiple definitions found for '${agent}':" >&2
    printf '%s\n' "${matches}" >&2
    return 2
  fi
  printf '%s\n' "${matches}"
}

DEST_DIR="${REPO_ROOT}/.codex/agents"
MODE="local"
DO_LIST=0
USE_STARTER=0
declare -a REQUESTED=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --starter)
      USE_STARTER=1
      shift
      ;;
    --list)
      DO_LIST=1
      shift
      ;;
    --local)
      MODE="local"
      DEST_DIR="${REPO_ROOT}/.codex/agents"
      shift
      ;;
    --global)
      MODE="global"
      DEST_DIR="${HOME}/.codex/agents"
      shift
      ;;
    --dest)
      [[ $# -ge 2 ]] || die "--dest requires a path"
      DEST_DIR="$2"
      MODE="custom"
      shift 2
      ;;
    --source)
      [[ $# -ge 2 ]] || die "--source requires a path"
      SOURCE_ROOT="$2"
      shift 2
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    -*)
      die "unknown option: $1"
      ;;
    *)
      REQUESTED+=("$1")
      shift
      ;;
  esac
done

if [[ "${DO_LIST}" -eq 1 ]]; then
  list_available
  exit 0
fi

require_source

if [[ "${USE_STARTER}" -eq 1 ]]; then
  REQUESTED+=("${STARTER_SET[@]}")
fi

if [[ "${#REQUESTED[@]}" -eq 0 ]]; then
  die "no subagents specified (use --starter, --list, or pass agent names)"
fi

mkdir -p "${DEST_DIR}"

# Deduplicate while preserving order.
declare -A SEEN=()
declare -a UNIQUE_REQUESTED=()
for name in "${REQUESTED[@]}"; do
  if [[ -z "${SEEN[${name}]:-}" ]]; then
    SEEN["${name}"]=1
    UNIQUE_REQUESTED+=("${name}")
  fi
done

installed=0
for agent in "${UNIQUE_REQUESTED[@]}"; do
  if ! src_file="$(find_agent_file "${agent}")"; then
    die "subagent not found: ${agent} (run with --list)"
  fi
  cp "${src_file}" "${DEST_DIR}/${agent}.toml"
  installed=$((installed + 1))
  echo "installed ${agent} -> ${DEST_DIR}/${agent}.toml"
done

echo
echo "installed ${installed} subagent(s) to ${DEST_DIR} (${MODE})"
echo "restart or refresh your Codex session to pick up new agents"
