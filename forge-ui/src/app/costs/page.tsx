"use client";

import { useEffect, useState, useCallback } from "react";
import {
  getCostsSummary,
  getCostsByAgent,
  type CostSummary,
} from "@/lib/api";
import { Card, CardTitle } from "@/components/card";
import { GanglionBadge } from "@/components/badge";
import { Skeleton, SkeletonGrid } from "@/components/skeleton";
import { ErrorBanner } from "@/components/error-banner";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Cell,
} from "recharts";

// ---------------------------------------------------------------------------
// Types for by-agent data
// ---------------------------------------------------------------------------

interface AgentMiningRow {
  agent_id: string;
  model_used: string;
  runs: number;
  total_tokens: number;
  successes: number;
}

interface AgentTaskRow {
  agent_id: string;
  task_type: string;
  wins: number;
  avg_quality: number;
  total_cost_usd: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function formatDuration(seconds: number): string {
  if (seconds >= 60) return `${(seconds / 60).toFixed(1)}m`;
  return `${seconds.toFixed(1)}s`;
}

function formatUsd(n: number): string {
  if (n >= 1) return `$${n.toFixed(2)}`;
  if (n >= 0.01) return `$${n.toFixed(3)}`;
  if (n > 0) return `$${n.toFixed(4)}`;
  return "$0.00";
}

function clamp(v: number, min: number, max: number): number {
  return Math.min(Math.max(v, min), max);
}

const BAR_COLORS = [
  "#ff6b3d",
  "#58a6ff",
  "#7ee787",
  "#d2a8ff",
  "#f0883e",
  "#3fb950",
  "#79c0ff",
  "#f778ba",
];

/** Aggregate spend per agent from the task execution rows */
function aggregateSpendByAgent(
  taskRows: AgentTaskRow[],
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const r of taskRows) {
    out[r.agent_id] = (out[r.agent_id] || 0) + (r.total_cost_usd ?? 0);
  }
  return out;
}

/** Aggregate tokens per agent from the mining rows */
function aggregateTokensByAgent(
  miningRows: AgentMiningRow[],
): Record<string, { tokens: number; runs: number; successes: number }> {
  const out: Record<string, { tokens: number; runs: number; successes: number }> = {};
  for (const r of miningRows) {
    const prev = out[r.agent_id] || { tokens: 0, runs: 0, successes: 0 };
    out[r.agent_id] = {
      tokens: prev.tokens + (r.total_tokens ?? 0),
      runs: prev.runs + (r.runs ?? 0),
      successes: prev.successes + (r.successes ?? 0),
    };
  }
  return out;
}

// ---------------------------------------------------------------------------
// Custom tooltip for recharts
// ---------------------------------------------------------------------------

function TokenTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ value: number }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-card border border-card-border rounded-lg px-3 py-2 text-xs shadow-lg">
      <div className="text-foreground font-medium mb-1">{label}</div>
      <div className="text-muted">
        Tokens: <span className="text-accent font-mono">{payload[0].value.toLocaleString()}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Progress bar component
// ---------------------------------------------------------------------------

