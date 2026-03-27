# How to Create a CAM Ganglion

**Audience**: You know how to use a terminal and have Python installed. No prior CAM experience needed.

---

## Terminology

Before we start, here's how the parts fit together:

```
CAM Brain    = the full federated system (all ganglia together)
CAM Ganglion = a specialized instance with its own claw.db and focus area
CAM Swarm    = the runtime layer that connects ganglia
```

Think of it like neuroscience:

```
Brain        = the whole organ — all knowledge, all capabilities
Ganglion     = a cluster of nerve cells specialized for one function
               (a semi-autonomous processing node)
Swarm        = the nerve fibers connecting ganglia
               (read-only queries, no data copying)
```

You are creating a new **Ganglion** — a specialized CAM node that:
- Has its own database (claw.db)
- Only knows about one domain
- Can be queried by other ganglia in the swarm
- Can query other ganglia when it needs knowledge outside its specialty

---

## What You'll Build

```
CAM-Pulse/
  data/
    claw.db                    <- primary ganglion (default)
    instances/
      medical-ai.db            <- your new specialist ganglion
      brain_manifest.json      <- this ganglion's resume for the swarm
  claw.toml                    <- shared config (ganglion registry lives here)
  .env                         <- your API keys (never committed)
  src/                         <- CAM source code (same for all ganglia)
```

**Same code, different databases.** Each ganglion is an independent brain
with its own methodologies, fitness scores, and lifecycle states.

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

**Troubleshoot**:
- `command not found: cam` — Run `source .venv/bin/activate` again
- `pip install` fails — Make sure you have Python 3.11+
- Errors about `sqlite-vec` — Normal on some systems, CAM falls back gracefully

---

## Step 3: Set Up Your API Keys

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

---

## Step 4: Verify the Default Ganglion Works

```bash
cam govern stats
```

You should see:

```
Memory Governance Stats
  Total methodologies:  0
  Active (non-dead):    0
  Quota: 0/5000 (0.0%)
  DB size: 0.46 MB
```

This is the primary ganglion — a fresh brain with zero methodologies.

---

## Step 5: Create Your Specialist Ganglion

Now create a new ganglion for your domain.

```bash
mkdir -p data/instances
```

Tell CAM to use the new ganglion's database via `CLAW_DB_PATH`:

```bash
export CLAW_DB_PATH=data/instances/medical-ai.db
```

**Check**: Verify CAM sees the new database.

```bash
cam govern stats
```

You should see `0 methodologies` — this is a brand new ganglion. The database
is automatically created and initialized.

---

## Step 6: Feed Your Ganglion

### Option A: Ingest Specific Repos (Recommended)

Pick 3-5 GitHub repos in your domain:

```bash
# Medical AI ganglion
cam pulse ingest \
  https://github.com/explosion/spacy-bio \
  https://github.com/allenai/scispacy \
  https://github.com/dmis-lab/biobert

# Game dev ganglion
cam pulse ingest \
  https://github.com/bevyengine/bevy \
  https://github.com/godotengine/godot

# Drive-ops ganglion (filesystem patterns)
cam pulse ingest \
  https://github.com/sharkdp/fd \
  https://github.com/BurntSushi/ripgrep
```

### Option B: HuggingFace Model Repos

```bash
cam pulse ingest https://huggingface.co/microsoft/phi-3-mini-4k-instruct
```

### Option C: X-Scout Auto-Discovery

Requires `XAI_API_KEY` in your `.env`:

```bash
cam pulse scan --keywords "medical AI clinical decision support"
```

**Check**: Verify your ganglion learned something.

```bash
cam govern stats
```

---

## Step 7: Search Your Ganglion's Knowledge

```bash
cam kb insights
cam kb search "named entity recognition for biomedical text"
cam kb domains
```

---

## Step 8: Generate a Brain Manifest

The manifest is your ganglion's resume — a compact JSON summary of what it
knows. Other ganglia in the swarm read this to decide if cross-querying is
worthwhile.

```bash
cam kb instances manifest
```

**Check**: The manifest file should exist.

```bash
cat data/brain_manifest.json | python3 -m json.tool | head -20
```

---

## Step 9: Use Your Ganglion for Builds

```bash
cam create /path/to/new-project --repo-mode new \
  --request "Build a biomedical NER pipeline using spaCy" \
  --check "pytest -q" \
  --execute
```

The agent receives your ganglion's knowledge as context when generating code.

---

## Step 10: Connect Ganglia into a CAM Brain

This is where the swarm comes alive. Register your specialist ganglion as
a sibling of the primary ganglion.

