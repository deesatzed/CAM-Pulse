"""Tests for the zombie demotion lifecycle rule.

A "zombie" methodology is one that has been retrieved many times but never
actually used in an outcome. The rule transitions such methodologies from
``viable`` to ``declining`` so they stop clogging retrieval slots.

All tests use pure in-memory dataclasses — no database required because the
zombie rule is implemented in the pure-function layer of lifecycle.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from claw.core.models import Methodology
from claw.memory.lifecycle import (
    ZOMBIE_RETRIEVED_MINIMUM,
    _evaluate_attributed_transition,
)


def _make_methodology(
    *,
    lifecycle_state: str = "viable",
    tags: list[str] | None = None,
    scope: str = "project",
) -> Methodology:
    return Methodology(
        id="test-meth",
        problem_description="test",
        solution_code="x",
        tags=tags or [],
        lifecycle_state=lifecycle_state,
        scope=scope,
        created_at=datetime.now(UTC),
    )


def _stats(
    *,
    retrieved: int = 0,
    used: int = 0,
    attributed: int = 0,
    successes: int = 0,
    failures: int = 0,
) -> dict[str, object]:
    return {
        "retrieved_count": retrieved,
        "used_count": used,
        "attributed_count": attributed,
        "attributed_success_count": successes,
        "attributed_failure_count": failures,
    }


class TestZombieDemotion:
    @pytest.mark.asyncio
    async def test_viable_zombie_demotes_to_declining(self):
        """Viable methodology with retrieved>=5 and used=0 should decline."""
        m = _make_methodology()
        stats = _stats(retrieved=ZOMBIE_RETRIEVED_MINIMUM, used=0)
        result = await _evaluate_attributed_transition(m, stats)
        assert result == "declining"

    @pytest.mark.asyncio
    async def test_viable_healthy_stays_viable(self):
        """Retrieved and used together should NOT trigger zombie rule."""
        m = _make_methodology()
        stats = _stats(retrieved=5, used=3, attributed=3, successes=3)
        result = await _evaluate_attributed_transition(m, stats)
        assert result is None

    @pytest.mark.asyncio
    async def test_below_retrieved_threshold_stays_viable(self):
        """Below ZOMBIE_RETRIEVED_MINIMUM, even with used=0, stays viable."""
        m = _make_methodology()
        stats = _stats(retrieved=ZOMBIE_RETRIEVED_MINIMUM - 1, used=0)
        result = await _evaluate_attributed_transition(m, stats)
        assert result is None

    @pytest.mark.asyncio
    async def test_seed_methodology_protected(self):
        """origin:seed methodologies are archetypes and should never be demoted."""
        m = _make_methodology(tags=["origin:seed", "architecture"])
        stats = _stats(retrieved=ZOMBIE_RETRIEVED_MINIMUM * 3, used=0)
        result = await _evaluate_attributed_transition(m, stats)
        assert result is None

    @pytest.mark.asyncio
    async def test_thriving_not_affected_by_zombie_rule(self):
        """The zombie rule only applies to viable; thriving follows other rules."""
        m = _make_methodology(lifecycle_state="thriving")
        stats = _stats(retrieved=ZOMBIE_RETRIEVED_MINIMUM, used=0)
        result = await _evaluate_attributed_transition(m, stats)
        # Thriving stays thriving — high-trust failure rule needs actual attributed failures
        assert result is None

    @pytest.mark.asyncio
    async def test_declining_stays_declining(self):
        """Already-declining methodologies short-circuit out of the rule."""
        m = _make_methodology(lifecycle_state="declining")
        stats = _stats(retrieved=ZOMBIE_RETRIEVED_MINIMUM, used=0)
        result = await _evaluate_attributed_transition(m, stats)
        assert result is None

    @pytest.mark.asyncio
    async def test_zombie_with_attributed_count_not_demoted(self):
        """If attributed_count > 0, even used_count=0 should not trigger zombie.

        (This guards against attribution bookkeeping edge cases where
        attribution fired without a used_in_outcome stage.)
        """
        m = _make_methodology()
        stats = _stats(retrieved=ZOMBIE_RETRIEVED_MINIMUM, used=0, attributed=1)
        result = await _evaluate_attributed_transition(m, stats)
        assert result is None

    @pytest.mark.asyncio
    async def test_dead_methodology_short_circuits(self):
        """Dead methodologies are terminal — no further transitions."""
        m = _make_methodology(lifecycle_state="dead")
        stats = _stats(retrieved=100, used=0)
        result = await _evaluate_attributed_transition(m, stats)
        assert result is None
