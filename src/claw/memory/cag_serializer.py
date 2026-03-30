"""CAG Methodology Serializer.

Converts Methodology objects into a structured text format optimized for
LLM comprehension when loaded into a KV cache. Each methodology becomes
a delimited block with problem, solution, domain, and capability metadata.

Used by the CAG retriever (Phase 2) and the knowledge export pipeline (Phase 3).
"""
from __future__ import annotations

import json
from typing import Any

from claw.core.models import Methodology


def _parse_capability_data(m: Methodology) -> dict[str, Any]:
    """Return capability_data as a dict, handling both dict and JSON string."""
    cap = m.capability_data or {}
    if isinstance(cap, str):
        try:
            cap = json.loads(cap)
        except (json.JSONDecodeError, TypeError):
            return {}
    return cap if isinstance(cap, dict) else {}


def _extract_fitness_score(m: Methodology) -> float:
    """Compute a single fitness score as the average of fitness_vector values."""
    fv = m.fitness_vector or {}
    if not fv:
        return 0.0
    return sum(fv.values()) / len(fv)


def _extract_domain(m: Methodology) -> str:
    """Extract domain from capability_data."""
    cap = _parse_capability_data(m)
    domains = cap.get("domain", [])
    if isinstance(domains, list):
        return ", ".join(str(d) for d in domains) or "unknown"
    return str(domains)


def _extract_triggers(m: Methodology) -> str:
    """Extract activation triggers from capability_data."""
    cap = _parse_capability_data(m)
    triggers = cap.get("activation_triggers", [])
    if isinstance(triggers, list):
        return ", ".join(str(t) for t in triggers)
    return str(triggers)


def _extract_io(m: Methodology, key: str) -> str:
    """Extract inputs or outputs from capability_data.

    Parameters
    ----------
    m : Methodology
        The methodology to extract IO from.
    key : str
        Either ``"inputs"`` or ``"outputs"``.
    """
    cap = _parse_capability_data(m)
    items = cap.get(key, [])
    if isinstance(items, list):
        parts = []
        for item in items:
            if isinstance(item, dict):
                parts.append(f"{item.get('name', '?')}:{item.get('type', '?')}")
            else:
                parts.append(str(item))
        return ", ".join(parts)
    return str(items)


def serialize_methodology(
    m: Methodology,
    max_solution_chars: int = 2000,
) -> str:
    """Serialize a single Methodology into a structured text block.

    The output format uses ``=== METHODOLOGY <id> ===`` delimiters and
    labelled fields so an LLM can reliably parse the content when it
    appears inside a KV-cache prompt prefix.

    Parameters
    ----------
    m : Methodology
        The methodology to serialize.
    max_solution_chars : int
        If the solution code exceeds this length it is truncated and a
        ``[TRUNCATED]`` marker is appended.
    """
    fitness = _extract_fitness_score(m)
    domain = _extract_domain(m)
    triggers = _extract_triggers(m)
    inputs = _extract_io(m, "inputs")
    outputs = _extract_io(m, "outputs")
    tags = ", ".join(m.tags) if m.tags else ""

    solution = m.solution_code or ""
    if len(solution) > max_solution_chars:
        solution = solution[:max_solution_chars] + f"\n[TRUNCATED — full: methodology#{m.id}]"

    lines = [
        f"=== METHODOLOGY {m.id} ===",
        f"DOMAIN: {domain} | TAGS: {tags} | LIFECYCLE: {m.lifecycle_state} | FITNESS: {fitness:.2f}",
        f"PROBLEM: {m.problem_description}",
        f"SOLUTION:\n{solution}",
    ]

    if m.methodology_notes:
        lines.append(f"NOTES: {m.methodology_notes}")

    if inputs or outputs:
        lines.append(f"IO: inputs=[{inputs}] outputs=[{outputs}]")

    if triggers:
        lines.append(f"TRIGGERS: {triggers}")

    lines.append("===")
    return "\n".join(lines)


def serialize_corpus(
    methodologies: list[Methodology],
    max_count: int = 0,
    max_solution_chars: int = 2000,
) -> str:
    """Serialize a list of methodologies into a full corpus document.

    Methodologies are sorted by fitness (highest first). If *max_count* > 0,
    only the top-N are included.

    Parameters
    ----------
    methodologies : list[Methodology]
        The methodologies to serialize.
    max_count : int
        Maximum number of methodologies to include. ``0`` means no limit.
    max_solution_chars : int
        Passed through to :func:`serialize_methodology`.
    """
    if not methodologies:
        return "# CAM Knowledge Base\nEmpty corpus.\n"

    # Sort by fitness descending
    sorted_methods = sorted(
        methodologies,
        key=lambda m: _extract_fitness_score(m),
        reverse=True,
    )

    if max_count > 0:
        sorted_methods = sorted_methods[:max_count]

    header = (
        f"# CAM Knowledge Base\n"
        f"# Total methodologies: {len(sorted_methods)}\n"
        f"# Format: structured blocks for LLM context injection\n\n"
    )

    blocks = [serialize_methodology(m, max_solution_chars) for m in sorted_methods]
    return header + "\n\n".join(blocks) + "\n"
