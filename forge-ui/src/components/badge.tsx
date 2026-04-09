const GANGLION_COLORS: Record<string, string> = {
  primary: "#ff6b3d",
  typescript: "#3178c6",
  go: "#00add8",
  rust: "#dea584",
  misc: "#76809d",
};

export function GanglionBadge({ name }: { name: string }) {
  const color = GANGLION_COLORS[name] || "#76809d";
  return (
    <span
      className="inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold uppercase tracking-wider"
      style={{
        backgroundColor: `${color}18`,
        color,
        border: `1px solid ${color}33`,
      }}
    >
      {name}
    </span>
  );
}

export function LifecycleBadge({ state }: { state: string }) {
  const colors: Record<string, string> = {
    embryonic: "#f0883e",
    viable: "#7ee787",
    thriving: "#3fb950",
    declining: "#f85149",
    dormant: "#8b949e",
    dead: "#484f58",
  };
  const c = colors[state] || "#8b949e";
  return (
    <span
      className="inline-block px-2 py-0.5 rounded text-xs"
      style={{ backgroundColor: `${c}18`, color: c }}
    >
      {state}
    </span>
  );
}

export function LangBadge({ lang }: { lang: string }) {
  return (
    <span className="inline-block px-2 py-0.5 rounded text-xs bg-cam-green/10 text-cam-green">
      {lang || "unknown"}
    </span>
  );
}
