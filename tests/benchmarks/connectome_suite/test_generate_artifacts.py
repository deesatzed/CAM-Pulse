from __future__ import annotations

import pytest

from tests.benchmarks.connectome_suite.generate_artifacts import generate_artifacts


@pytest.mark.asyncio
async def test_generate_artifacts_writes_markdown_and_json(tmp_path):
    out_dir = await generate_artifacts(tmp_path)
    assert (out_dir / "camseq_connectome_report.md").exists()
    assert (out_dir / "camseq_connectome_report.json").exists()
    assert (out_dir / "camseq_connectome_headlines.json").exists()
    assert (out_dir / "camseq_connectome_status.md").exists()
