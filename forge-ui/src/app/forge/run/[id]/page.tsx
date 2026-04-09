"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getForgeJobStatus } from "@/lib/api";
import { Card, CardTitle } from "@/components/card";
import { StepPipeline, type PipelineStage } from "@/components/step-pipeline";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface StageEvent {
  stage: string;
  status: "pending" | "running" | "success" | "error" | "skipped";
  detail: string;
  timestamp: string;
}

interface LogEntry {
  time: string;
  level: "info" | "warn" | "error" | "success";
  message: string;
}

// ---------------------------------------------------------------------------
// Log Stream Panel
// ---------------------------------------------------------------------------

function LogStream({ logs }: { logs: LogEntry[] }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [logs]);

  const levelColors = {
    info: "text-muted",
    warn: "text-amber-400",
    error: "text-red-400",
    success: "text-cam-green",
  };

  return (
    <div
      ref={scrollRef}
      className="bg-background border border-card-border rounded-lg p-4 h-[500px] overflow-y-auto font-mono text-xs"
    >
      {logs.length === 0 && (
        <div className="text-muted-dark">Waiting for execution events...</div>
      )}
      {logs.map((log, i) => (
        <div key={i} className="py-0.5 flex gap-2">
          <span className="text-muted-dark shrink-0">{log.time}</span>
          <span className={levelColors[log.level]}>{log.message}</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const DEFAULT_STAGES: PipelineStage[] = [
  { id: "brain_setup", label: "Brain Setup", status: "pending", detail: "Create ganglion DB" },
  { id: "prompt_write", label: "Prompt Template", status: "pending", detail: "Write custom prompt" },
  { id: "config_update", label: "Config Update", status: "pending", detail: "Update claw.toml" },
  { id: "mining", label: "Mining", status: "pending", detail: "Extract knowledge from repos" },
  { id: "cag_rebuild", label: "CAG Rebuild", status: "pending", detail: "Rebuild cache corpus" },
  { id: "verification", label: "Verification", status: "pending", detail: "Run validation checks" },
];

export default function ExecutionPage() {
  const params = useParams();
  const jobId = params.id as string;

  const [stages, setStages] = useState<PipelineStage[]>(DEFAULT_STAGES);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [status, setStatus] = useState<string>("connecting");
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const addLog = useCallback((level: LogEntry["level"], message: string) => {
    const time = new Date().toLocaleTimeString("en-US", {
      hour12: false,
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    setLogs((prev) => [...prev, { time, level, message }]);
  }, []);

  const updateStage = useCallback((id: string, update: Partial<PipelineStage>) => {
    setStages((prev) =>
      prev.map((s) => (s.id === id ? { ...s, ...update } : s))
    );
  }, []);

  // Poll for job status
  useEffect(() => {
    if (!jobId) return;

    addLog("info", `Connecting to execution job ${jobId}...`);

    const poll = async () => {
      try {
        const data = await getForgeJobStatus(jobId);
        const jobStatus = data.status as string;
        setStatus(jobStatus);

        // Update stages from job data
        const jobStages = data.stages as StageEvent[] | undefined;
        if (jobStages) {
          for (const event of jobStages) {
            updateStage(event.stage, {
              status: event.status,
              detail: event.detail,
            });
            if (event.status === "running") {
              addLog("info", `${event.stage}: ${event.detail}`);
            } else if (event.status === "success") {
              addLog("success", `${event.stage} completed`);
            } else if (event.status === "error") {
              addLog("error", `${event.stage} failed: ${event.detail}`);
            }
          }
        }

        if (jobStatus === "completed" || jobStatus === "error") {
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
          if (jobStatus === "completed") {
            addLog("success", "Execution completed successfully");
          } else {
            addLog("error", `Execution failed: ${data.error as string || "unknown error"}`);
            setError(data.error as string || "unknown error");
          }
        }
      } catch (e) {
        // Job might not exist yet or API issue
        const msg = e instanceof Error ? e.message : String(e);
        if (msg.includes("404")) {
          addLog("warn", "Job not found — it may not have started yet");
          setStatus("not_found");
        }
      }
    };

    // Initial check
    poll();

    // Poll every 2 seconds
    pollRef.current = setInterval(poll, 2000);

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
      }
    };
  }, [jobId, addLog, updateStage]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Execution Theater</h1>
          <p className="text-muted mt-1">
            Job <span className="font-mono text-foreground">{jobId}</span> —{" "}
            <span
              className={`font-medium ${
                status === "completed"
                  ? "text-cam-green"
                  : status === "error"
                  ? "text-red-400"
                  : status === "running"
                  ? "text-cam-blue"
                  : "text-muted"
              }`}
            >
              {status}
            </span>
          </p>
        </div>
        <Link href="/forge" className="text-sm text-muted hover:text-foreground">
          Back to Brain
        </Link>
      </div>

      {/* Main layout: stages + log */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Left: Pipeline stages */}
        <div className="lg:col-span-2">
          <Card>
            <CardTitle>Execution Pipeline</CardTitle>
            <StepPipeline stages={stages} />
          </Card>
        </div>

        {/* Right: Live log stream */}
        <div className="lg:col-span-3">
          <Card>
            <CardTitle>Live Output</CardTitle>
            <LogStream logs={logs} />
          </Card>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="text-red-400 text-sm bg-red-400/10 border border-red-400/20 rounded-lg px-4 py-3">
          Execution failed: {error}
        </div>
      )}

      {/* Completion actions */}
      {status === "completed" && (
        <Card className="border-cam-green/30">
          <div className="flex items-center justify-between">
            <div>
              <div className="text-sm text-cam-green font-bold">Execution Complete</div>
              <div className="text-xs text-muted mt-0.5">
                All stages finished successfully
              </div>
            </div>
            <div className="flex gap-3">
              <Link
                href="/forge"
                className="px-4 py-2 bg-card-border hover:bg-card-hover text-foreground text-sm font-medium rounded-lg transition-colors"
              >
                View Brain
              </Link>
              <Link
                href="/knowledge"
                className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm font-medium rounded-lg transition-colors"
              >
                Explore Knowledge
              </Link>
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}
