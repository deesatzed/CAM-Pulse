from __future__ import annotations

import asyncio

from claw.cli import _required_api_keys_for_command
from claw.core.config import load_config


class TestKeycheckHelpers:
    def test_mine_requires_openrouter_and_embedding_key_for_current_config(self):
        cfg = load_config()

        requirements = _required_api_keys_for_command(cfg, "mine")

        assert ("OPENROUTER_API_KEY", "OpenRouter LLM access") in requirements
        assert ("GOOGLE_API_KEY", "Gemini embeddings for methodology persistence") in requirements

    def test_ideate_requires_openrouter_only(self):
        cfg = load_config()

        requirements = _required_api_keys_for_command(cfg, "ideate")

        assert requirements == [("OPENROUTER_API_KEY", "OpenRouter LLM access")]

    def test_run_live_key_checks_success(self, monkeypatch):
        from claw import cli
        import claw.db.embeddings as embeddings_mod
        import claw.llm.client as llm_mod

        cfg = load_config()

        class FakeResponse:
            content = "OK"

        class FakeLLMClient:
            def __init__(self, config):
                self.config = config

            async def complete(self, **kwargs):
                return FakeResponse()

            async def close(self):
                return None

        class FakeEmbeddingEngine:
            def __init__(self, config):
                self.config = config
                self.model_name = config.model

            def encode(self, text):
                return [0.1] * self.config.dimension

        monkeypatch.setattr(cli, "_required_api_keys_for_command", lambda config, command_name: [
            ("OPENROUTER_API_KEY", "OpenRouter LLM access"),
            ("GOOGLE_API_KEY", "Gemini embeddings for methodology persistence"),
        ])
        monkeypatch.setattr(llm_mod, "LLMClient", FakeLLMClient)
        monkeypatch.setattr(embeddings_mod, "EmbeddingEngine", FakeEmbeddingEngine)

        results = asyncio.run(cli._run_live_key_checks(cfg, "mine"))

        assert results[0]["service"] == "OpenRouter"
        assert results[0]["status"] == "ok"
        assert results[1]["service"] == "Gemini embeddings"
        assert results[1]["status"] == "ok"

    def test_run_live_key_checks_failure(self, monkeypatch):
        from claw import cli
        import claw.db.embeddings as embeddings_mod
        import claw.llm.client as llm_mod

        cfg = load_config()

        class FakeLLMClient:
            def __init__(self, config):
                self.config = config

            async def complete(self, **kwargs):
                raise RuntimeError("bad openrouter key")

            async def close(self):
                return None

        class FakeEmbeddingEngine:
            def __init__(self, config):
                self.config = config

            def encode(self, text):
                raise RuntimeError("bad google key")

        monkeypatch.setattr(cli, "_required_api_keys_for_command", lambda config, command_name: [
            ("OPENROUTER_API_KEY", "OpenRouter LLM access"),
            ("GOOGLE_API_KEY", "Gemini embeddings for methodology persistence"),
        ])
        monkeypatch.setattr(llm_mod, "LLMClient", FakeLLMClient)
        monkeypatch.setattr(embeddings_mod, "EmbeddingEngine", FakeEmbeddingEngine)

        results = asyncio.run(cli._run_live_key_checks(cfg, "mine"))

        assert results[0]["status"] == "failed"
        assert "bad openrouter key" in results[0]["detail"]
        assert results[1]["status"] == "failed"
        assert "bad google key" in results[1]["detail"]
