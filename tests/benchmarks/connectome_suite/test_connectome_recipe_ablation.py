from __future__ import annotations

import pytest

from tests.benchmarks.connectome_suite.connectome_recipe_ablation import run_connectome_recipe_ablation


@pytest.mark.asyncio
async def test_connectome_recipe_ablation_executes():
    result = await run_connectome_recipe_ablation()
    assert result["baseline_selected"]
    assert result["learned_selected"]
    assert result["recipe_selected"]


@pytest.mark.asyncio
async def test_connectome_recipe_ablation_shows_learning_and_recipe_effects():
    result = await run_connectome_recipe_ablation()
    assert result["baseline_selected"] == "comp_transfer"
    assert result["learned_selected"] == "comp_direct"
    assert result["recipe_selected"] == "comp_direct"
    assert result["recipe_active"] is True
    assert result["recipe_sample_size"] == 3
    assert "recipe_family_preference" in result["recipe_confidence_basis"]
