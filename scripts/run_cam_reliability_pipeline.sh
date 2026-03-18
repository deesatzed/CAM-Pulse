#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAM_BIN="${ROOT_DIR}/.venv/bin/cam"
PYTEST_BIN="${ROOT_DIR}/.venv/bin/pytest"
PYTHON_BIN="${ROOT_DIR}/.venv/bin/python"
RUN_ID="${CAM_PIPELINE_RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
LOG_DIR="${ROOT_DIR}/tmp/reliability_pipeline/${RUN_ID}"
RESULTS_TSV="${LOG_DIR}/results.tsv"
SUMMARY_MD="${LOG_DIR}/summary.md"

CAM_PIPELINE_AGENT="${CAM_PIPELINE_AGENT:-claude}"
CAM_PIPELINE_SOURCE_DIR="${CAM_PIPELINE_SOURCE_DIR:-repoTst}"
CAM_PIPELINE_STOP_ON_FAIL="${CAM_PIPELINE_STOP_ON_FAIL:-0}"

mkdir -p "${LOG_DIR}"
printf "step\tstatus\tlabel\tlog\n" > "${RESULTS_TSV}"

if [[ ! -x "${CAM_BIN}" ]]; then
  echo "ERROR: CAM CLI not found at ${CAM_BIN}" >&2
  exit 1
fi
if [[ ! -x "${PYTEST_BIN}" ]]; then
  echo "ERROR: pytest not found at ${PYTEST_BIN}" >&2
  exit 1
fi
if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "ERROR: python not found at ${PYTHON_BIN}" >&2
  exit 1
fi
if [[ -z "${OPENROUTER_API_KEY:-}" || -z "${GOOGLE_API_KEY:-}" ]]; then
  echo "ERROR: OPENROUTER_API_KEY and GOOGLE_API_KEY must both be set." >&2
  exit 1
fi

run_step() {
  local step="$1"
  local label="$2"
  local log_file="$3"
  shift 3

  local status=0
  echo
  echo "== Step ${step}: ${label} =="
  set +e
  "$@" >"${log_file}" 2>&1
  status=$?
  set -e

  if [[ ${status} -eq 0 ]] && rg -q "Rejected \\(|Failure:" "${log_file}"; then
    status=1
  fi

  if [[ ${status} -eq 0 ]]; then
    echo "PASS: ${label}"
    printf "%s\tPASS\t%s\t%s\n" "${step}" "${label}" "${log_file}" >> "${RESULTS_TSV}"
    return 0
  fi

  echo "FAIL: ${label} (exit ${status})"
  printf "%s\tFAIL\t%s\t%s\n" "${step}" "${label}" "${log_file}" >> "${RESULTS_TSV}"
  if [[ "${CAM_PIPELINE_STOP_ON_FAIL}" == "1" ]]; then
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
    echo "# CAM Reliability Pipeline Summary"
    echo
    echo "- Run ID: \`${RUN_ID}\`"
    echo "- Agent: \`${CAM_PIPELINE_AGENT}\`"
    echo "- Source dir: \`${CAM_PIPELINE_SOURCE_DIR}\`"
    echo
    echo "| Step | Status | Label | Log |"
    echo "|---|---|---|---|"
    tail -n +2 "${RESULTS_TSV}" | while IFS=$'\t' read -r step status label log; do
      echo "| ${step} | ${status} | ${label} | ${log} |"
    done
    echo
    echo "Artifacts:"
    echo "- Results TSV: \`${RESULTS_TSV}\`"
    echo "- Summary: \`${SUMMARY_MD}\`"
  } > "${SUMMARY_MD}"
}

# 1. Baseline worktree status
run_step "1" "Capture baseline git status" "${LOG_DIR}/step1_git_status.log" \
  bash -lc "cd '${ROOT_DIR}' && git status --short"

# 2. Full unit/integration suite
run_step "2" "Run full pytest suite" "${LOG_DIR}/step2_pytest_full.log" \
  bash -lc "cd '${ROOT_DIR}' && '${PYTEST_BIN}' -q"

