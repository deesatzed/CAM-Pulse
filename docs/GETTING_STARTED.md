# Getting Started with CAM-PULSE

**Audience**: New users who want to get CAM running and see results in their first session.

## What You Will Accomplish

By the end of this guide, you will have:

1. Installed CAM and verified it works
2. Mined knowledge from a repo (CAM learns from code)
3. Seen CAM's knowledge base with what it learned
4. Optionally: enabled local LLM for zero-cost inference

---

## Step 1: Install

```bash
git clone https://github.com/deesatzed/CAM-Pulse.git
cd CAM-Pulse
python3 -m venv .venv
.venv/bin/pip install -e .
```

What this means: You cloned CAM's code, created an isolated Python environment, and installed all dependencies.

### Verify Installation

```bash
.venv/bin/cam --help
```

You should see a list of commands: `mine`, `enhance`, `cag`, `kb`, `doctor`, etc.

---

## Step 2: Set Up API Keys

CAM needs two API keys for cloud-based operations:

| Key | What For | Get It |
|-----|----------|--------|
| `OPENROUTER_API_KEY` | LLM access (Claude, Gemini, GPT via OpenRouter) | https://openrouter.ai/keys |
| `GOOGLE_API_KEY` | Gemini embeddings (384-dim vectors for search) | https://aistudio.google.com/apikey |

Create a `.env` file in the project root:

```bash
OPENROUTER_API_KEY=sk-or-your-key-here
GOOGLE_API_KEY=AIza-your-key-here
```

What this means: CAM uses OpenRouter to access LLMs for analysis, and Google's Gemini for creating searchable embeddings of knowledge.

**Skip API keys?** If you want zero-cost local-only inference, see [LOCAL_LLM_SETUP.md](LOCAL_LLM_SETUP.md) instead.

---

## Step 3: Verify Everything Works

```bash
.venv/bin/cam doctor environment
```

What this means: CAM checks that your API keys work, the database is reachable, and the embedding engine responds. You should see green "ok" for each service.

---

## Step 4: Mine Your First Repo

Pick any folder containing code repos (or a single repo) and let CAM learn from it:

```bash
.venv/bin/cam mine /path/to/your/repos --max-repos 3 --depth 3
```

What this means:
- `mine` = read and learn from code repositories
- `--max-repos 3` = only process 3 repos (keeps it quick for your first run)
- `--depth 3` = don't dig more than 3 directories deep

CAM will:
1. Discover git repos in the folder
2. Serialize each repo's files into a context window
3. Run 3-pass analysis: domain classify, overlap assess, LLM deep-dive
4. Extract findings and store them as **methodologies** in the knowledge base
5. Generate improvement tasks

You should see a results table with findings count, tokens used, and tasks generated.

---

## Step 5: See What CAM Learned

```bash
.venv/bin/cam kb search "your topic"
```

What this means: Search CAM's knowledge base for methodologies related to your topic. Replace "your topic" with something relevant to the repos you mined.

```bash
.venv/bin/cam kb insights
```

What this means: See a summary of everything CAM knows — domains, capability distribution, and synergies between methodologies.

---

## Step 6: Build the CAG Cache (Recommended)

```bash
.venv/bin/cam cag rebuild
.venv/bin/cam cag status
```

What this means: CAG (Cache-Augmented Generation) pre-computes your knowledge base into a format that is instantly available to every LLM query — no embedding lookup needed at query time. This makes all subsequent operations faster and more informed.

**Use this when**: You want CAM to apply its knowledge during mining and enhancement tasks.

---

## Step 7: Enhance a Repo (Optional)

```bash
.venv/bin/cam enhance /path/to/your-project
```

What this means: CAM uses everything it has learned to improve your project — it analyzes code, suggests changes, and applies improvements based on patterns mined from other repos.

To target one specific pending task by id (skips evaluate/plan):

```bash
.venv/bin/cam enhance /path/to/your-project --task-id <pending-task-uuid>
```

### Optional: seed the A/B knowledge ablation experiment

If you want CAM to record whether knowledge injection actually helps on your workload:

```bash
.venv/bin/cam ab-test start     # seed control + variant rows (one-time)
.venv/bin/cam ab-test status    # confirm both variants exist
```

After this, every `cam enhance` cycle writes a row to `ab_quality_samples` with the variant it used. See [docs/AB_KNOWLEDGE_ABLATION_SHOWPIECE.md](AB_KNOWLEDGE_ABLATION_SHOWPIECE.md).

---

## What's Next?

| Want to... | Read |
|-----------|------|
| Learn all CLI commands | [CAM_COMMAND_GUIDE.md](CAM_COMMAND_GUIDE.md) |
| Quick command reference | [CAM_OPERATOR_CHEATSHEET.md](CAM_OPERATOR_CHEATSHEET.md) |
| Set up local LLM (zero API cost) | [LOCAL_LLM_SETUP.md](LOCAL_LLM_SETUP.md) |
| Understand CAG caching | [CAG_GUIDE.md](CAG_GUIDE.md) |
| Understand KV cache compression | [KV_CACHE_GUIDE.md](KV_CACHE_GUIDE.md) |
| Tune advanced features (Kelly, deepConf, budget) | [ADVANCED_FEATURES.md](ADVANCED_FEATURES.md) |
| Fix problems | [TROUBLESHOOTING.md](TROUBLESHOOTING.md) |
| Tune memory management | [GOVERNANCE_TUNING.md](GOVERNANCE_TUNING.md) |
| See real workflow examples | CAM_SHOWPIECE_*.md files |
| Understand assimilation workflows | [CAM_BEGINNER_ASSIMILATION_GUIDE.md](CAM_BEGINNER_ASSIMILATION_GUIDE.md) |

---

## Key Concepts (Quick Reference)

| Concept | One-Line Explanation |
|---------|---------------------|
| **Methodology** | A piece of knowledge CAM learned (problem + solution + metadata) |
| **Mining** | CAM reads repos and extracts methodologies |
| **CAG** | Pre-computed knowledge cache for zero-latency retrieval |
| **Ganglion** | A specialized knowledge brain (default: "general") |
| **Governance** | Automatic memory management (lifecycle, quotas, dedup) |
| **Kelly routing** | Bayesian agent selection based on past performance |
| **KV cache** | Backend optimization for repeated LLM queries with local models |
| **Fitness** | EMA score tracking methodology quality over time |
| **PULSE** | Autonomous discovery engine (finds new repos to mine) |
| **deepConf** | 6-factor confidence score for methodology ranking |
| **Assimilation** | Process of enriching mined findings with novelty/potential scores |
