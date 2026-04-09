# Troubleshooting Guide

**Audience**: CAM operators encountering errors or unexpected behavior.

---

## Installation and Environment

### "ModuleNotFoundError: No module named 'claw'"

**Cause**: PYTHONPATH not set or wrong virtual environment active.

**Fix**:
```bash
cd /path/to/multiclaw
PYTHONPATH=src .venv/bin/python -m claw.cli --help
```

### "No module named 'google.genai'"

**Cause**: The `google-genai` package is not installed. Required for Gemini embeddings.

**Fix**:
```bash
.venv/bin/pip install google-genai
```

### Python environment gets SIGKILL (exit 137)

**Cause**: Binary incompatibility with certain conda environments on Apple Silicon.

**Fix**: Use the `mlx13` environment if available:
```bash
/Users/o2satz/miniforge3/envs/mlx13/bin/python -m claw.cli --help
```

Or create a clean venv:
```bash
python3 -m venv .venv
.venv/bin/pip install -e .
```

### "pip install -e . fails" with build errors

**Cause**: Missing system dependencies or outdated pip.

**Fix**:
```bash
.venv/bin/pip install --upgrade pip setuptools wheel
.venv/bin/pip install -e .
```

---

## API Keys

### "OPENROUTER_API_KEY not set"

**Fix**: Create a `.env` file in the project root:
```bash
OPENROUTER_API_KEY=sk-or-your-key-here
GOOGLE_API_KEY=AIza-your-key-here
```

### "Unauthorized" from OpenRouter

**Cause**: Invalid or expired API key, or insufficient credits.

**Fix**: Verify your key at https://openrouter.ai/keys and check your credit balance.

### "Gemini embedding failed" or "google.genai error"

**Cause**: Invalid `GOOGLE_API_KEY` or the Gemini API is temporarily unavailable.

**Fix**: Verify your key at https://aistudio.google.com/apikey. Run:
```bash
.venv/bin/cam doctor environment
```

---

## Mining

### "0 repos found" when mining

**Cause**: Directory does not contain git repositories, or all repos were already mined (skip-unchanged is enabled by default).

**Fix**: Use `--force` to rescan previously mined repos:
```bash
.venv/bin/cam mine /path/to/repos --force
```

### "Repaired malformed JSON from LLM"

**Cause**: The LLM returned invalid JSON in its response. The miner auto-repairs this.

**Fix**: No action needed. This is a non-fatal warning. The miner handles malformed JSON automatically.

### Mining is slow (>60s per repo)

**Cause**: Large repos with many files, or the LLM is processing a complex codebase.

**Fix**: Limit scope:
```bash
.venv/bin/cam mine /path/to/repos --max-repos 5 --depth 3
```

### "Failed to parse capability JSON" during assimilation

**Cause**: The LLM returned malformed JSON during capability enrichment. The methodology is still stored, just without full capability_data.

**Fix**: No action needed. This is a non-fatal warning. Novelty and potential scores may still be computed for the methodology.

---

## CAG (Cache-Augmented Generation)

### "CAG corpus empty"

**Cause**: Cache was never built, or there are no methodologies in the knowledge base.

**Fix**:
```bash
.venv/bin/cam mine /path/to/repos    # Populate KB first
.venv/bin/cam cag rebuild             # Then build the cache
```

### "stale: true" persists after rebuild

**Cause**: Another process (mining, governance) mutated methodologies after the last rebuild.

**Fix**: Wait for the mutation process to complete, then rebuild again:
```bash
.venv/bin/cam cag rebuild
```

### CAG not injected into prompts

**Cause**: Either the task type is not in the eligible list, or `[cag] enabled = false`.

**Eligible task types**: mining_extraction, bulk_classification, pattern_extraction, code_summarization, mining, novelty_detection, synergy_discovery.

### "knowledge_budget_chars too small"

**Cause**: The budget truncates the corpus to fewer methodologies than needed.

