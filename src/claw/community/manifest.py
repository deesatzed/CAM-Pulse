"""Brain manifest generator for the CAM Swarm.

Each CAM Ganglion generates a manifest summarizing what its claw.db knows:
categories, languages, source repos, methodology counts, lifecycle distribution.
Sibling ganglia read this manifest to decide if cross-querying is worthwhile.

Together, all ganglion manifests form a map of the CAM Brain's total knowledge.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("claw.community.manifest")


async def generate_manifest(
    engine: Any,
    instance_name: str = "",
    instance_description: str = "",
) -> dict[str, Any]:
    """Generate a brain manifest summarizing what this instance knows.

    Args:
        engine: DatabaseEngine with an open claw.db connection.
        instance_name: Human-readable name for this instance (e.g. "quantum-physics").
        instance_description: Short description of this instance's domain focus.

    Returns:
        A dict suitable for JSON serialization.
    """
    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    # --- Methodology counts by lifecycle ---
    lifecycle_rows = await engine.fetch_all(
        "SELECT lifecycle_state, COUNT(*) as cnt FROM methodologies GROUP BY lifecycle_state"
    )
    lifecycle_dist = {r["lifecycle_state"]: r["cnt"] for r in lifecycle_rows}
    total_methodologies = sum(lifecycle_dist.values())

    # --- Category tags ---
    tag_rows = await engine.fetch_all(
        "SELECT tags FROM methodologies WHERE lifecycle_state NOT IN ('dead', 'dormant')"
    )
    category_counts: dict[str, int] = {}
    source_repos: set[str] = set()
    for row in tag_rows:
        raw = row["tags"]
        if not raw:
            continue
        try:
            tags = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        for tag in tags:
            if not isinstance(tag, str):
                continue
            if tag.startswith("source:"):
                source_repos.add(tag.replace("source:", ""))
            elif tag.startswith("category:"):
                cat = tag.replace("category:", "")
                category_counts[cat] = category_counts.get(cat, 0) + 1
            elif ":" not in tag:
                category_counts[tag] = category_counts.get(tag, 0) + 1

    # --- Language breakdown ---
    lang_rows = await engine.fetch_all(
        """SELECT language, COUNT(*) as cnt FROM methodologies
           WHERE lifecycle_state NOT IN ('dead', 'dormant') AND language IS NOT NULL AND language != ''
           GROUP BY language ORDER BY cnt DESC"""
    )
    language_breakdown = {r["language"]: r["cnt"] for r in lang_rows}

    # --- Top methodology types ---
    type_rows = await engine.fetch_all(
        """SELECT methodology_type, COUNT(*) as cnt FROM methodologies
           WHERE lifecycle_state NOT IN ('dead', 'dormant')
           GROUP BY methodology_type ORDER BY cnt DESC LIMIT 10"""
    )
    type_breakdown = {r["methodology_type"]: r["cnt"] for r in type_rows}

    # --- PULSE discoveries ---
    pulse_count = 0
    try:
        pulse_rows = await engine.fetch_all(
            "SELECT COUNT(*) as cnt FROM pulse_discoveries WHERE status = 'assimilated'"
        )
        pulse_count = pulse_rows[0]["cnt"] if pulse_rows else 0
    except Exception:
        pass  # Table may not exist

    # --- Top categories (sorted by count, top 15) ---
    top_categories = sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:15]

    # --- Domain keywords (enriched from categories + languages + methodology vocabulary) ---
    domain_keywords = [cat for cat, _ in top_categories[:10]]
    domain_keywords.extend(lang for lang in list(language_breakdown.keys())[:5])
    # Add source repo names as domain keywords (lowercase)
    domain_keywords.extend(r.lower() for r in sorted(source_repos)[:20])

    # Extract top vocabulary from problem_description text (TF-based)
    try:
        vocab_rows = await engine.fetch_all(
            "SELECT problem_description FROM methodologies "
            "WHERE lifecycle_state NOT IN ('dead', 'dormant') "
            "AND problem_description IS NOT NULL AND problem_description != '' "
            "LIMIT 500"
        )
        import re as _re
        _stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would", "could",
            "should", "may", "might", "shall", "can", "to", "of", "in", "for",
            "on", "with", "at", "by", "from", "as", "into", "through", "during",
            "before", "after", "above", "below", "between", "under", "again",
            "over", "further", "then", "once", "here", "there", "when", "where",
            "why", "how", "all", "each", "every", "both", "few", "more", "most",
            "other", "some", "such", "no", "nor", "not", "only", "own", "same",
            "so", "than", "too", "very", "and", "but", "or", "if", "this", "that",
            "these", "those", "it", "its", "we", "our", "they", "them", "their",
            "what", "which", "who", "whom", "about", "up", "out", "just", "also",
            "new", "use", "using", "used", "add", "create", "make", "implement",
            "need", "want", "like", "get", "set", "code", "function", "class",
            "method", "data", "file", "system", "based", "provides", "pattern",
        }
        term_counts: dict[str, int] = {}
        for row in vocab_rows:
            tokens = _re.findall(r"[a-zA-Z0-9_]+", row["problem_description"].lower())
            for t in tokens:
                if len(t) >= 3 and t not in _stop_words:
                    term_counts[t] = term_counts.get(t, 0) + 1
        # Top 50 terms by frequency (min 3 occurrences)
        top_terms = sorted(
            ((t, c) for t, c in term_counts.items() if c >= 3),
            key=lambda x: -x[1],
        )[:50]
        existing = set(domain_keywords)
        domain_keywords.extend(t for t, _ in top_terms if t not in existing)
    except Exception as e:
        logger.debug("Vocabulary extraction skipped: %s", e)

    # --- Compute manifest fingerprint ---
    fingerprint_input = f"{total_methodologies}:{json.dumps(lifecycle_dist, sort_keys=True)}:{now_iso}"
    fingerprint = hashlib.sha256(fingerprint_input.encode()).hexdigest()[:16]

    manifest = {
        "manifest_version": "1.0",
        "generated_at": now_iso,
        "fingerprint": fingerprint,
        "instance_name": instance_name,
        "instance_description": instance_description,
        "total_methodologies": total_methodologies,
        "lifecycle_distribution": lifecycle_dist,
        "top_categories": dict(top_categories),
        "language_breakdown": language_breakdown,
        "methodology_types": type_breakdown,
        "source_repos": sorted(source_repos),
        "source_repo_count": len(source_repos),
        "pulse_discoveries_assimilated": pulse_count,
        "domain_keywords": domain_keywords,
    }

    return manifest


async def save_manifest(
    engine: Any,
    output_path: Path,
    instance_name: str = "",
    instance_description: str = "",
) -> dict[str, Any]:
    """Generate and save brain manifest to a JSON file.

    Args:
        engine: DatabaseEngine.
        output_path: Where to write the manifest JSON.
        instance_name: Human-readable name.
        instance_description: Domain description.

    Returns:
        The generated manifest dict.
    """
    manifest = await generate_manifest(engine, instance_name, instance_description)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(manifest, indent=2))
    logger.info("Saved brain manifest to %s (%d methodologies)", output_path, manifest["total_methodologies"])
    return manifest


def load_manifest(manifest_path: Path) -> Optional[dict[str, Any]]:
    """Load a brain manifest from disk.

    Returns None if the file doesn't exist or is invalid JSON.
    """
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load manifest from %s: %s", manifest_path, e)
        return None


def score_manifest_relevance(
    manifest: dict[str, Any],
    query_keywords: list[str],
    query_language: Optional[str] = None,
) -> float:
    """Score how relevant a sibling's manifest is to a query.

    Returns 0.0 to 1.0. Based on:
    - Keyword overlap with domain_keywords + top_categories (60%)
    - Language match (20%)
    - Brain size / maturity (20%)

    Args:
        manifest: A loaded brain manifest dict.
        query_keywords: Keywords extracted from the task description.
        query_language: Programming language of the task (if known).
    """
    if not manifest or not query_keywords:
        return 0.0

    # --- Keyword overlap (60%) ---
    domain_kw = set(k.lower() for k in manifest.get("domain_keywords", []))
    top_cats = set(k.lower() for k in manifest.get("top_categories", {}).keys())
    brain_terms = domain_kw | top_cats
    query_terms = set(k.lower() for k in query_keywords)
    if brain_terms:
        overlap = len(query_terms & brain_terms) / max(len(query_terms), 1)
    else:
        overlap = 0.0
    keyword_score = min(overlap * 1.5, 1.0)  # Boost partial overlap

    # --- Language match (20%) ---
    lang_score = 0.0
    if query_language:
        lang_breakdown = manifest.get("language_breakdown", {})
        if query_language.lower() in {k.lower() for k in lang_breakdown}:
            lang_score = 1.0
        elif lang_breakdown:
            lang_score = 0.2  # Has other languages, partial credit

    # --- Maturity (20%) ---
    total = manifest.get("total_methodologies", 0)
    lifecycle = manifest.get("lifecycle_distribution", {})
    viable_plus = sum(lifecycle.get(s, 0) for s in ["viable", "thriving"])
    maturity_score = min(total / 200, 1.0) * 0.5 + min(viable_plus / 50, 1.0) * 0.5

    return keyword_score * 0.6 + lang_score * 0.2 + maturity_score * 0.2


class BrainTopology:
    """Aggregates brain manifests into a topology summary for agent prompts.

    Produces a stable, deterministic string suitable for:
    - Agent task prompts (brain awareness section)
    - KV cache system message prefix
    - RLMHT trace system prompts (dynamic brain list)

    The summary is byte-identical for the same set of manifests, enabling
    KV cache hits. Regenerate only when brain topology changes (new mining).
    """

    def __init__(self, instance_config: Any, primary_db_path: str = ""):
        self._instance_config = instance_config
        self._primary_db_path = primary_db_path
        self._brain_summaries: list[dict[str, Any]] = []
        self._total_methodologies: int = 0
        self._loaded: bool = False

    def load(self) -> None:
        """Load all manifests and build topology. Sync, no DB queries."""
        self._brain_summaries = []
        self._total_methodologies = 0

        # Primary DB manifest
        primary_manifest_path = Path(
            getattr(self._instance_config, "manifest_path", "data/brain_manifest.json")
        )
        if not primary_manifest_path.is_absolute() and self._primary_db_path:
            # Resolve relative to workspace root (parent of data/)
            ws = Path(self._primary_db_path).parent.parent
            primary_manifest_path = ws / primary_manifest_path
        primary_manifest = load_manifest(primary_manifest_path)
        if primary_manifest:
            self._brain_summaries.append({
                "name": getattr(self._instance_config, "instance_name", "general") or "general",
                "description": getattr(self._instance_config, "instance_description", ""),
                "total": primary_manifest.get("total_methodologies", 0),
                "top_categories": sorted(primary_manifest.get("top_categories", {}).keys()),
                "languages": sorted(primary_manifest.get("language_breakdown", {}).keys()),
                "source": "primary",
            })
            self._total_methodologies += primary_manifest.get("total_methodologies", 0)

        # Sibling brain manifests
        for sibling in getattr(self._instance_config, "siblings", []):
            sibling_db = getattr(sibling, "db_path", "")
            if not sibling_db:
                continue
            manifest_path = Path(sibling_db).parent / "brain_manifest.json"
            manifest = load_manifest(manifest_path)
            if manifest:
                self._brain_summaries.append({
                    "name": getattr(sibling, "name", "unknown"),
                    "description": getattr(sibling, "description", ""),
                    "total": manifest.get("total_methodologies", 0),
                    "top_categories": sorted(manifest.get("top_categories", {}).keys()),
                    "languages": sorted(manifest.get("language_breakdown", {}).keys()),
                    "source": "ganglion",
                })
                self._total_methodologies += manifest.get("total_methodologies", 0)

        self._loaded = True

    def build_summary_text(self) -> str:
        """Build a deterministic text summary for prompt injection.

        Returns a stable string sorted by brain name for KV cache stability.
        """
        if not self._loaded:
            self.load()
        if not self._brain_summaries:
            return ""

        lines = [
            f"Available Knowledge Sources ({self._total_methodologies} total "
            f"methodologies across {len(self._brain_summaries)} brains):"
        ]
        for brain in sorted(self._brain_summaries, key=lambda b: b["name"]):
            cats = ", ".join(brain["top_categories"][:5]) if brain["top_categories"] else "general"
            langs = ", ".join(brain["languages"][:3]) if brain["languages"] else "multi-language"
            source_label = "[primary]" if brain["source"] == "primary" else "[ganglion]"
            lines.append(
                f"  - {brain['name']} {source_label}: {brain['total']} methodologies"
                f" | Focus: {cats} | Languages: {langs}"
            )
            if brain["description"]:
                lines.append(f"    {brain['description']}")
        return "\n".join(lines)

    def build_brain_list(self) -> str:
        """Build a compact brain list for RLMHT trace system prompts."""
        if not self._loaded:
            self.load()
        names = sorted(b["name"] for b in self._brain_summaries)
        return ", ".join(names) if names else "no brains loaded"

    @property
    def brain_names(self) -> list[str]:
        """Sorted list of brain names."""
        if not self._loaded:
            self.load()
        return sorted(b["name"] for b in self._brain_summaries)

    @property
    def total_methodologies(self) -> int:
        """Grand total of methodologies across all brains."""
        if not self._loaded:
            self.load()
        return self._total_methodologies
