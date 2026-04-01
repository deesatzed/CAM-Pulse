# `cam camify` Command — Implementation Plan

**Created**: 2026-04-01
**Status**: DESIGN COMPLETE — awaiting approval
**Confidence**: High — all patterns have existing precedent in the codebase

---

## What This Is

A new `cam camify` command that automates the manual workflow we performed to CAM-ify imbora:

1. **DISCOVER** — Read target repo's README, CLAUDE.md, spec files, domain guides
2. **MATCH** — Cross-reference with CAM's 2,895+ learned methodologies
3. **PLAN** — Generate executable step-by-step plan with concrete `cam` commands
4. **SAVE** — Write plan as actionable markdown + YAML frontmatter (machine-parseable)
5. **EXECUTE** (opt-in) — Run the plan step-by-step with validation gates

**Core principle**: This command is an **orchestrator** — it calls existing CAM engines (mine, enhance, preflight, KB search), not new ones.

---

## CLI Interface

```python
@app.command()
def camify(
    repo: str = typer.Argument(..., help="Path to the target repository"),
    goal: list[str] = typer.Option([], "--goal", "-g", help="Enhancement goal (repeatable)"),
    guide: list[str] = typer.Option([], "--guide", help="Path to domain guide .md file (repeatable, auto-detected if omitted)"),
    execute: bool = typer.Option(False, "--execute", help="Execute the plan after generation"),
    mode: str = typer.Option("attended", "--mode", "-m", help="attended | supervised | autonomous"),
    skip_mine: bool = typer.Option(False, "--skip-mine", help="Skip mining, use existing KB only"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Plan output path"),
    max_minutes: int = typer.Option(30, "--max-minutes", help="Wall-clock cap"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    config: Optional[str] = typer.Option(None, "--config", "-c"),
) -> None:
```

### Usage Examples

```bash
# Basic: analyze repo and generate plan
cam camify /path/to/target-repo

# With explicit goals
cam camify /path/to/repo --goal "enhance error handling" --goal "learn patterns for CAM KB"

# With domain guide file
cam camify /path/to/repo --guide /path/to/repo/AI_Augment.md

# Generate and execute
cam camify /path/to/repo --goal "enhance it" --execute --mode attended

# Skip mining (KB already has relevant knowledge)
cam camify /path/to/repo --skip-mine --goal "apply retry patterns"
```

---

## Architecture

### Execution Flow

```
cam camify /path/to/repo --goal "enhance" --goal "learn"
  │
  ▼
[1. DISCOVER] ─── _analyze_repo() + serialize_repo() + detect guides
  │                Returns: RepoProfile (metadata, domain, stack, gaps, guide content)
  │
  ▼
[2. MATCH] ────── HybridSearch against KB + identify gaps + govern stats
  │                Returns: MatchReport (matched methods, gap areas, mining targets)
  │
  ▼
[3. PLAN] ─────── Generate step-by-step plan with cam commands
  │                Each step: command + purpose + verification + failure fallback
  │                Returns: CamifyPlan (Pydantic model) + CAMIFY_PLAN.md
  │
  ▼
[4. INTERACT] ─── If no --goal provided: ask user (like cam chat)
  │                Multi-goal: "Add another goal? (y/n)"
  │                Prong pattern: allow goals to be added incrementally
  │
  ▼
[5. SAVE] ─────── Write plan to data/camify/ or --output path
  │                Format: Markdown with YAML frontmatter (dual human+machine)
  │
  ▼
[6. EXECUTE] ──── (opt-in via --execute)
                   Run plan steps sequentially via Python API
                   Each step: run → verify → continue or halt
```

### Integration with Existing Commands

Camify calls these internally — it does NOT re-implement them:

| Phase | Existing Code Reused | Module |
|---|---|---|
| Discovery | `_analyze_repo()`, `serialize_repo()` | `cli/_monolith.py`, `miner.py` |
| KB stats | `MemoryGovernor.get_storage_stats()` | `memory/governance.py` |
| KB match | `HybridSearch.search()`, `find_similar_with_signals()` | `memory/hybrid_search.py`, `memory/semantic.py` |
| Mining | `RepoMiner.mine_directory()` | `miner.py` |
| Evaluate | `Evaluator.run_battery()` | `evaluator.py` |
| Enhance | `MesoClaw`/`MicroClaw` cycle | `orchestration/cycle.py` |
| Context | `ClawFactory.create()` | `core/factory.py` |
| Interactive | `_chat_prompt()`, `_chat_confirm()` | `cli/_monolith.py` |

