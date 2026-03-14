"""Export CAM memory tables to a neutral JSONL knowledge pack.

This is the bridge between CAM assimilation and standalone apps.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def parse_json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
        if isinstance(value, list):
            return [str(v) for v in value]
    except Exception:
        pass
    return []


def export_pack(
    db_path: Path,
    out_path: Path,
    max_methodologies: int,
    max_tasks: int,
    include_methodologies: bool = True,
    include_tasks: bool = True,
) -> dict[str, int]:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    counts = {"methodologies": 0, "tasks": 0, "total": 0}

    with out_path.open("w", encoding="utf-8") as handle:
        if include_methodologies:
            rows = cur.execute(
                """
                SELECT id, problem_description, methodology_notes, tags, solution_code,
                       language, scope, methodology_type, success_count, retrieval_count,
                       created_at, novelty_score, potential_score
                FROM methodologies
                ORDER BY success_count DESC, retrieval_count DESC, created_at DESC
                LIMIT ?
                """,
                (max_methodologies,),
            ).fetchall()
            for row in rows:
                tags = parse_json_list(row["tags"])
                text = "\n".join(
                    [
                        row["problem_description"] or "",
                        row["methodology_notes"] or "",
                        row["solution_code"] or "",
                        "tags: " + ", ".join(tags),
                    ]
                )
                item = {
                    "id": f"meth:{row['id']}",
                    "title": (row["problem_description"] or "methodology")[:120],
                    "modality": "memory_methodology",
                    "text": text[:6000],
                    "source": f"{db_path}:methodologies",
                    "metadata": {
                        "language": row["language"],
                        "scope": row["scope"],
                        "methodology_type": row["methodology_type"],
                        "success_count": int(row["success_count"] or 0),
                        "retrieval_count": int(row["retrieval_count"] or 0),
                        "novelty_score": row["novelty_score"],
                        "potential_score": row["potential_score"],
                        "created_at": row["created_at"],
                        "tags": tags[:20],
                    },
                }
                handle.write(json.dumps(item, ensure_ascii=True) + "\n")
                counts["methodologies"] += 1
                counts["total"] += 1

        if include_tasks:
            rows = cur.execute(
                """
                SELECT id, title, description, status, priority, task_type,
                       recommended_agent, assigned_agent, execution_steps,
                       acceptance_checks, created_at, updated_at
                FROM tasks
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (max_tasks,),
            ).fetchall()
            for row in rows:
                steps = parse_json_list(row["execution_steps"])
                checks = parse_json_list(row["acceptance_checks"])
                text = "\n".join(
                    [
                        row["title"] or "",
                        row["description"] or "",
                        f"status={row['status']} type={row['task_type']} recommended={row['recommended_agent']}",
                        "steps: " + "; ".join(steps[:8]),
                        "checks: " + "; ".join(checks[:8]),
                    ]
                )
                item = {
                    "id": f"task:{row['id']}",
                    "title": (row["title"] or "task")[:120],
                    "modality": "memory_task",
                    "text": text[:5000],
                    "source": f"{db_path}:tasks",
                    "metadata": {
                        "status": row["status"],
                        "priority": int(row["priority"] or 0),
                        "task_type": row["task_type"],
                        "recommended_agent": row["recommended_agent"],
                        "assigned_agent": row["assigned_agent"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                    },
                }
                handle.write(json.dumps(item, ensure_ascii=True) + "\n")
                counts["tasks"] += 1
                counts["total"] += 1

    conn.close()
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Export CAM memory into a standalone JSONL knowledge pack.")
    parser.add_argument("--db", type=Path, default=Path("data/claw.db"))
    parser.add_argument("--out", type=Path, default=Path("data/cam_knowledge_pack.jsonl"))
    parser.add_argument("--max-methodologies", type=int, default=300)
    parser.add_argument("--max-tasks", type=int, default=300)
    parser.add_argument("--no-methodologies", action="store_true", help="Exclude methodologies from export.")
    parser.add_argument("--no-tasks", action="store_true", help="Exclude tasks from export.")
    args = parser.parse_args()

    counts = export_pack(
        db_path=args.db,
        out_path=args.out,
        max_methodologies=args.max_methodologies,
        max_tasks=args.max_tasks,
        include_methodologies=not args.no_methodologies,
        include_tasks=not args.no_tasks,
    )
    print(json.dumps({"out": str(args.out), **counts}, indent=2))


if __name__ == "__main__":
    main()
