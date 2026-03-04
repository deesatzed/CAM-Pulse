"""CLAW CLI — Typer-based command line interface.

Commands:
  evaluate <repo>   — structural analysis and store results
  enhance <repo>    — full pipeline: evaluate → plan → dispatch → verify → learn
  add-goal <repo>   — manually add a task/goal for a repository
  results           — show past task results from the database
  status            — show system status
  setup             — interactive API key, model, and agent configuration
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from typing import Optional

import time as _time

import typer
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.text import Text

app = typer.Typer(
    name="claw",
    help="CLAW — Codebase Learning & Autonomous Workforce",
    no_args_is_help=True,
)
console = Console()


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


@app.command()
def evaluate(
    repo: str = typer.Argument(..., help="Path to the repository to evaluate"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Evaluate a repository for enhancement potential.

    Runs analysis on the target repo, storing results in SQLite.
    """
    _setup_logging(verbose)

    repo_path = Path(repo).resolve()
    if not repo_path.exists():
        console.print(f"[red]Repository path does not exist: {repo_path}[/red]")
        raise typer.Exit(1)

    asyncio.run(_evaluate_async(repo_path, config))


async def _evaluate_async(repo_path: Path, config_path: Optional[str]) -> None:
    from claw.core.factory import ClawFactory
    from claw.core.models import Project, Task

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p, workspace_dir=repo_path)

    try:
        # Create or get project
        project = Project(
            name=repo_path.name,
            repo_path=str(repo_path),
        )
        await ctx.repository.create_project(project)

        console.print(f"\n[bold]CLAW Evaluation: {repo_path.name}[/bold]")
        console.print(f"  Repository: {repo_path}")
        console.print(f"  Project ID: {project.id}")
        console.print(f"  Database: {ctx.config.database.db_path}")

        # Phase 1: Basic structural analysis
        analysis = await _analyze_repo(repo_path)

        # Create evaluation task
        eval_task = Task(
            project_id=project.id,
            title=f"Evaluate {repo_path.name}",
            description=f"Structural analysis of {repo_path.name}",
            task_type="analysis",
            priority=10,
        )
        await ctx.repository.create_task(eval_task)

        # Log episode
        await ctx.repository.log_episode(
            session_id="cli-evaluate",
            event_type="evaluation_started",
            event_data={"repo_path": str(repo_path), "analysis": analysis},
            project_id=project.id,
        )

        # Display results
        _display_analysis(analysis, repo_path.name)

        # Store results
        await ctx.repository.log_episode(
            session_id="cli-evaluate",
            event_type="evaluation_completed",
            event_data=analysis,
            project_id=project.id,
        )

        console.print(f"\n[green]Evaluation stored in {ctx.config.database.db_path}[/green]")

    finally:
        await ctx.close()


async def _analyze_repo(repo_path: Path) -> dict:
    """Perform basic structural analysis of a repository."""
    analysis = {
        "has_git": (repo_path / ".git").exists(),
        "has_readme": any(
            (repo_path / f).exists() for f in ["README.md", "readme.md", "README"]
        ),
        "has_tests": any(
            (repo_path / d).exists() for d in ["tests", "test", "spec", "__tests__"]
        ),
        "file_counts": {},
        "total_files": 0,
        "languages_detected": [],
    }

    # Count files by extension
    ext_counts: dict[str, int] = {}
    total = 0
    for f in repo_path.rglob("*"):
        if f.is_file() and ".git" not in f.parts:
            total += 1
            ext = f.suffix.lower() or "(no ext)"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

    analysis["file_counts"] = dict(sorted(ext_counts.items(), key=lambda x: -x[1])[:20])
    analysis["total_files"] = total

    # Detect languages from extensions
    lang_map = {
        ".py": "Python", ".js": "JavaScript", ".ts": "TypeScript",
        ".rs": "Rust", ".go": "Go", ".java": "Java", ".rb": "Ruby",
        ".cpp": "C++", ".c": "C", ".cs": "C#", ".swift": "Swift",
        ".kt": "Kotlin", ".scala": "Scala", ".php": "PHP",
    }
    langs = []
    for ext, lang in lang_map.items():
        if ext in ext_counts:
            langs.append(lang)
    analysis["languages_detected"] = langs

    # Check for config files
    config_files = [
        "pyproject.toml", "package.json", "Cargo.toml", "go.mod",
        "pom.xml", "build.gradle", "Gemfile", "Makefile",
        "docker-compose.yml", "Dockerfile",
    ]
    analysis["config_files"] = [f for f in config_files if (repo_path / f).exists()]

    return analysis