### Multi-Goal Handling

Each goal maps to a pipeline variant in the generated plan:

| Goal Phrase | Pipeline Steps Added |
|---|---|
| "enhance the repo" | mine → evaluate → enhance |
| "learn from it for CAM KB" | mine with `--target` pointing to CAM |
| "create a new app inspired by it" | mine → ideate → create |
| "audit the repo" | evaluate only (no enhance) |
| "apply specific patterns" | skip-mine → enhance with KB filter |

If `--goal` is not provided:
- TTY mode: interactive prompt (ask goals, allow "add another")
- Non-TTY mode: default to "enhance the repo"

---

## File Changes

### New File: `src/claw/camify.py`

All core logic lives here (testable, not coupled to CLI):

```python
class RepoProfile(BaseModel):
    """Fingerprint of the target repository."""
    name: str
    path: Path
    has_readme: bool
    has_claude_md: bool
    has_spec: bool
    guide_files: list[Path]           # Auto-detected .md guides
    guide_content: dict[str, str]     # filename → content
    domain_keywords: list[str]        # Extracted from guides + README
    tech_stack: list[str]             # Detected languages/frameworks
    file_count: int
    repo_summary: str                 # Serialized content excerpt

class MatchReport(BaseModel):
    """KB cross-reference results."""
    matched_methodologies: list[dict]  # Top-N matches with scores
    gap_areas: list[str]              # Domains target needs but KB lacks
    kb_methodology_count: int
    recommended_mining_targets: list[str]  # URLs/repos to mine first if gaps

class CamifyStep(BaseModel):
    """Single step in the generated plan."""
    id: str
    phase: str                        # preflight | mine | match | evaluate | enhance | post
    command: str                      # Concrete cam CLI command
    purpose: str                      # Why this step exists
    verification: str                 # How to check it worked
    required: bool = True             # Halt on failure if True
    fallback: Optional[str] = None    # What to do if step fails

class CamifyPlan(BaseModel):
    """The full plan artifact."""
    version: int = 1
    target_repo: str
    goals: list[str]
    guide_files_used: list[str]
    kb_matches_found: int
    kb_gaps: list[str]
    steps: list[CamifyStep]
    created_at: str
    status: str = "PENDING"

class CamifyDiscovery:
    """Fingerprints the target repo."""
    async def discover(self, repo_path: Path, guide_paths: list[Path] = []) -> RepoProfile: ...

class CamifyMatcher:
    """Cross-references repo profile with CAM KB."""
    async def match(self, profile: RepoProfile, ctx: ClawContext) -> MatchReport: ...

class CamifyPlanner:
    """Generates executable plan from profile + matches + goals."""
    def plan(self, profile: RepoProfile, matches: MatchReport, goals: list[str]) -> CamifyPlan: ...
    def render_markdown(self, plan: CamifyPlan) -> str: ...

class CamifyExecutor:
    """Runs plan steps sequentially (behind --execute)."""
    async def execute(self, plan: CamifyPlan, ctx: ClawContext, mode: str) -> None: ...
```

### Modified: `src/claw/cli/_monolith.py`

Thin wrapper (~50 lines):

```python
@app.command()
def camify(repo, goal, guide, execute, mode, skip_mine, output, max_minutes, verbose, config):
    """Analyze a repository, match with CAM's KB, and generate an executable enhancement plan."""
    _setup_logging(verbose)
    repo_path = Path(repo).resolve()
    if not repo_path.exists():
        _error_exit(f"Repository not found: {repo_path}")
    asyncio.run(_camify_async(repo_path, goal, guide, execute, mode, skip_mine, output, max_minutes, config))

async def _camify_async(...):
    ctx = await ClawFactory.create(config_path=..., workspace_dir=repo_path)
    try:
        discovery = CamifyDiscovery()
        profile = await discovery.discover(repo_path, guide_paths=[Path(g) for g in guide])

        # Interactive goal collection if no --goal provided
        if not goals and sys.stdin.isatty():
            goals = _camify_interactive_goals(profile)
        if not goals:
            goals = ["enhance the repo"]

        matcher = CamifyMatcher()
        matches = await matcher.match(profile, ctx)

        planner = CamifyPlanner()
        plan = planner.plan(profile, matches, goals)
        markdown = planner.render_markdown(plan)

        # Save
        out_path = _write_camify_artifact(plan, markdown, output)
        console.print(f"Plan saved to: {out_path}")

        if execute:
            executor = CamifyExecutor()
            await executor.execute(plan, ctx, mode)
    finally:
        await ctx.close()
```

