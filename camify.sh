#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  camify.sh — CAM Quickstart
#  One-command cam-ify for any repository.
#
#  First-time users:   ./camify.sh
#  Returning users:    ./camify.sh <repo-url-or-path>
#  Non-interactive:    ./camify.sh --yes <repo-url-or-path>
#  Actually modify:    ./camify.sh --enhance <repo-url-or-path>
#  Resume last run:    ./camify.sh --resume
#  Rerun env wizard:   ./camify.sh --reconfig
#  Rebuild venv:       ./camify.sh --reinstall
#
#  Stops before any expensive or destructive action and asks for confirmation.
#  See --help for full flag list.
# ═══════════════════════════════════════════════════════════════════════════

set -o pipefail
# Do NOT use set -e globally — we want to handle failures ourselves so the
# user gets helpful error messages instead of silent exits.

# ─── Constants ────────────────────────────────────────────────────────────

SCRIPT_VERSION="0.1.0"
CAM_REPO_URL="https://github.com/deesatzed/CAM-Pulse.git"
CAM_HOME_DEFAULT="${HOME}/.cam-pulse"
TARGET_HOME_DEFAULT="${HOME}/cam_test"
STATE_DIR="${HOME}/.cam-pulse-state"
STATE_FILE="${STATE_DIR}/camify-state.json"
LOG_DIR=".camify-logs"
MIN_PYTHON_MAJOR=3
MIN_PYTHON_MINOR=12

# ─── Colors ───────────────────────────────────────────────────────────────

if [[ -t 1 ]] && [[ -z "${NO_COLOR:-}" ]]; then
    C_RESET=$'\033[0m'
    C_DIM=$'\033[2m'
    C_BOLD=$'\033[1m'
    C_RED=$'\033[31m'
    C_GREEN=$'\033[32m'
    C_YELLOW=$'\033[33m'
    C_BLUE=$'\033[34m'
    C_CYAN=$'\033[36m'
else
    C_RESET=""; C_DIM=""; C_BOLD=""; C_RED=""; C_GREEN=""
    C_YELLOW=""; C_BLUE=""; C_CYAN=""
fi

# ─── Logging helpers ──────────────────────────────────────────────────────

say()  { printf "%s\n" "$*"; }
info() { printf "${C_CYAN}%s${C_RESET}\n" "$*"; }
ok()   { printf "${C_GREEN}✓${C_RESET} %s\n" "$*"; }
warn() { printf "${C_YELLOW}⚠${C_RESET} %s\n" "$*" >&2; }
err()  { printf "${C_RED}✗${C_RESET} %s\n" "$*" >&2; }
die()  { err "$*"; exit 1; }

hr()   { printf "${C_DIM}%s${C_RESET}\n" "────────────────────────────────────────────────────────────────────────"; }

banner() {
    say ""
    printf "${C_BOLD}${C_BLUE}%s${C_RESET}\n" "  $1"
    hr
}

# ─── State file helpers (simple key=value, not real JSON) ─────────────────

state_init() {
    mkdir -p "$STATE_DIR"
    [[ -f "$STATE_FILE" ]] || printf "# camify.sh state — do not edit manually\n" > "$STATE_FILE"
}

state_set() {
    # Usage: state_set KEY VALUE
    local key="$1"
    local value="$2"
    state_init
    # Remove any existing line for this key, then append
    local tmp="${STATE_FILE}.tmp"
    grep -v "^${key}=" "$STATE_FILE" 2>/dev/null > "$tmp" || true
    printf "%s=%s\n" "$key" "$value" >> "$tmp"
    mv "$tmp" "$STATE_FILE"
}

state_get() {
    # Usage: state_get KEY [default]
    local key="$1"
    local default="${2:-}"
    if [[ -f "$STATE_FILE" ]]; then
        local val
        val=$(grep -E "^${key}=" "$STATE_FILE" 2>/dev/null | tail -1 | cut -d= -f2-)
        printf "%s" "${val:-$default}"
    else
        printf "%s" "$default"
    fi
}

# ─── Input helpers ────────────────────────────────────────────────────────

confirm() {
    # Usage: confirm "prompt" [default_yes]
    # Returns 0 on yes, 1 on no. Respects --yes flag.
    local prompt="$1"
    local default_yes="${2:-0}"

    if [[ "$NON_INTERACTIVE" == "1" ]]; then
        if [[ "$default_yes" == "1" ]]; then
            say "${prompt} [auto-yes]"
            return 0
        else
            say "${prompt} [auto-no]"
            return 1
        fi
    fi

    local hint="[y/N]"
    [[ "$default_yes" == "1" ]] && hint="[Y/n]"
    local reply
    read -r -p "${C_CYAN}?${C_RESET} ${prompt} ${hint} " reply
    if [[ -z "$reply" ]]; then
        [[ "$default_yes" == "1" ]] && return 0 || return 1
    fi
    [[ "$reply" =~ ^[Yy] ]] && return 0 || return 1
}

