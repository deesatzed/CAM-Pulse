"use client";

import { useState, useMemo, useCallback } from "react";
import {
  searchKnowledge,
  getMethodology,
  type SearchResponse,
  type SearchResult,
  type Methodology,
} from "@/lib/api";
import { Card, CardTitle } from "@/components/card";
import { GanglionBadge, LifecycleBadge, LangBadge } from "@/components/badge";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function truncate(text: string, max: number): string {
  if (!text || text.length <= max) return text || "";
  return text.slice(0, max) + "...";
}

function formatMs(ms: number): string {
  return ms < 1000 ? `${ms.toFixed(0)}ms` : `${(ms / 1000).toFixed(2)}s`;
}

// ---------------------------------------------------------------------------
// Filter state
// ---------------------------------------------------------------------------

interface Filters {
  lifecycles: Set<string>;
  languages: Set<string>;
}

function deriveOptions(results: SearchResult[]) {
  const lifecycles = new Set<string>();
  const languages = new Set<string>();
  for (const r of results) {
    if (r.lifecycle) lifecycles.add(r.lifecycle);
    if (r.language) languages.add(r.language);
  }
  return {
    lifecycles: Array.from(lifecycles).sort(),
    languages: Array.from(languages).sort(),
  };
}

function applyFilters(results: SearchResult[], filters: Filters): SearchResult[] {
  return results.filter((r) => {
    if (filters.lifecycles.size > 0 && !filters.lifecycles.has(r.lifecycle)) return false;
    if (filters.languages.size > 0 && !filters.languages.has(r.language)) return false;
    return true;
  });
}

// ---------------------------------------------------------------------------
// Toggle chip component
// ---------------------------------------------------------------------------

