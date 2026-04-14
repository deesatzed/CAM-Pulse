"""Baseline lineage utilities for CAM-SEQ.

M1 intentionally keeps lineage conservative: exact content-hash grouping with
stable family membership. More advanced AST or clone-aware clustering can be
added later without changing the public contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Iterable

from claw.core.models import ComponentCard, ComponentLineage


def _now() -> datetime:
    return datetime.now(UTC)


def canonical_content_hash(card: ComponentCard) -> str:
    """Return the exact-hash key used for M1 lineage grouping."""
    return card.receipt.content_hash


def build_initial_lineage(card: ComponentCard) -> ComponentLineage:
    """Create a new lineage record seeded from a single component card."""
    now = _now()
    return ComponentLineage(
        family_barcode=card.receipt.family_barcode,
        canonical_content_hash=canonical_content_hash(card),
        canonical_title=card.title,
        language=card.language,
        lineage_size=1,
        deduped_support_count=1,
        clone_inflated=False,
        created_at=now,
        updated_at=now,
    )


def merge_component_into_lineage(
    lineage: ComponentLineage,
    card: ComponentCard,
    *,
    distinct_support_increment: int = 1,
) -> ComponentLineage:
    """Update lineage counts after observing another component in the family.

    `distinct_support_increment` should stay at 1 for a new distinct source and
    0 when re-seeing the exact same supporting source.
    """
    if lineage.family_barcode != card.receipt.family_barcode:
        raise ValueError("cannot merge component into lineage with different family barcode")
    if lineage.canonical_content_hash != canonical_content_hash(card):
        raise ValueError("M1 lineage merge requires exact content-hash match")

    lineage.lineage_size += 1
    lineage.deduped_support_count = max(
        1,
        lineage.deduped_support_count + max(distinct_support_increment, 0),
    )
    lineage.clone_inflated = lineage.lineage_size > lineage.deduped_support_count
    lineage.updated_at = _now()
    if not lineage.canonical_title:
        lineage.canonical_title = card.title
    if not lineage.language:
        lineage.language = card.language
    return lineage


def rebuild_lineage_stats(
    lineage: ComponentLineage,
    components: Iterable[ComponentCard],
) -> ComponentLineage:
    """Recompute lineage counts from an explicit component set."""
    items = list(components)
    lineage.lineage_size = len(items)
    lineage.deduped_support_count = len({item.receipt.source_barcode for item in items}) or 1
    lineage.clone_inflated = lineage.lineage_size > lineage.deduped_support_count
    lineage.updated_at = _now()
    if items:
        lineage.canonical_title = lineage.canonical_title or items[0].title
        lineage.language = lineage.language or items[0].language
    return lineage
