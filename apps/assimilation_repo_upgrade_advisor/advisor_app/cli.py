"""CLI entrypoint."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .knowledge_pack import load_knowledge_pack
from .recommender import build_recommendations
from .report import render_report
from .repo_scan import derive_signals, scan_repo


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a repo upgrade plan grounded in assimilated CAM knowledge.",
    )
    parser.add_argument("--knowledge-pack", required=True, type=Path, help="Path to a CAM knowledge-pack JSONL export.")
    parser.add_argument("--repo", required=True, type=Path, help="Target repository path to analyze.")
    parser.add_argument("--output", "-o", required=True, type=Path, help="Markdown output path.")
    parser.add_argument("--json-output", type=Path, default=None, help="Optional JSON recommendation output path.")
    parser.add_argument(
        "--focus",
        nargs="*",
        default=None,
        choices=["testing", "architecture", "devops", "code_quality", "security"],
        help="Optional focus categories.",
    )
    parser.add_argument("--limit", type=int, default=5, help="Maximum recommendations to render.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        knowledge_items = load_knowledge_pack(args.knowledge_pack)
        profile = scan_repo(args.repo)
        signals = derive_signals(profile, set(args.focus) if args.focus else None)
        recommendations = build_recommendations(signals, knowledge_items, limit=args.limit)
        report = render_report(profile, recommendations, len(knowledge_items))

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")

        if args.json_output:
            payload = {
                "repo": str(args.repo),
                "knowledge_items": len(knowledge_items),
                "recommendations": [
                    {
                        "title": rec.title,
                        "category": rec.category,
                        "confidence": rec.confidence,
                        "difficulty": rec.difficulty,
                        "payoff": rec.payoff,
                        "evidence": rec.evidence,
                        "first_step": rec.first_step,
                        "provenance": [
                            {
                                "item_id": match.item_id,
                                "title": match.title,
                                "source_repo": match.source_repo,
                                "score": match.score,
                                "rationale": match.rationale,
                            }
                            for match in rec.provenance
                        ],
                    }
                    for rec in recommendations
                ],
            }
            args.json_output.parent.mkdir(parents=True, exist_ok=True)
            args.json_output.write_text(json.dumps(payload, indent=2), encoding="utf-8")

        print(f"Wrote report to {args.output}")
        print(f"Recommendations: {len(recommendations)}")
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
