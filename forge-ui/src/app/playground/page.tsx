"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  createPlan,
  executeTask,
  getConfig,
  getSessionStatus,
  getSessionCorrections,
  type SessionStatus,
  type GateResult,
  type CorrectionEntry,
} from "@/lib/api";
import { Card, CardTitle } from "@/components/card";
import { ErrorBanner } from "@/components/error-banner";

// ---------------------------------------------------------------------------
// Gate metadata (educational reference)
// ---------------------------------------------------------------------------

const GATE_INFO: Record<string, { name: string; description: string }> = {
  dependency_jail: {
    name: "Dependency Jail",
    description: "Blocks unauthorized imports not in the project manifest.",
  },
  style_match: {
    name: "Style Match",
    description: "Enforces naming, indentation, and file layout conventions.",
  },
  chaos_check: {
    name: "Chaos Check",
    description: "Rejects bare except, eval/exec, shell=True, hardcoded secrets.",
  },
  placeholder_scan: {
    name: "Placeholder Scan",
    description: "Rejects TODO, FIXME, NotImplementedError, pass-only functions.",
  },
  drift_alignment: {
    name: "Drift Alignment",
    description: "Measures semantic similarity between task brief and output.",
  },
  claim_validation: {
    name: "Claims Verification",
    description: "Detects unsubstantiated assertions or hallucinated references.",
  },
  llm_deep_review: {
    name: "LLM Deep Review",
    description: "Full LLM code review. Only runs when gates 1-6 pass.",
  },
};

const GATE_ORDER = [
  "dependency_jail",
  "style_match",
  "chaos_check",
  "placeholder_scan",
  "drift_alignment",
  "claim_validation",
  "llm_deep_review",
];

// ---------------------------------------------------------------------------
// Gate visualization
// ---------------------------------------------------------------------------

type GateStatus = "pending" | "pass" | "fail" | "running";

