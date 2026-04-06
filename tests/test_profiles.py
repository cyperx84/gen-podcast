"""Tests for profile loading and management."""

import json
from pathlib import Path

import pytest

from gen_podcast import profiles as mod


@pytest.fixture(autouse=True)
def tmp_dirs(tmp_path, monkeypatch):
    """Redirect profile dirs to temp."""
    user_dir = tmp_path / "user_profiles"
    defaults_dir = tmp_path / "defaults"
    for sub in ["episodes", "speakers"]:
        (user_dir / sub).mkdir(parents=True)
        (defaults_dir / sub).mkdir(parents=True)
    monkeypatch.setattr(mod, "USER_PROFILES_DIR", user_dir)
    monkeypatch.setattr(mod, "DEFAULTS_DIR", defaults_dir)
    return {"user": user_dir, "defaults": defaults_dir}


def _write_profile(base: Path, subdir: str, name: str, data: dict) -> None:
    (base / subdir / f"{name}.json").write_text(json.dumps(data))


class TestLoadEpisodeProfile:
    def test_loads_from_defaults(self, tmp_dirs):
        _write_profile(tmp_dirs["defaults"], "episodes", "test_ep", {"name": "test_ep"})
        result = mod.load_episode_profile("test_ep")
        assert result == {"name": "test_ep"}

    def test_user_overrides_default(self, tmp_dirs):
        _write_profile(tmp_dirs["defaults"], "episodes", "ep", {"name": "default"})
        _write_profile(tmp_dirs["user"], "episodes", "ep", {"name": "user"})
        result = mod.load_episode_profile("ep")
        assert result["name"] == "user"

    def test_returns_none_for_builtin(self, tmp_dirs):
        assert mod.load_episode_profile("tech_discussion") is None

    def test_returns_none_for_unknown(self, tmp_dirs):
        assert mod.load_episode_profile("nonexistent") is None


class TestLoadSpeakerProfile:
    def test_loads_from_defaults(self, tmp_dirs):
        _write_profile(tmp_dirs["defaults"], "speakers", "sp", {"name": "sp"})
        result = mod.load_speaker_profile("sp")
        assert result == {"name": "sp"}


class TestInjectApiKeys:
    def test_injects_openai_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        episode = {"outline_provider": "openai", "transcript_provider": "openai"}
        speaker = {"tts_provider": "openai"}
        mod.inject_api_keys(episode, speaker)
        assert episode["outline_config"]["api_key"] == "sk-test"
        assert episode["transcript_config"]["api_key"] == "sk-test"
        assert speaker["tts_config"]["api_key"] == "sk-test"

    def test_skips_missing_env_var(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        episode = {"outline_provider": "openai"}
        mod.inject_api_keys(episode, None)
        assert "outline_config" not in episode or "api_key" not in episode.get("outline_config", {})

    def test_handles_none_profiles(self):
        # Should not raise
        mod.inject_api_keys(None, None)

    def test_multiple_providers(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-anth")
        episode = {"outline_provider": "openai", "transcript_provider": "anthropic"}
        mod.inject_api_keys(episode, None)
        assert episode["outline_config"]["api_key"] == "sk-openai"
        assert episode["transcript_config"]["api_key"] == "sk-anth"


class TestListProfiles:
    def test_includes_builtins(self, tmp_dirs):
        result = mod.list_profiles()
        assert "tech_discussion" in result["episodes"]
        assert result["episodes"]["tech_discussion"] == "builtin"

    def test_includes_file_profiles(self, tmp_dirs):
        _write_profile(tmp_dirs["defaults"], "episodes", "custom", {"name": "custom"})
        result = mod.list_profiles()
        assert result["episodes"]["custom"] == "default"

    def test_user_profiles_marked(self, tmp_dirs):
        _write_profile(tmp_dirs["user"], "episodes", "mine", {"name": "mine"})
        result = mod.list_profiles()
        assert result["episodes"]["mine"] == "user"


class TestInitProfiles:
    def test_copies_defaults(self, tmp_dirs):
        _write_profile(tmp_dirs["defaults"], "episodes", "ep1", {"name": "ep1"})
        _write_profile(tmp_dirs["defaults"], "speakers", "sp1", {"name": "sp1"})
        copied = mod.init_profiles()
        assert len(copied) == 2
        assert (tmp_dirs["user"] / "episodes" / "ep1.json").exists()
        assert (tmp_dirs["user"] / "speakers" / "sp1.json").exists()

    def test_does_not_overwrite(self, tmp_dirs):
        _write_profile(tmp_dirs["defaults"], "episodes", "ep1", {"name": "default"})
        _write_profile(tmp_dirs["user"], "episodes", "ep1", {"name": "user"})
        copied = mod.init_profiles()
        assert len(copied) == 0
        data = json.loads((tmp_dirs["user"] / "episodes" / "ep1.json").read_text())
        assert data["name"] == "user"
