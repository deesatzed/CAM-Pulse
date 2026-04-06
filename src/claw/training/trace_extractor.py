"""RLMHT trace extraction — generates ChatML training examples from cross-brain analysis.

Captures three trace types:
  1. **Routing traces**: "Which brains to query for this domain?"
  2. **Grouping traces**: "Which patterns are universal vs unique?"
  3. **Composition traces**: "How do these patterns compose into layers?"

Each trace is a ChatML message triplet (system/user/assistant) written
as a single JSON line to a JSONL file.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from claw.core.models import CrossLanguageReport

logger = logging.getLogger("claw.training.trace_extractor")

def _build_system_prompt(brain_names: list[str] | None = None) -> str:
    """Build system prompt with actual brain names.

    Args:
        brain_names: List of brain names. When None, uses a generic description.

    Returns:
        System prompt string for ChatML traces.
    """
    if brain_names and len(brain_names) > 0:
        brain_list = ", ".join(brain_names)
        return (
            "You are a cross-language pattern synthesis expert. You analyze software patterns "
            f"across {brain_list} brains to find universal patterns, unique innovations, "
            "and transferable insights. You compose multi-brain architectures from the best patterns "
            "in each language ecosystem."
        )
    return (
        "You are a cross-language pattern synthesis expert. You analyze software patterns "
        "across multiple language brains to find universal patterns, unique innovations, "
        "and transferable insights. You compose multi-brain architectures from the best patterns "
        "in each language ecosystem."
    )


# Default for backward compatibility
SYSTEM_PROMPT = _build_system_prompt()


def _make_routing_traces(report: CrossLanguageReport, system_prompt: str = "") -> list[dict]:
    """Generate routing decision traces: which brains to query for this domain."""
    _sp = system_prompt or SYSTEM_PROMPT
    traces = []

    # One trace for the overall routing decision
    brains_queried = list(report.raw_results_by_brain.keys())
    result_counts = {
        brain: len(ids) for brain, ids in report.raw_results_by_brain.items()
    }

    user_msg = (
        f"Query: \"{report.query}\"\n"
        f"Available brains: {brains_queried}\n"
        f"Domains: {report.domains_queried}\n\n"
        f"Which brains should be queried and why?"
    )

    assistant_msg_parts = [f"For the query \"{report.query}\", I route to these brains:\n"]
    for brain in brains_queried:
        count = result_counts.get(brain, 0)
        assistant_msg_parts.append(f"- **{brain}**: {count} results returned")

    assistant_msg_parts.append(
        f"\nCross-brain coverage: {report.metrics.cross_brain_coverage:.0%} "
        f"({report.metrics.brains_with_results}/{report.metrics.brains_queried} brains with results)"
    )

    traces.append({
        "messages": [
            {"role": "system", "content": _sp},
            {"role": "user", "content": user_msg},
            {"role": "assistant", "content": "\n".join(assistant_msg_parts)},
        ],
        "trace_type": "routing",
        "query": report.query,
    })

    # Per-brain routing traces
    for brain, ids in report.raw_results_by_brain.items():
        traces.append({
            "messages": [
                {"role": "system", "content": _sp},
                {"role": "user", "content": (
                    f"Should the '{brain}' brain be queried for: \"{report.query}\"?"
                )},
                {"role": "assistant", "content": (
                    f"Yes. The {brain} brain returned {len(ids)} relevant methodologies "
                    f"for this query. Methodology IDs: {ids[:5]}"
                    f"{'...' if len(ids) > 5 else ''}"
                )},
            ],
            "trace_type": "routing",
            "query": report.query,
        })

    return traces


def _make_grouping_traces(report: CrossLanguageReport, system_prompt: str = "") -> list[dict]:
    """Generate pattern grouping traces: universal vs unique classification."""
    _sp = system_prompt or SYSTEM_PROMPT
    traces = []

    # Universal pattern traces
    for pattern in report.universal_patterns:
        langs = list(pattern.implementations.keys())
        impl_lines = []
        for lang, summary in pattern.implementations.items():
            impl_lines.append(f"  [{lang}] {summary}")

        traces.append({
            "messages": [
                {"role": "system", "content": _sp},
                {"role": "user", "content": (
                    f"Classify this pattern found across brains:\n"
                    f"Pattern: {pattern.pattern_name}\n"
                    f"Languages: {langs}\n"
                    f"Implementations:\n" + "\n".join(impl_lines)
                )},
                {"role": "assistant", "content": (
                    f"UNIVERSAL PATTERN: \"{pattern.pattern_name}\"\n"
                    f"Found in {len(langs)} brains: {langs}\n"
                    f"Domain overlap score: {pattern.domain_overlap:.2f}\n"
                    f"Categories: {pattern.source_categories}\n"
                    f"This is the same abstract concept implemented differently per language."
                )},
            ],
            "trace_type": "grouping",
            "query": report.query,
        })

    # Unique innovation traces
    for innovation in report.unique_innovations:
        traces.append({
            "messages": [
                {"role": "system", "content": _sp},
                {"role": "user", "content": (
                    f"Is this pattern unique to one brain?\n"
                    f"Brain: {innovation.brain}\n"
                    f"Category: {innovation.category}\n"
                    f"Problem: {innovation.problem_summary}"
                )},
                {"role": "assistant", "content": (
                    f"UNIQUE INNOVATION in {innovation.brain}:\n"
                    f"{innovation.problem_summary}\n"
                    f"Why unique: {innovation.why_unique}\n"
                    f"No equivalent found in other brains."
                )},
            ],
            "trace_type": "grouping",
            "query": report.query,
        })

    return traces


def _make_composition_traces(report: CrossLanguageReport, system_prompt: str = "") -> list[dict]:
    """Generate composition traces: how patterns combine into layers."""
    _sp = system_prompt or SYSTEM_PROMPT
    traces = []

    if not report.composition_layers:
        return traces

    # Full composition trace
    layer_lines = []
    for layer in report.composition_layers:
        layer_lines.append(
            f"  L{layer.layer_number}: {layer.layer_name} "
            f"({layer.contributing_brain}) — {layer.methodology_summary[:80]}"
        )

    traces.append({
        "messages": [
            {"role": "system", "content": _sp},
            {"role": "user", "content": (
                f"Compose a multi-brain architecture for: \"{report.query}\"\n"
                f"Available brains: {list(report.raw_results_by_brain.keys())}"
            )},
            {"role": "assistant", "content": (
                f"MULTI-BRAIN COMPOSITION ({len(report.composition_layers)} layers):\n"
                + "\n".join(layer_lines)
                + f"\n\nSources: {report.metrics.total_results} methodologies from "
                f"{report.metrics.brains_with_results} brains"
            )},
        ],
        "trace_type": "composition",
        "query": report.query,
    })

    # Per-layer traces
    for layer in report.composition_layers:
        traces.append({
            "messages": [
                {"role": "system", "content": _sp},
                {"role": "user", "content": (
                    f"Which brain provides the best '{layer.layer_name}' layer "
                    f"for: \"{report.query}\"?"
                )},
                {"role": "assistant", "content": (
                    f"Layer {layer.layer_number} ({layer.layer_name}): "
                    f"Best provided by {layer.contributing_brain} brain.\n"
                    f"Methodology: {layer.methodology_summary}\n"
                    f"ID: {layer.methodology_id}"
                )},
            ],
            "trace_type": "composition",
            "query": report.query,
        })

    # Transferable insight traces
    for insight in report.transferable_insights:
        traces.append({
            "messages": [
                {"role": "system", "content": _sp},
                {"role": "user", "content": (
                    f"Can the pattern from {insight.source_brain} be transferred "
                    f"to {insight.target_brain}?\n"
                    f"Pattern: {insight.pattern_name}"
                )},
                {"role": "assistant", "content": (
                    f"TRANSFERABLE INSIGHT: {insight.source_brain} → {insight.target_brain}\n"
                    f"Pattern: {insight.pattern_name}\n"
                    f"Rationale: {insight.rationale}\n"
                    f"Source methodology: {insight.source_methodology_id}"
                )},
            ],
            "trace_type": "composition",
            "query": report.query,
        })

    return traces


class FederationTraceExtractor:
    """Extracts ChatML training traces from CrossLanguageReport objects.

    Writes traces as JSONL to the specified output directory.
    """

    def __init__(
        self,
        output_dir: str = "data/rlmht_traces",
        brain_names: list[str] | None = None,
    ):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._system_prompt = _build_system_prompt(brain_names)

    def extract_traces(self, report: CrossLanguageReport) -> list[dict]:
        """Extract all trace types from a report.

        Returns:
            List of ChatML trace dicts.
        """
        traces = []
        traces.extend(_make_routing_traces(report, self._system_prompt))
        traces.extend(_make_grouping_traces(report, self._system_prompt))
        traces.extend(_make_composition_traces(report, self._system_prompt))
        return traces

    def write_traces(
        self,
        report: CrossLanguageReport,
        domain_label: Optional[str] = None,
    ) -> tuple[Path, int]:
        """Extract traces and write to JSONL file.

        Args:
            report: The cross-language analysis report.
            domain_label: Label for the output file (defaults to first domain).

        Returns:
            Tuple of (output_path, trace_count).
        """
        traces = self.extract_traces(report)

        if not domain_label:
            domain_label = report.domains_queried[0] if report.domains_queried else "general"

        # Sanitize label for filename
        safe_label = "".join(c if c.isalnum() or c == "_" else "_" for c in domain_label)
        date_str = datetime.now(UTC).strftime("%Y%m%d")
        filename = f"{safe_label}_{date_str}.jsonl"
        output_path = self.output_dir / filename

        with open(output_path, "a") as f:
            for trace in traces:
                f.write(json.dumps(trace, ensure_ascii=False) + "\n")

        logger.info("Wrote %d traces to %s", len(traces), output_path)
        return output_path, len(traces)
