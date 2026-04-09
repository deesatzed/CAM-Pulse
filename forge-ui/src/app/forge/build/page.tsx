"use client";

import { useState, useCallback, useEffect } from "react";
import Link from "next/link";
import {
  searchKnowledge,
  getGapsMatrix,
  previewRepo,
  getConfig,
  createGanglion,
  validateForge,
  getPrompts,
  type SearchResponse,
  type CoverageMatrix,
  type PromptInfo,
} from "@/lib/api";
import { Card, CardTitle } from "@/components/card";
import { GanglionBadge } from "@/components/badge";
import { IntentBar } from "@/components/intent-bar";
import { ErrorBanner } from "@/components/error-banner";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Recipe {
  brainName: string;
  description: string;
  repoPaths: string[];
  agentIds: string[];
  promptTemplate: string;
  existingKnowledge: SearchResponse | null;
  gapInfo: CoverageMatrix | null;
  repoPreview: Record<string, unknown> | null;
  validation: Record<string, unknown> | null;
}

// ---------------------------------------------------------------------------
// Recipe Sections
// ---------------------------------------------------------------------------

function BrainConfigSection({
  recipe,
  onUpdate,
}: {
  recipe: Recipe;
  onUpdate: (patch: Partial<Recipe>) => void;
}) {
  return (
    <Card>
      <CardTitle>Brain Configuration</CardTitle>
      <div className="space-y-3">
        <div>
          <label className="text-xs text-muted uppercase tracking-wider">Brain Name</label>
          <input
            type="text"
            value={recipe.brainName}
            onChange={(e) => onUpdate({ brainName: e.target.value.toLowerCase().replace(/[^a-z0-9-_]/g, "") })}
            placeholder="e.g. sql-queries, react-patterns"
            className="mt-1 w-full bg-background border border-card-border rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-dark focus:outline-none focus:border-accent"
          />
        </div>
        <div>
          <label className="text-xs text-muted uppercase tracking-wider">Description</label>
          <input
            type="text"
            value={recipe.description}
            onChange={(e) => onUpdate({ description: e.target.value })}
            placeholder="What this brain specializes in..."
            className="mt-1 w-full bg-background border border-card-border rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-dark focus:outline-none focus:border-accent"
          />
        </div>
      </div>
    </Card>
  );
}

function RepoPathsSection({
  recipe,
  onUpdate,
  onPreview,
  loading,
}: {
  recipe: Recipe;
  onUpdate: (patch: Partial<Recipe>) => void;
  onPreview: (path: string) => void;
  loading: boolean;
}) {
  const [newPath, setNewPath] = useState("");

  const addPath = () => {
    const trimmed = newPath.trim();
    if (trimmed && !recipe.repoPaths.includes(trimmed)) {
      onUpdate({ repoPaths: [...recipe.repoPaths, trimmed] });
      onPreview(trimmed);
      setNewPath("");
    }
  };

  return (
    <Card>
      <CardTitle>Knowledge Sources</CardTitle>
      <p className="text-xs text-muted mb-3">
        Add local directories to mine for knowledge.
      </p>
      <div className="flex gap-2 mb-3">
        <input
          type="text"
          value={newPath}
          onChange={(e) => setNewPath(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") addPath();
          }}
          placeholder="/path/to/your/repo"
          className="flex-1 bg-background border border-card-border rounded-lg px-3 py-2 text-sm text-foreground placeholder:text-muted-dark focus:outline-none focus:border-accent font-mono"
        />
        <button
          onClick={addPath}
          disabled={!newPath.trim() || loading}
          className="px-4 py-2 bg-accent hover:bg-accent-hover disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors"
        >
          {loading ? "Scanning..." : "Add"}
        </button>
      </div>
      {recipe.repoPaths.length > 0 && (
        <div className="space-y-1.5">
          {recipe.repoPaths.map((p) => (
            <div key={p} className="flex items-center gap-2 px-3 py-1.5 bg-card-border/50 rounded-lg">
              <span className="text-xs font-mono text-foreground flex-1 truncate">{p}</span>
              <button
                onClick={() => onUpdate({ repoPaths: recipe.repoPaths.filter((x) => x !== p) })}
                className="text-xs text-muted-dark hover:text-red-400"
              >
                remove
              </button>
            </div>
          ))}
        </div>
      )}
      {recipe.repoPreview && (
        <div className="mt-3 p-3 bg-background rounded-lg border border-card-border">
          <div className="text-xs text-muted uppercase tracking-wider mb-1">Repo Analysis</div>
          <div className="text-xs text-foreground">
            {(recipe.repoPreview.total_files as number)?.toLocaleString() || 0} files,{" "}
            {((recipe.repoPreview.total_bytes as number) / 1024).toFixed(0) || 0} KB
          </div>
          <div className="text-xs text-muted mt-1">
            Suggested brain:{" "}
            <span className="text-accent font-medium">
              {recipe.repoPreview.suggested_brain as string}
            </span>
          </div>
        </div>
      )}
    </Card>
  );
}

