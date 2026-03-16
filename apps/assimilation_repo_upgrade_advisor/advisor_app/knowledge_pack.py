"""Knowledge pack loading and matching helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import KnowledgeItem, KnowledgeMatch, RepoSignal

_WORD_RE = re.compile(r"[a-z0-9_+-]+")
_STOPWORDS = {"a", "an", "and", "are", "as", "be", "by", "for", "from", "in", "is", "it", "its", "lacks", "making", "now", "of", "on", "or", "repo", "repository", "so", "that", "the", "their", "there", "this", "to", "with"}


def _tokenize(text: str) -> set[str]:
    return {token for token in _WORD_RE.findall(text.lower()) if len(token) > 2 and token not in _STOPWORDS}


def _source_repo(metadata: dict, tags: list[str]) -> str:
    if metadata.get("source_repo"):
        return str(metadata["source_repo"])
    for tag in tags:
        if tag.startswith("source:"):
            return tag.split(":", 1)[1]
    return "unknown"


def load_knowledge_pack(path: Path) -> list[KnowledgeItem]:
    items: list[KnowledgeItem] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        obj = json.loads(line)
        metadata = obj.get("metadata", {})
        tags = [str(tag) for tag in metadata.get("tags", [])]
        items.append(
            KnowledgeItem(
                item_id=str(obj.get("id", "")),
                title=str(obj.get("title", "")),
                text=str(obj.get("text", "")),
                modality=str(obj.get("modality", "")),
                source=str(obj.get("source", "")),
                source_repo=_source_repo(metadata, tags),
                tags=tags,
                task_type=metadata.get("task_type"),
                potential_score=float(metadata.get("potential_score") or 0.0),
                novelty_score=float(metadata.get("novelty_score") or 0.0),
            )
        )
    return items


def match_knowledge(signal: RepoSignal, items: list[KnowledgeItem], limit: int = 3) -> list[KnowledgeMatch]:
    signal_tokens = _tokenize(" ".join(signal.query_terms + [signal.category, signal.title, signal.why_now]))
    results: list[KnowledgeMatch] = []
    for item in items:
        if item.source_repo == "unknown":
            continue
        corpus = " ".join([item.title, item.text, item.source_repo, " ".join(item.tags), item.task_type or ""])
        item_tokens = _tokenize(corpus)
        overlap = signal_tokens & item_tokens
        if not overlap:
            continue
        category_bonus = 0.15 if f"category:{signal.category}" in item.tags else 0.0
        task_bonus = 0.1 if item.task_type == signal.category else 0.0
        relevance = min(1.0, len(overlap) / max(4.0, len(signal_tokens) * 0.5))
        score = relevance + category_bonus + task_bonus + (item.potential_score * 0.35) + (item.novelty_score * 0.15)
        rationale = ", ".join(sorted(list(overlap))[:5])
        results.append(
            KnowledgeMatch(
                item_id=item.item_id,
                title=item.title,
                source_repo=item.source_repo,
                score=round(score, 3),
                rationale=rationale,
            )
        )
    results.sort(key=lambda m: m.score, reverse=True)
    return results[:limit]
