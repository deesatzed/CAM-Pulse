"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
  getBrainGraph,
  type BrainGraphNode,
  searchKnowledge,
  type SearchResponse,
} from "@/lib/api";
import { Card, CardTitle, StatCard } from "@/components/card";
import { GanglionBadge } from "@/components/badge";
import { SkeletonGrid, Skeleton } from "@/components/skeleton";
import { ErrorBanner } from "@/components/error-banner";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function BrainDetailPage() {
  const params = useParams();
  const brainName = params.name as string;

  const [node, setNode] = useState<BrainGraphNode | null>(null);
  const [search, setSearch] = useState<SearchResponse | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getBrainGraph()
      .then((data) => {
        const found = data.nodes.find((n) => n.name === brainName || n.id === brainName);
        if (found) setNode(found);
        else setError(`Brain '${brainName}' not found`);
      })
      .catch((e) => setError(e.message));
  }, [brainName]);

  const handleSearch = async () => {
    if (!searchQuery.trim()) return;
    setSearching(true);
    try {
      const results = await searchKnowledge(searchQuery, 20);
      setSearch(results);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSearching(false);
    }
  };

  if (error) {
    return (
      <ErrorBanner
        message={error}
        onRetry={() => {
          setError(null);
          getBrainGraph()
            .then((data) => {
              const found = data.nodes.find((n) => n.name === brainName || n.id === brainName);
              if (found) setNode(found);
              else setError(`Brain '${brainName}' not found`);
            })
            .catch((e) => setError(e.message));
        }}
      />
    );
  }

  if (!node) {
    return (
      <div className="space-y-6">
        <div className="flex items-center gap-3"><Skeleton className="h-10 w-10 rounded-full" /><div><Skeleton className="h-6 w-48" /><Skeleton className="h-4 w-32 mt-1" /></div></div>
        <SkeletonGrid count={4} />
      </div>
    );
  }

  const categories = Object.entries(node.categories).sort((a, b) => b[1] - a[1]);
  const maxCat = categories.length > 0 ? categories[0][1] : 1;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <GanglionBadge name={node.name} />
          <div>
            <h1 className="text-2xl font-bold text-foreground">{node.name}</h1>
            <p className="text-muted mt-0.5">
              {node.methodology_count.toLocaleString()} methodologies |{" "}
              {Object.keys(node.categories).length} categories
            </p>
          </div>
        </div>
        <Link href="/forge" className="text-sm text-muted hover:text-foreground">
          Back to Brain Graph
        </Link>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Methodologies" value={node.methodology_count} />
        <StatCard label="Categories" value={Object.keys(node.categories).length} />
        <StatCard
          label="Avg Fitness"
          value={node.fitness_summary.avg.toFixed(2)}
          sub={`${node.fitness_summary.min.toFixed(2)} – ${node.fitness_summary.max.toFixed(2)}`}
        />
        <StatCard
          label="Type"
          value={node.is_primary ? "Primary" : "Sibling"}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Categories */}
        <Card>
          <CardTitle>Category Breakdown</CardTitle>
          <div className="space-y-2">
            {categories.map(([cat, cnt]) => (
              <div key={cat} className="flex items-center gap-3">
                <span className="text-xs text-muted w-36 text-right truncate">{cat}</span>
                <div className="flex-1 h-3 bg-card-border rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full bg-accent"
                    style={{ width: `${(cnt / maxCat) * 100}%` }}
                  />
                </div>
                <span className="text-xs text-foreground font-mono w-10 text-right">{cnt}</span>
              </div>
            ))}
          </div>
        </Card>

        {/* Top Methodologies */}
        <Card>
          <CardTitle>Top by Fitness</CardTitle>
          {node.top_methodologies.length === 0 ? (
            <p className="text-xs text-muted">No fitness scores available yet.</p>
          ) : (
            <div className="space-y-2">
              {node.top_methodologies.map((m, i) => (
                <div key={i} className="flex items-center gap-3 py-1.5 border-b border-card-border last:border-0">
                  <span className="text-accent font-mono text-sm font-bold w-10">
                    {m.fitness.toFixed(2)}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm text-foreground truncate">{m.title}</div>
                    <div className="text-xs text-muted-dark">{m.category}</div>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>

      {/* Search within brain */}
      <Card>
        <CardTitle>Search This Brain</CardTitle>
        <div className="flex gap-3 mb-3">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !searching) handleSearch();
            }}
            placeholder={`Search ${node.name} brain...`}
            className="flex-1 bg-background border border-card-border rounded-lg px-4 py-2.5 text-sm text-foreground placeholder:text-muted-dark focus:outline-none focus:border-accent"
          />
          <button
            onClick={handleSearch}
            disabled={searching || !searchQuery.trim()}
            className="px-5 py-2.5 bg-accent hover:bg-accent-hover disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {searching ? "Searching..." : "Search"}
          </button>
        </div>
        {search && (
          <div className="space-y-2">
            <div className="text-xs text-muted">
              {search.total_results} results in {search.elapsed_ms.toFixed(0)}ms
            </div>
            {search.results
              .filter((r) => r.source_ganglion === brainName || brainName === "primary")
              .slice(0, 10)
              .map((r) => (
                <div key={r.id} className="py-2 border-b border-card-border last:border-0">
                  <div className="flex items-center gap-2">
                    <GanglionBadge name={r.source_ganglion} />
                    <span className="text-xs text-muted">{r.language} | {r.lifecycle}</span>
                  </div>
                  <Link
                    href={`/knowledge/${r.id}`}
                    className="text-sm text-foreground hover:text-accent mt-1 block"
                  >
                    {r.problem}
                  </Link>
                </div>
              ))}
          </div>
        )}
      </Card>

      {/* Actions */}
      <div className="flex gap-4">
        <Link
          href="/mining"
          className="px-4 py-2 bg-card-border hover:bg-card-hover text-foreground text-sm font-medium rounded-lg transition-colors"
        >
          Mine More Knowledge
        </Link>
        <Link
          href="/knowledge/gaps"
          className="px-4 py-2 bg-card-border hover:bg-card-hover text-foreground text-sm font-medium rounded-lg transition-colors"
        >
          View Coverage Gaps
        </Link>
      </div>
    </div>
  );
}
