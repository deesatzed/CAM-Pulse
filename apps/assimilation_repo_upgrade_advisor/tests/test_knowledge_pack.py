from pathlib import Path

from advisor_app.knowledge_pack import load_knowledge_pack, match_knowledge
from advisor_app.models import RepoSignal

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_knowledge_pack_extracts_source_repo_and_scores():
    items = load_knowledge_pack(FIXTURES / "knowledge_pack.jsonl")
    assert len(items) == 4
    assert items[0].source_repo == "fixture-testing"
    assert items[0].potential_score > 0


def test_match_knowledge_returns_ranked_matches():
    items = load_knowledge_pack(FIXTURES / "knowledge_pack.jsonl")
    signal = RepoSignal(
        signal_id="missing-tests",
        category="testing",
        title="Add tests",
        why_now="No tests are present.",
        evidence=["No test files found"],
        improvement="Add tests.",
        first_step="Create tests/.",
        difficulty="medium",
        payoff="high",
        query_terms=["testing", "verification", "workflow"],
    )
    matches = match_knowledge(signal, items)
    assert matches
    assert matches[0].source_repo == "fixture-testing"
