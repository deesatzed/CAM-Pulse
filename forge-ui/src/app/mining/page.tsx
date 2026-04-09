"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Card, CardTitle } from "@/components/card";
import { Skeleton } from "@/components/skeleton";
import { ErrorBanner } from "@/components/error-banner";
import { startMining, getMiningStatus, getRecentMining } from "@/lib/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type JobStatus = "queued" | "running" | "completed" | "failed" | string;

interface ActiveJob {
  jobId: string;
  path: string;
  brain: string;
  status: JobStatus;
  details: Record<string, unknown>;
}

interface MiningOutcome {
  repo_name: string;
  brain: string;
  model_used: string;
  agent_id: string;
  strategy: string;
  success: boolean;
  findings_count: number;
  tokens_used: number;
  duration_seconds: number;
  created_at: string;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const BRAIN_OPTIONS = ["auto-detect", "python", "typescript", "go", "rust", "misc"] as const;

function statusColor(s: JobStatus): string {
  switch (s) {
    case "queued":    return "bg-yellow-500/15 text-yellow-400 border-yellow-500/40";
    case "running":   return "bg-cam-blue/15 text-cam-blue border-cam-blue/40";
    case "completed": return "bg-cam-green/15 text-cam-green border-cam-green/40";
    case "failed":    return "bg-red-500/15 text-red-400 border-red-500/40";
    default:          return "bg-card-border text-muted border-card-border";
  }
}

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function MiningPage() {
  // Form state
  const [path, setPath] = useState("");
  const [brain, setBrain] = useState<string>("auto-detect");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);

  // Active job state
  const [activeJob, setActiveJob] = useState<ActiveJob | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Recent outcomes
  const [outcomes, setOutcomes] = useState<MiningOutcome[]>([]);
  const [outcomesError, setOutcomesError] = useState<string | null>(null);
  const [outcomesLoading, setOutcomesLoading] = useState(true);

  // ---------------------------------------------------------------------------
  // Load recent outcomes
  // ---------------------------------------------------------------------------
  const loadOutcomes = useCallback(async () => {
    try {
      const data = await getRecentMining();
      const sorted = [...(data.outcomes || [])].sort((a, b) => {
        const ta = String(a.created_at ?? "");
        const tb = String(b.created_at ?? "");
        return tb.localeCompare(ta);
      }) as MiningOutcome[];
      setOutcomes(sorted);
      setOutcomesError(null);
    } catch (e: unknown) {
      setOutcomesError(e instanceof Error ? e.message : String(e));
    } finally {
      setOutcomesLoading(false);
    }
  }, []);

  useEffect(() => {
    loadOutcomes();
  }, [loadOutcomes]);

  // ---------------------------------------------------------------------------
  // Poll active job
  // ---------------------------------------------------------------------------
  const startPolling = useCallback(
    (jobId: string) => {
      if (pollRef.current) clearInterval(pollRef.current);

      pollRef.current = setInterval(async () => {
        try {
          const data = await getMiningStatus(jobId);
          const status = String(data.status ?? "unknown");
          setActiveJob((prev) =>
            prev ? { ...prev, status, details: data } : prev
          );

          if (status !== "queued" && status !== "running") {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            // Refresh outcomes table after job finishes
            loadOutcomes();
          }
        } catch {
          // Keep polling on transient errors
        }
      }, 2000);
    },
    [loadOutcomes]
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Submit
  // ---------------------------------------------------------------------------
  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!path.trim()) return;

    setSubmitting(true);
    setSubmitError(null);

