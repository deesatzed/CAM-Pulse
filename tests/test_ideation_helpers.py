"""Tests for CAM ideation helper functions."""

from __future__ import annotations

import json
from pathlib import Path


class TestIdeationHelpers:
    def test_normalize_ideation_payload(self):
        from claw import cli

        payload = {
            "ideas": [
                {
                    "title": "ForgeBench",
                    "tagline": "Turn mined repo knowledge into benchmarkable build plans.",
                    "problem": "Teams mine repos but do not convert them into buildable products.",
                    "why_valuable": "Creates a direct path from knowledge to product execution.",
                    "novelty": "Combines CAM memory with repo-specific mechanisms.",
                    "repos_used": ["repo-a", "repo-b"],
                    "cam_knowledge_used": ["cap-a", "cap-b"],
                    "app_request": "Build a standalone app for benchmarkable repo-to-product planning.",
                    "spec_items": ["Must be standalone", "Must produce runnable plans"],
                    "execution_steps": ["pytest -q"],
                    "acceptance_checks": ["pytest -q"],
                    "repo_mode": "new",
                    "build_confidence": "0.8",
                }
            ]
        }

        ideas = cli._normalize_ideation_payload(payload, idea_count=3)

        assert len(ideas) == 1
        assert ideas[0]["title"] == "ForgeBench"
        assert ideas[0]["repos_used"] == ["repo-a", "repo-b"]
        assert ideas[0]["build_confidence"] == 0.8

    def test_write_ideation_artifacts(self, tmp_path, monkeypatch):
        from claw import cli

        monkeypatch.setattr(cli, "_IDEA_DIR", tmp_path / "ideas")
        ideas = [
            {
                "title": "Repo Weaver",
                "tagline": "Compose apps from mined repo patterns.",
                "problem": "Useful patterns stay trapped in notes.",
                "why_valuable": "Turns mined knowledge into product candidates.",
                "novelty": "Uses CAM memory as a build substrate.",
                "repos_used": ["repo-a"],
                "cam_knowledge_used": ["method-a"],
                "app_request": "Build Repo Weaver.",
                "spec_items": ["Standalone"],
                "execution_steps": ["pytest -q"],
                "acceptance_checks": ["pytest -q"],
                "repo_mode": "new",
                "build_confidence": 0.7,
            }
        ]

        json_path, md_path = cli._write_ideation_artifacts(
            source_dir=Path("/tmp/Repo2Eval"),
            focus="invent a strong standalone app",
            ideas=ideas,
            raw_payload={"ideas": ideas},
        )

        assert json_path.exists()
        assert md_path.exists()

        written = json.loads(json_path.read_text(encoding="utf-8"))
        assert written["source_dir"] == "/tmp/Repo2Eval"
        assert written["ideas"][0]["title"] == "Repo Weaver"

        md = md_path.read_text(encoding="utf-8")
        assert "CAM Ideation Report" in md
        assert "Repo Weaver" in md
