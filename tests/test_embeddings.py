"""Tests for CLAW embedding engine."""

import struct

from claw.db.embeddings import EmbeddingEngine


class TestEmbeddingEngine:
    def test_cosine_similarity_identical(self):
        sim = EmbeddingEngine.cosine_similarity([1, 0, 0], [1, 0, 0])
        assert abs(sim - 1.0) < 0.001

    def test_cosine_similarity_orthogonal(self):
        sim = EmbeddingEngine.cosine_similarity([1, 0, 0], [0, 1, 0])
        assert abs(sim) < 0.001

    def test_cosine_similarity_opposite(self):
        sim = EmbeddingEngine.cosine_similarity([1, 0], [-1, 0])
        assert abs(sim - (-1.0)) < 0.001

    def test_cosine_similarity_zero_vector(self):
        sim = EmbeddingEngine.cosine_similarity([0, 0, 0], [1, 0, 0])
        assert sim == 0.0


class TestSqliteVecConversion:
    def test_roundtrip(self):
        vec = [0.1, 0.2, 0.3, 0.4, 0.5]
        packed = EmbeddingEngine.to_sqlite_vec(vec)
        unpacked = EmbeddingEngine.from_sqlite_vec(packed)
        assert len(unpacked) == 5
        for a, b in zip(vec, unpacked):
            assert abs(a - b) < 0.0001

    def test_384_dim_vector(self):
        vec = [float(i) / 384 for i in range(384)]
        packed = EmbeddingEngine.to_sqlite_vec(vec)
        assert len(packed) == 384 * 4  # 4 bytes per float32
        unpacked = EmbeddingEngine.from_sqlite_vec(packed)
        assert len(unpacked) == 384

    def test_empty_vector(self):
        packed = EmbeddingEngine.to_sqlite_vec([])
        assert len(packed) == 0
        unpacked = EmbeddingEngine.from_sqlite_vec(packed)
        assert unpacked == []
