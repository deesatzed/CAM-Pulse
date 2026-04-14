"use client";

import Link from "next/link";
import { useState } from "react";
import { searchComponents, type ComponentCardSummary } from "@/lib/api";
import { Card, CardTitle } from "@/components/card";
import { LangBadge } from "@/components/badge";
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

function SourceBadge({ scope }: { scope?: "memory" | "workspace" }) {
  if (!scope) return null;
  const isWorkspace = scope === "workspace";
  return (
    <span
      className="inline-block px-2 py-0.5 rounded text-xs"
      style={{
        backgroundColor: isWorkspace ? "#79c0ff18" : "#3fb95018",
        color: isWorkspace ? "#79c0ff" : "#3fb950",
      }}
    >
      {isWorkspace ? "workspace" : "memory"}
    </span>
  );
}

export default function ComponentExplorerPage() {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ComponentCardSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function runSearch() {
    const trimmed = query.trim();
    if (!trimmed) return;
    setLoading(true);
    setError(null);
    try {
      const data = await searchComponents(trimmed, { limit: 30 });
      setResults(data.items);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-foreground">Component Explorer</h1>
        <p className="text-sm text-muted mt-1">
          Search backfilled and mined CAM-SEQ component memory by job, file, symbol, or component type.
        </p>
      </div>

      <Card>
        <CardTitle>Search</CardTitle>
        <div className="flex gap-3 flex-col md:flex-row">
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void runSearch();
            }}
            placeholder="retry helper, token refresh, validator, queue worker..."
            className="flex-1 rounded-lg border border-card-border bg-background px-4 py-3 text-sm outline-none focus:border-accent"
          />
          <button
            type="button"
            onClick={() => void runSearch()}
            disabled={loading}
            className="rounded-lg bg-accent px-4 py-3 text-sm font-semibold text-white disabled:opacity-60"
          >
            {loading ? "Searching..." : "Search"}
          </button>
        </div>
      </Card>

      {error && <ErrorBanner message="Failed to search components" detail={error} onRetry={() => { setError(null); void runSearch(); }} />}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        {results.map((item) => (
          <Link key={item.id} href={`/knowledge/components/${item.id}`}>
            <Card className="hover:border-accent/40 transition-colors cursor-pointer h-full">
              <div className="flex items-center gap-2 mb-3 flex-wrap">
                <CoverageBadge state={item.coverage_state} />
                <LangBadge lang={item.language || "unknown"} />
                <SourceBadge scope={item.source_scope} />
                <span className="inline-block px-2 py-0.5 rounded text-xs bg-card-border/60 text-muted">
                  {item.component_type}
                </span>
              </div>
              <div className="text-base font-semibold text-foreground mb-1">{item.title}</div>
              <div className="text-xs text-muted font-mono break-all mb-2">{item.file_path}</div>
              {item.symbol && <div className="text-sm text-foreground mb-3">symbol: <span className="font-mono">{item.symbol}</span></div>}
              <div className="text-xs text-muted flex gap-4 flex-wrap">
                <span>precision: <strong className="text-foreground">{item.provenance_precision}</strong></span>
                <span>success: <strong className="text-foreground">{item.success_count}</strong></span>
                <span>failure: <strong className="text-foreground">{item.failure_count}</strong></span>
                {typeof item.search_score === "number" && (
                  <span>match: <strong className="text-foreground">{item.search_score}</strong></span>
                )}
              </div>
            </Card>
          </Link>
        ))}
      </div>

      {!loading && !error && results.length === 0 && (
        <Card>
          <div className="text-sm text-muted">Run a search to inspect component memory.</div>
        </Card>
      )}
    </div>
  );
}
