
# KB Bootstrap Playbooks

Curated first-run workflows for bringing the CAM-PULSE knowledge base from
empty → domain-ready. Every command in this document is real and was
verified against `src/claw/community/seeder.py` and
`src/claw/data/seed/*.jsonl`.

## How bootstrap works

`cam kb bootstrap --domain <D>` resolves `<D>` through the `DOMAIN_PACKS`
table in `src/claw/community/seeder.py:45`, loads the matching JSONL
seed packs, inserts each record into `methodologies` + `methodology_fts`
+ `methodology_embeddings`, and tags every row with `origin:seed` so it:

- cannot be confused with user-mined knowledge,
- is protected from lifecycle decay,
- can be re-seeded if accidentally deleted.

Seeds are idempotent — the `community_imports.content_hash` UNIQUE index
makes re-running a bootstrap a no-op unless `--force` is passed.

```bash
# Discover what's on disk before committing to a domain
cam kb seed --list-packs

# First-run: Python brain starter
cam kb bootstrap --domain python

# Force re-seed (idempotent otherwise)
cam kb bootstrap --domain python --force

# Full sweep
cam kb bootstrap --domain all
```

## Seed pack inventory

Counts and category distributions are taken directly from
`src/claw/data/seed/*.jsonl` and were verified on this commit.

| Pack | Records | Languages | Top categories |
|------|--------:|-----------|----------------|
| `core_v1` | 31 | python (13), unlabeled (18) | architecture (5), algorithm (2), cli_ux (2), cross_cutting (2), testing (1) |
| `starter_python_v1` | 51 | python (16), unlabeled (34), typescript (1) | code_quality (5), architecture (3), security (3), design_patterns (3), memory (2), ai_integration (1) |
| `starter_devsecops_v1` | 12 | python (11), unlabeled (1) | code_quality (7), security (3), testing (2) |
| `starter_webdev_v1` | 1 | typescript (1) | architecture (1) |

The "unlabeled" rows are polyglot methodologies — architecture,
CLI-UX, testing, and cross-cutting patterns that don't belong to a
single language.

## Playbook 1 — Python-primary workspace (default)

**When to use:** Any Python-first repository (Django, FastAPI, pytest
pipelines, data tools, ML/LLM apps).

```bash
cam init --domain python --yes
# or, if already initialised:
cam kb bootstrap --domain python
```

**Packs loaded:** `core_v1` + `starter_python_v1` → **82 methodologies**

**What you get:**
- 31 foundational architecture / algorithm / CLI patterns from `core_v1`
- 51 Python-biased code-quality, security, design-pattern, and
  AI-integration methodologies from `starter_python_v1`

**Verify:**
```bash
cam doctor status | grep methodologies
# should report: methodologies: 82 (82 seed) on a fresh DB
```

## Playbook 2 — DevSecOps / CI-CD hardening

**When to use:** Repositories where the primary concern is supply-chain
security, dependency scanning, CI hardening, or compliance reviews.

```bash
cam init --domain devsecops --yes
# or:
cam kb bootstrap --domain devsecops
```

**Packs loaded:** `core_v1` + `starter_devsecops_v1` → **43 methodologies**

**What you get:**
- The `core_v1` foundation (31)
- 12 devsecops-focused methodologies weighted toward `code_quality` (7),
  `security` (3), and `testing` (2)

**Tip:** Stack this on top of `python` later with
`cam kb bootstrap --domain python` — the content-hash dedup prevents
double-inserts for `core_v1`, so you end up with 94 unique rows instead
of 125.

## Playbook 3 — Webdev (TypeScript / Next.js / React)

**When to use:** Any TypeScript- or JavaScript-primary repository where
Python brain patterns still provide useful cross-cutting value (pytest
harness design, architecture patterns, security).

```bash
cam init --domain webdev --yes
# or:
cam kb bootstrap --domain webdev
```

**Packs loaded:** `core_v1` + `starter_webdev_v1` + `starter_python_v1`
→ **83 methodologies**