prompt_input() {
    # Usage: prompt_input "question" [default]
    local question="$1"
    local default="${2:-}"
    if [[ "$NON_INTERACTIVE" == "1" ]]; then
        printf "%s" "$default"
        return
    fi
    local reply
    if [[ -n "$default" ]]; then
        read -r -p "${C_CYAN}?${C_RESET} ${question} [${default}]: " reply
        printf "%s" "${reply:-$default}"
    else
        read -r -p "${C_CYAN}?${C_RESET} ${question}: " reply
        printf "%s" "$reply"
    fi
}

prompt_secret() {
    # Usage: prompt_secret "question"
    local question="$1"
    if [[ "$NON_INTERACTIVE" == "1" ]]; then
        die "Cannot prompt for secret in --yes mode. Set via .env first."
    fi
    local reply
    read -r -s -p "${C_CYAN}?${C_RESET} ${question}: " reply
    printf "\n" >&2
    printf "%s" "$reply"
}

# ─── Trap / cleanup ───────────────────────────────────────────────────────

on_exit() {
    local code=$?
    if [[ $code -ne 0 ]] && [[ -n "${CURRENT_STAGE:-}" ]]; then
        err "camify.sh aborted during stage: ${CURRENT_STAGE}"
        say "${C_DIM}Resume with:${C_RESET} ${C_BOLD}./camify.sh --resume${C_RESET}"
        say "${C_DIM}Last logs:${C_RESET}     ${LOG_DIR}/"
    fi
    exit $code
}
trap on_exit EXIT INT TERM

# ─── Argument parsing ─────────────────────────────────────────────────────

TARGET_REPO=""
NON_INTERACTIVE=0
DO_ENHANCE=0
DO_RESUME=0
DO_REINSTALL=0
DO_RECONFIG=0
STOP_AT=""
DRY_RUN=0
GOALS=()

usage() {
    cat <<EOF
${C_BOLD}camify.sh${C_RESET} — CAM Quickstart v${SCRIPT_VERSION}

${C_BOLD}USAGE${C_RESET}
    ./camify.sh [OPTIONS] [REPO_URL_OR_PATH]

${C_BOLD}ARGUMENTS${C_RESET}
    REPO_URL_OR_PATH    Git URL or local path of the repo to cam-ify.
                        If omitted, the wizard will ask.

${C_BOLD}OPTIONS${C_RESET}
    --yes, -y           Non-interactive mode. Accept defaults, don't prompt.
                        Still stops before 'enhance' unless --enhance is set.
    --enhance           Allow the script to actually modify the target repo
                        (runs 'cam enhance'). Without this, it stops after
                        generating the enhancement plan.
    --goal TEXT, -g     Enhancement goal (repeatable). If none given, CAM
                        decides based on the repo profile.
    --stop-at STAGE     Stop after a specific stage. One of:
                          preflight, install, setup, target,
                          structural, quick, camify, enhance
    --resume            Resume from the last successful stage.
    --reinstall         Force rebuild of the CAM venv.
    --reconfig          Re-run the .env wizard (new keys or new models).
    --dry-run           Print the commands that would run, don't execute
                        expensive or destructive ones.
    --version           Print script version and exit.
    --help, -h          Show this help and exit.

${C_BOLD}EXAMPLES${C_RESET}
    # First time, fully interactive
    ./camify.sh

    # Cam-ify a specific repo
    ./camify.sh https://github.com/user/repo.git

    # Full pipeline, no prompts, including actual file changes
    ./camify.sh --yes --enhance https://github.com/user/repo.git

    # Just run the planner, stop before any LLM cost
    ./camify.sh --stop-at structural /path/to/local/repo

    # With specific enhancement goals
    ./camify.sh -g "improve error handling" -g "add README" ./my-repo
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)       usage; exit 0 ;;
        --version)       say "camify.sh v${SCRIPT_VERSION}"; exit 0 ;;
        -y|--yes)        NON_INTERACTIVE=1; shift ;;
        --enhance)       DO_ENHANCE=1; shift ;;
        -g|--goal)       GOALS+=("$2"); shift 2 ;;
        --stop-at)       STOP_AT="$2"; shift 2 ;;
        --resume)        DO_RESUME=1; shift ;;
        --reinstall)     DO_REINSTALL=1; shift ;;
        --reconfig)      DO_RECONFIG=1; shift ;;
        --dry-run)       DRY_RUN=1; shift ;;
        -*)              die "Unknown option: $1 (try --help)" ;;
        *)
            if [[ -z "$TARGET_REPO" ]]; then
                TARGET_REPO="$1"
            else
                die "Extra positional argument: $1 (only one repo at a time)"
            fi
            shift
            ;;
    esac
done

# Validate --stop-at
case "$STOP_AT" in
    ""|preflight|install|setup|target|structural|quick|camify|enhance) ;;
    *) die "Invalid --stop-at '${STOP_AT}'. Valid: preflight install setup target structural quick camify enhance" ;;
