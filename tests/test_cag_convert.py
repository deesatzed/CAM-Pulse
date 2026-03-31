"""Tests for cam cag convert — RAG-to-CAG conversion pipeline.

Tests the RAG adapter module (readers, auto-detect, adapter) and the
end-to-end convert flow. Chroma/LanceDB tests are conditional on their
libraries being installed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from claw.memory.rag_adapter import (
    RAGDocument,
    _dict_to_rag_doc,
    _extract_first_paragraph,
    _extract_tags,
    _infer_domain,
    adapt_to_methodologies,
    auto_detect,
    read_directory,
    read_source,
)


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestExtractFirstParagraph:
    def test_multi_paragraph(self):
        text = "First paragraph here.\n\nSecond paragraph.\n\nThird."
        assert _extract_first_paragraph(text) == "First paragraph here."

    def test_single_paragraph(self):
        text = "Just one paragraph with no double newlines."
        assert _extract_first_paragraph(text) == "Just one paragraph with no double newlines."

    def test_strips_heading_markers(self):
        text = "# My Heading\n\nParagraph content."
        assert _extract_first_paragraph(text) == "My Heading"

    def test_truncates_long_text(self):
        text = "A" * 500 + "\n\nSecond."
        result = _extract_first_paragraph(text, max_chars=200)
        assert len(result) == 200

    def test_empty_paragraphs_skipped(self):
        text = "\n\n\n\nActual content.\n\nMore."
        assert _extract_first_paragraph(text) == "Actual content."


class TestExtractTags:
    def test_tags_list(self):
        meta = {"tags": ["python", "ml", "nlp"]}
        assert _extract_tags(meta) == ["python", "ml", "nlp"]

    def test_tags_csv_string(self):
        meta = {"tags": "python, ml, nlp"}
        assert _extract_tags(meta) == ["python", "ml", "nlp"]

    def test_labels_key(self):
        meta = {"labels": ["label1", "label2"]}
        assert _extract_tags(meta) == ["label1", "label2"]

    def test_categories_key(self):
        meta = {"categories": ["cat1"]}
        assert _extract_tags(meta) == ["cat1"]

    def test_multiple_keys_combined(self):
        meta = {"tags": ["a"], "labels": ["b"], "keywords": ["c"]}
        assert _extract_tags(meta) == ["a", "b", "c"]

    def test_empty_metadata(self):
        assert _extract_tags({}) == []

    def test_none_values_skipped(self):
        meta = {"tags": None, "labels": ["x"]}
        assert _extract_tags(meta) == ["x"]


class TestInferDomain:
    def test_domain_list(self):
        meta = {"domain": ["ml", "nlp"]}
        assert _infer_domain(meta) == ["ml", "nlp"]

    def test_domain_string(self):
        meta = {"domain": "machine-learning"}
        assert _infer_domain(meta) == ["machine-learning"]

    def test_category_fallback(self):
        meta = {"category": "data-science"}
        assert _infer_domain(meta) == ["data-science"]

    def test_topic_fallback(self):
        meta = {"topic": "retrieval"}
        assert _infer_domain(meta) == ["retrieval"]

    def test_no_domain_returns_imported(self):
        assert _infer_domain({}) == ["imported"]

    def test_empty_string_skipped(self):
        meta = {"domain": ""}
        assert _infer_domain(meta) == ["imported"]


# ---------------------------------------------------------------------------
# RAGDocument adapter
# ---------------------------------------------------------------------------


class TestAdaptToMethodologies:
    def test_minimal_doc(self):
        docs = [RAGDocument(content="This is the document content.")]
        result = adapt_to_methodologies(docs)
        assert len(result) == 1
        m = result[0]
        assert m.solution_code == "This is the document content."
        assert m.problem_description == "This is the document content."
        assert m.lifecycle_state == "viable"

    def test_with_title(self):
        docs = [RAGDocument(content="Body text.", title="My Title")]
        result = adapt_to_methodologies(docs)
        assert result[0].problem_description == "My Title"

    def test_with_metadata_tags(self):
        docs = [RAGDocument(
            content="Content.",
            metadata={"tags": ["python", "rag"]},
        )]
        result = adapt_to_methodologies(docs)
        assert result[0].tags == ["python", "rag"]

    def test_fitness_score(self):
        docs = [RAGDocument(content="Content.", score=0.85)]
        result = adapt_to_methodologies(docs)
        assert result[0].fitness_vector["total"] == 0.85
        assert result[0].fitness_vector["imported"] == 0.85

    def test_default_fitness(self):
        docs = [RAGDocument(content="Content.")]
        result = adapt_to_methodologies(docs)
        assert result[0].fitness_vector["total"] == 0.5

    def test_source_in_notes(self):
        docs = [RAGDocument(content="Content.", source="/path/to/file.md")]
        result = adapt_to_methodologies(docs)
        assert "Imported from: /path/to/file.md" in result[0].methodology_notes

    def test_capability_data_has_domain(self):
        docs = [RAGDocument(
            content="Content.",
            metadata={"domain": "ml"},
        )]
        result = adapt_to_methodologies(docs)
        assert result[0].capability_data["domain"] == ["ml"]
        assert result[0].capability_data["source_format"] == "rag_import"

    def test_multiple_docs(self):
        docs = [
            RAGDocument(content="Doc 1.", title="First"),
            RAGDocument(content="Doc 2.", title="Second"),
            RAGDocument(content="Doc 3.", title="Third"),
        ]
        result = adapt_to_methodologies(docs)
        assert len(result) == 3
        assert result[0].problem_description == "First"
        assert result[2].problem_description == "Third"


# ---------------------------------------------------------------------------
# _dict_to_rag_doc
# ---------------------------------------------------------------------------


class TestDictToRagDoc:
    def test_page_content_field(self):
        obj = {"page_content": "Hello world", "metadata": {"source": "test.md"}}
        doc = _dict_to_rag_doc(obj)
        assert doc is not None
        assert doc.content == "Hello world"
        assert doc.metadata == {"source": "test.md"}

    def test_content_field(self):
        doc = _dict_to_rag_doc({"content": "Body text", "title": "My Title"})
        assert doc is not None
        assert doc.content == "Body text"
        assert doc.title == "My Title"

    def test_text_field(self):
        doc = _dict_to_rag_doc({"text": "Body text"})
        assert doc is not None
        assert doc.content == "Body text"

    def test_no_content_returns_none(self):
        doc = _dict_to_rag_doc({"id": "123", "embedding": [0.1, 0.2]})
        assert doc is None

    def test_score_extraction(self):
        doc = _dict_to_rag_doc({"content": "X", "score": 0.9})
        assert doc is not None
        assert doc.score == 0.9

    def test_score_in_metadata(self):
        doc = _dict_to_rag_doc({"content": "X", "metadata": {"relevance": 0.7}})
        assert doc is not None
        assert doc.score == 0.7


# ---------------------------------------------------------------------------
# Directory reader
# ---------------------------------------------------------------------------


class TestReadDirectory:
    def test_reads_markdown(self, tmp_path):
        (tmp_path / "doc1.md").write_text("# Title One\n\nBody of doc one.")
        (tmp_path / "doc2.md").write_text("# Title Two\n\nBody of doc two.")
        docs = read_directory(tmp_path)
        assert len(docs) == 2
        titles = {d.title for d in docs}
        assert "Title One" in titles
        assert "Title Two" in titles

    def test_reads_txt(self, tmp_path):
        (tmp_path / "notes.txt").write_text("Plain text notes here.")
        docs = read_directory(tmp_path)
        assert len(docs) == 1
        assert docs[0].content == "Plain text notes here."

    def test_json_langchain_format(self, tmp_path):
        data = [
            {"page_content": "Doc one content", "metadata": {"source": "a.pdf"}},
            {"page_content": "Doc two content", "metadata": {"source": "b.pdf"}},
        ]
        (tmp_path / "export.json").write_text(json.dumps(data))
        docs = read_directory(tmp_path)
        assert len(docs) == 2
        assert docs[0].content == "Doc one content"

    def test_json_simple_format(self, tmp_path):
        data = [
            {"content": "First doc", "title": "Doc A"},
            {"content": "Second doc", "title": "Doc B"},
        ]
        (tmp_path / "docs.json").write_text(json.dumps(data))
        docs = read_directory(tmp_path)
        assert len(docs) == 2
        assert docs[0].title == "Doc A"

    def test_filters_extensions(self, tmp_path):
        (tmp_path / "good.md").write_text("Keep this.")
        (tmp_path / "skip.py").write_text("Skip this.")
        (tmp_path / "skip.csv").write_text("Also skip.")
        docs = read_directory(tmp_path)
        assert len(docs) == 1
        assert "Keep this" in docs[0].content

    def test_recursive(self, tmp_path):
        sub = tmp_path / "subdir"
        sub.mkdir()
        (tmp_path / "top.md").write_text("Top level.")
        (sub / "nested.md").write_text("Nested document.")
        docs = read_directory(tmp_path)
        assert len(docs) == 2

    def test_skips_unreadable(self, tmp_path):
        (tmp_path / "good.md").write_text("Valid content.")
        # Create a binary file with .txt extension
        (tmp_path / "bad.txt").write_bytes(b"\x80\x81\x82\x83" * 100)
        docs = read_directory(tmp_path)
        # Should have at least the good file
        assert any("Valid content" in d.content for d in docs)

    def test_jsonl_format(self, tmp_path):
        lines = [
            json.dumps({"content": "Line one"}),
            json.dumps({"content": "Line two"}),
            json.dumps({"content": "Line three"}),
        ]
        (tmp_path / "data.json").write_text("\n".join(lines))
        docs = read_directory(tmp_path)
        assert len(docs) == 3


# ---------------------------------------------------------------------------
# Auto-detect
# ---------------------------------------------------------------------------


class TestAutoDetect:
    def test_chroma(self, tmp_path):
        (tmp_path / "chroma.sqlite3").write_text("")
        assert auto_detect(tmp_path) == "chroma"

    def test_lancedb(self, tmp_path):
        (tmp_path / "table.lance").mkdir()
        assert auto_detect(tmp_path) == "lancedb"

    def test_faiss(self, tmp_path):
        (tmp_path / "index.faiss").write_bytes(b"\x00")
        assert auto_detect(tmp_path) == "faiss"

    def test_directory_fallback(self, tmp_path):
        (tmp_path / "readme.md").write_text("Hello")
        assert auto_detect(tmp_path) == "directory"

    def test_empty_directory(self, tmp_path):
        assert auto_detect(tmp_path) == "directory"


# ---------------------------------------------------------------------------
# read_source dispatcher
# ---------------------------------------------------------------------------


class TestReadSource:
    def test_auto_detect_directory(self, tmp_path):
        (tmp_path / "doc.md").write_text("# Hello\n\nWorld")
        docs, fmt = read_source(tmp_path)
        assert fmt == "directory"
        assert len(docs) == 1

    def test_explicit_format(self, tmp_path):
        (tmp_path / "doc.md").write_text("# Hello\n\nWorld")
        docs, fmt = read_source(tmp_path, fmt="directory")
        assert fmt == "directory"
        assert len(docs) == 1

    def test_unknown_format_raises(self, tmp_path):
        with pytest.raises(ValueError, match="Unknown format"):
            read_source(tmp_path, fmt="weaviate")


# ---------------------------------------------------------------------------
# End-to-end convert pipeline
# ---------------------------------------------------------------------------


class TestEndToEndConvert:
    def test_directory_to_cag_cache(self, tmp_path):
        """Full pipeline: md files → RAGDocuments → Methodologies → CAG cache."""
        # Create source documents
        src_dir = tmp_path / "rag_source"
        src_dir.mkdir()
        for i in range(5):
            (src_dir / f"doc{i}.md").write_text(
                f"# Document {i}\n\nThis is the content of document number {i}. "
                f"It contains information about topic {i} and related subjects."
            )

        # Read and convert
        docs, fmt = read_source(src_dir)
        assert fmt == "directory"
        assert len(docs) == 5

        # Filter (all should pass with 50 char minimum)
        docs = [d for d in docs if len(d.content) >= 50]
        assert len(docs) == 5

        # Adapt to methodologies
        meths = adapt_to_methodologies(docs)
        assert len(meths) == 5

        # Verify methodology fields
        for m in meths:
            assert m.problem_description.startswith("Document")
            assert "content of document" in m.solution_code
            assert m.lifecycle_state == "viable"
            assert m.fitness_vector["total"] == 0.5
            assert m.capability_data["source_format"] == "rag_import"

    def test_min_chars_filter(self, tmp_path):
        """Short documents should be filtered out."""
        src_dir = tmp_path / "rag_source"
        src_dir.mkdir()
        (src_dir / "short.md").write_text("Tiny.")
        (src_dir / "long.md").write_text("A" * 200 + "\n\nSubstantial content here.")

        docs, _ = read_source(src_dir)
        filtered = [d for d in docs if len(d.content) >= 50]
        assert len(filtered) == 1
        assert "Substantial" in filtered[0].content or len(filtered[0].content) >= 50

    def test_max_docs_limit(self, tmp_path):
        """Max docs limit should truncate the list."""
        src_dir = tmp_path / "rag_source"
        src_dir.mkdir()
        for i in range(10):
            (src_dir / f"doc{i:02d}.md").write_text(f"# Doc {i}\n\nContent {i} here.")

        docs, _ = read_source(src_dir)
        assert len(docs) == 10
        limited = docs[:3]
        assert len(limited) == 3

    @pytest.mark.asyncio
    async def test_build_cache_with_adapted_methodologies(self, tmp_path):
        """Verify CAGRetriever.build_cache() works with adapted Methodology objects."""
        from claw.core.config import CAGConfig
        from claw.memory.cag_retriever import CAGRetriever

        # Create source
        src_dir = tmp_path / "rag_source"
        src_dir.mkdir()
        for i in range(3):
            (src_dir / f"doc{i}.md").write_text(
                f"# RAG Document {i}\n\n"
                f"This document covers topic {i} with detailed explanations "
                f"about the subject matter and practical examples."
            )

        # Read → Adapt
        docs, _ = read_source(src_dir)
        meths = adapt_to_methodologies(docs)

        # Build cache
        cache_dir = str(tmp_path / "cag_cache")
        cfg = CAGConfig(enabled=True, cache_dir=cache_dir)
        retriever = CAGRetriever(cfg)
        meta = await retriever.build_cache(ganglion="test-import", methodologies=meths)

        # Verify cache files
        assert meta["methodology_count"] == 3
        assert meta["corpus_tokens_approx"] > 0

        corpus_path = Path(cache_dir) / "test-import" / "corpus.txt"
        meta_path = Path(cache_dir) / "test-import" / "meta.json"
        assert corpus_path.exists()
        assert meta_path.exists()

        corpus = corpus_path.read_text()
        assert "RAG Document" in corpus
        assert "=== METHODOLOGY" in corpus

    @pytest.mark.asyncio
    async def test_cache_loadable_after_convert(self, tmp_path):
        """After building, the cache should be loadable via CAGRetriever."""
        from claw.core.config import CAGConfig
        from claw.memory.cag_retriever import CAGRetriever

        src_dir = tmp_path / "rag_source"
        src_dir.mkdir()
        (src_dir / "doc.md").write_text(
            "# Test Document\n\nContent for testing cache loading after convert."
        )

        docs, _ = read_source(src_dir)
        meths = adapt_to_methodologies(docs)

        cache_dir = str(tmp_path / "cag_cache")
        cfg = CAGConfig(enabled=True, cache_dir=cache_dir)
        retriever = CAGRetriever(cfg)
        await retriever.build_cache(ganglion="loadtest", methodologies=meths)

        # Load in a fresh retriever
        fresh = CAGRetriever(cfg)
        loaded = await fresh.load_cache(ganglion="loadtest")
        assert loaded is True

        status = fresh.get_status(ganglion="loadtest")
        assert status["loaded"] is True
        assert status["stale"] is False
        assert status["methodology_count"] == 1

        corpus = fresh.get_corpus(ganglion="loadtest")
        assert "Test Document" in corpus


# ---------------------------------------------------------------------------
# Chroma reader (conditional)
# ---------------------------------------------------------------------------


class TestReadChroma:
    """Tests only run if chromadb is installed."""

    @pytest.fixture(autouse=True)
    def _check_chromadb(self):
        pytest.importorskip("chromadb")

    def test_read_chroma_persistent(self, tmp_path):
        import chromadb

        db_dir = tmp_path / "chroma_db"
        db_dir.mkdir()
        client = chromadb.PersistentClient(path=str(db_dir))
        col = client.create_collection("test_docs")
        col.add(
            documents=["Document one about RAG.", "Document two about CAG.", "Document three about embeddings."],
            ids=["doc1", "doc2", "doc3"],
            metadatas=[
                {"title": "RAG Intro", "tags": "rag,retrieval"},
                {"title": "CAG Intro", "tags": "cag,cache"},
                {"title": "Embeddings", "domain": "ml"},
            ],
        )

        from claw.memory.rag_adapter import read_chroma

        docs = read_chroma(db_dir)
        assert len(docs) == 3
        contents = {d.content for d in docs}
        assert "Document one about RAG." in contents
        assert all(d.source.startswith("chroma:") for d in docs)

    def test_chroma_auto_detect(self, tmp_path):
        import chromadb

        db_dir = tmp_path / "chroma_db"
        db_dir.mkdir()
        client = chromadb.PersistentClient(path=str(db_dir))
        col = client.create_collection("test")
        col.add(documents=["Hello"], ids=["1"])

        docs, fmt = read_source(db_dir)
        assert fmt == "chroma"
        assert len(docs) == 1


# ---------------------------------------------------------------------------
# LanceDB reader (conditional)
# ---------------------------------------------------------------------------


class TestReadLanceDB:
    """Tests only run if lancedb is installed."""

    @pytest.fixture(autouse=True)
    def _check_lancedb(self):
        pytest.importorskip("lancedb")

    def test_read_lancedb_table(self, tmp_path):
        import lancedb as ldb

        db_dir = tmp_path / "lance_db"
        db = ldb.connect(str(db_dir))
        db.create_table("docs", data=[
            {"text": "LanceDB document one.", "title": "Doc 1"},
            {"text": "LanceDB document two.", "title": "Doc 2"},
        ])

        from claw.memory.rag_adapter import read_lancedb

        docs = read_lancedb(db_dir)
        assert len(docs) == 2
        assert all(d.source.startswith("lancedb:") for d in docs)
        contents = {d.content for d in docs}
        assert "LanceDB document one." in contents


# ---------------------------------------------------------------------------
# FAISS reader
# ---------------------------------------------------------------------------


class TestReadFAISS:
    def test_faiss_no_docstore_raises(self, tmp_path):
        (tmp_path / "index.faiss").write_bytes(b"\x00" * 100)

        from claw.memory.rag_adapter import read_faiss

        with pytest.raises(FileNotFoundError, match="no docstore"):
            read_faiss(tmp_path)

    def test_faiss_json_sidecar(self, tmp_path):
        (tmp_path / "index.faiss").write_bytes(b"\x00" * 100)
        data = [
            {"content": "FAISS doc one", "title": "F1"},
            {"content": "FAISS doc two", "title": "F2"},
        ]
        (tmp_path / "docstore.json").write_text(json.dumps(data))

        from claw.memory.rag_adapter import read_faiss

        docs = read_faiss(tmp_path)
        assert len(docs) == 2
        assert docs[0].content == "FAISS doc one"

    def test_faiss_jsonl_sidecar(self, tmp_path):
        (tmp_path / "index.faiss").write_bytes(b"\x00" * 100)
        lines = [
            json.dumps({"content": "Line 1"}),
            json.dumps({"content": "Line 2"}),
        ]
        (tmp_path / "documents.jsonl").write_text("\n".join(lines))

        from claw.memory.rag_adapter import read_faiss

        docs = read_faiss(tmp_path)
        assert len(docs) == 2
