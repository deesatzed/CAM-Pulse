from __future__ import annotations

import pytest

from tests.benchmarks.connectome_suite.report import build_connectome_report, build_connectome_report_data, write_connectome_headlines, write_connectome_manifest, write_connectome_report_json, write_connectome_status_markdown


@pytest.mark.asyncio
async def test_connectome_report_contains_key_sections():
    report = await build_connectome_report()
    assert "# CAM-SEQ Connectome Benchmark Report" in report
    assert "## Pilot Suite" in report
    assert "## Full Suite" in report
    assert "## Planning Ablation" in report
    assert "## Connectome + Recipe Ablation" in report
    assert "## Live Reviewed-Run Harness" in report
    assert "## Seeded Retrograde Cases" in report
    assert "## Local Security Lane" in report
    assert "top cause distribution:" in report
    assert "root summary distribution:" in report
    assert "recommended action distribution:" in report
    assert "recipe active: True" in report


@pytest.mark.asyncio
async def test_connectome_report_data_contains_seeded_root_summary_counts(tmp_path):
    data = await build_connectome_report_data()
    assert "seeded_retrograde" in data
    assert data["seeded_retrograde"]["root_summary_counts"]
    assert data["seeded_retrograde"]["recommended_action_counts"]
    assert data["seeded_retrograde"]["dominant_cluster_counts"]
    assert data["seeded_retrograde"]["confidence_band_counts"]
    assert data["seeded_retrograde"]["calibration_counts"]
    assert data["seeded_retrograde"]["stability_counts"]

    out = tmp_path / "connectome_report.json"
    await write_connectome_report_json(out)
    written = out.read_text(encoding="utf-8")
    assert "\"root_summary_counts\"" in written

    md = tmp_path / "connectome_report.md"
    md.write_text("# test\n", encoding="utf-8")
    manifest = tmp_path / "connectome_manifest.json"
    await write_connectome_manifest(manifest, markdown_path=md, json_path=out)
    written_manifest = manifest.read_text(encoding="utf-8")
    assert "\"artifacts\"" in written_manifest
    assert "\"generated_for\"" in written_manifest
    assert "\"overall_task_count\"" in written_manifest

    headlines = tmp_path / "connectome_headlines.json"
    await write_connectome_headlines(headlines)
    written_headlines = headlines.read_text(encoding="utf-8")
    assert "\"full_archetype_accuracy\"" in written_headlines
    assert "\"top_seeded_cause_kinds\"" in written_headlines
    assert "\"dominant_seeded_clusters\"" in written_headlines
    assert "\"seeded_confidence_bands\"" in written_headlines
    assert "\"seeded_calibrations\"" in written_headlines
    assert "\"seeded_stabilities\"" in written_headlines

    status_md = tmp_path / "connectome_status.md"
    await write_connectome_status_markdown(status_md)
    written_status = status_md.read_text(encoding="utf-8")
    assert "# CAM-SEQ Benchmark Status" in written_status
    assert "Full archetype accuracy" in written_status
    assert "Dominant seeded clusters" in written_status
    assert "Seeded confidence bands" in written_status
    assert "Seeded calibrations" in written_status
    assert "Seeded stabilities" in written_status
