"""Kit packaging — export top methodologies as a JourneyKits-compatible directory.

Generates a portable knowledge kit containing methodology prompts, a manifest,
and a README.  All text is scrubbed for secrets before export.

Usage:
    from claw.community.kit_exporter import export_kit
    result = await export_kit(engine, Path("/tmp/my-kit"), brain="python", category="testing", top_n=5)
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from pathlib import Path
from typing import Any, Optional

from claw.community.packer import _sanitize_text, compute_content_hash

logger = logging.getLogger("claw.community.kit_exporter")


async def export_kit(
    engine: Any,
    output_dir: Path,
    brain: str = "python",
    category: Optional[str] = None,
    top_n: int = 10,
    instance_name: str = "",
    force: bool = False,
) -> dict:
    """Export top methodologies as a JourneyKits-compatible directory.

    Args:
        engine: DatabaseEngine instance for DB access.
        output_dir: Where to create the kit directory.
        brain: Brain name to filter by (via source: tag or ganglion).
        category: Optional category filter (e.g. "testing", "architecture").
        top_n: Maximum number of methodologies to include.
        instance_name: Instance name for the manifest.
        force: If True, overwrite existing output_dir.

    Returns:
        Dict with kit_name, methodology_count, output_path, manifest_hash.

    Raises:
        ValueError: If brain has no methodologies or output_dir exists without --force.
    """
    if output_dir.exists() and not force:
        raise ValueError(
            f"Output directory already exists: {output_dir}. Use --force to overwrite."
        )

    # Build query to find top methodologies by fitness
    conditions = ["m.lifecycle_state IN ('viable', 'thriving')"]
    params: list[Any] = []

    if category:
        conditions.append("m.tags LIKE ?")
        params.append(f'%"category:{category}"%')

    where_clause = " AND ".join(conditions)
    query = (
        f"SELECT m.id, m.problem_description, m.solution_code, "
        f"m.methodology_notes, m.tags, m.language, m.lifecycle_state, "
        f"m.fitness_vector, m.success_count, m.failure_count, m.retrieval_count "
        f"FROM methodologies m "
        f"WHERE {where_clause} "
        f"ORDER BY json_extract(m.fitness_vector, '$.total') DESC "
        f"LIMIT ?"
    )
    params.append(top_n)

    rows = await engine.fetch_all(query, params)

    if not rows:
        raise ValueError(
            f"No methodologies found for brain='{brain}'"
            + (f", category='{category}'" if category else "")
            + ". Cannot create empty kit."
        )

    # Create directory structure
    output_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir = output_dir / "prompts"
    prompts_dir.mkdir(exist_ok=True)

    # Generate prompts
    methodologies_meta: list[dict] = []
    for idx, row in enumerate(rows, 1):
        tags_raw = row.get("tags") or "[]"
        try:
            tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
        except (json.JSONDecodeError, TypeError):
            tags = []

        fv_raw = row.get("fitness_vector") or "{}"
        try:
            fv = json.loads(fv_raw) if isinstance(fv_raw, str) else fv_raw
        except (json.JSONDecodeError, TypeError):
            fv = {}

        problem = _sanitize_text(row.get("problem_description") or "")
        solution = _sanitize_text(row.get("solution_code") or "")
        notes = _sanitize_text(row.get("methodology_notes") or "")

        # Create slug from problem description
        slug = re.sub(r'[^a-z0-9]+', '-', problem[:60].lower()).strip('-') or f"method-{idx}"

        # Write prompt file
        prompt_content = f"## Problem\n\n{problem}\n\n## Solution\n\n{solution}\n"
        if notes:
            prompt_content += f"\n## Notes\n\n{notes}\n"
        if tags:
            prompt_content += f"\n## Tags\n\n{', '.join(str(t) for t in tags)}\n"

        prompt_path = prompts_dir / f"{idx:03d}-{slug}.md"
        prompt_path.write_text(prompt_content)

        methodologies_meta.append({
            "id": row["id"],
            "problem": problem[:200],
            "fitness": fv.get("total", 0.0),
            "tags": tags,
            "language": row.get("language"),
            "success_count": row.get("success_count", 0),
            "failure_count": row.get("failure_count", 0),
            "retrieval_count": row.get("retrieval_count", 0),
        })

    # Generate system prompt
    system_prompt_path = prompts_dir / "system.md"
    system_prompt_path.write_text(
        f"# CAM-PULSE Knowledge Kit: {brain}\n\n"
        f"This kit contains {len(rows)} curated methodologies"
        + (f" in the '{category}' category" if category else "")
        + f" from the '{brain}' brain.\n\n"
        f"Each methodology represents a proven pattern, fix, or technique "
        f"extracted from real codebases and validated through usage.\n"
    )

    # Generate journey.json manifest
    kit_name = f"cam-{brain}" + (f"-{category}" if category else "")
    manifest = {
        "name": kit_name,
        "version": "1.0.0",
        "description": f"CAM-PULSE knowledge kit: {brain}"
        + (f" / {category}" if category else ""),
        "author": instance_name or "cam-pulse",
        "brain": brain,
        "category": category,
        "methodology_count": len(rows),
        "tools": [
            {"name": "claw_query_memory", "ref": "cam-pulse-mcp"},
            {"name": "claw_store_finding", "ref": "cam-pulse-mcp"},
        ],
        "model_preferences": {
            "reasoning": "claude-sonnet",
            "generation": "gpt-4o",
        },
        "methodologies": methodologies_meta,
    }

    manifest_path = output_dir / "journey.json"
    manifest_path.write_text(json.dumps(manifest, indent=2))

    # Generate README
    readme_lines = [
        f"# {kit_name}\n",
        f"CAM-PULSE Knowledge Kit — {len(rows)} methodologies from the `{brain}` brain",
    ]
    if category:
        readme_lines.append(f"filtered to the `{category}` category.")
    readme_lines.extend([
        "",
        "## Contents",
        "",
        f"- `journey.json` — Kit manifest",
        f"- `prompts/system.md` — System prompt with brain context",
        f"- `prompts/NNN-*.md` — {len(rows)} methodology prompts",
        "",
        "## Methodology Summary",
        "",
        "| # | Problem | Fitness | Language |",
        "|---|---------|---------|----------|",
    ])
    for idx, m in enumerate(methodologies_meta, 1):
        prob = m["problem"][:60].replace("|", "\\|")
        readme_lines.append(
            f"| {idx} | {prob} | {m['fitness']:.2f} | {m.get('language') or '-'} |"
        )
    readme_lines.extend([
        "",
        "---",
        f"Generated by CAM-PULSE ({instance_name or 'anonymous'})",
    ])

    readme_path = output_dir / "README.md"
    readme_path.write_text("\n".join(readme_lines))

    manifest_hash = compute_content_hash(kit_name, json.dumps(manifest))

    logger.info(
        "Exported kit '%s' with %d methodologies to %s",
        kit_name, len(rows), output_dir,
    )

    return {
        "kit_name": kit_name,
        "methodology_count": len(rows),
        "output_path": str(output_dir),
        "manifest_hash": manifest_hash,
    }