**Fix**: Increase the budget in `claw.toml`:
```toml
[cag]
knowledge_budget_chars = 32000    # Increase from default 16000
```

> **Note (2026-04-09)**: A paired A/B experiment (26 pairs, p=1.000) showed **no significant difference** between 24K and 32K chars. The default 16K is the tested sweet spot. Increasing beyond it is unlikely to improve quality and may slightly hurt Token Economy. See `scripts/run_ab_knowledge_budget.py`.

---

## Local LLM

### "Connection refused on port 11434"

**Cause**: Ollama is not running.

**Fix**:
```bash
ollama serve
```

### "Model not found"

**Cause**: The model has not been downloaded.

**Fix**:
```bash
ollama pull qwen2.5:7b
```

### "rope.dimension_sections has wrong array length; expected 4, got 3"

**Cause**: The TurboQuant fork (TheTom/llama-cpp-turboquant, build 8670) does not support `qwen3.5` (qwen35 architecture).

**Fix**: Use `qwen2.5` (qwen2 architecture) with TurboQuant. Ollama supports both architectures.

### First request is very slow, subsequent ones are fast

**Cause**: Normal behavior. The first request builds the KV cache from scratch (cold start). Subsequent requests reuse the cached prefix.

**Fix**: No fix needed. Ensure `keep_alive = -1` in config to prevent cache eviction between requests.

### "Out of memory" during inference

**Cause**: Model weights + KV cache exceed available RAM.

**Fix** (pick one):
- Reduce `ctx_size` in `claw.toml` (e.g., 16384 instead of 32768)
- Switch to turbo3 or turbo4 KV compression (4.9x or 6x memory reduction)
- Use a smaller model

### Local agent never gets selected by Kelly routing

**Cause**: The `local_quality_multiplier` (default 0.7) discounts local agent quality.

**Fix**: Increase the multiplier if your local model is competitive:
```toml
[kelly]
local_quality_multiplier = 0.9
```

---

## Governance and Memory

### "max_methodologies exceeded"

**Cause**: The knowledge base has more methodologies than the governance quota allows.

**Fix**: The governance sweep will auto-cull lowest-fitness methodologies. Or increase the quota:
```toml
[governance]
max_methodologies = 10000
```

### Methodologies stuck in "embryonic" state

**Cause**: Not enough task completions to advance the methodology's lifecycle.

**Fix**: Normal behavior. Methodologies advance from embryonic to viable to thriving as they accumulate successful usage. Run more tasks that use these methodologies.

### Governance sweep removing too many methodologies

**Cause**: Quota is too low or many methodologies have low fitness.

**Fix**: Increase the quota or review the fitness landscape:
```bash
.venv/bin/cam kb insights
```

---

## Budget

### "Budget exceeded" pausing tasks

**Cause**: API spend hit one of the 4 caps (per-task, per-project, per-day, per-agent).

**Fix**: Increase the relevant cap in `claw.toml`:
```toml
[budget]
per_task_usd = 10.0
per_day_usd = 200.0
```

---

## Tests

### Running the full test suite

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/ -q
```

### Pre-existing test failures

Known pre-existing issues that do not affect core functionality:
- `tests/test_doctor_routing.py` — untracked file with stale import (safe to delete)
- Environment-specific failures with `google.genai` or `python3` subprocess

---

## Database

### "Database is locked"

**Cause**: Another CAM process is holding the SQLite lock.

**Fix**: Wait for the other process to finish, or check for stale processes:
```bash
ps aux | grep claw
```

### "Schema migration failed"

**Cause**: Database file is corrupted or from an incompatible version.

**Fix**: Back up the database, then let CAM recreate it:
```bash
mv data/claw.db data/claw.db.backup
.venv/bin/cam doctor environment    # Recreates the database
```

---

## Getting Help

1. Check this troubleshooting guide
2. Run diagnostics: `.venv/bin/cam doctor environment`
3. Check terminal output (CAM uses structured logging with timestamps)
4. Open an issue: https://github.com/deesatzed/CAM-Pulse/issues
