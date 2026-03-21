"""Tests for CAM-PULSE configuration."""

from claw.core.config import ClawConfig, PulseConfig, load_config


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

    def test_load_config_includes_pulse(self):
        config = load_config()
        assert hasattr(config, "pulse")
        assert isinstance(config.pulse, PulseConfig)
        # claw.toml should have [pulse] section
        assert config.pulse.novelty_threshold == 0.70
