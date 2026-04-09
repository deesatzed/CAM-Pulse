"use client";

import { useState } from "react";

interface ErrorBannerProps {
  message: string;
  detail?: string;
  onRetry?: () => void;
}

export function ErrorBanner({ message, detail, onRetry }: ErrorBannerProps) {
  const [showDetail, setShowDetail] = useState(false);

  return (
    <div className="bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-3">
      <div className="flex items-center justify-between">
        <span className="text-red-400 text-sm">{message}</span>
        <div className="flex gap-2">
          {detail && (
            <button
              onClick={() => setShowDetail(!showDetail)}
              className="text-xs text-red-400/70 hover:text-red-400 px-2 py-1 rounded hover:bg-red-500/10 transition-colors"
            >
              {showDetail ? "Hide" : "Details"}
            </button>
          )}
          {onRetry && (
            <button
              onClick={onRetry}
              className="text-xs text-foreground bg-card-border px-3 py-1 rounded-lg hover:bg-card-border/80 transition-colors"
            >
              Retry
            </button>
          )}
        </div>
      </div>
      {showDetail && detail && (
        <pre className="mt-2 text-xs text-red-400/70 font-mono whitespace-pre-wrap">
          {detail}
        </pre>
      )}
    </div>
  );
}