esac

# ─── Stage gate helper ────────────────────────────────────────────────────

stage_gate() {
    # Usage: stage_gate STAGE_NAME
    # Returns 1 (stop) if STOP_AT matches this stage's predecessor.
    local stage="$1"
    CURRENT_STAGE="$stage"
    state_set "last_stage" "$stage"
    if [[ -n "$STOP_AT" ]] && [[ "$STOP_AT" == "$stage" ]]; then
        # Mark the stop stage as the one we just finished
        return 0
    fi
    return 0
}

should_stop_after() {
    # Usage: should_stop_after STAGE_NAME
    # Returns 0 if we should stop after this stage.
    [[ -n "$STOP_AT" ]] && [[ "$STOP_AT" == "$1" ]]
}

# ═══════════════════════════════════════════════════════════════════════════
#  Stage 0 — Preflight
# ═══════════════════════════════════════════════════════════════════════════

stage_preflight() {
    stage_gate "preflight"
    banner "Stage 0: Preflight"

    local os_name
    os_name=$(uname -s)
    case "$os_name" in
        Darwin) ok "OS: macOS ($os_name)" ;;
        Linux)  ok "OS: Linux" ;;
        MINGW*|MSYS*|CYGWIN*)
            err "Windows detected. Please use WSL2 with Ubuntu."
            die "Aborted — unsupported OS."
            ;;
        *)      warn "Unrecognized OS: $os_name (continuing anyway)" ;;
    esac

    # Python check
    local py_bin=""
    for cand in python3.13 python3.12 python3; do
        if command -v "$cand" >/dev/null 2>&1; then
            py_bin="$cand"
            break
        fi
    done

    if [[ -z "$py_bin" ]]; then
        err "No Python 3 found in PATH."
        case "$os_name" in
            Darwin) say "Install: ${C_BOLD}brew install python@3.12${C_RESET}" ;;
            Linux)  say "Install: ${C_BOLD}sudo apt install python3.12 python3.12-venv${C_RESET}" ;;
        esac
        die "Python 3.${MIN_PYTHON_MINOR}+ required."
    fi

    local py_version
    py_version=$("$py_bin" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null)
    local py_major="${py_version%.*}"
    local py_minor="${py_version#*.}"

    if [[ -z "$py_version" ]]; then
        die "Could not determine Python version from $py_bin"
    fi

    if (( py_major < MIN_PYTHON_MAJOR )) || { (( py_major == MIN_PYTHON_MAJOR )) && (( py_minor < MIN_PYTHON_MINOR )); }; then
        err "Python ${py_version} found, but ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ is required."
        case "$os_name" in
            Darwin) say "Install: ${C_BOLD}brew install python@3.12${C_RESET}" ;;
            Linux)  say "Install: ${C_BOLD}sudo apt install python3.12 python3.12-venv${C_RESET}" ;;
        esac
        die "Please install Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ and re-run."
    fi
    ok "Python ${py_version} at $(command -v "$py_bin")"
    PYTHON_BIN="$py_bin"

    # Git check
    if ! command -v git >/dev/null 2>&1; then
        die "git not found. Install it and re-run."
    fi
    ok "git $(git --version | awk '{print $3}')"

    # curl check
    if ! command -v curl >/dev/null 2>&1; then
        die "curl not found. Install it and re-run."
    fi
    ok "curl available"

    state_set "preflight" "ok"
    state_set "python_bin" "$PYTHON_BIN"

    should_stop_after "preflight" && { ok "Stopped after preflight as requested."; exit 0; }
}

# ═══════════════════════════════════════════════════════════════════════════
#  Stage 1 — CAM install (detect existing or clone + venv)
# ═══════════════════════════════════════════════════════════════════════════

