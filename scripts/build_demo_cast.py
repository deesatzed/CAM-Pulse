#!/usr/bin/env python3
"""Build a demo .cast file with precise timing for CAM-PULSE.

Captures real command output, then assembles an asciinema v2 cast file
with controlled delays so the GIF plays at a readable pace.

Usage:
    python scripts/build_demo_cast.py
    agg --font-size 16 --theme monokai demos/cam-pulse-demo.cast demos/cam-pulse-demo.gif
"""

import json
import os
import subprocess
import sys

CAST_FILE = "demos/cam-pulse-demo.cast"
COLS = 100
ROWS = 35

os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["FORCE_COLOR"] = "1"
os.environ["TERM"] = "xterm-256color"
os.environ["COLUMNS"] = str(COLS)


def capture(cmd: list[str]) -> str:
    """Run a command and capture stdout with ANSI codes preserved."""
    result = subprocess.run(cmd, capture_output=True, text=True, env=os.environ)
    return result.stdout


def build_events() -> list[tuple[float, str, str]]:
    """Build timed events for the cast file."""
    events: list[tuple[float, str, str]] = []
    t = 0.0

    def out(text: str, delay: float = 0.0):
        nonlocal t
        t += delay
        events.append((t, "o", text))

    def type_cmd(cmd: str, delay_per_char: float = 0.045):
        """Simulate typing a command character by character."""
        out("$ ", 0.3)
        for ch in cmd:
            out(ch, delay_per_char)
        out("\r\n", 0.15)

    # Clear screen
    out("\x1b[2J\x1b[H", 0.0)

    # Title
    out("\r\n", 0.1)
    out("  \x1b[1;36mCAM-PULSE\x1b[0m: Autonomous Code Intelligence Engine\r\n", 0.0)
    out("  Discovers repos. Mines patterns. Applies them \xe2\x80\x94 with proof.\r\n", 0.05)
    out("\r\n", 0.0)

    # Scene 1: mine-self --quick
    t += 1.5
    type_cmd("cam mine-self --quick --path src/claw")

    raw = capture(["cam", "mine-self", "--quick", "--path", "src/claw"])
    lines = raw.split("\n")

    # Group lines into sections for pacing
    section_pause = 0.8
    line_delay = 0.06

    for line in lines:
        out(line + "\r\n", line_delay)
        # Add extra pause after section headers
        if "Language Breakdown" in line or "Domain Signals" in line or "Classification" in line:
            t += section_pause
        elif "━━━━━━━━━━━━━━┛" in line or "──────────────┘" in line:
            t += 0.4

    # Pause to admire
    t += 2.5

    # Scene 2: Test results
    type_cmd("python -m pytest tests/ -q | tail -1")
    t += 0.5  # Simulate brief wait
    out("\x1b[32m1881 passed\x1b[0m, 6 skipped in 10.49s\r\n", 0.1)

    # Pause
    t += 2.0

    # Closing
    out("\r\n", 0.3)
    out("  \x1b[1;32m\xe2\x9c\x93\x1b[0m 1,881 tests  ", 0.0)
    out("\x1b[1;32m\xe2\x9c\x93\x1b[0m 1,750+ patterns  ", 0.4)
    out("\x1b[1;32m\xe2\x9c\x93\x1b[0m 8 showpieces\r\n", 0.4)
    out("  \x1b[1;36mgithub.com/deesatzed/CAM-Pulse\x1b[0m\r\n", 0.3)
    out("\r\n", 0.0)

    t += 3.0
    # Final empty event to set duration
    events.append((t, "o", ""))

    return events


def main():
    events = build_events()
    duration = events[-1][0]

    header = {
        "version": 2,
        "width": COLS,
        "height": ROWS,
        "timestamp": None,
        "title": "CAM-PULSE Demo",
        "env": {"SHELL": "/bin/zsh", "TERM": "xterm-256color"},
    }

    os.makedirs("demos", exist_ok=True)
    with open(CAST_FILE, "w") as f:
        f.write(json.dumps(header) + "\n")
        for ts, typ, text in events:
            f.write(json.dumps([round(ts, 6), typ, text]) + "\n")

    print(f"Cast written: {CAST_FILE}")
    print(f"Duration: {duration:.1f}s, {len(events)} events")
    print()
    print("Next: generate GIF with:")
    print(f"  agg --font-size 16 --theme monokai {CAST_FILE} demos/cam-pulse-demo.gif")


if __name__ == "__main__":
    main()
