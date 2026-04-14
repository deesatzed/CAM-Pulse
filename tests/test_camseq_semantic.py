from __future__ import annotations

from claw.core.models import ComponentCard, CoverageState, Receipt
from claw.memory.hybrid_search import HybridSearch
from claw.memory.semantic import SemanticMemory


class _DeterministicEmbeddings:
    async def async_encode(self, text: str) -> list[float]:
        return [0.1] * 384


async def test_semantic_component_bridge(repository):
    lineage = await repository.upsert_component_lineage(
        __import__("claw.core.models", fromlist=["ComponentLineage"]).ComponentLineage(
            family_barcode="fam_validator",
            canonical_content_hash="sha256:validator1",
            canonical_title="Payload Validator",
            language="python",
        )
    )
    card = ComponentCard(
        methodology_id=None,
        title="Payload Validator",
        component_type="validator",
        abstract_jobs=["validator"],
        receipt=Receipt(
            source_barcode="src_validator_1",
            family_barcode="fam_validator",
            lineage_id=lineage.id,
            repo="org/service",
            file_path="app/validators.py",
            symbol="validate_payload",
            content_hash="sha256:validator1",
            provenance_precision="symbol",
        ),
        language="python",
        applicability=["request validation"],
        coverage_state=CoverageState.COVERED,
    )
    saved = await repository.upsert_component_card(card)

    hybrid = HybridSearch(repository=repository, embedding_engine=_DeterministicEmbeddings())
    semantic = SemanticMemory(
        repository=repository,
        embedding_engine=_DeterministicEmbeddings(),
        hybrid_search=hybrid,
    )

    results = await semantic.search_components("validator", limit=5, language="python")
    assert any(item.id == saved.id for item in results)

    fetched = await semantic.get_component(saved.id)
    assert fetched is not None
    assert fetched.title == "Payload Validator"

    history = await semantic.get_component_history(saved.id)
    assert history["component"].id == saved.id
    assert len(history["lineage_components"]) >= 1
