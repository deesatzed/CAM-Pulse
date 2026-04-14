"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  banRunFamily,
  blockRunSlot,
  getPlan,
  getForgeJobStatus,
  getRunAudits,
  pauseRunSlot,
  resumeRunSlot,
  reverifyRunSlot,
  getRunConnectome,
  getRunEvents,
  getRunEventsStreamUrl,
  getRunLandings,
  getRunDistill,
  getRunRetrograde,
  getRunStatus,
  swapRunCandidate,
  unbanRunFamily,
  unblockRunSlot,
  type ApplicationPacket,
  type DistillResponse,
  type PlanDetail,
  type RunActionAudit,
  type RetrogradeResponse,
  type RunConnectomeResponse,
  type RunEventsResponse,
  type RunLandingsResponse,
  type RunStatusResponse,
} from "@/lib/api";
import { Card, CardTitle } from "@/components/card";
import { StepPipeline, type PipelineStage } from "@/components/step-pipeline";

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

const DEFAULT_STAGES: PipelineStage[] = [
  { id: "brain_setup", label: "Brain Setup", status: "pending", detail: "Create ganglion DB" },
  { id: "prompt_write", label: "Prompt Template", status: "pending", detail: "Write custom prompt" },
  { id: "config_update", label: "Config Update", status: "pending", detail: "Update claw.toml" },
  { id: "mining", label: "Mining", status: "pending", detail: "Extract knowledge from repos" },
  { id: "cag_rebuild", label: "CAG Rebuild", status: "pending", detail: "Rebuild cache corpus" },
  { id: "verification", label: "Verification", status: "pending", detail: "Run validation checks" },
];

function severityTone(severity: "neutral" | "low" | "medium" | "high"): string {
  if (severity === "high") return "border-red-400/30 bg-red-400/10 text-red-300";
  if (severity === "medium") return "border-amber-400/30 bg-amber-400/10 text-amber-200";
  if (severity === "low") return "border-cam-green/30 bg-cam-green/10 text-cam-green";
  return "border-card-border bg-card text-foreground";
}

function waitSeverity(waitMs: number): "neutral" | "medium" | "high" {
  if (waitMs >= 15000) return "high";
  if (waitMs >= 5000) return "medium";
  return "neutral";
}

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
      {logs.length === 0 && <div className="text-muted-dark">Waiting for execution events...</div>}
      {logs.map((log, i) => (
        <div key={i} className="py-0.5 flex gap-2">
          <span className="text-muted-dark shrink-0">{log.time}</span>
          <span className={levelColors[log.level]}>{log.message}</span>
        </div>
      ))}
    </div>
  );
}

function LegacyForgeRun({ jobId }: { jobId: string }) {
  const [stages, setStages] = useState<PipelineStage[]>(DEFAULT_STAGES);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [status, setStatus] = useState<string>("connecting");
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    const addLog = (level: LogEntry["level"], message: string) => {
      const time = new Date().toLocaleTimeString("en-US", {
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
      setLogs((prev) => [...prev, { time, level, message }]);
    };
    const updateStage = (id: string, update: Partial<PipelineStage>) => {
      setStages((prev) => prev.map((s) => (s.id === id ? { ...s, ...update } : s)));
    };

    addLog("info", `Connecting to execution job ${jobId}...`);

    const poll = async () => {
      try {
        const data = await getForgeJobStatus(jobId);
        const jobStatus = data.status as string;
        setStatus(jobStatus);
        const jobStages = data.stages as StageEvent[] | undefined;
        if (jobStages) {
          for (const event of jobStages) {
            updateStage(event.stage, { status: event.status, detail: event.detail });
          }
        }
        if (jobStatus === "completed" || jobStatus === "error") {
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
          if (jobStatus === "error") {
            setError((data.error as string) || "unknown error");
          }
        }
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (msg.includes("404")) {
          setStatus("not_found");
        }
      }
    };

    poll();
    pollRef.current = setInterval(poll, 2000);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, [jobId]);

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Execution Theater</h1>
          <p className="text-muted mt-1">
            Job <span className="font-mono text-foreground">{jobId}</span> — <span className="font-medium">{status}</span>
          </p>
        </div>
        <Link href="/forge" className="text-sm text-muted hover:text-foreground">Back to Brain</Link>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        <div className="lg:col-span-2">
          <Card>
            <CardTitle>Execution Pipeline</CardTitle>
            <StepPipeline stages={stages} />
          </Card>
        </div>
        <div className="lg:col-span-3">
          <Card>
            <CardTitle>Live Output</CardTitle>
            <LogStream logs={logs} />
          </Card>
        </div>
      </div>

      {error && <div className="text-red-400 text-sm bg-red-400/10 border border-red-400/20 rounded-lg px-4 py-3">Execution failed: {error}</div>}
    </div>
  );
}

function TabButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-2 rounded-lg text-sm transition-colors ${active ? "bg-accent text-white" : "bg-card-border text-foreground hover:bg-card-hover"}`}
    >
      {children}
    </button>
  );
}

export default function ExecutionPage() {
  const params = useParams();
  const runId = params.id as string;
  const [mode, setMode] = useState<"checking" | "camseq" | "legacy">("checking");
  const [tab, setTab] = useState<"sequence" | "connectome" | "landings" | "events" | "audits">("sequence");
  const [run, setRun] = useState<RunStatusResponse | null>(null);
  const [connectome, setConnectome] = useState<RunConnectomeResponse>({ nodes: [], edges: [] });
  const [landings, setLandings] = useState<RunLandingsResponse>({ landings: [] });
  const [events, setEvents] = useState<RunEventsResponse>({ events: [] });
  const [retrograde, setRetrograde] = useState<RetrogradeResponse | null>(null);
  const [distill, setDistill] = useState<DistillResponse | null>(null);
  const [plan, setPlan] = useState<PlanDetail | null>(null);
  const [audits, setAudits] = useState<RunActionAudit[]>([]);
  const [auditFilters, setAuditFilters] = useState<{ slot: string; actionType: string; actor: string }>({
    slot: "all",
    actionType: "all",
    actor: "all",
  });
  const [swapState, setSwapState] = useState<{ slotId: string | null; error: string | null }>({ slotId: null, error: null });
  const [slotActionState, setSlotActionState] = useState<{ slotId: string | null; action: string | null; error: string | null }>({
    slotId: null,
    action: null,
    error: null,
  });
  const [error, setError] = useState<string | null>(null);

  const refreshCamseqRun = useCallback(async () => {
    const [status, conn, land, evts, auditResp] = await Promise.all([
      getRunStatus(runId),
      getRunConnectome(runId),
      getRunLandings(runId),
      getRunEvents(runId),
      getRunAudits(runId),
    ]);
    setRun(status);
    setConnectome(conn);
    setLandings(land);
    setEvents(evts);
    setAudits(auditResp.audits);
    if (status.plan_id) {
      const detail = await getPlan(status.plan_id);
      setPlan(detail);
    }
  }, [runId]);

  useEffect(() => {
    if (!runId) return;
    let mounted = true;

    const loadCamseq = async () => {
      try {
        const status = await getRunStatus(runId);
        if (!mounted) return;
        setRun(status);
        setMode("camseq");
      } catch (e) {
        const msg = e instanceof Error ? e.message : String(e);
        if (msg.includes("404")) {
          setMode("legacy");
        } else {
          setError(msg);
          setMode("legacy");
        }
      }
    };

    loadCamseq();
    return () => {
      mounted = false;
    };
  }, [runId]);

  useEffect(() => {
    if (mode !== "camseq" || !runId) return;
    let cancelled = false;

    const poll = async () => {
      try {
        const [status, conn, land, evts, auditResp] = await Promise.all([
          getRunStatus(runId),
          getRunConnectome(runId),
          getRunLandings(runId),
          getRunEvents(runId),
          getRunAudits(runId),
        ]);
        if (cancelled) return;
        setRun(status);
        setConnectome(conn);
        setLandings(land);
        setEvents(evts);
        setAudits(auditResp.audits);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    };

    poll();
    const id = setInterval(poll, 2000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [mode, runId]);

  useEffect(() => {
    if (mode !== "camseq" || !runId) return;
    const source = new EventSource(getRunEventsStreamUrl(runId));
    source.onmessage = () => {};
    source.addEventListener("packet_selected", async () => {
      const evts = await getRunEvents(runId);
      setEvents(evts);
    });
    source.addEventListener("landing_recorded", async () => {
      const [land, conn] = await Promise.all([getRunLandings(runId), getRunConnectome(runId)]);
      setLandings(land);
      setConnectome(conn);
    });
    source.addEventListener("slot_verified", async () => {
      const [status, evts] = await Promise.all([getRunStatus(runId), getRunEvents(runId)]);
      setRun(status);
      setEvents(evts);
    });
    source.addEventListener("slot_failed", async () => {
      const [status, evts] = await Promise.all([getRunStatus(runId), getRunEvents(runId)]);
      setRun(status);
      setEvents(evts);
    });
    source.addEventListener("candidate_swapped", async () => {
      await refreshCamseqRun();
    });
    source.addEventListener("retry_delta", async () => {
      const [status, evts] = await Promise.all([getRunStatus(runId), getRunEvents(runId)]);
      setRun(status);
      setEvents(evts);
    });
    return () => {
      source.close();
    };
  }, [mode, runId, refreshCamseqRun]);

  useEffect(() => {
    if (mode !== "camseq" || !runId) return;
    const loadAnalysis = async () => {
      try {
        const [retro, dist] = await Promise.all([getRunRetrograde(runId), getRunDistill(runId)]);
        setRetrograde(retro);
        setDistill(dist);
      } catch {
        // Keep Forge Run resilient; Evolution route is the detailed analysis surface.
      }
    };
    loadAnalysis();
  }, [mode, runId]);

  useEffect(() => {
    if (mode !== "camseq" || !run?.plan_id) return;
    let cancelled = false;
    const loadPlan = async () => {
      try {
        const detail = await getPlan(run.plan_id as string);
        if (!cancelled) setPlan(detail);
      } catch {
        if (!cancelled) setPlan(null);
      }
    };
    loadPlan();
    return () => {
      cancelled = true;
    };
  }, [mode, run?.plan_id]);

  const packetBySlot = useMemo(() => {
    const bySlot = new Map<string, ApplicationPacket>();
    for (const packet of plan?.packets || []) {
      bySlot.set(packet.slot.slot_id, packet);
    }
    return bySlot;
  }, [plan]);

  const handleSwapCandidate = async (slotId: string, candidateComponentId: string) => {
    setSwapState({ slotId, error: null });
    try {
      await swapRunCandidate(runId, slotId, candidateComponentId, "swap from sequencing console");
      await refreshCamseqRun();
    } catch (e) {
      setSwapState({
        slotId: null,
        error: e instanceof Error ? e.message : String(e),
      });
      return;
    }
    setSwapState({ slotId: null, error: null });
  };

  const handleSlotAction = async (slotId: string, action: "pause" | "resume" | "reverify") => {
    setSlotActionState({ slotId, action, error: null });
    try {
      if (action === "pause") await pauseRunSlot(runId, slotId);
      else if (action === "resume") await resumeRunSlot(runId, slotId);
      else await reverifyRunSlot(runId, slotId);
      await refreshCamseqRun();
      setSlotActionState({ slotId: null, action: null, error: null });
    } catch (e) {
      setSlotActionState({
        slotId: null,
        action: null,
        error: e instanceof Error ? e.message : String(e),
      });
    }
  };

  const handleGovernanceAction = async (
    slotId: string,
    action: "block" | "unblock" | "banFamily" | "unbanFamily",
    familyBarcode?: string,
  ) => {
    setSlotActionState({ slotId, action, error: null });
    try {
      if (action === "block") await blockRunSlot(runId, slotId, "blocked from sequencing console");
      else if (action === "unblock") await unblockRunSlot(runId, slotId, "unblocked from sequencing console");
      else if (action === "banFamily" && familyBarcode) await banRunFamily(runId, familyBarcode, "banned from sequencing console");
      else if (action === "unbanFamily" && familyBarcode) await unbanRunFamily(runId, familyBarcode, "unbanned from sequencing console");
      await refreshCamseqRun();
      setSlotActionState({ slotId: null, action: null, error: null });
    } catch (e) {
      setSlotActionState({
        slotId: null,
        action: null,
        error: e instanceof Error ? e.message : String(e),
      });
    }
  };

  const sequenceRows = useMemo(() => {
    if (!run) return [];
    return run.steps.map((step) => ({
      time: new Date(step.timestamp).toLocaleTimeString("en-US", { hour12: false }),
      label: step.step,
      detail: step.detail,
    }));
  }, [run]);

  const filteredAudits = useMemo(() => {
    return audits.filter((audit) => {
      if (auditFilters.slot !== "all" && (audit.slot_id || "run") !== auditFilters.slot) return false;
      if (auditFilters.actionType !== "all" && audit.action_type !== auditFilters.actionType) return false;
      if (auditFilters.actor !== "all" && audit.actor !== auditFilters.actor) return false;
      return true;
    });
  }, [audits, auditFilters]);

  const auditSlots = useMemo(() => Array.from(new Set(audits.map((audit) => audit.slot_id || "run"))), [audits]);
  const auditActionTypes = useMemo(() => Array.from(new Set(audits.map((audit) => audit.action_type))), [audits]);
  const auditActors = useMemo(() => Array.from(new Set(audits.map((audit) => audit.actor))), [audits]);

  if (mode === "checking") {
    return <div className="text-sm text-muted">Loading run...</div>;
  }

  if (mode === "legacy") {
    return <LegacyForgeRun jobId={runId} />;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Sequencing Console</h1>
          <p className="text-muted mt-1">
            Run <span className="font-mono text-foreground">{runId}</span> — <span className="font-medium">{run?.status}</span>
          </p>
        </div>
        <Link href="/playground" className="text-sm text-muted hover:text-foreground">Back to Playground</Link>
      </div>

      {error && <div className="text-red-400 text-sm bg-red-400/10 border border-red-400/20 rounded-lg px-4 py-3">{error}</div>}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card><div className="text-xs text-muted">Current Slot</div><div className="text-sm font-semibold text-foreground mt-1">{run?.current_slot_id || "n/a"}</div></Card>
        <Card><div className="text-xs text-muted">Completed Slots</div><div className="text-sm font-semibold text-foreground mt-1">{run?.summary.completed_slots ?? 0}/{run?.summary.total_slots ?? 0}</div></Card>
        <Card><div className="text-xs text-muted">Retries</div><div className="text-sm font-semibold text-foreground mt-1">{run?.retry_count ?? 0}</div></Card>
        <Card><div className="text-xs text-muted">Landings</div><div className="text-sm font-semibold text-foreground mt-1">{run?.summary.landing_events ?? 0}</div></Card>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card><div className="text-xs text-muted">Blocked Slots</div><div className={`text-sm font-semibold mt-1 ${(run?.summary.blocked_slots ?? 0) > 0 ? "text-amber-300" : "text-foreground"}`}>{run?.summary.blocked_slots ?? 0}</div></Card>
        <Card><div className="text-xs text-muted">Banned Families</div><div className={`text-sm font-semibold mt-1 ${(run?.summary.banned_families ?? 0) > 0 ? "text-amber-300" : "text-foreground"}`}>{run?.summary.banned_families ?? 0}</div></Card>
        <Card><div className="text-xs text-muted">Blocked Wait</div><div className={`text-sm font-semibold mt-1 ${waitSeverity(run?.summary.blocked_wait_ms ?? 0) === "high" ? "text-red-300" : waitSeverity(run?.summary.blocked_wait_ms ?? 0) === "medium" ? "text-amber-300" : "text-foreground"}`}>{(((run?.summary.blocked_wait_ms ?? 0) / 1000)).toFixed(1)}s</div></Card>
        <Card><div className="text-xs text-muted">Family Wait</div><div className={`text-sm font-semibold mt-1 ${waitSeverity(run?.summary.family_wait_ms ?? 0) === "high" ? "text-red-300" : waitSeverity(run?.summary.family_wait_ms ?? 0) === "medium" ? "text-amber-300" : "text-foreground"}`}>{(((run?.summary.family_wait_ms ?? 0) / 1000)).toFixed(1)}s</div></Card>
      </div>

      <Card>
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-xs text-muted uppercase tracking-wider">Slot Progress</div>
            <div className="text-xs text-muted mt-1">Per-slot status summary from reviewed packets and runtime outcomes.</div>
          </div>
          <Link href={`/evolution/run/${runId}`} className="text-sm text-accent hover:text-accent-hover">
            Open Retrograde Analysis
          </Link>
        </div>
        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
          {(run?.slots || []).map((slot) => (
            <div key={slot.slot_id} className="border border-card-border rounded-lg p-3">
              <div className="font-medium text-foreground">{slot.name}</div>
              <div className="text-xs text-muted mt-1">
                {slot.status} · {Math.round(slot.confidence * 100)}% · {slot.coverage_state}
              </div>
              <div className="text-xs text-muted mt-1">
                landings {slot.landing_count} · retries {slot.retry_count}
              </div>
              <div className="text-xs text-muted mt-1">
                blocked wait {(slot.blocked_wait_ms / 1000).toFixed(1)}s · family wait {(slot.family_wait_ms / 1000).toFixed(1)}s
              </div>
              <div className="text-xs text-muted mt-1">
                selected {slot.selected_component_id || "unknown"}
              </div>
              {slot.block_reason ? (
                <div className="text-xs text-amber-400 mt-1">
                  blocked: {slot.block_reason}
                </div>
              ) : null}
              <div className="mt-3 flex flex-wrap gap-2">
                {slot.status === "executing" ? (
                  <button
                    type="button"
                    disabled={slotActionState.slotId === slot.slot_id}
                    onClick={() => handleSlotAction(slot.slot_id, "pause")}
                    className="px-2 py-1 rounded border border-card-border text-xs text-foreground hover:bg-card-hover disabled:opacity-50"
                  >
                    pause
                  </button>
                ) : null}
                {slot.status === "paused" ? (
                  <button
                    type="button"
                    disabled={slotActionState.slotId === slot.slot_id}
                    onClick={() => handleSlotAction(slot.slot_id, "resume")}
                    className="px-2 py-1 rounded border border-card-border text-xs text-foreground hover:bg-card-hover disabled:opacity-50"
                  >
                    resume
                  </button>
                ) : null}
                {slot.status === "executing" || slot.status === "verified" ? (
                  <button
                    type="button"
                    disabled={slotActionState.slotId === slot.slot_id}
                    onClick={() => handleSlotAction(slot.slot_id, "reverify")}
                    className="px-2 py-1 rounded border border-card-border text-xs text-foreground hover:bg-card-hover disabled:opacity-50"
                  >
                    reverify
                  </button>
                ) : null}
                {slot.status !== "blocked" ? (
                  <button
                    type="button"
                    disabled={slotActionState.slotId === slot.slot_id}
                    onClick={() => handleGovernanceAction(slot.slot_id, "block")}
                    className="px-2 py-1 rounded border border-card-border text-xs text-foreground hover:bg-card-hover disabled:opacity-50"
                  >
                    block
                  </button>
                ) : (
                  <button
                    type="button"
                    disabled={slotActionState.slotId === slot.slot_id}
                    onClick={() => handleGovernanceAction(slot.slot_id, "unblock")}
                    className="px-2 py-1 rounded border border-card-border text-xs text-foreground hover:bg-card-hover disabled:opacity-50"
                  >
                    unblock
                  </button>
                )}
                {packetBySlot.get(slot.slot_id) ? (
                  (() => {
                    const family = packetBySlot.get(slot.slot_id)!.selected.receipt.family_barcode;
                    const banned = Boolean(run?.banned_family_barcodes?.[family]);
                    return (
                      <button
                        type="button"
                        disabled={slotActionState.slotId === slot.slot_id}
                        onClick={() => handleGovernanceAction(slot.slot_id, banned ? "unbanFamily" : "banFamily", family)}
                        className="px-2 py-1 rounded border border-card-border text-xs text-foreground hover:bg-card-hover disabled:opacity-50"
                      >
                        {banned ? "unban family" : "ban family"}
                      </button>
                    );
                  })()
                ) : null}
              </div>
              {packetBySlot.get(slot.slot_id)?.runner_ups?.length ? (
                <div className="mt-3 space-y-2">
                  <div className="text-[11px] uppercase tracking-wider text-muted">Runner-ups</div>
                  <div className="flex flex-wrap gap-2">
                    {packetBySlot.get(slot.slot_id)!.runner_ups.map((candidate) => (
                      <button
                        key={candidate.component_id}
                        type="button"
                        disabled={swapState.slotId === slot.slot_id || slot.status === "verified" || slot.status === "failed"}
                        onClick={() => handleSwapCandidate(slot.slot_id, candidate.component_id)}
                        className="px-2 py-1 rounded border border-card-border text-xs text-foreground hover:bg-card-hover disabled:opacity-50"
                      >
                        swap to {candidate.component_id}
                      </button>
                    ))}
                  </div>
                </div>
              ) : null}
            </div>
          ))}
        </div>
        {swapState.error ? <div className="mt-4 text-xs text-red-400">{swapState.error}</div> : null}
        {slotActionState.error ? <div className="mt-2 text-xs text-red-400">{slotActionState.error}</div> : null}
      </Card>

      <div className="flex gap-2 flex-wrap">
        <TabButton active={tab === "sequence"} onClick={() => setTab("sequence")}>Sequence</TabButton>
        <TabButton active={tab === "connectome"} onClick={() => setTab("connectome")}>Connectome</TabButton>
        <TabButton active={tab === "landings"} onClick={() => setTab("landings")}>Landings</TabButton>
        <TabButton active={tab === "events"} onClick={() => setTab("events")}>Events</TabButton>
        <TabButton active={tab === "audits"} onClick={() => setTab("audits")}>Audits</TabButton>
      </div>

      {tab === "sequence" && (
        <Card>
          <CardTitle>Sequence</CardTitle>
          <div className="space-y-2 text-sm">
            {sequenceRows.length === 0 ? (
              <div className="text-muted">No sequence events yet.</div>
            ) : (
              sequenceRows.map((row, idx) => (
                <div key={`${row.time}-${idx}`} className="border border-card-border rounded-lg p-3">
                  <div className="text-xs text-muted">{row.time}</div>
                  <div className="font-medium text-foreground mt-1">{row.label}</div>
                  <div className="text-sm text-muted mt-1">{row.detail}</div>
                </div>
              ))
            )}
          </div>
        </Card>
      )}

      {tab === "connectome" && (
        <Card>
          <CardTitle>Connectome</CardTitle>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div>
              <div className="text-xs text-muted uppercase tracking-wider mb-2">Nodes</div>
              <div className="space-y-2 text-sm">
                {connectome.nodes.map((node) => (
                  <div key={node.id} className="border border-card-border rounded-lg p-3">
                    <div className="font-medium text-foreground">{node.id}</div>
                    <div className="text-xs text-muted mt-1">{node.kind}</div>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <div className="text-xs text-muted uppercase tracking-wider mb-2">Edges</div>
              <div className="space-y-2 text-sm">
                {connectome.edges.map((edge, idx) => (
                  <div key={`${edge.source}-${edge.target}-${idx}`} className="border border-card-border rounded-lg p-3">
                    <div className="font-medium text-foreground">{edge.source} → {edge.target}</div>
                    <div className="text-xs text-muted mt-1">{edge.type}</div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </Card>
      )}

      {tab === "landings" && (
        <Card>
          <CardTitle>Landings</CardTitle>
          <div className="space-y-2 text-sm">
            {landings.landings.length === 0 ? (
              <div className="text-muted">No landing events recorded yet.</div>
            ) : (
              landings.landings.map((landing) => (
                <div key={landing.locus_barcode} className="border border-card-border rounded-lg p-3">
                  <div className="font-medium text-foreground">{landing.file_path}</div>
                  <div className="text-xs text-muted mt-1">
                    slot {landing.slot_id} · packet {landing.packet_id} · {landing.origin}
                  </div>
                </div>
              ))
            )}
          </div>
        </Card>
      )}

      {tab === "events" && (
        <Card>
          <CardTitle>Events</CardTitle>
          <div className="space-y-2 text-sm">
            {events.events.length === 0 ? (
              <div className="text-muted">No events recorded yet.</div>
            ) : (
              events.events.map((event) => (
                <div key={event.event_id} className="border border-card-border rounded-lg p-3">
                  <div className="font-medium text-foreground">{event.event_type}</div>
                  <div className="text-xs text-muted mt-1">{event.timestamp}</div>
                  <pre className="mt-2 text-xs text-muted whitespace-pre-wrap">{JSON.stringify(event.payload, null, 2)}</pre>
                </div>
              ))
            )}
          </div>
        </Card>
      )}

      {tab === "audits" && (
        <Card>
          <CardTitle>Audits</CardTitle>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
            <select
              value={auditFilters.slot}
              onChange={(e) => setAuditFilters((prev) => ({ ...prev, slot: e.target.value }))}
              className="bg-background border border-card-border rounded-lg px-3 py-2 text-sm text-foreground"
            >
              <option value="all">All slots</option>
              {auditSlots.map((slot) => <option key={slot} value={slot}>{slot}</option>)}
            </select>
            <select
              value={auditFilters.actionType}
              onChange={(e) => setAuditFilters((prev) => ({ ...prev, actionType: e.target.value }))}
              className="bg-background border border-card-border rounded-lg px-3 py-2 text-sm text-foreground"
            >
              <option value="all">All actions</option>
              {auditActionTypes.map((actionType) => <option key={actionType} value={actionType}>{actionType}</option>)}
            </select>
            <select
              value={auditFilters.actor}
              onChange={(e) => setAuditFilters((prev) => ({ ...prev, actor: e.target.value }))}
              className="bg-background border border-card-border rounded-lg px-3 py-2 text-sm text-foreground"
            >
              <option value="all">All actors</option>
              {auditActors.map((actor) => <option key={actor} value={actor}>{actor}</option>)}
            </select>
          </div>
          <div className="space-y-2 text-sm">
            {filteredAudits.length === 0 ? (
              <div className="text-muted">No audit actions recorded yet.</div>
            ) : (
              filteredAudits.map((audit) => (
                <div key={audit.id} className="border border-card-border rounded-lg p-3">
                  <div className="font-medium text-foreground">{audit.action_type}</div>
                  <div className="text-xs text-muted mt-1">
                    {audit.created_at} · {audit.slot_id || "run"} · {audit.actor}
                  </div>
                  <div className="text-sm text-muted mt-2">{audit.reason || "no reason recorded"}</div>
                  <pre className="mt-2 text-xs text-muted whitespace-pre-wrap">{JSON.stringify(audit.action_payload, null, 2)}</pre>
                </div>
              ))
            )}
          </div>
        </Card>
      )}

      {(retrograde || distill) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {retrograde && (
            <Card>
              <CardTitle>Retrograde Snapshot</CardTitle>
              <div className="space-y-3 text-sm">
                {retrograde.root_cause_summary ? (
                  <div className="border border-card-border rounded-lg p-3">
                    <div className="text-xs uppercase tracking-wider text-muted">Root Cause Summary</div>
                    <div className="font-medium text-foreground mt-1">
                      {retrograde.root_cause_summary.primary_kind ?? "unknown"}
                    </div>
                    {retrograde.root_cause_summary.primary_explanation ? (
                      <div className="text-xs text-muted mt-1">{retrograde.root_cause_summary.primary_explanation}</div>
                    ) : null}
                    {retrograde.root_cause_summary.narrative ? (
                      <div className="text-xs text-muted mt-2">{retrograde.root_cause_summary.narrative}</div>
                    ) : null}
                    {retrograde.root_cause_summary.confidence_band ? (
                      <div className="text-[11px] text-muted mt-2">
                        confidence band: {retrograde.root_cause_summary.confidence_band}
                      </div>
                    ) : null}
                    {retrograde.root_cause_summary.recommended_action ? (
                      <div className="text-[11px] text-muted mt-2">
                        next action: {retrograde.root_cause_summary.recommended_action}
                      </div>
                    ) : null}
                    {retrograde.root_cause_summary.actionability ? (
                      <div className="text-[11px] text-muted mt-2">
                        actionability: {retrograde.root_cause_summary.actionability}
                      </div>
                    ) : null}
                    {retrograde.root_cause_summary.dominant_cluster ? (
                      <div className="text-[11px] text-muted mt-2">
                        dominant cluster: {retrograde.root_cause_summary.dominant_cluster}
                      </div>
                    ) : null}
                    {typeof retrograde.root_cause_summary.evidence_count === "number" ? (
                      <div className="text-[11px] text-muted mt-2">
                        evidence count: {retrograde.root_cause_summary.evidence_count}
                      </div>
                    ) : null}
                    {retrograde.root_cause_summary.summary_version ? (
                      <div className="text-[11px] text-muted mt-2">
                        summary version: {retrograde.root_cause_summary.summary_version}
                      </div>
                    ) : null}
                    {typeof retrograde.root_cause_summary.confidence_score === "number" ? (
                      <div className="text-[11px] text-muted mt-2">
                        confidence score: {retrograde.root_cause_summary.confidence_score.toFixed(2)}
                      </div>
                    ) : null}
                    {retrograde.root_cause_summary.confidence_reason ? (
                      <div className="text-[11px] text-muted mt-2">
                        confidence reason: {retrograde.root_cause_summary.confidence_reason}
                      </div>
                    ) : null}
                    {retrograde.root_cause_summary.calibration ? (
                      <div className="text-[11px] text-muted mt-2">
                        calibration: {retrograde.root_cause_summary.calibration}
                      </div>
                    ) : null}
                    {retrograde.root_cause_summary.stability ? (
                      <div className="text-[11px] text-muted mt-2">
                        stability: {retrograde.root_cause_summary.stability}
                      </div>
                    ) : null}
                    {retrograde.root_cause_summary.stability_reason ? (
                      <div className="text-[11px] text-muted mt-2">
                        stability reason: {retrograde.root_cause_summary.stability_reason}
                      </div>
                    ) : null}
                    <div className="flex flex-wrap gap-2 mt-2 text-[11px] text-muted">
                      {retrograde.root_cause_summary.proof_pressure ? <span>proof pressure</span> : null}
                      {retrograde.root_cause_summary.governance_pressure ? <span>governance pressure</span> : null}
                      {retrograde.root_cause_summary.counterfactual_available ? <span>runner-up available</span> : null}
                    </div>
                    {retrograde.root_cause_summary.confidence_drivers?.length ? (
                      <div className="text-[11px] text-muted mt-2">
                        confidence drivers: {retrograde.root_cause_summary.confidence_drivers.join(", ")}
                      </div>
                    ) : null}
                    {retrograde.root_cause_summary.supporting_signals.length ? (
                      <div className="text-[11px] text-muted mt-2">
                        signals: {retrograde.root_cause_summary.supporting_signals.join(", ")}
                      </div>
                    ) : null}
                    {retrograde.root_cause_summary.clusters?.length ? (
                      <div className="mt-2 space-y-1">
                        {retrograde.root_cause_summary.clusters.map((cluster) => (
                          <div key={cluster.cluster} className="text-[11px] text-muted">
                            {cluster.cluster}: {cluster.top_kind ?? "unknown"} ({cluster.score.toFixed(2)})
                          </div>
                        ))}
                      </div>
                    ) : null}
                    {retrograde.root_cause_summary.decision_path?.length ? (
                      <div className="mt-2 space-y-1">
                        {retrograde.root_cause_summary.decision_path.map((step, idx) => (
                          <div key={`${step.kind}-${idx}`} className="text-[11px] text-muted">
                            {idx + 1}. {step.kind ?? "unknown"} ({step.score.toFixed(2)})
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {retrograde.cause_chain.map((item) => (
                  <div key={`${item.kind}-${item.id}`} className="border border-card-border rounded-lg p-3">
                    <div className="font-medium text-foreground">{item.kind}</div>
                    {typeof item.rank_score === "number" ? <div className="text-xs text-muted mt-1">score {item.rank_score.toFixed(2)}</div> : null}
                    <div className="text-xs text-muted mt-1">{item.explanation}</div>
                    {item.supporting_signals?.length ? (
                      <div className="text-[11px] text-muted mt-2">
                        signals: {item.supporting_signals.join(", ")}
                      </div>
                    ) : null}
                  </div>
                ))}
              </div>
            </Card>
          )}
          {distill && (
            <Card>
              <CardTitle>Distill Snapshot</CardTitle>
              <div className="space-y-2 text-sm">
                <div className="text-xs text-muted">Promotions: {distill.promotions.length}</div>
                <div className="text-xs text-muted">Downgrades: {distill.downgrades.length}</div>
                <div className="text-xs text-muted">Negative memory: {distill.negative_memory_updates.length}</div>
                <div className="text-xs text-muted">Action audits: {run?.summary.action_audits ?? audits.length}</div>
                <div className="text-xs text-muted">Governance recommendations: {distill.governance_recommendations.length}</div>
                {distill.governance_recommendations.map((rec, idx) => (
                  <div key={`${rec.kind}-${idx}`} className={`rounded-lg border p-3 ${severityTone(rec.severity)}`}>
                    <div className="text-xs uppercase tracking-wider">{rec.kind}</div>
                    <div className="text-xs mt-1">{rec.reason}</div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
