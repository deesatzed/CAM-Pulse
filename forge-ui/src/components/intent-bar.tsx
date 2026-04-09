"use client";

import { useState, useRef, useEffect } from "react";

export interface IntentBarProps {
  placeholder?: string;
  onSubmit: (intent: string) => void;
  loading?: boolean;
  examples?: string[];
}

export function IntentBar({
  placeholder = "Describe what you want to build with CAM...",
  onSubmit,
  loading = false,
  examples,
}: IntentBarProps) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (value.trim() && !loading) {
      onSubmit(value.trim());
    }
  };

  return (
    <form onSubmit={handleSubmit} className="relative">
      <div className="flex items-center gap-3 bg-card border border-card-border rounded-xl px-4 py-3 focus-within:border-accent/60 focus-within:ring-1 focus-within:ring-accent/30 transition-all">
        <svg
          className="w-5 h-5 text-muted shrink-0"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M13 10V3L4 14h7v7l9-11h-7z"
          />
        </svg>
        <input
          ref={inputRef}
          type="text"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          placeholder={placeholder}
          className="flex-1 bg-transparent text-foreground text-sm placeholder:text-muted-dark outline-none"
          disabled={loading}
        />
        <button
          type="submit"
          disabled={!value.trim() || loading}
          className="shrink-0 px-4 py-1.5 bg-accent text-white text-sm font-medium rounded-lg disabled:opacity-40 disabled:cursor-not-allowed hover:bg-accent-hover transition-colors"
        >
          {loading ? "Analyzing..." : "Analyze"}
        </button>
      </div>
      <div className="text-xs text-muted-dark mt-2 px-1">
        {examples && examples.length > 0
          ? `Examples: ${examples.map((e) => `"${e}"`).join(" · ")}`
          : 'Examples: "Build a SQL brain for my PostgreSQL database" · "Mine my Django project for security patterns" · "What knowledge do I have about testing?"'}
      </div>
    </form>
  );
}