# 3. Incremental mining steady-state check
run_step "3" "Mine repoTst (changed-only steady-state)" "${LOG_DIR}/step3_mine_changed_only.log" \
  bash -lc "cd '${ROOT_DIR}' && '${CAM_BIN}' mine '${CAM_PIPELINE_SOURCE_DIR}' --target '${ROOT_DIR}' --depth 4 --max-repos 5 --changed-only --max-minutes 30"

# 4. Reassess mined knowledge for CAM reliability
run_step "4" "Reassess mined knowledge for reliability loop" "${LOG_DIR}/step4_reassess.log" \
  bash -lc "cd '${ROOT_DIR}' && '${CAM_BIN}' learn reassess --task 'improve CAM reliability for create validate execution loops' --limit 15"

# 5. Controlled CAM-on-CAM execute with strict checks
before_multiclaw_spec="$(latest_spec_for_slug multiclaw)"
run_step "5" "Run fixed-mode CAM self-improvement execute" "${LOG_DIR}/step5_create_execute.log" \
  bash -lc "cd '${ROOT_DIR}' && '${CAM_BIN}' create '${ROOT_DIR}' --repo-mode fixed --agent '${CAM_PIPELINE_AGENT}' --request 'improve CAM reliability for create+validate loops and UX' --check \"${PYTEST_BIN} -q tests/test_create_benchmark_spec.py tests/test_cycle.py tests/test_openrouter.py tests/test_cli_ux.py tests/test_preflight_cli.py tests/test_config.py tests/test_miner.py\" --preflight --accept-preflight-defaults --namespace-safe-retry --execute --max-minutes 30"

after_multiclaw_spec="$(latest_spec_for_slug multiclaw)"
if [[ -n "${after_multiclaw_spec}" ]]; then
  MULTICLAW_SPEC="${after_multiclaw_spec}"
else
  MULTICLAW_SPEC="${before_multiclaw_spec}"
fi

if [[ -z "${MULTICLAW_SPEC}" ]]; then
  echo "ERROR: Could not determine multiclaw spec path after step 5" >&2
  exit 1
fi

# 6. Validate the create spec from step 5
run_step "6" "Validate latest multiclaw create spec" "${LOG_DIR}/step6_validate.log" \
  bash -lc "cd '${ROOT_DIR}' && '${CAM_BIN}' validate --spec-file '${MULTICLAW_SPEC}' --max-minutes 10"

# 7. Showpiece proof path + deterministic smoke
run_step "7" "Run medCSS showpiece harness (create+validate+postcheck)" "${LOG_DIR}/step7_medcss_harness.log" \
  bash -lc "cd '${ROOT_DIR}' && CAM_TEST_AGENT='${CAM_PIPELINE_AGENT}' OPENROUTER_API_KEY='${OPENROUTER_API_KEY}' GOOGLE_API_KEY='${GOOGLE_API_KEY}' ./scripts/test_medcss_modernizer.sh"

run_step "7.1" "Smoke versioned medCSS CLI showpiece app" "${LOG_DIR}/step7_showpiece_smoke.log" \
  bash -lc "cd '${ROOT_DIR}/apps/medcss_modernizer_showpiece' && '${PYTEST_BIN}' -q && '${PYTHON_BIN}' -m app.cli --site 'legacy clinic site with dense text' --purpose 'increase trust and appointment conversions' --ideas 'minimal, airy, modern medical' --out demo_report.md --html-out demo_landing.html && test -f demo_report.md && test -f demo_landing.html && grep -q 'Modernization Recommendations' demo_report.md && rm -f demo_report.md demo_landing.html"

render_summary
echo
echo "CAM reliability pipeline complete"
echo "  Logs: ${LOG_DIR}"
echo "  Summary: ${SUMMARY_MD}"

tail -n +2 "${RESULTS_TSV}" | rg -q $'\tFAIL\t' && exit 1 || exit 0
