"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  approvePlan,
  executePlan,
  getPlan,
  swapPlanCandidate,
  type ApplicationPacket,
  type PlanDetail,
} from "@/lib/api";
import { Card, CardTitle, StatCard } from "@/components/card";
import { ErrorBanner } from "@/components/error-banner";

function PacketDetail({
  packet,
  onSwap,
  swapping,
}: {
  packet: ApplicationPacket;
  onSwap: (componentId: string) => Promise<void>;
  swapping: boolean;
}) {
  return (
    <Card>
      <CardTitle>{packet.slot.name.replace(/_/g, " ")}</CardTitle>
      <div className="space-y-4 text-sm">
        <div>
          <div className="text-xs text-muted uppercase tracking-wider mb-1">Selected Component</div>
          <div className="font-medium text-foreground">{packet.selected.title}</div>
          <div className="text-xs text-muted mt-1 font-mono break-all">
            {packet.selected.receipt.repo} :: {packet.selected.receipt.file_path}
            {packet.selected.receipt.symbol ? ` :: ${packet.selected.receipt.symbol}` : ""}
          </div>
          <div className="flex flex-wrap gap-2 mt-2 text-xs">
            <span className="px-2 py-0.5 rounded bg-card-border text-foreground">{packet.selected.fit_bucket}</span>
            <span className="px-2 py-0.5 rounded bg-card-border text-foreground">{packet.selected.transfer_mode}</span>
            <span className="px-2 py-0.5 rounded bg-card-border text-foreground">
              {Math.round(packet.selected.confidence * 100)}%
            </span>
          </div>
        </div>

        <div>
          <div className="text-xs text-muted uppercase tracking-wider mb-1">Why Selected</div>
          <ul className="space-y-1 text-foreground">
            {packet.why_selected.map((reason) => (
              <li key={reason}>• {reason}</li>
            ))}
          </ul>
        </div>

        <div>
          <div className="text-xs text-muted uppercase tracking-wider mb-1">Adaptation Plan</div>
          <ul className="space-y-1 text-foreground">
            {packet.adaptation_plan.map((step) => (
              <li key={step.step_id}>• {step.title}</li>
            ))}
          </ul>
        </div>

        <div>
          <div className="text-xs text-muted uppercase tracking-wider mb-1">Proof Plan</div>
          <div className="flex flex-wrap gap-2">
            {packet.proof_plan.map((gate) => (
              <span key={gate.gate_id} className="px-2 py-0.5 rounded bg-card-border text-foreground text-xs">
                {gate.gate_type}
              </span>
            ))}
          </div>
        </div>

        <div>
          <div className="text-xs text-muted uppercase tracking-wider mb-1">Runner-ups</div>
          {packet.runner_ups.length === 0 ? (
            <div className="text-xs text-muted">{packet.no_viable_runner_up_reason || "No viable runner-up"}</div>
          ) : (
            <div className="space-y-2">
              {packet.runner_ups.map((candidate) => (
                <div key={candidate.component_id} className="border border-card-border rounded-lg p-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-foreground">{candidate.title}</div>
                      <div className="text-xs text-muted mt-1">
                        {candidate.fit_bucket} · {candidate.transfer_mode} · {Math.round(candidate.confidence * 100)}%
                      </div>
                    </div>
                    <button
                      onClick={() => onSwap(candidate.component_id)}
                      disabled={swapping}
                      className="px-3 py-1.5 rounded-lg bg-card-border hover:bg-card-hover disabled:opacity-50 text-xs text-foreground"
                    >
                      Swap In
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>

        {packet.review_required_reasons.length > 0 && (
          <div>
            <div className="text-xs text-muted uppercase tracking-wider mb-1">Review Required Because</div>
            <div className="flex flex-wrap gap-2">
              {packet.review_required_reasons.map((reason) => (
                <span key={reason} className="px-2 py-0.5 rounded bg-amber-500/10 text-amber-300 text-xs">
                  {reason}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

export default function PlanReviewPage() {
  const params = useParams<{ planId: string }>();
  const router = useRouter();
  const planId = params.planId;
  const [plan, setPlan] = useState<PlanDetail | null>(null);
  const [selectedSlotId, setSelectedSlotId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!planId) return;
    let cancelled = false;
    const load = async () => {
      try {
        setLoading(true);
        const detail = await getPlan(planId);
        if (cancelled) return;
        setPlan(detail);
        setSelectedSlotId((current) => current || detail.slots[0]?.slot_id || null);
        setError(null);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [planId]);

  const selectedPacket = useMemo(() => {
    if (!plan || !selectedSlotId) return null;
    return plan.packets.find((packet) => packet.slot.slot_id === selectedSlotId) || null;
  }, [plan, selectedSlotId]);

  const reload = async () => {
    if (!planId) return;
    const detail = await getPlan(planId);
    setPlan(detail);
    setSelectedSlotId((current) => current || detail.slots[0]?.slot_id || null);
  };

  const handleApprove = async () => {
    if (!plan) return;
    try {
      setActing(true);
      await approvePlan(plan.plan_id);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setActing(false);
    }
  };

  const handleExecute = async () => {
    if (!plan) return;
    try {
      setActing(true);
      const result = await executePlan(plan.plan_id, plan.approved_slot_ids);
      router.push(result.redirect_to);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setActing(false);
    }
  };

  const handleSwap = async (componentId: string) => {
    if (!plan || !selectedSlotId) return;
    try {
      setActing(true);
      await swapPlanCandidate(plan.plan_id, selectedSlotId, componentId, "Manual packet review swap");
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setActing(false);
    }
  };

  if (loading) {
    return <div className="text-sm text-muted">Loading plan review...</div>;
  }

  if (!plan) {
    return <ErrorBanner message={error || "Plan not found"} />;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Pre-Mutation Plan Review</h1>
          <p className="text-muted mt-1">Inspect slot packets before any code is written.</p>
        </div>
        <div className="flex gap-2">
          <Link
            href="/playground"
            className="px-4 py-2 bg-card-border hover:bg-card-hover text-foreground text-sm font-medium rounded-lg transition-colors"
          >
            Back
          </Link>
          <button
            onClick={handleApprove}
            disabled={acting}
            className="px-4 py-2 bg-card-border hover:bg-card-hover disabled:opacity-50 text-foreground text-sm font-medium rounded-lg transition-colors"
          >
            Approve All
          </button>
          <button
            onClick={handleExecute}
            disabled={acting || plan.approved_slot_ids.length === 0}
            className="px-4 py-2 bg-accent hover:bg-accent-hover disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
          >
            Execute Approved Plan
          </button>
        </div>
      </div>

      {error && <ErrorBanner message={error} onRetry={() => setError(null)} />}

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatCard label="Archetype" value={plan.task_archetype} sub={`${Math.round(plan.archetype_confidence * 100)}% confidence`} />
        <StatCard label="Slots" value={plan.summary.total_slots} sub={`${plan.summary.critical_slots} critical`} />
        <StatCard label="Weak Evidence" value={plan.summary.weak_evidence_slots} sub={plan.status} />
      </div>

      <Card>
        <CardTitle>Task</CardTitle>
        <div className="text-sm text-foreground">{plan.task_text}</div>
        {plan.workspace_dir && <div className="text-xs text-muted mt-2 font-mono">{plan.workspace_dir}</div>}
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-5 gap-6">
        <div className="xl:col-span-2 space-y-3">
          <Card>
            <CardTitle>Slots</CardTitle>
            <div className="space-y-2">
              {plan.slots.map((slot) => (
                <button
                  key={slot.slot_id}
                  onClick={() => setSelectedSlotId(slot.slot_id)}
                  className={`w-full text-left border rounded-lg p-3 transition-colors ${
                    selectedSlotId === slot.slot_id
                      ? "border-accent bg-accent/5"
                      : "border-card-border hover:bg-card-border/30"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <div className="text-sm font-medium text-foreground">{slot.name.replace(/_/g, " ")}</div>
                      <div className="text-xs text-muted mt-1">
                        {slot.risk} · {Math.round(slot.confidence * 100)}%
                      </div>
                    </div>
                    <div className="flex flex-col gap-1 items-end text-xs">
                      <span className="px-2 py-0.5 rounded bg-card-border text-foreground">{slot.status}</span>
                      <span className="px-2 py-0.5 rounded bg-card-border text-foreground">{slot.coverage_state}</span>
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </Card>
        </div>

        <div className="xl:col-span-3">
          {selectedPacket ? (
            <PacketDetail packet={selectedPacket} onSwap={handleSwap} swapping={acting} />
          ) : (
            <Card>
              <CardTitle>Packet Detail</CardTitle>
              <div className="text-sm text-muted">Select a slot to inspect its packet.</div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
