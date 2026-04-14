from __future__ import annotations

from claw.core.models import CompiledRecipe, ComponentCard, CoverageState, GovernancePolicy, Receipt, SlotRisk, SlotSpec
from claw.memory.component_ranker import rank_components_for_slot


def _card(*, title: str, component_type: str, abstract_jobs: list[str], language: str = "python", non_applicability: list[str] | None = None):
    return ComponentCard(
        title=title,
        component_type=component_type,
        abstract_jobs=abstract_jobs,
        receipt=Receipt(
            source_barcode=f"src_{title}",
            family_barcode=f"fam_{component_type}",
            lineage_id="lin_1",
            repo="org/service",
            file_path="app/file.py",
            symbol=title,
            content_hash=f"sha256:{title}",
            provenance_precision="symbol",
        ),
        language=language,
        applicability=[title],
        non_applicability=non_applicability or [],
        test_evidence=["tests/test_file.py"],
        coverage_state=CoverageState.COVERED,
    )


def test_ranker_prefers_direct_fit():
    slot = SlotSpec(
        slot_id="slot_refresh",
        slot_barcode="slot_refresh_bc",
        name="token_refresh",
        abstract_job="token_refresh_serialization",
        risk=SlotRisk.CRITICAL,
        constraints=["async"],
        target_stack=["python", "httpx"],
        proof_expectations=["tests"],
    )
    direct = _card(title="refresh_session", component_type="api_client", abstract_jobs=["token_refresh_serialization"])
    weak = _card(title="parse_csv", component_type="parser", abstract_jobs=["parser_transform"])
    ranked = rank_components_for_slot(slot, [weak, direct], target_language="python")
    assert ranked[0].component_id == direct.id
    assert ranked[0].fit_bucket.value in {"will_help", "may_help"}


def test_ranker_penalizes_constraint_conflict():
    slot = SlotSpec(
        slot_id="slot_retry",
        slot_barcode="slot_retry_bc",
        name="retry_logic",
        abstract_job="retry_with_backoff",
        risk=SlotRisk.NORMAL,
        constraints=["async"],
        target_stack=["python"],
        proof_expectations=["tests"],
    )
    conflicting = _card(
        title="sync_retry",
        component_type="helper",
        abstract_jobs=["retry_with_backoff"],
        non_applicability=["async"],
    )
    ranked = rank_components_for_slot(slot, [conflicting], target_language="python")
    assert ranked[0].fit_bucket.value in {"stretch", "no_help", "may_help"}
    assert ranked[0].known_failure_modes


def test_ranker_penalizes_active_family_policy():
    slot = SlotSpec(
        slot_id="slot_refresh",
        slot_barcode="slot_refresh_bc",
        name="token_refresh",
        abstract_job="token_refresh_serialization",
        risk=SlotRisk.CRITICAL,
        constraints=["async"],
        target_stack=["python", "httpx"],
        proof_expectations=["tests"],
    )
    governed = _card(title="refresh_session", component_type="api_client", abstract_jobs=["token_refresh_serialization"])
    governed.receipt.family_barcode = "fam_governed"
    ungoverned = _card(title="refresh_session_alt", component_type="api_client", abstract_jobs=["token_refresh_serialization"])
    policy = GovernancePolicy(
        task_archetype="oauth_session_management",
        family_barcode="fam_governed",
        policy_kind="family_policy",
        severity="high",
        reason="repeated async failures",
        recommendation="quarantine family",
    )
    ranked = rank_components_for_slot(
        slot,
        [governed, ungoverned],
        target_language="python",
        governance_policies=[policy],
    )
    assert ranked[0].component_id == ungoverned.id
    assert any("governance_family_policy" == basis for basis in ranked[1].confidence_basis)


def test_ranker_prefers_active_recipe_family():
    slot = SlotSpec(
        slot_id="slot_refresh",
        slot_barcode="slot_refresh_bc",
        name="token_refresh",
        abstract_job="token_refresh_serialization",
        risk=SlotRisk.CRITICAL,
        constraints=["async"],
        target_stack=["python", "httpx"],
        proof_expectations=["tests"],
    )
    recipe_fit = _card(title="refresh_session_recipe", component_type="helper", abstract_jobs=["authenticated_api_client"])
    recipe_fit.receipt.family_barcode = "fam_recipe"
    directish = _card(title="refresh_session_direct", component_type="helper", abstract_jobs=["authenticated_api_client"])
    directish.receipt.family_barcode = "fam_other"
    recipe = CompiledRecipe(
        task_archetype="oauth_session_management",
        recipe_name="oauth_recipe",
        recipe_json={
            "slot_order": ["token_refresh", "tests"],
            "preferred_families": ["fam_recipe"],
        },
        sample_size=5,
        is_active=True,
    )
    ranked = rank_components_for_slot(
        slot,
        [directish, recipe_fit],
        target_language="python",
        compiled_recipes=[recipe],
    )
    assert ranked[0].component_id == recipe_fit.id
    assert "recipe_family_preference" in ranked[0].confidence_basis
