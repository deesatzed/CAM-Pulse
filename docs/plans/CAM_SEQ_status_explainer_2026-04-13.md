# CAM-SEQ Status Explainer

Date: 2026-04-13

Purpose:
- explain what CAM-SEQ currently is
- explain what each major feature does
- separate real implementation from partial implementation and aspirational work
- give a concrete mining trial procedure

## Short Version

Core CAM-SEQ is real.

What is real now:
- component memory
- task decomposition into slots
- application packet review before mutation
- reviewed run sequencing
- retrograde/distill after run
- governance/policy memory
- federation packet surfaces
- benchmark/proof scaffolding

What is not fully real:
- perfect generic component search relevance
- full local CodeQL lane
- true external A2A specialist transport
- polished demo/proof layer
- deeper causal reasoning beyond heuristics

What is genuinely vaporware:
- anything claiming full external specialist orchestration or full local CodeQL enforcement by default
- those are planned or partial, not finished

## Feature Map

### 1. Component Memory

Description:
- Stores reusable code components as `ComponentCard`s with provenance, fit history, and lineage.

Can do now:
- extract components from repo code
- backfill components from existing methodologies
- search, list, and view components
- show component history and lineage
- use component memory during plan creation

Cannot do yet:
- perfect search relevance for broad generic queries
- exhaustive parser precision across all language constructs

Reality:
- real
- partially rough around generic search UX

Main files:
- [component_extractor.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/mining/component_extractor.py)
- [miner.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/miner.py)
- [semantic.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/memory/semantic.py)

### 2. Plan Review / Application Packets

Description:
- Turns a task into slots, ranks candidates, builds one packet per slot, and forces review before execution.

Can do now:
- infer task archetype
- decompose into slots
- build reviewed packets
- approve and swap candidates
- execute approved plans

Cannot do yet:
- guarantee high-quality candidate discovery if the repo has weak mined memory for that topic

Reality:
- real
- one of the strongest built parts

Main files:
- [taskome.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/planning/taskome.py)
- [component_ranker.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/memory/component_ranker.py)
- [application_packet.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/planning/application_packet.py)

### 3. Reviewed Run Sequencing

Description:
- Executes approved plans slot-by-slot and records pair, landing, outcome, and connectome events.

Can do now:
- run reviewed plans
- show sequence, connectome, landings, and events
- pause, resume, and reverify
- swap candidates during a run
- block and unblock slots
- ban and unban families

Cannot do yet:
- replace the legacy execution engine with a brand-new native executor
- it still wraps the existing cycle in a slot-aware control loop

Reality:
- real
- additive, not total engine replacement

Main files:
- [dashboard_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/web/dashboard_server.py)
- [forge run page](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/forge/run/[id]/page.tsx)

### 4. Retrograde / Distill

Description:
- Explains why a run failed or succeeded and proposes promotions, recipes, governance actions, and mining missions.

Can do now:
- produce retrograde analysis
- show audits
- distill recommendations
- queue mining missions
- promote recipes and policies

Cannot do yet:
- deep causal reasoning beyond a sophisticated heuristic ranking layer
- fully separate negative-memory subsystem

Reality:
- real
- useful, but still heuristic

Main files:
- [dashboard_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/web/dashboard_server.py)
- [evolution run page](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/evolution/run/[runId]/page.tsx)

### 5. Governance / Critical Slot Lane

Description:
- Adds policy memory, proof gates, waivers, conflict detection, and policy-aware ranking for risky slots.

Can do now:
- promote policies
- apply policies during planning and swaps
- show conflicts and trends
- run Semgrep via the Docker path
- use waivers and proof gates

Cannot do yet:
- full local CodeQL lane by default
- full heavyweight static-analysis hard gate locally

Reality:
- real but partial
- not vaporware, but not fully complete

Main files:
- [policy_tools.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/security/policy_tools.py)
- [security/semgrep.yml](/Volumes/WS4TB/RNACAM/CAM-Pulse/security/semgrep.yml)

### 6. Federation / MCP / Recipes

Description:
- Cross-brain packet search, specialist packet exchange, MCP tools, mining missions, and recipe reuse.

Can do now:
- packet-style federation search
- specialist packet exchange surface
- CAM-SEQ MCP tools
- mining mission persistence
- recipe promotion and some auto-distillation

Cannot do yet:
- true external A2A transport
- full specialist runtime exchange outside this additive app layer

Reality:
- mostly real
- external transport is still aspirational

Main files:
- [mcp_server.py](/Volumes/WS4TB/RNACAM/CAM-Pulse/src/claw/mcp_server.py)
- [federation page](/Volumes/WS4TB/RNACAM/CAM-Pulse/forge-ui/src/app/federation/page.tsx)

### 7. Benchmarks / Proof

Description:
- Pilot and full benchmark suites, ablations, seeded retrograde cases, and generated reports.

Can do now:
- run pilot and full benchmark scaffolds
- run seeded retrograde tests
- generate markdown and JSON benchmark artifacts

