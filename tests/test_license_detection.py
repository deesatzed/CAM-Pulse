"""Tests for license-aware mining (Phase A).

Covers:
- _detect_license() classification for all license families
- Migration 13 idempotency
- License metadata flow into pulse_discoveries and capability_data
- Miner _seed_capability_data_from_finding() license_type propagation
"""

from __future__ import annotations

import asyncio
import textwrap
from pathlib import Path

import pytest

from claw.pulse.assimilator import PulseAssimilator


# ---------------------------------------------------------------------------
# License text fixtures
# ---------------------------------------------------------------------------

MIT_LICENSE = textwrap.dedent("""\
    MIT License

    Copyright (c) 2026 Example Corp

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in
    all copies or substantial portions of the Software.
""")

APACHE_LICENSE = textwrap.dedent("""\
                                 Apache License
                           Version 2.0, January 2004
                        http://www.apache.org/licenses/

    TERMS AND CONDITIONS FOR USE, REPRODUCTION, AND DISTRIBUTION
    ...
""")

GPL3_LICENSE = textwrap.dedent("""\
                        GNU GENERAL PUBLIC LICENSE
                           Version 3, 29 June 2007

     Copyright (C) 2007 Free Software Foundation, Inc. <http://fsf.org/>
     Everyone is permitted to copy and distribute verbatim copies
     of this license document, but changing it is not allowed.
""")

AGPL_LICENSE = textwrap.dedent("""\
                        GNU AFFERO GENERAL PUBLIC LICENSE
                           Version 3, 19 November 2007

     Copyright (C) 2007 Free Software Foundation, Inc. <http://fsf.org/>
""")

BSD3_LICENSE = textwrap.dedent("""\
    BSD 3-Clause License

    Copyright (c) 2026, Example Corp.
    All rights reserved.

    Redistribution and use in source and binary forms, with or without
    modification, are permitted provided that the following conditions are met:
    ...
""")

ISC_LICENSE = textwrap.dedent("""\
    ISC License

    Copyright (c) 2026, Example Corp.

    Permission to use, copy, modify, and/or distribute this software for any
    purpose with or without fee is hereby granted, provided that the above
    copyright notice and this permission notice appear in all copies.
""")

UNKNOWN_LICENSE = textwrap.dedent("""\
    Custom Proprietary License Agreement

    This software is the property of MegaCorp Inc. You may not use, copy,
    or distribute without written permission from the legal department.
""")

MPL_LICENSE = textwrap.dedent("""\
    Mozilla Public License Version 2.0

    1. Definitions
""")


# ---------------------------------------------------------------------------
# Permissive license tests
# ---------------------------------------------------------------------------

