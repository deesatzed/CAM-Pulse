"""Tests for the mine-all bulk mining features.

Uses real filesystem and in-memory SQLite (no mocks).
Tests domain classification, profile creation, priority sorting, and checkpoint save/resume.
"""

from __future__ import annotations

from claw.miner import (
    RepoCandidate,
    RepoProfile,
    RepoScanLedger,
    RepoScanRecord,
    classify_repo_domain,
)

# ---------------------------------------------------------------------------
# Domain classification tests
# ---------------------------------------------------------------------------


class TestDomainClassification:
    """classify_repo_domain should identify domains from README text."""

    def test_medical_domain(self, tmp_path):
        readme = "This app uses FHIR to manage patient records and clinical diagnosis workflows"
        assert classify_repo_domain(tmp_path, readme) == "medical"

    def test_finance_domain(self, tmp_path):
        readme = "A trading platform with portfolio management and forex market analysis"
        assert classify_repo_domain(tmp_path, readme) == "finance"

    def test_ai_ml_domain(self, tmp_path):
        readme = "RAG pipeline using embeddings and LLM with langchain for agent orchestration"
        assert classify_repo_domain(tmp_path, readme) == "ai_ml"

    def test_devtools_domain(self, tmp_path):
        readme = "A CLI linter and formatter for Go code with neovim plugin support"
        assert classify_repo_domain(tmp_path, readme) == "devtools"

    def test_infrastructure_domain(self, tmp_path):
        readme = "Kubernetes helm charts for deploying prometheus and grafana monitoring"
        assert classify_repo_domain(tmp_path, readme) == "infrastructure"

    def test_web_apps_domain(self, tmp_path):
        readme = "A nextjs react app with graphql and oauth jwt authentication"
        assert classify_repo_domain(tmp_path, readme) == "web_apps"

    def test_data_science_domain(self, tmp_path):
        readme = "ETL pipeline using pandas numpy with jupyter notebooks and airflow scheduling"
        assert classify_repo_domain(tmp_path, readme) == "data_science"

    def test_unknown_domain(self, tmp_path):
        readme = "Hello world"
        assert classify_repo_domain(tmp_path, readme) == "general"

    def test_empty_readme(self, tmp_path):
        assert classify_repo_domain(tmp_path, "") == "general"

    def test_filename_based_classification(self, tmp_path):
        """Should classify from filenames even without README text."""
        (tmp_path / "fhir_server.py").touch()
        (tmp_path / "patient_model.py").touch()
        # file names alone contain "fhir" and "patient" → medical
        result = classify_repo_domain(tmp_path, "")
        assert result == "medical"


# ---------------------------------------------------------------------------
# RepoProfile tests
# ---------------------------------------------------------------------------


class TestRepoProfile:
    """RepoProfile should hold classification + scoring metadata."""

    def test_default_values(self, tmp_path):
        cand = RepoCandidate(
            path=tmp_path,
            name="test-repo",
            canonical_name="test-repo",
            depth=1,
        )
        profile = RepoProfile(candidate=cand)
        assert profile.primary_brain == "python"
        assert profile.application_domain == "general"
        assert profile.yield_score == 0.5
        assert profile.ledger_status == "new"

    def test_custom_values(self, tmp_path):
        cand = RepoCandidate(
            path=tmp_path,
            name="my-medical-app",
            canonical_name="my-medical-app",
            depth=2,
            file_count=150,
            total_bytes=500_000,
        )
        profile = RepoProfile(
            candidate=cand,
            primary_brain="python",
            application_domain="medical",
            yield_score=0.85,
            gap_score=0.3,
            ledger_status="new",
        )
        assert profile.application_domain == "medical"
        assert profile.yield_score == 0.85
        assert profile.gap_score == 0.3

    def test_priority_sorting(self, tmp_path):
        """Profiles should sort by yield_score descending."""
        profiles = [
            RepoProfile(
                candidate=RepoCandidate(path=tmp_path / "a", name="a", canonical_name="a", depth=1),
                yield_score=0.3,
            ),
            RepoProfile(
                candidate=RepoCandidate(path=tmp_path / "b", name="b", canonical_name="b", depth=1),
                yield_score=0.9,
            ),
            RepoProfile(
                candidate=RepoCandidate(path=tmp_path / "c", name="c", canonical_name="c", depth=1),
                yield_score=0.6,
            ),
        ]
        sorted_profiles = sorted(profiles, key=lambda p: p.yield_score, reverse=True)
        assert sorted_profiles[0].candidate.name == "b"
        assert sorted_profiles[1].candidate.name == "c"
        assert sorted_profiles[2].candidate.name == "a"


# ---------------------------------------------------------------------------
# Checkpoint / ledger tests
# ---------------------------------------------------------------------------