### Modified: `src/claw/cli/__init__.py`

Add `camify` and `_camify_async` to re-exports.

### New Directory: `data/camify/`

Plan artifacts stored here with naming: `{timestamp}-{repo_slug}-camify-plan.md`

---

## Plan Artifact Format

The output file is dual-format — human-readable markdown with YAML frontmatter that machines can parse:

```markdown
---
camify_version: 1
target_repo: /Volumes/WS4TB/imb-CAM/imbora
goals:
  - "enhance error handling and retry logic"
  - "learn from repo for CAM KB"
guide_files:
  - AI_Augment.md
kb_matches_found: 12
kb_gaps:
  - "tabular GAN generation"
  - "diffusion models for tabular data"
created_at: "2026-04-01T14:30:00Z"
status: PENDING
---

# CAM-ify Plan: imbora

## Goals
1. Enhance error handling and retry logic
2. Learn from repo for CAM KB

## KB Match Summary
- 12 relevant methodologies found across 4 domains
- Gap: tabular GAN generation (recommend mining CTGAN repos first)

## Step 1: Pre-flight
**Command**: `cam doctor environment`
**Purpose**: Verify CAM installation, API keys, DB health
**Verify**: Exit code 0, all checks green

## Step 2: Mine target repo
**Command**: `cam mine /path/to/imbora --target /path/to/imbora --max-repos 1 --depth 5`
**Purpose**: Let CAM study imbora's domain, patterns, and gaps
**Verify**: `cam govern stats` shows increased methodology count

...
```

---

## Discovery Engine: Guide File Detection

Auto-detects guide files in the target repo using name patterns:

```python
GUIDE_PATTERNS = [
    "AI_*.md", "*augment*.md", "*enhance*.md", "*roadmap*.md",
    "*upgrade*.md", "*improve*.md", "*TODO*.md", "*backlog*.md",
    "CLAUDE.md", "spec.json", "spec.yaml",
]
```

Scans repo root and `docs/` directory. User can override with `--guide /path/to/file.md`.

---

## Test Plan Summary

8 test files, ~80 test functions:

| Test File | Coverage Target | What It Tests |
|---|---|---|
| `test_camify_discovery.py` | 95% | File detection, metadata extraction, edge cases |
| `test_camify_kb_matching.py` | 90% | KB queries, ranking, gap detection |
| `test_camify_plan_generation.py` | 90% | Plan structure, content, commands |
| `test_camify_file_writing.py` | 85% | Output persistence, naming, permissions |
| `test_camify_cli.py` | 95% | Command registration, args, exit codes |
| `test_camify_interactive.py` | 85% | Multi-goal prompts, input handling |
| `test_camify_integration.py` | 90% | End-to-end on realistic test repos |
| `test_camify_models.py` | 95% | Pydantic model validation |

All tests use real dependencies (sqlite in-memory, tmp_path). No mocks.

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Guide file false positives (every repo has .md files) | Medium | Low | Restrict to name patterns + keyword match, `--guide` override |
| Empty KB produces useless plan | Low | Medium | Detect and add "mine similar repos first" step |
| Plan execution failure cascading | Medium | High | Each step has `required` flag; halt on required failure |
| Monolith file size growth | Certain | Low | Only thin wrapper in monolith; logic in `camify.py` |
| Interactive mode conflicts with scripts | Low | Medium | TTY detection; non-TTY defaults to "enhance" |

---

## Next Actions (Priority Order)

1. **Create `src/claw/camify.py`** — Pydantic models + Discovery + Matcher + Planner classes
2. **Add CLI wrapper** to `_monolith.py` — thin `camify()` command + `_camify_async()`
3. **Write tests** — Start with discovery + plan generation (most testable without live KB)
4. **Update docs** — Add `cam camify` to `CAM_COMMAND_DECISION_TREE.md` and `CAM_IFY_REPO_GUIDE.md`
5. **Wire CamifyExecutor** — The `--execute` path that runs the plan (depends on steps 1-3)

---

## Prong 2 Connection

This plan also serves the imbora CAM-ification:
- `cam camify /Volumes/WS4TB/imb-CAM/imbora --guide AI_Augment.md` would auto-generate the plan we manually wrote in `CAM_IFY_IMBORA_PLAN.md`
- The imbora use case becomes the first real test of the feature
- Any gaps in the automated plan vs our manual plan reveal what the command still needs
