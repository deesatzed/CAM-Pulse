from pathlib import Path

from advisor_app.cli import main, parse_args

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_args_accepts_required_values(tmp_path):
    args = parse_args([
        "--knowledge-pack", str(FIXTURES / "knowledge_pack.jsonl"),
        "--repo", str(FIXTURES / "sample_repo"),
        "--output", str(tmp_path / "report.md"),
    ])
    assert args.limit == 5


def test_cli_generates_markdown_and_json(tmp_path):
    report_path = tmp_path / "report.md"
    json_path = tmp_path / "report.json"
    exit_code = main([
        "--knowledge-pack", str(FIXTURES / "knowledge_pack.jsonl"),
        "--repo", str(FIXTURES / "sample_repo"),
        "--output", str(report_path),
        "--json-output", str(json_path),
    ])
    assert exit_code == 0
    report = report_path.read_text(encoding="utf-8")
    assert "Ranked Recommendations" in report
    assert "Assimilated provenance" in report
    assert "missing-tests" not in report
    assert "fixture-testing" in report
    assert json_path.exists()