stage_install() {
    stage_gate "install"
    banner "Stage 1: CAM Install"

    # Case A: running from inside a CAM-Pulse checkout
    local script_dir
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [[ -f "${script_dir}/claw.toml" ]] && [[ -f "${script_dir}/pyproject.toml" ]]; then
        if grep -q 'name = "claw"' "${script_dir}/pyproject.toml" 2>/dev/null; then
            CAM_HOME="$script_dir"
            ok "Using existing CAM-Pulse checkout: ${CAM_HOME}"
        fi
    fi

    # Case B: previously bootstrapped to ~/.cam-pulse
    if [[ -z "${CAM_HOME:-}" ]] && [[ -d "$CAM_HOME_DEFAULT" ]] && [[ -f "${CAM_HOME_DEFAULT}/claw.toml" ]]; then
        CAM_HOME="$CAM_HOME_DEFAULT"
        ok "Using existing CAM-Pulse at: ${CAM_HOME}"
    fi

    # Case C: fresh bootstrap
    if [[ -z "${CAM_HOME:-}" ]]; then
        CAM_HOME="$CAM_HOME_DEFAULT"
        info "No existing CAM-Pulse found. Cloning to ${CAM_HOME}..."
        if [[ "$DRY_RUN" == "1" ]]; then
            say "[dry-run] git clone $CAM_REPO_URL $CAM_HOME"
        else
            git clone --quiet "$CAM_REPO_URL" "$CAM_HOME" \
                || die "git clone failed. Check network and try again."
            ok "Cloned CAM-Pulse"
        fi
    fi

    cd "$CAM_HOME" || die "Cannot cd to $CAM_HOME"
    state_set "cam_home" "$CAM_HOME"

    # venv
    local venv="${CAM_HOME}/.venv"
    if [[ "$DO_REINSTALL" == "1" ]] && [[ -d "$venv" ]]; then
        info "Rebuilding venv per --reinstall..."
        rm -rf "$venv"
    fi

    if [[ ! -d "$venv" ]]; then
        info "Creating venv..."
        if [[ "$DRY_RUN" == "1" ]]; then
            say "[dry-run] $PYTHON_BIN -m venv $venv"
        else
            "$PYTHON_BIN" -m venv "$venv" || die "venv creation failed"
            ok "venv created"
        fi
    else
        ok "venv exists"
    fi

    # shellcheck disable=SC1091
    if [[ "$DRY_RUN" != "1" ]]; then
        source "${venv}/bin/activate" || die "Could not activate venv"
    fi

    # Install CAM if `cam` CLI is missing OR --reinstall requested
    local need_install=0
    if [[ "$DO_REINSTALL" == "1" ]]; then
        need_install=1
    elif ! command -v cam >/dev/null 2>&1; then
        need_install=1
    fi

    if [[ "$need_install" == "1" ]]; then
        # Prefer `uv` when available — it's 10-100x faster than pip and
        # handles venv-aware installs cleanly. Fall back to pip on
        # machines where uv isn't installed.
        local installer_desc="pip"
        if command -v uv >/dev/null 2>&1; then
            installer_desc="uv pip"
        fi
        info "Installing CAM ($installer_desc install -e .) ..."
        if [[ "$DRY_RUN" == "1" ]]; then
            say "[dry-run] $installer_desc install -q -e ."
        else
            if command -v uv >/dev/null 2>&1; then
                # `source .venv/bin/activate` above set VIRTUAL_ENV so
                # uv will install into the active venv automatically.
                uv pip install --quiet -e . 2>&1 | tail -20 \
                    || die "uv pip install failed. Check Python version and network."
            else
                pip install --quiet --upgrade pip >/dev/null 2>&1 || true
                pip install --quiet -e . 2>&1 | tail -20 \
                    || die "pip install failed. Check Python version and network."
            fi
            ok "CAM installed"
        fi
    else
        ok "CAM already installed"
    fi

    # Verify
    if [[ "$DRY_RUN" != "1" ]]; then
        if ! cam --help >/dev/null 2>&1; then
            die "cam CLI is broken. Try: ./camify.sh --reinstall"
        fi
        ok "cam CLI responds"
    fi

    state_set "install" "ok"
    should_stop_after "install" && { ok "Stopped after install as requested."; exit 0; }
}

# ═══════════════════════════════════════════════════════════════════════════
#  Stage 2 — .env wizard
# ═══════════════════════════════════════════════════════════════════════════

validate_openrouter_key() {
    # Usage: validate_openrouter_key KEY
    # Returns 0 if key works, 1 otherwise.
    local key="$1"
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer ${key}" \
        "https://openrouter.ai/api/v1/auth/key" 2>/dev/null || echo "000")
    [[ "$http_code" == "200" ]]
}

fetch_openrouter_models() {
    # Writes model IDs (one per line) to stdout.
    curl -s "https://openrouter.ai/api/v1/models" 2>/dev/null \
      | "$PYTHON_BIN" -c 'import sys, json; d=json.load(sys.stdin); print("\n".join(m["id"] for m in d.get("data", [])))' \
      2>/dev/null || true
}

validate_slug() {
    # Usage: validate_slug SLUG MODEL_LIST_FILE
    local slug="$1"
    local list_file="$2"
    grep -Fxq "$slug" "$list_file"
}

