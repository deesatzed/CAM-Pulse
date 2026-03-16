"""Recommendation synthesis."""

from __future__ import annotations

from .knowledge_pack import match_knowledge
from .models import KnowledgeItem, Recommendation, RepoSignal


def build_recommendations(signals: list[RepoSignal], items: list[KnowledgeItem], limit: int = 5) -> list[Recommendation]:
    recommendations: list[Recommendation] = []
    for signal in signals:
        provenance = match_knowledge(signal, items, limit=3)
        if not provenance:
            continue
        confidence = min(0.99, round((sum(match.score for match in provenance) / len(provenance)) / 1.6, 3))
        recommendations.append(
            Recommendation(
                title=signal.title,
                category=signal.category,
                why_now=signal.why_now,
                evidence=signal.evidence,
                recommended_change=signal.improvement,
                first_step=signal.first_step,
                difficulty=signal.difficulty,
                payoff=signal.payoff,
                confidence=confidence,
                provenance=provenance,
            )
        )
    recommendations.sort(key=lambda rec: (rec.confidence, 1 if rec.payoff == "high" else 0), reverse=True)
    return recommendations[:limit]