def _display_analysis(analysis: dict, name: str) -> None:
    """Display analysis results using Rich."""
    console.print()

    # Summary table
    table = Table(title=f"Repository Analysis: {name}")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Total Files", str(analysis["total_files"]))
    table.add_row("Git Repository", "Yes" if analysis["has_git"] else "No")
    table.add_row("Has README", "Yes" if analysis["has_readme"] else "No")
    table.add_row("Has Tests", "Yes" if analysis["has_tests"] else "No")
    table.add_row("Languages", ", ".join(analysis["languages_detected"]) or "None detected")
    table.add_row("Config Files", ", ".join(analysis["config_files"]) or "None")

    console.print(table)

    # File breakdown
    if analysis["file_counts"]:
        ft = Table(title="File Type Breakdown (Top 10)")
        ft.add_column("Extension", style="cyan")
        ft.add_column("Count", style="yellow", justify="right")

        for ext, count in list(analysis["file_counts"].items())[:10]:
            ft.add_row(ext, str(count))

        console.print(ft)


@app.command()
def enhance(
    repo: str = typer.Argument(..., help="Path to the repository to enhance"),
    mode: str = typer.Option("attended", "--mode", "-m", help="Mode: attended, supervised, autonomous"),
    max_tasks: int = typer.Option(10, "--max-tasks", help="Maximum number of tasks to process"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable debug logging"),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Enhance a repository: evaluate, plan, dispatch, verify, learn.

    Runs the full MesoClaw pipeline on the target repo.
    """
    _setup_logging(verbose)

    repo_path = Path(repo).resolve()
    if not repo_path.exists():
        console.print(f"[red]Repository path does not exist: {repo_path}[/red]")
        raise typer.Exit(1)

    if mode not in ("attended", "supervised", "autonomous"):
        console.print(f"[red]Invalid mode: {mode}. Use attended, supervised, or autonomous.[/red]")
        raise typer.Exit(1)

    asyncio.run(_enhance_async(repo_path, config, mode, max_tasks))


async def _enhance_async(
    repo_path: Path,
    config_path: Optional[str],
    mode: str,
    max_tasks: int,
) -> None:
    from claw.core.factory import ClawFactory
    from claw.core.models import Project
    from claw.cycle import MicroClaw
    from claw.planner import EvaluationResult, Planner

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p, workspace_dir=repo_path)

    try:
        # Create or get project
        project = Project(
            name=repo_path.name,
            repo_path=str(repo_path),
        )
        await ctx.repository.create_project(project)

        console.print(f"\n[bold]CLAW Enhancement: {repo_path.name}[/bold]")
        console.print(f"  Repository: {repo_path}")
        console.print(f"  Mode: {mode}")
        console.print(f"  Agents: {', '.join(ctx.agents.keys()) or 'none'}")

        if not ctx.agents:
            console.print("[red]No agents available. Enable at least one agent in claw.toml.[/red]")
            return

        # Phase 1: Evaluate
        console.print("\n[cyan]Phase 1: Evaluating repository...[/cyan]")
        analysis = await _analyze_repo(repo_path)
        _display_analysis(analysis, repo_path.name)

        # Phase 2: Plan — convert analysis into tasks
        console.print("\n[cyan]Phase 2: Planning enhancements...[/cyan]")
        planner = Planner(project_id=project.id, repository=ctx.repository)

        eval_results = _analysis_to_eval_results(analysis, repo_path.name)
        tasks = await planner.analyze_gaps(eval_results)

        if not tasks:
            console.print("[green]No enhancement tasks identified. Repository looks good![/green]")
            return

        tasks = tasks[:max_tasks]
        console.print(f"  Generated {len(tasks)} enhancement tasks")

        # Store tasks in DB
        for task in tasks:
            await ctx.repository.create_task(task)

        # Phase 3: Execute — run MicroClaw cycles
        console.print(f"\n[cyan]Phase 3: Executing {len(tasks)} tasks...[/cyan]")
        micro = MicroClaw(ctx=ctx, project_id=project.id)

        completed = 0
        failed = 0
        for i in range(len(tasks)):
            task_label = tasks[i].title[:60] if i < len(tasks) else "task"
            console.print(f"\n  [bold]Task {i + 1}/{len(tasks)}:[/bold] {task_label}")

            # Progress state shared with the callback
            progress_state = {"step": "starting", "detail": "", "start": _time.monotonic()}

            def on_step(step: str, detail: str) -> None:
                progress_state["step"] = step
                progress_state["detail"] = detail

            async def run_with_progress():
                """Run the cycle while updating a live spinner."""
                cycle_task = asyncio.create_task(micro.run_cycle(on_step=on_step))
                step_icons = {
                    "grab": "[cyan]grab[/cyan]",
                    "evaluate": "[cyan]evaluate[/cyan]",
                    "decide": "[yellow]decide[/yellow]",
                    "act": "[bold green]act[/bold green]",
                    "verify": "[magenta]verify[/magenta]",
                    "learn": "[blue]learn[/blue]",
                    "done": "[green]done[/green]",
                }
                with Live(console=console, refresh_per_second=2, transient=True) as live:
                    while not cycle_task.done():
                        elapsed = _time.monotonic() - progress_state["start"]
                        step = progress_state["step"]
                        icon = step_icons.get(step, step)
                        detail = progress_state["detail"]
                        mins = int(elapsed // 60)
                        secs = int(elapsed % 60)
                        time_str = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
                        live.update(
                            Text.from_markup(
                                f"    [{time_str}] {icon}  {detail}"
                            )
                        )
                        await asyncio.sleep(0.5)
                return cycle_task.result()

            cycle_result = await run_with_progress()

            if cycle_result.success:
                completed += 1
                duration = cycle_result.duration_seconds or 0
                console.print(f"    [green]completed[/green] ({duration:.1f}s)")
            else:
                failed += 1
                console.print(f"    [yellow]failed[/yellow]")

            # Show what the agent did
            _display_task_result(cycle_result)

            if mode == "attended":
                response = console.input("  Continue? [y/n] ")
                if response.lower() != "y":
                    console.print("  [yellow]Paused by user.[/yellow]")
                    break

        # Summary
        console.print(f"\n[bold]Enhancement Summary[/bold]")
        console.print(f"  Completed: {completed}")
        console.print(f"  Failed: {failed}")
        console.print(f"  Results stored in {ctx.config.database.db_path}")

    finally:
        await ctx.close()


def _analysis_to_eval_results(analysis: dict, name: str) -> list:
    """Convert structural analysis into EvaluationResult objects for the Planner."""
    from claw.planner import EvaluationResult

    results = []

    if not analysis.get("has_tests"):
        results.append(EvaluationResult(
            prompt_name="structural_analysis",
            findings=[f"{name} has no test directory — add test infrastructure"],
            severity="high",
            category="testing",
        ))

    if not analysis.get("has_readme"):
        results.append(EvaluationResult(
            prompt_name="structural_analysis",
            findings=[f"{name} is missing a README — add documentation"],
            severity="medium",
            category="docs",
        ))

    if not analysis.get("has_git"):
        results.append(EvaluationResult(
            prompt_name="structural_analysis",
            findings=[f"{name} is not a git repository — initialize git"],
            severity="low",
            category="architecture",
        ))

    if not analysis.get("config_files"):
        results.append(EvaluationResult(
            prompt_name="structural_analysis",
            findings=[f"{name} has no build/config files — add project manifest"],
            severity="medium",
            category="architecture",
        ))

    # If the analysis looks healthy, add a general enhancement task
    if not results:
        results.append(EvaluationResult(
            prompt_name="structural_analysis",
            findings=[f"General code quality review for {name}"],
            severity="low",
            category="analysis",
        ))

    return results


def _display_task_result(cycle_result) -> None:
    """Display the outcome of a single task cycle."""
    from claw.core.models import CycleResult

    if not isinstance(cycle_result, CycleResult):
        return

    outcome = cycle_result.outcome
    verification = cycle_result.verification

    # Agent and cost
    agent = cycle_result.agent_id or "unknown"
    cost = cycle_result.cost_usd
    tokens = cycle_result.tokens_used

    info_parts = [f"Agent: {agent}"]
    if cost > 0:
        info_parts.append(f"Cost: ${cost:.4f}")
    if tokens > 0:
        info_parts.append(f"Tokens: {tokens:,}")
    console.print(f"    {' | '.join(info_parts)}")

    # Approach summary (truncated for display)
    if outcome and outcome.approach_summary:
        summary = outcome.approach_summary
        if len(summary) > 200:
            summary = summary[:200] + "..."
        console.print(f"    [dim]Summary:[/dim] {summary}")

    # Files changed
    if outcome and outcome.files_changed:
        files_str = ", ".join(outcome.files_changed[:5])
        extra = f" (+{len(outcome.files_changed) - 5} more)" if len(outcome.files_changed) > 5 else ""
        console.print(f"    [dim]Files:[/dim] {files_str}{extra}")

    # Verification
    if verification:
        if verification.approved:
            console.print(f"    [green]Verified[/green] (quality: {verification.quality_score or 0:.2f})")
        else:
            v_count = len(verification.violations)
            console.print(f"    [red]Rejected[/red] ({v_count} violation{'s' if v_count != 1 else ''})")
            for v in verification.violations[:3]:
                check = v.get("check", "")
                detail = v.get("detail", "")
                console.print(f"      - {check}: {detail}")

    # Failure reason
    if outcome and outcome.failure_reason and not cycle_result.success:
        console.print(f"    [yellow]Failure:[/yellow] {outcome.failure_reason}")
        if outcome.failure_detail:
            detail = outcome.failure_detail[:150]
            console.print(f"    [dim]{detail}[/dim]")


@app.command()
def results(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
    limit: int = typer.Option(20, "--limit", "-n", help="Number of results to show"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Filter by project ID"),
) -> None:
    """Show past task results from the database."""
    _setup_logging(False)
    asyncio.run(_results_async(config, limit, project))


async def _results_async(config_path: Optional[str], limit: int, project_id: Optional[str]) -> None:
    from claw.core.factory import ClawFactory

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p)

    try:
        rows = await ctx.repository.get_project_results(project_id=project_id, limit=limit)

        if not rows:
            console.print("\n[yellow]No task results found.[/yellow]")
            return

        console.print(f"\n[bold]CLAW Task Results[/bold] ({len(rows)} shown)\n")

        table = Table(show_lines=True)
        table.add_column("#", style="dim", width=3)
        table.add_column("Task", style="cyan", max_width=40)
        table.add_column("Status", width=10)
        table.add_column("Agent", style="yellow", width=8)
        table.add_column("Outcome", width=9)
        table.add_column("Duration", justify="right", width=8)
        table.add_column("Summary", max_width=50)

        for i, row in enumerate(rows, 1):
            title = (row.get("title") or "")[:40]
            status_val = row.get("status", "")
            agent = row.get("agent_id") or row.get("assigned_agent") or "-"
            hypothesis_outcome = row.get("hypothesis_outcome") or "-"
            duration = row.get("duration_seconds")
            summary = (row.get("approach_summary") or "")[:50]

            # Color status
            if status_val == "DONE":
                status_display = "[green]DONE[/green]"
            elif status_val == "PENDING":
                status_display = "[yellow]PENDING[/yellow]"
            elif status_val in ("CODING", "REVIEWING", "DISPATCHED"):
                status_display = f"[cyan]{status_val}[/cyan]"
            else:
                status_display = status_val

            # Color outcome
            if hypothesis_outcome == "SUCCESS":
                outcome_display = "[green]SUCCESS[/green]"
            elif hypothesis_outcome == "FAILURE":
                outcome_display = "[red]FAILURE[/red]"
            else:
                outcome_display = hypothesis_outcome

            # Format duration
            if duration:
                mins = int(duration // 60)
                secs = int(duration % 60)
                dur_str = f"{mins}m {secs:02d}s" if mins else f"{secs}s"
            else:
                dur_str = "-"

            table.add_row(
                str(i), title, status_display, agent,
                outcome_display, dur_str, summary,
            )

        console.print(table)

        # Quick summary stats
        total = len(rows)
        successes = sum(1 for r in rows if r.get("hypothesis_outcome") == "SUCCESS")
        failures = sum(1 for r in rows if r.get("hypothesis_outcome") == "FAILURE")
        pending = sum(1 for r in rows if r.get("status") == "PENDING")
        console.print(f"\n  Total: {total} | Success: {successes} | Failed: {failures} | Pending: {pending}")

    finally:
        await ctx.close()


@app.command()
def status(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Show CLAW system status."""
    _setup_logging(False)
    asyncio.run(_status_async(config))


async def _status_async(config_path: Optional[str]) -> None:
    from claw.core.factory import ClawFactory

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p)

    try:
        console.print("\n[bold]CLAW System Status[/bold]")
        console.print(f"  Database: {ctx.config.database.db_path}")
        console.print(f"  Agents: {', '.join(ctx.agents.keys()) or 'none'}")

        # Check agent health
        for name, agent in ctx.agents.items():
            health = await agent.health_check()
            status_str = "[green]available[/green]" if health.available else f"[red]unavailable: {health.error}[/red]"
            console.print(f"  {name}: {status_str}")

        # Task summary
        summary = await ctx.repository.get_task_status_summary()
        if summary:
            console.print("\n  Task Summary:")
            for status, count in summary.items():
                console.print(f"    {status}: {count}")
        else:
            console.print("  No tasks yet.")

    finally:
        await ctx.close()


@app.command(name="add-goal")
def add_goal(
    repo: str = typer.Argument(..., help="Path to the repository this goal is for"),
    title: str = typer.Option(..., "--title", "-t", prompt="Goal title", help="Short title for the goal"),
    description: str = typer.Option(
        ..., "--description", "-d", prompt="Goal description (what should the agent do?)",
        help="Detailed description of what should be accomplished",
    ),
    priority: str = typer.Option(
        "medium", "--priority", "-p",
        help="Priority: critical, high, medium, low",
    ),
    task_type: str = typer.Option(
        "analysis", "--type",
        help="Task type: analysis, testing, documentation, security, refactoring, bug_fix, architecture, dependency_analysis",
    ),
    agent: Optional[str] = typer.Option(
        None, "--agent", "-a",
        help="Preferred agent: claude, codex, gemini, grok (or leave blank for auto-routing)",
    ),
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Add a custom goal/task for a repository.

    Creates a task that will be picked up by `claw enhance` on the next run.
    """
    _setup_logging(False)

    repo_path = Path(repo).resolve()
    if not repo_path.exists():
        console.print(f"[red]Repository path does not exist: {repo_path}[/red]")
        raise typer.Exit(1)

    valid_priorities = {"critical": 10, "high": 8, "medium": 5, "low": 2}
    if priority.lower() not in valid_priorities:
        console.print(f"[red]Invalid priority '{priority}'. Use: critical, high, medium, low[/red]")
        raise typer.Exit(1)

    valid_types = [
        "analysis", "testing", "documentation", "security", "refactoring",
        "bug_fix", "architecture", "dependency_analysis",
    ]
    if task_type not in valid_types:
        console.print(f"[red]Invalid task type '{task_type}'. Use: {', '.join(valid_types)}[/red]")
        raise typer.Exit(1)

    if agent and agent not in ("claude", "codex", "gemini", "grok"):
        console.print(f"[red]Invalid agent '{agent}'. Use: claude, codex, gemini, grok[/red]")
        raise typer.Exit(1)

    asyncio.run(_add_goal_async(
        repo_path, title, description, priority.lower(), task_type, agent, config,
    ))


async def _add_goal_async(
    repo_path: Path,
    title: str,
    description: str,
    priority: str,
    task_type: str,
    agent: Optional[str],
    config_path: Optional[str],
) -> None:
    from claw.core.factory import ClawFactory
    from claw.core.models import Project, Task, TaskStatus
    from claw.dispatcher import DEFAULT_AGENT, STATIC_ROUTING

    config_p = Path(config_path) if config_path else None
    ctx = await ClawFactory.create(config_path=config_p, workspace_dir=repo_path)

    priority_map = {"critical": 10, "high": 8, "medium": 5, "low": 2}

    try:
        # Find or create project for this repo
        project = await ctx.repository.get_project_by_name(repo_path.name)
        if project is None:
            project = Project(name=repo_path.name, repo_path=str(repo_path))
            await ctx.repository.create_project(project)
            console.print(f"  Created new project: {project.name} ({project.id})")

        # Determine recommended agent
        recommended = agent or STATIC_ROUTING.get(task_type, DEFAULT_AGENT)

        task = Task(
            project_id=project.id,
            title=title,
            description=description,
            status=TaskStatus.PENDING,
            priority=priority_map[priority],
            task_type=task_type,
            recommended_agent=recommended,
        )
        await ctx.repository.create_task(task)

        console.print(f"\n[green]Goal added successfully![/green]")
        console.print(f"  Title: {title}")
        console.print(f"  Project: {project.name}")
        console.print(f"  Priority: {priority} ({priority_map[priority]})")
        console.print(f"  Type: {task_type}")
        console.print(f"  Agent: {recommended}")
        console.print(f"  Task ID: {task.id}")
        console.print(f"\nRun [bold]claw enhance {repo_path}[/bold] to execute this goal.")

    finally:
        await ctx.close()


@app.command()
def setup(
    config: Optional[str] = typer.Option(None, "--config", "-c", help="Path to claw.toml"),
) -> None:
    """Interactive setup for API keys, models, and agent configuration.

    Walks you through configuring each agent with API keys and model preferences,
    then writes the updated configuration to claw.toml.
    """
    import toml as _toml

    config_path = Path(config) if config else Path(__file__).parent.parent.parent / "claw.toml"
    config_path = config_path.resolve()

    if not config_path.exists():
        console.print(f"[red]Config file not found: {config_path}[/red]")
        console.print("[dim]Run from the multiclaw directory or pass --config path/to/claw.toml[/dim]")
        raise typer.Exit(1)

    console.print(f"\n[bold]CLAW Setup[/bold]")
    console.print(f"  Config: {config_path}\n")

    # Load current config
    with open(config_path) as f:
        raw = _toml.load(f)

    agents_section = raw.setdefault("agents", {})
    changed = False

    # --- Agent configuration ---
    agent_info = {
        "claude": {
            "label": "Claude Code (Anthropic)",
            "key_env": "ANTHROPIC_API_KEY",
            "default_mode": "cli",
            "model_hint": "e.g. claude-sonnet-4-6, claude-opus-4-6",
        },
        "codex": {
            "label": "Codex (OpenAI)",
            "key_env": "OPENAI_API_KEY",
            "default_mode": "cli",
            "model_hint": "e.g. codex-mini-latest, o4-mini",
        },
        "gemini": {
            "label": "Gemini (Google)",
            "key_env": "GOOGLE_API_KEY",
            "default_mode": "api",
            "model_hint": "e.g. gemini-2.5-pro, gemini-2.5-flash",
        },
        "grok": {
            "label": "Grok (xAI)",
            "key_env": "XAI_API_KEY",
            "default_mode": "api",
            "model_hint": "e.g. grok-3, grok-3-mini",
        },
    }

    for agent_name, info in agent_info.items():
        console.print(f"[bold cyan]--- {info['label']} ---[/bold cyan]")

        current = agents_section.get(agent_name, {})
        current_enabled = current.get("enabled", False)
        current_model = current.get("model")
        current_budget = current.get("max_budget_usd", 1.0)

        # Check if API key is set in environment
        import os
        key_env = info["key_env"]
        key_present = bool(os.getenv(key_env, ""))
        key_status = "[green]set[/green]" if key_present else "[red]not set[/red]"
        console.print(f"  API key ({key_env}): {key_status}")

        if not key_present:
            console.print(f"  [dim]Set it with: export {key_env}=your-key-here[/dim]")

        # Enable/disable
        enable_str = console.input(
            f"  Enable {agent_name}? [{'Y/n' if current_enabled else 'y/N'}] "
        ).strip().lower()

        if enable_str == "":
            enable = current_enabled
        else:
            enable = enable_str in ("y", "yes")

        if not enable:
            agents_section.setdefault(agent_name, {})["enabled"] = False
            if enable != current_enabled:
                changed = True
            console.print(f"  [dim]{agent_name}: disabled[/dim]\n")
            continue

        # Model selection
        console.print(f"  Model ({info['model_hint']}):")
        model_input = console.input(
            f"  Model [{current_model or 'none'}]: "
        ).strip()

        model = model_input if model_input else current_model

        # Budget
        budget_input = console.input(
            f"  Max budget per task USD [{current_budget}]: "
        ).strip()

        try:
            budget = float(budget_input) if budget_input else current_budget
        except ValueError:
            console.print(f"  [yellow]Invalid budget, keeping {current_budget}[/yellow]")
            budget = current_budget

        # Mode
        current_mode = current.get("mode", info["default_mode"])
        mode_input = console.input(
            f"  Mode (cli/api) [{current_mode}]: "
        ).strip().lower()
        mode = mode_input if mode_input in ("cli", "api", "cloud") else current_mode

        # Write to config
        agent_section = agents_section.setdefault(agent_name, {})
        new_values = {
            "enabled": True,
            "mode": mode,
            "api_key_env": key_env,
            "max_concurrent": current.get("max_concurrent", 2),
            "timeout": current.get("timeout", 600 if agent_name in ("claude", "gemini") else 300),
            "max_budget_usd": budget,
        }
        if model:
            new_values["model"] = model

        if new_values != {k: current.get(k) for k in new_values}:
            changed = True

        agent_section.update(new_values)

        status_parts = [f"enabled", f"mode={mode}"]
        if model:
            status_parts.append(f"model={model}")
        status_parts.append(f"budget=${budget:.2f}")
        console.print(f"  [green]{agent_name}: {', '.join(status_parts)}[/green]\n")

    # --- OpenRouter API key (used by LLM client for verification/planning) ---
    console.print(f"[bold cyan]--- OpenRouter (LLM Client) ---[/bold cyan]")
    import os
    or_key = os.getenv("OPENROUTER_API_KEY", "")
    or_status = "[green]set[/green]" if or_key else "[red]not set[/red]"
    console.print(f"  API key (OPENROUTER_API_KEY): {or_status}")
    if not or_key:
        console.print(f"  [dim]Set it with: export OPENROUTER_API_KEY=your-key-here[/dim]")
    console.print()

    # --- Write config ---
    if changed:
        with open(config_path, "w") as f:
            _toml.dump(raw, f)
        console.print(f"[green]Configuration saved to {config_path}[/green]")
    else:
        console.print(f"[dim]No changes made to {config_path}[/dim]")

    # --- Summary ---
    enabled_agents = [
        name for name, cfg in agents_section.items()
        if isinstance(cfg, dict) and cfg.get("enabled")
    ]
    console.print(f"\n[bold]Setup Complete[/bold]")
    console.print(f"  Enabled agents: {', '.join(enabled_agents) or 'none'}")

    # Check for missing keys
    missing_keys = []
    for name in enabled_agents:
        cfg = agents_section[name]
        key_env_name = cfg.get("api_key_env", "")
        if key_env_name and not os.getenv(key_env_name, ""):
            missing_keys.append(f"  export {key_env_name}=your-key-here")

    if missing_keys:
        console.print(f"\n[yellow]Missing API keys — add these to your shell profile:[/yellow]")
        for line in missing_keys:
            console.print(line)

    console.print(f"\n[dim]Next steps:[/dim]")
    console.print(f"  claw status              — verify agent connectivity")
    console.print(f"  claw evaluate <repo>     — analyze a repository")
    console.print(f"  claw add-goal <repo>     — add a custom task")
    console.print(f"  claw enhance <repo>      — run the full pipeline")


def app_main() -> None:
    """Entry point for the installed CLI."""
    app()


if __name__ == "__main__":
    app_main()
