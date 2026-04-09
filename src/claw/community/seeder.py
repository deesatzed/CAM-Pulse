"""Seed knowledge loader for first-run initialization.

Loads curated JSONL packs from src/claw/data/seed/ into an empty
(or partially populated) methodology store. Idempotent — skips
records whose content_hash already exists.

The origin:seed tag marks seed methodologies so they can be:
  - Re-seeded if accidentally deleted
  - Protected from lifecycle decay (stays viable or better)
  - Distinguished from user-mined knowledge in searches
"""

from __future__ import annotations

import hashlib
import json
import logging
import struct
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("claw.community.seeder")

# Seed data ships inside the Python package
SEED_DIR = Path(__file__).resolve().parent.parent / "data" / "seed"

SEED_TAG = "origin:seed"


def discover_seed_packs() -> list[Path]:
    """Find all .jsonl files in the seed directory, sorted by name."""
    if not SEED_DIR.exists():
        logger.debug("Seed directory not found: %s", SEED_DIR)
        return []
    packs = sorted(SEED_DIR.glob("*.jsonl"))
    if packs:
        logger.info("Discovered %d seed pack(s) in %s", len(packs), SEED_DIR)
    return packs


def load_seed_records(packs: list[Path]) -> list[dict[str, Any]]:
    """Load and parse all records from seed JSONL files."""
    records: list[dict[str, Any]] = []
    for pack in packs:
        for line_num, line in enumerate(pack.read_text().strip().splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                # Ensure origin:seed tag
                tags = record.get("metadata", {}).get("tags", [])
                if isinstance(tags, str):
                    tags = json.loads(tags)
                if SEED_TAG not in tags:
                    tags.append(SEED_TAG)
                record.setdefault("metadata", {})["tags"] = tags
                records.append(record)
            except json.JSONDecodeError as e:
                logger.warning("Bad JSON at %s:%d: %s", pack.name, line_num, e)
    return records


def _compute_content_hash(record: dict[str, Any]) -> str:
    """Compute a dedup hash for a seed record."""
    text = record.get("text", "")
    record_id = record.get("id", "")
    payload = f"{record_id}:{text[:2000]}"
    return hashlib.sha256(payload.encode()).hexdigest()


async def needs_seeding(engine: Any, force: bool = False) -> bool:
    """Check if the DB needs seeding.

    Returns True if:
      - force=True, OR
      - The methodologies table has zero rows, OR
      - No rows with origin:seed tag exist (re-seed case)
    """
    if force:
        return True

    row = await engine.fetch_one("SELECT COUNT(*) as cnt FROM methodologies")
    total = row["cnt"] if row else 0
    if total == 0:
        return True

    # Check if any seed records exist
    row = await engine.fetch_one(
        "SELECT COUNT(*) as cnt FROM methodologies WHERE tags LIKE ?",
        ['%"origin:seed"%'],
    )
    seed_count = row["cnt"] if row else 0
    if seed_count == 0:
        logger.info("No seed methodologies found — seeding recommended")
        return True

    return False


async def _ensure_community_tables(engine: Any) -> None:
    """Ensure community_imports table exists for dedup tracking."""
    await engine.conn.execute("""
        CREATE TABLE IF NOT EXISTS community_imports (
            id TEXT PRIMARY KEY,
            content_hash TEXT NOT NULL,
            contributor_instance_id TEXT NOT NULL,
            contributor_alias TEXT,
            origin_id TEXT,
            status TEXT DEFAULT 'quarantined'
                CHECK (status IN ('quarantined','approved','rejected','seed')),
            gate_results TEXT NOT NULL DEFAULT '{}',
            sanitized_record TEXT NOT NULL,
            imported_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            approved_at TEXT,
            UNIQUE(content_hash)
        )
    """)
    await engine.conn.commit()


async def _is_hash_known(engine: Any, content_hash: str) -> bool:
    """Check if a content_hash already exists in community_imports."""
    row = await engine.fetch_one(
        "SELECT id FROM community_imports WHERE content_hash = ?",
        [content_hash],
    )
    return row is not None


async def _seed_record(
    record: dict[str, Any],
    engine: Any,
    embedding_engine: Optional[Any] = None,
) -> Optional[str]:
    """Insert a single seed record directly into the knowledge base.

    Trusted source — bypasses the 7-gate community validator since seed
    JSONL ships with the codebase and is code-reviewed.

    Returns the new methodology ID, or None if skipped (dedup).
    """
    content_hash = _compute_content_hash(record)

    # Idempotency: skip if already imported
    if await _is_hash_known(engine, content_hash):
        logger.debug("Seed record already exists (hash=%s), skipping", content_hash[:12])
        return None

    meta = record.get("metadata", {})
    cm = record.get("community_meta", {})
    text = record.get("text", "")
    parts = text.split("\n\n", 2)
    problem = parts[0] if parts else text
    solution = parts[1] if len(parts) > 1 else ""
    notes = parts[2] if len(parts) > 2 else ""

    new_id = str(uuid.uuid4())
    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = json.loads(tags)
    if SEED_TAG not in tags:
        tags.append(SEED_TAG)

    cap_data = meta.get("capability_data") or {}
    if isinstance(cap_data, str):
        cap_data = json.loads(cap_data)
    cap_data["seed_origin"] = {
        "pack_version": cm.get("pack_format_version", "1.0"),
        "seeded_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }

    # 1. Insert into methodologies table
    await engine.execute(
        """INSERT INTO methodologies
           (id, problem_description, solution_code, methodology_notes,
            tags, language, scope, methodology_type, capability_data,
            lifecycle_state, success_count, failure_count, retrieval_count,
            fitness_vector, generation, novelty_score, potential_score)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [
            new_id,
            problem,
            solution,
            notes,
            json.dumps(tags),
            meta.get("language", ""),
            "global",  # Seeds are globally scoped
            meta.get("methodology_type", "PATTERN"),
            json.dumps(cap_data),
            "viable",  # Seeds start proven, not embryonic
            meta.get("success_count", 0),
            0,  # failure_count
            0,  # retrieval_count
            "{}",  # fitness_vector
            0,  # generation
            meta.get("novelty_score"),
            meta.get("potential_score"),
        ],
    )

    # 2. FTS5 index — required for text search
    await engine.execute(
        "INSERT INTO methodology_fts (methodology_id, problem_description, methodology_notes, tags) VALUES (?, ?, ?, ?)",
        [new_id, problem, notes, json.dumps(tags)],
    )

    # 3. Embedding — required for semantic (vector) search
    if embedding_engine is not None:
        try:
            vec = await embedding_engine.async_encode(problem)
            vec_bytes = struct.pack(f"<{len(vec)}f", *vec)
            await engine.execute(
                "INSERT INTO methodology_embeddings (methodology_id, embedding) VALUES (?, ?)",
                [new_id, vec_bytes],
            )
        except Exception as e:
            logger.warning("Seed embedding failed for %s: %s", new_id, e)

    # 4. Record in community_imports for dedup tracking
    await engine.execute(
        """INSERT OR IGNORE INTO community_imports
           (id, content_hash, contributor_instance_id, contributor_alias, origin_id, status, sanitized_record)
           VALUES (?, ?, ?, ?, ?, 'seed', ?)""",
        [
            str(uuid.uuid4()),
            content_hash,
            cm.get("instance_id", "cam-seed"),
            cm.get("contributor_alias", "cam-seed"),
            record.get("id", ""),
            json.dumps(record),
        ],
    )

    return new_id


async def run_seed(
    engine: Any,
    embedding_engine: Optional[Any] = None,
    force: bool = False,
    config: Optional[object] = None,
) -> dict[str, Any]:
    """Execute the seed import pipeline.

    1. Discover seed packs
    2. Check if seeding is needed
    3. Load records
    4. Insert each record (with dedup)
    5. Return summary
    """
    result = {"imported": 0, "skipped": 0, "rejected": 0, "errors": [], "details": [], "reason": ""}

    packs = discover_seed_packs()
    if not packs:
        result["reason"] = "no_seed_packs"
        return result

    if not await needs_seeding(engine, force=force):
        logger.debug("Seed knowledge already present — skipping")
        result["reason"] = "already_seeded"
        return result

    records = load_seed_records(packs)
    if not records:
        result["reason"] = "empty_packs"
        return result

    logger.info("Seeding %d methodologies from %d pack(s)", len(records), len(packs))

    # Ensure dedup tracking table exists
    await _ensure_community_tables(engine)

    for record in records:
        try:
            new_id = await _seed_record(record, engine, embedding_engine=embedding_engine)
            if new_id:
                result["imported"] += 1
                result["details"].append({"id": new_id, "action": "seeded"})
            else:
                result["skipped"] += 1
                result["details"].append({"id": record.get("id", "?"), "action": "skip_dedup"})
        except Exception as e:
            result["rejected"] += 1
            result["errors"].append(str(e))
            logger.warning("Failed to seed record %s: %s", record.get("id", "?"), e)

    if result["imported"] > 0:
        from claw.memory.cag_staleness import maybe_mark_cag_stale
        maybe_mark_cag_stale(config)

    logger.info(
        "Seed complete: imported=%d, skipped=%d, rejected=%d",
        result["imported"], result["skipped"], result["rejected"],
    )
    result["reason"] = "seeded"
    return result


async def repair_missing_embeddings(
    engine: Any,
    embedding_engine: Any,
    limit: int = 500,
) -> int:
    """Find methodologies with no embedding and generate them.

    Returns count of repaired records.
    """
    rows = await engine.fetch_all(
        """SELECT m.id, m.problem_description
           FROM methodologies m
           LEFT JOIN methodology_embeddings me ON m.id = me.methodology_id
           WHERE me.methodology_id IS NULL
           LIMIT ?""",
        [limit],
    )

    repaired = 0
    for row in rows:
        try:
            vec = await embedding_engine.async_encode(row["problem_description"])
            vec_bytes = struct.pack(f"<{len(vec)}f", *vec)
            await engine.execute(
                "INSERT OR IGNORE INTO methodology_embeddings (methodology_id, embedding) VALUES (?, ?)",
                [row["id"], vec_bytes],
            )
            repaired += 1
        except Exception as e:
            logger.warning("Repair embedding failed for %s: %s", row["id"], e)

    if repaired > 0:
        logger.info("Repaired %d missing embeddings", repaired)
    return repaired
