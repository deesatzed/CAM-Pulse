"""Export methodologies as JourneyKits-compatible directory packages.

Produces a directory with:
    journey.json   — manifest with name, count, and methodology list
    README.md      — human-readable overview
    prompts/       — one .md per methodology + system.md
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("claw.community.kit_exporter")

# Patterns that indicate secrets — redact from exported text
_SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"Bearer\s+[a-zA-Z0-9._\-]+"),
]


def _strip_secrets(text: str) -> str:
    """Replace secret patterns with [REDACTED]."""
    for pat in _SECRET_PATTERNS:
        text = pat.sub("[REDACTED]", text)
    return text


async def export_kit(
    engine: Any,
    output_dir: Path,
    brain: str,
    category: Optional[str] = None,
    top_n: int = 5,
) -> dict[str, Any]:
    """Export top methodologies as a JourneyKit directory.

    Args:
        engine: DatabaseEngine instance with fetch_all/execute.
        output_dir: Target directory (created if needed).
        brain: Brain name (e.g. 'python', 'typescript').
        category: Optional category tag filter (matches 'category:<value>' in tags).
        top_n: Maximum number of methodologies to export.

    Returns:
        Dict with 'methodology_count' and 'kit_name'.

    Raises:
        ValueError: If no viable methodologies match the query.
    """
    # Build query — filter by lifecycle_state='viable' and optional category tag
    if category is not None:
        tag_pattern = f"%category:{category}%"
        rows = await engine.fetch_all(
            "SELECT id, problem_description, solution_code, tags, fitness_vector "
            "FROM methodologies "
            "WHERE lifecycle_state = 'viable' AND tags LIKE ? "
            "ORDER BY json_extract(fitness_vector, '$.total') DESC "
            "LIMIT ?",
            [tag_pattern, top_n],
        )
    else:
        rows = await engine.fetch_all(
            "SELECT id, problem_description, solution_code, tags, fitness_vector "
            "FROM methodologies "
            "WHERE lifecycle_state = 'viable' "
            "ORDER BY json_extract(fitness_vector, '$.total') DESC "
            "LIMIT ?",
            [top_n],
        )

    if not rows:
        raise ValueError(
            f"No methodologies found for brain={brain!r}, category={category!r}"
        )

    kit_name = f"cam-{brain}-{category}" if category else f"cam-{brain}"

    # Create directory structure
    output_dir.mkdir(parents=True, exist_ok=True)
    prompts_dir = output_dir / "prompts"
    prompts_dir.mkdir(exist_ok=True)

    # Build methodology list for manifest
    methodologies: list[dict[str, Any]] = []
    for row in rows:
        methodologies.append({
            "id": row["id"],
            "problem_description": _strip_secrets(row["problem_description"]),
            "solution_code": _strip_secrets(row["solution_code"]),
            "tags": json.loads(row["tags"]) if isinstance(row["tags"], str) else row["tags"],
        })

    # Write journey.json
    manifest = {
        "name": kit_name,
        "methodology_count": len(methodologies),
        "methodologies": methodologies,
    }
    (output_dir / "journey.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False)
    )

    # Write README.md
    readme_lines = [
        f"# {kit_name}",
        "",
        f"Exported {len(methodologies)} methodologies from CAM-PULSE.",
        "",
        "## Methodologies",
        "",
    ]
    for m in methodologies:
        readme_lines.append(f"- **{m['id']}**: {m['problem_description'][:80]}")
    (output_dir / "README.md").write_text("\n".join(readme_lines) + "\n")

    # Write prompts/system.md
    system_prompt = (
        f"You are an expert using the {kit_name} knowledge kit.\n"
        f"You have access to {len(methodologies)} proven methodologies.\n"
    )
    (prompts_dir / "system.md").write_text(system_prompt)

    # Write one prompt per methodology
    for m in methodologies:
        slug = re.sub(r"[^a-zA-Z0-9_-]", "_", m["id"])
        content = (
            f"# {m['id']}\n\n"
            f"## Problem\n{m['problem_description']}\n\n"
            f"## Solution\n```\n{m['solution_code']}\n```\n"
        )
        (prompts_dir / f"{slug}.md").write_text(_strip_secrets(content))

    logger.info("Exported kit %s with %d methodologies to %s", kit_name, len(methodologies), output_dir)

    return {
        "methodology_count": len(methodologies),
        "kit_name": kit_name,
    }
