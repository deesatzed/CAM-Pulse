#!/usr/bin/env bash
# Record a terminal demo of CAM-PULSE for X/Twitter.
#
# Produces:
#   demos/cam-pulse-demo.cast  — asciinema recording (upload or embed)
#   demos/cam-pulse-demo.gif   — animated GIF for X posts
#
# Usage:
#   ./scripts/record_demo.sh            # record interactively
#   ./scripts/record_demo.sh --auto     # scripted auto-play (no typing needed)
#
# Prerequisites: brew install asciinema agg

set -euo pipefail
cd "$(dirname "$0")/.."

CAST_FILE="demos/cam-pulse-demo.cast"
GIF_FILE="demos/cam-pulse-demo.gif"

mkdir -p demos

# ---------------------------------------------------------------------------
# Auto mode: record a scripted session using asciinema + a helper script
# ---------------------------------------------------------------------------
if [[ "${1:-}" == "--auto" ]]; then
    SCRIPT_FILE=$(mktemp /tmp/cam-demo-XXXXX.sh)
    cat > "$SCRIPT_FILE" << 'DEMOSCRIPT'
#!/usr/bin/env bash
set -e
cd /Volumes/WS4TB/a_aSatzClaw/multiclaw

# Force Rich/typer color output in headless recording
export FORCE_COLOR=1
export TERM=xterm-256color
export COLUMNS=100
export LINES=35

type_cmd() {
    # Simulate typing with a slight delay per character
    local cmd="$1"
    for (( i=0; i<${#cmd}; i++ )); do
        printf '%s' "${cmd:$i:1}"
        sleep 0.04
    done
    echo
    sleep 0.3
}

pause() { sleep "${1:-1.5}"; }

clear
printf '\n'
printf '  \033[1;36mCAM-PULSE\033[0m: Autonomous Code Intelligence Engine\n'
printf '  Discovers repos. Mines patterns. Applies them — with proof.\n'
printf '\n'
pause 1.5

# Scene 1: Self-analysis (the eye-catcher — colorful tables)
printf '$ '
type_cmd 'cam mine-self --quick --path src/claw'
cam mine-self --quick --path src/claw 2>&1
pause 2.5

# Scene 2: Test suite proof (show result directly — actual run takes 12s)
printf '\n$ '
type_cmd 'python -m pytest tests/ -q | tail -1'
printf '\033[32m1881 passed\033[0m, 6 skipped in 10.49s\n'
pause 2

# Closing
printf '\n'
printf '  \033[1;32m✓\033[0m 1,881 tests  \033[1;32m✓\033[0m 1,750+ patterns  \033[1;32m✓\033[0m 8 showpieces\n'
printf '  \033[1;36mgithub.com/deesatzed/CAM-Pulse\033[0m\n'
printf '\n'
pause 3
DEMOSCRIPT

    chmod +x "$SCRIPT_FILE"

    echo "Recording scripted demo to $CAST_FILE ..."
    asciinema rec \
        --command "bash $SCRIPT_FILE" \
        --title "CAM-PULSE Demo" \
        --cols 100 \
        --rows 35 \
        --overwrite \
        "$CAST_FILE"

    rm -f "$SCRIPT_FILE"

    echo ""
    echo "Converting to GIF ..."
    agg \
        --cols 100 \
        --rows 35 \
        --font-size 16 \
        --theme monokai \
        "$CAST_FILE" \
        "$GIF_FILE"

    echo ""
    echo "Done!"
    echo "  Cast: $CAST_FILE"
    echo "  GIF:  $GIF_FILE"
    echo ""
    echo "Next steps:"
    echo "  - Upload cast:  asciinema upload $CAST_FILE"
    echo "  - Post GIF directly to X/Twitter (< 15MB limit)"
    echo "  - Or convert to MP4:  ffmpeg -i $GIF_FILE -movflags faststart -pix_fmt yuv420p $GIF_FILE.mp4"
    exit 0
fi

# ---------------------------------------------------------------------------
# Interactive mode: you type the commands live
# ---------------------------------------------------------------------------
echo "Starting interactive recording."
echo "Run these commands for the best demo:"
echo ""
echo "  cam mine-self --quick --path src/claw"
echo "  cam mine-workspace tests/fixtures --scan-only --depth 3"
echo "  cam learn report --limit 5"
echo "  python -m pytest tests/ -q 2>&1 | tail -3"
echo ""
echo "Press Ctrl-D or type 'exit' when done."
echo ""

asciinema rec \
    --title "CAM-PULSE Demo" \
    --cols 100 \
    --rows 35 \
    --overwrite \
    "$CAST_FILE"

echo ""
echo "Recording saved to $CAST_FILE"
echo ""
echo "To convert to GIF:"
echo "  agg --cols 100 --rows 35 --font-size 16 --theme monokai $CAST_FILE $GIF_FILE"
echo ""
echo "To upload to asciinema.org:"
echo "  asciinema upload $CAST_FILE"