function GatePipeline({
  gates,
  currentStep,
}: {
  gates: GateResult[];
  currentStep: string;
}) {
  const gateMap = new Map(gates.map((g) => [g.check, g]));
  const isVerifying = currentStep === "verify";

  return (
    <div className="space-y-0">
      {GATE_ORDER.map((gateId, i) => {
        const result = gateMap.get(gateId);
        const info = GATE_INFO[gateId];
        const isLast = i === GATE_ORDER.length - 1;

        let status: GateStatus = "pending";
        if (result) {
          status = result.status === "pass" ? "pass" : "fail";
        } else if (isVerifying && gates.length === i) {
          status = "running";
        }

        const styles = {
          pending: { dot: "bg-card-border", text: "text-muted", line: "bg-card-border" },
          running: { dot: "bg-cam-blue animate-pulse", text: "text-cam-blue", line: "bg-cam-blue/30" },
          pass: { dot: "bg-cam-green", text: "text-cam-green", line: "bg-cam-green/30" },
          fail: { dot: "bg-red-500", text: "text-red-400", line: "bg-red-500/30" },
        }[status];

        return (
          <div key={gateId} className="flex gap-3">
            <div className="flex flex-col items-center">
              <div className={`w-3 h-3 rounded-full shrink-0 mt-1 ${styles.dot}`} />
              {!isLast && <div className={`w-0.5 flex-1 min-h-[24px] ${styles.line}`} />}
            </div>
            <div className="pb-4">
              <div className="flex items-center gap-2">
                <span className={`text-sm font-medium ${styles.text}`}>
                  G{i + 1}: {info.name}
                </span>
                {status !== "pending" && (
                  <span
                    className={`text-[10px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded ${
                      status === "pass"
                        ? "bg-cam-green/15 text-cam-green"
                        : status === "fail"
                        ? "bg-red-500/15 text-red-400"
                        : "bg-cam-blue/15 text-cam-blue"
                    }`}
                  >
                    {status === "running" ? "checking" : status}
                  </span>
                )}
              </div>
              <div className="text-xs text-muted mt-0.5">{info.description}</div>
              {result && result.status === "fail" && result.detail && (
                <div className="text-xs text-red-400/80 mt-1 font-mono bg-red-500/5 rounded px-2 py-1">
                  {result.detail.slice(0, 200)}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Correction Timeline
// ---------------------------------------------------------------------------

function CorrectionTimeline({ corrections }: { corrections: CorrectionEntry[] }) {
  if (corrections.length === 0) return null;

  return (
    <Card>
      <CardTitle>Correction Loop ({corrections.length} correction{corrections.length !== 1 ? "s" : ""})</CardTitle>
      <div className="relative ml-4">
        <div className="absolute left-0 top-2 bottom-2 w-px bg-card-border" />
        {corrections.map((c, i) => (
          <div key={i} className="relative pl-7 pb-5 last:pb-0">
            <div className="absolute left-[-5px] top-1.5 w-[11px] h-[11px] rounded-full border-2 border-red-500 bg-red-500" />
            <div className="text-xs font-semibold text-foreground mb-1">
              Attempt {c.attempt_number + 1} Failed
            </div>
            <div className="space-y-1">
              {c.violations.map((v, vi) => (
                <div key={vi} className="text-xs text-red-400">
                  {v.check}: {v.detail.slice(0, 150)}
                </div>
              ))}
              {c.code_diff && (
                <details className="mt-1">
                  <summary className="text-xs text-muted cursor-pointer hover:text-foreground">
                    View code diff
                  </summary>
                  <pre className="mt-1 text-xs text-cam-green bg-background border border-card-border rounded p-2 overflow-x-auto max-h-40 overflow-y-auto font-mono">
                    {c.code_diff.slice(0, 2000)}
                  </pre>
                </details>
              )}
              {c.failing_test_content && (
                <details className="mt-1">
                  <summary className="text-xs text-muted cursor-pointer hover:text-foreground">
                    View failing tests
                  </summary>
                  <pre className="mt-1 text-xs text-amber-400 bg-background border border-card-border rounded p-2 overflow-x-auto max-h-40 overflow-y-auto font-mono">
                    {c.failing_test_content.slice(0, 2000)}
                  </pre>
                </details>
              )}
            </div>
          </div>
        ))}
        {/* Final attempt marker */}
        <div className="relative pl-7">
          <div className="absolute left-[-5px] top-1.5 w-[11px] h-[11px] rounded-full border-2 border-cam-blue bg-cam-blue" />
          <div className="text-xs font-semibold text-cam-blue">
            Attempt {corrections.length + 1} (final)
          </div>
        </div>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Step Log
// ---------------------------------------------------------------------------

function StepLog({ steps }: { steps: Array<{ step: string; detail: string; timestamp: string }> }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [steps]);

  const stepColors: Record<string, string> = {
    grab: "text-cam-blue",
    evaluate: "text-muted",
    decide: "text-cam-purple",
    act: "text-foreground",
    correct: "text-amber-400",
    verify: "text-cam-blue",
    learn: "text-cam-green",
    done: "text-cam-green",
  };

  return (
    <div
      ref={scrollRef}
      className="bg-background border border-card-border rounded-lg p-4 h-[300px] overflow-y-auto font-mono text-xs"
    >
      {steps.length === 0 && (
        <div className="text-muted-dark">Waiting for execution events...</div>
      )}
      {steps.map((s, i) => (
        <div key={i} className="py-0.5 flex gap-2">
          <span className="text-muted-dark shrink-0">
            {new Date(s.timestamp).toLocaleTimeString("en-US", { hour12: false })}
          </span>
          <span className={`font-bold w-16 shrink-0 ${stepColors[s.step] || "text-muted"}`}>
            [{s.step}]
          </span>
          <span className="text-muted">{s.detail}</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Result Panel
// ---------------------------------------------------------------------------

function ResultPanel({ session }: { session: SessionStatus }) {
  if (!session.result) return null;

  const r = session.result;
  const v = r.verification;

  return (
    <Card className={r.success ? "border-cam-green/30" : "border-red-500/30"}>
      <CardTitle>{r.success ? "Execution Succeeded" : "Execution Failed"}</CardTitle>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <div>
          <div className="text-xs text-muted">Status</div>
          <div className={`text-sm font-bold ${r.success ? "text-cam-green" : "text-red-400"}`}>
            {r.success ? "Approved" : "Rejected"}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted">Tokens</div>
          <div className="text-sm font-bold text-foreground font-mono">{r.tokens_used.toLocaleString()}</div>
        </div>
        <div>
          <div className="text-xs text-muted">Cost</div>
          <div className="text-sm font-bold text-foreground font-mono">${r.cost_usd.toFixed(4)}</div>
        </div>
        <div>
          <div className="text-xs text-muted">Duration</div>
          <div className="text-sm font-bold text-foreground font-mono">{r.duration_seconds.toFixed(1)}s</div>
        </div>
      </div>

      {r.outcome.approach_summary && (
        <div className="mb-3">
          <div className="text-xs text-muted uppercase tracking-wider mb-1">Approach</div>
          <p className="text-xs text-foreground leading-relaxed">{r.outcome.approach_summary}</p>
        </div>
      )}

      {r.outcome.files_changed.length > 0 && (
        <div className="mb-3">
          <div className="text-xs text-muted uppercase tracking-wider mb-1">Files Changed</div>
          <div className="flex flex-wrap gap-1.5">
            {r.outcome.files_changed.map((f) => (
              <span key={f} className="text-xs font-mono px-2 py-0.5 rounded bg-card-border text-foreground">
                {f}
              </span>
            ))}
          </div>
        </div>
      )}

      {v && (
        <div className="mb-3">
          <div className="text-xs text-muted uppercase tracking-wider mb-1">Verification</div>
          <div className="flex gap-4 text-xs">
            <span>Quality: <strong className="text-foreground">{v.quality_score?.toFixed(2) ?? "--"}</strong></span>
            {v.drift_cosine_score !== null && (
              <span>Drift: <strong className="text-foreground">{v.drift_cosine_score.toFixed(2)}</strong></span>
            )}
            {v.tests_after !== null && (
              <span>Tests: <strong className="text-foreground">{v.tests_after}</strong></span>
            )}
          </div>
          {v.violations.length > 0 && (
            <div className="mt-2 space-y-1">
              {v.violations.map((viol, i) => (
                <div key={i} className="text-xs text-red-400">
                  {viol.check}: {viol.detail.slice(0, 150)}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {r.outcome.failure_reason && (
        <div className="text-xs text-red-400 bg-red-500/5 rounded p-2 mt-2">
          {r.outcome.failure_reason}: {r.outcome.failure_detail}
        </div>
      )}

      <div className="mt-4 flex gap-3">
        <Link
          href="/"
          className="px-4 py-2 bg-card-border hover:bg-card-hover text-foreground text-sm font-medium rounded-lg transition-colors"
        >
          Dashboard
        </Link>
        <Link
          href="/knowledge"
          className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm font-medium rounded-lg transition-colors"
        >
          Explore Knowledge
        </Link>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function PlaygroundPage() {
  const router = useRouter();
  const [taskDescription, setTaskDescription] = useState("");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [session, setSession] = useState<SessionStatus | null>(null);
  const [corrections, setCorrections] = useState<CorrectionEntry[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showGuide, setShowGuide] = useState(false);
  const [packetReviewEnabled, setPacketReviewEnabled] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    let cancelled = false;
    const loadConfig = async () => {
      try {
        const config = await getConfig();
        const enabled = Boolean(
          (config as { feature_flags?: { application_packets?: boolean } }).feature_flags?.application_packets
        );
        if (!cancelled) setPacketReviewEnabled(enabled);
      } catch {
        if (!cancelled) setPacketReviewEnabled(false);
      }
    };
    loadConfig();
    return () => {
      cancelled = true;
    };
  }, []);

  // Poll for session status
  useEffect(() => {
    if (!sessionId) return;

    const poll = async () => {
      try {
        const status = await getSessionStatus(sessionId);
        setSession(status);

        // Fetch corrections if any
        if (status.corrections_count > 0) {
          const corr = await getSessionCorrections(sessionId);
          setCorrections(corr.corrections);
        }

        // Stop polling when done
        if (status.status === "completed" || status.status === "failed" || status.status === "error") {
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (msg.includes("404")) {
          // Session not ready yet
        } else {
          setError(msg);
        }
      }
    };

    poll();
    pollRef.current = setInterval(poll, 2000);

    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [sessionId]);

  const handleSubmit = useCallback(async () => {
    const desc = taskDescription.trim();
    if (!desc) return;

    setSubmitting(true);
    setError(null);
    setSession(null);
    setCorrections([]);
    setSessionId(null);

    try {
      if (packetReviewEnabled) {
        const plan = await createPlan({
          task_text: desc,
          execution_mode: "interactive",
          check_commands: ["pytest -q"],
        });
        router.push(`/playground/plan/${plan.plan_id}`);
        return;
      }

      const result = await executeTask(desc);
      setSessionId(result.session_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }, [packetReviewEnabled, router, taskDescription]);

  const isRunning = session?.status === "running" || session?.status === "starting";
  const isDone = session?.status === "completed" || session?.status === "failed" || session?.status === "error";
  const currentStep = session?.steps.length ? session.steps[session.steps.length - 1].step : "";

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Playground</h1>
          <p className="text-muted mt-1">
            Execute tasks with real 7-gate verification and correction loop.
          </p>
        </div>
        <button
          onClick={() => setShowGuide(!showGuide)}
          className="text-sm text-muted hover:text-foreground px-3 py-1.5 rounded-lg hover:bg-card-border/50 transition-colors"
        >
          {showGuide ? "Hide Guide" : "Gate Guide"}
        </button>
      </div>

      {/* Collapsible gate guide */}
      {showGuide && (
        <Card>
          <CardTitle>7-Gate Verification Pipeline</CardTitle>
          <p className="text-xs text-muted mb-3">
            Every task passes through 7 sequential gates. Failure triggers the correction loop
            (max 3 attempts). Gate 7 only runs when 1-6 pass.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {GATE_ORDER.map((gateId, i) => {
              const info = GATE_INFO[gateId];
              return (
                <div key={gateId} className="flex items-start gap-2 p-2 bg-card-border/20 rounded-lg">
                  <span className="text-xs font-bold text-accent shrink-0 mt-0.5">G{i + 1}</span>
                  <div>
                    <div className="text-xs font-medium text-foreground">{info.name}</div>
                    <div className="text-xs text-muted">{info.description}</div>
                  </div>
                </div>
              );
            })}
          </div>
          <div className="mt-3 grid grid-cols-3 gap-3">
            <div className="rounded-lg border border-card-border p-2">
              <div className="text-xs font-semibold text-accent">Max Attempts</div>
              <div className="text-lg font-bold text-foreground">3</div>
            </div>
            <div className="rounded-lg border border-card-border p-2">
              <div className="text-xs font-semibold text-accent">Feedback</div>
              <div className="text-xs text-foreground">Diff + violations + test files</div>
            </div>
            <div className="rounded-lg border border-card-border p-2">
              <div className="text-xs font-semibold text-accent">Escalation</div>
              <div className="text-xs text-foreground">Content reduction → chunk → model</div>
            </div>
          </div>
        </Card>
      )}

      {/* Task input */}
      <Card>
        <CardTitle>Submit Task</CardTitle>
        <div className="space-y-3">
          <textarea
            value={taskDescription}
            onChange={(e) => setTaskDescription(e.target.value)}
            placeholder="Describe the task to execute... e.g. 'Add pagination to the /api/items endpoint with cursor-based navigation'"
            rows={3}
            disabled={isRunning}
            className="w-full bg-background border border-card-border rounded-lg px-4 py-3 text-sm text-foreground placeholder:text-muted-dark focus:outline-none focus:border-accent resize-none disabled:opacity-50"
          />
          <div className="flex items-center justify-between">
            <div className="text-xs text-muted">
              {packetReviewEnabled
                ? "Creates a pre-mutation application packet plan before any write happens."
                : "Executes with real MicroClaw cycle: grab → evaluate → decide → act → verify → learn"}
            </div>
            <button
              onClick={handleSubmit}
              disabled={submitting || isRunning || !taskDescription.trim()}
              className="px-5 py-2.5 bg-accent hover:bg-accent-hover disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {submitting ? "Submitting..." : isRunning ? "Running..." : packetReviewEnabled ? "Review Plan" : "Execute"}
            </button>
          </div>
        </div>
      </Card>

      {error && <ErrorBanner message={error} onRetry={() => setError(null)} />}

      {/* Active session */}
      {session && (
        <>
          {/* Status bar */}
          <div className="flex items-center gap-4">
            <span className="text-xs text-muted font-mono">{session.session_id.slice(0, 8)}...</span>
            <span
              className={`text-xs font-bold uppercase tracking-wider ${
                session.status === "completed"
                  ? "text-cam-green"
                  : session.status === "failed" || session.status === "error"
                  ? "text-red-400"
                  : "text-cam-blue"
              }`}
            >
              {session.status}
            </span>
            {isRunning && currentStep && (
              <span className="text-xs text-muted">
                Step: <span className="text-foreground font-medium">{currentStep}</span>
              </span>
            )}
          </div>

          {/* Main layout: gates + log */}
          <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
            {/* Left: Gate pipeline */}
            <div className="lg:col-span-2">
              <Card>
                <CardTitle>Verification Gates</CardTitle>
                <GatePipeline gates={session.gates} currentStep={currentStep} />
              </Card>
            </div>

            {/* Right: Live step log */}
            <div className="lg:col-span-3">
              <Card>
                <CardTitle>Execution Log</CardTitle>
                <StepLog steps={session.steps} />
              </Card>
            </div>
          </div>

          {/* Correction timeline */}
          <CorrectionTimeline corrections={corrections} />

          {/* Result */}
          {isDone && <ResultPanel session={session} />}

          {/* Error from session */}
          {session.error && (
            <ErrorBanner message={`Execution error: ${session.error}`} />
          )}
        </>
      )}

      {/* Empty state */}
      {!session && !submitting && (
        <div className="text-center py-12">
          <div className="text-muted-dark text-4xl mb-3">7</div>
          <p className="text-muted text-sm">
            Submit a task above to watch it pass through the 7-gate verification pipeline.
          </p>
          <p className="text-muted-dark text-xs mt-1">
            Uses real MicroClaw execution with correction loops and methodology injection.
          </p>
        </div>
      )}
    </div>
  );
}
