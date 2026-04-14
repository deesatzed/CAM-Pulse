"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  createMiningMission,
  getRunAudits,
  getRunDistill,
  getRunRetrograde,
  promoteGovernancePolicy,
  promoteRunRecipe,
  type DistillResponse,
  type RetrogradeResponse,
  type RunActionAudit,
} from "@/lib/api";
import { Card, CardTitle } from "@/components/card";
import { ErrorBanner } from "@/components/error-banner";

function TabButton({ active, onClick, label }: { active: boolean; onClick: () => void; label: string }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-2 rounded-lg text-sm transition-colors ${active ? "bg-accent text-white" : "bg-card-border text-foreground hover:bg-card-hover"}`}
    >
      {label}
    </button>
  );
}

function severityTone(severity: "low" | "medium" | "high" | string): string {
  if (severity === "high") return "border-red-400/30 bg-red-400/10 text-red-300";
  if (severity === "medium") return "border-amber-400/30 bg-amber-400/10 text-amber-200";
  return "border-cam-green/30 bg-cam-green/10 text-cam-green";
}

export default function EvolutionRunPage() {
  const params = useParams<{ runId: string }>();
  const runId = params.runId;
  const [tab, setTab] = useState<"retrograde" | "distill" | "audits">("retrograde");
  const [retrograde, setRetrograde] = useState<RetrogradeResponse | null>(null);
  const [distill, setDistill] = useState<DistillResponse | null>(null);
  const [audits, setAudits] = useState<RunActionAudit[]>([]);
  const [auditFilters, setAuditFilters] = useState<{ slot: string; actionType: string; actor: string }>({
    slot: "all",
    actionType: "all",
    actor: "all",
  });
  const [error, setError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [acting, setActing] = useState(false);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    const load = async () => {
      try {
        const [retro, dist, auditResp] = await Promise.all([getRunRetrograde(runId), getRunDistill(runId), getRunAudits(runId)]);
        if (cancelled) return;
        setRetrograde(retro);
        setDistill(dist);
        setAudits(auditResp.audits);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const filteredAudits = audits.filter((audit) => {
    if (auditFilters.slot !== "all" && (audit.slot_id || "run") !== auditFilters.slot) return false;
    if (auditFilters.actionType !== "all" && audit.action_type !== auditFilters.actionType) return false;
    if (auditFilters.actor !== "all" && audit.actor !== auditFilters.actor) return false;
    return true;
  });
  const auditSlots = Array.from(new Set(audits.map((audit) => audit.slot_id || "run")));
  const auditActionTypes = Array.from(new Set(audits.map((audit) => audit.action_type)));
  const auditActors = Array.from(new Set(audits.map((audit) => audit.actor)));

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Evolution Run Analysis</h1>
          <p className="text-muted mt-1">Run <span className="font-mono text-foreground">{runId}</span></p>
        </div>
        <div className="flex gap-3">
          <Link href={`/forge/run/${runId}`} className="text-sm text-accent hover:text-accent-hover">
            Back to Sequencing Console
          </Link>
          <Link href="/evolution" className="text-sm text-muted hover:text-foreground">
            Evolution Lab
          </Link>
        </div>
      </div>

      {error && <ErrorBanner message={error} onRetry={() => setError(null)} />}
      {actionMessage && <div className="text-sm text-cam-green bg-cam-green/10 border border-cam-green/20 rounded-lg px-4 py-3">{actionMessage}</div>}

      <div className="flex gap-2">
        <TabButton active={tab === "retrograde"} onClick={() => setTab("retrograde")} label="Retrograde" />
        <TabButton active={tab === "distill"} onClick={() => setTab("distill")} label="Distill" />
        <TabButton active={tab === "audits"} onClick={() => setTab("audits")} label="Audits" />
      </div>

      {tab === "retrograde" && (
        <Card>
          <CardTitle>Retrograde</CardTitle>
          {!retrograde ? (
            <div className="text-sm text-muted">Loading retrograde analysis...</div>
          ) : (
            <div className="space-y-4 text-sm">
              <div>
                <div className="text-xs text-muted uppercase tracking-wider mb-1">Confidence</div>
                <div className="text-foreground">{Math.round(retrograde.confidence * 100)}%</div>
              </div>
              {retrograde.root_cause_summary ? (
                <div>
                  <div className="text-xs text-muted uppercase tracking-wider mb-1">Root Cause Summary</div>
                  <div className="border border-card-border rounded-lg p-3">
                    <div className="font-medium text-foreground">
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
                    <div className="flex flex-wrap gap-2 text-[11px] text-muted mt-2">
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
                </div>
              ) : null}
              <div>
                <div className="text-xs text-muted uppercase tracking-wider mb-1">Cause Chain</div>
                <div className="space-y-2">
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
              </div>
              {retrograde.runner_up_analysis && (
                <div>
                  <div className="text-xs text-muted uppercase tracking-wider mb-1">Runner-up</div>
                  <div className="border border-card-border rounded-lg p-3">
                    <div className="font-medium text-foreground">{retrograde.runner_up_analysis.component_id}</div>
                    {retrograde.runner_up_analysis.transfer_mode ? (
                      <div className="text-xs text-muted mt-1">
                        transfer mode {retrograde.runner_up_analysis.transfer_mode}
                      </div>
                    ) : null}
                    <ul className="text-xs text-muted mt-2 space-y-1">
                      {retrograde.runner_up_analysis.why.map((reason) => (
                        <li key={reason}>• {reason}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
            </div>
          )}
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
              <div className="text-sm text-muted">No audit actions recorded yet.</div>
            ) : (
              filteredAudits.map((audit) => (
                <div key={audit.id} className="border border-card-border rounded-lg p-3">
                  <div className="font-medium text-foreground">{audit.action_type}</div>
                  <div className="text-xs text-muted mt-1">
                    {audit.created_at} · {audit.slot_id || "run"} · {audit.actor}
                  </div>
                  <div className="text-xs text-muted mt-2">{audit.reason || "no reason recorded"}</div>
                  <pre className="mt-2 text-xs text-muted whitespace-pre-wrap bg-background border border-card-border rounded-lg p-3">{JSON.stringify(audit.action_payload, null, 2)}</pre>
                </div>
              ))
            )}
          </div>
        </Card>
      )}

      {tab === "distill" && (
        <Card>
          <CardTitle>Distill</CardTitle>
          {!distill ? (
            <div className="text-sm text-muted">Loading distill analysis...</div>
          ) : (
            <div className="space-y-4 text-sm">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="border border-card-border rounded-lg p-3">
                  <div className="text-xs text-muted uppercase tracking-wider">Promotions</div>
                  <div className="text-lg font-semibold text-foreground mt-1">{distill.promotions.length}</div>
                </div>
                <div className="border border-card-border rounded-lg p-3">
                  <div className="text-xs text-muted uppercase tracking-wider">Downgrades</div>
                  <div className="text-lg font-semibold text-foreground mt-1">{distill.downgrades.length}</div>
                </div>
                <div className="border border-card-border rounded-lg p-3">
                  <div className="text-xs text-muted uppercase tracking-wider">Negative Memory</div>
                  <div className="text-lg font-semibold text-foreground mt-1">{distill.negative_memory_updates.length}</div>
                </div>
              </div>
              <div>
                <div className="text-xs text-muted uppercase tracking-wider mb-1">Recipe Candidates</div>
                <pre className="text-xs text-muted whitespace-pre-wrap bg-background border border-card-border rounded-lg p-3">{JSON.stringify(distill.recipe_candidates, null, 2)}</pre>
              </div>
              <div>
                <div className="text-xs text-muted uppercase tracking-wider mb-1">Packet Transfer Summary</div>
                <pre className="text-xs text-muted whitespace-pre-wrap bg-background border border-card-border rounded-lg p-3">{JSON.stringify(distill.packet_transfer_summary, null, 2)}</pre>
              </div>
              <div>
                <div className="text-xs text-muted uppercase tracking-wider mb-1">Governance Recommendations</div>
                <div className="space-y-3">
                  {distill.governance_recommendations.length === 0 ? (
                    <div className="text-xs text-muted">No governance recommendations for this run.</div>
                  ) : (
                    distill.governance_recommendations.map((recommendation, idx) => (
                      <div key={`${recommendation.kind}-${idx}`} className={`rounded-lg border p-3 ${severityTone(recommendation.severity)}`}>
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="text-xs uppercase tracking-wider">{recommendation.kind}</div>
                            <div className="text-sm mt-2">{recommendation.reason}</div>
                            <div className="text-xs mt-2 opacity-90">{recommendation.recommendation}</div>
                          </div>
                          <button
                            type="button"
                            disabled={acting}
                            onClick={async () => {
                              try {
                                setActing(true);
                                const result = await promoteGovernancePolicy(runId, {
                                  policy_kind: recommendation.kind,
                                  severity: recommendation.severity,
                                  reason: recommendation.reason,
                                  recommendation: recommendation.recommendation,
                                  evidence_json: {
                                    source: "run_distill",
                                    run_id: runId,
                                    task_archetype: distill.task_archetype,
                                  },
                                });
                                setActionMessage(`Promoted governance policy ${result.policy.id}`);
                              } catch (e) {
                                setError(e instanceof Error ? e.message : String(e));
                              } finally {
                                setActing(false);
                              }
                            }}
                            className="px-3 py-2 rounded-lg bg-background border border-card-border text-xs text-foreground hover:bg-card-hover disabled:opacity-50"
                          >
                            Promote Policy
                          </button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
              <div>
                <div className="text-xs text-muted uppercase tracking-wider mb-1">Federation Recommendations</div>
                <div className="space-y-3">
                  {distill.federation_recommendations.length === 0 ? (
                    <div className="text-xs text-muted">No federation-specific recommendations for this run.</div>
                  ) : (
                    distill.federation_recommendations.map((recommendation, idx) => (
                      <div key={`${recommendation.kind}-${idx}`} className={`rounded-lg border p-3 ${severityTone(recommendation.severity)}`}>
                        <div className="text-xs uppercase tracking-wider">{recommendation.kind}</div>
                        <div className="text-sm mt-2">{recommendation.reason}</div>
                        <div className="text-xs mt-2 opacity-90">{recommendation.recommendation}</div>
                      </div>
                    ))
                  )}
                </div>
              </div>
              <div className="flex gap-3">
                <button
                  onClick={async () => {
                    try {
                      setActing(true);
                      const result = await promoteRunRecipe(runId, {
                        recipe_name: `${distill.task_archetype || "run"}_v1`,
                        minimum_sample_size: 1,
                      });
                      setActionMessage(`Promoted recipe ${String(result.recipe["recipe_name"] || "unknown")}`);
                    } catch (e) {
                      setError(e instanceof Error ? e.message : String(e));
                    } finally {
                      setActing(false);
                    }
                  }}
                  disabled={acting}
                  className="px-4 py-2 bg-accent hover:bg-accent-hover disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors"
                >
                  Promote Recipe
                </button>
                <button
                  onClick={async () => {
                    try {
                      setActing(true);
                      const result = await createMiningMission(runId, {
                        slot_family: String(distill.task_archetype || "unknown_gap"),
                        priority: "high",
                        reason: "Promote direct-fit coverage from retrograde/distill analysis",
                      });
                      setActionMessage(`Queued mining mission ${result.mission.id}`);
                    } catch (e) {
                      setError(e instanceof Error ? e.message : String(e));
                    } finally {
                      setActing(false);
                    }
                  }}
                  disabled={acting}
                  className="px-4 py-2 bg-card-border hover:bg-card-hover disabled:opacity-50 text-foreground text-sm font-medium rounded-lg transition-colors"
                >
                  Queue Mining Mission
                </button>
              </div>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