**Why the Python supplement?** The webdev pack is intentionally tiny
(1 architecture record) because the TypeScript ganglion isn't yet
seeded from a curated pack — its methodologies are mined live from
repos like `dram-quest`. See `src/claw/community/seeder.py:40` for
the rationale. Stacking with `starter_python_v1` gives webdev users a
useful baseline while the TS pack matures.

## Playbook 4 — All packs (maximum coverage)

**When to use:** You're demonstrating CAM-PULSE, running an A/B
experiment that needs maximum methodology diversity, or mining a
polyglot repository.

```bash
cam init --domain all --yes
# or:
cam kb bootstrap --domain all
```

**Packs loaded:** `core_v1` + `starter_python_v1` +
`starter_devsecops_v1` + `starter_webdev_v1` → **95 methodologies**
(31 + 51 + 12 + 1 before dedup, content-hash guarantees no duplicates).

## After bootstrap — next steps

Once the KB has seed rows, you can extend it in three directions:

### Mine the current repo

```bash
cam mine --brain python   # or typescript / go / rust — auto-detected
```

This appends mined methodologies into `instances/<brain>/claw.db`
(the brain ganglion), and federation queries automatically surface
them alongside the seed rows.

### Zero-cost self-preview

```bash
cam mine-self --quick
```

Scans the current repo, reports language breakdown and domain
signals — no LLM calls, no token cost. Use this before committing
to a full mine.

### Federate across ganglia

```bash
cam federate "<natural language query>"
```

Queries the primary brain (`data/claw.db`) plus every sibling
ganglion under `instances/*/claw.db`. Returns ranked methodologies
across the whole federation.

## Playbooks not yet available

The task charter originally asked for 7 domain playbooks. Only 4 are
real right now because the underlying `DOMAIN_PACKS` table in
`src/claw/community/seeder.py:45` exposes exactly those four keys.
The remaining three (below) are deliberately not shipped as seed
packs — doing so without real content would be a mock-data
violation of the workspace rules.

| Deferred playbook | Why it's not ready |
|-------------------|--------------------|
| `data-science` | No curated pack yet — mine from Jupyter / pandas / numpy repos first, then export. |
| `rust-systems` | Rust ganglion has 60 live-mined methodologies (see `MEMORY.md`) but none have been curated into a static pack; the mining pipeline populates `instances/rust/claw.db` on demand. |
| `go-backend` | Same as rust — 33 live-mined rows in `instances/go/claw.db`, no curated pack. |

To add a new playbook properly:

1. Mine a representative repo: `cam mine --brain <lang> <repo>`
2. Review the outputs via `cam kb search` / `cam federate`
3. Promote viable methodologies to a curated pack using the
   kit exporter (`cam kb export-kit`, see Step 7 of
   `streamed-squishing-whale.md`)
4. Add the new pack stem to `DOMAIN_PACKS` in `seeder.py`
5. Add the playbook section to this document

## Troubleshooting

**`cam doctor status` shows `methodologies: 0`** — The DB was never
seeded. Run `cam kb bootstrap --domain python`. If the count stays
at zero, check logs for `Seed directory not found` — that means the
package install is missing `src/claw/data/seed/`, which should never
happen via `pip install` or `uv pip install`.

**`cam kb bootstrap` says `already_seeded`** — You already have
`origin:seed` rows. Pass `--force` to re-seed.

**"no_seed_packs" reason** — The filter passed to
`discover_seed_packs()` matched no files. Check your pack name with
`cam kb seed --list-packs`.

**Embedding failures during bootstrap** — Non-fatal. The row is still
inserted into `methodologies` + `methodology_fts`; only
`methodology_embeddings` is missed. Backfill is available as a
library call via `seeder.repair_missing_embeddings(engine, embedding_engine)`
— no CLI wrapper exists yet.

## References

- Seeder implementation: `src/claw/community/seeder.py`
- CLI wiring: `src/claw/cli/_monolith.py` → `kb_app` command group
- Lifecycle decay and promotion rules: see `docs/LIFECYCLE_PROMOTION_INVESTIGATION.md`
- Seed packs: `src/claw/data/seed/*.jsonl`
