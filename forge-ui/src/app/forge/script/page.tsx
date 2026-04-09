"use client";

import { useState, useCallback } from "react";
import Link from "next/link";
import { generateScript } from "@/lib/api";
import { Card, CardTitle } from "@/components/card";
import { ScriptViewer } from "@/components/script-viewer";
import { ErrorBanner } from "@/components/error-banner";

// ---------------------------------------------------------------------------
// Available operations for script generation
// ---------------------------------------------------------------------------

const AVAILABLE_OPS = [
  { id: "create_brain", label: "Create Brain", description: "Provision a new ganglion database" },
  { id: "write_prompt", label: "Write Prompt", description: "Generate a custom mining prompt template" },
  { id: "update_config", label: "Update Config", description: "Modify claw.toml settings" },
  { id: "mine_repos", label: "Mine Repos", description: "Extract knowledge from repositories" },
  { id: "rebuild_cag", label: "Rebuild CAG", description: "Rebuild the cache-augmented generation corpus" },
  { id: "run_verification", label: "Run Verification", description: "Execute 7-gate verification checks" },
];

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ScriptPage() {
  const [selectedOps, setSelectedOps] = useState<string[]>([]);
  const [result, setResult] = useState<{
    script: string;
    filename: string;
    description: string;
  } | null>(null);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleOp = useCallback((id: string) => {
    setSelectedOps((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }, []);

  const handleGenerate = useCallback(async () => {
    if (selectedOps.length === 0) return;
    setGenerating(true);
    setError(null);
    try {
      const data = await generateScript(selectedOps);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setGenerating(false);
    }
  }, [selectedOps]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">Script Generator</h1>
          <p className="text-muted mt-1">
            Generate executable shell scripts for CAM operations.
          </p>
        </div>
        <Link href="/forge" className="text-sm text-muted hover:text-foreground">
          Back to Brain
        </Link>
      </div>

      {/* Operation selector */}
      <Card>
        <CardTitle>Select Operations</CardTitle>
        <p className="text-xs text-muted mb-3">
          Choose which operations to include in the generated script.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {AVAILABLE_OPS.map((op) => {
            const selected = selectedOps.includes(op.id);
            return (
              <button
                key={op.id}
                onClick={() => toggleOp(op.id)}
                className={`flex items-center gap-3 px-4 py-3 rounded-lg text-left transition-colors ${
                  selected
                    ? "bg-accent/10 border border-accent/40"
                    : "bg-card-border/30 border border-transparent hover:border-card-border"
                }`}
              >
                <span
                  className={`w-5 h-5 rounded flex items-center justify-center text-xs font-bold ${
                    selected ? "bg-accent text-white" : "bg-card-border text-muted"
                  }`}
                >
                  {selected ? "+" : ""}
                </span>
                <div>
                  <div className="text-sm font-medium text-foreground">{op.label}</div>
                  <div className="text-xs text-muted">{op.description}</div>
                </div>
              </button>
            );
          })}
        </div>
        <div className="mt-4 flex items-center justify-between">
          <span className="text-xs text-muted">
            {selectedOps.length} operation{selectedOps.length !== 1 ? "s" : ""} selected
          </span>
          <button
            onClick={handleGenerate}
            disabled={generating || selectedOps.length === 0}
            className="px-5 py-2.5 bg-accent hover:bg-accent-hover disabled:opacity-40 text-white text-sm font-medium rounded-lg transition-colors"
          >
            {generating ? "Generating..." : "Generate Script"}
          </button>
        </div>
      </Card>

      {error && <ErrorBanner message={error} onRetry={handleGenerate} />}

      {/* Generated script */}
      {result && (
        <div className="space-y-4">
          <div className="flex items-center gap-3">
            <h2 className="text-lg font-bold text-foreground">Generated Script</h2>
            <span className="text-xs text-muted">{result.description}</span>
          </div>
          <ScriptViewer script={result.script} filename={result.filename} />
          <div className="text-xs text-muted">
            Run with: <code className="text-cam-green font-mono">chmod +x {result.filename} && ./{result.filename}</code>
          </div>
        </div>
      )}
    </div>
  );
}
