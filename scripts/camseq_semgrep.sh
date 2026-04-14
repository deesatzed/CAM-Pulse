#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: $0 <workspace_dir> <config_path> [file_paths...]" >&2
  exit 2
fi

workspace_dir="$(cd "$1" && pwd)"
config_path="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
shift 2

targets=()
if [[ $# -eq 0 ]]; then
  targets+=("/work")
else
  for path in "$@"; do
    if [[ -z "$path" ]]; then
      continue
    fi
    abs_path="$(cd "$(dirname "$path")" && pwd)/$(basename "$path")"
    case "$abs_path" in
      "$workspace_dir"/*)
        rel="${abs_path#"$workspace_dir"/}"
        targets+=("/work/$rel")
        ;;
      *)
        ;;
    esac
  done
fi

if [[ ${#targets[@]} -eq 0 ]]; then
  targets+=("/work")
fi

docker run --rm \
  -e SEMGREP_SEND_METRICS=off \
  -e SEMGREP_ENABLE_VERSION_CHECK=0 \
  -v "$workspace_dir:/work:ro" \
  -v "$config_path:/config/semgrep.yml:ro" \
  semgrep/semgrep:latest \
  semgrep scan --config /config/semgrep.yml --json --quiet "${targets[@]}"
