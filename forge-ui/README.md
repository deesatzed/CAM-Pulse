# CAM-PULSE Web UI (`forge-ui`)

The browser interface for CAM-PULSE. 15 interactive pages backed by 40+ real FastAPI endpoints. Zero mock data — every number, chart, and interaction hits real APIs against real data.

## Quick Start

```bash
# 1. Start the backend (from multiclaw root)
cam dashboard            # FastAPI on :8420

# 2. Start the frontend
cd forge-ui
npm install
npm run dev              # Next.js on :3000
```

Open [http://localhost:3000](http://localhost:3000).

## Pages

| Page | Route | Description |
|------|-------|-------------|
| **Dashboard** | `/` | Brain stats, lifecycle distribution, language breakdown, sibling brains |
| **Knowledge Explorer** | `/knowledge` | Federated search across all 7 brains with ganglion badges and filters |
| **Methodology Detail** | `/knowledge/[id]` | Solution code, fitness history, usage attribution, metadata |
| **Gap Heatmap** | `/knowledge/gaps` | Interactive category x brain coverage matrix with click-to-mine |
| **Playground** | `/playground` | Execute tasks via MicroClaw, watch 7-gate verification, correction replay |
| **Evolution Lab** | `/evolution` | A/B tests (Bayesian comparison), agent routing heatmap, fitness trajectories, bandit arms |
| **Mining Console** | `/mining` | Mine repos from browser, select target brain, watch extraction |
| **Federation Hub** | `/federation` | D3 force-directed brain topology, cross-brain analysis |
| **Costs** | `/costs` | Token cost breakdown, budget utilization bars, per-agent efficiency cards |
| **Brain Graph** | `/forge` | D3 force-directed visualization of all brains and connections |
| **Build Brain** | `/forge/build` | 4-step wizard: name, repos, agents, prompts. Persists via sessionStorage |
| **Script Generator** | `/forge/script` | Generate executable shell scripts for CAM operations |
| **Brain Detail** | `/forge/brain/[name]` | Per-ganglion methodology explorer with categories |
| **Forge Run** | `/forge/run/[id]` | Execution session detail with step log and results |

## Tech Stack

- **Next.js 16** (App Router) with TypeScript
- **Tailwind CSS** (dark theme)
- **Recharts** for charts (fitness trajectories, bar charts, routing heatmap)
- **D3.js** for force-directed brain topology graph
- **FastAPI** backend at `localhost:8420` (via `NEXT_PUBLIC_API_URL` env var)

## Architecture

```
forge-ui/
  src/
    app/              # Next.js App Router pages (15 routes)
    components/       # Shared components (8 total)
      badge.tsx       # Language/category badges
      card.tsx        # Card + CardTitle
      error-banner.tsx # Retry-enabled error display
      intent-bar.tsx  # Intent analysis bar
      script-viewer.tsx # Shell script viewer with copy/download
      sidebar.tsx     # Navigation sidebar
      skeleton.tsx    # Loading skeletons
      step-pipeline.tsx # Step visualization pipeline
    lib/
      api.ts          # Typed API client (40+ endpoints)
```

Every API call goes through `lib/api.ts` which provides full TypeScript interfaces for all request/response shapes.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXT_PUBLIC_API_URL` | `http://localhost:8420` | FastAPI backend URL |

## Development

```bash
npm run dev          # Development server with hot reload
npm run build        # Production build (validates all routes)
npm run lint         # ESLint check
npx tsc --noEmit     # Type check without building
```

## Tests

Backend endpoint tests live in the parent `tests/` directory:

```bash
cd ..
PYTHONPATH=src python -m pytest tests/test_dashboard_server.py tests/test_dashboard_playground.py -v
# 74 passed
```
