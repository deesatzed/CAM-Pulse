"""Generate seed knowledge pack from local methodology DB.

Usage: python scripts/generate_seed_pack.py [--max 30] [--include-ids ID1,ID2]

Writes to src/claw/data/seed/core_v1.jsonl
"""
import asyncio
import json
import sys
from pathlib import Path


async def main() -> None:
    from claw.core.config import load_config
    from claw.db.engine import DatabaseEngine
    from claw.community.packer import pack_methodologies

    max_count = 30
    include_ids: list[str] = []
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--max" and i + 1 < len(sys.argv) - 1:
            max_count = int(sys.argv[i + 2])
        if arg == "--include-ids" and i + 1 < len(sys.argv) - 1:
            include_ids = sys.argv[i + 2].split(",")

    config = load_config()
    engine = DatabaseEngine(config.database)
    await engine.connect()
    await engine.apply_migrations()
    await engine.initialize_schema()

    state_path = Path(config.database.db_path).parent / "community_state.json"
    records, manifest = await pack_methodologies(
        engine=engine,
        state_path=state_path,
        min_lifecycle="viable",
        max_count=max_count,
    )

    # Force-include specific IDs that may not meet lifecycle threshold
    if include_ids:
        existing_ids = {r.get("id") for r in records}
        for mid in include_ids:
            if mid in existing_ids:
                continue
            row = await engine.fetch_one(
                "SELECT * FROM methodologies WHERE id LIKE ?",
                [f"{mid}%"],
            )
            if row:
                text = f"{row['problem_description']}\n\n{row['solution_code']}"
                if row.get("methodology_notes"):
                    text += f"\n\n{row['methodology_notes']}"
                record = {
                    "id": row["id"],
                    "title": row["problem_description"][:80],
                    "modality": "memory_methodology",
                    "text": text[:6000],
                    "metadata": {
                        "language": row.get("language", ""),
                        "scope": row.get("scope", "global"),
                        "methodology_type": row.get("methodology_type", "PATTERN"),
                        "tags": json.loads(row.get("tags", "[]")),
                        "success_count": row.get("success_count", 0),
                        "retrieval_count": row.get("retrieval_count", 0),
                        "novelty_score": row.get("novelty_score"),
                        "potential_score": row.get("potential_score"),
                        "capability_data": json.loads(row.get("capability_data", "{}") or "{}"),
                    },
                    "community_meta": {
                        "pack_format_version": "1.0",
                        "instance_id": manifest.get("instance_id", "cam-seed"),
                        "contributor_alias": "cam-seed",
                        "exported_at": manifest.get("exported_at", ""),
                        "origin_lifecycle": row.get("lifecycle_state", "viable"),
                        "content_hash": "",
                    },
                }
                # Compute content hash
                import hashlib
                payload = f"{record['id']}:{record['text'][:2000]}"
                record["community_meta"]["content_hash"] = hashlib.sha256(payload.encode()).hexdigest()
                records.append(record)
                print(f"  Force-included: {row['id'][:12]} ({row['problem_description'][:60]})")

    # Add origin:seed tag to each record
    for record in records:
        tags = record.get("metadata", {}).get("tags", [])
        if "origin:seed" not in tags:
            tags.append("origin:seed")
        record["metadata"]["tags"] = tags

    # Write JSONL
    output = Path(__file__).resolve().parent.parent / "src" / "claw" / "data" / "seed" / "core_v1.jsonl"
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")

    print(f"Wrote {len(records)} seed methodologies to {output}")
    await engine.close()


if __name__ == "__main__":
    asyncio.run(main())
