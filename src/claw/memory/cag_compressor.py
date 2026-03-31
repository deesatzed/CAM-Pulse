"""CAG Shorthand Compressor.

Compresses methodology text using extractive/abstractive summarization
for higher information density in the CAG corpus. Uses facebook/bart-large-cnn
when available, falls back to simple extractive compression.

Runs at build time only (during ``cam cag rebuild``), not at query time.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("claw.memory.cag_compressor")

# Lazy-load transformers to keep it optional
_summarizer = None
_summarizer_loaded = False


def _load_summarizer() -> Optional[object]:
    """Lazy-load the BART summarizer. Returns None if transformers not installed."""
    global _summarizer, _summarizer_loaded
    if _summarizer_loaded:
        return _summarizer
    _summarizer_loaded = True
    try:
        from transformers import pipeline  # type: ignore[import-untyped]

        _summarizer = pipeline(
            "summarization",
            model="facebook/bart-large-cnn",
            device=-1,  # CPU -- build time only, doesn't need GPU speed
        )
        logger.info("BART summarizer loaded for shorthand compression")
    except ImportError:
        logger.info("transformers not installed -- using fallback compression")
        _summarizer = None
    except Exception as exc:
        logger.warning("Failed to load BART summarizer: %s", exc)
        _summarizer = None
    return _summarizer


def reset_summarizer_state() -> None:
    """Reset the lazy-load state. Used by tests to allow re-loading."""
    global _summarizer, _summarizer_loaded
    _summarizer = None
    _summarizer_loaded = False


def compress_text(
    text: str,
    max_output_chars: int = 800,
    min_input_chars: int = 500,
) -> str:
    """Compress text using summarization.

    Args:
        text: Input text to compress.
        max_output_chars: Maximum characters in compressed output.
        min_input_chars: Minimum input length to bother compressing.
            Texts shorter than this are returned as-is.

    Returns:
        Compressed text, or original text if compression not available/needed.
    """
    if len(text) <= min_input_chars:
        return text

    summarizer = _load_summarizer()
    if summarizer is not None:
        return _compress_with_bart(summarizer, text, max_output_chars)
    return _compress_extractive(text, max_output_chars)


def _compress_with_bart(summarizer: object, text: str, max_output_chars: int) -> str:
    """Compress using BART summarizer."""
    # BART has a ~1024 token input limit, so chunk if needed
    max_input_chars = 4000  # ~1024 tokens
    chunks = [text[i : i + max_input_chars] for i in range(0, len(text), max_input_chars)]

    summaries: list[str] = []
    chars_so_far = 0
    for chunk in chunks:
        if chars_so_far >= max_output_chars:
            break
        try:
            result = summarizer(  # type: ignore[operator]
                chunk,
                max_length=min(200, max_output_chars - chars_so_far),
                min_length=30,
                do_sample=False,
            )
            summary = result[0]["summary_text"]
            summaries.append(summary)
            chars_so_far += len(summary)
        except Exception as exc:
            logger.debug("BART chunk compression failed: %s", exc)
            # Fallback: take first portion of the chunk
            remaining = max_output_chars - chars_so_far
            summaries.append(chunk[:remaining])
            chars_so_far += remaining

    return " ".join(summaries)


def _compress_extractive(text: str, max_output_chars: int) -> str:
    """Fallback: simple extractive compression by keeping key sentences.

    Strategy: Split into sentences, keep the first and last sentences
    (usually the most informative), then fill from the middle until budget.
    """
    import re

    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    if len(sentences) <= 2:
        return text[:max_output_chars]

    # Always keep first and last sentence
    last_sentence = sentences[-1]
    result = [sentences[0]]
    chars = len(sentences[0])

    # Add sentences from the middle until budget is exhausted
    middle = sentences[1:-1]
    for sent in middle:
        if chars + len(sent) + 1 > max_output_chars - len(last_sentence) - 1:
            break
        result.append(sent)
        chars += len(sent) + 1

    result.append(last_sentence)
    return " ".join(result)
