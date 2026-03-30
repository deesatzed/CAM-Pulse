"""Tests for LocalLLMConfig and CAGConfig enhancements."""
from __future__ import annotations

from claw.core.config import LocalLLMConfig


class TestLocalLLMConfig:
    def test_default_provider(self):
        cfg = LocalLLMConfig()
        assert cfg.provider == "ollama"

    def test_ctx_size_default(self):
        cfg = LocalLLMConfig()
        assert cfg.ctx_size == 32768

    def test_kv_cache_type_default(self):
        cfg = LocalLLMConfig()
        assert cfg.kv_cache_type == "f16"

    def test_custom_values(self):
        cfg = LocalLLMConfig(
            provider="atomic-chat",
            ctx_size=131072,
            kv_cache_type="turbo3",
        )
        assert cfg.provider == "atomic-chat"
        assert cfg.ctx_size == 131072
        assert cfg.kv_cache_type == "turbo3"


class TestCAGConfig:
    def test_default_disabled(self):
        from claw.core.config import CAGConfig
        cfg = CAGConfig()
        assert cfg.enabled is False

    def test_default_cache_dir(self):
        from claw.core.config import CAGConfig
        cfg = CAGConfig()
        assert cfg.cache_dir == "data/cag_caches"

    def test_default_max_methodologies(self):
        from claw.core.config import CAGConfig
        cfg = CAGConfig()
        assert cfg.max_methodologies_per_cache == 2000

    def test_custom_values(self):
        from claw.core.config import CAGConfig
        cfg = CAGConfig(enabled=True, max_methodologies_per_cache=500)
        assert cfg.enabled is True
        assert cfg.max_methodologies_per_cache == 500

    def test_cag_on_clawconfig(self):
        from claw.core.config import ClawConfig, CAGConfig
        cc = ClawConfig()
        assert isinstance(cc.cag, CAGConfig)
        assert cc.cag.enabled is False
