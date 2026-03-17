"""Rich CLI dashboard for monitoring CLAW operations.

Provides formatted displays of agent scores, fleet status, cost summaries,
pattern extraction progress, and quality trajectories. Uses the Rich library
for styled terminal output when available, with a plain-text fallback.

Each ``render_*`` method returns a string rather than printing directly, which
enables testing, piping, and composition. The ``render_full_dashboard`` method
composes all panels into a single dashboard view.

All data is read from the database via the Repository/Engine layer — no data
is fabricated or cached.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from claw.db.repository import Repository

logger = logging.getLogger("claw.dashboard")

# Attempt to import Rich for styled output; fall back to plain text
try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    HAS_RICH = True
except ImportError:
    HAS_RICH = False
    logger.info("Rich library not available; dashboard will use plain text")


class Dashboard:
    """CLI dashboard for monitoring CLAW system state.

    Renders formatted views of agent performance, fleet status, costs,
    patterns, and quality trajectories from the database.

    Usage::

        dashboard = Dashboard(repository)
        output = await dashboard.render_full_dashboard()
        print(output)
    """

    def __init__(self, repository: Repository) -> None:
        """Initialize the Dashboard.

        Args:
            repository: Data access layer for querying system state.
        """
        self.repository = repository
        if HAS_RICH:
            self._console = Console(record=True, width=120)
        logger.info("Dashboard initialized (rich=%s)", HAS_RICH)

    # -------------------------------------------------------------------
    # Agent Scores
    # -------------------------------------------------------------------

    async def render_agent_scores(self) -> str:
        """Render a table of agent performance scores.

        Queries the ``agent_scores`` table and displays per-agent, per-task-type
        breakdown showing success rate, average quality, average duration, and
        average cost.

        Returns:
            Formatted string with agent score data.
        """
        rows = await self.repository.get_agent_scores()

        if not rows:
            return self._wrap_panel("No agent scores recorded yet.", "Agent Scores")

        if HAS_RICH:
            table = Table(title="Agent Scores", show_lines=True)
            table.add_column("Agent", style="cyan", no_wrap=True)
            table.add_column("Task Type", style="green")
            table.add_column("Attempts", justify="right")
            table.add_column("Success Rate", justify="right", style="bold")
            table.add_column("Avg Quality", justify="right")
            table.add_column("Avg Duration (s)", justify="right")
            table.add_column("Avg Cost ($)", justify="right")
            table.add_column("Last Used", no_wrap=True)

            # Sort by agent_id then task_type for consistent display
            sorted_rows = sorted(rows, key=lambda r: (r.get("agent_id", ""), r.get("task_type", "")))

            for row in sorted_rows:
                total = row.get("total_attempts", 0)
                successes = row.get("successes", 0)
                success_rate = f"{(successes / total * 100):.1f}%" if total > 0 else "N/A"
                avg_quality = f"{row.get('avg_quality_score', 0.0):.2f}"
                avg_duration = f"{row.get('avg_duration_seconds', 0.0):.1f}"
                avg_cost = f"{row.get('avg_cost_usd', 0.0):.4f}"
                last_used = row.get("last_used_at", "Never") or "Never"
                if last_used != "Never":
                    # Truncate to date for display
                    last_used = last_used[:10]

                # Compute bayesian score for display
                bayesian_score = self._compute_bayesian_score(row)

                table.add_row(
                    str(row.get("agent_id", "?")),
                    str(row.get("task_type", "?")),
                    str(total),
                    success_rate,
                    f"{avg_quality} (B:{bayesian_score:.2f})",
                    avg_duration,
                    avg_cost,
                    last_used,
                )

            return self._render_rich_table(table)

        else:
            # Plain text fallback
            lines = ["=== Agent Scores ===", ""]
            header = (
                f"{'Agent':<12} {'Task Type':<20} {'Attempts':>8} "
                f"{'Success':>8} {'Quality':>8} {'Duration':>10} "
                f"{'Cost':>8} {'Last Used':>12}"
            )
            lines.append(header)
            lines.append("-" * len(header))

            sorted_rows = sorted(rows, key=lambda r: (r.get("agent_id", ""), r.get("task_type", "")))

            for row in sorted_rows:
                total = row.get("total_attempts", 0)
                successes = row.get("successes", 0)
                success_rate = f"{(successes / total * 100):.1f}%" if total > 0 else "N/A"
                avg_quality = f"{row.get('avg_quality_score', 0.0):.2f}"
                avg_duration = f"{row.get('avg_duration_seconds', 0.0):.1f}s"
                avg_cost = f"${row.get('avg_cost_usd', 0.0):.4f}"
                last_used = (row.get("last_used_at") or "Never")[:10]

                lines.append(
                    f"{str(row.get('agent_id', '?')):<12} "
                    f"{str(row.get('task_type', '?')):<20} "
                    f"{total:>8} {success_rate:>8} {avg_quality:>8} "
                    f"{avg_duration:>10} {avg_cost:>8} {last_used:>12}"
                )

            return "\n".join(lines)

    def _compute_bayesian_score(self, score_row: dict[str, Any]) -> float:
        """Compute a Bayesian-adjusted quality score for an agent/task-type pair.

        Uses a simple Bayesian average: (C * m + sum_of_ratings) / (C + n)
        where C is the confidence threshold (5 samples) and m is the prior
        mean (0.5).

        Args:
            score_row: A dict from the agent_scores table.

        Returns:
            Bayesian-adjusted score between 0.0 and 1.0.
        """
        total = score_row.get("total_attempts", 0)
        avg_quality = score_row.get("avg_quality_score", 0.0)

        # Prior parameters
        confidence_threshold = 5
        prior_mean = 0.5

        # Bayesian average
        bayesian = (confidence_threshold * prior_mean + total * avg_quality) / (
            confidence_threshold + total
        )
        return bayesian

    # -------------------------------------------------------------------
    # Fleet Status
    # -------------------------------------------------------------------

    async def render_fleet_status(self) -> str:
        """Render fleet repository status overview.

        Shows status distribution counts, budget utilization, and task
        completion rates across the fleet.

        Returns:
            Formatted string with fleet status data.
        """
        rows = await self.repository.engine.fetch_all(
            "SELECT * FROM fleet_repos ORDER BY priority DESC",
        )

        if not rows:
            return self._wrap_panel("No fleet repos registered.", "Fleet Status")

        # Aggregate by status
        status_counts: dict[str, int] = {}
        total_allocated = 0.0
        total_used = 0.0
        total_tasks_created = 0
        total_tasks_completed = 0

        for row in rows:
            status = row.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            total_allocated += row.get("budget_allocated_usd", 0.0)
            total_used += row.get("budget_used_usd", 0.0)
            total_tasks_created += row.get("tasks_created", 0)
            total_tasks_completed += row.get("tasks_completed", 0)

        if HAS_RICH:
            # Status summary table
            status_table = Table(title="Fleet Status Summary", show_lines=True)
            status_table.add_column("Status", style="cyan")
            status_table.add_column("Count", justify="right", style="bold")

            all_statuses = ["pending", "evaluating", "enhancing", "completed", "failed", "skipped"]
            for status in all_statuses:
                count = status_counts.get(status, 0)
                if count > 0:
                    status_table.add_row(status, str(count))

            # Repos detail table
            detail_table = Table(title="Fleet Repos", show_lines=True)
            detail_table.add_column("Repo", style="green", no_wrap=True)
            detail_table.add_column("Status", style="cyan")
            detail_table.add_column("Priority", justify="right")
            detail_table.add_column("Budget ($)", justify="right")
            detail_table.add_column("Used ($)", justify="right")
            detail_table.add_column("Tasks", justify="right")
            detail_table.add_column("Eval Score", justify="right")

            for row in rows:
                allocated = row.get("budget_allocated_usd", 0.0)
                used = row.get("budget_used_usd", 0.0)
                tasks_created = row.get("tasks_created", 0)
                tasks_completed = row.get("tasks_completed", 0)
                task_str = f"{tasks_completed}/{tasks_created}"
                eval_score = row.get("evaluation_score")
                eval_str = f"{eval_score:.2f}" if eval_score is not None else "N/A"

                detail_table.add_row(
                    str(row.get("repo_name", "?")),
                    str(row.get("status", "?")),
                    f"{row.get('priority', 0.0):.1f}",
                    f"{allocated:.2f}",
                    f"{used:.2f}",
                    task_str,
                    eval_str,
                )

            # Budget summary line
            budget_pct = (total_used / total_allocated * 100) if total_allocated > 0 else 0.0
            task_pct = (total_tasks_completed / total_tasks_created * 100) if total_tasks_created > 0 else 0.0

            summary_text = (
                f"Total repos: {len(rows)} | "
                f"Budget: ${total_used:.2f} / ${total_allocated:.2f} ({budget_pct:.1f}%) | "
                f"Tasks: {total_tasks_completed} / {total_tasks_created} ({task_pct:.1f}%)"
            )

            # Render both tables
            self._console.print(status_table)
            self._console.print(detail_table)
            self._console.print(f"\n{summary_text}")
            output = self._console.export_text()
            self._console._record_buffer.clear()
            return output

        else:
            # Plain text fallback
            lines = ["=== Fleet Status ===", ""]

            lines.append("Status Distribution:")
            all_statuses = ["pending", "evaluating", "enhancing", "completed", "failed", "skipped"]
            for status in all_statuses:
                count = status_counts.get(status, 0)
                if count > 0:
                    lines.append(f"  {status}: {count}")

            lines.append("")
            lines.append("Repos:")
            header = (
                f"  {'Repo':<30} {'Status':<12} {'Priority':>8} "
                f"{'Budget':>10} {'Used':>10} {'Tasks':>8} {'Score':>8}"
            )
            lines.append(header)
            lines.append("  " + "-" * (len(header) - 2))

            for row in rows:
                allocated = row.get("budget_allocated_usd", 0.0)
                used = row.get("budget_used_usd", 0.0)
                tasks_created = row.get("tasks_created", 0)
                tasks_completed = row.get("tasks_completed", 0)
                task_str = f"{tasks_completed}/{tasks_created}"
                eval_score = row.get("evaluation_score")
                eval_str = f"{eval_score:.2f}" if eval_score is not None else "N/A"

                lines.append(
                    f"  {str(row.get('repo_name', '?')):<30} "
                    f"{str(row.get('status', '?')):<12} "
                    f"{row.get('priority', 0.0):>8.1f} "
                    f"${allocated:>9.2f} ${used:>9.2f} "
                    f"{task_str:>8} {eval_str:>8}"
                )

            budget_pct = (total_used / total_allocated * 100) if total_allocated > 0 else 0.0
            task_pct = (total_tasks_completed / total_tasks_created * 100) if total_tasks_created > 0 else 0.0

            lines.append("")
            lines.append(
                f"Total: {len(rows)} repos | "
                f"Budget: ${total_used:.2f}/${total_allocated:.2f} ({budget_pct:.1f}%) | "
                f"Tasks: {total_tasks_completed}/{total_tasks_created} ({task_pct:.1f}%)"
            )

            return "\n".join(lines)

    # -------------------------------------------------------------------
    # Cost Summary
    # -------------------------------------------------------------------

    async def render_cost_summary(self) -> str:
        """Render token cost summary by agent and by day.

        Queries the ``token_costs`` table and aggregates costs by agent_id
        and by calendar date.

        Returns:
            Formatted string with cost breakdown data.
        """
        # Aggregate by agent
        agent_rows = await self.repository.engine.fetch_all(
            """SELECT agent_id,
                      COUNT(*) as call_count,
                      SUM(input_tokens) as total_input,
                      SUM(output_tokens) as total_output,
                      SUM(total_tokens) as total_tokens,
                      SUM(cost_usd) as total_cost
               FROM token_costs
               GROUP BY agent_id
               ORDER BY total_cost DESC""",
        )

        # Aggregate by day
        day_rows = await self.repository.engine.fetch_all(
            """SELECT DATE(created_at) as day,
                      COUNT(*) as call_count,
                      SUM(total_tokens) as total_tokens,
                      SUM(cost_usd) as total_cost
               FROM token_costs
               GROUP BY DATE(created_at)
               ORDER BY day DESC
               LIMIT 30""",
        )

        if not agent_rows and not day_rows:
            return self._wrap_panel("No token costs recorded yet.", "Cost Summary")

        if HAS_RICH:
            output_parts = []

            if agent_rows:
                agent_table = Table(title="Cost by Agent", show_lines=True)
                agent_table.add_column("Agent", style="cyan")
                agent_table.add_column("Calls", justify="right")
                agent_table.add_column("Input Tokens", justify="right")
                agent_table.add_column("Output Tokens", justify="right")
                agent_table.add_column("Total Tokens", justify="right")
                agent_table.add_column("Total Cost ($)", justify="right", style="bold")

                grand_total_cost = 0.0
                for row in agent_rows:
                    agent_id = str(row.get("agent_id") or "unknown")
                    cost = row.get("total_cost", 0.0) or 0.0
                    grand_total_cost += cost

                    agent_table.add_row(
                        agent_id,
                        str(row.get("call_count", 0)),
                        f"{row.get('total_input', 0) or 0:,}",
                        f"{row.get('total_output', 0) or 0:,}",
                        f"{row.get('total_tokens', 0) or 0:,}",
                        f"{cost:.4f}",
                    )

                # Grand total row
                agent_table.add_row(
                    "TOTAL", "", "", "", "",
                    f"{grand_total_cost:.4f}",
                    style="bold yellow",
                )

                self._console.print(agent_table)
                output_parts.append(self._console.export_text())
                self._console._record_buffer.clear()

            if day_rows:
                day_table = Table(title="Cost by Day (last 30 days)", show_lines=True)
                day_table.add_column("Date", style="green")
                day_table.add_column("Calls", justify="right")
                day_table.add_column("Total Tokens", justify="right")
                day_table.add_column("Cost ($)", justify="right", style="bold")

                for row in day_rows:
                    day_table.add_row(
                        str(row.get("day", "?")),
                        str(row.get("call_count", 0)),
                        f"{row.get('total_tokens', 0) or 0:,}",
                        f"{row.get('total_cost', 0.0) or 0.0:.4f}",
                    )

                self._console.print(day_table)
                output_parts.append(self._console.export_text())
                self._console._record_buffer.clear()

            return "\n".join(output_parts)

        else:
            # Plain text fallback
            lines = ["=== Cost Summary ===", ""]

            if agent_rows:
                lines.append("Cost by Agent:")
                header = (
                    f"  {'Agent':<15} {'Calls':>6} {'Input Tok':>12} "
                    f"{'Output Tok':>12} {'Total Tok':>12} {'Cost ($)':>10}"
                )
                lines.append(header)
                lines.append("  " + "-" * (len(header) - 2))

                grand_total_cost = 0.0
                for row in agent_rows:
                    agent_id = str(row.get("agent_id") or "unknown")
                    cost = row.get("total_cost", 0.0) or 0.0
                    grand_total_cost += cost

                    lines.append(
                        f"  {agent_id:<15} "
                        f"{row.get('call_count', 0):>6} "
                        f"{row.get('total_input', 0) or 0:>12,} "
                        f"{row.get('total_output', 0) or 0:>12,} "
                        f"{row.get('total_tokens', 0) or 0:>12,} "
                        f"${cost:>9.4f}"
                    )

                lines.append(f"  {'TOTAL':<15} {'':>6} {'':>12} {'':>12} {'':>12} ${grand_total_cost:>9.4f}")
                lines.append("")

            if day_rows:
                lines.append("Cost by Day (last 30):")
                header = f"  {'Date':<12} {'Calls':>6} {'Tokens':>12} {'Cost ($)':>10}"
                lines.append(header)
                lines.append("  " + "-" * (len(header) - 2))

                for row in day_rows:
                    lines.append(
                        f"  {str(row.get('day', '?')):<12} "
                        f"{row.get('call_count', 0):>6} "
                        f"{row.get('total_tokens', 0) or 0:>12,} "
                        f"${row.get('total_cost', 0.0) or 0.0:>9.4f}"
                    )

            return "\n".join(lines)

    # -------------------------------------------------------------------
    # Pattern Summary
    # -------------------------------------------------------------------

    async def render_pattern_summary(self, project_id: Optional[str] = None) -> str:
        """Render methodology/pattern extraction summary.

        Shows the distribution of methodologies across lifecycle states
        (embryonic, viable, thriving, declining, dormant, dead) and top
        methodology types.

        Args:
            project_id: Optional project filter. If provided, only shows
                        methodologies linked to tasks in that project.
                        Currently shows all methodologies (project filtering
                        requires join through tasks).

        Returns:
            Formatted string with pattern summary data.
        """
        # Lifecycle state distribution
        lifecycle_rows = await self.repository.engine.fetch_all(
            """SELECT lifecycle_state, COUNT(*) as cnt
               FROM methodologies
               GROUP BY lifecycle_state
               ORDER BY cnt DESC""",
        )

        # Methodology type distribution
        type_rows = await self.repository.engine.fetch_all(
            """SELECT methodology_type, COUNT(*) as cnt
               FROM methodologies
               WHERE methodology_type IS NOT NULL
               GROUP BY methodology_type
               ORDER BY cnt DESC
               LIMIT 10""",
        )

        # Top performing methodologies (by success/retrieval ratio)
        top_rows = await self.repository.engine.fetch_all(
            """SELECT id, problem_description, lifecycle_state,
                      retrieval_count, success_count, failure_count, generation
               FROM methodologies
               WHERE retrieval_count > 0
               ORDER BY (CAST(success_count AS REAL) / MAX(retrieval_count, 1)) DESC
               LIMIT 10""",
        )

        # Total count
        total_row = await self.repository.engine.fetch_one(
            "SELECT COUNT(*) as cnt FROM methodologies",
        )
        total_count = total_row["cnt"] if total_row else 0
        evidence_audit = await self.repository.get_methodology_evidence_audit(limit=5)
        evidence_summary = evidence_audit["summary"]
        flagged_items = evidence_audit["flagged"]

        if total_count == 0:
            return self._wrap_panel("No methodologies extracted yet.", "Pattern Summary")

        if HAS_RICH:
            output_parts = []

            # Lifecycle distribution
            lifecycle_table = Table(title=f"Pattern Lifecycle ({total_count} total)", show_lines=True)
            lifecycle_table.add_column("State", style="cyan")
            lifecycle_table.add_column("Count", justify="right", style="bold")
            lifecycle_table.add_column("Percentage", justify="right")

            all_states = ["embryonic", "viable", "thriving", "declining", "dormant", "dead"]
            state_counts = {row["lifecycle_state"]: row["cnt"] for row in lifecycle_rows}

            for state in all_states:
                count = state_counts.get(state, 0)
                pct = (count / total_count * 100) if total_count > 0 else 0.0
                if count > 0:
                    lifecycle_table.add_row(state, str(count), f"{pct:.1f}%")

            self._console.print(lifecycle_table)
            output_parts.append(self._console.export_text())
            self._console._record_buffer.clear()

            if evidence_summary["total_reviewed"] > 0:
                evidence_table = Table(title="Evidence Quality", show_lines=True)
                evidence_table.add_column("Metric", style="magenta")
                evidence_table.add_column("Count", justify="right", style="bold")
                evidence_table.add_row("High-trust reviewed", str(evidence_summary["total_reviewed"]))
                evidence_table.add_row("Attribution-backed", str(evidence_summary["attribution_backed_total"]))
                evidence_table.add_row("Legacy-backed", str(evidence_summary["legacy_backed_total"]))
                evidence_table.add_row("Low expectation", str(evidence_summary["low_expectation_total"]))
                evidence_table.add_row("Flagged for audit", str(evidence_summary["flagged_total"]))
                self._console.print(evidence_table)
                output_parts.append(self._console.export_text())
                self._console._record_buffer.clear()

            if flagged_items:
                flagged_table = Table(title="Flagged High-Trust Methods", show_lines=True)
                flagged_table.add_column("ID", style="cyan", width=8)
                flagged_table.add_column("State", width=10)
                flagged_table.add_column("Scope", width=8)
                flagged_table.add_column("Evidence", width=11)
                flagged_table.add_column("Attr Succ", justify="right", width=9)
                flagged_table.add_column("Exp", justify="right", width=6)
                flagged_table.add_column("Problem", max_width=46)

                for item in flagged_items:
                    expectation_score = item.get("avg_expectation_match_score")
                    flagged_table.add_row(
                        item["id"][:8],
                        item["lifecycle_state"],
                        item["scope"],
                        item["evidence_source"],
                        str(item["attributed_success_count"]),
                        "-" if expectation_score is None else f"{float(expectation_score):.2f}",
                        item["problem_description"][:46],
                    )

                self._console.print(flagged_table)
                output_parts.append(self._console.export_text())
                self._console._record_buffer.clear()

            # Type distribution
            if type_rows:
                type_table = Table(title="Methodology Types", show_lines=True)
                type_table.add_column("Type", style="green")
                type_table.add_column("Count", justify="right")

                for row in type_rows:
                    type_table.add_row(
                        str(row.get("methodology_type", "?")),
                        str(row.get("cnt", 0)),
                    )

                self._console.print(type_table)
                output_parts.append(self._console.export_text())
                self._console._record_buffer.clear()

            # Top performing
            if top_rows:
                top_table = Table(title="Top Performing Patterns", show_lines=True)
                top_table.add_column("Problem", style="white", max_width=50)
                top_table.add_column("State", style="cyan")
                top_table.add_column("Retrieved", justify="right")
                top_table.add_column("Success", justify="right")
                top_table.add_column("Failure", justify="right")
                top_table.add_column("Gen", justify="right")

                for row in top_rows:
                    desc = str(row.get("problem_description", ""))
                    if len(desc) > 50:
                        desc = desc[:47] + "..."

                    top_table.add_row(
                        desc,
                        str(row.get("lifecycle_state", "?")),
                        str(row.get("retrieval_count", 0)),
                        str(row.get("success_count", 0)),
                        str(row.get("failure_count", 0)),
                        str(row.get("generation", 0)),
                    )

                self._console.print(top_table)
                output_parts.append(self._console.export_text())
                self._console._record_buffer.clear()

            return "\n".join(output_parts)

        else:
            # Plain text fallback
            lines = [f"=== Pattern Summary ({total_count} total) ===", ""]

            lines.append("Lifecycle Distribution:")
            all_states = ["embryonic", "viable", "thriving", "declining", "dormant", "dead"]
            state_counts = {row["lifecycle_state"]: row["cnt"] for row in lifecycle_rows}
            for state in all_states:
                count = state_counts.get(state, 0)
                pct = (count / total_count * 100) if total_count > 0 else 0.0
                if count > 0:
                    lines.append(f"  {state}: {count} ({pct:.1f}%)")

            if evidence_summary["total_reviewed"] > 0:
                lines.append("")
                lines.append("Evidence Quality:")
                lines.append(f"  high-trust reviewed: {evidence_summary['total_reviewed']}")
                lines.append(f"  attribution-backed: {evidence_summary['attribution_backed_total']}")
                lines.append(f"  legacy-backed: {evidence_summary['legacy_backed_total']}")
                lines.append(f"  low expectation: {evidence_summary['low_expectation_total']}")
                lines.append(f"  flagged for audit: {evidence_summary['flagged_total']}")

            if flagged_items:
                lines.append("")
                lines.append("Flagged High-Trust Methods:")
                for item in flagged_items:
                    expectation_score = item.get("avg_expectation_match_score")
                    exp = "-" if expectation_score is None else f"{float(expectation_score):.2f}"
                    lines.append(
                        f"  [{item['lifecycle_state']}/{item['scope']}] {item['problem_description'][:50]} "
                        f"(evidence={item['evidence_source']}, attributed_success={item['attributed_success_count']}, exp={exp})"
                    )

            if type_rows:
                lines.append("")
                lines.append("Methodology Types:")
                for row in type_rows:
                    lines.append(
                        f"  {str(row.get('methodology_type', '?'))}: "
                        f"{row.get('cnt', 0)}"
                    )

            if top_rows:
                lines.append("")
                lines.append("Top Performing Patterns:")
                for row in top_rows:
                    desc = str(row.get("problem_description", ""))
                    if len(desc) > 50:
                        desc = desc[:47] + "..."
                    lines.append(
                        f"  [{row.get('lifecycle_state', '?')}] {desc} "
                        f"(retrieved={row.get('retrieval_count', 0)}, "
                        f"success={row.get('success_count', 0)}, "
                        f"gen={row.get('generation', 0)})"
                    )

            return "\n".join(lines)

    # -------------------------------------------------------------------
    # Quality Trajectory
    # -------------------------------------------------------------------

    async def render_quality_trajectory(self, project_id: Optional[str] = None) -> str:
        """Render quality score trends over time.

        Shows how agent quality scores have evolved by querying the
        ``agent_scores`` table and displaying per-agent trends based on
        their current cumulative performance.

        For a true time-series trajectory, this also queries hypothesis_log
        to show outcome trends over recent attempts.

        Args:
            project_id: Optional project filter. If provided, limits to
                        tasks/hypotheses within that project.

        Returns:
            Formatted string with quality trajectory data.
        """
        # Current agent quality standings
        agent_rows = await self.repository.engine.fetch_all(
            """SELECT agent_id,
                      SUM(total_attempts) as total_attempts,
                      SUM(successes) as total_successes,
                      SUM(failures) as total_failures,
                      AVG(avg_quality_score) as overall_quality,
                      AVG(avg_duration_seconds) as overall_duration,
                      MAX(last_used_at) as latest_activity
               FROM agent_scores
               GROUP BY agent_id
               ORDER BY overall_quality DESC""",
        )

        # Recent hypothesis outcomes (last 50) for trend analysis
        if project_id:
            hypothesis_rows = await self.repository.engine.fetch_all(
                """SELECT h.outcome, h.agent_id, h.created_at
                   FROM hypothesis_log h
                   JOIN tasks t ON h.task_id = t.id
                   WHERE t.project_id = ?
                   ORDER BY h.created_at DESC
                   LIMIT 50""",
                [project_id],
            )
        else:
            hypothesis_rows = await self.repository.engine.fetch_all(
                """SELECT outcome, agent_id, created_at
                   FROM hypothesis_log
                   ORDER BY created_at DESC
                   LIMIT 50""",
            )

        if not agent_rows and not hypothesis_rows:
            return self._wrap_panel("No quality data available yet.", "Quality Trajectory")

        if HAS_RICH:
            output_parts = []

            if agent_rows:
                quality_table = Table(title="Agent Quality Standings", show_lines=True)
                quality_table.add_column("Agent", style="cyan")
                quality_table.add_column("Total Attempts", justify="right")
                quality_table.add_column("Success Rate", justify="right", style="bold")
                quality_table.add_column("Avg Quality", justify="right")
                quality_table.add_column("Avg Duration (s)", justify="right")
                quality_table.add_column("Latest Activity")

                for row in agent_rows:
                    total = row.get("total_attempts", 0) or 0
                    successes = row.get("total_successes", 0) or 0
                    success_rate = f"{(successes / total * 100):.1f}%" if total > 0 else "N/A"
                    quality = row.get("overall_quality", 0.0) or 0.0
                    duration = row.get("overall_duration", 0.0) or 0.0
                    latest = row.get("latest_activity") or "Never"
                    if latest != "Never":
                        latest = latest[:10]

                    quality_table.add_row(
                        str(row.get("agent_id", "?")),
                        str(total),
                        success_rate,
                        f"{quality:.2f}",
                        f"{duration:.1f}",
                        latest,
                    )

                self._console.print(quality_table)
                output_parts.append(self._console.export_text())
                self._console._record_buffer.clear()

            if hypothesis_rows:
                # Compute rolling success rate over recent hypotheses
                # Split into chunks of 10 to show trend
                chunk_size = 10
                trend_lines = []
                reversed_rows = list(reversed(hypothesis_rows))  # Oldest first

                for i in range(0, len(reversed_rows), chunk_size):
                    chunk = reversed_rows[i : i + chunk_size]
                    successes_in_chunk = sum(
                        1 for r in chunk if r.get("outcome") == "SUCCESS"
                    )
                    chunk_rate = successes_in_chunk / len(chunk) if chunk else 0.0
                    first_date = chunk[0].get("created_at", "?")
                    if isinstance(first_date, str) and len(first_date) >= 10:
                        first_date = first_date[:10]
                    trend_lines.append((first_date, len(chunk), chunk_rate))

                if trend_lines:
                    trend_table = Table(title="Recent Success Trend (batches of 10)", show_lines=True)
                    trend_table.add_column("Period Start", style="green")
                    trend_table.add_column("Attempts", justify="right")
                    trend_table.add_column("Success Rate", justify="right", style="bold")
                    trend_table.add_column("Trend", style="yellow")

                    prev_rate: Optional[float] = None
                    for date, count, rate in trend_lines:
                        if prev_rate is not None:
                            if rate > prev_rate:
                                trend_indicator = "UP"
                            elif rate < prev_rate:
                                trend_indicator = "DOWN"
                            else:
                                trend_indicator = "FLAT"
                        else:
                            trend_indicator = "--"

                        trend_table.add_row(
                            str(date),
                            str(count),
                            f"{rate * 100:.1f}%",
                            trend_indicator,
                        )
                        prev_rate = rate

                    self._console.print(trend_table)
                    output_parts.append(self._console.export_text())
                    self._console._record_buffer.clear()

            return "\n".join(output_parts)

        else:
            # Plain text fallback
            lines = ["=== Quality Trajectory ===", ""]

            if agent_rows:
                lines.append("Agent Quality Standings:")
                header = (
                    f"  {'Agent':<12} {'Attempts':>8} {'Success':>8} "
                    f"{'Quality':>8} {'Duration':>10} {'Latest':>12}"
                )
                lines.append(header)
                lines.append("  " + "-" * (len(header) - 2))

                for row in agent_rows:
                    total = row.get("total_attempts", 0) or 0
                    successes = row.get("total_successes", 0) or 0
                    success_rate = f"{(successes / total * 100):.1f}%" if total > 0 else "N/A"
                    quality = row.get("overall_quality", 0.0) or 0.0
                    duration = row.get("overall_duration", 0.0) or 0.0
                    latest = (row.get("latest_activity") or "Never")[:10]

                    lines.append(
                        f"  {str(row.get('agent_id', '?')):<12} "
                        f"{total:>8} {success_rate:>8} "
                        f"{quality:>8.2f} {duration:>10.1f}s {latest:>12}"
                    )

            if hypothesis_rows:
                lines.append("")
                lines.append("Recent Success Trend (batches of 10):")
                reversed_rows = list(reversed(hypothesis_rows))
                chunk_size = 10
                prev_rate_val: Optional[float] = None

                for i in range(0, len(reversed_rows), chunk_size):
                    chunk = reversed_rows[i : i + chunk_size]
                    successes_in_chunk = sum(
                        1 for r in chunk if r.get("outcome") == "SUCCESS"
                    )
                    chunk_rate = successes_in_chunk / len(chunk) if chunk else 0.0
                    first_date = chunk[0].get("created_at", "?")
                    if isinstance(first_date, str) and len(first_date) >= 10:
                        first_date = first_date[:10]

                    if prev_rate_val is not None:
                        if chunk_rate > prev_rate_val:
                            trend = "UP"
                        elif chunk_rate < prev_rate_val:
                            trend = "DOWN"
                        else:
                            trend = "FLAT"
                    else:
                        trend = "--"

                    lines.append(
                        f"  {first_date}: {len(chunk)} attempts, "
                        f"{chunk_rate * 100:.1f}% success [{trend}]"
                    )
                    prev_rate_val = chunk_rate

            return "\n".join(lines)

    # -------------------------------------------------------------------
    # Full Dashboard
    # -------------------------------------------------------------------

    async def render_full_dashboard(self, project_id: Optional[str] = None) -> str:
        """Compose all dashboard panels into a single output.

        Renders agent scores, fleet status, cost summary, pattern summary,
        and quality trajectory into one comprehensive view.

        Args:
            project_id: Optional project filter passed to panels that support it.

        Returns:
            Formatted string containing the full dashboard.
        """
        sections: list[str] = []

        # Header
        if HAS_RICH:
            header = "CLAW Dashboard"
            self._console.print(Panel(header, style="bold blue"))
            sections.append(self._console.export_text())
            self._console._record_buffer.clear()
        else:
            sections.append("=" * 60)
            sections.append("  CLAW Dashboard")
            sections.append("=" * 60)

        # Render each panel, catching errors to prevent one panel from
        # breaking the entire dashboard
        panel_renderers = [
            ("Agent Scores", self.render_agent_scores),
            ("Fleet Status", self.render_fleet_status),
            ("Cost Summary", self.render_cost_summary),
            ("Pattern Summary", lambda: self.render_pattern_summary(project_id)),
            ("Quality Trajectory", lambda: self.render_quality_trajectory(project_id)),
        ]

        for panel_name, renderer in panel_renderers:
            try:
                output = await renderer()
                sections.append("")
                sections.append(output)
            except Exception as exc:
                logger.error("Failed to render %s panel: %s", panel_name, exc)
                sections.append("")
                sections.append(
                    self._wrap_panel(
                        f"Error rendering {panel_name}: {exc}",
                        panel_name,
                    )
                )

        return "\n".join(sections)

    # -------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------

    def _wrap_panel(self, content: str, title: str) -> str:
        """Wrap content in a Rich Panel or plain text box.

        Args:
            content: The text content to wrap.
            title: The panel/box title.

        Returns:
            Formatted string with the content wrapped.
        """
        if HAS_RICH:
            self._console.print(Panel(content, title=title))
            output = self._console.export_text()
            self._console._record_buffer.clear()
            return output
        else:
            border = "-" * 40
            return f"--- {title} ---\n{content}\n{border}"

    def _render_rich_table(self, table: "Table") -> str:
        """Render a Rich Table to string.

        Args:
            table: A Rich Table instance to render.

        Returns:
            The rendered table as a plain string (with ANSI codes stripped
            since the Console is in record mode).
        """
        self._console.print(table)
        output = self._console.export_text()
        self._console._record_buffer.clear()
        return output
