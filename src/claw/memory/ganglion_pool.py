"""GanglionRepositoryPool — cached write-mode Repository instances for ganglion DBs.

Path C Fix 2: When federation queries return methodologies from sibling
ganglion DBs, the outcome feedback loop (retrieval + success/failure +
fitness + lifecycle) must be written back to the *source* ganglion,
not the primary ``data/claw.db``.

This pool caches one ``DatabaseEngine`` per ganglion db_path for the
lifetime of the cycle run, so we don't pay connect + apply_migrations
on every outcome.  Engines are lazily created, keyed on the resolved
absolute path, and closed together via ``close_all()`` on ctx teardown.

Thread-safety: async locks gate engine creation so concurrent tasks
accessing the same ganglion for the first time do not duplicate the
engine.  Individual SQLite writes are serialized by aiosqlite itself.

Usage::

    pool = GanglionRepositoryPool()
    repo = await pool.get_repository("/Volumes/.../instances/rust/claw.db")
    await repo.update_methodology_outcome(meth_id, success=True)
    # ...
    await pool.close_all()  # At ctx.aclose() time
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Optional

from claw.core.config import DatabaseConfig
from claw.db.engine import DatabaseEngine
from claw.db.repository import Repository

logger = logging.getLogger("claw.memory.ganglion_pool")


class GanglionRepositoryPool:
    """Caches write-mode Repository instances per ganglion DB path.

    The pool is intended to live on ``ClawContext`` for the duration of
    a cycle run.  It is **not** a connection pool — each cached entry is
    a single long-lived DatabaseEngine (one aiosqlite connection).  This
    matches the single-connection model used by the primary repository.
    """

    def __init__(self, primary_db_path: Optional[str] = None) -> None:
        """
        Args:
            primary_db_path: Absolute path to the primary ``data/claw.db``.
                When the caller asks for a repository at this path, the
                pool returns ``None`` so the caller falls back to the
                pre-existing primary Repository (no duplicate engine).
        """
        self._primary_db_path: Optional[str] = (
            str(Path(primary_db_path).resolve()) if primary_db_path else None
        )
        self._engines: dict[str, DatabaseEngine] = {}
        self._repositories: dict[str, Repository] = {}
        self._creation_lock = asyncio.Lock()

    def _normalize_path(self, db_path: str) -> str:
        """Resolve a db_path to an absolute string for consistent keying."""
        return str(Path(db_path).resolve())

    def is_primary(self, db_path: str) -> bool:
        """Return True if *db_path* points at the primary DB."""
        if not self._primary_db_path:
            return False
        return self._normalize_path(db_path) == self._primary_db_path

    async def get_repository(self, db_path: str) -> Optional[Repository]:
        """Return a cached Repository for *db_path*, creating on first access.

        Returns ``None`` if *db_path* is the primary DB — the caller must
        use the main ``ClawContext.repository`` in that case.

        Raises:
            FileNotFoundError: If the DB file does not exist.
        """
        resolved = self._normalize_path(db_path)
        if self._primary_db_path and resolved == self._primary_db_path:
            return None

        if resolved in self._repositories:
            return self._repositories[resolved]

        async with self._creation_lock:
            # Re-check under the lock in case another coroutine created it
            if resolved in self._repositories:
                return self._repositories[resolved]

            path_obj = Path(resolved)
            if not path_obj.exists():
                raise FileNotFoundError(
                    f"Ganglion DB not found: {resolved}"
                )

            db_config = DatabaseConfig(db_path=resolved)
            engine = DatabaseEngine(db_config)
            await engine.connect()
            # apply_migrations is idempotent and required before any
            # write so the methodology_fitness_log / lifecycle columns
            # exist when outcomes update them.
            await engine.apply_migrations()
            repo = Repository(engine)

            self._engines[resolved] = engine
            self._repositories[resolved] = repo
            logger.info(
                "GanglionRepositoryPool: opened write-mode engine for %s",
                resolved,
            )
            return repo

    async def close_all(self) -> None:
        """Close every cached engine.  Safe to call multiple times."""
        if not self._engines:
            return
        for resolved, engine in list(self._engines.items()):
            try:
                await engine.close()
                logger.debug(
                    "GanglionRepositoryPool: closed engine for %s",
                    resolved,
                )
            except Exception as e:
                logger.warning(
                    "GanglionRepositoryPool: error closing %s: %s",
                    resolved, e,
                )
        self._engines.clear()
        self._repositories.clear()

    def __len__(self) -> int:
        return len(self._repositories)

    def paths(self) -> list[str]:
        """Return the list of currently cached ganglion db_paths."""
        return list(self._repositories.keys())
