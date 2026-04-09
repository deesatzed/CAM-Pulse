"use client";

import { useState } from "react";

interface ScriptViewerProps {
  script: string;
  filename?: string;
  language?: string;
}

export function ScriptViewer({
  script,
  filename = "cam-forge.sh",
}: ScriptViewerProps) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    await navigator.clipboard.writeText(script);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const blob = new Blob([script], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="bg-card border border-card-border rounded-xl overflow-hidden">
      <div className="flex items-center justify-between px-4 py-2 border-b border-card-border bg-card-border/30">
        <span className="text-xs text-muted font-mono">{filename}</span>
        <div className="flex gap-2">
          <button
            onClick={handleCopy}
            className="text-xs text-muted hover:text-foreground px-2 py-1 rounded hover:bg-card-border transition-colors"
          >
            {copied ? "Copied!" : "Copy"}
          </button>
          <button
            onClick={handleDownload}
            className="text-xs text-muted hover:text-foreground px-2 py-1 rounded hover:bg-card-border transition-colors"
          >
            Download
          </button>
        </div>
      </div>
      <pre className="p-4 overflow-x-auto text-xs leading-relaxed">
        <code className="text-cam-green font-mono">{script}</code>
      </pre>
    </div>
  );
}
