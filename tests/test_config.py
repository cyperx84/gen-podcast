"""Tests for config file management."""

import json

import pytest

from gen_podcast import config as mod


@pytest.fixture(autouse=True)
def tmp_config(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "CONFIG_PATH", tmp_path / "config.json")
    return tmp_path / "config.json"


class TestLoadConfig:
    def test_returns_empty_when_file_missing(self, tmp_config):
        assert not tmp_config.exists()
        assert mod.load_config() == {}

    def test_returns_parsed_dict_when_file_exists(self, tmp_config):
        tmp_config.write_text(json.dumps({"episode_profile": "tech_discussion"}))
        result = mod.load_config()
        assert result == {"episode_profile": "tech_discussion"}

    def test_returns_empty_on_malformed_json(self, tmp_config):
        tmp_config.write_text("not valid json {{{{")
        result = mod.load_config()
        assert result == {}


class TestSetConfig:
    def test_writes_key_to_file(self, tmp_config):
        mod.set_config("episode_profile", "tech_discussion")
        assert tmp_config.exists()
        data = json.loads(tmp_config.read_text())
        assert data["episode_profile"] == "tech_discussion"

    def test_coerces_int_keys(self, tmp_config):
        mod.set_config("timeout", "120")
        data = json.loads(tmp_config.read_text())
        assert data["timeout"] == 120
        assert isinstance(data["timeout"], int)

    def test_raises_for_unknown_key(self, tmp_config):
        with pytest.raises(ValueError, match="Unknown config key"):
            mod.set_config("nonexistent_key", "value")

    def test_raises_for_unconvertible_value(self, tmp_config):
        with pytest.raises(ValueError, match="Invalid value"):
            mod.set_config("timeout", "notanint")


class TestUnsetConfig:
    def test_removes_key_returns_true(self, tmp_config):
        mod.set_config("episode_profile", "tech_discussion")
        result = mod.unset_config("episode_profile")
        assert result is True
        data = json.loads(tmp_config.read_text())
        assert "episode_profile" not in data

    def test_returns_false_for_missing_key(self, tmp_config):
        result = mod.unset_config("episode_profile")
        assert result is False

    def test_raises_for_unknown_key(self, tmp_config):
        with pytest.raises(ValueError, match="Unknown config key"):
            mod.unset_config("nonexistent_key")


class TestResetConfig:
    def test_deletes_file(self, tmp_config):
        mod.set_config("episode_profile", "tech_discussion")
        assert tmp_config.exists()
        mod.reset_config()
        assert not tmp_config.exists()

    def test_noop_if_file_missing(self, tmp_config):
        assert not tmp_config.exists()
        # Should not raise
        mod.reset_config()
        assert not tmp_config.exists()
