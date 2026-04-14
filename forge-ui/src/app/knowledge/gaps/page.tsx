"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  getGapsMatrix,
  getGapsDiscover,
  getGapsTrend,
  type CoverageMatrix,
  type GapCluster,
  type GapTrendSnapshot,
} from "@/lib/api";
import { Card, CardTitle } from "@/components/card";
import { Skeleton, SkeletonCard, SkeletonGrid } from "@/components/skeleton";
import { ErrorBanner } from "@/components/error-banner";

// ---------------------------------------------------------------------------
// Heatmap cell color logic
// ---------------------------------------------------------------------------

function cellColor(count: number): string {
  if (count === 0) return "#f8514930";
  if (count <= 2) return "#f0883e30";
  if (count <= 4) return "#3fb95030";
  return "#3fb950";
}

function cellTextColor(count: number): string {
  if (count === 0) return "#f85149";
  if (count <= 2) return "#f0883e";
  if (count <= 4) return "#3fb950";
  return "#ffffff";
}

// ---------------------------------------------------------------------------
// Selected cell type
// ---------------------------------------------------------------------------

interface SelectedCell {
  category: string;
  brain: string;
  count: number;
}

function cellStatus(count: number): { label: string; color: string } {
  if (count === 0) return { label: "No coverage", color: "#f85149" };
  if (count <= 2) return { label: "Sparse", color: "#f0883e" };
  if (count <= 4) return { label: "Good", color: "#3fb950" };
  return { label: "Strong", color: "#3fb950" };
}

// ---------------------------------------------------------------------------
// Cell detail panel
// ---------------------------------------------------------------------------