function UtilizationBar({
  percent,
  label,
}: {
  percent: number;
  label: string;
}) {
  const clamped = clamp(percent, 0, 100);
  // Color thresholds: green < 60%, accent/orange 60-85%, red > 85%
  let barColor = "bg-cam-green";
  if (clamped > 85) barColor = "bg-red-500";
  else if (clamped > 60) barColor = "bg-accent";

  return (
    <div className="w-full">
      <div className="flex items-center justify-between text-xs mb-1">
        <span className="text-muted">{label}</span>
        <span className="text-foreground font-mono font-medium">
          {percent.toFixed(1)}%
        </span>
      </div>
      <div className="h-2.5 w-full bg-card-hover rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-500 ${barColor}`}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Budget Utilization Section
// ---------------------------------------------------------------------------

function BudgetUtilization({
  budgets,
  spendByAgent,
}: {
  budgets: CostSummary["agent_budgets"];
  spendByAgent: Record<string, number>;
}) {
  // Only show agents that have a budget configured
  const entries = Object.entries(budgets)
    .filter(([, info]) => info.max_budget_usd > 0)
    .sort(([, a], [, b]) => b.max_budget_usd - a.max_budget_usd);

  if (entries.length === 0) return null;

  const totalBudget = entries.reduce((s, [, v]) => s + v.max_budget_usd, 0);
  const totalSpend = Object.values(spendByAgent).reduce((s, v) => s + v, 0);
  const overallPercent = totalBudget > 0 ? (totalSpend / totalBudget) * 100 : 0;

  return (
    <section>
      <h2 className="text-lg font-semibold text-foreground mb-4">
        Budget Utilization
      </h2>

      {/* Overall summary bar */}
      <Card className="mb-4">
        <div className="flex items-center justify-between mb-2">
          <div>
            <span className="text-sm font-medium text-foreground">Overall Fleet Budget</span>
            <span className="text-xs text-muted ml-3">
              {formatUsd(totalSpend)} of {formatUsd(totalBudget)}
            </span>
          </div>
          <span
            className={`text-xs px-2 py-0.5 rounded-full font-medium ${
              overallPercent > 85
                ? "bg-red-500/10 text-red-400"
                : overallPercent > 60
                  ? "bg-accent/10 text-accent"
                  : "bg-cam-green/10 text-cam-green"
            }`}
          >
            {overallPercent.toFixed(1)}% used
          </span>
        </div>
        <UtilizationBar percent={overallPercent} label="" />
      </Card>

      {/* Per-agent utilization */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {entries.map(([agentId, info]) => {
          const spent = spendByAgent[agentId] ?? 0;
          const percent = info.max_budget_usd > 0 ? (spent / info.max_budget_usd) * 100 : 0;

          return (
            <Card key={agentId}>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-foreground truncate max-w-[60%]">
                  {agentId}
                </span>
                <span
                  className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    info.mode === "local"
                      ? "bg-cam-green/10 text-cam-green"
                      : "bg-cam-blue/10 text-cam-blue"
                  }`}
                >
                  {info.mode}
                </span>
              </div>

              {/* Budget amounts */}
              <div className="flex items-baseline gap-2 mb-3">
                <span className="text-lg font-bold text-foreground font-mono">
                  {formatUsd(spent)}
                </span>
                <span className="text-xs text-muted">
                  / {formatUsd(info.max_budget_usd)}
                </span>
              </div>

              {/* Utilization bar */}
              <UtilizationBar percent={percent} label="budget used" />

              {/* Model info */}
              {info.model && (
                <div className="text-xs text-muted-dark mt-3 font-mono truncate">
                  {info.model}
                </div>
              )}
            </Card>
          );
        })}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Agent Spend Summary Cards
// ---------------------------------------------------------------------------

function AgentSpendSummary({
  budgets,
  spendByAgent,
  tokensByAgent,
}: {
  budgets: CostSummary["agent_budgets"];
  spendByAgent: Record<string, number>;
  tokensByAgent: Record<string, { tokens: number; runs: number; successes: number }>;
}) {
  // Merge all agent IDs from budgets, spend, and token data
  const allAgentIds = new Set([
    ...Object.keys(budgets),
    ...Object.keys(spendByAgent),
    ...Object.keys(tokensByAgent),
  ]);

  const agentSummaries = Array.from(allAgentIds)
    .map((agentId) => {
      const budget = budgets[agentId];
      const spent = spendByAgent[agentId] ?? 0;
      const tokenInfo = tokensByAgent[agentId] ?? { tokens: 0, runs: 0, successes: 0 };
      const costPer1kTokens =
        tokenInfo.tokens > 0 ? (spent / tokenInfo.tokens) * 1000 : 0;
      const successRate =
        tokenInfo.runs > 0
          ? (tokenInfo.successes / tokenInfo.runs) * 100
          : 0;

      return {
        agentId,
        mode: budget?.mode ?? "unknown",
        totalCost: spent,
        totalTokens: tokenInfo.tokens,
        totalRuns: tokenInfo.runs,
        successes: tokenInfo.successes,
        costPer1kTokens,
        successRate,
      };
    })
    .filter((a) => a.totalTokens > 0 || a.totalCost > 0)
    .sort((a, b) => b.totalTokens - a.totalTokens);

  if (agentSummaries.length === 0) return null;

  return (
    <section>
      <h2 className="text-lg font-semibold text-foreground mb-4">
        Agent Spend Summary
      </h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {agentSummaries.map((agent) => (
          <Card key={agent.agentId}>
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium text-foreground truncate max-w-[70%]">
                {agent.agentId}
              </span>
              <span
                className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                  agent.mode === "local"
                    ? "bg-cam-green/10 text-cam-green"
                    : "bg-cam-blue/10 text-cam-blue"
                }`}
              >
                {agent.mode}
              </span>
            </div>

            {/* Metric grid */}
            <div className="grid grid-cols-2 gap-x-4 gap-y-2">
              {/* Total Cost */}
              <div>
                <div className="text-xs text-muted">Total Cost</div>
                <div className="text-sm font-bold text-accent font-mono">
                  {formatUsd(agent.totalCost)}
                </div>
              </div>

              {/* Total Tokens */}
              <div>
                <div className="text-xs text-muted">Total Tokens</div>
                <div className="text-sm font-bold text-cam-blue font-mono">
                  {formatTokens(agent.totalTokens)}
                </div>
              </div>

              {/* Cost Efficiency */}
              <div>
                <div className="text-xs text-muted">Cost / 1K tokens</div>
                <div className="text-sm font-medium text-foreground font-mono">
                  {agent.costPer1kTokens > 0
                    ? formatUsd(agent.costPer1kTokens)
                    : "--"}
                </div>
              </div>

              {/* Success Rate */}
              <div>
                <div className="text-xs text-muted">Success Rate</div>
                <div
                  className={`text-sm font-medium font-mono ${
                    agent.successRate >= 80
                      ? "text-cam-green"
                      : agent.successRate >= 50
                        ? "text-accent"
                        : "text-muted"
                  }`}
                >
                  {agent.totalRuns > 0
                    ? `${agent.successRate.toFixed(1)}%`
                    : "--"}
                </div>
              </div>

              {/* Runs */}
              <div>
                <div className="text-xs text-muted">Runs</div>
                <div className="text-sm font-medium text-foreground">
                  {agent.totalRuns.toLocaleString()}
                </div>
              </div>

              {/* Successes */}
              <div>
                <div className="text-xs text-muted">Successes</div>
                <div className="text-sm font-medium text-cam-green">
                  {agent.successes.toLocaleString()}
                </div>
              </div>
            </div>
          </Card>
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Existing Sub-components (preserved)
// ---------------------------------------------------------------------------

function MiningCostsTable({
  costs,
}: {
  costs: CostSummary["mining_costs"];
}) {
  if (!costs.length) {
    return (
      <Card>
        <CardTitle>Mining Costs</CardTitle>
        <p className="text-muted text-sm">No mining cost data available.</p>
      </Card>
    );
  }

  return (
    <Card>
      <CardTitle>Mining Costs</CardTitle>
      <div className="overflow-x-auto -mx-5 px-5">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-card-border text-left">
              <th className="pb-2 pr-4 text-muted font-medium">Model</th>
              <th className="pb-2 pr-4 text-muted font-medium">Agent</th>
              <th className="pb-2 pr-4 text-muted font-medium">Brain</th>
              <th className="pb-2 pr-4 text-muted font-medium text-right">Runs</th>
              <th className="pb-2 pr-4 text-muted font-medium text-right">Tokens</th>
              <th className="pb-2 pr-4 text-muted font-medium text-right">Successes</th>
              <th className="pb-2 text-muted font-medium text-right">Avg Duration</th>
            </tr>
          </thead>
          <tbody>
            {costs.map((row, i) => (
              <tr
                key={`${row.model_used}-${row.agent_id}-${row.brain}-${i}`}
                className="border-b border-card-border/50 hover:bg-card-hover/30 transition-colors"
              >
                <td className="py-2.5 pr-4 font-mono text-xs text-foreground">
                  {row.model_used}
                </td>
                <td className="py-2.5 pr-4 text-foreground">{row.agent_id}</td>
                <td className="py-2.5 pr-4">
                  <GanglionBadge name={row.brain} />
                </td>
                <td className="py-2.5 pr-4 text-right text-foreground">
                  {row.runs.toLocaleString()}
                </td>
                <td className="py-2.5 pr-4 text-right font-mono text-cam-blue">
                  {formatTokens(row.total_tokens)}
                </td>
                <td className="py-2.5 pr-4 text-right">
                  <span
                    className={
                      row.successes > 0 ? "text-cam-green" : "text-muted"
                    }
                  >
                    {row.successes.toLocaleString()}
                  </span>
                </td>
                <td className="py-2.5 text-right text-muted">
                  {formatDuration(row.avg_duration)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

function TokenBarChart({ costs }: { costs: CostSummary["mining_costs"] }) {
  // Aggregate tokens by model
  const byModel: Record<string, number> = {};
  for (const row of costs) {
    byModel[row.model_used] = (byModel[row.model_used] || 0) + row.total_tokens;
  }

  const data = Object.entries(byModel)
    .map(([model, tokens]) => ({ model, tokens }))
    .sort((a, b) => b.tokens - a.tokens);

  if (!data.length) return null;

  return (
    <Card>
      <CardTitle>Token Usage by Model</CardTitle>
      <div className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 40, left: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#21262d" />
            <XAxis
              dataKey="model"
              tick={{ fill: "#8b949e", fontSize: 11 }}
              angle={-30}
              textAnchor="end"
              height={60}
              stroke="#21262d"
            />
            <YAxis
              tick={{ fill: "#8b949e", fontSize: 11 }}
              tickFormatter={(v: number) => formatTokens(v)}
              stroke="#21262d"
            />
            <Tooltip content={<TokenTooltip />} />
            <Bar dataKey="tokens" radius={[4, 4, 0, 0]} maxBarSize={48}>
              {data.map((_, idx) => (
                <Cell
                  key={idx}
                  fill={BAR_COLORS[idx % BAR_COLORS.length]}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}

function AgentBreakdown({
  mining,
  taskExecution,
}: {
  mining: Array<Record<string, unknown>>;
  taskExecution: Array<Record<string, unknown>>;
}) {
  return (
    <section>
      <h2 className="text-lg font-semibold text-foreground mb-4">
        Per-Agent Breakdown
      </h2>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Mining stats */}
        <Card>
          <CardTitle>Mining Stats by Agent</CardTitle>
          {mining.length === 0 ? (
            <p className="text-muted text-sm">No mining data.</p>
          ) : (
            <div className="overflow-x-auto -mx-5 px-5">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-card-border text-left">
                    {Object.keys(mining[0]).map((key) => (
                      <th
                        key={key}
                        className="pb-2 pr-3 text-muted font-medium text-xs"
                      >
                        {key.replace(/_/g, " ")}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {mining.map((row, i) => (
                    <tr
                      key={i}
                      className="border-b border-card-border/50 hover:bg-card-hover/30 transition-colors"
                    >
                      {Object.values(row).map((val, j) => (
                        <td
                          key={j}
                          className="py-2 pr-3 text-xs text-foreground"
                        >
                          {typeof val === "number"
                            ? val.toLocaleString()
                            : String(val ?? "-")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {/* Task execution stats */}
        <Card>
          <CardTitle>Task Execution Stats by Agent</CardTitle>
          {taskExecution.length === 0 ? (
            <p className="text-muted text-sm">No task execution data.</p>
          ) : (
            <div className="overflow-x-auto -mx-5 px-5">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-card-border text-left">
                    {Object.keys(taskExecution[0]).map((key) => (
                      <th
                        key={key}
                        className="pb-2 pr-3 text-muted font-medium text-xs"
                      >
                        {key.replace(/_/g, " ")}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {taskExecution.map((row, i) => (
                    <tr
                      key={i}
                      className="border-b border-card-border/50 hover:bg-card-hover/30 transition-colors"
                    >
                      {Object.values(row).map((val, j) => (
                        <td
                          key={j}
                          className="py-2 pr-3 text-xs text-foreground"
                        >
                          {typeof val === "number"
                            ? val.toLocaleString()
                            : String(val ?? "-")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function CostsPage() {
  const [summary, setSummary] = useState<CostSummary | null>(null);
  const [byAgent, setByAgent] = useState<{
    mining: Array<Record<string, unknown>>;
    task_execution: Array<Record<string, unknown>>;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadData = useCallback(() => {
    Promise.all([getCostsSummary(), getCostsByAgent()])
      .then(([s, a]) => {
        setSummary(s);
        setByAgent(a);
      })
      .catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  if (error) {
    return (
      <ErrorBanner
        message="Failed to load cost data"
        detail={error}
        onRetry={() => { setError(null); loadData(); }}
      />
    );
  }

  if (!summary || !byAgent) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-72" />
        <SkeletonGrid count={4} />
        <SkeletonGrid count={4} />
      </div>
    );
  }

  // Totals for the header
  const totalTokens = summary.mining_costs.reduce(
    (acc, r) => acc + r.total_tokens,
    0
  );
  const totalRuns = summary.mining_costs.reduce(
    (acc, r) => acc + r.runs,
    0
  );
  const totalSuccesses = summary.mining_costs.reduce(
    (acc, r) => acc + r.successes,
    0
  );

  // Compute aggregated spend and token data from by-agent response
  const spendByAgent = aggregateSpendByAgent(
    byAgent.task_execution as unknown as AgentTaskRow[]
  );
  const tokensByAgent = aggregateTokensByAgent(
    byAgent.mining as unknown as AgentMiningRow[]
  );

  const totalSpendUsd = Object.values(spendByAgent).reduce((s, v) => s + v, 0);
  const totalBudgetUsd = Object.values(summary.agent_budgets).reduce(
    (s, v) => s + v.max_budget_usd,
    0,
  );

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-foreground">Cost Tracker</h1>
        <p className="text-muted mt-1">
          Token usage, agent budgets, spend efficiency, and mining cost breakdown
        </p>
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <Card>
          <div className="text-xs text-muted uppercase tracking-wider">
            Total Tokens
          </div>
          <div className="text-2xl font-bold text-accent mt-1 font-mono">
            {formatTokens(totalTokens)}
          </div>
        </Card>
        <Card>
          <div className="text-xs text-muted uppercase tracking-wider">
            Total Runs
          </div>
          <div className="text-2xl font-bold text-foreground mt-1">
            {totalRuns.toLocaleString()}
          </div>
        </Card>
        <Card>
          <div className="text-xs text-muted uppercase tracking-wider">
            Successes
          </div>
          <div className="text-2xl font-bold text-cam-green mt-1">
            {totalSuccesses.toLocaleString()}
          </div>
        </Card>
        <Card>
          <div className="text-xs text-muted uppercase tracking-wider">
            Total Spend
          </div>
          <div className="text-2xl font-bold text-accent mt-1 font-mono">
            {formatUsd(totalSpendUsd)}
          </div>
          {totalBudgetUsd > 0 && (
            <div className="text-xs text-muted mt-1">
              of {formatUsd(totalBudgetUsd)} budget
            </div>
          )}
        </Card>
        <Card>
          <div className="text-xs text-muted uppercase tracking-wider">
            Agents
          </div>
          <div className="text-2xl font-bold text-foreground mt-1">
            {Object.keys(summary.agent_budgets).length}
          </div>
        </Card>
      </div>

      {/* Budget utilization bars */}
      <BudgetUtilization
        budgets={summary.agent_budgets}
        spendByAgent={spendByAgent}
      />

      {/* Agent spend summary cards */}
      <AgentSpendSummary
        budgets={summary.agent_budgets}
        spendByAgent={spendByAgent}
        tokensByAgent={tokensByAgent}
      />

      {/* Token chart */}
      <TokenBarChart costs={summary.mining_costs} />

      {/* Mining costs table */}
      <MiningCostsTable costs={summary.mining_costs} />

      {/* Per-agent breakdown */}
      <AgentBreakdown
        mining={byAgent.mining}
        taskExecution={byAgent.task_execution}
      />
    </div>
  );
}