function ToggleChip({
  label,
  active,
  onToggle,
}: {
  label: string;
  active: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={`px-2.5 py-1 rounded text-xs font-medium border transition-colors cursor-pointer ${
        active
          ? "bg-accent/20 text-accent border-accent/40"
          : "bg-card-border/30 text-muted border-card-border hover:text-foreground"
      }`}
    >
      {label}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Result card
// ---------------------------------------------------------------------------

function ResultCard({
  result,
  onClick,
}: {
  result: SearchResult;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-accent rounded-xl"
    >
      <Card className="hover:border-accent/40 transition-colors cursor-pointer">
        {/* Header badges */}
        <div className="flex flex-wrap items-center gap-2 mb-3">
          <GanglionBadge name={result.source_ganglion} />
          <LangBadge lang={result.language} />
          <LifecycleBadge state={result.lifecycle} />
          <span className="ml-auto text-xs text-muted font-mono">
            rank {result.fts_rank.toFixed(2)}
          </span>
        </div>

        {/* Problem description */}
        <p className="text-sm text-foreground leading-relaxed mb-3">
          {truncate(result.problem, 220)}
        </p>

        {/* Solution preview */}
        {result.solution_preview && (
          <pre className="text-xs text-cam-green bg-background border border-card-border rounded-lg p-3 mb-3 overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed max-h-40 overflow-y-auto">
            <code>{truncate(result.solution_preview, 600)}</code>
          </pre>
        )}

        {/* Tags */}
        {result.tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5 mb-3">
            {result.tags.map((tag) => (
              <span
                key={tag}
                className="px-2 py-0.5 rounded bg-cam-purple/10 text-cam-purple text-[11px]"
              >
                {tag}
              </span>
            ))}
          </div>
        )}

        {/* Meta */}
        <div className="flex flex-wrap gap-4 text-xs text-muted">
          <span>
            retrievals: <strong className="text-foreground">{result.retrievals}</strong>
          </span>
          <span>
            successes: <strong className="text-foreground">{result.successes}</strong>
          </span>
          {result.novelty !== null && (
            <span>
              novelty: <strong className="text-foreground">{result.novelty.toFixed(2)}</strong>
            </span>
          )}
        </div>
      </Card>
    </button>
  );
}

// ---------------------------------------------------------------------------
// Detail panel / modal
// ---------------------------------------------------------------------------

function DetailPanel({
  methodology,
  loading,
  error,
  onClose,
}: {
  methodology: Methodology | null;
  loading: boolean;
  error: string | null;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-end">
      {/* Backdrop */}
      <button
        type="button"
        className="absolute inset-0 bg-black/60 cursor-default"
        onClick={onClose}
        aria-label="Close detail panel"
      />

      {/* Panel */}
      <div className="relative w-full max-w-2xl h-full bg-card border-l border-card-border overflow-y-auto p-6 animate-in slide-in-from-right">
        <button
          type="button"
          onClick={onClose}
          className="absolute top-4 right-4 text-muted hover:text-foreground text-lg cursor-pointer"
          aria-label="Close"
        >
          x
        </button>

        {loading && <p className="text-muted">Loading methodology details...</p>}
        {error && <p className="text-red-400">Error: {error}</p>}
        {methodology && (
          <div>
            <div className="flex flex-wrap items-center gap-2 mb-4">
              <LifecycleBadge state={methodology.lifecycle_state} />
              <LangBadge lang={methodology.language} />
              <span className="text-xs text-muted font-mono">{methodology.methodology_type}</span>
            </div>

            <h2 className="text-lg font-bold text-foreground mb-1">Methodology Detail</h2>
            <p className="text-xs text-muted-dark font-mono mb-4 break-all">{methodology.id}</p>

            {/* Problem */}
            <section className="mb-5">
              <CardTitle>Problem</CardTitle>
              <p className="text-sm text-foreground leading-relaxed whitespace-pre-wrap">
                {methodology.problem_description}
              </p>
            </section>

            {/* Solution */}
            <section className="mb-5">
              <CardTitle>Solution</CardTitle>
              <pre className="text-xs text-cam-green bg-background border border-card-border rounded-lg p-4 overflow-x-auto whitespace-pre-wrap font-mono leading-relaxed max-h-96 overflow-y-auto">
                <code>{methodology.solution_code}</code>
              </pre>
            </section>

            {/* Notes */}
            {methodology.methodology_notes && (
              <section className="mb-5">
                <CardTitle>Notes</CardTitle>
                <p className="text-sm text-muted leading-relaxed whitespace-pre-wrap">
                  {methodology.methodology_notes}
                </p>
              </section>
            )}

            {/* Tags */}
            {methodology.tags.length > 0 && (
              <section className="mb-5">
                <CardTitle>Tags</CardTitle>
                <div className="flex flex-wrap gap-1.5">
                  {methodology.tags.map((tag) => (
                    <span
                      key={tag}
                      className="px-2 py-0.5 rounded bg-cam-purple/10 text-cam-purple text-xs"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </section>
            )}

            {/* Files affected */}
            {methodology.files_affected && (
              <section className="mb-5">
                <CardTitle>Files Affected</CardTitle>
                <p className="text-xs text-muted font-mono whitespace-pre-wrap">
                  {methodology.files_affected}
                </p>
              </section>
            )}

            {/* Scores and stats */}
            <section className="mb-5">
              <CardTitle>Statistics</CardTitle>
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-background border border-card-border rounded-lg p-3">
                  <div className="text-xs text-muted">Retrievals</div>
                  <div className="text-xl font-bold text-foreground">{methodology.retrieval_count}</div>
                </div>
                <div className="bg-background border border-card-border rounded-lg p-3">
                  <div className="text-xs text-muted">Successes</div>
                  <div className="text-xl font-bold text-cam-green">{methodology.success_count}</div>
                </div>
                <div className="bg-background border border-card-border rounded-lg p-3">
                  <div className="text-xs text-muted">Failures</div>
                  <div className="text-xl font-bold text-red-400">{methodology.failure_count}</div>
                </div>
                <div className="bg-background border border-card-border rounded-lg p-3">
                  <div className="text-xs text-muted">Novelty</div>
                  <div className="text-xl font-bold text-cam-purple">
                    {methodology.novelty_score !== null ? methodology.novelty_score.toFixed(2) : "--"}
                  </div>
                </div>
                <div className="bg-background border border-card-border rounded-lg p-3">
                  <div className="text-xs text-muted">Potential</div>
                  <div className="text-xl font-bold text-cam-blue">
                    {methodology.potential_score !== null ? methodology.potential_score.toFixed(2) : "--"}
                  </div>
                </div>
                <div className="bg-background border border-card-border rounded-lg p-3">
                  <div className="text-xs text-muted">Created</div>
                  <div className="text-sm font-mono text-foreground">
                    {methodology.created_at ? new Date(methodology.created_at).toLocaleDateString() : "--"}
                  </div>
                </div>
              </div>
            </section>
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function KnowledgeExplorer() {
  const [query, setQuery] = useState("");
  const [searchData, setSearchData] = useState<SearchResponse | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<string | null>(null);

  // Filters
  const [filters, setFilters] = useState<Filters>({
    lifecycles: new Set(),
    languages: new Set(),
  });

  // Detail panel
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Methodology | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  // ---------------------------------------------------------------------------
  // Derived
  // ---------------------------------------------------------------------------

  const filterOptions = useMemo(
    () => (searchData ? deriveOptions(searchData.results) : { lifecycles: [], languages: [] }),
    [searchData],
  );

  const filteredResults = useMemo(
    () => (searchData ? applyFilters(searchData.results, filters) : []),
    [searchData, filters],
  );

  // ---------------------------------------------------------------------------
  // Actions
  // ---------------------------------------------------------------------------

  const handleSearch = useCallback(async () => {
    const trimmed = query.trim();
    if (!trimmed) return;

    setSearching(true);
    setSearchError(null);
    setSearchData(null);
    setFilters({ lifecycles: new Set(), languages: new Set() });

    try {
      const data = await searchKnowledge(trimmed, 50);
      setSearchData(data);
    } catch (e: unknown) {
      setSearchError(e instanceof Error ? e.message : String(e));
    } finally {
      setSearching(false);
    }
  }, [query]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter") handleSearch();
    },
    [handleSearch],
  );

  const openDetail = useCallback(async (id: string) => {
    setSelectedId(id);
    setDetail(null);
    setDetailLoading(true);
    setDetailError(null);

    try {
      const m = await getMethodology(id);
      setDetail(m);
    } catch (e: unknown) {
      setDetailError(e instanceof Error ? e.message : String(e));
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const closeDetail = useCallback(() => {
    setSelectedId(null);
    setDetail(null);
    setDetailError(null);
  }, []);

  const toggleFilter = useCallback(
    (kind: "lifecycles" | "languages", value: string) => {
      setFilters((prev) => {
        const next = new Set(prev[kind]);
        if (next.has(value)) {
          next.delete(value);
        } else {
          next.add(value);
        }
        return { ...prev, [kind]: next };
      });
    },
    [],
  );

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div>
      {/* Page header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-foreground">Knowledge Explorer</h1>
        <p className="text-muted mt-1">
          Federated full-text search across all CAM brain ganglia
        </p>
      </div>

      {/* Search bar */}
      <div className="flex gap-3 mb-6">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Search methodologies across all brains..."
          className="flex-1 bg-card border border-card-border rounded-lg px-4 py-2.5 text-sm text-foreground placeholder:text-muted-dark focus:outline-none focus:border-accent/60 transition-colors"
        />
        <button
          type="button"
          onClick={handleSearch}
          disabled={searching || !query.trim()}
          className="px-5 py-2.5 bg-accent hover:bg-accent-hover disabled:opacity-40 text-white text-sm font-semibold rounded-lg transition-colors cursor-pointer disabled:cursor-not-allowed"
        >
          {searching ? "Searching..." : "Search"}
        </button>
      </div>

      {/* Error */}
      {searchError && (
        <div className="text-red-400 bg-red-400/10 border border-red-400/20 rounded-lg p-4 mb-6 text-sm">
          Search failed: {searchError}
        </div>
      )}

      {/* Results section */}
      {searchData && (
        <>
          {/* Search summary */}
          <Card className="mb-6">
            <div className="flex flex-wrap items-center gap-4">
              <div className="text-sm text-foreground">
                <strong className="text-accent">{searchData.total_results}</strong> results for{" "}
                <span className="font-mono text-cam-blue">&quot;{searchData.query}&quot;</span>
              </div>
              <div className="text-xs text-muted">
                in {formatMs(searchData.elapsed_ms)}
              </div>
              <div className="ml-auto flex flex-wrap items-center gap-2">
                {Object.entries(searchData.ganglion_counts).map(([ganglion, count]) => (
                  <span key={ganglion} className="flex items-center gap-1.5">
                    <GanglionBadge name={ganglion} />
                    <span className="text-xs text-muted">{count}</span>
                  </span>
                ))}
              </div>
            </div>
            {filteredResults.length !== searchData.results.length && (
              <div className="text-xs text-muted mt-2">
                Showing {filteredResults.length} of {searchData.results.length} after filters
              </div>
            )}
          </Card>

          {/* Filter toggles */}
          {(filterOptions.lifecycles.length > 1 || filterOptions.languages.length > 1) && (
            <div className="flex flex-wrap gap-6 mb-6">
              {filterOptions.lifecycles.length > 1 && (
                <div>
                  <div className="text-xs text-muted uppercase tracking-wider mb-2">Lifecycle</div>
                  <div className="flex flex-wrap gap-1.5">
                    {filterOptions.lifecycles.map((lc) => (
                      <ToggleChip
                        key={lc}
                        label={lc}
                        active={filters.lifecycles.has(lc)}
                        onToggle={() => toggleFilter("lifecycles", lc)}
                      />
                    ))}
                  </div>
                </div>
              )}
              {filterOptions.languages.length > 1 && (
                <div>
                  <div className="text-xs text-muted uppercase tracking-wider mb-2">Language</div>
                  <div className="flex flex-wrap gap-1.5">
                    {filterOptions.languages.map((lang) => (
                      <ToggleChip
                        key={lang}
                        label={lang}
                        active={filters.languages.has(lang)}
                        onToggle={() => toggleFilter("languages", lang)}
                      />
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Result cards */}
          {filteredResults.length === 0 ? (
            <div className="text-muted text-sm py-8 text-center">
              No results match the current filters.
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4">
              {filteredResults.map((result) => (
                <ResultCard
                  key={result.id}
                  result={result}
                  onClick={() => openDetail(result.id)}
                />
              ))}
            </div>
          )}
        </>
      )}

      {/* Empty state */}
      {!searchData && !searching && !searchError && (
        <div className="text-center py-16">
          <div className="text-muted-dark text-5xl mb-4">?</div>
          <p className="text-muted text-sm">
            Enter a search query to explore methodologies across all brain ganglia.
          </p>
          <p className="text-muted-dark text-xs mt-2">
            Searches problem descriptions, solutions, notes, and tags via FTS5
          </p>
        </div>
      )}

      {/* Detail panel */}
      {selectedId && (
        <DetailPanel
          methodology={detail}
          loading={detailLoading}
          error={detailError}
          onClose={closeDetail}
        />
      )}
    </div>
  );
}
