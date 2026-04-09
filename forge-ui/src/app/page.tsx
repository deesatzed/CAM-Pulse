"use client";

import { useEffect, useState } from "react";
import { getStats, type BrainStats } from "@/lib/api";
import { Card, CardTitle, StatCard } from "@/components/card";
import { GanglionBadge } from "@/components/badge";
import { SkeletonGrid } from "@/components/skeleton";
import { ErrorBanner } from "@/components/error-banner";

export default function DashboardHome() {
  const [stats, setStats] = useState<BrainStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getStats().then(setStats).catch((e) => setError(e.message));
  }, []);

  if (error) return <ErrorBanner message="Failed to load brain stats" detail={error} onRetry={() => { setError(null); getStats().then(setStats).catch((e) => setError(e.message)); }} />;
  if (!stats) return <div className="space-y-6"><div className="mb-8"><div className="h-8 w-64 bg-card-border rounded animate-pulse" /><div className="h-4 w-96 bg-card-border rounded animate-pulse mt-2" /></div><SkeletonGrid count={4} /></div>;

  const { primary, siblings, total_across_brain } = stats;

  return (
    <div>
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground">CAM-PULSE Brain Dashboard</h1>
        <p className="text-muted mt-1">Federated knowledge explorer — querying all ganglia simultaneously</p>
        <div className="text-4xl font-bold text-accent mt-2">
          {total_across_brain.toLocaleString()}{" "}
          <span className="text-base font-normal text-muted">methodologies across the CAM Brain</span>
        </div>
      </div>

      {/* Ganglion cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-8">
        <Card className="border-accent/30">
          <div className="flex items-center gap-2 mb-2">
            <GanglionBadge name="primary" />
            <span className="text-sm text-muted">Primary Ganglion</span>
          </div>
          <div className="text-3xl font-bold text-foreground">{primary.active.toLocaleString()}</div>
          <div className="text-xs text-muted mt-1">active methodologies</div>
          <div className="text-xs text-muted-dark mt-1">
            {primary.source_repos} source repos | {Object.keys(primary.languages).length} languages
          </div>
        </Card>
        {siblings.map((sib) => (
          <Card key={sib.name}>
            <div className="flex items-center gap-2 mb-2">
              <GanglionBadge name={sib.name} />
              <span className={`text-xs ${sib.db_exists ? "text-cam-green" : "text-red-400"}`}>
                {sib.db_exists ? "online" : "offline"}
              </span>
            </div>
            <div className="text-3xl font-bold text-foreground">{(sib.methodology_count ?? 0).toLocaleString()}</div>
            <div className="text-xs text-muted mt-1">methodologies</div>
            {sib.description && <div className="text-xs text-muted-dark mt-1">{sib.description.slice(0, 60)}</div>}
          </Card>
        ))}
      </div>

      {/* Stats panels */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardTitle>Lifecycle Distribution</CardTitle>
          {Object.entries(primary.lifecycle)
            .sort(([, a], [, b]) => b - a)
            .map(([state, count]) => {
              const max = Math.max(...Object.values(primary.lifecycle));
              const pct = max > 0 ? (count / max) * 100 : 0;
              return (
                <div key={state} className="flex items-center gap-3 mb-2">
                  <span className="w-20 text-right text-xs text-muted">{state}</span>
                  <div className="flex-1 h-2 bg-card-border rounded-full overflow-hidden">
                    <div
                      className="h-full bg-gradient-to-r from-accent to-accent-hover rounded-full"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="w-12 text-xs text-muted">{count.toLocaleString()}</span>
                </div>
              );
            })}
        </Card>
        <Card>
          <CardTitle>Top Knowledge Domains</CardTitle>
          <div className="flex flex-wrap gap-2">
            {Object.entries(primary.top_categories).map(([cat, count]) => (
              <span key={cat} className="inline-flex items-center gap-1.5 px-3 py-1 bg-card-border rounded-md text-xs text-foreground">
                {cat}
                <strong className="text-accent">{count}</strong>
              </span>
            ))}
          </div>
        </Card>
      </div>

      {/* Quick stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-6">
        <StatCard label="Total" value={primary.total} sub="all methodologies" />
        <StatCard label="Active" value={primary.active} sub="non-dead/dormant" />
        <StatCard label="Source Repos" value={primary.source_repos} sub="mined repositories" />
        <StatCard label="Languages" value={Object.keys(primary.languages).length} sub="programming languages" />
      </div>
    </div>
  );
}
