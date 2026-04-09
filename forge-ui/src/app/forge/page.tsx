"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import Link from "next/link";
import * as d3 from "d3";
import {
  getBrainGraph,
  getBrainBanditState,
  getCapabilityBoundaries,
  type BrainGraphNode,
  type BrainGraphEdge,
  type BanditArmState,
  type CapabilityBoundaries,
} from "@/lib/api";
import { Card, CardTitle, StatCard } from "@/components/card";
import { GanglionBadge } from "@/components/badge";
import { SkeletonGrid, Skeleton } from "@/components/skeleton";
import { ErrorBanner } from "@/components/error-banner";

// ---------------------------------------------------------------------------
// Brain Graph (D3 Force-Directed)
// ---------------------------------------------------------------------------

const NODE_COLORS: Record<string, string> = {
  primary: "#ff6b3d",
  typescript: "#3178c6",
  go: "#00add8",
  rust: "#dea584",
  python: "#3572a5",
  misc: "#76809d",
};

function getNodeColor(name: string): string {
  return NODE_COLORS[name] || NODE_COLORS.misc;
}

interface BrainGraphProps {
  nodes: BrainGraphNode[];
  edges: BrainGraphEdge[];
  onNodeClick: (node: BrainGraphNode) => void;
}

function BrainGraph({ nodes, edges, onNodeClick }: BrainGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [tooltip, setTooltip] = useState<{
    node: BrainGraphNode;
    x: number;
    y: number;
  } | null>(null);

  useEffect(() => {
    if (!svgRef.current || nodes.length === 0) return;

    const svg = d3.select(svgRef.current);
    const width = 800;
    const height = 500;

    svg.selectAll("*").remove();
    svg.attr("viewBox", `0 0 ${width} ${height}`);

    const maxCount = Math.max(...nodes.map((n) => n.methodology_count), 1);

    // Build D3 data
    const d3Nodes = nodes.map((n) => ({
      ...n,
      r: 20 + (n.methodology_count / maxCount) * 40,
      color: getNodeColor(n.name),
    }));

    // Use string IDs for D3 force link compatibility
    const d3Edges = edges
      .filter((e) => d3Nodes.some((n) => n.id === e.source) && d3Nodes.some((n) => n.id === e.target))
      .map((e) => ({ source: e.source, target: e.target }));

    // Force simulation
    type D3Node = typeof d3Nodes[0] & d3.SimulationNodeDatum;
    const simulation = d3
      .forceSimulation(d3Nodes as D3Node[])
      .force(
        "link",
        d3
          .forceLink<D3Node, d3.SimulationLinkDatum<D3Node>>(d3Edges as d3.SimulationLinkDatum<D3Node>[])
          .id((d) => d.id)
          .distance(120)
      )
      .force("charge", d3.forceManyBody().strength(-300))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force(
        "collision",
        d3.forceCollide().radius((d) => (d as typeof d3Nodes[0]).r + 8)
      );

    // Gradient defs
    const defs = svg.append("defs");
    d3Nodes.forEach((n) => {
      const grad = defs
        .append("radialGradient")
        .attr("id", `grad-${n.id}`)
        .attr("cx", "30%")
        .attr("cy", "30%");
      grad.append("stop").attr("offset", "0%").attr("stop-color", n.color).attr("stop-opacity", 0.4);
      grad.append("stop").attr("offset", "100%").attr("stop-color", n.color).attr("stop-opacity", 0.1);
    });

    // Edge lines
    const linkGroup = svg
      .append("g")
      .selectAll("line")
      .data(d3Edges)
      .enter()
      .append("line")
      .attr("stroke", "#30363d")
      .attr("stroke-width", 1.5)
      .attr("stroke-dasharray", "4 2");

    // Node groups
    const nodeGroup = svg
      .append("g")
      .selectAll("g")
      .data(d3Nodes)
      .enter()
      .append("g")
      .style("cursor", "pointer")
      .on("click", (_, d) => {
        const orig = nodes.find((n) => n.id === d.id);
        if (orig) onNodeClick(orig);
      })
      .on("mouseenter", function (event, d) {
        const orig = nodes.find((n) => n.id === d.id);
        if (orig) {
          setTooltip({
            node: orig,
            x: (d as d3.SimulationNodeDatum).x || 0,
            y: (d as d3.SimulationNodeDatum).y || 0,
          });
        }
        d3.select(this).select("circle.glow").attr("opacity", 0.6);
      })
      .on("mouseleave", function () {
        setTooltip(null);
        d3.select(this).select("circle.glow").attr("opacity", 0);
      });

    // Drag behavior
    const drag = d3
      .drag<SVGGElement, typeof d3Nodes[0]>()
      .on("start", (event, d) => {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        (d as d3.SimulationNodeDatum).fx = (d as d3.SimulationNodeDatum).x;
        (d as d3.SimulationNodeDatum).fy = (d as d3.SimulationNodeDatum).y;
      })
      .on("drag", (event, d) => {
        (d as d3.SimulationNodeDatum).fx = event.x;
        (d as d3.SimulationNodeDatum).fy = event.y;
      })
      .on("end", (event, d) => {
        if (!event.active) simulation.alphaTarget(0);
        (d as d3.SimulationNodeDatum).fx = null;
        (d as d3.SimulationNodeDatum).fy = null;
      });

    (nodeGroup as d3.Selection<SVGGElement, typeof d3Nodes[0], SVGGElement, unknown>).call(drag);

    // Glow circle
    nodeGroup
      .append("circle")
      .attr("class", "glow")
      .attr("r", (d) => d.r + 6)
      .attr("fill", "none")
      .attr("stroke", (d) => d.color)
      .attr("stroke-width", 2)
      .attr("opacity", 0);

    // Main circle
    nodeGroup
      .append("circle")
      .attr("r", (d) => d.r)
      .attr("fill", (d) => `url(#grad-${d.id})`)
      .attr("stroke", (d) => d.color)
      .attr("stroke-width", 2);

    // Pulse animation for primary
    nodeGroup
      .filter((d) => d.is_primary)
      .append("circle")
      .attr("r", (d) => d.r + 3)
      .attr("fill", "none")
      .attr("stroke", "#ff6b3d")
      .attr("stroke-width", 1)
      .attr("opacity", 0.3)
      .append("animate")
      .attr("attributeName", "r")
      .attr("from", (d: typeof d3Nodes[0]) => d.r + 3)
      .attr("to", (d: typeof d3Nodes[0]) => d.r + 15)
      .attr("dur", "2s")
      .attr("repeatCount", "indefinite")
      .attr("begin", "0s");

    nodeGroup
      .filter((d) => d.is_primary)
      .select("circle:last-of-type")
      .append("animate")
      .attr("attributeName", "opacity")
      .attr("from", "0.3")
      .attr("to", "0")
      .attr("dur", "2s")
      .attr("repeatCount", "indefinite");

    // Count text
    nodeGroup
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dominant-baseline", "middle")
      .attr("fill", (d) => d.color)
      .attr("font-size", (d) => (d.r > 35 ? 16 : 12))
      .attr("font-weight", "bold")
      .attr("font-family", "var(--font-geist-mono), monospace")
      .text((d) => d.methodology_count.toLocaleString());

    // Label
    nodeGroup
      .append("text")
      .attr("text-anchor", "middle")
      .attr("y", (d) => d.r + 16)
      .attr("fill", "#8b949e")
      .attr("font-size", 11)
      .attr("font-family", "var(--font-geist-sans), sans-serif")
      .text((d) => d.name);

    // Tick — after simulation resolves string IDs to node objects
    simulation.on("tick", () => {
      linkGroup
        .attr("x1", (d) => ((d.source as unknown as d3.SimulationNodeDatum).x || 0))
        .attr("y1", (d) => ((d.source as unknown as d3.SimulationNodeDatum).y || 0))
        .attr("x2", (d) => ((d.target as unknown as d3.SimulationNodeDatum).x || 0))
        .attr("y2", (d) => ((d.target as unknown as d3.SimulationNodeDatum).y || 0));

      nodeGroup.attr(
        "transform",
        (d) =>
          `translate(${(d as d3.SimulationNodeDatum).x || 0},${(d as d3.SimulationNodeDatum).y || 0})`
      );
    });

    return () => {
      simulation.stop();
    };
  }, [nodes, edges, onNodeClick]);

  return (
    <div className="relative">
      <svg ref={svgRef} className="w-full" style={{ height: 500 }} />
      {tooltip && (
        <div
          className="absolute bg-card border border-card-border rounded-lg p-3 shadow-xl pointer-events-none z-10"
          style={{
            left: `${Math.min(tooltip.x + 20, 600)}px`,
            top: `${Math.min(tooltip.y - 20, 400)}px`,
            maxWidth: 260,
          }}
        >
          <div className="flex items-center gap-2 mb-1.5">
            <GanglionBadge name={tooltip.node.name} />
            <span className="text-xs font-mono text-foreground">
              {tooltip.node.methodology_count} methodologies
            </span>
          </div>
          <div className="text-xs text-muted space-y-0.5">
            <div>
              Fitness: avg {tooltip.node.fitness_summary.avg}, range{" "}
              {tooltip.node.fitness_summary.min}–{tooltip.node.fitness_summary.max}
            </div>
            {Object.entries(tooltip.node.categories)
              .slice(0, 4)
              .map(([cat, cnt]) => (
                <div key={cat}>
                  {cat}: <span className="text-foreground">{cnt}</span>
                </div>
              ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Node Detail Panel
// ---------------------------------------------------------------------------

function NodeDetail({ node }: { node: BrainGraphNode }) {
  const cats = Object.entries(node.categories).sort((a, b) => b[1] - a[1]);
  const maxCat = cats.length > 0 ? cats[0][1] : 1;

  return (
    <Card>
      <div className="flex items-center gap-3 mb-4">
        <GanglionBadge name={node.name} />
        <div>
          <div className="text-lg font-bold text-foreground">
            {node.methodology_count.toLocaleString()} methodologies
          </div>
          <div className="text-xs text-muted">
            fitness avg {node.fitness_summary.avg} | {Object.keys(node.categories).length} categories
          </div>
        </div>
      </div>

      {/* Category breakdown */}
      <div className="space-y-1.5 mb-4">
        {cats.slice(0, 8).map(([cat, cnt]) => (
          <div key={cat} className="flex items-center gap-2">
            <span className="text-xs text-muted w-32 text-right truncate">{cat}</span>
            <div className="flex-1 h-2 bg-card-border rounded-full overflow-hidden">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${(cnt / maxCat) * 100}%`,
                  background: getNodeColor(node.name),
                }}
              />
            </div>
            <span className="text-xs text-foreground font-mono w-8 text-right">{cnt}</span>
          </div>
        ))}
      </div>

      {/* Top methodologies */}
      {node.top_methodologies.length > 0 && (
        <div>
          <div className="text-xs text-muted uppercase tracking-wider mb-2">Top by Fitness</div>
          {node.top_methodologies.map((m, i) => (
            <div key={i} className="flex items-center gap-2 py-1 text-xs">
              <span className="text-accent font-mono">{m.fitness.toFixed(2)}</span>
              <span className="text-foreground truncate">{m.title}</span>
              <span className="text-muted-dark ml-auto">{m.category}</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Bandit Arms Mini View
// ---------------------------------------------------------------------------

function BanditPreview({ arms }: { arms: BanditArmState[] }) {
  if (arms.length === 0)
    return (
      <Card>
        <CardTitle>Thompson Sampling</CardTitle>
        <p className="text-xs text-muted">No bandit data yet — run tasks to populate.</p>
      </Card>
    );

  return (
    <Card>
      <CardTitle>Thompson Sampling — Top Arms</CardTitle>
      <div className="space-y-2">
        {arms.slice(0, 8).map((arm) => (
          <div key={arm.methodology_id} className="flex items-center gap-2">
            {/* CI bar */}
            <div className="flex-1 h-3 bg-card-border rounded-full relative overflow-hidden">
              <div
                className="absolute h-full rounded-full bg-cam-green/30"
                style={{
                  left: `${arm.ci_low * 100}%`,
                  width: `${(arm.ci_high - arm.ci_low) * 100}%`,
                }}
              />
              <div
                className="absolute h-full w-1 bg-cam-green rounded-full"
                style={{ left: `${arm.mean * 100}%` }}
              />
            </div>
            <span className="text-xs font-mono text-foreground w-10 text-right">
              {(arm.mean * 100).toFixed(0)}%
            </span>
            <span className="text-xs text-muted truncate w-28">{arm.title}</span>
            <span className="text-xs text-muted-dark">
              {arm.successes}W/{arm.failures}L
            </span>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Capability Boundaries
// ---------------------------------------------------------------------------

function BoundariesPanel({ boundaries }: { boundaries: CapabilityBoundaries }) {
  const hasData =
    boundaries.hard_tasks.length > 0 ||
    boundaries.failing_methodologies.length > 0 ||
    boundaries.coverage_gaps.length > 0;

  if (!hasData)
    return (
      <Card>
        <CardTitle>Capability Boundaries</CardTitle>
        <p className="text-xs text-muted">No boundary violations detected.</p>
      </Card>
    );

  return (
    <Card>
      <CardTitle>Capability Boundaries</CardTitle>
      {boundaries.hard_tasks.length > 0 && (
        <div className="mb-3">
          <div className="text-xs text-red-400 uppercase tracking-wider mb-1">Hard Tasks</div>
          {boundaries.hard_tasks.map((t) => (
            <div key={t.task_type} className="text-xs text-muted py-0.5">
              <span className="text-foreground">{t.task_type}</span> — {t.agents_tried} agents,{" "}
              {(t.avg_failure_rate * 100).toFixed(0)}% failure
            </div>
          ))}
        </div>
      )}
      {boundaries.failing_methodologies.length > 0 && (
        <div className="mb-3">
          <div className="text-xs text-red-400 uppercase tracking-wider mb-1">
            Failing Methodologies
          </div>
          {boundaries.failing_methodologies.slice(0, 5).map((m) => (
            <div key={m.methodology_id} className="text-xs text-muted py-0.5">
              <span className="text-foreground">{m.title}</span> — {m.failures} failures, 0 wins
            </div>
          ))}
        </div>
      )}
      {boundaries.coverage_gaps.length > 0 && (
        <div>
          <div className="text-xs text-amber-400 uppercase tracking-wider mb-1">Coverage Gaps</div>
          <div className="flex flex-wrap gap-1.5">
            {boundaries.coverage_gaps.slice(0, 10).map((g, i) => (
              <span
                key={i}
                className="text-xs px-2 py-0.5 rounded bg-amber-400/10 text-amber-400 border border-amber-400/20"
              >
                {g.category}
              </span>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ForgePage() {
  const [graphData, setGraphData] = useState<{
    nodes: BrainGraphNode[];
    edges: BrainGraphEdge[];
  } | null>(null);
  const [banditData, setBanditData] = useState<BanditArmState[]>([]);
  const [boundaries, setBoundaries] = useState<CapabilityBoundaries | null>(null);
  const [selectedNode, setSelectedNode] = useState<BrainGraphNode | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([getBrainGraph(), getBrainBanditState(), getCapabilityBoundaries()])
      .then(([graph, bandit, bounds]) => {
        setGraphData(graph);
        setBanditData(bandit.arms);
        setBoundaries(bounds);
      })
      .catch((e) => setError(e.message));
  }, []);

  const handleNodeClick = useCallback((node: BrainGraphNode) => {
    setSelectedNode((prev) => (prev?.id === node.id ? null : node));
  }, []);

  if (error) {
    return (
      <ErrorBanner
        message="Failed to load brain graph"
        detail={error}
        onRetry={() => {
          setError(null);
          Promise.all([getBrainGraph(), getBrainBanditState(), getCapabilityBoundaries()])
            .then(([graph, bandit, bounds]) => {
              setGraphData(graph);
              setBanditData(bandit.arms);
              setBoundaries(bounds);
            })
            .catch((e) => setError(e.message));
        }}
      />
    );
  }

  if (!graphData) {
    return (
      <div className="space-y-6">
        <div><Skeleton className="h-8 w-48" /><Skeleton className="h-4 w-72 mt-2" /></div>
        <SkeletonGrid count={4} />
        <Skeleton className="h-[500px] w-full" />
      </div>
    );
  }

  const totalMethods = graphData.nodes.reduce((s, n) => s + n.methodology_count, 0);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground">The Brain</h1>
          <p className="text-muted mt-1">
            Living knowledge graph — {graphData.nodes.length} ganglia,{" "}
            {totalMethods.toLocaleString()} methodologies
          </p>
        </div>
        <Link
          href="/forge/build"
          className="px-5 py-2.5 bg-accent hover:bg-accent-hover text-white text-sm font-medium rounded-lg transition-colors"
        >
          Build New Brain
        </Link>
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Total Methodologies" value={totalMethods} />
        <StatCard
          label="Active Ganglia"
          value={graphData.nodes.filter((n) => n.methodology_count > 0).length}
        />
        <StatCard label="Thompson Arms" value={banditData.length} />
        <StatCard
          label="Coverage Gaps"
          value={boundaries?.coverage_gaps.length || 0}
          sub={boundaries?.hard_tasks.length ? `${boundaries.hard_tasks.length} hard tasks` : undefined}
        />
      </div>

      {/* Main content: graph + detail panel */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2">
          <Card>
            <CardTitle>Brain Topology</CardTitle>
            <p className="text-xs text-muted mb-2">
              Click a ganglion to see category breakdown. Drag to rearrange.
            </p>
            <BrainGraph
              nodes={graphData.nodes}
              edges={graphData.edges}
              onNodeClick={handleNodeClick}
            />
            {/* Node summary chips */}
            <div className="flex flex-wrap gap-2 mt-4 pt-4 border-t border-card-border">
              {graphData.nodes.map((n) => (
                <button
                  key={n.id}
                  onClick={() => handleNodeClick(n)}
                  className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs transition-colors ${
                    selectedNode?.id === n.id
                      ? "bg-accent/20 border border-accent/40"
                      : "bg-card-border/50 hover:bg-card-border"
                  }`}
                >
                  <GanglionBadge name={n.name} />
                  <span className="text-foreground font-mono">
                    {n.methodology_count.toLocaleString()}
                  </span>
                </button>
              ))}
            </div>
          </Card>
        </div>

        <div className="space-y-4">
          {selectedNode ? (
            <NodeDetail node={selectedNode} />
          ) : (
            <Card>
              <p className="text-sm text-muted">
                Click a brain node to see its category breakdown and top methodologies.
              </p>
            </Card>
          )}
          <BanditPreview arms={banditData} />
          {boundaries && <BoundariesPanel boundaries={boundaries} />}
        </div>
      </div>
    </div>
  );
}