function AgentSection({
  recipe,
  agents,
  onUpdate,
}: {
  recipe: Recipe;
  agents: Record<string, Record<string, unknown>>;
  onUpdate: (patch: Partial<Recipe>) => void;
}) {
  return (
    <Card>
      <CardTitle>Agent Recommendation</CardTitle>
      <p className="text-xs text-muted mb-3">
        Select which agents to use for mining and task execution.
      </p>
      <div className="space-y-1.5">
        {Object.entries(agents).map(([aid, acfg]) => {
          const selected = recipe.agentIds.includes(aid);
          const enabled = acfg.enabled as boolean;
          return (
            <button
              key={aid}
              onClick={() => {
                if (selected) {
                  onUpdate({ agentIds: recipe.agentIds.filter((x) => x !== aid) });
                } else {
                  onUpdate({ agentIds: [...recipe.agentIds, aid] });
                }
              }}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                selected
                  ? "bg-accent/10 border border-accent/40"
                  : "bg-card-border/30 border border-transparent hover:border-card-border"
              }`}
            >
              <span
                className={`w-5 h-5 rounded flex items-center justify-center text-xs ${
                  selected ? "bg-accent text-white" : "bg-card-border text-muted"
                }`}
              >
                {selected ? "+" : ""}
              </span>
              <span className={`font-medium ${enabled ? "text-foreground" : "text-muted-dark"}`}>
                {aid}
              </span>
              <span className="text-xs text-muted ml-auto">
                {acfg.mode as string} | {acfg.model as string}
              </span>
              {!enabled && <span className="text-xs text-amber-400">disabled</span>}
            </button>
          );
        })}
      </div>
    </Card>
  );
}

function PromptSection({
  recipe,
  prompts,
  onUpdate,
}: {
  recipe: Recipe;
  prompts: PromptInfo[];
  onUpdate: (patch: Partial<Recipe>) => void;
}) {
  return (
    <Card>
      <CardTitle>Prompt Template</CardTitle>
      <p className="text-xs text-muted mb-3">
        Select or fork an existing prompt template for mining.
      </p>
      <div className="space-y-1.5">
        {prompts.map((p) => {
          const selected = recipe.promptTemplate === p.name;
          return (
            <button
              key={p.name}
              onClick={() => onUpdate({ promptTemplate: p.name })}
              className={`w-full flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors ${
                selected
                  ? "bg-accent/10 border border-accent/40"
                  : "bg-card-border/30 border border-transparent hover:border-card-border"
              }`}
            >
              <span className="font-mono text-foreground">{p.name}</span>
              <span className="text-xs text-muted ml-auto">
                {p.line_count} lines, {(p.size_bytes / 1024).toFixed(1)}KB
              </span>
            </button>
          );
        })}
      </div>
    </Card>
  );
}

function ExistingKnowledgePanel({ data }: { data: SearchResponse }) {
  if (data.total_results === 0) return null;
  return (
    <Card>
      <CardTitle>
        Existing Knowledge ({data.total_results} matches)
      </CardTitle>
      <div className="space-y-2">
        {data.results.slice(0, 5).map((r) => (
          <div key={r.id} className="flex items-start gap-2 py-1.5 border-b border-card-border last:border-0">
            <GanglionBadge name={r.source_ganglion} />
            <div className="flex-1 min-w-0">
              <div className="text-xs text-foreground truncate">{r.problem}</div>
              <div className="text-xs text-muted-dark">{r.language} | {r.lifecycle}</div>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-2 text-xs text-muted">
        Ganglion breakdown:{" "}
        {Object.entries(data.ganglion_counts).map(([g, c]) => `${g}: ${c}`).join(", ")}
      </div>
    </Card>
  );
}

function ValidationPanel({ validation }: { validation: Record<string, unknown> }) {
  const checks = (validation.checks as Array<{ check: string; status: string; detail: string }>) || [];
  if (checks.length === 0) return null;

  const colors = { green: "text-cam-green", yellow: "text-amber-400", red: "text-red-400" };

  return (
    <Card>
      <CardTitle>Pre-flight Validation</CardTitle>
      <div className="space-y-1">
        {checks.map((c, i) => (
          <div key={i} className="flex items-center gap-2 text-xs">
            <span className={`font-bold ${colors[c.status as keyof typeof colors] || "text-muted"}`}>
              {c.status === "green" ? "PASS" : c.status === "yellow" ? "WARN" : "FAIL"}
            </span>
            <span className="text-foreground">{c.check.replace(/_/g, " ")}</span>
            <span className="text-muted-dark ml-auto truncate max-w-[200px]">{c.detail}</span>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const STORAGE_KEY = "cam-forge-build-recipe";

function loadSavedRecipe(): Partial<Recipe> {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const saved = JSON.parse(raw);
    // Only restore simple fields — not API response objects
    return {
      brainName: saved.brainName || "",
      description: saved.description || "",
      repoPaths: saved.repoPaths || [],
      agentIds: saved.agentIds || [],
      promptTemplate: saved.promptTemplate || "repo-mine-misc.md",
    };
  } catch {
    return {};
  }
}

function saveRecipe(recipe: Recipe) {
  try {
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        brainName: recipe.brainName,
        description: recipe.description,
        repoPaths: recipe.repoPaths,
        agentIds: recipe.agentIds,
        promptTemplate: recipe.promptTemplate,
      })
    );
  } catch {
    // sessionStorage full or unavailable — non-critical
  }
}

export default function BuildPage() {
  const [recipe, setRecipe] = useState<Recipe>(() => ({
    brainName: "",
    description: "",
    repoPaths: [],
    agentIds: [],
    promptTemplate: "repo-mine-misc.md",
    existingKnowledge: null,
    gapInfo: null,
    repoPreview: null,
    validation: null,
    ...loadSavedRecipe(),
  }));
  const [agents, setAgents] = useState<Record<string, Record<string, unknown>>>({});
  const [prompts, setPrompts] = useState<PromptInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [building, setBuilding] = useState(false);
  const [buildResult, setBuildResult] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Persist recipe to sessionStorage on changes
  useEffect(() => {
    saveRecipe(recipe);
  }, [recipe]);

  // Load config and prompts on intent submit
  const handleIntentSubmit = useCallback(
    async (intent: string) => {
      setLoading(true);
      setError(null);
      try {
        const [configData, promptsData, searchData, gapData] = await Promise.all([
          getConfig(),
          getPrompts(),
          searchKnowledge(intent, 10),
          getGapsMatrix().catch(() => null),
        ]);
        setAgents((configData.agents as Record<string, Record<string, unknown>>) || {});
        setPrompts(promptsData.prompts || []);

        // Extract brain name heuristic from intent
        const words = intent.toLowerCase().split(/\s+/);
        const langWords = ["python", "typescript", "go", "rust", "sql", "java", "elixir", "react"];
        const matchedLang = words.find((w) => langWords.includes(w));

        setRecipe((prev) => ({
          ...prev,
          brainName: matchedLang || prev.brainName,
          description: intent,
          existingKnowledge: searchData,
          gapInfo: gapData,
          agentIds: Object.entries((configData.agents as Record<string, Record<string, unknown>>) || {})
            .filter(([, v]) => v.enabled)
            .map(([k]) => k)
            .slice(0, 3),
        }));
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        setLoading(false);
      }
    },
    []
  );

  const handleRepoPreview = useCallback(async (path: string) => {
    setScanning(true);
    try {
      const preview = await previewRepo(path);
      setRecipe((prev) => ({
        ...prev,
        repoPreview: preview,
        brainName: prev.brainName || (preview.suggested_brain as string) || "",
      }));
    } catch {
      // Silently handle — preview is non-critical
    } finally {
      setScanning(false);
    }
  }, []);

  const handleValidate = useCallback(async () => {
    try {
      const result = await validateForge(recipe.brainName, recipe.agentIds, recipe.repoPaths);
      setRecipe((prev) => ({ ...prev, validation: result }));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [recipe.brainName, recipe.agentIds, recipe.repoPaths]);

  const handleBuild = useCallback(async () => {
    setBuilding(true);
    setError(null);
    try {
      // Step 1: Create the brain
      const result = await createGanglion(recipe.brainName, recipe.description, recipe.promptTemplate);
      setBuildResult(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBuilding(false);
    }
  }, [recipe.brainName, recipe.description, recipe.promptTemplate]);

  const updateRecipe = useCallback((patch: Partial<Recipe>) => {
    setRecipe((prev) => ({ ...prev, ...patch }));
  }, []);

  const ready = recipe.brainName.length >= 2 && recipe.description.length > 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Build a Brain</h1>
          <p className="text-muted mt-1">
            Describe what you want to build — CAM will analyze existing knowledge and propose a recipe.
          </p>
        </div>
        <Link href="/forge" className="text-sm text-muted hover:text-foreground">
          Back to Brain
        </Link>
      </div>

      {/* Intent Bar */}
      <IntentBar
        onSubmit={handleIntentSubmit}
        loading={loading}
        placeholder="Describe what you want to build with CAM..."
        examples={[
          "A brain for PostgreSQL stored procedures and query optimization",
          "React component patterns from my design system repo",
          "Security vulnerability patterns across Go microservices",
          "Machine learning pipeline best practices from my ML repos",
        ]}
      />

      {error && (
        <ErrorBanner message={error} onRetry={() => setError(null)} />
      )}

      {/* Recipe sections — shown after intent analysis */}
      {(recipe.existingKnowledge || recipe.brainName) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          <div className="space-y-4">
            <BrainConfigSection recipe={recipe} onUpdate={updateRecipe} />
            <RepoPathsSection
              recipe={recipe}
              onUpdate={updateRecipe}
              onPreview={handleRepoPreview}
              loading={scanning}
            />
            {Object.keys(agents).length > 0 && (
              <AgentSection recipe={recipe} agents={agents} onUpdate={updateRecipe} />
            )}
          </div>
          <div className="space-y-4">
            {prompts.length > 0 && (
              <PromptSection recipe={recipe} prompts={prompts} onUpdate={updateRecipe} />
            )}
            {recipe.existingKnowledge && (
              <ExistingKnowledgePanel data={recipe.existingKnowledge} />
            )}
            {recipe.validation && <ValidationPanel validation={recipe.validation} />}
          </div>
        </div>
      )}

      {/* Build bar */}
      {ready && (
        <div className="sticky bottom-0 bg-card/95 backdrop-blur border-t border-card-border py-4 -mx-6 px-6 flex items-center justify-between">
          <div className="text-sm text-muted">
            <span className="text-foreground font-medium">{recipe.brainName}</span> brain
            {recipe.repoPaths.length > 0 && ` — ${recipe.repoPaths.length} repos to mine`}
            {recipe.agentIds.length > 0 && ` — ${recipe.agentIds.length} agents`}
          </div>
          <div className="flex gap-3">
            <button
              onClick={handleValidate}
              className="px-4 py-2 bg-card-border hover:bg-card-hover text-foreground text-sm font-medium rounded-lg transition-colors"
            >
              Validate
            </button>
            <button
              onClick={handleBuild}
              disabled={building}
              className="px-5 py-2.5 bg-accent hover:bg-accent-hover disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors"
            >
              {building ? "Building..." : "Build Now"}
            </button>
          </div>
        </div>
      )}

      {/* Build result */}
      {buildResult && (
        <Card className="border-cam-green/30">
          <CardTitle>Brain Created</CardTitle>
          <div className="text-sm text-foreground">
            <span className="text-cam-green font-bold">
              {buildResult.status as string}
            </span>{" "}
            — {buildResult.name as string}
          </div>
          <div className="text-xs text-muted mt-1">
            DB: {buildResult.db_path as string}
          </div>
          <div className="mt-3 flex gap-3">
            <Link
              href={`/forge/brain/${encodeURIComponent(recipe.brainName)}`}
              className="px-4 py-2 bg-accent hover:bg-accent-hover text-white text-sm font-medium rounded-lg transition-colors"
            >
              View Brain Detail
            </Link>
            <Link
              href="/forge"
              className="px-4 py-2 bg-card-border hover:bg-card-hover text-foreground text-sm font-medium rounded-lg transition-colors"
            >
              Brain Graph
            </Link>
            <Link
              href="/mining"
              className="px-4 py-2 bg-card-border hover:bg-card-hover text-foreground text-sm font-medium rounded-lg transition-colors"
            >
              Start Mining
            </Link>
            <Link
              href="/federation"
              className="px-4 py-2 bg-card-border hover:bg-card-hover text-foreground text-sm font-medium rounded-lg transition-colors"
            >
              Federation Hub
            </Link>
          </div>
        </Card>
      )}
    </div>
  );
}
