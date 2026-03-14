"""Tests for CAM knowledge-pack export bridge."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
from pathlib import Path


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _seed_bridge_db(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE methodologies (
            id TEXT PRIMARY KEY,
            problem_description TEXT,
            methodology_notes TEXT,
            tags TEXT,
            solution_code TEXT,
            language TEXT,
            scope TEXT,
            methodology_type TEXT,
            success_count INTEGER,
            retrieval_count INTEGER,
            created_at TEXT,
            novelty_score REAL,
            potential_score REAL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE tasks (
            id TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            status TEXT,
            priority INTEGER,
            task_type TEXT,
            recommended_agent TEXT,
            assigned_agent TEXT,
            execution_steps TEXT,
            acceptance_checks TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )

    cur.execute(
        """
        INSERT INTO methodologies
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            "m1",
            "Improve retrieval robustness",
            "Use anchored concept channels",
            json.dumps(["retrieval", "anchor"]),
            "def improve(): pass",
            "python",
            "global",
            "PATTERN",
            3,
            7,
            "2026-03-11T13:00:00Z",
            0.71,
            0.82,
        ],
    )
    cur.execute(
        """
        INSERT INTO tasks
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            "t1",
            "Bridge CAM to Forge",
            "Export assimilated knowledge into a neutral pack.",
            "PENDING",
            8,
            "architecture",
            "codex",
            None,
            json.dumps(["export pack", "run forge"]),
            json.dumps(["pack exists", "artifacts created"]),
            "2026-03-11T13:01:00Z",
            "2026-03-11T13:02:00Z",
        ],
    )

    conn.commit()
    conn.close()


class TestKnowledgePackExport:
    def test_export_pack_writes_jsonl(self, tmp_path):
        module = _load_module(
            "export_cam_knowledge_pack",
            Path("scripts/export_cam_knowledge_pack.py").resolve(),
        )
        db_path = tmp_path / "bridge.db"
        out_path = tmp_path / "pack.jsonl"
        _seed_bridge_db(db_path)

        counts = module.export_pack(
            db_path=db_path,
            out_path=out_path,
            max_methodologies=10,
            max_tasks=10,
        )

        assert counts == {"methodologies": 1, "tasks": 1, "total": 2}
        rows = [json.loads(line) for line in out_path.read_text().splitlines()]
        assert len(rows) == 2
        assert rows[0]["id"] == "meth:m1"
        assert rows[0]["metadata"]["methodology_type"] == "PATTERN"
        assert rows[1]["id"] == "task:t1"
        assert rows[1]["metadata"]["task_type"] == "architecture"

    def test_export_pack_respects_section_flags(self, tmp_path):
        module = _load_module(
            "export_cam_knowledge_pack_flags",
            Path("scripts/export_cam_knowledge_pack.py").resolve(),
        )
        db_path = tmp_path / "bridge.db"
        out_path = tmp_path / "tasks_only.jsonl"
        _seed_bridge_db(db_path)

        counts = module.export_pack(
            db_path=db_path,
            out_path=out_path,
            max_methodologies=10,
            max_tasks=10,
            include_methodologies=False,
            include_tasks=True,
        )

        assert counts == {"methodologies": 0, "tasks": 1, "total": 1}
        rows = [json.loads(line) for line in out_path.read_text().splitlines()]
        assert len(rows) == 1
        assert rows[0]["modality"] == "memory_task"
