#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAM_BIN="${ROOT_DIR}/.venv/bin/cam"
RUN_ID="${CAM_LADDER_RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
LOG_DIR="${ROOT_DIR}/tmp/ladder_logs/${RUN_ID}"
RESULTS_TSV="${LOG_DIR}/results.tsv"
SUMMARY_MD="${LOG_DIR}/summary.md"

CAM_LADDER_AGENT="${CAM_LADDER_AGENT:-claude}"
CAM_LADDER_MAX_LEVEL="${CAM_LADDER_MAX_LEVEL:-4}"
CAM_LADDER_SOURCE_DIR="${CAM_LADDER_SOURCE_DIR:-repoTST}"
CAM_LADDER_STOP_ON_FAIL="${CAM_LADDER_STOP_ON_FAIL:-0}"
CAM_LADDER_SELF_EXECUTE="${CAM_LADDER_SELF_EXECUTE:-0}"
CAM_LADDER_CHANGED_ONLY="${CAM_LADDER_CHANGED_ONLY:-1}"

mkdir -p "${LOG_DIR}"

if [[ ! -x "${CAM_BIN}" ]]; then
  echo "ERROR: CAM CLI not found at ${CAM_BIN}" >&2
  exit 1
fi

case "${CAM_LADDER_AGENT}" in
  claude|codex|gemini|grok)
    ;;
  *)
    echo "ERROR: CAM_LADDER_AGENT must be one of: claude, codex, gemini, grok" >&2
    exit 1
    ;;
esac

printf "level\tstatus\tlabel\tlog\n" > "${RESULTS_TSV}"

run_step() {
  local level="$1"
  local label="$2"
  local log_file="$3"
  shift 3

  local status=0
  echo
  echo "== Level ${level}: ${label} =="
  set +e
  "$@" >"${log_file}" 2>&1
  status=$?
  set -e

  if [[ ${status} -eq 0 ]] && rg -q "Rejected \\(|Failure:" "${log_file}"; then
    status=1
  fi

  if [[ ${status} -eq 0 ]]; then
    echo "PASS: ${label}"
    printf "%s\tPASS\t%s\t%s\n" "${level}" "${label}" "${log_file}" >> "${RESULTS_TSV}"
    return 0
  fi

  echo "FAIL: ${label} (exit ${status})"
  printf "%s\tFAIL\t%s\t%s\n" "${level}" "${label}" "${log_file}" >> "${RESULTS_TSV}"
  if [[ "${CAM_LADDER_STOP_ON_FAIL}" == "1" ]]; then
    echo "Stopping early because CAM_LADDER_STOP_ON_FAIL=1"
    return "${status}"
  fi
  return 0
}