function CellDetailPanel({
  cell,
  onClose,
}: {
  cell: SelectedCell;
  onClose: () => void;
}) {
  const status = cellStatus(cell.count);
  const isGap = cell.count <= 2;

  return (
    <div className="border border-card-border rounded-lg bg-background/80 backdrop-blur-sm p-4 mt-3 animate-in fade-in slide-in-from-top-2 duration-200">
      <div className="flex items-start justify-between mb-3">
        <div className="flex items-center gap-2">
          <span
            className="w-3 h-3 rounded-full flex-shrink-0"
            style={{ background: status.color }}
          />
          <div>
            <span className="text-sm font-semibold text-foreground font-mono">
              {cell.category}
            </span>
            <span className="text-muted-dark mx-1.5">/</span>
            <span className="text-sm font-semibold text-cam-purple">
              {cell.brain}
            </span>
          </div>
        </div>
        <button
          onClick={onClose}
          className="text-muted hover:text-foreground transition-colors text-sm px-1.5 py-0.5 rounded hover:bg-card-border/40"
          aria-label="Close detail panel"
        >
          &times;
        </button>
      </div>

      <div className="flex items-center gap-3 mb-4">
        <span
          className="text-xs font-bold px-2 py-0.5 rounded-full"
          style={{
            color: status.color,
            backgroundColor: `${status.color}20`,
          }}
        >
          {status.label}
        </span>
        <span className="text-xs text-muted">
          {cell.count === 0
            ? "Zero methodologies in this cell"
            : `${cell.count} methodology${cell.count !== 1 ? "ies" : ""} in this cell`}
        </span>
      </div>

      {isGap && (
        <div className="flex flex-wrap gap-2">
          <Link
            href={`/mining?category=${encodeURIComponent(cell.category)}&brain=${encodeURIComponent(cell.brain)}`}
            className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-md bg-accent/15 text-accent hover:bg-accent/25 transition-colors border border-accent/20"
          >
            <svg
              width="12"
              height="12"
              viewBox="0 0 16 16"
              fill="currentColor"
              className="flex-shrink-0"
            >
              <path d="M11.28 3.22a.75.75 0 0 1 0 1.06L4.56 11H8.25a.75.75 0 0 1 0 1.5H3a.75.75 0 0 1-.75-.75V6.5a.75.75 0 0 1 1.5 0v3.69l6.72-6.72a.75.75 0 0 1 1.06 0Z" />
            </svg>
            Mine this gap
          </Link>
          <Link
            href={`/knowledge?q=${encodeURIComponent(cell.category)}`}
            className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-md bg-card-border/40 text-foreground hover:bg-card-border/60 transition-colors border border-card-border"
          >
            <svg
              width="12"
              height="12"
              viewBox="0 0 16 16"
              fill="currentColor"
              className="flex-shrink-0"
            >
              <path d="M10.68 11.74a6 6 0 0 1-7.922-8.982 6 6 0 0 1 8.982 7.922l3.04 3.04a.749.749 0 1 1-1.06 1.06l-3.04-3.04ZM11.5 7a4.499 4.499 0 1 0-8.997 0A4.499 4.499 0 0 0 11.5 7Z" />
            </svg>
            Search related
          </Link>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function GapHeatmapPage() {
  const [matrix, setMatrix] = useState<CoverageMatrix | null>(null);
  const [clusters, setClusters] = useState<GapCluster[]>([]);
  const [trendSummary, setTrendSummary] = useState<string>("");
  const [snapshots, setSnapshots] = useState<GapTrendSnapshot[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedCell, setSelectedCell] = useState<SelectedCell | null>(null);

  const loadData = useCallback(() => {
    setLoading(true);
    setError(null);
    Promise.all([getGapsMatrix(), getGapsDiscover(), getGapsTrend()])
      .then(([matrixData, discoverData, trendData]) => {
        setMatrix(matrixData);
        setClusters(discoverData.clusters);
        setTrendSummary(trendData.summary);
        setSnapshots(trendData.snapshots);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const timer = setTimeout(() => {
      loadData();
    }, 0);
    return () => clearTimeout(timer);
  }, [loadData]);

  if (error) {
    return (
      <ErrorBanner
        message="Failed to load gap data"
        detail={error}
        onRetry={() => { setError(null); loadData(); }}
      />
    );
  }
  if (loading || !matrix) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-4 w-96" />
        <SkeletonCard />
        <SkeletonGrid count={2} />
        <SkeletonCard />
      </div>
    );
  }

  // Derive sorted categories (by total descending) and brains
  const categories = Object.keys(matrix.total_by_category).sort(
    (a, b) => matrix.total_by_category[b] - matrix.total_by_category[a]
  );
  const brains = Object.keys(matrix.total_by_brain).sort(
    (a, b) => matrix.total_by_brain[b] - matrix.total_by_brain[a]
  );

  // Helper: is a cell clickable (sparse or empty)?
  const isClickable = (count: number) => count <= 2;

  // Toggle cell selection
  const handleCellClick = (category: string, brain: string, count: number) => {
    if (!isClickable(count)) return;
    setSelectedCell((prev) =>
      prev && prev.category === category && prev.brain === brain
        ? null
        : { category, brain, count }
    );
  };

  return (
    <div>
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-foreground">Knowledge Gap Heatmap</h1>
        <p className="text-muted mt-1">
          Coverage matrix across categories and brains — red cells indicate gaps, green cells indicate depth.
          Click any red or orange cell to inspect and act on it.
        </p>
        <div className="flex gap-4 mt-3">
          <span className="inline-flex items-center gap-1.5 text-xs text-muted">
            <span className="w-3 h-3 rounded" style={{ background: "#f8514930", border: "1px solid #f85149" }} />
            Empty (0)
          </span>
          <span className="inline-flex items-center gap-1.5 text-xs text-muted">
            <span className="w-3 h-3 rounded" style={{ background: "#f0883e30", border: "1px solid #f0883e" }} />
            Sparse (1-2)
          </span>
          <span className="inline-flex items-center gap-1.5 text-xs text-muted">
            <span className="w-3 h-3 rounded" style={{ background: "#3fb95030", border: "1px solid #3fb950" }} />
            Good (3-4)
          </span>
          <span className="inline-flex items-center gap-1.5 text-xs text-muted">
            <span className="w-3 h-3 rounded" style={{ background: "#3fb950" }} />
            Strong (5+)
          </span>
        </div>
      </div>

      {/* Heatmap */}
      <Card className="mb-6 overflow-hidden">
        <CardTitle>Coverage Matrix</CardTitle>
        <div className="overflow-x-auto -mx-5 px-5 pb-2">
          <table className="min-w-full border-collapse">
            <thead>
              <tr>
                <th className="sticky left-0 z-10 bg-card text-left text-xs text-muted font-medium px-3 py-2 border-b border-card-border min-w-[180px]">
                  Category
                </th>
                {brains.map((brain) => (
                  <th
                    key={brain}
                    className="text-center text-xs text-muted font-medium px-3 py-2 border-b border-card-border whitespace-nowrap"
                  >
                    {brain}
                    <div className="text-[10px] text-muted-dark font-normal">
                      {matrix.total_by_brain[brain]}
                    </div>
                  </th>
                ))}
                <th className="text-center text-xs text-muted font-medium px-3 py-2 border-b border-card-border">
                  Total
                </th>
              </tr>
            </thead>
            <tbody>
              {categories.map((category) => (
                <tr key={category} className="hover:bg-card-hover/30 transition-colors">
                  <td className="sticky left-0 z-10 bg-card text-xs text-foreground px-3 py-2 border-b border-card-border/50 font-mono">
                    {category}
                  </td>
                  {brains.map((brain) => {
                    const count = matrix.matrix[category]?.[brain] ?? 0;
                    const clickable = isClickable(count);
                    const isSelected =
                      selectedCell?.category === category &&
                      selectedCell?.brain === brain;
                    return (
                      <td
                        key={brain}
                        onClick={
                          clickable
                            ? () => handleCellClick(category, brain, count)
                            : undefined
                        }
                        className={[
                          "text-center text-xs font-bold px-3 py-2 border-b border-card-border/50",
                          clickable
                            ? "cursor-pointer hover:ring-2 hover:ring-accent/50 hover:ring-inset transition-shadow"
                            : "",
                          isSelected
                            ? "ring-2 ring-accent ring-inset"
                            : "",
                        ]
                          .filter(Boolean)
                          .join(" ")}
                        style={{
                          backgroundColor: cellColor(count),
                          color: cellTextColor(count),
                        }}
                        title={
                          clickable
                            ? `Click to inspect ${category} / ${brain}`
                            : undefined
                        }
                      >
                        {count}
                      </td>
                    );
                  })}
                  <td className="text-center text-xs text-muted px-3 py-2 border-b border-card-border/50 font-bold">
                    {matrix.total_by_category[category]}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Inline detail panel for selected cell */}
        {selectedCell && (
          <CellDetailPanel
            cell={selectedCell}
            onClose={() => setSelectedCell(null)}
          />
        )}
      </Card>

      {/* Sparse + Empty cells */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
        <Card>
          <CardTitle>
            Sparse Cells ({matrix.sparse_cells.length})
          </CardTitle>
          <p className="text-xs text-muted mb-3">
            Category-brain pairs with only 1-2 methodologies -- candidates for targeted mining.
          </p>
          {matrix.sparse_cells.length === 0 ? (
            <p className="text-xs text-muted-dark italic">No sparse cells detected.</p>
          ) : (
            <div className="max-h-64 overflow-y-auto space-y-1">
              {matrix.sparse_cells.map(([cat, brain], i) => {
                const count = matrix.matrix[cat]?.[brain] ?? 0;
                const isSelected =
                  selectedCell?.category === cat &&
                  selectedCell?.brain === brain;
                return (
                  <button
                    key={i}
                    onClick={() => handleCellClick(cat, brain, count)}
                    className={[
                      "flex items-center gap-2 text-xs px-2 py-1 rounded w-full text-left transition-colors",
                      isSelected
                        ? "bg-accent/15 ring-1 ring-accent/40"
                        : "bg-card-border/30 hover:bg-card-border/50",
                    ].join(" ")}
                  >
                    <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: "#f0883e" }} />
                    <span className="text-foreground font-mono">{cat}</span>
                    <span className="text-muted-dark">/</span>
                    <span className="text-cam-purple">{brain}</span>
                    <span className="ml-auto text-muted-dark">
                      {count}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </Card>

        <Card>
          <CardTitle>
            Empty Cells ({matrix.empty_cells.length})
          </CardTitle>
          <p className="text-xs text-muted mb-3">
            Category-brain pairs with zero methodologies -- blind spots in the knowledge base.
          </p>
          {matrix.empty_cells.length === 0 ? (
            <p className="text-xs text-muted-dark italic">Full coverage -- no empty cells.</p>
          ) : (
            <div className="max-h-64 overflow-y-auto space-y-1">
              {matrix.empty_cells.map(([cat, brain], i) => {
                const isSelected =
                  selectedCell?.category === cat &&
                  selectedCell?.brain === brain;
                return (
                  <button
                    key={i}
                    onClick={() => handleCellClick(cat, brain, 0)}
                    className={[
                      "flex items-center gap-2 text-xs px-2 py-1 rounded w-full text-left transition-colors",
                      isSelected
                        ? "bg-accent/15 ring-1 ring-accent/40"
                        : "bg-card-border/30 hover:bg-card-border/50",
                    ].join(" ")}
                  >
                    <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: "#f85149" }} />
                    <span className="text-foreground font-mono">{cat}</span>
                    <span className="text-muted-dark">/</span>
                    <span className="text-cam-purple">{brain}</span>
                  </button>
                );
              })}
            </div>
          )}
        </Card>
      </div>

      {/* Discovered Clusters */}
      <Card className="mb-6">
        <CardTitle>Discovered Clusters ({clusters.length})</CardTitle>
        <p className="text-xs text-muted mb-4">
          Thematic clusters found by analyzing methodology similarity -- potential new categories.
        </p>
        {clusters.length === 0 ? (
          <p className="text-xs text-muted-dark italic">No clusters discovered yet.</p>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {clusters.map((cluster, i) => (
              <div
                key={i}
                className="border border-card-border rounded-lg p-4 bg-background/50"
              >
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <div className="text-sm font-semibold text-foreground">{cluster.theme}</div>
                    <div className="text-[10px] text-muted-dark mt-0.5">
                      Suggested: <span className="text-cam-blue">{cluster.suggested_name}</span>
                    </div>
                  </div>
                  <span className="inline-flex items-center px-2 py-0.5 rounded-full bg-accent/20 text-accent text-xs font-bold">
                    {cluster.count}
                  </span>
                </div>
                <div className="text-xs text-muted mb-2">
                  {cluster.methodology_ids.length} methodology{cluster.methodology_ids.length !== 1 ? "ies" : "y"}
                </div>
                {cluster.sample_titles.length > 0 && (
                  <ul className="space-y-1">
                    {cluster.sample_titles.map((title, j) => (
                      <li
                        key={j}
                        className="text-xs text-muted-dark pl-3 border-l-2 border-card-border"
                      >
                        {title}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Trend Summary */}
      <Card>
        <CardTitle>Gap Trend</CardTitle>
        {trendSummary ? (
          <p className="text-sm text-foreground leading-relaxed whitespace-pre-wrap mb-4">
            {trendSummary}
          </p>
        ) : (
          <p className="text-xs text-muted-dark italic mb-4">No trend summary available.</p>
        )}
        {snapshots.length > 0 && (
          <>
            <div className="text-xs text-muted mb-2 font-medium">Recent snapshots</div>
            <div className="overflow-x-auto">
              <table className="min-w-full border-collapse text-xs">
                <thead>
                  <tr>
                    <th className="text-left text-muted font-medium px-3 py-1.5 border-b border-card-border">
                      Date
                    </th>
                    <th className="text-right text-muted font-medium px-3 py-1.5 border-b border-card-border">
                      Total Methodologies
                    </th>
                    <th className="text-right text-muted font-medium px-3 py-1.5 border-b border-card-border">
                      Sparse Cells
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {snapshots.map((snap) => (
                    <tr key={snap.id} className="hover:bg-card-hover/30 transition-colors">
                      <td className="text-foreground px-3 py-1.5 border-b border-card-border/50 font-mono">
                        {new Date(snap.created_at).toLocaleDateString("en-US", {
                          year: "numeric",
                          month: "short",
                          day: "numeric",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </td>
                      <td className="text-right text-foreground px-3 py-1.5 border-b border-card-border/50">
                        {snap.total_methodologies.toLocaleString()}
                      </td>
                      <td className="text-right px-3 py-1.5 border-b border-card-border/50">
                        <span
                          className={
                            snap.sparse_cells.length > 5
                              ? "text-[#f0883e]"
                              : snap.sparse_cells.length > 0
                                ? "text-[#f0883e80]"
                                : "text-cam-green"
                          }
                        >
                          {snap.sparse_cells.length}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
