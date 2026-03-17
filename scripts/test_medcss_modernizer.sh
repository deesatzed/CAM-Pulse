#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CAM_BIN="${ROOT_DIR}/.venv/bin/cam"
MEDCSS_FILE="${ROOT_DIR}/medCSS.md"
LOG_DIR="${ROOT_DIR}/tmp/medcss_test_logs"
RUN_ID="${CAM_TEST_RUN_ID:-$(date +%Y%m%d-%H%M%S)}"
TARGET_BASENAME="medcss-web-modernizer-${RUN_ID}"
TARGET_REPO="${ROOT_DIR}/tmp/${TARGET_BASENAME}"
CAM_TEST_AGENT="${CAM_TEST_AGENT:-claude}"

mkdir -p "${TARGET_REPO}" "${LOG_DIR}"

if [[ ! -x "${CAM_BIN}" ]]; then
  echo "ERROR: CAM CLI not found at ${CAM_BIN}" >&2
  exit 1
fi

if [[ ! -f "${MEDCSS_FILE}" ]]; then
  echo "ERROR: medCSS.md not found at ${MEDCSS_FILE}" >&2
  exit 1
fi

if [[ -z "${OPENROUTER_API_KEY:-}" ]]; then
  echo "ERROR: OPENROUTER_API_KEY is not set. Export it before running this script." >&2
  exit 1
fi

case "${CAM_TEST_AGENT}" in
  claude|codex|gemini|grok)
    ;;
  *)
    echo "ERROR: CAM_TEST_AGENT must be one of: claude, codex, gemini, grok" >&2
    exit 1
    ;;
esac

STYLE_CONTEXT="$(
  sed -n '1,18p' "${MEDCSS_FILE}" \
    | sed -e 's/[Pp]laceholder/template/g' -e 's/[Mm]ock/example/g'
)"
REQUEST_FILE="${LOG_DIR}/medcss_modernizer_request.txt"

cat > "${REQUEST_FILE}" <<REQ
Use this style reference as inspiration context (do not blindly copy dark-mode constraints):

${STYLE_CONTEXT}

Build a standalone Website Aesthetic Modernizer application.

Product expectation:
- The app must ask the user for:
  - current site URL or site description
  - site/business purpose
  - design ideas / design direction
- The app must support an "Analyze First" workflow that evaluates the current site info first, then suggests modern design directions.
- The app must also support direct recommendation workflow when URL analysis is unavailable.
- Default design direction must be light / non-dark and modern.
- Recommendations must be structured and actionable (typography, color, layout, motion, accessibility).

Technical expectation:
- Deliver production-ready standalone web app assets.
- Do not import CAM runtime code.
- Include README with run/usage steps.
REQ

REQUEST="$(cat "${REQUEST_FILE}")"
CREATE_LOG="${LOG_DIR}/medcss_modernizer_create_${RUN_ID}.log"
VALIDATE_LOG="${LOG_DIR}/medcss_modernizer_validate_${RUN_ID}.log"
POSTCHECK_LOG="${LOG_DIR}/medcss_modernizer_postcheck_${RUN_ID}.log"
CREATE_STATUS=0
VALIDATE_STATUS=0
POSTCHECK_STATUS=0

set -x
set +e
"${CAM_BIN}" create "${TARGET_REPO}" \
  --repo-mode new \
  --title "Website Aesthetic Modernizer (medCSS)" \
  --agent "${CAM_TEST_AGENT}" \
  --request "${REQUEST}" \
  --spec "Must be standalone and must not import CAM runtime code." \
  --spec "Default visual direction must be light/non-dark modern aesthetic." \
  --spec "UI must collect current site (URL or description), purpose, and design ideas." \
  --spec "Must include an Analyze First mode that returns recommendations before redesign output." \
  --spec "Recommendations must include typography, color, layout, motion, and accessibility guidance." \
  --check "test -f index.html" \
  --check "test -f README.md" \
  --check "rg -q -i 'current site' ." \
  --check "rg -q -i 'purpose' ." \
  --check "rg -q -i 'design direction' ." \
  --check "rg -q -i 'analyze first' ." \
  --execute \
  --max-minutes 20 | tee "${CREATE_LOG}"
CREATE_STATUS=$?
if [[ ${CREATE_STATUS} -eq 0 ]] && rg -q "Rejected \\(|Failure:" "${CREATE_LOG}"; then
  echo "Detected rejected execution in create log despite zero exit code." >&2
  CREATE_STATUS=1
fi
set -e
set +x

SPEC_FILE="$(ls -1t "${ROOT_DIR}"/data/create_specs/*-"${TARGET_BASENAME}"-create-spec.json 2>/dev/null | head -n 1 || true)"
if [[ -z "${SPEC_FILE}" ]]; then
  SPEC_FILE="$(ls -1t "${ROOT_DIR}"/data/create_specs/*-create-spec.json 2>/dev/null | head -n 1 || true)"
fi

if [[ -z "${SPEC_FILE}" ]]; then
  echo "ERROR: Could not locate generated create spec file." >&2
  exit 1
fi

set -x
set +e
"${CAM_BIN}" validate --spec-file "${SPEC_FILE}" --max-minutes 10 | tee "${VALIDATE_LOG}"
VALIDATE_STATUS=$?
set -e
set +x

set -x
set +e
(
  cd "${TARGET_REPO}" && \
  test -f index.html && \
  test -f README.md && \
  rg -q -i 'current site' . && \
  rg -q -i 'purpose' . && \
  rg -q -i 'design direction' . && \
  rg -q -i 'analyze first' .
) | tee "${POSTCHECK_LOG}"
POSTCHECK_STATUS=$?
if [[ ${POSTCHECK_STATUS} -eq 0 ]] && [[ -f "${TARGET_REPO}/tests/acceptance_checks.sh" ]]; then
  (
    cd "${TARGET_REPO}/tests" && \
    bash acceptance_checks.sh
  ) | tee -a "${POSTCHECK_LOG}"
  POSTCHECK_STATUS=$?
fi
set -e
set +x

echo
echo "medCSS modernizer test completed"
echo "  Agent:       ${CAM_TEST_AGENT}"
echo "  Target repo: ${TARGET_REPO}"
echo "  Spec file:   ${SPEC_FILE}"
echo "  Create log:  ${CREATE_LOG}"
echo "  Validate log:${VALIDATE_LOG}"
echo "  Postcheck log:${POSTCHECK_LOG}"
echo "  Create exit: ${CREATE_STATUS}"
echo "  Validate exit:${VALIDATE_STATUS}"
echo "  Postcheck exit:${POSTCHECK_STATUS}"

if [[ ${CREATE_STATUS} -ne 0 || ${VALIDATE_STATUS} -ne 0 || ${POSTCHECK_STATUS} -ne 0 ]]; then
  exit 1
fi
