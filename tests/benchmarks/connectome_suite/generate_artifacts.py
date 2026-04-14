from __future__ import annotations

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tests.benchmarks.connectome_suite.report import (
    write_connectome_headlines,
    write_connectome_manifest,
    write_connectome_report,
    write_connectome_report_json,
    write_connectome_status_markdown,
)


async def generate_artifacts(out_dir: str | Path = "docs/benchmarks") -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "camseq_connectome_report.md"
    json_path = out_dir / "camseq_connectome_report.json"
    headlines_path = out_dir / "camseq_connectome_headlines.json"
    status_md_path = out_dir / "camseq_connectome_status.md"
    await write_connectome_report(md_path)
    await write_connectome_report_json(json_path)
    await write_connectome_headlines(headlines_path)
    await write_connectome_status_markdown(status_md_path)
    await write_connectome_manifest(out_dir / "camseq_connectome_manifest.json", markdown_path=md_path, json_path=json_path)
    return out_dir


async def main() -> None:
    await generate_artifacts()


if __name__ == "__main__":
    asyncio.run(main())
