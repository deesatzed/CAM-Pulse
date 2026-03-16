from pathlib import Path

from advisor_app.repo_scan import derive_signals, scan_repo

FIXTURES = Path(__file__).parent / "fixtures" / "sample_repo"


def test_scan_repo_detects_missing_controls():
    profile = scan_repo(FIXTURES)
    assert profile.python_files
    assert not profile.test_files
    assert not profile.ci_files
    assert not profile.has_pyproject


def test_derive_signals_creates_recommendations_for_missing_tests_and_ci():
    profile = scan_repo(FIXTURES)
    signals = derive_signals(profile)
    ids = {signal.signal_id for signal in signals}
    assert "missing-tests" in ids
    assert "missing-ci" in ids
    assert "missing-packaging" in ids
