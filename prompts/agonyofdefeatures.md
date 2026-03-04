# Agony of Defeatures — Real vs Synthetic Feature Audit

Analyze the repository and classify every user-facing feature by its connection to real functionality. The goal is to expose features that appear to work but are backed by fake, mocked, or placeholder data.

## Instructions

For every feature visible to the end user (UI element, API endpoint, CLI command, webhook handler), trace the full execution path from the user interaction to the data source. Classify based on what actually happens, not what the code says it does.

## Classification Definitions

- **LIVE** — Feature connects to a real backend, real database, real external service. Data flows end-to-end with no simulation.
- **SYNTH** — Feature connects to code that generates synthetic, random, or hardcoded data instead of real sources. The UI works but the data is fabricated.
- **DEMO** — Feature renders static placeholder content. No execution path beyond displaying predetermined values.
- **ORPHAN** — Feature code exists but is unreachable: no route points to it, no UI element triggers it, no test exercises it.

## Required Output

### Feature Inventory Table

| # | Feature | Classification | Entry Point | Data Source | Evidence Path |
|---|---------|---------------|-------------|-------------|---------------|
| 1 | User login | LIVE | `src/routes/auth.py:45` | PostgreSQL `users` table | auth.py -> service.py -> db.py -> real DB |
| 2 | Dashboard charts | SYNTH | `src/pages/dashboard.tsx:12` | `generateFakeData()` in `utils/mock.ts:8` | dashboard -> api call -> handler returns Math.random() |
| 3 | Export PDF | DEMO | `src/components/Export.tsx:5` | Button exists, onClick shows "Coming soon" | Dead end at component level |
| 4 | Legacy search | ORPHAN | `src/search/legacy.py` | No route references this module | Unreachable |

### For Each SYNTH or DEMO Feature

Provide a detailed trace:

1. **User action** — what the user does to trigger this feature
2. **Code path** — file:line through each layer
3. **Where it goes fake** — the exact line where real data stops and synthetic begins
4. **What it pretends to do** — the behavior the user sees
5. **What it actually does** — what the code really executes

### Summary Statistics

| Classification | Count | Percentage |
|---------------|-------|------------|
| LIVE          | N     | N%         |
| SYNTH         | N     | N%         |
| DEMO          | N     | N%         |
| ORPHAN        | N     | N%         |

### Risk Assessment

For each SYNTH and DEMO feature, assess:

- **User deception risk** — could a user mistake this for real functionality?
- **Data integrity risk** — could synthetic data contaminate real data stores?
- **Removal safety** — can this be removed or upgraded without breaking other features?

## Output Format

Use the exact tables and sections above. Every classification must include file path evidence. If you cannot trace a feature fully, mark it as "UNVERIFIABLE" and explain what blocked the trace.

Focus on actionable findings with file path evidence.