latest_spec_for_slug() {
  local slug="$1"
  ls -1t "${ROOT_DIR}"/data/create_specs/*-"${slug}"-create-spec.json 2>/dev/null | head -n 1 || true
}

render_summary() {
  {
    echo "# CAM Expectation Ladder Summary"
    echo
    echo "- Run ID: \`${RUN_ID}\`"
    echo "- Agent: \`${CAM_LADDER_AGENT}\`"
    echo "- Max level: \`${CAM_LADDER_MAX_LEVEL}\`"
    echo "- Source dir: \`${CAM_LADDER_SOURCE_DIR}\`"
    echo "- Changed only mine: \`${CAM_LADDER_CHANGED_ONLY}\`"
    echo "- Self execute: \`${CAM_LADDER_SELF_EXECUTE}\`"
    echo
    echo "| Level | Status | Label | Log |"
    echo "|---|---|---|---|"
    tail -n +2 "${RESULTS_TSV}" | while IFS=$'\t' read -r level status label log; do
      echo "| ${level} | ${status} | ${label} | ${log} |"
    done
    echo
    echo "Artifacts:"
    echo "- Results TSV: \`${RESULTS_TSV}\`"
    echo "- This summary: \`${SUMMARY_MD}\`"
  } > "${SUMMARY_MD}"
}

if [[ "${CAM_LADDER_MAX_LEVEL}" -lt 0 ]]; then
  echo "ERROR: CAM_LADDER_MAX_LEVEL must be >= 0" >&2
  exit 1
fi

# Level 0: baseline runtime expectations
if [[ "${CAM_LADDER_MAX_LEVEL}" -ge 0 ]]; then
  run_step "0" "Runtime health and expectation preflight" "${LOG_DIR}/level0_health.log" \
    bash -lc "set -euo pipefail; '${CAM_BIN}' --help >/dev/null; '${CAM_BIN}' govern stats; '${CAM_BIN}' doctor expectations"
fi

# Level 1: simple deterministic standalone CLI build
if [[ "${CAM_LADDER_MAX_LEVEL}" -ge 1 ]]; then
  L1_SLUG="ladder-l1-${RUN_ID}"
  L1_REPO="${ROOT_DIR}/tmp/${L1_SLUG}"
  mkdir -p "${L1_REPO}"
  run_step "1" "Standalone tiny CLI app (create+execute)" "${LOG_DIR}/level1_create.log" \
    "${CAM_BIN}" create "${L1_REPO}" \
      --repo-mode new \
      --title "Expectation Ladder L1" \
      --agent "${CAM_LADDER_AGENT}" \
      --request "Create a tiny standalone CLI app that writes a markdown file from a title and body." \
      --answer "Delivery surface: CLI app" \
      --answer "Autonomy: bounded supervised loop" \
      --spec "Must be standalone and must not import CAM runtime code." \
      --spec "Must expose python -m app.cli." \
      --check "python -m app.cli --help" \
      --check "python -m app.cli -t 'Test Title' -b 'Test body' -o out.md" \
      --check "test -f out.md" \
      --check "rg -q '^# Test Title' out.md" \
      --accept-preflight-defaults \
      --execute \
      --max-minutes 12

  L1_SPEC="$(latest_spec_for_slug "${L1_SLUG}")"
  if [[ -z "${L1_SPEC}" ]]; then
    echo "ERROR: Could not find L1 spec file for ${L1_SLUG}" >&2
    exit 1
  fi
  run_step "1.1" "Validate L1 spec" "${LOG_DIR}/level1_validate.log" \
    "${CAM_BIN}" validate --spec-file "${L1_SPEC}" --max-minutes 8
fi

# Level 2: workflow complexity with UX checks
if [[ "${CAM_LADDER_MAX_LEVEL}" -ge 2 ]]; then
  L2_SLUG="ladder-l2-${RUN_ID}"
  L2_REPO="${ROOT_DIR}/tmp/${L2_SLUG}"
  mkdir -p "${L2_REPO}"
  run_step "2" "Workflow UX app (create+execute)" "${LOG_DIR}/level2_create.log" \
    "${CAM_BIN}" create "${L2_REPO}" \
      --repo-mode new \
      --title "Expectation Ladder L2" \
      --agent "${CAM_LADDER_AGENT}" \
      --request "Create a tiny standalone web app that asks for current site, purpose, and design direction, with an Analyze First flow." \
      --answer "Delivery surface: web app" \
      --answer "Autonomy: bounded supervised loop" \
      --spec "Must be standalone and must not import CAM runtime code." \
      --spec "Must include Analyze First workflow and direct recommendation workflow." \
      --check "test -f index.html" \
      --check "test -f README.md" \
      --check "rg -q -i 'current site' ." \
      --check "rg -q -i 'purpose' ." \
      --check "rg -q -i 'design direction' ." \
      --check "rg -q -i 'analyze first' ." \
      --accept-preflight-defaults \
      --execute \
      --max-minutes 12

  L2_SPEC="$(latest_spec_for_slug "${L2_SLUG}")"
  if [[ -z "${L2_SPEC}" ]]; then
    echo "ERROR: Could not find L2 spec file for ${L2_SLUG}" >&2
    exit 1
  fi
  run_step "2.1" "Validate L2 spec" "${LOG_DIR}/level2_validate.log" \
    "${CAM_BIN}" validate --spec-file "${L2_SPEC}" --max-minutes 8
fi

# Level 3: transfer from mined repos into CAM retrieval and reassessment
if [[ "${CAM_LADDER_MAX_LEVEL}" -ge 3 ]]; then
  if [[ "${CAM_LADDER_CHANGED_ONLY}" == "1" ]]; then
    run_step "3" "Mine source repos into CAM (changed-only optional)" "${LOG_DIR}/level3_mine.log" \
      "${CAM_BIN}" mine "${CAM_LADDER_SOURCE_DIR}" --target "${ROOT_DIR}" --depth 3 --max-repos 3 --max-minutes 20 --changed-only
  else
    run_step "3" "Mine source repos into CAM (changed-only optional)" "${LOG_DIR}/level3_mine.log" \
      "${CAM_BIN}" mine "${CAM_LADDER_SOURCE_DIR}" --target "${ROOT_DIR}" --depth 3 --max-repos 3 --max-minutes 20
  fi
  run_step "3.1" "Reassess mined knowledge for CAM reliability task" "${LOG_DIR}/level3_reassess.log" \
    "${CAM_BIN}" learn reassess --task "improve CAM reliability for create validate execution loops" --limit 10
fi

# Level 4: CAM-on-CAM self-improvement contract (safe by default)
if [[ "${CAM_LADDER_MAX_LEVEL}" -ge 4 ]]; then
  run_step "4" "Self-improvement preflight contract" "${LOG_DIR}/level4_preflight.log" \
    "${CAM_BIN}" preflight "${ROOT_DIR}" \
      --repo-mode fixed \
      --request "Apply mined patterns to improve CAM reliability for create validate execution loops." \
      --check "pytest -q tests/test_create_benchmark_spec.py tests/test_cycle.py tests/test_openrouter.py tests/test_cli_ux.py tests/test_preflight_cli.py"

  L4_SLUG="multiclaw"
  run_step "4.1" "Self-improvement create spec only (no execute)" "${LOG_DIR}/level4_create_spec_only.log" \
    "${CAM_BIN}" create "${ROOT_DIR}" \
      --repo-mode fixed \
      --request "Apply mined patterns to improve CAM reliability for create validate execution loops." \
      --answer "Delivery surface: internal CLI/runtime reliability improvements in existing CAM repo" \
      --check "pytest -q tests/test_create_benchmark_spec.py tests/test_cycle.py tests/test_openrouter.py tests/test_cli_ux.py tests/test_preflight_cli.py" \
      --preflight \
      --no-preview \
      --max-minutes 10

  if [[ "${CAM_LADDER_SELF_EXECUTE}" == "1" ]]; then
    run_step "4.2" "Self-improvement execute (guarded)" "${LOG_DIR}/level4_execute.log" \
      "${CAM_BIN}" create "${ROOT_DIR}" \
        --repo-mode fixed \
        --request "Apply mined patterns to improve CAM reliability for create validate execution loops without introducing a new top-level source namespace." \
        --answer "Delivery surface: internal CLI/runtime reliability improvements in existing CAM repo" \
        --check "pytest -q tests/test_create_benchmark_spec.py tests/test_cycle.py tests/test_openrouter.py tests/test_cli_ux.py tests/test_preflight_cli.py" \
        --preflight \
        --accept-preflight-defaults \
        --execute \
        --max-minutes 20
  else
    echo "Skipping level 4.2 self-execute. Set CAM_LADDER_SELF_EXECUTE=1 to enable." \
      | tee "${LOG_DIR}/level4_execute.log"
    printf "4.2\tSKIP\tSelf-improvement execute (guarded)\t%s\n" "${LOG_DIR}/level4_execute.log" >> "${RESULTS_TSV}"
  fi
fi

render_summary
echo
echo "Expectation ladder complete."
echo "  Logs: ${LOG_DIR}"
echo "  Summary: ${SUMMARY_MD}"

if tail -n +2 "${RESULTS_TSV}" | rg -q $'\tFAIL\t'; then
  exit 1
fi
