# CAM Showpiece: Book-to-Screenplay Converter

**CAM builds creative tools, not just code utilities.**

This showpiece proves that CAM's PULSE knowledge pipeline can learn from screenplay-format repos and use that knowledge to build a working novel-to-screenplay converter that produces valid Fountain format with LLM-powered dialogue attribution.

## What This Proves

**Criticism answered:** "CAM only works for typical dev tools — it can't handle creative or domain-specific tasks."

**Proof:**

1. PULSE mines 2 open-source screenplay repos → learns Fountain spec, parser architecture, dialogue handling
2. CAM builds a complete Python CLI converter using that knowledge
3. The converter transforms real novel prose (WWII literary fiction) into valid Fountain-format screenplays
4. LLM-powered dialogue attribution via OpenRouter correctly identifies speakers in complex literary prose
5. Three style presets produce measurably different output density
6. 13 tests pass covering parser, formatter, CLI, styles, and acceptance

## Prerequisites

- **OpenRouter API key** (`OPENROUTER_API_KEY`) — required for LLM-powered dialogue attribution
- CAM installed and configured
- Python 3.12+ with `uv`

Set your API key:
```bash
export OPENROUTER_API_KEY="sk-or-v1-your-key-here"
# Or add to .env file in the project root
```

## Knowledge Sources

| Pattern | Source Repo | Methodology |
|---------|------------|-------------|
| Two-phase parser with pending decisions | wildwinter/screenplay-tools | State-first pass to identify element types, then merge pass for dialogue blocks |
| Incremental dialogue/action merging | wildwinter/screenplay-tools | Interleave action and dialogue in scene element order |
| Spec-aware writer preserves formatting | wildwinter/screenplay-tools | Fountain format compliance: scene headings, character cues, transitions |
| Inline comment and note preservation | wildwinter/screenplay-tools | Handle attribution text adjacent to dialogue |
| State-machine parser with rewind | ludovicchabant/Jouvence | Paragraph-level parsing with speculative lookahead |
| Dynamic paragraph dispatch via lazy adders | ludovicchabant/Jouvence | Route prose paragraphs to correct element type by content analysis |
| YAML-driven script corpus as executable parser tests | ludovicchabant/Jouvence | Test-driven development for screenplay parsing |
| Renderer strategy split | ludovicchabant/Jouvence | Separate structure parsing from format rendering |

## The Task

```
Build a Python CLI tool that converts novel prose chapters into
Fountain-format screenplays. Parse plain-text chapter files, detecting
scene breaks. Identify dialogue by recognizing quoted speech patterns
and attributing it to characters via LLM analysis through OpenRouter.
Convert prose narration into screenplay ACTION lines. Generate proper
Fountain format output with scene headings (INT./EXT.), CHARACTER cues
in caps, dialogue blocks, and transitions. Support three style presets:
faithful, cinematic, minimalist.
```

**Knowledge activation:** The request targets mined patterns — "parse" triggers the state-machine parser, "dialogue" triggers dialogue/action merging, "Fountain format" triggers the spec-aware writer, "style presets" triggers the renderer strategy split.

## How It Works

```
Novel chapter (.txt)         Style preset       OpenRouter API
       │                          │                   │
       ▼                          │                   │
┌─────────────────┐               │                   │
│  Scene Splitter  │  Split on --- markers             │
└────────┬────────┘               │                   │
         ▼                        │                   │
┌─────────────────┐               │                   │
│  Quote Extractor │  Regex: "..." with rule-based     │
│  + Rule-Based    │  "said X" / context / alternation │
│    Attribution   │                                   │
└────────┬────────┘                                    │
         ▼                                             ▼
┌──────────────────────────────────────────────────────────┐
│  LLM Attribution Overlay (OpenRouter)                     │
│  Sends each scene's prose to LLM for accurate speaker     │
│  identification. Overrides rule-based where LLM is        │
│  confident. Falls back to rule-based if API unavailable.  │
└────────┬─────────────────────────────────────────────────┘
         ▼                        │
┌─────────────────┐               │
│ Scene Builder    │  Interleave ActionBlock + DialogueBlock
│                  │  Infer INT./EXT. headings from content
└────────┬────────┘               │
         ▼                        ▼
┌─────────────────────────────────────┐
│  Fountain Formatter                  │
│  faithful: full prose as action      │
│  cinematic: trim long narration      │
│  minimalist: condense + uppercase    │
└────────────────┬────────────────────┘
                 ▼
         .fountain file
```

