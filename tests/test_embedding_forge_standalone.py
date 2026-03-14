"""Tests for standalone Multimodal Embedding Forge."""

from __future__ import annotations

import importlib.util
import json
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


def _write_repo(repo_path: Path) -> None:
    repo_path.mkdir(parents=True, exist_ok=True)
    (repo_path / "README.md").write_text(
        "# Demo Repo\n\nMultimodal retrieval and synthesis for code and notes.\n",
        encoding="utf-8",
    )
    (repo_path / "train.py").write_text(
        "def train_model():\n    return 'anchor residual retrieval'\n",
        encoding="utf-8",
    )


class FakeEmbeddingEngine:
    def __init__(self, model, dimension, api_key_env, task_type, required_model):
        if required_model and model != required_model:
            raise RuntimeError(
                f"Embeddings model '{model}' rejected; required model is '{required_model}'"
            )
        self.dimension = dimension

    def encode_batch(self, texts):
        vectors = []
        for i, text in enumerate(texts):
            vec = [0.0] * self.dimension
            for token in text.lower().split():
                idx = (sum(ord(ch) for ch in token) + i) % self.dimension
                vec[idx] += 1.0
            vectors.append(vec)
        return vectors

    def encode(self, text):
        return self.encode_batch([text])[0]


class TestStandaloneForge:
    def test_source_has_no_cam_runtime_imports(self):
        source = Path("apps/embedding_forge/forge_standalone.py").read_text(encoding="utf-8")
        assert "from claw" not in source
        assert "import claw" not in source
        assert "sys.path.insert" not in source

    def test_required_model_rejects_non_matching_model(self):
        module = _load_module(
            "forge_standalone_model_guard",
            Path("apps/embedding_forge/forge_standalone.py").resolve(),
        )

        try:
            module.StandaloneEmbeddingEngine(
                model="gemini-embedding-001",
                dimension=16,
                api_key_env="GOOGLE_API_KEY",
                task_type="RETRIEVAL_DOCUMENT",
                required_model="gemini-embedding-2-preview",
            )
            assert False, "expected model mismatch to raise"
        except RuntimeError as exc:
            assert "required model" in str(exc)

    def test_build_showpiece_from_knowledge_pack_creates_artifacts(self, tmp_path, monkeypatch):
        module = _load_module(
            "forge_standalone_build",
            Path("apps/embedding_forge/forge_standalone.py").resolve(),
        )
        monkeypatch.setattr(module, "StandaloneEmbeddingEngine", FakeEmbeddingEngine)

        repo_path = tmp_path / "repo"
        note_path = tmp_path / "note.md"
        pack_path = tmp_path / "pack.jsonl"
        out_dir = tmp_path / "out"

        _write_repo(repo_path)
        note_path.write_text(
            "Gemini embeddings can align code, docs, and memory for retrieval.\n",
            encoding="utf-8",
        )
        pack_items = [
            {
                "id": "meth:1",
                "title": "Anchor channel method",
                "modality": "memory_methodology",
                "text": "Use anchor channels to align code with notes and memory.",
                "source": "pack:methodologies",
                "metadata": {"task_type": "architecture"},
            },
            {
                "id": "task:1",
                "title": "Create export bridge",
                "modality": "memory_task",
                "text": "Export CAM memory into a neutral knowledge pack for Forge.",
                "source": "pack:tasks",
                "metadata": {"task_type": "architecture"},
            },
        ]
        pack_path.write_text(
            "\n".join(json.dumps(item) for item in pack_items) + "\n",
            encoding="utf-8",
        )

        metrics = module.build_showpiece(
            repo_path=repo_path,
            note_path=note_path,
            cam_db_path=None,
            knowledge_pack_paths=[pack_path],
            out_dir=out_dir,
            max_methodologies=10,
            max_tasks=10,
            base_dim=24,
            anchor_dim=4,
            residual_dim=4,
            anchor_weight=1.0,
            residual_weight=1.0,
            embedding_model="gemini-embedding-2-preview",
            required_embedding_model="gemini-embedding-2-preview",
            embedding_api_key_env="GOOGLE_API_KEY",
            embedding_task_type="RETRIEVAL_DOCUMENT",
        )

        assert metrics["docs_total"] == 5
        assert metrics["embedding_model"] == "gemini-embedding-2-preview"
        assert (out_dir / "forge_metrics.json").exists()
        assert (out_dir / "forge_device_spec.json").exists()
        assert (out_dir / "forge_index.json").exists()
        assert (out_dir / "forge_report.md").exists()

        written_metrics = json.loads((out_dir / "forge_metrics.json").read_text(encoding="utf-8"))
        assert written_metrics["forge_dim"] == 8
        index_rows = json.loads((out_dir / "forge_index.json").read_text(encoding="utf-8"))
        assert len(index_rows) == 5