class TestDetectLicense:
    """Unit tests for PulseAssimilator._detect_license()."""

    def test_detect_mit_license(self, tmp_path: Path) -> None:
        (tmp_path / "LICENSE").write_text(MIT_LICENSE)
        assert PulseAssimilator._detect_license(tmp_path) == "permissive"

    def test_detect_apache_license(self, tmp_path: Path) -> None:
        (tmp_path / "LICENSE").write_text(APACHE_LICENSE)
        assert PulseAssimilator._detect_license(tmp_path) == "permissive"

    def test_detect_bsd3_license(self, tmp_path: Path) -> None:
        (tmp_path / "LICENSE").write_text(BSD3_LICENSE)
        assert PulseAssimilator._detect_license(tmp_path) == "permissive"

    def test_detect_isc_license(self, tmp_path: Path) -> None:
        (tmp_path / "LICENSE").write_text(ISC_LICENSE)
        assert PulseAssimilator._detect_license(tmp_path) == "permissive"

    def test_detect_gpl3_license(self, tmp_path: Path) -> None:
        (tmp_path / "LICENSE").write_text(GPL3_LICENSE)
        assert PulseAssimilator._detect_license(tmp_path) == "copyleft"

    def test_detect_agpl_license(self, tmp_path: Path) -> None:
        (tmp_path / "LICENSE").write_text(AGPL_LICENSE)
        assert PulseAssimilator._detect_license(tmp_path) == "copyleft"

    def test_detect_mpl_license(self, tmp_path: Path) -> None:
        (tmp_path / "LICENSE").write_text(MPL_LICENSE)
        assert PulseAssimilator._detect_license(tmp_path) == "copyleft"

    def test_detect_no_license_file(self, tmp_path: Path) -> None:
        assert PulseAssimilator._detect_license(tmp_path) == "none"

    def test_detect_unknown_license(self, tmp_path: Path) -> None:
        (tmp_path / "LICENSE").write_text(UNKNOWN_LICENSE)
        assert PulseAssimilator._detect_license(tmp_path) == "unknown"

    def test_detect_license_md_variant(self, tmp_path: Path) -> None:
        """LICENSE.md is found when LICENSE does not exist."""
        (tmp_path / "LICENSE.md").write_text(MIT_LICENSE)
        assert PulseAssimilator._detect_license(tmp_path) == "permissive"

    def test_detect_licence_uk_spelling(self, tmp_path: Path) -> None:
        """LICENCE (UK spelling) is also checked."""
        (tmp_path / "LICENCE").write_text(MIT_LICENSE)
        assert PulseAssimilator._detect_license(tmp_path) == "permissive"

    def test_detect_copying_file(self, tmp_path: Path) -> None:
        """COPYING is used by GPL projects."""
        (tmp_path / "COPYING").write_text(GPL3_LICENSE)
        assert PulseAssimilator._detect_license(tmp_path) == "copyleft"

    def test_detect_license_apache_suffix(self, tmp_path: Path) -> None:
        """LICENSE-APACHE file (used by Rust crates)."""
        (tmp_path / "LICENSE-APACHE").write_text(APACHE_LICENSE)
        assert PulseAssimilator._detect_license(tmp_path) == "permissive"

    def test_detect_license_mit_suffix(self, tmp_path: Path) -> None:
        """LICENSE-MIT file (used by Rust crates)."""
        (tmp_path / "LICENSE-MIT").write_text(MIT_LICENSE)
        assert PulseAssimilator._detect_license(tmp_path) == "permissive"

    def test_unreadable_license_returns_none(self, tmp_path: Path) -> None:
        """If the LICENSE file cannot be read, return 'none'."""
        license_dir = tmp_path / "LICENSE"
        license_dir.mkdir()  # Directory, not a file
        assert PulseAssimilator._detect_license(tmp_path) == "none"

    def test_empty_license_file(self, tmp_path: Path) -> None:
        """Empty LICENSE file is treated as unknown."""
        (tmp_path / "LICENSE").write_text("")
        # Empty string is falsy -> returns "none"
        assert PulseAssimilator._detect_license(tmp_path) == "none"

    def test_license_priority_first_match_wins(self, tmp_path: Path) -> None:
        """When multiple license files exist, first match in priority order wins."""
        (tmp_path / "LICENSE").write_text(MIT_LICENSE)
        (tmp_path / "COPYING").write_text(GPL3_LICENSE)
        # LICENSE is checked before COPYING
        assert PulseAssimilator._detect_license(tmp_path) == "permissive"


# ---------------------------------------------------------------------------
# Migration 13 tests
# ---------------------------------------------------------------------------

