const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8420";

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${path} failed (${res.status}): ${body}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Stats
// ---------------------------------------------------------------------------

export interface BrainStats {
  primary: {
    name: string;
    total: number;
    active: number;
    lifecycle: Record<string, number>;
    languages: Record<string, number>;
    top_categories: Record<string, number>;
    source_repos: number;
  };
  siblings: Array<{
    name: string;
    description: string;
    db_exists: boolean;
    methodology_count: number;
  }>;
  total_across_brain: number;
}

export function getStats(): Promise<BrainStats> {
  return fetchAPI("/api/stats");
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

export interface SearchResult {
  id: string;
  problem: string;
  solution_preview: string;
  notes: string;
  tags: string[];
  language: string;
  lifecycle: string;
  novelty: number | null;
  retrievals: number;
  successes: number;
  source_ganglion: string;
  fts_rank: number;
  relevance_score?: number;
}

export interface SearchResponse {
  query: string;
  total_results: number;
  elapsed_ms: number;
  ganglion_counts: Record<string, number>;
  results: SearchResult[];
}

export function searchKnowledge(q: string, limit = 30): Promise<SearchResponse> {
  return fetchAPI(`/api/search?q=${encodeURIComponent(q)}&limit=${limit}`);
}

// ---------------------------------------------------------------------------
// Methodology
// ---------------------------------------------------------------------------

export interface Methodology {
  id: string;
  problem_description: string;
  solution_code: string;
  methodology_notes: string;
  tags: string[];
  language: string;
  lifecycle_state: string;
  methodology_type: string;
  novelty_score: number | null;
  potential_score: number | null;
  retrieval_count: number;
  success_count: number;
  failure_count: number;
  created_at: string;
  files_affected: string | null;
}

export function getMethodology(id: string): Promise<Methodology> {
  return fetchAPI(`/api/methodology/${id}`);
}

export interface FitnessEntry {
  fitness_total: number;
  fitness_vector: Record<string, number>;
  trigger_event: string;
  created_at: string;
}

export function getMethodologyFitness(id: string): Promise<{ methodology_id: string; entries: FitnessEntry[] }> {
  return fetchAPI(`/api/methodology/${id}/fitness`);
}

// ---------------------------------------------------------------------------
// Gaps
// ---------------------------------------------------------------------------

export interface CoverageMatrix {
  matrix: Record<string, Record<string, number>>;
  sparse_cells: Array<[string, string]>;
  empty_cells: Array<[string, string]>;
  total_by_category: Record<string, number>;
  total_by_brain: Record<string, number>;
}

export function getGapsMatrix(): Promise<CoverageMatrix> {
  return fetchAPI("/api/gaps/matrix");
}

export interface GapCluster {
  theme: string;
  count: number;
  sample_titles: string[];
  suggested_name: string;
  methodology_ids: string[];
}

export function getGapsDiscover(): Promise<{ clusters: GapCluster[] }> {
  return fetchAPI("/api/gaps/discover");
}

export interface GapTrendSnapshot {
  id: string;
  total_methodologies: number;
  sparse_cells: Array<[string, string]>;
  created_at: string;
}

export function getGapsTrend(): Promise<{ summary: string; snapshots: GapTrendSnapshot[] }> {
  return fetchAPI("/api/gaps/trend");
}

// ---------------------------------------------------------------------------
// Evolution
// ---------------------------------------------------------------------------

export function getABTests(): Promise<{ tests: Record<string, unknown>[] }> {
  return fetchAPI("/api/evolution/ab-tests");
}

export interface FitnessTrajectoryEntry {
  fitness: number;
  vector: Record<string, number>;
  event: string;
  timestamp: string;
}

export function getEvolutionFitness(methodologyId: string): Promise<{ methodology_id: string; trajectory: FitnessTrajectoryEntry[] }> {
  return fetchAPI(`/api/evolution/fitness/${methodologyId}`);
}

export interface RoutingEntry {
  agent_id: string;
  task_type: string;
  wins: number;
  losses: number;
  total: number;
  avg_quality: number;
  avg_cost: number;
}

export function getRouting(): Promise<{ routing: RoutingEntry[] }> {
  return fetchAPI("/api/evolution/routing");
}

export interface BanditArm {
  methodology_id: string;
  task_type: string;
  successes: number;
  failures: number;
  total: number;
  win_rate: number;
  last_updated: string;
}

export function getBanditArms(taskType?: string): Promise<{ arms: BanditArm[]; task_types: string[] }> {
  const params = taskType ? `?task_type=${encodeURIComponent(taskType)}` : "";
  return fetchAPI(`/api/evolution/bandit${params}`);
}

// ---------------------------------------------------------------------------
// Costs
// ---------------------------------------------------------------------------

export interface CostSummary {
  mining_costs: Array<{
    model_used: string;
    agent_id: string;
    brain: string;
    runs: number;
    total_tokens: number;
    successes: number;
    avg_duration: number;
  }>;
  agent_budgets: Record<string, { max_budget_usd: number; model: string | null; mode: string }>;
}

export function getCostsSummary(): Promise<CostSummary> {
  return fetchAPI("/api/costs/summary");
}

export function getCostsByAgent(): Promise<{
  mining: Array<Record<string, unknown>>;
  task_execution: Array<Record<string, unknown>>;
}> {
  return fetchAPI("/api/costs/by-agent");
}

// ---------------------------------------------------------------------------
// Federation
// ---------------------------------------------------------------------------

export interface TopologyNode {
  id: string;
  type: "primary" | "sibling";
  methodology_count: number;
  db_exists: boolean;
  description?: string;
}

export interface TopologyEdge {
  source: string;
  target: string;
  type: string;
}

export function getFederationTopology(): Promise<{
  nodes: TopologyNode[];
  edges: TopologyEdge[];
  total_methodologies: number;
}> {
  return fetchAPI("/api/federation/topology");
}

export interface CrossLanguageReport {
  query: string;
  universal_patterns: Array<{
    pattern_name: string;
    implementations: Record<string, string>;
    evidence_ids: string[];
    domain_overlap: number;
  }>;
  unique_innovations: Array<{
    brain: string;
    methodology_id: string;
    problem_summary: string;
    why_unique: string;
  }>;
  transferable_insights: Array<{
    source_brain: string;
    target_brain: string;
    rationale: string;
  }>;
  metrics: Record<string, unknown>;
}

export function analyzeFederation(query: string): Promise<CrossLanguageReport> {
  return fetchAPI("/api/federation/analyze", {
    method: "POST",
    body: JSON.stringify({ query }),
  });
}

// ---------------------------------------------------------------------------
// Mining
// ---------------------------------------------------------------------------

export function startMining(path: string, brain?: string): Promise<{ job_id: string; status: string }> {
  return fetchAPI("/api/mine", {
    method: "POST",
    body: JSON.stringify({ path, brain }),
  });
}

export function getMiningStatus(jobId: string): Promise<Record<string, unknown>> {
  return fetchAPI(`/api/mine/${jobId}`);
}

export function getRecentMining(): Promise<{ outcomes: Array<Record<string, unknown>> }> {
  return fetchAPI("/api/mine/recent/list");
}

// ---------------------------------------------------------------------------
// Brain Intelligence (Forge)
// ---------------------------------------------------------------------------

export interface BrainGraphNode {
  id: string;
  name: string;
  methodology_count: number;
  categories: Record<string, number>;
  top_methodologies: Array<{ title: string; category: string; fitness: number }>;
  fitness_summary: { avg: number; min: number; max: number };
  is_primary: boolean;
  db_exists?: boolean;
}

export interface BrainGraphEdge {
  source: string;
  target: string;
  type: string;
}

export function getBrainGraph(): Promise<{ nodes: BrainGraphNode[]; edges: BrainGraphEdge[] }> {
  return fetchAPI("/api/brain/graph");
}

export interface BanditArmState {
  methodology_id: string;
  title: string;
  alpha: number;
  beta: number;
  mean: number;
  ci_low: number;
  ci_high: number;
  successes: number;
  failures: number;
  total: number;
  task_types: string[];
}

export function getBrainBanditState(taskType?: string): Promise<{ arms: BanditArmState[]; count: number }> {
  const params = taskType ? `?task_type=${encodeURIComponent(taskType)}` : "";
  return fetchAPI(`/api/brain/bandit-state${params}`);
}

export interface CapabilityBoundaries {
  hard_tasks: Array<{ task_type: string; agents_tried: number; avg_failure_rate: number }>;
  failing_methodologies: Array<{ methodology_id: string; title: string; category: string | null; failures: number }>;
  coverage_gaps: Array<{ category: string; brain?: string; count?: number }>;
}

export function getCapabilityBoundaries(): Promise<CapabilityBoundaries> {
  return fetchAPI("/api/brain/capability-boundaries");
}

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

export function getConfig(): Promise<Record<string, unknown>> {
  return fetchAPI("/api/config");
}

export function patchConfig(section: string, update: Record<string, unknown>): Promise<Record<string, unknown>> {
  return fetchAPI(`/api/config/${section}`, {
    method: "PATCH",
    body: JSON.stringify(update),
  });
}

export function reloadConfig(): Promise<{ status: string }> {
  return fetchAPI("/api/config/reload", { method: "POST" });
}

// ---------------------------------------------------------------------------
// Prompts
// ---------------------------------------------------------------------------

export interface PromptInfo {
  name: string;
  path: string;
  size_bytes: number;
  line_count: number;
}

export function getPrompts(): Promise<{ prompts: PromptInfo[] }> {
  return fetchAPI("/api/prompts");
}

export function getPrompt(name: string): Promise<{ name: string; content: string; path: string }> {
  return fetchAPI(`/api/prompts/${encodeURIComponent(name)}`);
}

export function createPrompt(name: string, content: string, forkFrom?: string): Promise<Record<string, unknown>> {
  const body: Record<string, string> = { name, content };
  if (forkFrom) body.fork_from = forkFrom;
  return fetchAPI("/api/prompts", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------------
// Ganglia (Brain CRUD)
// ---------------------------------------------------------------------------

export function createGanglion(name: string, description?: string, promptTemplate?: string): Promise<Record<string, unknown>> {
  return fetchAPI("/api/ganglia", {
    method: "POST",
    body: JSON.stringify({ name, description, prompt_template: promptTemplate }),
  });
}

export function deleteGanglion(name: string): Promise<Record<string, unknown>> {
  return fetchAPI(`/api/ganglia/${encodeURIComponent(name)}`, { method: "DELETE" });
}

export function previewRepo(path: string): Promise<Record<string, unknown>> {
  return fetchAPI("/api/forge/preview-repo", {
    method: "POST",
    body: JSON.stringify({ path }),
  });
}

export function validateForge(brainName: string, agentIds: string[], repoPaths: string[]): Promise<Record<string, unknown>> {
  return fetchAPI("/api/forge/validate", {
    method: "POST",
    body: JSON.stringify({ brain_name: brainName, agent_ids: agentIds, repo_paths: repoPaths }),
  });
}

// ---------------------------------------------------------------------------
// Forge Execution (Phase 5)
// ---------------------------------------------------------------------------

export function analyzeIntent(intent: string, repoPath?: string): Promise<Record<string, unknown>> {
  return fetchAPI("/api/forge/analyze-intent", {
    method: "POST",
    body: JSON.stringify({ intent, repo_path: repoPath }),
  });
}

export function executeForge(steps: Array<Record<string, unknown>>): Promise<{ job_id: string; status: string }> {
  return fetchAPI("/api/forge/execute", {
    method: "POST",
    body: JSON.stringify({ steps }),
  });
}

export function getForgeJobStatus(jobId: string): Promise<Record<string, unknown>> {
  return fetchAPI(`/api/forge/execute/${jobId}`);
}

export function generateScript(operations: string[]): Promise<{ script: string; filename: string; description: string }> {
  return fetchAPI("/api/forge/generate-script", {
    method: "POST",
    body: JSON.stringify({ operations }),
  });
}

// ---------------------------------------------------------------------------
// Playground — Task Execution (MicroClaw)
// ---------------------------------------------------------------------------

export interface GateResult {
  check: string;
  status: "pass" | "fail";
  detail: string;
}

export interface StepEvent {
  step: string;
  detail: string;
  timestamp: string;
}

export interface CorrectionEntry {
  attempt_number: number;
  violations: Array<{ check: string; detail: string }>;
  test_output: string;
  code_diff: string;
  failing_test_content: string;
  quality_score: number;
  failure_reason: string | null;
}

export interface ExecutionResult {
  cycle_level: string;
  task_id: string | null;
  project_id: string | null;
  agent_id: string | null;
  success: boolean;
  tokens_used: number;
  cost_usd: number;
  duration_seconds: number;
  outcome: {
    files_changed: string[];
    test_output: string;
    tests_passed: boolean;
    diff: string;
    approach_summary: string;
    model_used: string | null;
    agent_id: string | null;
    failure_reason: string | null;
    failure_detail: string | null;
    tokens_used: number;
    cost_usd: number;
    duration_seconds: number;
  };
  verification: {
    approved: boolean;
    violations: Array<{ check: string; detail: string }>;
    recommendations: string[];
    quality_score: number | null;
    tests_before: number | null;
    tests_after: number | null;
    test_output: string;
    drift_cosine_score: number | null;
  } | null;
}

export interface SessionStatus {
  session_id: string;
  status: "starting" | "running" | "completed" | "failed" | "error";
  task_description: string;
  steps: StepEvent[];
  gates: GateResult[];
  corrections_count: number;
  result: ExecutionResult | null;
  error: string | null;
  created_at: string;
}

export interface SessionCorrections {
  session_id: string;
  corrections: CorrectionEntry[];
  total_attempts: number;
}

export function executeTask(
  taskDescription: string,
  projectId?: string,
  workspaceDir?: string,
): Promise<{ session_id: string; status: string }> {
  return fetchAPI("/api/execute", {
    method: "POST",
    body: JSON.stringify({
      task_description: taskDescription,
      project_id: projectId,
      workspace_dir: workspaceDir,
    }),
  });
}

export function getSessionStatus(sessionId: string): Promise<SessionStatus> {
  return fetchAPI(`/api/sessions/${sessionId}`);
}

export function getSessionCorrections(sessionId: string): Promise<SessionCorrections> {
  return fetchAPI(`/api/sessions/${sessionId}/corrections`);
}
