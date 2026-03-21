"""TUI Dashboard for CAM-PULSE.

Displays pulse activity, discoveries, scan history, and statistics
using the rich library.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any, Optional

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from claw.db.engine import DatabaseEngine

logger = logging.getLogger("claw.pulse.dashboard")


class PulseDashboard:
    """Interactive TUI showing pulse activity."""

    def __init__(self, engine: DatabaseEngine):
        self.engine = engine
        self.console = Console()

    async def show_novel(self, limit: int = 20) -> None:
        """Display recent novel discoveries with scores."""
        rows = await self.engine.fetch_all(
            """SELECT canonical_url, github_url, novelty_score, status,
                      keywords_matched, x_author_handle, discovered_at
               FROM pulse_discoveries
               ORDER BY discovered_at DESC
               LIMIT ?""",
            [limit],
        )

        if not rows:
            self.console.print("[dim]No discoveries yet. Run 'cam pulse scan' first.[/dim]")
            return

        table = Table(
            title="PULSE Discoveries",
            show_lines=False,
            header_style="bold cyan",
        )
        table.add_column("URL", style="blue", max_width=45)
        table.add_column("Novelty", justify="right", style="green")
        table.add_column("Status", style="yellow")
        table.add_column("Keywords", max_width=25)
        table.add_column("Author", style="dim")
        table.add_column("Discovered", style="dim")

        for row in rows:
            score = row.get("novelty_score")
            score_str = f"{score:.2f}" if score is not None else "-"
            keywords = _parse_json_list(row.get("keywords_matched", "[]"))
            kw_str = ", ".join(keywords[:3])
            if len(keywords) > 3:
                kw_str += f" +{len(keywords) - 3}"

            discovered = row.get("discovered_at", "")
            if discovered:
                discovered = discovered[:16]  # Trim to YYYY-MM-DDTHH:MM

            table.add_row(
                _truncate(row.get("canonical_url", ""), 45),
                score_str,
                row.get("status", "?"),
                kw_str,
                row.get("x_author_handle", "") or "",
                discovered,
            )

        self.console.print(table)

    async def show_scans(self, limit: int = 10) -> None:
        """Display recent scan sessions."""
        rows = await self.engine.fetch_all(
            """SELECT id, scan_type, keywords, started_at, completed_at,
                      repos_discovered, repos_novel, repos_assimilated,
                      cost_usd, tokens_used, error_detail
               FROM pulse_scan_log
               ORDER BY started_at DESC
               LIMIT ?""",
            [limit],
        )

        if not rows:
            self.console.print("[dim]No scans recorded yet.[/dim]")
            return

        table = Table(
            title="PULSE Scan History",
            show_lines=False,
            header_style="bold cyan",
        )
        table.add_column("Scan ID", style="dim", max_width=10)
        table.add_column("Started", style="dim")
        table.add_column("Discovered", justify="right")
        table.add_column("Novel", justify="right", style="green")
        table.add_column("Assimilated", justify="right", style="blue")
        table.add_column("Cost", justify="right")
        table.add_column("Tokens", justify="right")
        table.add_column("Errors", style="red")

        for row in rows:
            started = row.get("started_at", "")
            if started:
                started = started[:16]

            cost = row.get("cost_usd", 0.0) or 0.0
            tokens = row.get("tokens_used", 0) or 0
            errors = row.get("error_detail")
            error_str = ""
            if errors:
                try:
                    err_list = json.loads(errors)
                    error_str = str(len(err_list)) if isinstance(err_list, list) else "1"
                except (json.JSONDecodeError, TypeError):
                    error_str = "1"

            table.add_row(
                _truncate(row.get("id", ""), 10),
                started,
                str(row.get("repos_discovered", 0)),
                str(row.get("repos_novel", 0)),
                str(row.get("repos_assimilated", 0)),
                f"${cost:.3f}",
                str(tokens),
                error_str,
            )

        self.console.print(table)

    async def show_stats(self) -> None:
        """Aggregate pulse statistics."""
        # Total counts by status
        status_rows = await self.engine.fetch_all(
            "SELECT status, COUNT(*) as cnt FROM pulse_discoveries GROUP BY status"
        )
        status_counts = {r["status"]: r["cnt"] for r in status_rows}
        total = sum(status_counts.values())

        # Scan stats
        scan_row = await self.engine.fetch_one(
            """SELECT COUNT(*) as total_scans,
                      COALESCE(SUM(repos_discovered), 0) as total_discovered,
                      COALESCE(SUM(repos_novel), 0) as total_novel,
                      COALESCE(SUM(repos_assimilated), 0) as total_assimilated,
                      COALESCE(SUM(cost_usd), 0.0) as total_cost,
                      COALESCE(SUM(tokens_used), 0) as total_tokens
               FROM pulse_scan_log"""
        )

        # Today's stats
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        today_row = await self.engine.fetch_one(
            """SELECT COUNT(*) as scans_today,
                      COALESCE(SUM(repos_discovered), 0) as discovered_today,
                      COALESCE(SUM(repos_novel), 0) as novel_today,
                      COALESCE(SUM(cost_usd), 0.0) as cost_today
               FROM pulse_scan_log
               WHERE started_at >= ?""",
            [today],
        )

        # Top keywords
        kw_rows = await self.engine.fetch_all(
            "SELECT keywords_matched FROM pulse_discoveries"
        )
        kw_freq: dict[str, int] = {}
        for r in kw_rows:
            for kw in _parse_json_list(r.get("keywords_matched", "[]")):
                kw_freq[kw] = kw_freq.get(kw, 0) + 1
        top_kw = sorted(kw_freq.items(), key=lambda x: -x[1])[:5]

        # Build display
        stats_table = Table(
            title="PULSE Statistics",
            show_header=False,
            show_lines=False,
            padding=(0, 2),
        )
        stats_table.add_column("Key", style="bold")
        stats_table.add_column("Value", style="green")

        stats_table.add_row("Total discoveries", str(total))
        for status, cnt in sorted(status_counts.items()):
            stats_table.add_row(f"  {status}", str(cnt))

        if scan_row:
            stats_table.add_row("", "")
            stats_table.add_row("Total scans", str(scan_row.get("total_scans", 0)))
            cost = scan_row.get("total_cost", 0.0) or 0.0
            stats_table.add_row("Total cost", f"${cost:.4f}")
            stats_table.add_row("Total tokens", str(scan_row.get("total_tokens", 0)))

        if today_row:
            stats_table.add_row("", "")
            stats_table.add_row("Today's scans", str(today_row.get("scans_today", 0)))
            stats_table.add_row("Today's discoveries", str(today_row.get("discovered_today", 0)))
            today_cost = today_row.get("cost_today", 0.0) or 0.0
            stats_table.add_row("Today's cost", f"${today_cost:.4f}")

        if top_kw:
            stats_table.add_row("", "")
            stats_table.add_row("Top keywords", "")
            for kw, count in top_kw:
                stats_table.add_row(f"  {kw}", str(count))

        self.console.print(stats_table)

    async def show_daily_report(self, date: Optional[str] = None) -> None:
        """Generate daily report summary."""
        if not date:
            date = datetime.now(UTC).strftime("%Y-%m-%d")

        next_date = date[:8] + str(int(date[8:]) + 1).zfill(2)

        # Discoveries for this date
        disc_rows = await self.engine.fetch_all(
            """SELECT canonical_url, novelty_score, status, keywords_matched
               FROM pulse_discoveries
               WHERE discovered_at >= ? AND discovered_at < ?
               ORDER BY novelty_score DESC""",
            [date, next_date],
        )

        # Scans for this date
        scan_rows = await self.engine.fetch_all(
            """SELECT id, repos_discovered, repos_novel, repos_assimilated, cost_usd
               FROM pulse_scan_log
               WHERE started_at >= ? AND started_at < ?""",
            [date, next_date],
        )

        total_discovered = sum(r.get("repos_discovered", 0) for r in scan_rows)
        total_novel = sum(r.get("repos_novel", 0) for r in scan_rows)
        total_assimilated = sum(r.get("repos_assimilated", 0) for r in scan_rows)
        total_cost = sum(r.get("cost_usd", 0.0) or 0.0 for r in scan_rows)

        lines = [
            f"[bold]PULSE Daily Report: {date}[/bold]",
            f"Scans: {len(scan_rows)}",
            f"Discovered: {total_discovered} repos, {total_novel} novel, {total_assimilated} assimilated",
            f"Cost: ${total_cost:.4f}",
        ]

        if disc_rows:
            lines.append("")
            lines.append("[bold]Top discoveries:[/bold]")
            for row in disc_rows[:10]:
                score = row.get("novelty_score")
                score_str = f"{score:.2f}" if score is not None else "?"
                lines.append(
                    f"  [{score_str}] {row.get('canonical_url', '?')} ({row.get('status', '?')})"
                )

        panel = Panel(
            "\n".join(lines),
            title=f"PULSE Report {date}",
            border_style="cyan",
        )
        self.console.print(panel)


def _parse_json_list(value: Any) -> list[str]:
    """Safely parse a JSON list string."""
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, TypeError):
            pass
    return []


def _truncate(s: str, max_len: int) -> str:
    """Truncate string with ellipsis."""
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."
