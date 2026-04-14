"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  BarChart,
  Bar,
  Cell,
} from "recharts";
import {
  getMethodology,
  getMethodologyFitness,
  type Methodology,
  type FitnessEntry,
} from "@/lib/api";
import { Card, CardTitle } from "@/components/card";
import { LifecycleBadge, LangBadge } from "@/components/badge";
import { Skeleton, SkeletonCard, SkeletonGrid } from "@/components/skeleton";
import { ErrorBanner } from "@/components/error-banner";

// ---------------------------------------------------------------------------
// Dimension colors for the fitness vector bar chart
// ---------------------------------------------------------------------------
const DIMENSION_COLORS = [
  "#ff6b3d", // accent
  "#58a6ff", // blue
  "#7ee787", // green
  "#d2a8ff", // purple
  "#f0883e", // orange
  "#f778ba", // pink
  "#79c0ff", // light blue
  "#ffa657", // light orange
  "#a5d6ff", // pale blue
  "#56d364", // bright green
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

function shortDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

function scoreColor(value: number | null): string {
  if (value === null) return "text-muted";
  if (value >= 0.7) return "text-cam-green";
  if (value >= 0.4) return "text-yellow-400";
  return "text-red-400";
}

// ---------------------------------------------------------------------------
// Stat tile sub-component
// ---------------------------------------------------------------------------

function StatTile({
  label,
  value,
  colorClass,
}: {
  label: string;
  value: string | number;
  colorClass?: string;
}) {
  return (
    <div className="bg-card border border-card-border rounded-lg p-4">
      <div className="text-xs text-muted uppercase tracking-wider mb-1">{label}</div>
      <div className={`text-lg font-bold ${colorClass || "text-foreground"}`}>
        {typeof value === "number" ? value.toLocaleString() : value}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Custom recharts tooltip
// ---------------------------------------------------------------------------

function FitnessTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ value: number; name: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-card border border-card-border rounded-lg px-3 py-2 text-xs shadow-lg">
      <div className="text-muted mb-1">{label}</div>
      {payload.map((entry, i) => (
        <div key={i} className="text-foreground font-medium">
          {entry.name}: {entry.value.toFixed(3)}
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page component
// ---------------------------------------------------------------------------

export default function MethodologyDetailPage() {
  const params = useParams();
  const id = params.id as string;

  const [methodology, setMethodology] = useState<Methodology | null>(null);
  const [fitness, setFitness] = useState<FitnessEntry[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const loadData = useCallback(() => {
    if (!id) return;

    setLoading(true);
    setError(null);

    Promise.all([
      getMethodology(id),
      getMethodologyFitness(id).catch(() => ({ methodology_id: id, entries: [] })),
    ])
      .then(([meth, fit]) => {
        setMethodology(meth);
        setFitness(fit.entries);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData();
    }, 0);
    return () => clearTimeout(timer);
  }, [loadData]);

  // -- Loading / Error states -----------------------------------------------

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-3 w-64" />
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonGrid count={4} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8">
        <Link href="/knowledge" className="text-accent hover:text-accent-hover text-sm mb-4 inline-block">
          &larr; Back to Knowledge
        </Link>
        <div className="mt-4">
          <ErrorBanner
            message="Failed to load methodology"
            detail={error}
            onRetry={() => { setError(null); loadData(); }}
          />
        </div>
      </div>
    );
  }

  if (!methodology) {
    return (
      <div className="p-8">
        <Link href="/knowledge" className="text-accent hover:text-accent-hover text-sm mb-4 inline-block">
          &larr; Back to Knowledge
        </Link>
        <div className="text-muted mt-4">Methodology not found.</div>
      </div>
    );
  }

  // -- Derived data ---------------------------------------------------------

  const successRate =
    methodology.retrieval_count > 0
      ? ((methodology.success_count / methodology.retrieval_count) * 100).toFixed(1)
      : "N/A";

  // Fitness chart data: sorted chronologically
  const fitnessChartData = fitness
    .slice()
    .sort((a, b) => new Date(a.created_at).getTime() - new Date(b.created_at).getTime())
    .map((entry) => ({
      date: shortDate(entry.created_at),
      fitness_total: parseFloat(entry.fitness_total.toFixed(3)),
      trigger: entry.trigger_event,
    }));

  // Latest fitness vector for the horizontal bar chart
  const latestVector =
    fitness.length > 0
      ? fitness
          .slice()
          .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())[0]
          .fitness_vector
      : null;

  const vectorBarData = latestVector
    ? Object.entries(latestVector)
        .map(([dimension, value]) => ({ dimension, value: parseFloat(value.toFixed(3)) }))
        .sort((a, b) => b.value - a.value)
    : [];

  // -- Render ---------------------------------------------------------------

  return (
    <div>
      {/* Back link */}
      <Link
        href="/knowledge"
        className="text-accent hover:text-accent-hover text-sm mb-6 inline-flex items-center gap-1 transition-colors"
      >
        &larr; Back to Knowledge
      </Link>

      {/* Header row: type + badges */}
      <div className="flex flex-wrap items-center gap-3 mb-2 mt-2">
        <span className="text-xs text-muted uppercase tracking-wider font-semibold">
          {methodology.methodology_type}
        </span>
        <LifecycleBadge state={methodology.lifecycle_state} />
        <LangBadge lang={methodology.language} />
      </div>

      {/* ID */}
      <div className="text-xs text-muted-dark font-mono mb-6 select-all">{methodology.id}</div>

      {/* ------------------------------------------------------------------ */}
      {/* Problem Description                                                */}
      {/* ------------------------------------------------------------------ */}
      <Card className="mb-6">
        <CardTitle>Problem Description</CardTitle>
        <p className="text-foreground leading-relaxed whitespace-pre-wrap">
          {methodology.problem_description}
        </p>
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* Solution Code                                                      */}
      {/* ------------------------------------------------------------------ */}
      <Card className="mb-6">
        <CardTitle>Solution</CardTitle>
        <div className="rounded-lg overflow-hidden">
          <pre className="bg-[#0d1117] border border-card-border rounded-lg p-4 overflow-x-auto text-sm leading-relaxed">
            <code className="text-cam-green font-mono">{methodology.solution_code}</code>
          </pre>
        </div>
      </Card>

      {/* ------------------------------------------------------------------ */}
      {/* Methodology Notes                                                  */}
      {/* ------------------------------------------------------------------ */}
      {methodology.methodology_notes && (
        <Card className="mb-6">
          <CardTitle>Methodology Notes</CardTitle>
          <p className="text-foreground/80 leading-relaxed whitespace-pre-wrap">
            {methodology.methodology_notes}
          </p>
        </Card>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Tags                                                               */}
      {/* ------------------------------------------------------------------ */}
      {methodology.tags.length > 0 && (
        <Card className="mb-6">
          <CardTitle>Tags</CardTitle>
          <div className="flex flex-wrap gap-2">
            {methodology.tags.map((tag) => (
              <span
                key={tag}
                className="inline-block px-3 py-1 bg-card-border rounded-full text-xs text-foreground"
              >
                {tag}
              </span>
            ))}
          </div>
        </Card>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Files Affected                                                     */}
      {/* ------------------------------------------------------------------ */}
      {methodology.files_affected && (
        <Card className="mb-6">
          <CardTitle>Files Affected</CardTitle>
          <p className="text-foreground/80 text-sm font-mono whitespace-pre-wrap">
            {methodology.files_affected}
          </p>
        </Card>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Stats Grid                                                         */}
      {/* ------------------------------------------------------------------ */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <StatTile label="Lifecycle" value={methodology.lifecycle_state} />
        <StatTile label="Language" value={methodology.language || "unknown"} />
        <StatTile
          label="Novelty Score"
          value={methodology.novelty_score !== null ? methodology.novelty_score.toFixed(2) : "N/A"}
          colorClass={scoreColor(methodology.novelty_score)}
        />
        <StatTile
          label="Potential Score"
          value={methodology.potential_score !== null ? methodology.potential_score.toFixed(2) : "N/A"}
          colorClass={scoreColor(methodology.potential_score)}
        />
        <StatTile label="Retrievals" value={methodology.retrieval_count} />
        <StatTile
          label="Successes"
          value={methodology.success_count}
          colorClass="text-cam-green"
        />
        <StatTile
          label="Failures"
          value={methodology.failure_count}
          colorClass={methodology.failure_count > 0 ? "text-red-400" : "text-foreground"}
        />
        <StatTile label="Success Rate" value={successRate === "N/A" ? "N/A" : `${successRate}%`} />
      </div>

      {/* Created date */}
      <div className="text-xs text-muted mb-8">
        Created {formatDate(methodology.created_at)}
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Fitness Total Over Time (Line Chart)                               */}
      {/* ------------------------------------------------------------------ */}
      {fitnessChartData.length > 0 && (
        <Card className="mb-6">
          <CardTitle>Fitness Trajectory</CardTitle>
          <div className="h-64 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={fitnessChartData}>
                <XAxis
                  dataKey="date"
                  tick={{ fill: "#8b949e", fontSize: 11 }}
                  axisLine={{ stroke: "#21262d" }}
                  tickLine={false}
                />
                <YAxis
                  tick={{ fill: "#8b949e", fontSize: 11 }}
                  axisLine={{ stroke: "#21262d" }}
                  tickLine={false}
                  domain={["auto", "auto"]}
                />
                <Tooltip content={<FitnessTooltip />} />
                <Line
                  type="monotone"
                  dataKey="fitness_total"
                  name="Fitness"
                  stroke="#ff6b3d"
                  strokeWidth={2}
                  dot={{ fill: "#ff6b3d", r: 3 }}
                  activeDot={{ r: 5, fill: "#ff8552" }}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
          {/* Event annotations */}
          <div className="mt-3 flex flex-wrap gap-2">
            {fitnessChartData.map((d, i) => (
              <span key={i} className="text-xs text-muted-dark">
                {d.date}: {d.trigger}
              </span>
            ))}
          </div>
        </Card>
      )}

      {/* ------------------------------------------------------------------ */}
      {/* Fitness Vector Breakdown (Horizontal Bar Chart)                    */}
      {/* ------------------------------------------------------------------ */}
      {vectorBarData.length > 0 && (
        <Card className="mb-6">
          <CardTitle>Fitness Vector Breakdown (Latest)</CardTitle>
          <div className="h-64 mt-2">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={vectorBarData}
                layout="vertical"
                margin={{ left: 20, right: 20, top: 5, bottom: 5 }}
              >
                <XAxis
                  type="number"
                  tick={{ fill: "#8b949e", fontSize: 11 }}
                  axisLine={{ stroke: "#21262d" }}
                  tickLine={false}
                  domain={[0, "auto"]}
                />
                <YAxis
                  type="category"
                  dataKey="dimension"
                  tick={{ fill: "#c9d1d9", fontSize: 11 }}
                  axisLine={{ stroke: "#21262d" }}
                  tickLine={false}
                  width={120}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#161b22",
                    border: "1px solid #21262d",
                    borderRadius: 8,
                    fontSize: 12,
                    color: "#c9d1d9",
                  }}
                />
                <Bar dataKey="value" name="Score" radius={[0, 4, 4, 0]}>
                  {vectorBarData.map((_, index) => (
                    <Cell
                      key={index}
                      fill={DIMENSION_COLORS[index % DIMENSION_COLORS.length]}
                    />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Card>
      )}

      {/* Empty state for fitness */}
      {fitnessChartData.length === 0 && (
        <Card className="mb-6">
          <CardTitle>Fitness History</CardTitle>
          <p className="text-muted text-sm">No fitness entries recorded yet for this methodology.</p>
        </Card>
      )}
    </div>
  );
}