## Expected Output

```
book-to-screenplay/
├── app/
│   ├── __init__.py
│   ├── cli.py              # typer CLI: convert <file> --style <preset> --output <file>
│   ├── formatter.py        # Fountain format output with style presets
│   ├── llm_attribution.py  # LLM-powered dialogue attribution via OpenRouter
│   ├── models.py           # Scene, ActionBlock, DialogueBlock, StylePreset
│   └── parser.py           # Quote extraction, attribution, scene splitting
├── input/
│   ├── chapter_01.txt      # "Academy Street" — 2,930 words, 6 scenes
│   ├── chapter_02.txt      # "What the Scholarship Was For" — 2,120 words, 5 scenes
│   ├── chapter_03.txt      # "The Name" — 2,901 words, 8 scenes
│   ├── characters_ch1_3.txt  # Character profiles from autonovel
│   └── beats_ch1_3.txt       # Scene beats from autonovel
├── output/
│   ├── ch01_faithful.fountain
│   ├── ch01_cinematic.fountain
│   ├── ch01_minimalist.fountain
│   ├── ch02_faithful.fountain
│   ├── ch02_cinematic.fountain
│   ├── ch02_minimalist.fountain
│   ├── ch03_faithful.fountain
│   ├── ch03_cinematic.fountain
│   └── ch03_minimalist.fountain
├── tests/
│   ├── test_acceptance.py  # End-to-end CLI tests with real chapter input
│   ├── test_cli.py         # Help, version, error handling
│   ├── test_formatter.py   # Fountain structure, interleaved order, multi-scene
│   ├── test_parser.py      # Scene breaks, dialogue attribution
│   └── test_styles.py      # Style preset variation, minimalist condensation
├── pyproject.toml
└── README.md
```

## Run It

### Prerequisites

- **OpenRouter API key** — set `OPENROUTER_API_KEY` in your environment or `.env` file
- Python 3.12+ with `uv`
- CAM installed (for knowledge mining step)

### Quick Run

```bash
# Set your OpenRouter API key
export OPENROUTER_API_KEY="sk-or-v1-your-key-here"

# Mine screenplay knowledge (if not already done)
cam pulse ingest https://github.com/wildwinter/screenplay-tools --force
cam pulse ingest https://github.com/ludovicchabant/Jouvence --force

# Run the converter (LLM attribution enabled by default)
cd /Volumes/WS4TB/a_aSatzClaw/book-to-screenplay
uv run book-to-screenplay convert input/chapter_01.txt --style faithful --output output/ch01_faithful.fountain
uv run book-to-screenplay convert input/chapter_01.txt --style minimalist --output output/ch01_minimalist.fountain

# Run without LLM (rule-based only, no API key needed)
uv run book-to-screenplay convert input/chapter_01.txt --style faithful --no-llm --output output/ch01_rulebased.fountain

# Override the LLM model
uv run book-to-screenplay convert input/chapter_01.txt --style faithful --model "openai/gpt-5.4-mini" --output output/ch01_faithful.fountain

# Run tests
uv run pytest -v
```

### Full Harness

```bash
cd /Volumes/WS4TB/a_aSatzClaw/multiclaw
bash scripts/test_book_screenplay_showpiece.sh
```

## Verification Steps