pick_model() {
    # Usage: pick_model "Claude" "anthropic/" "z-ai/" MODEL_LIST_FILE
    # Prompts user; returns slug on stdout.
    local slot_name="$1"
    local primary_prefix="$2"
    local secondary_prefix="$3"
    local list_file="$4"

    say ""
    info "Pick a model for the ${C_BOLD}${slot_name}${C_RESET}${C_CYAN} agent slot${C_RESET}"
    say "${C_DIM}  (used for: see .env.example for per-slot description)${C_RESET}"

    # Show ~10 candidates matching the prefix
    local candidates
    candidates=$(grep -E "^(${primary_prefix}|${secondary_prefix})" "$list_file" | head -12)
    if [[ -z "$candidates" ]]; then
        candidates=$(head -12 "$list_file")
    fi

    local i=1
    while IFS= read -r model; do
        printf "  ${C_BOLD}%2d${C_RESET}. %s\n" "$i" "$model"
        ((i++))
    done <<< "$candidates"
    say "   ${C_DIM}0. Skip this slot${C_RESET}"
    say "   ${C_DIM}c. Enter a custom slug${C_RESET}"

    local choice slug
    while true; do
        choice=$(prompt_input "Choice for ${slot_name}" "1")
        case "$choice" in
            0)
                printf ""
                return 0
                ;;
            c|C)
                slug=$(prompt_input "Enter custom slug (vendor/model-name)" "")
                if [[ -z "$slug" ]]; then
                    warn "Empty slug — try again"
                    continue
                fi
                if validate_slug "$slug" "$list_file"; then
                    printf "%s" "$slug"
                    return 0
                else
                    warn "Slug '${slug}' not found in OpenRouter catalog"
                    confirm "Use it anyway?" 0 && { printf "%s" "$slug"; return 0; }
                fi
                ;;
            ''|*[!0-9]*)
                warn "Enter a number or 'c' for custom"
                ;;
            *)
                slug=$(printf "%s\n" "$candidates" | sed -n "${choice}p")
                if [[ -z "$slug" ]]; then
                    warn "Invalid choice — try again"
                    continue
                fi
                printf "%s" "$slug"
                return 0
                ;;
        esac
    done
}

stage_setup() {
    stage_gate "setup"
    banner "Stage 2: Configuration (.env + cam setup)"

    local env_file="${CAM_HOME}/.env"

    # If .env exists and user didn't request reconfig, try to reuse
    if [[ -f "$env_file" ]] && [[ "$DO_RECONFIG" != "1" ]]; then
        if grep -q "^OPENROUTER_API_KEY=" "$env_file" \
           && grep -q "^CAM_MODEL_CLAUDE=" "$env_file"; then
            ok "Existing .env found (use --reconfig to re-run wizard)"
            state_set "setup" "ok"
            should_stop_after "setup" && { ok "Stopped after setup as requested."; exit 0; }
            return 0
        fi
    fi

    # New or forced reconfig
    if [[ "$NON_INTERACTIVE" == "1" ]]; then
        if [[ "$DRY_RUN" == "1" ]]; then
            warn "Dry-run + --yes: skipping interactive setup wizard."
            warn "(.env at $env_file is missing or incomplete; real run would prompt here.)"
            state_set "setup" "skipped-dryrun"
            should_stop_after "setup" && { ok "Stopped after setup as requested."; exit 0; }
            return 0
        fi
        die "No valid .env and --yes was set. Create .env manually or run without --yes."
    fi

    say ""
    say "${C_BOLD}Let's set up your API keys and models.${C_RESET}"
    say ""

    # OpenRouter key — prompt and validate live
    local openrouter_key=""
    while true; do
        say "Get an OpenRouter key at: ${C_BOLD}https://openrouter.ai/keys${C_RESET}"
        openrouter_key=$(prompt_secret "Paste your OpenRouter API key")
        if [[ -z "$openrouter_key" ]]; then
            warn "Empty key — try again"
            continue
        fi
        info "Validating key against OpenRouter..."
        if validate_openrouter_key "$openrouter_key"; then
            ok "Key accepted by OpenRouter"
            break
        else
            err "Key was rejected (HTTP non-200). Check and try again."
            confirm "Try a different key?" 1 || die "Aborted during key entry."
        fi
    done

    # Optional Google key
    say ""
    say "${C_DIM}Google API key is optional (used for embeddings/novelty scoring)${C_RESET}"
    say "${C_DIM}Get one at: https://aistudio.google.com/apikey${C_RESET}"
    local google_key
    google_key=$(prompt_secret "Paste Google key (or press Enter to skip)") || google_key=""

    # Fetch model catalog
    say ""
    info "Fetching OpenRouter model catalog..."
    local models_file
    models_file=$(mktemp)
    fetch_openrouter_models > "$models_file"
    local model_count
    model_count=$(wc -l < "$models_file" | tr -d ' ')
    if [[ "$model_count" -lt 10 ]]; then
        rm -f "$models_file"
        die "Could not fetch OpenRouter model catalog. Check network."
    fi
    ok "Loaded ${model_count} models"

    # Pick models
    local claude_model codex_model gemini_model grok_model
    claude_model=$(pick_model "Claude" "anthropic/" "z-ai/" "$models_file")
    codex_model=$(pick_model "Codex"  "openai/"    "qwen/"  "$models_file")
    gemini_model=$(pick_model "Gemini" "google/"   "google/" "$models_file")
    grok_model=$(pick_model  "Grok"   "x-ai/"     "x-ai/"  "$models_file")

    rm -f "$models_file"

    # Confirmation summary
    say ""
    hr
    say "${C_BOLD}Configuration summary${C_RESET}"
    printf "  Claude : %s\n" "${claude_model:-<skipped>}"
    printf "  Codex  : %s\n" "${codex_model:-<skipped>}"
    printf "  Gemini : %s\n" "${gemini_model:-<skipped>}"
    printf "  Grok   : %s\n" "${grok_model:-<skipped>}"
    hr

    if ! confirm "Write this to .env?" 1; then
        die "Aborted during config confirmation."
    fi

    # Write .env atomically
    local tmp_env="${env_file}.tmp"
    {
        printf "# ════════════════════════════════════════════════════════════════\n"
        printf "#  CAM .env — generated by camify.sh v%s on %s\n" "$SCRIPT_VERSION" "$(date '+%Y-%m-%d %H:%M:%S')"
        printf "#  Re-run './camify.sh --reconfig' to regenerate.\n"
        printf "# ════════════════════════════════════════════════════════════════\n"
        printf "\n"
        printf "OPENROUTER_API_KEY=%s\n" "$openrouter_key"
        [[ -n "$google_key" ]] && printf "GOOGLE_API_KEY=%s\n" "$google_key"
        printf "\n"
        [[ -n "$claude_model" ]] && printf "CAM_MODEL_CLAUDE=%s\n" "$claude_model"
        [[ -n "$codex_model"  ]] && printf "CAM_MODEL_CODEX=%s\n"  "$codex_model"
        [[ -n "$gemini_model" ]] && printf "CAM_MODEL_GEMINI=%s\n" "$gemini_model"
        [[ -n "$grok_model"   ]] && printf "CAM_MODEL_GROK=%s\n"   "$grok_model"
    } > "$tmp_env"
    mv "$tmp_env" "$env_file"
    chmod 600 "$env_file"
    ok ".env written"

    # Run cam setup
    info "Running 'cam setup' to wire config into claw.toml..."
    if [[ "$DRY_RUN" == "1" ]]; then
        say "[dry-run] cam setup --config ./claw.toml"
    else
        # setup is interactive for budgets — feed default empty lines so it
        # accepts the defaults
        printf '\n\n\n\n' | cam setup --config "./claw.toml" \
            || die "'cam setup' failed. Check the output above."
        ok "cam setup complete"
    fi

    # Sanity check with cam status
    info "Running 'cam status' to verify agents..."
    if [[ "$DRY_RUN" != "1" ]]; then
        cam status 2>&1 | tee "${CAM_HOME}/${LOG_DIR:-.camify-logs}/setup-status.log" >/dev/null || true
        if cam status 2>&1 | grep -q "available"; then
            ok "Agents reporting available"
        else
            warn "cam status did not report any available agents. Continuing anyway."
        fi
    fi

    state_set "setup" "ok"
    should_stop_after "setup" && { ok "Stopped after setup as requested."; exit 0; }
}

