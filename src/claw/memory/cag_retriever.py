"""CAG (Cache-Augmented Generation) Retriever.

Precomputes methodology corpus into structured text, stores to disk,
and provides instant retrieval. Sits alongside HybridSearch as an
alternative retrieval strategy -- vectorless, zero-latency at query time.

The CAG approach:
1. build_cache() serializes top-N methodologies (by fitness) into a text corpus
2. The corpus is stored on disk and loaded into memory
3. At query time, the corpus is injected into the LLM prompt prefix (KV cache)
4. The LLM reasons over the entire corpus without any similarity search

This eliminates embedding computation and vector search latency at query time,
trading disk/memory for speed.

Cache structure on disk (inside config.cache_dir/<ganglion>/):
    corpus.txt         -- serialized methodology text
    meta.json          -- {ganglion, methodology_count, built_at, stale, corpus_tokens_approx}
"""
from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

from claw.core.config import CAGConfig
from claw.core.models import Methodology
from claw.db.repository import Repository
from claw.memory.cag_serializer import serialize_corpus
from claw.memory.fitness import get_fitness_score

logger = logging.getLogger("claw.memory.cag_retriever")


class CAGRetriever:
    """Cache-Augmented Generation retriever.

    Precomputes methodology corpus into structured text, stores to disk,
    and provides instant retrieval. Sits alongside HybridSearch as an
    alternative retrieval strategy.

    Cache structure on disk (inside config.cache_dir/<ganglion>/):
        corpus.txt         -- serialized methodology text
        meta.json          -- {ganglion, methodology_count, built_at, stale, corpus_tokens_approx}
    """

    def __init__(self, config: CAGConfig, repository: Optional[Repository] = None):
        self._config = config
        self._repository = repository
        self._loaded_corpus: dict[str, str] = {}  # ganglion -> corpus text
        self._meta: dict[str, dict] = {}  # ganglion -> meta dict

    def _cache_dir(self, ganglion: str) -> Path:
        """Return the directory path for a ganglion's cache."""
        return Path(self._config.cache_dir) / ganglion

    def _corpus_path(self, ganglion: str) -> Path:
        """Return the path to the corpus.txt file."""
        return self._cache_dir(ganglion) / "corpus.txt"

    def _meta_path(self, ganglion: str) -> Path:
        """Return the path to the meta.json file."""
        return self._cache_dir(ganglion) / "meta.json"

    async def build_cache(
        self,
        ganglion: str = "general",
        methodologies: Optional[list[Methodology]] = None,
    ) -> dict:
        """Serialize top-N methodologies by fitness, write corpus + meta to disk.

        Parameters
        ----------
        ganglion : str
            The ganglion name (namespace). Different ganglia get separate caches.
        methodologies : list[Methodology] | None
            If provided, use these methodologies instead of fetching from the
            repository. Useful for testing and CLI tooling.

        Returns
        -------
        dict
            Metadata dict with keys: ganglion, methodology_count, built_at,
            stale, corpus_tokens_approx, methodology_ids.
        """
        # 1. Get methodologies -- either provided or from repository
        if methodologies is not None:
            all_methods = methodologies
        elif self._repository is not None:
            all_methods = await self._repository.list_methodologies(
                limit=self._config.max_methodologies_per_cache * 2,
                include_dead=False,
            )
        else:
            logger.warning("No repository and no methodologies provided -- building empty cache")
            all_methods = []

        # 2. Sort by fitness score (descending) using get_fitness_score()
        sorted_methods = sorted(
            all_methods,
            key=lambda m: get_fitness_score(m),
            reverse=True,
        )

        # 3. Take top max_methodologies_per_cache
        top_methods = sorted_methods[: self._config.max_methodologies_per_cache]

        # 4. Serialize using serialize_corpus() with config.max_solution_chars
        #    Note: serialize_corpus also sorts internally, but we pre-sort so
        #    the methodology_ids list matches the corpus order.
        corpus_text = serialize_corpus(
            top_methods,
            max_count=0,  # Already limited above
            max_solution_chars=self._config.max_solution_chars,
        )

        # 5. Build metadata
        built_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        methodology_ids = [m.id for m in top_methods]
        corpus_tokens_approx = len(corpus_text) // 4

        meta = {
            "ganglion": ganglion,
            "methodology_count": len(top_methods),
            "built_at": built_at,
            "stale": False,
            "corpus_tokens_approx": corpus_tokens_approx,
            "methodology_ids": methodology_ids,
        }

        # 6. Write to disk
        cache_dir = self._cache_dir(ganglion)
        os.makedirs(str(cache_dir), exist_ok=True)

        self._corpus_path(ganglion).write_text(corpus_text, encoding="utf-8")
        self._meta_path(ganglion).write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

        # 7. Update in-memory state
        self._loaded_corpus[ganglion] = corpus_text
        self._meta[ganglion] = meta

        logger.info(
            "CAG cache built for ganglion=%s: %d methodologies, ~%d tokens",
            ganglion,
            len(top_methods),
            corpus_tokens_approx,
        )

        return meta

    async def load_cache(self, ganglion: str = "general") -> bool:
        """Load cached corpus from disk.

        Returns True if loaded successfully, False if files don't exist
        or are corrupt.
        """
        corpus_path = self._corpus_path(ganglion)
        meta_path = self._meta_path(ganglion)

        if not corpus_path.exists() or not meta_path.exists():
            logger.debug("CAG cache not found for ganglion=%s", ganglion)
            return False

        try:
            corpus_text = corpus_path.read_text(encoding="utf-8")
            meta_text = meta_path.read_text(encoding="utf-8")
            meta = json.loads(meta_text)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning(
                "Failed to load CAG cache for ganglion=%s: %s", ganglion, exc
            )
            return False

        if not isinstance(meta, dict):
            logger.warning("CAG meta.json is not a dict for ganglion=%s", ganglion)
            return False

        self._loaded_corpus[ganglion] = corpus_text
        self._meta[ganglion] = meta

        logger.info(
            "CAG cache loaded for ganglion=%s: %d methodologies, ~%d tokens",
            ganglion,
            meta.get("methodology_count", 0),
            meta.get("corpus_tokens_approx", 0),
        )

        return True

    def is_loaded(self, ganglion: str = "general") -> bool:
        """Check if corpus is loaded in memory for given ganglion."""
        return ganglion in self._loaded_corpus and bool(self._loaded_corpus[ganglion])

    def is_stale(self, ganglion: str = "general") -> bool:
        """Check if cache is marked stale.

        Returns True if:
        - No meta exists for this ganglion (never built)
        - Meta exists and stale flag is True
        """
        meta = self._meta.get(ganglion, {})
        return meta.get("stale", True)

    def mark_stale(self, ganglion: str = "general") -> None:
        """Mark cache as stale (called by mutation hooks).

        Updates both in-memory meta and the meta.json file on disk.
        If no meta exists yet, creates a minimal stale entry.
        """
        meta_path = self._meta_path(ganglion)

        # Try to read existing meta from disk
        if meta_path.exists():
            try:
                existing_text = meta_path.read_text(encoding="utf-8")
                meta = json.loads(existing_text)
                if not isinstance(meta, dict):
                    meta = {}
            except (OSError, json.JSONDecodeError, UnicodeDecodeError):
                meta = {}
        else:
            meta = {}

        # If no meta at all, create minimal stale entry
        if not meta:
            meta = {"ganglion": ganglion, "stale": True}
        else:
            meta["stale"] = True

        # Update in-memory state
        self._meta[ganglion] = meta

        # Write to disk (create directory if needed)
        cache_dir = self._cache_dir(ganglion)
        os.makedirs(str(cache_dir), exist_ok=True)
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        logger.info("CAG cache marked stale for ganglion=%s", ganglion)

    def get_status(self, ganglion: str = "general") -> dict:
        """Return cache status for reporting (cam cag status).

        Returns a dict with keys:
            ganglion, methodology_count, built_at, stale,
            corpus_tokens_approx, loaded
        """
        meta = self._meta.get(ganglion, {})
        return {
            "ganglion": ganglion,
            "methodology_count": meta.get("methodology_count", 0),
            "built_at": meta.get("built_at", None),
            "stale": meta.get("stale", True),
            "corpus_tokens_approx": meta.get("corpus_tokens_approx", 0),
            "loaded": self.is_loaded(ganglion),
        }

    def get_corpus(self, ganglion: str = "general") -> str:
        """Return the loaded corpus text. Empty string if not loaded."""
        return self._loaded_corpus.get(ganglion, "")

    def get_methodology_ids(self, ganglion: str = "general") -> list[str]:
        """Return IDs of methodologies in the cache (from meta)."""
        meta = self._meta.get(ganglion, {})
        return meta.get("methodology_ids", [])