class TestLedgerCheckpoint:
    """RepoScanLedger should save/load checkpoint state."""

    def test_save_and_load(self, tmp_path):
        ledger_path = tmp_path / "ledger.json"
        ledger = RepoScanLedger(ledger_path)

        cand = RepoCandidate(
            path=tmp_path / "repo1",
            name="repo1",
            canonical_name="repo1",
            depth=1,
            file_count=42,
            total_bytes=10000,
            scan_signature="sig1",
            content_hash="hash1",
        )

        # Simulate recording a result
        record = RepoScanRecord(
            repo_path=str(cand.path),
            repo_name="repo1",
            canonical_name="repo1",
            source_kind="git",
            scan_signature="sig1",
            file_count=42,
            total_bytes=10000,
            last_commit_ts=1700000000.0,
            last_mined_at=1700001000.0,
            findings_count=5,
            tokens_used=1000,
            content_hash="hash1",
        )

        ledger._load()
        key = ledger.repo_key(cand.path)
        ledger._records[key] = record
        ledger._save()

        # Load in a new ledger instance
        ledger2 = RepoScanLedger(ledger_path)
        loaded = ledger2.get_record(cand.path)
        assert loaded is not None
        assert loaded.repo_name == "repo1"
        assert loaded.findings_count == 5
        assert loaded.tokens_used == 1000

    def test_should_mine_new(self, tmp_path):
        ledger = RepoScanLedger(tmp_path / "ledger.json")
        cand = RepoCandidate(
            path=tmp_path / "new-repo",
            name="new-repo",
            canonical_name="new-repo",
            depth=1,
            scan_signature="newsig",
        )
        should, reason = ledger.should_mine(cand)
        assert should is True
        assert reason == "new"

    def test_should_mine_unchanged(self, tmp_path):
        ledger_path = tmp_path / "ledger.json"
        ledger = RepoScanLedger(ledger_path)

        repo_path = tmp_path / "unchanged-repo"
        repo_path.mkdir()

        cand = RepoCandidate(
            path=repo_path,
            name="unchanged-repo",
            canonical_name="unchanged-repo",
            depth=1,
            scan_signature="same-sig",
        )

        # Pre-populate the ledger
        key = ledger.repo_key(repo_path)
        ledger._load()
        ledger._records[key] = RepoScanRecord(
            repo_path=key,
            repo_name="unchanged-repo",
            canonical_name="unchanged-repo",
            source_kind="git",
            scan_signature="same-sig",
            file_count=10,
            total_bytes=5000,
            last_commit_ts=1700000000.0,
            last_mined_at=1700001000.0,
        )
        ledger._save()

        # New ledger should say unchanged
        ledger2 = RepoScanLedger(ledger_path)
        should, reason = ledger2.should_mine(cand)
        assert should is False
        assert reason == "unchanged"

    def test_should_mine_changed(self, tmp_path):
        ledger_path = tmp_path / "ledger.json"
        ledger = RepoScanLedger(ledger_path)

        repo_path = tmp_path / "changed-repo"
        repo_path.mkdir()

        key = ledger.repo_key(repo_path)
        ledger._load()
        ledger._records[key] = RepoScanRecord(
            repo_path=key,
            repo_name="changed-repo",
            canonical_name="changed-repo",
            source_kind="git",
            scan_signature="old-sig",
            file_count=10,
            total_bytes=5000,
            last_commit_ts=1700000000.0,
            last_mined_at=1700001000.0,
        )
        ledger._save()

        cand = RepoCandidate(
            path=repo_path,
            name="changed-repo",
            canonical_name="changed-repo",
            depth=1,
            scan_signature="new-sig",
        )

        ledger2 = RepoScanLedger(ledger_path)
        should, reason = ledger2.should_mine(cand)
        assert should is True
        assert reason == "changed"

    def test_force_rescan(self, tmp_path):
        ledger = RepoScanLedger(tmp_path / "ledger.json")
        cand = RepoCandidate(
            path=tmp_path / "repo",
            name="repo",
            canonical_name="repo",
            depth=1,
            scan_signature="sig",
        )
        should, reason = ledger.should_mine(cand, force_rescan=True)
        assert should is True
        assert reason == "forced"

    def test_ledger_list_records(self, tmp_path):
        ledger_path = tmp_path / "ledger.json"
        ledger = RepoScanLedger(ledger_path)
        ledger._load()

        for i in range(3):
            key = f"/path/repo{i}"
            ledger._records[key] = RepoScanRecord(
                repo_path=key,
                repo_name=f"repo{i}",
                canonical_name=f"repo{i}",
                source_kind="git",
                scan_signature=f"sig{i}",
                file_count=i * 10,
                total_bytes=i * 1000,
                last_commit_ts=1700000000.0 + i,
                last_mined_at=1700001000.0 + i,
            )
        ledger._save()

        ledger2 = RepoScanLedger(ledger_path)
        records = ledger2.list_records()
        assert len(records) == 3