class TestMigration13:
    """Tests for the license_type column migration."""

    @pytest.fixture
    def db_engine(self):
        """Create an in-memory DatabaseEngine for testing."""
        from claw.core.config import DatabaseConfig
        from claw.db.engine import DatabaseEngine

        config = DatabaseConfig(db_path=":memory:")
        engine = DatabaseEngine(config)
        return engine

    def test_migration_13_adds_license_type_column(self, db_engine) -> None:
        async def _run():
            await db_engine.connect()
            await db_engine.apply_migrations()
            await db_engine.initialize_schema()

            cols = await db_engine.fetch_all(
                "SELECT name FROM pragma_table_info('pulse_discoveries')"
            )
            col_names = {r["name"] for r in cols}
            assert "license_type" in col_names
            await db_engine.close()

        asyncio.run(_run())

    def test_migration_13_idempotent(self, db_engine) -> None:
        """Running migrations twice should not raise."""
        async def _run():
            await db_engine.connect()
            await db_engine.apply_migrations()
            await db_engine.initialize_schema()
            # Run again -- should be silent
            await db_engine.apply_migrations()
            await db_engine.initialize_schema()

            cols = await db_engine.fetch_all(
                "SELECT name FROM pragma_table_info('pulse_discoveries')"
            )
            col_names = {r["name"] for r in cols}
            assert "license_type" in col_names
            await db_engine.close()

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Model field tests
# ---------------------------------------------------------------------------

class TestModelFields:
    """Verify license_type field on data models."""

    def test_pulse_discovery_has_license_type(self) -> None:
        from claw.pulse.models import PulseDiscovery

        d = PulseDiscovery(
            github_url="https://github.com/x/y",
            canonical_url="https://github.com/x/y",
            license_type="permissive",
        )
        assert d.license_type == "permissive"

    def test_pulse_discovery_license_type_defaults_empty(self) -> None:
        from claw.pulse.models import PulseDiscovery

        d = PulseDiscovery(
            github_url="https://github.com/x/y",
            canonical_url="https://github.com/x/y",
        )
        assert d.license_type == ""

    def test_assimilation_result_has_license_type(self) -> None:
        from claw.pulse.models import AssimilationResult, PulseDiscovery

        d = PulseDiscovery(
            github_url="https://github.com/x/y",
            canonical_url="https://github.com/x/y",
        )
        r = AssimilationResult(discovery=d, license_type="copyleft")
        assert r.license_type == "copyleft"


# ---------------------------------------------------------------------------
# SQL round-trip test
# ---------------------------------------------------------------------------

class TestLicenseStorageRoundTrip:
    """Verify license_type survives write -> read in pulse_discoveries."""

    def test_license_type_stored_and_retrieved(self) -> None:
        import uuid
        from claw.core.config import DatabaseConfig
        from claw.db.engine import DatabaseEngine

        async def _run():
            config = DatabaseConfig(db_path=":memory:")
            engine = DatabaseEngine(config)
            await engine.connect()
            await engine.apply_migrations()
            await engine.initialize_schema()

            disc_id = str(uuid.uuid4())
            await engine.execute(
                """INSERT INTO pulse_discoveries
                   (id, github_url, canonical_url, status, license_type)
                   VALUES (?, ?, ?, 'assimilated', ?)""",
                [disc_id, "https://github.com/x/y", "https://github.com/x/y", "permissive"],
            )

            rows = await engine.fetch_all(
                "SELECT license_type FROM pulse_discoveries WHERE id = ?",
                [disc_id],
            )
            assert len(rows) == 1
            assert rows[0]["license_type"] == "permissive"
            await engine.close()

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# Miner capability_data license propagation
# ---------------------------------------------------------------------------

