from __future__ import annotations

from claw.mining.scip_loader import detect_scip_index, load_repo_scip, load_scip_symbols
from claw.miner import MiningFinding, RepoMiner


def test_detect_scip_index_json(tmp_path):
    scip_dir = tmp_path / ".scip"
    scip_dir.mkdir()
    index = scip_dir / "index.json"
    index.write_text('{"symbols": []}', encoding="utf-8")

    detected = detect_scip_index(tmp_path)
    assert detected == index


def test_load_scip_symbols_from_jsonl(tmp_path):
    index = tmp_path / "scip.jsonl"
    index.write_text(
        '{"symbol": "pkg Foo#", "file_path": "src/foo.py", "kind": "class", "line_start": 3, "line_end": 12}\n',
        encoding="utf-8",
    )
    symbols = load_scip_symbols(index)
    assert len(symbols) == 1
    assert symbols[0].file_path == "src/foo.py"
    assert symbols[0].kind == "class"


def test_load_repo_scip_absent(tmp_path):
    path, symbols = load_repo_scip(tmp_path)
    assert path is None
    assert symbols == []


def test_repo_miner_applies_scip_precision_to_symbols(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "foo.py").write_text("def refresh_session():\n    return True\n", encoding="utf-8")
    (tmp_path / "scip.jsonl").write_text(
        '{"symbol": "python pkg refresh_session", "file_path": "src/foo.py", "kind": "function", "line_start": 1, "line_end": 2}\n',
        encoding="utf-8",
    )

    symbols = RepoMiner._extract_symbols_from_file(tmp_path, "src/foo.py")
    upgraded = RepoMiner._apply_scip_precision(symbols, tmp_path)

    matched = next(item for item in upgraded if item["symbol_name"] == "refresh_session")
    assert matched["provenance_precision"] == "precise_symbol"
    assert matched["line_start"] == 1
    assert matched["line_end"] == 2


def test_seed_capability_data_preserves_symbol_precision_metadata():
    miner = object.__new__(RepoMiner)
    finding = MiningFinding(
        title="Refresh helper",
        description="Handles refresh",
        category="security",
        source_repo="org/service",
        source_files=["src/foo.py"],
        source_symbols=[
            {
                "file_path": "src/foo.py",
                "symbol_name": "refresh_session",
                "symbol_kind": "function",
                "line_start": 1,
                "line_end": 2,
                "provenance_precision": "precise_symbol",
                "note": "scip matched",
            }
        ],
    )

    capability = RepoMiner._seed_capability_data_from_finding(miner, finding)
    symbol_artifacts = [item for item in capability["source_artifacts"] if item["symbol_name"] == "refresh_session"]
    assert symbol_artifacts
    assert symbol_artifacts[0]["provenance_precision"] == "precise_symbol"
    assert symbol_artifacts[0]["line_start"] == 1