# ═══════════════════════════════════════════════════════════════════════════
#  Stage 3 — Target repo
# ═══════════════════════════════════════════════════════════════════════════

stage_target() {
    stage_gate "target"
    banner "Stage 3: Target Repository"

    # If not supplied on CLI, prompt
    if [[ -z "$TARGET_REPO" ]]; then
        if [[ "$NON_INTERACTIVE" == "1" ]]; then
            die "No target repo given and --yes set. Pass a repo as the first argument."
        fi
        say "What repo do you want to cam-ify?"
        say "  1. A git URL (https://github.com/...)"
        say "  2. A local path"
        say "  3. Self-enhance (CAM-Pulse itself — dogfood demo)"
        local recent
        recent=$(state_get "last_target")
        if [[ -n "$recent" ]]; then
            say "  4. Recent: ${recent}"
        fi
        say ""
        local choice
        choice=$(prompt_input "Choice" "1")
        case "$choice" in
            1) TARGET_REPO=$(prompt_input "Git URL") ;;
            2) TARGET_REPO=$(prompt_input "Local path") ;;
            3) TARGET_REPO="$CAM_HOME" ;;
            4) TARGET_REPO="$recent" ;;
            *) die "Invalid choice" ;;
        esac
    fi

    [[ -z "$TARGET_REPO" ]] && die "No target repo specified."

    # Resolve: URL vs local path
    local target_path=""
    if [[ "$TARGET_REPO" =~ ^https?:// ]] || [[ "$TARGET_REPO" =~ ^git@ ]]; then
        # Clone
        mkdir -p "$TARGET_HOME_DEFAULT"
        local repo_name
        repo_name=$(basename "$TARGET_REPO" .git)
        target_path="${TARGET_HOME_DEFAULT}/${repo_name}"

        if [[ -d "$target_path/.git" ]]; then
            ok "Target already cloned at ${target_path}"
            if confirm "Pull latest?" 0; then
                (cd "$target_path" && git pull --ff-only --quiet) && ok "Updated" || warn "Pull failed, using existing"
            fi
        else
            info "Cloning ${TARGET_REPO} into ${target_path}..."
            if [[ "$DRY_RUN" == "1" ]]; then
                say "[dry-run] git clone $TARGET_REPO $target_path"
            else
                git clone --quiet "$TARGET_REPO" "$target_path" \
                    || die "git clone failed for ${TARGET_REPO}"
                ok "Cloned target"
            fi
        fi
    else
        # Local path
        target_path=$(cd "$TARGET_REPO" 2>/dev/null && pwd) || die "Target path does not exist: $TARGET_REPO"
        ok "Using local path: ${target_path}"
    fi

    TARGET_PATH="$target_path"
    state_set "last_target" "$TARGET_PATH"
    state_set "target" "ok"

    # Quick summary
    local py_count
    py_count=$(find "$TARGET_PATH" -name "*.py" 2>/dev/null | head -500 | wc -l | tr -d ' ')
    local has_tests="no"
    [[ -d "${TARGET_PATH}/tests" ]] || [[ -d "${TARGET_PATH}/test" ]] && has_tests="yes"
    say "  ${C_DIM}Python files:${C_RESET} ${py_count}"
    say "  ${C_DIM}Has tests dir:${C_RESET} ${has_tests}"

    should_stop_after "target" && { ok "Stopped after target as requested."; exit 0; }
}

# ═══════════════════════════════════════════════════════════════════════════
#  Stage 4 — Structural evaluate (free)
# ═══════════════════════════════════════════════════════════════════════════

stage_structural() {
    stage_gate "structural"
    banner "Stage 4: Structural Analysis (free, no LLM calls)"

    mkdir -p "${CAM_HOME}/${LOG_DIR}"
    local log="${CAM_HOME}/${LOG_DIR}/$(date +%Y%m%d-%H%M%S)-structural.log"

    if [[ "$DRY_RUN" == "1" ]]; then
        say "[dry-run] cam evaluate $TARGET_PATH --mode structural --config ./claw.toml"
    else
        cam evaluate "$TARGET_PATH" --mode structural --config "./claw.toml" 2>&1 | tee "$log" \
            || { err "Structural evaluate failed"; tail -30 "$log" >&2; die "See $log"; }
    fi

    state_set "structural" "ok"
    ok "Structural analysis complete"
    say "  ${C_DIM}Log:${C_RESET} $log"

    should_stop_after "structural" && { ok "Stopped after structural as requested."; exit 0; }

    if ! confirm "Proceed to LLM-powered quick evaluate? (estimated cost ~\$0.10–\$1.00)" 1; then
        ok "Stopping before LLM calls. Resume with: ./camify.sh --resume"
        exit 0
    fi
}

# ═══════════════════════════════════════════════════════════════════════════
#  Stage 5 — Quick evaluate (first real LLM calls)
# ═══════════════════════════════════════════════════════════════════════════

stage_quick() {
    stage_gate "quick"
    banner "Stage 5: Quick Evaluate (LLM — real cost)"

    mkdir -p "${CAM_HOME}/${LOG_DIR}"
    local log="${CAM_HOME}/${LOG_DIR}/$(date +%Y%m%d-%H%M%S)-quick.log"

    info "Running cam evaluate --mode quick ..."
    if [[ "$DRY_RUN" == "1" ]]; then
        say "[dry-run] cam evaluate $TARGET_PATH --mode quick --config ./claw.toml"
    else
        cam evaluate "$TARGET_PATH" --mode quick --config "./claw.toml" 2>&1 | tee "$log" \
            || { err "Quick evaluate failed"; tail -30 "$log" >&2; die "See $log"; }
    fi

    state_set "quick" "ok"
    ok "Quick evaluate complete"
    say "  ${C_DIM}Log:${C_RESET} $log"

    should_stop_after "quick" && { ok "Stopped after quick as requested."; exit 0; }

    if ! confirm "Proceed to generate enhancement plan (cam camify)?" 1; then
        ok "Stopping before camify. Resume with: ./camify.sh --resume"
        exit 0
    fi
}

# ═══════════════════════════════════════════════════════════════════════════
#  Stage 6 — Camify (planner, also real LLM cost)
# ═══════════════════════════════════════════════════════════════════════════

stage_camify() {
    stage_gate "camify"
    banner "Stage 6: Enhancement Planner (cam camify)"

    mkdir -p "${CAM_HOME}/${LOG_DIR}"
    local log="${CAM_HOME}/${LOG_DIR}/$(date +%Y%m%d-%H%M%S)-camify.log"

    local goal_args=()
    for g in "${GOALS[@]}"; do
        goal_args+=(--goal "$g")
    done

    info "Running cam camify ..."
    if [[ "${#GOALS[@]}" -eq 0 ]]; then
        say "  ${C_DIM}No --goal given. CAM will prompt you, or decide based on the repo.${C_RESET}"
    fi

    if [[ "$DRY_RUN" == "1" ]]; then
        say "[dry-run] cam camify $TARGET_PATH ${goal_args[*]} --config ./claw.toml"
    else
        cam camify "$TARGET_PATH" "${goal_args[@]}" --config "./claw.toml" 2>&1 | tee "$log" \
            || { err "cam camify failed"; tail -30 "$log" >&2; die "See $log"; }
    fi

    state_set "camify" "ok"
    ok "Enhancement plan generated"
    say "  ${C_DIM}Log:${C_RESET} $log"

    should_stop_after "camify" && { ok "Stopped after camify as requested."; exit 0; }

    # Enhance gate — always require explicit opt-in
    if [[ "$DO_ENHANCE" != "1" ]]; then
        say ""
        warn "Not running 'cam enhance' — this would modify files in:"
        say "      ${C_BOLD}${TARGET_PATH}${C_RESET}"
        say ""
        say "To actually apply the plan, re-run with: ${C_BOLD}--enhance${C_RESET}"
        say "Example: ${C_BOLD}./camify.sh --resume --enhance${C_RESET}"
        say ""
        ok "Stopping before enhance (safe default)."
        exit 0
    fi
}

# ═══════════════════════════════════════════════════════════════════════════
#  Stage 7 — Enhance (modifies target repo!)
# ═══════════════════════════════════════════════════════════════════════════

stage_enhance() {
    stage_gate "enhance"
    banner "Stage 7: Apply Enhancements (cam enhance — MODIFIES FILES)"

    # Safety: target repo must be a clean git tree
    if [[ -d "${TARGET_PATH}/.git" ]]; then
        local dirty
        dirty=$(cd "$TARGET_PATH" && git status --porcelain 2>/dev/null | head -1)
        if [[ -n "$dirty" ]]; then
            err "Target repo has uncommitted changes. Commit or stash first."
            die "  ${TARGET_PATH}"
        fi
        ok "Target git tree is clean"
    else
        warn "Target is not a git repo — changes will NOT be reversible via git"
        if ! confirm "Continue anyway?" 0; then
            die "Aborted."
        fi
    fi

    # Final confirmation — even with --yes, this stage needs an extra nudge
    say ""
    warn "About to run ${C_BOLD}cam enhance${C_RESET}${C_YELLOW} against:${C_RESET}"
    say "      ${C_BOLD}${TARGET_PATH}${C_RESET}"
    say ""
    if [[ "$NON_INTERACTIVE" != "1" ]]; then
        if ! confirm "Proceed with file modifications?" 0; then
            die "Aborted at final enhance gate."
        fi
    else
        warn "--yes is set; proceeding without final prompt. (This is your doing.)"
    fi

    mkdir -p "${CAM_HOME}/${LOG_DIR}"
    local log="${CAM_HOME}/${LOG_DIR}/$(date +%Y%m%d-%H%M%S)-enhance.log"

    if [[ "$DRY_RUN" == "1" ]]; then
        say "[dry-run] cam enhance $TARGET_PATH --config ./claw.toml"
    else
        cam enhance "$TARGET_PATH" --config "./claw.toml" 2>&1 | tee "$log" \
            || { err "cam enhance failed"; tail -30 "$log" >&2; die "See $log"; }
    fi

    state_set "enhance" "ok"
    ok "Enhancement complete"
    say "  ${C_DIM}Log:${C_RESET} $log"

    # Post-run summary
    if [[ -d "${TARGET_PATH}/.git" ]]; then
        say ""
        say "${C_BOLD}Changes in target repo:${C_RESET}"
        (cd "$TARGET_PATH" && git status --short)
        say ""
        say "Review with: ${C_BOLD}cd ${TARGET_PATH} && git diff${C_RESET}"
    fi
}

# ═══════════════════════════════════════════════════════════════════════════
#  Main dispatch
# ═══════════════════════════════════════════════════════════════════════════

main() {
    state_init

    say ""
    printf "${C_BOLD}${C_BLUE}  CAM Quickstart${C_RESET} ${C_DIM}v%s${C_RESET}\n" "$SCRIPT_VERSION"
    say "  ${C_DIM}Cam-ify any repo in a few steps with guard rails on every step.${C_RESET}"

    if [[ "$DO_RESUME" == "1" ]]; then
        local last
        last=$(state_get "last_stage")
        info "Resuming from state: last_stage=${last:-<none>}"
        # Load prior target if no new one given
        if [[ -z "$TARGET_REPO" ]]; then
            TARGET_REPO=$(state_get "last_target")
            [[ -n "$TARGET_REPO" ]] && ok "Resumed target: $TARGET_REPO"
        fi
    fi

    stage_preflight
    stage_install
    stage_setup
    stage_target
    stage_structural
    stage_quick
    stage_camify
    stage_enhance

    say ""
    ok "${C_BOLD}All stages complete.${C_RESET}"
    say ""
}

main "$@"
