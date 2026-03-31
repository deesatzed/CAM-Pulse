"""CAG Methodology Serializer.

Converts Methodology objects into a structured text format optimized for
LLM comprehension when loaded into a KV cache. Each methodology becomes
a delimited block with problem, solution, domain, and capability metadata.

When a solution exceeds the context_pointer_threshold, the serializer emits
a compact "pointer" block that preserves problem description and capability
summary while replacing the full solution with a reference ID. The agent can
request the full content on demand via the pointer reference.

When shorthand compression is enabled, long solutions are compressed via
extractive/abstractive summarization (BART or fallback) before serialization.
Compression runs at build time only.

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


def _build_capability_summary(m: Methodology) -> str:
    """Build a compact capability summary string from capability_data.

    Used by the pointer format to preserve essential capability metadata
    without including the full solution code.
    """
    cap = _parse_capability_data(m)
    parts: list[str] = []

    # Domain
    domains = cap.get("domain")
    if domains:
        if isinstance(domains, list):
            parts.append(f"domain={', '.join(str(d) for d in domains)}")
        else:
            parts.append(f"domain={domains}")

    # Activation triggers (first 3)
    triggers = cap.get("activation_triggers")
    if triggers and isinstance(triggers, list):
        parts.append(f"triggers={', '.join(str(t) for t in triggers[:3])}")

    # Outputs (first 3)
    outputs = cap.get("outputs")
    if outputs and isinstance(outputs, list):
        out_names = [
            o.get("name", str(o)) if isinstance(o, dict) else str(o)
            for o in outputs[:3]
        ]
        parts.append(f"outputs={', '.join(out_names)}")

    return "; ".join(parts) if parts else "no capability data"


def serialize_methodology(
    m: Methodology,
    max_solution_chars: int = 2000,
    pointer_threshold: int = 0,
    compress: bool = False,
    compress_max_chars: int = 800,
) -> str:
    """Serialize a single Methodology into a structured text block.

    The output format uses ``=== METHODOLOGY <id> ===`` delimiters and
    labelled fields so an LLM can reliably parse the content when it
    appears inside a KV-cache prompt prefix.

    When *pointer_threshold* > 0 and the solution exceeds that length,
    a compact pointer format is emitted instead of the full (or truncated)
    solution. The pointer preserves the methodology ID, problem description,
    capability summary, and solution size so the agent can request the full
    content on demand via ``ref:methodology#<id>``.

    When *compress* is True and the solution exceeds *compress_max_chars*,
    the solution text is compressed via extractive/abstractive summarization
    before serialization. This runs at build time only.

    Parameters
    ----------
    m : Methodology
        The methodology to serialize.
    max_solution_chars : int
        If the solution code exceeds this length it is truncated and a
        ``[TRUNCATED]`` marker is appended. Only used when pointer_threshold
        is 0 (disabled) or the solution is under the pointer threshold.
    pointer_threshold : int
        When > 0, solutions exceeding this character count are replaced with
        a compact pointer block. When 0 (default), the old truncation
        behaviour is used.
    compress : bool
        When True, long solutions are compressed via shorthand compression
        before serialization. Compression is applied before truncation.
    compress_max_chars : int
        Maximum characters in compressed output. Only used when compress=True.
    """
    fitness = _extract_fitness_score(m)
    domain = _extract_domain(m)
    tags = ", ".join(m.tags) if m.tags else ""
    solution = m.solution_code or ""

    # --- Context pointer path: compact summary + reference ID ---
    if pointer_threshold > 0 and len(solution) > pointer_threshold:
        cap_summary = _build_capability_summary(m)

        lines = [
            f"=== METHODOLOGY {m.id} ===",
            f"DOMAIN: {domain} | TAGS: {tags} | LIFECYCLE: {m.lifecycle_state} | FITNESS: {fitness:.2f}",
            f"PROBLEM: {m.problem_description}",
            f"CAPABILITY: {cap_summary}",
            f"SOLUTION: [POINTER -- {len(solution)} chars -- ref:methodology#{m.id}]",
        ]

        if m.methodology_notes:
            notes = m.methodology_notes[:200]
            if len(m.methodology_notes) > 200:
                notes += "..."
            lines.append(f"NOTES: {notes}")

        lines.append("===")
        return "\n".join(lines)

    # --- Shorthand compression path ---
    if compress and len(solution) > compress_max_chars:
        from claw.memory.cag_compressor import compress_text

        solution = compress_text(solution, max_output_chars=compress_max_chars)
    elif len(solution) > max_solution_chars:
        solution = solution[:max_solution_chars] + f"\n[TRUNCATED -- full: methodology#{m.id}]"

    # --- Also compress methodology_notes if compress is enabled ---
    notes_text = m.methodology_notes or ""
    if compress and len(notes_text) > compress_max_chars:
        from claw.memory.cag_compressor import compress_text

        notes_text = compress_text(notes_text, max_output_chars=compress_max_chars)

    # --- Standard path: full solution (possibly truncated/compressed) ---
    triggers = _extract_triggers(m)
    inputs = _extract_io(m, "inputs")
    outputs = _extract_io(m, "outputs")

    lines = [
        f"=== METHODOLOGY {m.id} ===",
        f"DOMAIN: {domain} | TAGS: {tags} | LIFECYCLE: {m.lifecycle_state} | FITNESS: {fitness:.2f}",
        f"PROBLEM: {m.problem_description}",
        f"SOLUTION:\n{solution}",
    ]

    if notes_text:
        lines.append(f"NOTES: {notes_text}")

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
    pointer_threshold: int = 0,
    compress: bool = False,
    compress_max_chars: int = 800,
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
    pointer_threshold : int
        Passed through to :func:`serialize_methodology`. When > 0, solutions
        exceeding this length are emitted as compact pointers instead of
        truncated code.
    compress : bool
        Passed through to :func:`serialize_methodology`. When True, long
        solutions are compressed via shorthand compression.
    compress_max_chars : int
        Passed through to :func:`serialize_methodology`. Maximum characters
        per solution after compression.
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

    blocks = [
        serialize_methodology(
            m,
            max_solution_chars,
            pointer_threshold=pointer_threshold,
            compress=compress,
            compress_max_chars=compress_max_chars,
        )
        for m in sorted_methods
    ]
    return header + "\n\n".join(blocks) + "\n"
