# How to Create a Standalone CAM-PULSE Instance

**Audience**: You know how to use a terminal and have Python installed. No prior CAM experience needed.

---

## What This Guide Does

You will clone CAM-PULSE, point it at its own private database, and feed it repos from one specific domain (medical AI, game dev, quantum computing — whatever you care about). At the end, you will have a standalone brain that only knows about your domain.

Think of it like this:

```
CAM-PULSE (the code)  =  a doctor's training and skills
claw.db (the database) =  the doctor's memory of every patient they've seen

Same medical school, different specialty:
  - general.db    → knows a little about everything
  - cardiac.db    → deep expertise in heart conditions
  - neuro.db      → deep expertise in brain disorders
```

You are creating a new specialist.

---

## Prerequisites

| What | Why | Check |
|------|-----|-------|
| Python 3.11+ | CAM needs it | `python3 --version` |
| Git | Clone the repo | `git --version` |
| ~2 GB disk | Code + venv + database | `df -h .` |
| OpenRouter API key | LLM calls for mining | [openrouter.ai/keys](https://openrouter.ai/keys) |
| Google API key | Embeddings for search | [aistudio.google.com/apikey](https://aistudio.google.com/apikey) |

Optional:
- `XAI_API_KEY` — only if you want X-Scout auto-discovery via Grok
- `HF_TOKEN` — only if you want to mine HuggingFace model repos
- `GITHUB_TOKEN` — only if you want freshness monitoring with higher rate limits

---

## Step 1: Clone CAM-PULSE

```bash
git clone https://github.com/deesatzed/CAM-Pulse.git
cd CAM-Pulse
```

**Check**: You should see files like `claw.toml`, `src/`, `tests/`, `README.md`.

```bash
ls claw.toml src/ tests/
```

If you see "No such file or directory", you are in the wrong folder. Run `cd CAM-Pulse`.

---

## Step 2: Create a Virtual Environment and Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

**Check**: The `cam` command should work.

```bash
cam --help
```

You should see a list of commands starting with `chat`, `evaluate`, `enhance`, etc.

**Troubleshoot**:
- `command not found: cam` → Run `source .venv/bin/activate` again. Your terminal prompt should show `(.venv)`.
- `pip install` fails → Make sure you have Python 3.11+. Run `python3 --version`.
- Errors about `sqlite-vec` → This is normal on some systems. CAM will still work; vector search falls back gracefully.

---

## Step 3: Set Up Your API Keys

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` and fill in your keys:

```bash
OPENROUTER_API_KEY=sk-or-v1-your-key-here
GOOGLE_API_KEY=AIza-your-key-here
```

**Check**: Verify keys are loaded.

```bash
cam doctor keycheck --for mine --live
```

You should see green checkmarks. If you see red X marks, double-check that your keys are correct and have credit/quota.

**Troubleshoot**:
- `OPENROUTER_API_KEY not set` → Make sure `.env` is in the same directory as `claw.toml`.
- `Google API key invalid` → Go to [aistudio.google.com/apikey](https://aistudio.google.com/apikey), create a new key, and make sure "Generative Language API" is enabled.

---

## Step 4: Verify the Default Database Works

```bash
cam govern stats
```

You should see something like:

```
Memory Governance Stats
  Total methodologies:  0
  Active (non-dead):    0
  Quota: 0/2000 (0.0%)
  DB size: 0.46 MB
```

This is a fresh brain — zero methodologies. That is correct.

**Check**: Confirm where the database lives.

```bash
ls -la data/claw.db
```

This is the default database at `data/claw.db`.

---

## Step 5: Create Your Standalone Database

Now create a separate database for your specialty. Pick a name that describes your domain.

```bash
mkdir -p data/instances
```

Tell CAM to use your new database by setting the `CLAW_DB_PATH` environment variable:

```bash
export CLAW_DB_PATH=data/instances/medical-ai.db
```

**Check**: Verify CAM sees the new path.

```bash
cam govern stats
```

You should see a fresh `0 methodologies` output again — this is a brand new brain. The database file is automatically created and initialized with all tables.

```bash
ls -la data/instances/medical-ai.db
```

**Troubleshoot**:
- `No such file or directory` for the `.db` file → Run `cam govern stats` first. CAM creates the database on first access.
- You see methodologies > 0 → You are still pointing at the old database. Check `echo $CLAW_DB_PATH`.

---

## Step 6: Feed Your Specialist Brain

Now the fun part. You have three ways to teach your specialist:

### Option A: Feed It Specific Repos (Recommended for Starting)

Pick 3-5 GitHub repos in your domain and ingest them directly:

```bash
# Example: Medical AI specialist
cam pulse ingest \
  https://github.com/explosion/spacy-bio \
  https://github.com/allenai/scispacy \
  https://github.com/dmis-lab/biobert

# Example: Game dev specialist
cam pulse ingest \
  https://github.com/bevyengine/bevy \
  https://github.com/godotengine/godot \
  https://github.com/phaserjs/phaser

# Example: Quantum computing specialist
cam pulse ingest \
  https://github.com/Qiskit/qiskit \
  https://github.com/quantumlib/Cirq \
  https://github.com/PennyLaneAI/pennylane
```

Each repo takes 30-60 seconds. You will see output like:

```
Assimilating https://github.com/explosion/spacy-bio ...
  Cloned (depth=1)
  License: MIT (permissive)
  Secret scan: CLEAN
  Mining: 3-pass pipeline
  Stored: 7 methodologies
```

**Check**: Verify your brain learned something.

```bash
cam govern stats
```

You should see `Total methodologies: N` where N > 0.

### Option B: Feed It HuggingFace Model Repos

```bash
cam pulse ingest https://huggingface.co/microsoft/phi-3-mini-4k-instruct
cam pulse ingest-hf d4data/biomedical-ner-all --revision main
```

### Option C: Let X-Scout Discover Repos Automatically

This requires an `XAI_API_KEY` in your `.env`.

```bash
cam pulse scan --keywords "medical AI clinical decision support"
```

X-Scout uses Grok to search X/Twitter for GitHub repos that developers are sharing, then mines them automatically.

**Troubleshoot**:
- `Secret scan blocked assimilation` → The repo contains hardcoded credentials. This is CAM protecting you. Pick a different repo.
- `Mining failed: timeout` → The repo is very large. Try a smaller one, or increase `[mining] timeout_seconds` in `claw.toml`.
- `0 methodologies stored` → The LLM could not extract useful patterns. This happens with very small or empty repos.

---

## Step 7: Search Your Knowledge

```bash
# See what your brain knows
cam kb insights

# Search for specific patterns
cam kb search "named entity recognition for biomedical text"

# See which domains you cover
cam kb domains
```

**Check**: `cam kb search` should return results related to the repos you ingested.

**Troubleshoot**:
- `0 results` → You may not have ingested enough repos, or your search terms do not match what was mined. Try broader terms.
- `Embedding error` → Check that `GOOGLE_API_KEY` is set in `.env`.

---

## Step 8: Generate a Brain Manifest

The manifest is a summary of what your specialist knows. Other CAM instances can read it.

```bash
cam kb instances manifest
```

**Check**: The manifest file should exist.

```bash
cat data/brain_manifest.json | python3 -m json.tool | head -20
```

You should see fields like `total_methodologies`, `top_categories`, `language_breakdown`.

---

## Step 9: Use Your Specialist for Builds

Now your specialist can help build things in its domain:

```bash
# Create a new project using your specialist's knowledge
cam create /path/to/new-project --repo-mode new \
  --request "Build a biomedical NER pipeline using spaCy" \
  --check "pytest -q" \
  --execute
```

The agent will receive your specialist's knowledge as context when it generates code.

---

## Step 10 (Optional): Connect Instances via Federation

If you have multiple specialists, they can share knowledge.

**On your general instance** (use the default database):

```bash
unset CLAW_DB_PATH  # back to default data/claw.db

# Register your medical specialist as a sibling
cam kb instances add "medical-ai" \
  "$(pwd)/data/instances/medical-ai.db" \
  --description "Clinical decision support, NER, pharmacology"

# Check it shows up
cam kb instances list

# Test a cross-instance query
cam kb instances query "biomedical named entity recognition"
```

Federation is **read-only** — the general instance can search the medical brain, but it never modifies it.

---

## Quick Reference: Switching Between Instances

```bash
# Use your medical specialist
export CLAW_DB_PATH=data/instances/medical-ai.db
cam govern stats   # Shows medical brain
cam kb insights    # Shows medical knowledge

# Switch back to general
unset CLAW_DB_PATH
cam govern stats   # Shows general brain

# Use a different specialist
export CLAW_DB_PATH=data/instances/quantum.db
cam govern stats   # Shows quantum brain
```

You can also create a shell alias:

```bash
# Add to your ~/.zshrc or ~/.bashrc
alias cam-medical="CLAW_DB_PATH=data/instances/medical-ai.db cam"
alias cam-quantum="CLAW_DB_PATH=data/instances/quantum.db cam"
alias cam-gamedev="CLAW_DB_PATH=data/instances/gamedev.db cam"
```

Then just run:

```bash
cam-medical pulse ingest https://github.com/some/medical-repo
cam-medical kb search "drug interaction"
cam-quantum kb search "error correction"
```

---

## Troubleshooting Checklist

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `cam: command not found` | venv not activated | `source .venv/bin/activate` |
| `0 methodologies` after ingest | Check CLAW_DB_PATH | `echo $CLAW_DB_PATH` — is it pointing where you think? |
| `OPENROUTER_API_KEY not set` | .env file missing or wrong location | `.env` must be next to `claw.toml` |
| `Secret scan blocked` | Repo has real credentials | Normal — pick a different repo |
| `Embedding error` | GOOGLE_API_KEY missing | Add to `.env` |
| `sqlite3.OperationalError: database is locked` | Another CAM process has the DB open | Close other terminals running CAM |
| Federation returns 0 results | Sibling DB path wrong or empty | `cam kb instances list` — check DB exists |
| `Mining: 0 patterns extracted` | Repo too small or not code | Try a larger, more established repo |
| Tests fail on fresh clone | Missing API keys | Expected — 10 tests skip without keys |

---

## What You Built

```
CAM-Pulse/
  data/
    claw.db                    ← general brain (default)
    instances/
      medical-ai.db            ← your specialist brain
      brain_manifest.json      ← your specialist's resume
  claw.toml                    ← shared config
  .env                         ← your API keys (never committed)
  src/                         ← CAM source code (same for all instances)
```

- **Same code**, different databases
- Each database is an independent brain with its own methodologies, fitness scores, and lifecycle states
- Federation lets brains share knowledge without copying or modifying each other
- You can create as many specialists as you want — just set `CLAW_DB_PATH` to a new path

---

## Next Steps

- **Add more repos**: `cam pulse ingest <url>` — each new repo deepens your specialist
- **Check freshness**: `cam pulse freshness --verbose` — see if mined repos have changed
- **Run PULSE daemon**: `cam pulse daemon` — auto-discover repos via X/Twitter
- **Self-enhance**: `cam self-enhance start` — let CAM improve its own code using your specialist's knowledge
- **Search knowledge**: `cam kb search "your topic"` — find patterns across everything you have mined
- **Audit trust**: `cam doctor audit --limit 10` — see which methodologies have proven track records

---

## Full Verification Script

Run this to verify everything works end-to-end:

```bash
#!/bin/bash
set -e

echo "=== Step 1: Verify install ==="
cam --help > /dev/null && echo "PASS: cam CLI works"

echo "=== Step 2: Verify keys ==="
cam doctor keycheck --for mine --live && echo "PASS: API keys valid"

echo "=== Step 3: Create standalone DB ==="
export CLAW_DB_PATH=data/instances/test-instance.db
cam govern stats | grep "Total methodologies" && echo "PASS: DB initialized"

echo "=== Step 4: Ingest a repo ==="
cam pulse ingest https://github.com/pallets/flask --force
cam govern stats | grep -v "Total methodologies:  0" && echo "PASS: Methodologies stored"

echo "=== Step 5: Search knowledge ==="
cam kb search "web framework routing" && echo "PASS: Search works"

echo "=== Step 6: Generate manifest ==="
cam kb instances manifest
test -f data/brain_manifest.json && echo "PASS: Manifest created"

echo "=== Step 7: Security scan ==="
cam security status | grep "AVAILABLE\|ENABLED" && echo "PASS: Security scanner active"

echo "=== All checks passed ==="
unset CLAW_DB_PATH
```
