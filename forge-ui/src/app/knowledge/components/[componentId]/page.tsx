"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { getComponent, getComponentHistory, type ComponentDetailResponse, type ComponentHistoryResponse } from "@/lib/api";
import { Card, CardTitle, StatCard } from "@/components/card";
import { LangBadge } from "@/components/badge";
import { SkeletonCard, SkeletonGrid } from "@/components/skeleton";
import { ErrorBanner } from "@/components/error-banner";

function CoverageBadge({ state }: { state: string }) {
  const colors: Record<string, string> = {
    covered: "#3fb950",
    weak: "#f0883e",
    uncovered: "#f85149",
    quarantined: "#d2a8ff",
    clone_inflated: "#79c0ff",
  };
  const color = colors[state] || "#8b949e";
  return (
    <span className="inline-block px-2 py-0.5 rounded text-xs" style={{ backgroundColor: `${color}18`, color }}>
      {state}
    </span>
  );
}

export default function ComponentDetailPage() {
  const params = useParams();
  const componentId = params.componentId as string;
  const [detail, setDetail] = useState<ComponentDetailResponse | null>(null);
  const [history, setHistory] = useState<ComponentHistoryResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!componentId) return;
    setLoading(true);
    setError(null);
    try {
      const [detailData, historyData] = await Promise.all([
        getComponent(componentId),
        getComponentHistory(componentId),
      ]);
      setDetail(detailData);
      setHistory(historyData);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [componentId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <div className="space-y-6">
        <SkeletonCard />
        <SkeletonGrid count={4} />
      </div>
    );
  }

  if (error || !detail || !history) {
    return (
      <div className="space-y-4">
        <Link href="/knowledge/components" className="text-accent hover:text-accent-hover text-sm inline-block">
          &larr; Back to Components
        </Link>
        <ErrorBanner message="Failed to load component" detail={error || "Component not found"} onRetry={() => { void load(); }} />
      </div>
    );
  }

  const component = detail.component;
  return (
    <div className="space-y-6">
      <Link href="/knowledge/components" className="text-accent hover:text-accent-hover text-sm inline-block">
        &larr; Back to Components
      </Link>

      <Card>
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <CoverageBadge state={component.coverage_state} />
          <LangBadge lang={component.language || "unknown"} />
          <span className="inline-block px-2 py-0.5 rounded text-xs bg-card-border/60 text-muted">{component.component_type}</span>
        </div>
        <h1 className="text-2xl font-bold text-foreground mb-1">{component.title}</h1>
        <div className="text-xs text-muted font-mono break-all mb-4">{component.id}</div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-sm">
          <div>
            <div className="text-muted mb-1">Receipt</div>
            <div className="font-mono break-all">{component.receipt.file_path}</div>
            {component.receipt.symbol && <div className="font-mono">{component.receipt.symbol}</div>}
            <div className="text-muted mt-1">{component.receipt.provenance_precision}</div>
          </div>
          <div>
            <div className="text-muted mb-1">Lineage</div>
            <div className="font-mono break-all">{detail.lineage?.id || component.receipt.lineage_id}</div>
            <div className="text-muted mt-1">family: {component.receipt.family_barcode}</div>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Success" value={component.success_count} />
        <StatCard label="Failure" value={component.failure_count} />
        <StatCard label="Fit Rows" value={detail.fit_history.length} />
        <StatCard label="Packet History" value={history.packet_history.length} />
      </div>

      <Card>
        <CardTitle>Governance Summary</CardTitle>
        {!detail.governance_summary || !detail.governance_summary.active_policy_count ? (
          <div className="text-sm text-muted">No active family policies for this component lineage.</div>
        ) : (
          <div className="space-y-3 text-sm">
            <div className="text-muted">
              family {detail.governance_summary.family_barcode} · active policies {detail.governance_summary.active_policy_count}
              {detail.governance_summary.highest_severity ? ` · highest severity ${detail.governance_summary.highest_severity}` : ""}
            </div>
            {detail.governance_summary.policies.map((policy, idx) => (
              <div key={`${String(policy.id || idx)}`} className="border border-card-border rounded-lg p-3">
                <div className="font-medium text-foreground">{String(policy.policy_kind || "policy")}</div>
                <div className="text-xs text-muted mt-1">{String(policy.severity || "")} · {String(policy.status || "")}</div>
                <div className="text-xs text-muted mt-2">{String(policy.reason || policy.recommendation || "")}</div>
              </div>
            ))}
          </div>
        )}
      </Card>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card>
          <CardTitle>Applicability</CardTitle>
          <ul className="space-y-2 text-sm text-foreground">
            {component.applicability.length ? component.applicability.map((item) => <li key={item}>- {item}</li>) : <li className="text-muted">No applicability notes.</li>}
          </ul>
        </Card>
        <Card>
          <CardTitle>Non-Applicability / Risk</CardTitle>
          <ul className="space-y-2 text-sm text-foreground">
            {[...component.non_applicability, ...component.risk_notes].length
              ? [...component.non_applicability, ...component.risk_notes].map((item, idx) => <li key={`${item}-${idx}`}>- {item}</li>)
              : <li className="text-muted">No known failure modes recorded.</li>}
          </ul>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <Card>
          <CardTitle>Fit History</CardTitle>
          <div className="space-y-3">
            {detail.fit_history.length ? detail.fit_history.map((fit) => (
              <div key={fit.id} className="border border-card-border rounded-lg p-3 text-sm">
                <div className="font-medium text-foreground">{fit.slot_signature || fit.component_type || "generic"}</div>
                <div className="text-muted">{fit.fit_bucket} / {fit.transfer_mode}</div>
                <div className="text-xs text-muted mt-1">confidence {fit.confidence.toFixed(2)}</div>
              </div>
            )) : <div className="text-sm text-muted">No fit history yet.</div>}
          </div>
        </Card>
        <Card>
          <CardTitle>History</CardTitle>
          <div className="space-y-3 text-sm">
            <div>
              <div className="text-muted mb-1">Lineage Components</div>
              {history.lineage_components.length ? history.lineage_components.map((item) => (
                <div key={item.id} className="font-mono text-xs break-all">{item.title} · {item.file_path}</div>
              )) : <div className="text-muted">No lineage siblings.</div>}
            </div>
            <div>
              <div className="text-muted mb-1">Packet History</div>
              {history.packet_history.length ? history.packet_history.map((item) => (
                <div key={item.packet_id} className="font-mono text-xs break-all">{item.task_archetype} · {item.slot_name} · {item.fit_bucket}</div>
              )) : <div className="text-muted">No packet history yet.</div>}
            </div>
          </div>
        </Card>
      </div>
    </div>
  );
}
