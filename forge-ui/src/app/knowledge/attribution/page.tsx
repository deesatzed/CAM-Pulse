"use client";

import { useEffect, useState } from "react";
import {
  getAttributionProof,
  type AttributionProof,
  type AttributionMethodologyEntry,
} from "@/lib/api";
import { Card, CardTitle } from "@/components/card";
import { Skeleton, SkeletonCard } from "@/components/skeleton";
import { ErrorBanner } from "@/components/error-banner";

// ---------------------------------------------------------------------------
// Funnel bar
// ---------------------------------------------------------------------------

function FunnelBar({
  label,
  value,
  max,
  color,
}: {
  label: string;
  value: number;
  max: number;
  color: string;
}) {
  const pct = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="flex items-center gap-3">
      <span className="w-24 text-xs text-muted text-right">{label}</span>
      <div className="flex-1 h-6 bg-card-border/30 rounded overflow-hidden relative">
        <div
          className="h-full rounded transition-all duration-700"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
        <span className="absolute inset-0 flex items-center justify-center text-xs font-mono text-foreground">
          {value.toLocaleString()}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Methodology table
// ---------------------------------------------------------------------------

function MethodologyTable({
  entries,
  title,
}: {
  entries: AttributionMethodologyEntry[];
  title: string;
}) {
  if (entries.length === 0) return null;

  return (
    <Card>
      <CardTitle>{title}</CardTitle>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-muted text-xs border-b border-card-border">
              <th className="pb-2 pr-3">Methodology</th>
              <th className="pb-2 pr-3 text-right">State</th>
              <th className="pb-2 pr-3 text-right">Retrieved</th>
              <th className="pb-2 pr-3 text-right">Applied</th>
              <th className="pb-2 pr-3 text-right">Success</th>
              <th className="pb-2 pr-3 text-right">Apply %</th>
              <th className="pb-2 text-right">Success %</th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr
                key={e.methodology_id}
                className="border-b border-card-border/50 hover:bg-card-border/20"
              >
                <td className="py-1.5 pr-3 max-w-[300px] truncate" title={e.title}>
                  {e.title}
                </td>
                <td className="py-1.5 pr-3 text-right text-xs text-muted">
                  {e.lifecycle}
                </td>
                <td className="py-1.5 pr-3 text-right font-mono">{e.retrieved}</td>
                <td className="py-1.5 pr-3 text-right font-mono">{e.applied}</td>
                <td className="py-1.5 pr-3 text-right font-mono text-green-400">
                  {e.success}
                </td>
                <td className="py-1.5 pr-3 text-right font-mono">
                  {e.retrieved > 0
                    ? `${(e.applied_rate * 100).toFixed(0)}%`
                    : "-"}
                </td>
                <td className="py-1.5 text-right font-mono">
                  {e.applied > 0
                    ? `${(e.success_rate * 100).toFixed(0)}%`
                    : "-"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function AttributionPage() {
  const [proof, setProof] = useState<AttributionProof | null>(null);
  const [error, setError] = useState<string>("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getAttributionProof()
      .then(setProof)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="space-y-6 p-6">
        <Skeleton className="h-8 w-64" />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  if (error) return <ErrorBanner message={error} />;
  if (!proof) return <ErrorBanner message="No attribution data available" />;

  const { funnel } = proof;
  const funnelMax = Math.max(
    funnel.total_retrieved,
    funnel.total_applied,
    funnel.total_success,
    1,
  );

  return (
    <div className="space-y-6 p-6 max-w-5xl">
      <h1 className="text-2xl font-bold">Attribution Proof</h1>
      <p className="text-muted text-sm">
        System-wide funnel: methodologies retrieved → applied in outcomes →
        attributed to successful tasks.
      </p>

      {/* Funnel visualization */}
      <Card>
        <CardTitle>Knowledge Funnel</CardTitle>
        <div className="space-y-3 mt-3">
          <FunnelBar
            label="Retrieved"
            value={funnel.total_retrieved}
            max={funnelMax}
            color="#58a6ff"
          />
          <FunnelBar
            label="Applied"
            value={funnel.total_applied}
            max={funnelMax}
            color="#f0883e"
          />
          <FunnelBar
            label="Succeeded"
            value={funnel.total_success}
            max={funnelMax}
            color="#3fb950"
          />
          {funnel.total_failure > 0 && (
            <FunnelBar
              label="Failed"
              value={funnel.total_failure}
              max={funnelMax}
              color="#f85149"
            />
          )}
        </div>
      </Card>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <div className="text-xs text-muted">Methodologies Tracked</div>
          <div className="text-2xl font-bold">{proof.methodology_count}</div>
        </Card>
        <Card>
          <div className="text-xs text-muted">Applied Rate</div>
          <div className="text-2xl font-bold">
            {(funnel.applied_rate * 100).toFixed(1)}%
          </div>
        </Card>
        <Card>
          <div className="text-xs text-muted">Success Rate</div>
          <div className="text-2xl font-bold text-green-400">
            {(funnel.success_rate * 100).toFixed(1)}%
          </div>
        </Card>
        <Card>
          <div className="text-xs text-muted">Never Applied</div>
          <div className="text-2xl font-bold text-amber-400">
            {proof.never_applied_count}
          </div>
        </Card>
      </div>

      {/* Per-methodology table */}
      <MethodologyTable
        title="Per-Methodology Performance"
        entries={proof.per_methodology}
      />

      {/* Never-applied list */}
      {proof.never_applied.length > 0 && (
        <>
          <MethodologyTable
            title="Never Applied (Retrieved but Unused)"
            entries={proof.never_applied}
          />
          <p className="text-xs text-muted -mt-4">
            Note: methodologies tagged <code>origin:seed</code> are curated
            archetypes and are intentionally protected from the zombie
            demotion rule. Seeing them listed here with 0 applied is expected
            behaviour — they persist as reference patterns whether or not they
            have been applied yet.
          </p>
        </>
      )}
    </div>
  );
}
