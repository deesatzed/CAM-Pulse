"""CAGCache — load and serve a pre-built CAG corpus.

This module provides the ``CAGCache`` class which reads a corpus and its
metadata from disk and exposes query, status, and stale-marking operations.

Zero external dependencies: only uses ``json``, ``pathlib``, and ``hashlib``
from the Python standard library.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Default values — can be overridden per-instance
DEFAULT_GANGLION = "imported"
DEFAULT_KNOWLEDGE_BUDGET = 16000


class CAGCache:
    """Load and serve a pre-built CAG corpus.

    The cache consists of two files in ``cache_dir/``:

    - ``corpus.txt``  -- serialized knowledge base text
    - ``meta.json``   -- metadata (document count, build time, stale flag)

    Parameters
    ----------
    cache_dir : str
        Path to the directory containing ``corpus.txt`` and ``meta.json``.
    ganglion : str
        Name of the ganglion (knowledge partition) this cache represents.
    """

    def __init__(
        self,
        cache_dir: str = ".",
        ganglion: str = DEFAULT_GANGLION,
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._ganglion = ganglion
        self._corpus: str = ""
        self._meta: dict = {}

    @property
    def corpus_path(self) -> Path:
        """Path to the corpus text file."""
        return self._cache_dir / "corpus.txt"

    @property
    def meta_path(self) -> Path:
        """Path to the metadata JSON file."""
        return self._cache_dir / "meta.json"

    def load(self) -> bool:
        """Load corpus and metadata from disk.

        Returns
        -------
        bool
            ``True`` if both files were read and parsed successfully,
            ``False`` otherwise.
        """
        if not self.corpus_path.exists() or not self.meta_path.exists():
            return False
        try:
            self._corpus = self.corpus_path.read_text(encoding="utf-8")
            self._meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return False
        if not isinstance(self._meta, dict):
            self._meta = {}
            return False
        return True

    def is_loaded(self) -> bool:
        """Check if the corpus is loaded in memory."""
        return bool(self._corpus)

    def is_stale(self) -> bool:
        """Check if the cache is marked stale (needs rebuild)."""
        return self._meta.get("stale", True)

    def get_corpus(self) -> str:
        """Return the loaded corpus text. Empty string if not loaded."""
        return self._corpus

    def get_status(self) -> dict:
        """Return cache status as a dict.

        Keys returned:
        - ``ganglion``: partition name
        - ``methodology_count``: number of methodologies in the corpus
        - ``built_at``: ISO timestamp of when the cache was built
        - ``stale``: whether the cache needs rebuilding
        - ``corpus_tokens_approx``: approximate token count
        - ``loaded``: whether the corpus is in memory
        - ``pointer_count``: number of pointer references
        - ``shorthand_compression``: whether shorthand was applied
        """
        return {
            "ganglion": self._ganglion,
            "methodology_count": self._meta.get("methodology_count", 0),
            "built_at": self._meta.get("built_at", None),
            "stale": self._meta.get("stale", True),
            "corpus_tokens_approx": self._meta.get("corpus_tokens_approx", 0),
            "loaded": self.is_loaded(),
            "pointer_count": self._meta.get("pointer_count", 0),
            "shorthand_compression": self._meta.get("shorthand_compression", False),
        }

    def mark_stale(self) -> None:
        """Mark the cache as stale on disk.

        Call this from any code path that mutates your knowledge base
        (document ingestion, deletion, re-ranking) so the cache is
        rebuilt on next startup.

        Preserves all existing metadata fields and only sets
        ``stale`` to ``True``.
        """
        self.meta_path.parent.mkdir(parents=True, exist_ok=True)

        meta: dict = {}
        if self.meta_path.exists():
            try:
                meta = json.loads(self.meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                meta = {}
        if not isinstance(meta, dict):
            meta = {}

        meta["ganglion"] = self._ganglion
        meta["stale"] = True
        self.meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        self._meta = meta

    def corpus_hash(self) -> str:
        """Return a short MD5 hash of the corpus for cache-hit tracking.

        Returns
        -------
        str
            12-character hex digest prefix. Empty string if no corpus loaded.
        """
        if not self._corpus:
            return ""
        return hashlib.md5(self._corpus.encode()).hexdigest()[:12]