Cannot do yet:
- broader real-repo mutation benchmark program
- polished demo artifacts

Reality:
- real scaffolding
- partial proof layer

Main files:
- [tests/benchmarks/connectome_suite](/Volumes/WS4TB/RNACAM/CAM-Pulse/tests/benchmarks/connectome_suite)
- [camseq_connectome_report.md](/Volumes/WS4TB/RNACAM/CAM-Pulse/docs/benchmarks/camseq_connectome_report.md)

## What The System Can And Cannot Do Relative To The Original Spec

### Before mutation

Spec wanted:
- packet-first review before writing

Current:
- yes, implemented

Status:
- real

### During mutation

Spec wanted:
- slot-by-slot supervision, events, connectome, controls

Current:
- yes, implemented

Status:
- real

### After mutation

Spec wanted:
- retrograde, distill, mining, recipe and policy learning

Current:
- yes, implemented in first usable form

Status:
- real but heuristic

### Critical-slot hard security lane

Spec wanted:
- stricter risky-slot handling with static analysis

Current:
- partially implemented
- Semgrep path: yes
- CodeQL default local path: no

Status:
- partial, not vaporware

### Federation specialist transport

Spec wanted:
- stronger specialist and external exchange

Current:
- additive internal version exists
- true external or A2A transport does not

Status:
- partial and partly aspirational

## What Is Vaporware Vs Not

### Not vaporware
- component cards
- application packets
- plan review
- reviewed execution
- connectome, events, and audits
- retrograde and distill
- mining missions
- policy memory
- federation packet UI and API
- benchmark harnesses and reports

### Partial, but real
- critical-slot security lane
- recipe learning
- federation supervision
- benchmark proof program

### Still aspirational
- full external A2A specialist transport
- polished full-system proof and demo package
- full default local CodeQL lane

## Mining Trial

There are two useful trial types.

### Trial A: Quick preview

Purpose:
- no heavy mining
- just see whether the repo looks mineable

Run:

```bash
cd /Volumes/WS4TB/RNACAM/CAM-Pulse
source .venv/bin/activate
PYTHONPATH=src python -m claw.cli._monolith mine-self --quick --path .
```

What it does:
- scans file stats
- shows language and domain signals
- no LLM calls

### Trial B: Real mining

Purpose:
- actually write methodologies and findings into CAM memory

Run:

```bash
cd /Volumes/WS4TB/RNACAM/CAM-Pulse
source .venv/bin/activate
PYTHONPATH=src python -m claw.cli._monolith mine-self --path . --target . --no-tasks --max-minutes 10 -v
```

If key validation is a problem, use:

```bash
PYTHONPATH=src python -m claw.cli._monolith mine-self --path . --target . --no-tasks --no-live-keycheck --max-minutes 10 -v
```

What it does:
- mines the repo
- stores methodologies and findings
- does not generate enhancement tasks because of `--no-tasks`

### Backfill components from mined methodologies

Run:

```bash
cd /Volumes/WS4TB/RNACAM/CAM-Pulse
source .venv/bin/activate
PYTHONPATH=src python -m claw.cli._monolith learn backfill-components -n 200 -v
```

What it does:
- turns mined methodologies into `ComponentCard`s

### Verify the trial

1. Search components:

```bash
curl -sS 'http://127.0.0.1:8420/api/v2/components/search?q=oauth%20token%20refresh&limit=8'
```

2. Create a plan:

```bash
curl -sS -X POST 'http://127.0.0.1:8420/api/v2/plans' \
  -H 'Content-Type: application/json' \
  -d '{
    "task_text":"Add OAuth session handling with token refresh",
    "workspace_dir":"/Volumes/WS4TB/RNACAM/CAM-Pulse",
    "target_language":"python"
  }'
```

3. Optional HTTP backfill instead of CLI:

```bash
curl -sS -X POST 'http://127.0.0.1:8420/api/v2/components/backfill' \
  -H 'Content-Type: application/json' \
  -d '{"limit":200}'
```

### What success looks like

- `mine-self` completes without fatal errors
- `backfill-components` reports created or updated component counts
- component search returns real repo-local cards
- plan creation succeeds without relying only on weak workspace fallback

### What failure looks like

- mining does not write methodologies
- backfill creates zero useful components
- search only returns weak generic modules
- plans always rely on weak fallback instead of mined memory

## Best Next Trial

Run this sequence:

```bash
cd /Volumes/WS4TB/RNACAM/CAM-Pulse
source .venv/bin/activate
PYTHONPATH=src python -m claw.cli._monolith mine-self --quick --path .
PYTHONPATH=src python -m claw.cli._monolith mine-self --path . --target . --no-tasks --no-live-keycheck --max-minutes 10 -v
PYTHONPATH=src python -m claw.cli._monolith learn backfill-components -n 200 -v
curl -sS 'http://127.0.0.1:8420/api/v2/components/search?q=oauth%20token%20refresh&limit=8'
```

If you run that sequence, the outputs will show whether the mining trial produced useful memory or mostly noise.