    try {
      const brainArg = brain === "auto-detect" ? undefined : brain;
      const result = await startMining(path.trim(), brainArg);
      const newJob: ActiveJob = {
        jobId: result.job_id,
        path: path.trim(),
        brain,
        status: result.status || "queued",
        details: result as unknown as Record<string, unknown>,
      };
      setActiveJob(newJob);
      startPolling(result.job_id);
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <div>
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground">Mining Console</h1>
        <p className="text-muted mt-1">
          Launch repository mining jobs and monitor outcomes across all ganglia.
        </p>
      </div>

      {/* ---- Input Form ---- */}
      <Card className="mb-6">
        <CardTitle>Start Mining Job</CardTitle>
        <form onSubmit={handleSubmit} className="flex flex-col sm:flex-row gap-3">
          {/* Path input */}
          <input
            type="text"
            value={path}
            onChange={(e) => setPath(e.target.value)}
            placeholder="/absolute/path/to/repository"
            className="flex-1 rounded-lg border border-card-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-dark focus:outline-none focus:border-accent/60 focus:ring-1 focus:ring-accent/30 font-mono"
          />

          {/* Brain selector */}
          <select
            value={brain}
            onChange={(e) => setBrain(e.target.value)}
            className="rounded-lg border border-card-border bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:border-accent/60 focus:ring-1 focus:ring-accent/30 cursor-pointer"
          >
            {BRAIN_OPTIONS.map((opt) => (
              <option key={opt} value={opt}>
                {opt}
              </option>
            ))}
          </select>

          {/* Submit */}
          <button
            type="submit"
            disabled={submitting || !path.trim()}
            className="rounded-lg bg-accent px-5 py-2 text-sm font-semibold text-white hover:bg-accent-hover transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
          >
            {submitting ? "Starting..." : "Start Mining"}
          </button>
        </form>

        {submitError && (
          <div className="mt-3">
            <ErrorBanner
              message="Failed to start mining job"
              detail={submitError}
              onRetry={() => { setSubmitError(null); }}
            />
          </div>
        )}
      </Card>

      {/* ---- Active Job Status ---- */}
      {activeJob && (
        <Card className="mb-6">
          <CardTitle>Active Job</CardTitle>
          <div className="flex flex-wrap items-center gap-4 mb-3">
            <div className="text-xs text-muted">
              Job ID: <code className="text-foreground font-mono">{activeJob.jobId}</code>
            </div>
            <div className="text-xs text-muted">
              Path: <code className="text-foreground font-mono">{activeJob.path}</code>
            </div>
            <div className="text-xs text-muted">
              Brain: <span className="text-foreground">{activeJob.brain}</span>
            </div>
          </div>

          {/* Status badge */}
          <div className="flex items-center gap-3">
            <span
              className={`inline-block px-3 py-1 rounded-full text-xs font-semibold uppercase tracking-wider border ${statusColor(
                activeJob.status
              )}`}
            >
              {activeJob.status}
            </span>

            {(activeJob.status === "queued" || activeJob.status === "running") && (
              <span className="text-xs text-muted animate-pulse">Polling every 2s...</span>
            )}

            {activeJob.status === "completed" && (
              <span className="text-xs text-cam-green">Job finished successfully.</span>
            )}

            {activeJob.status === "failed" && (
              <span className="text-xs text-red-400">
                Job failed.{" "}
                {activeJob.details.error ? String(activeJob.details.error) : "Check server logs."}
              </span>
            )}
          </div>

          {/* Details dump for non-trivial data */}
          {activeJob.details && Object.keys(activeJob.details).length > 2 && (
            <details className="mt-3">
              <summary className="text-xs text-muted-dark cursor-pointer hover:text-muted">
                Raw job details
              </summary>
              <pre className="mt-2 text-[11px] text-muted font-mono bg-background rounded-lg p-3 overflow-x-auto max-h-48">
                {JSON.stringify(activeJob.details, null, 2)}
              </pre>
            </details>
          )}
        </Card>
      )}

      {/* ---- Recent Mining Outcomes ---- */}
      <Card>
        <div className="flex items-center justify-between mb-4">
          <CardTitle>Recent Mining Outcomes</CardTitle>
          <button
            onClick={() => {
              setOutcomesLoading(true);
              loadOutcomes();
            }}
            className="text-xs text-muted hover:text-foreground transition-colors"
          >
            Refresh
          </button>
        </div>

        {outcomesLoading && (
          <div className="space-y-3">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-3/4" />
          </div>
        )}

        {outcomesError && (
          <ErrorBanner
            message="Failed to load mining outcomes"
            detail={outcomesError}
            onRetry={() => { setOutcomesError(null); setOutcomesLoading(true); loadOutcomes(); }}
          />
        )}

        {!outcomesLoading && !outcomesError && outcomes.length === 0 && (
          <div className="text-xs text-muted-dark py-4">No mining outcomes recorded yet.</div>
        )}

        {!outcomesLoading && outcomes.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-card-border text-left">
                  <th className="pb-2 pr-3 font-semibold text-muted">Repo</th>
                  <th className="pb-2 pr-3 font-semibold text-muted">Brain</th>
                  <th className="pb-2 pr-3 font-semibold text-muted">Model</th>
                  <th className="pb-2 pr-3 font-semibold text-muted">Agent</th>
                  <th className="pb-2 pr-3 font-semibold text-muted">Strategy</th>
                  <th className="pb-2 pr-3 font-semibold text-muted">Result</th>
                  <th className="pb-2 pr-3 font-semibold text-muted text-right">Findings</th>
                  <th className="pb-2 pr-3 font-semibold text-muted text-right">Tokens</th>
                  <th className="pb-2 pr-3 font-semibold text-muted text-right">Duration</th>
                  <th className="pb-2 font-semibold text-muted">Created</th>
                </tr>
              </thead>
              <tbody>
                {outcomes.map((row, idx) => (
                  <tr
                    key={idx}
                    className="border-b border-card-border/50 hover:bg-card-border/20 transition-colors"
                  >
                    <td className="py-2 pr-3 font-mono text-foreground max-w-[160px] truncate" title={row.repo_name}>
                      {row.repo_name || "-"}
                    </td>
                    <td className="py-2 pr-3">
                      <BrainBadge brain={row.brain} />
                    </td>
                    <td className="py-2 pr-3 text-muted font-mono max-w-[140px] truncate" title={row.model_used}>
                      {row.model_used || "-"}
                    </td>
                    <td className="py-2 pr-3 text-muted max-w-[100px] truncate" title={row.agent_id}>
                      {row.agent_id || "-"}
                    </td>
                    <td className="py-2 pr-3 text-muted max-w-[100px] truncate" title={row.strategy}>
                      {row.strategy || "-"}
                    </td>
                    <td className="py-2 pr-3">
                      <SuccessBadge success={row.success} />
                    </td>
                    <td className="py-2 pr-3 text-right text-foreground font-mono">
                      {row.findings_count != null ? row.findings_count : "-"}
                    </td>
                    <td className="py-2 pr-3 text-right text-muted font-mono">
                      {row.tokens_used != null ? row.tokens_used.toLocaleString() : "-"}
                    </td>
                    <td className="py-2 pr-3 text-right text-muted font-mono">
                      {row.duration_seconds != null ? `${row.duration_seconds.toFixed(1)}s` : "-"}
                    </td>
                    <td className="py-2 text-muted whitespace-nowrap">
                      {row.created_at ? formatTimestamp(row.created_at) : "-"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

const BRAIN_COLORS: Record<string, string> = {
  python: "#ff6b3d",
  typescript: "#3178c6",
  go: "#00add8",
  rust: "#dea584",
  misc: "#76809d",
};

function BrainBadge({ brain }: { brain: string }) {
  const color = BRAIN_COLORS[brain] || "#76809d";
  return (
    <span
      className="inline-block px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wider"
      style={{
        backgroundColor: `${color}18`,
        color,
        border: `1px solid ${color}33`,
      }}
    >
      {brain || "unknown"}
    </span>
  );
}

function SuccessBadge({ success }: { success: boolean }) {
  if (success) {
    return (
      <span className="inline-block px-2 py-0.5 rounded text-[10px] font-semibold bg-cam-green/15 text-cam-green">
        success
      </span>
    );
  }
  return (
    <span className="inline-block px-2 py-0.5 rounded text-[10px] font-semibold bg-red-500/15 text-red-400">
      failed
    </span>
  );
}