**On the primary ganglion** (use the default database):

```bash
unset CLAW_DB_PATH  # back to primary ganglion

# Register the medical ganglion
cam kb instances add "medical-ai" \
  "$(pwd)/data/instances/medical-ai.db" \
  --description "Clinical decision support, NER, pharmacology"

# Check the swarm
cam kb instances list

# Test a cross-ganglion query
cam kb instances query "biomedical named entity recognition"
```

The swarm is **read-only** — the primary ganglion can search the medical
ganglion's brain, but it never modifies it.

**Enable automatic swarm queries during builds:**

Edit `claw.toml`:

```toml
[instances]
enabled = true
instance_name = "general"
instance_description = "General-purpose AI development patterns"
```

Now when the primary ganglion works on a task and its local knowledge is
sparse (confidence < 0.3), it automatically queries sibling ganglia for
supplemental methodologies.

---

## Quick Reference: Switching Ganglia

```bash
# Use your medical ganglion
export CLAW_DB_PATH=data/instances/medical-ai.db
cam govern stats   # Shows medical ganglion's knowledge
cam kb insights    # Shows medical ganglion's domains

# Switch back to primary
unset CLAW_DB_PATH
cam govern stats   # Shows primary ganglion

# Use a different ganglion
export CLAW_DB_PATH=data/instances/drive-ops.db
cam govern stats   # Shows drive-ops ganglion
```

Shell aliases for convenience:

```bash
# Add to ~/.zshrc or ~/.bashrc
alias cam-medical="CLAW_DB_PATH=data/instances/medical-ai.db cam"
alias cam-drive="CLAW_DB_PATH=data/instances/drive-ops.db cam"
alias cam-quantum="CLAW_DB_PATH=data/instances/quantum.db cam"
```

Then:

```bash
cam-medical kb search "drug interaction"
cam-drive kb search "repo dedup"
cam-quantum kb search "error correction"
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `cam: command not found` | venv not activated | `source .venv/bin/activate` |
| `0 methodologies` after ingest | Wrong ganglion active | `echo $CLAW_DB_PATH` |
| `OPENROUTER_API_KEY not set` | .env missing | `.env` must be next to `claw.toml` |
| `Secret scan blocked` | Repo has real credentials | Normal — pick a different repo |
| `Embedding error` | GOOGLE_API_KEY missing | Add to `.env` |
| `database is locked` | Another CAM process has DB open | Close other terminals |
| Swarm returns 0 results | Ganglion DB path wrong or empty | `cam kb instances list` |
| `0 patterns extracted` | Repo too small | Try a larger repo |

---

## How the CAM Brain Forms

```
┌──────────────────────────────────────────────────────────┐
│                      CAM Brain                           │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐   │
│  │   Primary     │  │  Medical AI  │  │  Drive-Ops   │   │
│  │   Ganglion    │  │  Ganglion    │  │  Ganglion    │   │
│  │              │  │              │  │              │   │
│  │  general.db  │  │ medical.db   │  │ drive-ops.db │   │
│  │  1877 meths  │  │   42 meths   │  │    0 meths   │   │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘   │
│         │                 │                 │            │
│         └────────CAM Swarm (FTS5)───────────┘            │
│               read-only · no data copying                │
└──────────────────────────────────────────────────────────┘
```

- Each ganglion operates independently
- The swarm connects them via brain manifests
- During task execution, if local confidence is low, the swarm queries
  relevant ganglia and injects their methodologies into the prompt
- Results are tagged with source ganglion name for attribution
- Federation never modifies sibling databases

---

## Full Verification Script

```bash
#!/bin/bash
set -e

echo "=== Step 1: Verify install ==="
cam --help > /dev/null && echo "PASS: cam CLI works"

echo "=== Step 2: Verify keys ==="
cam doctor keycheck --for mine --live && echo "PASS: API keys valid"

echo "=== Step 3: Create specialist ganglion ==="
export CLAW_DB_PATH=data/instances/test-ganglion.db
cam govern stats | grep "Total methodologies" && echo "PASS: Ganglion DB initialized"

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

---

## Next Steps

- **Grow your ganglion**: `cam pulse ingest <url>` — each repo deepens its expertise
- **Check freshness**: `cam pulse freshness --verbose` — see if mined repos have been updated
- **Self-enhance**: `cam self-enhance start` — let the ganglion improve its own code
- **Connect more ganglia**: `cam kb instances add <name> <db_path>` — expand the brain
- **Audit trust**: `cam doctor audit --limit 10` — see which methodologies have proven track records
