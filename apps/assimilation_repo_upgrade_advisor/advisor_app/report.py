"""Markdown report rendering."""

from __future__ import annotations

from .models import Recommendation, RepoProfile


def render_report(profile: RepoProfile, recommendations: list[Recommendation], knowledge_item_count: int) -> str:
    lines: list[str] = []
    lines.append(f"# Assimilation-Powered Repo Upgrade Plan: {profile.repo_path.name}")
    lines.append("")
    lines.append("## Executive Summary")
    lines.append(
        f"Scanned `{profile.repo_path}` and matched repo signals against {knowledge_item_count} assimilated knowledge-pack items."
    )
    lines.append(f"Detected {len(recommendations)} ranked upgrade recommendations.")
    lines.append("")
    lines.append("## Repo Snapshot")
    lines.append(f"- Files scanned: {profile.file_count}")
    lines.append(f"- Python files: {len(profile.python_files)}")
    lines.append(f"- Test files: {len(profile.test_files)}")
    lines.append(f"- CI workflows: {len(profile.ci_files)}")
    lines.append(f"- Top files: {', '.join(profile.top_files[:8])}")
    lines.append("")
    lines.append("## Ranked Recommendations")
    lines.append("")
    for idx, rec in enumerate(recommendations, start=1):
        lines.append(f"### {idx}. {rec.title}")
        lines.append("")
        lines.append(f"- Category: `{rec.category}`")
        lines.append(f"- Confidence: `{rec.confidence:.3f}`")
        lines.append(f"- Difficulty: `{rec.difficulty}`")
        lines.append(f"- Expected payoff: `{rec.payoff}`")
        lines.append(f"- Why now: {rec.why_now}")
        lines.append(f"- Recommended change: {rec.recommended_change}")
        lines.append(f"- First step: {rec.first_step}")
        lines.append("- Evidence:")
        for item in rec.evidence:
            lines.append(f"  - {item}")
        lines.append("- Assimilated provenance:")
        for match in rec.provenance:
            lines.append(
                f"  - `{match.item_id}` from `{match.source_repo}` — {match.title} (score={match.score:.3f}; overlap: {match.rationale})"
            )
        lines.append("")
    lines.append("## Implementation Order")
    lines.append("")
    for idx, rec in enumerate(recommendations, start=1):
        lines.append(f"{idx}. {rec.title} -> {rec.first_step}")
    lines.append("")
    lines.append("## Why These Surfaced")
    lines.append("")
    lines.append(
        "Recommendations surfaced where concrete repo signals aligned with assimilated methodologies/tasks by category, vocabulary overlap, and stored potential scores."
    )
    lines.append("")
    lines.append("---")
    lines.append("Standalone report generated without importing CAM runtime code.")
    return "\n".join(lines)