class TestMinerLicensePropagation:
    """Verify RepoMiner._seed_capability_data_from_finding() includes license_type.

    The _seed_capability_data_from_finding method at miner.py:861 reads
    license_type from self._current_mine_metadata (set by the assimilator
    before mining). This test verifies the full propagation chain using
    a real RepoMiner instance with real dependencies.
    """

    def test_license_in_methodology_capability_data(self) -> None:
        """Setting _current_mine_metadata on RepoMiner propagates license_type
        into the capability_data dict produced by _seed_capability_data_from_finding().
        """
        from claw.core.config import DatabaseConfig, load_config
        from claw.db.embeddings import EmbeddingEngine
        from claw.db.engine import DatabaseEngine
        from claw.db.repository import Repository
        from claw.llm.client import LLMClient
        from claw.memory.hybrid_search import HybridSearch
        from claw.memory.semantic import SemanticMemory
        from claw.miner import MiningFinding, RepoMiner

        config = load_config()
        db_config = DatabaseConfig(db_path=":memory:")
        embedding_engine = EmbeddingEngine()

        # Build a real RepoMiner with real dependencies.
        # _seed_capability_data_from_finding is a sync method that only reads
        # self._current_mine_metadata and the finding fields -- no network or
        # DB calls are made, but the constructor requires these objects.
        async def _build_and_test():
            engine = DatabaseEngine(db_config)
            await engine.connect()
            repo = Repository(engine)
            llm_client = LLMClient(config.llm)
            hybrid_search = HybridSearch(repo, embedding_engine)
            semantic_memory = SemanticMemory(repo, embedding_engine, hybrid_search)
            miner = RepoMiner(repo, llm_client, semantic_memory, config)

            try:
                # Simulate what the assimilator sets before mining a repo
                miner._current_mine_metadata = {"license_type": "permissive"}

                finding = MiningFinding(
                    title="Pattern: retry decorator",
                    description="Exponential backoff retry logic with jitter",
                    category="resilience",
                    source_repo="https://github.com/test/repo",
                    source_files=["src/retry.py"],
                    relevance_score=0.75,
                )

                cap_data = miner._seed_capability_data_from_finding(finding)

                # Verify license_type is present and has the correct value
                assert "license_type" in cap_data, (
                    f"license_type key missing from capability_data. "
                    f"Keys present: {sorted(cap_data.keys())}"
                )
                assert cap_data["license_type"] == "permissive"

                # Verify copyleft also propagates correctly
                miner._current_mine_metadata = {"license_type": "copyleft"}
                cap_data_copyleft = miner._seed_capability_data_from_finding(finding)
                assert cap_data_copyleft["license_type"] == "copyleft"

                # Verify default when no metadata is set (getattr fallback)
                del miner._current_mine_metadata
                cap_data_no_meta = miner._seed_capability_data_from_finding(finding)
                assert cap_data_no_meta["license_type"] == ""

            finally:
                await engine.close()

        asyncio.run(_build_and_test())

    def test_license_empty_string_when_metadata_has_no_key(self) -> None:
        """When _current_mine_metadata exists but lacks license_type key,
        capability_data should contain license_type as empty string.
        """
        from claw.core.config import DatabaseConfig, load_config
        from claw.db.embeddings import EmbeddingEngine
        from claw.db.engine import DatabaseEngine
        from claw.db.repository import Repository
        from claw.llm.client import LLMClient
        from claw.memory.hybrid_search import HybridSearch
        from claw.memory.semantic import SemanticMemory
        from claw.miner import MiningFinding, RepoMiner

        config = load_config()
        db_config = DatabaseConfig(db_path=":memory:")
        embedding_engine = EmbeddingEngine()

        async def _build_and_test():
            engine = DatabaseEngine(db_config)
            await engine.connect()
            repo = Repository(engine)
            llm_client = LLMClient(config.llm)
            hybrid_search = HybridSearch(repo, embedding_engine)
            semantic_memory = SemanticMemory(repo, embedding_engine, hybrid_search)
            miner = RepoMiner(repo, llm_client, semantic_memory, config)

            try:
                # Metadata exists but has no license_type key
                miner._current_mine_metadata = {"some_other_field": "value"}

                finding = MiningFinding(
                    title="Pattern: circuit breaker",
                    description="Circuit breaker pattern for external calls",
                    category="resilience",
                    source_repo="https://github.com/test/repo2",
                    source_files=["src/breaker.py"],
                    relevance_score=0.80,
                )

                cap_data = miner._seed_capability_data_from_finding(finding)
                assert cap_data["license_type"] == ""

            finally:
                await engine.close()

        asyncio.run(_build_and_test())
