"""Tests for CAM-PULSE configuration."""

from claw.core.config import ClawConfig, PulseConfig, PulseProfileConfig, load_config


class TestPulseConfig:
    def test_pulse_config_defaults(self):
        pc = PulseConfig()
        assert pc.enabled is False
        assert pc.poll_interval_minutes == 30
        assert pc.max_scouts == 4
        assert pc.novelty_threshold == 0.70
        assert pc.max_cost_per_scan_usd == 0.50
        assert pc.max_cost_per_day_usd == 10.0
        assert pc.max_repos_per_scan == 20
        assert pc.clone_workspace == "data/pulse_clones"
        assert pc.auto_mine is True
        assert pc.auto_queue_enhance is False
        assert pc.enhance_novelty_threshold == 0.85
        assert pc.self_improve_interval_hours == 24
        assert pc.xai_model == ""
        assert pc.xai_api_key_env == "XAI_API_KEY"
        assert len(pc.keywords) >= 1

    def test_pulse_config_custom_values(self):
        pc = PulseConfig(
            enabled=True,
            poll_interval_minutes=15,
            novelty_threshold=0.80,
            xai_model="grok-3",
            keywords=["AI framework", "new tool"],
        )
        assert pc.enabled is True
        assert pc.poll_interval_minutes == 15
        assert pc.novelty_threshold == 0.80
        assert pc.xai_model == "grok-3"
        assert pc.keywords == ["AI framework", "new tool"]

    def test_claw_config_has_pulse(self):
        config = ClawConfig()
        assert hasattr(config, "pulse")
        assert isinstance(config.pulse, PulseConfig)

    def test_pulse_config_has_profile(self):
        pc = PulseConfig()
        assert hasattr(pc, "profile")
        assert isinstance(pc.profile, PulseProfileConfig)

    def test_profile_defaults(self):
        profile = PulseProfileConfig()
        assert profile.name == "general"
        assert profile.mission == ""
        assert profile.domains == []
        assert profile.novelty_bias == {}

    def test_profile_custom_values(self):
        profile = PulseProfileConfig(
            name="agent-memory",
            mission="Discover repos for agent memory",
            domains=["memory", "RAG", "vector-db"],
            novelty_bias={"memory": 0.15, "RAG": 0.10},
        )
        assert profile.name == "agent-memory"
        assert profile.mission == "Discover repos for agent memory"
        assert len(profile.domains) == 3
        assert profile.novelty_bias["memory"] == 0.15

    def test_pulse_config_with_profile(self):
        pc = PulseConfig(
            enabled=True,
            xai_model="grok-4-1-fast-non-reasoning",
            profile=PulseProfileConfig(
                name="code-quality",
                domains=["testing", "linting"],
            ),
        )
        assert pc.profile.name == "code-quality"
        assert pc.profile.domains == ["testing", "linting"]

    def test_pulse_config_from_dict(self):
        """Simulate TOML loading with nested profile."""
        data = {
            "enabled": True,
            "xai_model": "grok-4-1-fast-non-reasoning",
            "profile": {
                "name": "agent-comms",
                "mission": "Discover multi-agent repos",
                "domains": ["multi-agent", "orchestration"],
                "novelty_bias": {"orchestration": 0.15},
            },
        }
        pc = PulseConfig(**data)
        assert pc.profile.name == "agent-comms"
        assert pc.profile.novelty_bias == {"orchestration": 0.15}

    def test_load_config_includes_pulse(self):
        config = load_config()
        assert hasattr(config, "pulse")
        assert isinstance(config.pulse, PulseConfig)
        # claw.toml should have [pulse] section
        assert config.pulse.novelty_threshold == 0.70

    def test_load_config_includes_profile(self):
        config = load_config()
        assert hasattr(config.pulse, "profile")
        assert isinstance(config.pulse.profile, PulseProfileConfig)
        # claw.toml has [pulse.profile] with name = "general"
        assert config.pulse.profile.name == "general"