| Step | What | Pass Criteria |
|------|------|--------------|
| API Key | `OPENROUTER_API_KEY` is set | Required for LLM attribution |
| KB Check | `cam kb search "screenplay parser"` | Returns results from wildwinter/Jouvence |
| Structure | Check app/, tests/, pyproject.toml | All present |
| Tests | `uv run pytest -v` | 13/13 pass |
| Input | Check chapter files exist | 3 chapters, 7,951 words total |
| Conversion | Generate 9 Fountain files | All 9 created, no LLM errors |
| Scene Headings | grep for INT./EXT. | At least 6 per chapter |
| Character Cues | grep for all-caps names | ABRAHAM, NORMAN, MRS. BISHUSKY detected |
| Transitions | grep for CUT TO: | At least 4 per chapter |
| Style Variation | Compare word counts | faithful > cinematic > minimalist |

## What No Other Tool Does

1. **Mines screenplay repos first** — CAM doesn't just write code; it learns from existing screenplay parsers before building one
2. **Knowledge-injected creative output** — The agent prompt includes retrieved patterns from wildwinter/screenplay-tools and Jouvence
3. **LLM-powered dialogue attribution** — Uses OpenRouter to accurately identify speakers in complex literary prose with sparse speech tags
4. **Domain transfer** — Patterns learned from code repos (parser architecture, state machines, renderers) applied to a creative writing task
5. **Full provenance chain** — Every methodology has its source repo URL and discovery date
6. **Real literary input** — Not lorem ipsum; processes a 7,951-word three-chapter WWII novel with complex prose
7. **Graceful degradation** — LLM attribution is primary, with rule-based fallback if API is unavailable

## Proven Results (Live Run 2026-03-24)

**Task ID:** c491c134-cc19-4990-ba65-52dcb26deaeb

**Metrics:**
- Methodologies mined: 8 (4 from screenplay-tools, 4 from Jouvence)
- Files produced: 16 (parser, formatter, models, CLI, LLM attribution, 5 test files, config)
- Tests: 13 passing
- Chapters converted: 3 (7,951 words → 9 Fountain files)
- LLM model: `openai/gpt-5.4-mini` via OpenRouter
- Style reduction: faithful=2,991 words → minimalist=1,923 words (36% reduction)
- Characters detected: ABRAHAM (34 cues), NORMAN (25 cues), MRS. BISHUSKY (4 cues) in Chapter 1
- Scene headings: 6 per chapter (correct)

**Code produced:**

| File | Lines | Purpose |
|------|-------|---------|
| app/parser.py | 336 | Scene splitting, quote extraction, bidirectional rule-based attribution, LLM overlay integration |
| app/llm_attribution.py | 159 | LLM-powered dialogue attribution via OpenRouter (sends prose to LLM, parses speaker assignments) |
| app/formatter.py | 71 | Fountain format output with faithful/cinematic/minimalist presets |
| app/cli.py | 56 | typer CLI with convert command, --model and --no-llm flags |
| app/models.py | 36 | Scene, ActionBlock, DialogueBlock, SceneElement union type |
| tests/test_acceptance.py | 58 | End-to-end tests including real chapter conversion |
| tests/test_parser.py | 14 | Scene break detection and attribution |
| tests/test_formatter.py | 52 | Fountain structure, interleaved order, multi-scene |
| tests/test_styles.py | 37 | Style preset variation |
| tests/test_cli.py | 22 | CLI help, version, error handling |

**Dialogue Attribution: Rule-Based vs LLM**

| Metric | Rule-Based Only | LLM-Powered (OpenRouter) |
|--------|----------------|--------------------------|
| Correctly attributed (Ch1) | ~60% | ~90%+ |
| Characters detected | 1 (ABRAHAM only) | 3 (ABRAHAM, NORMAN, MRS. BISHUSKY) |
| Rapid-fire dialogue handling | Alternation heuristic | Full context understanding |
| "In a minute" speaker | ABRAHAM (wrong) | NORMAN (correct) |
| "He's studying" speaker | ABRAHAM (wrong) | MRS. BISHUSKY (correct) |

**Honest Limitations:**

- Scene heading inference is heuristic (keyword-based) — may not always match the exact setting
- LLM attribution depends on OpenRouter API availability and the selected model's quality
- The converter does not yet use the character profiles or scene beats as supplementary input (future enhancement)
- Currently processes one chapter at a time (no batch processing)
