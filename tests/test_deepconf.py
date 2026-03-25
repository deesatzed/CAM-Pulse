"""Tests for deepConf 6-factor scoring and related configuration.

Track B: Validates _extract_capability_data(), DeepConfConfig defaults
and integration, and the full 6-factor _derive_memory_signals() scoring
in HybridSearch.

NO MOCKS. All computations use real values and real Pydantic models.

NOTE: _extract_capability_data() uses getattr() to handle both Pydantic
Methodology instances (dict) and raw DB row objects (JSON string). For the
string-input tests we use Methodology.model_construct() to bypass Pydantic
validation, simulating how DB rows arrive with TEXT capability_data.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from claw.core.config import DeepConfConfig, load_config
from claw.core.models import Methodology
from claw.memory.hybrid_search import (
    HybridSearch,
    HybridSearchResult,
    _extract_capability_data,
)


# ---------------------------------------------------------------------------
# Helper: build a lightweight object with a .capability_data attribute
# that holds a string value (simulating a DB row or unvalidated object).
# This is what _extract_capability_data() handles via getattr().
# ---------------------------------------------------------------------------

def _raw_methodology(cap_data_value):
    """Create a SimpleNamespace with capability_data set to any value.

    This simulates the raw DB row objects that _extract_capability_data()
    handles via getattr(). The function never calls Pydantic validation,
    so string values are valid here.
    """
    return SimpleNamespace(capability_data=cap_data_value)


# ---------------------------------------------------------------------------
# TestExtractCapabilityData
# ---------------------------------------------------------------------------

class TestExtractCapabilityData:
    """Tests for _extract_capability_data() safe JSON extraction."""

    def test_dict_input(self):
        m = Methodology(
            problem_description="test",
            solution_code="code",
            capability_data={"enrichment_status": "enriched"},
        )
        result = _extract_capability_data(m)
        assert result == {"enrichment_status": "enriched"}

    def test_json_string_input(self):
        """JSON string with a dict deserializes correctly (DB row scenario)."""
        obj = _raw_methodology(json.dumps({"source_repos": ["a", "b"]}))
        result = _extract_capability_data(obj)
        assert result["source_repos"] == ["a", "b"]

    def test_none_input(self):
        m = Methodology(
            problem_description="test",
            solution_code="code",
            capability_data=None,
        )
        result = _extract_capability_data(m)
        assert result == {}

    def test_empty_string(self):
        """Empty string from DB returns empty dict."""
        obj = _raw_methodology("")
        result = _extract_capability_data(obj)
        assert result == {}

    def test_null_string(self):
        """The literal string 'null' from DB returns empty dict."""
        obj = _raw_methodology("null")
        result = _extract_capability_data(obj)
        assert result == {}

    def test_invalid_json(self):
        """Non-JSON string from DB returns empty dict without raising."""
        obj = _raw_methodology("not json at all")
        result = _extract_capability_data(obj)
        assert result == {}

    def test_json_array_returns_empty(self):
        """A JSON array is not a dict, so it should return empty."""
        obj = _raw_methodology('["a", "b"]')
        result = _extract_capability_data(obj)
        assert result == {}

    def test_complex_capability_data(self):
        """Full CapabilityData-shaped dict extracts correctly."""
        cap = {
            "enrichment_status": "enriched",
            "source_repos": ["repo1", "repo2", "repo3"],
            "domain": ["ml", "nlp"],
            "schema_version": 2,
        }
        m = Methodology(
            problem_description="test",
            solution_code="code",
            capability_data=cap,
        )
        result = _extract_capability_data(m)
        assert result["enrichment_status"] == "enriched"
        assert len(result["source_repos"]) == 3
        assert result["schema_version"] == 2

    def test_missing_attribute_returns_empty(self):
        """Object with no capability_data attribute returns empty dict."""
        obj = SimpleNamespace()
        result = _extract_capability_data(obj)
        assert result == {}

    def test_json_string_nested_dict(self):
        """Nested JSON dict from DB deserializes correctly."""
        nested = json.dumps({
            "enrichment_status": "enriched",
            "source_repos": ["x"],
            "composability": {"standalone": True, "can_chain_after": ["ml"]},
        })
        obj = _raw_methodology(nested)
        result = _extract_capability_data(obj)
        assert result["composability"]["standalone"] is True


# ---------------------------------------------------------------------------
# TestDeepConfConfig
# ---------------------------------------------------------------------------

class TestDeepConfConfig:
    """Tests for DeepConfConfig Pydantic model and its integration."""

    def test_defaults(self):
        cfg = DeepConfConfig()
        assert cfg.retrieval_weight == 0.25
        assert cfg.authority_weight == 0.20
        assert cfg.accuracy_weight == 0.20
        assert cfg.novelty_weight == 0.10
        assert cfg.provenance_weight == 0.10
        assert cfg.verification_weight == 0.15
        assert cfg.min_critical_threshold == 0.15

    def test_weights_sum_to_one(self):
        cfg = DeepConfConfig()
        total = (
            cfg.retrieval_weight
            + cfg.authority_weight
            + cfg.accuracy_weight
            + cfg.novelty_weight
            + cfg.provenance_weight
            + cfg.verification_weight
        )
        assert abs(total - 1.0) < 0.001

    def test_custom_values(self):
        cfg = DeepConfConfig(retrieval_weight=0.4, authority_weight=0.3)
        assert cfg.retrieval_weight == 0.4
        assert cfg.authority_weight == 0.3
        # Others remain at defaults
        assert cfg.accuracy_weight == 0.20
        assert cfg.novelty_weight == 0.10

    def test_in_claw_config(self):
        config = load_config()
        assert hasattr(config, "deep_conf")
        assert isinstance(config.deep_conf, DeepConfConfig)

    def test_serialization_roundtrip(self):
        cfg = DeepConfConfig(retrieval_weight=0.5, min_critical_threshold=0.20)
        dumped = cfg.model_dump()
        restored = DeepConfConfig(**dumped)
        assert restored.retrieval_weight == 0.5
        assert restored.min_critical_threshold == 0.20


# ---------------------------------------------------------------------------
# TestDeepConfScoring
# ---------------------------------------------------------------------------

class TestDeepConfScoring:
    """Tests for the 6-factor _derive_memory_signals() scoring math.

    Uses HybridSearch.__new__() to create a minimal instance with only
    the _deep_conf attribute set. This avoids needing a full database
    and embedding engine, while exercising the real scoring logic.
    """

    def _make_search(self, deep_conf=None):
        """Create a minimal HybridSearch for testing _derive_memory_signals."""
        hs = HybridSearch.__new__(HybridSearch)
        hs._deep_conf = deep_conf
        return hs

    def _make_result(
        self,
        lifecycle="viable",
        success=0,
        failure=0,
        novelty=None,
        cap_data=None,
        vector_score=0.8,
        text_score=0.7,
        source="hybrid",
    ):
        m = Methodology(
            problem_description="test problem",
            solution_code="def solve(): pass",
            lifecycle_state=lifecycle,
            success_count=success,
            failure_count=failure,
            novelty_score=novelty,
            capability_data=cap_data,
        )
        return HybridSearchResult(
            methodology=m,
            vector_score=vector_score,
            text_score=text_score,
            source=source,
        )

    def test_viable_untested_default(self):
        """Viable, untested methodology with good retrieval scores -- moderate confidence."""
        hs = self._make_search()
        r = self._make_result()
        conf, conflict = hs._derive_memory_signals(r)
        assert 0.3 < conf < 0.7
        assert conflict < 0.5

    def test_thriving_proven_high_confidence(self):
        """Thriving methodology with high success rate should score high."""
        hs = self._make_search()
        r = self._make_result(
            lifecycle="thriving",
            success=10,
            failure=0,
            novelty=0.8,
            cap_data={"enrichment_status": "enriched", "source_repos": ["a", "b", "c"]},
        )
        conf, _ = hs._derive_memory_signals(r)
        assert conf > 0.8

    def test_dead_methodology_suppressed(self):
        """Dead methodology should have very low confidence via min-critical gating."""
        hs = self._make_search()
        r = self._make_result(lifecycle="dead")
        conf, _ = hs._derive_memory_signals(r)
        assert conf < 0.3  # Suppressed: source_authority=0.0 triggers halving

    def test_declining_lower_than_viable(self):
        """Declining lifecycle scores lower than viable, all else equal."""
        hs = self._make_search()
        r_viable = self._make_result(lifecycle="viable")
        r_declining = self._make_result(lifecycle="declining")
        conf_v, _ = hs._derive_memory_signals(r_viable)
        conf_d, _ = hs._derive_memory_signals(r_declining)
        assert conf_v > conf_d

    def test_high_failure_rate_lowers_confidence(self):
        """High failure count produces lower confidence than high success count."""
        hs = self._make_search()
        r_good = self._make_result(success=9, failure=1)
        r_bad = self._make_result(success=1, failure=9)
        conf_good, _ = hs._derive_memory_signals(r_good)
        conf_bad, _ = hs._derive_memory_signals(r_bad)
        assert conf_good > conf_bad

    def test_more_sources_higher_provenance(self):
        """Three source repos produce higher confidence than one."""
        hs = self._make_search()
        r_one = self._make_result(cap_data={"source_repos": ["a"]})
        r_three = self._make_result(cap_data={"source_repos": ["a", "b", "c"]})
        conf_one, _ = hs._derive_memory_signals(r_one)
        conf_three, _ = hs._derive_memory_signals(r_three)
        assert conf_three > conf_one

    def test_enriched_beats_seeded(self):
        """Enriched enrichment_status scores higher than seeded."""
        hs = self._make_search()
        r_enriched = self._make_result(cap_data={"enrichment_status": "enriched"})
        r_seeded = self._make_result(cap_data={"enrichment_status": "seeded"})
        conf_e, _ = hs._derive_memory_signals(r_enriched)
        conf_s, _ = hs._derive_memory_signals(r_seeded)
        assert conf_e > conf_s

    def test_conflict_from_score_disagreement(self):
        """Large gap between vector and text scores produces high conflict."""
        hs = self._make_search()
        r = self._make_result(vector_score=0.9, text_score=0.1, source="hybrid")
        _, conflict = hs._derive_memory_signals(r)
        assert conflict > 0.5

    def test_no_conflict_for_non_hybrid(self):
        """Non-hybrid (vector-only or text-only) sources report zero conflict."""
        hs = self._make_search()
        r = self._make_result(source="vector")
        _, conflict = hs._derive_memory_signals(r)
        assert conflict == 0.0

    def test_no_conflict_for_text_only(self):
        """Text-only source also reports zero conflict."""
        hs = self._make_search()
        r = self._make_result(source="text", vector_score=0.0, text_score=0.9)
        _, conflict = hs._derive_memory_signals(r)
        assert conflict == 0.0

    def test_custom_config_weights(self):
        """Custom weights change the scoring -- heavy retrieval weight."""
        cfg_heavy_retrieval = DeepConfConfig(
            retrieval_weight=0.90,
            authority_weight=0.02,
            accuracy_weight=0.02,
            novelty_weight=0.02,
            provenance_weight=0.02,
            verification_weight=0.02,
        )
        hs = self._make_search(deep_conf=cfg_heavy_retrieval)
        r = self._make_result(vector_score=0.95, text_score=0.95, source="hybrid")
        conf, _ = hs._derive_memory_signals(r)
        # With 90% weight on retrieval and perfect scores, confidence is very high
        assert conf > 0.85

    def test_confidence_bounded_0_to_1(self):
        """Confidence and conflict always stay in [0.0, 1.0] across all inputs."""
        hs = self._make_search()
        for lc in ["thriving", "viable", "embryonic", "declining", "dormant", "dead"]:
            for s, f in [(10, 0), (0, 10), (0, 0), (5, 5)]:
                r = self._make_result(lifecycle=lc, success=s, failure=f)
                conf, conflict = hs._derive_memory_signals(r)
                assert 0.0 <= conf <= 1.0, (
                    f"confidence {conf} out of bounds for {lc} s={s} f={f}"
                )
                assert 0.0 <= conflict <= 1.0, (
                    f"conflict {conflict} out of bounds for {lc} s={s} f={f}"
                )

    def test_embryonic_lower_than_thriving(self):
        """Embryonic lifecycle is lower confidence than thriving."""
        hs = self._make_search()
        r_emb = self._make_result(lifecycle="embryonic")
        r_thr = self._make_result(lifecycle="thriving")
        conf_emb, _ = hs._derive_memory_signals(r_emb)
        conf_thr, _ = hs._derive_memory_signals(r_thr)
        assert conf_thr > conf_emb

    def test_dormant_lower_than_declining(self):
        """Dormant lifecycle is lower confidence than declining."""
        hs = self._make_search()
        r_dormant = self._make_result(lifecycle="dormant")
        r_declining = self._make_result(lifecycle="declining")
        conf_dormant, _ = hs._derive_memory_signals(r_dormant)
        conf_declining, _ = hs._derive_memory_signals(r_declining)
        assert conf_declining > conf_dormant

    def test_novelty_score_affects_confidence(self):
        """Higher novelty score produces higher confidence (via novelty factor)."""
        hs = self._make_search()
        r_low = self._make_result(novelty=0.1)
        r_high = self._make_result(novelty=0.9)
        conf_low, _ = hs._derive_memory_signals(r_low)
        conf_high, _ = hs._derive_memory_signals(r_high)
        assert conf_high > conf_low

    def test_zero_scores_still_produces_valid_confidence(self):
        """Zero vector and text scores still produce a valid confidence."""
        hs = self._make_search()
        r = self._make_result(vector_score=0.0, text_score=0.0, source="vector")
        conf, conflict = hs._derive_memory_signals(r)
        assert 0.0 <= conf <= 1.0
        assert conflict == 0.0

    def test_perfect_hybrid_agreement(self):
        """Identical vector and text scores produce zero conflict."""
        hs = self._make_search()
        r = self._make_result(vector_score=0.85, text_score=0.85, source="hybrid")
        _, conflict = hs._derive_memory_signals(r)
        assert conflict == 0.0

    def test_merged_status_verification(self):
        """Merged enrichment_status scores higher than partial."""
        hs = self._make_search()
        r_merged = self._make_result(cap_data={"enrichment_status": "merged"})
        r_partial = self._make_result(cap_data={"enrichment_status": "partial"})
        conf_m, _ = hs._derive_memory_signals(r_merged)
        conf_p, _ = hs._derive_memory_signals(r_partial)
        assert conf_m > conf_p

    def test_half_success_half_failure_neutral(self):
        """Equal success and failure counts produce historical_accuracy=0.5 (neutral)."""
        hs = self._make_search()
        r_neutral = self._make_result(success=5, failure=5)
        r_untested = self._make_result(success=0, failure=0)
        conf_neutral, _ = hs._derive_memory_signals(r_neutral)
        conf_untested, _ = hs._derive_memory_signals(r_untested)
        # Neutral (0.5) == untested (0.5 default), so confidences should be very close
        assert abs(conf_neutral - conf_untested) < 0.01


# ---------------------------------------------------------------------------
# TestSeedExistingRepos
# ---------------------------------------------------------------------------

class TestSeedExistingRepos:
    """Tests for FreshnessMonitor.seed_existing_repos() database logic."""

    @pytest.fixture
    async def pulse_engine(self):
        from claw.core.config import DatabaseConfig
        from claw.db.engine import DatabaseEngine

        config = DatabaseConfig(db_path=":memory:")
        engine = DatabaseEngine(config)
        await engine.connect()
        await engine.apply_migrations()
        await engine.initialize_schema()
        yield engine
        await engine.close()

    async def test_seed_empty_db_returns_zero(self, pulse_engine):
        from claw.pulse.freshness import FreshnessMonitor

        config = load_config()
        monitor = FreshnessMonitor(pulse_engine, config)
        result = await monitor.seed_existing_repos()
        assert result == 0

    async def test_seed_skips_already_seeded(self, pulse_engine):
        from claw.pulse.freshness import FreshnessMonitor

        await pulse_engine.execute(
            """INSERT INTO pulse_discoveries
               (id, github_url, canonical_url, status, head_sha_at_mine, source_kind)
               VALUES ('d1', 'https://github.com/test/repo',
                        'https://github.com/test/repo', 'assimilated', 'abc123', 'github')"""
        )

        config = load_config()
        monitor = FreshnessMonitor(pulse_engine, config)
        result = await monitor.seed_existing_repos()
        assert result == 0  # Already has head_sha, should skip
