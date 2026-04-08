"""Tests for CLI commands."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from gen_podcast import status as status_mod
from gen_podcast.cli import main


@pytest.fixture(autouse=True)
def tmp_jobs_dir(tmp_path, monkeypatch):
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(status_mod, "JOBS_DIR", jobs)
    return jobs


@pytest.fixture
def runner():
    return CliRunner()


class TestGenerate:
    def test_no_content_exits_2(self, runner):
        result = runner.invoke(main, ["generate"])
        assert result.exit_code == 2
        data = json.loads(result.output)
        assert "error" in data

    def test_content_flag_foreground(self, runner, tmp_path, monkeypatch):
        """Test that foreground mode calls run_foreground and outputs JSON."""
        fake_result = {
            "id": "test123",
            "status": "completed",
            "output": {"audio_file": "/tmp/out.mp3"},
        }

        async def mock_run(**kwargs):
            return fake_result

        with patch("gen_podcast.cli.run_foreground", side_effect=mock_run):
            result = runner.invoke(
                main,
                ["generate", "--content", "Hello world", "--foreground"],
                catch_exceptions=False,
            )
        assert result.exit_code == 0
        # stdout may have stderr mixed in; find the JSON object
        output = result.output
        json_start = output.index("{")
        data = json.loads(output[json_start:])
        assert data["status"] == "completed"

    def test_content_file(self, runner, tmp_path):
        content_file = tmp_path / "article.txt"
        content_file.write_text("Some article content")

        with patch("gen_podcast.cli.spawn_background", return_value="bg123"):
            result = runner.invoke(
                main,
                ["generate", "--content-file", str(content_file)],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["job_id"] == "bg123"
        assert data["status"] == "queued"

    def test_stdin_mode(self, runner):
        with patch("gen_podcast.cli.spawn_background", return_value="stdin123"):
            result = runner.invoke(
                main,
                ["generate", "--stdin"],
                input="Content from stdin",
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["job_id"] == "stdin123"

    def test_briefing_file(self, runner, tmp_path):
        briefing_file = tmp_path / "brief.txt"
        briefing_file.write_text("discuss the content carefully")

        with patch("gen_podcast.cli.spawn_background", return_value="bf123") as spawn:
            result = runner.invoke(
                main,
                ["generate", "--content", "hi", "--briefing-file", str(briefing_file)],
            )
        assert result.exit_code == 0
        # spawn_background should receive the file's contents as briefing
        assert spawn.call_args.kwargs["briefing"] == "discuss the content carefully"

    def test_model_override_flags_forwarded(self, runner):
        with patch("gen_podcast.cli.spawn_background", return_value="mo123") as spawn:
            result = runner.invoke(
                main,
                [
                    "generate",
                    "--content", "hi",
                    "--outline-provider", "openai",
                    "--outline-model", "gpt-4",
                    "--transcript-provider", "anthropic",
                    "--transcript-model", "claude-3",
                    "--tts-provider", "elevenlabs",
                    "--tts-model", "eleven_v2",
                ],
            )
        assert result.exit_code == 0
        overrides = spawn.call_args.kwargs["model_overrides"]
        assert overrides == {
            "outline_provider": "openai",
            "outline_model": "gpt-4",
            "transcript_provider": "anthropic",
            "transcript_model": "claude-3",
            "tts_provider": "elevenlabs",
            "tts_model": "eleven_v2",
        }

    def test_foreground_failed_result_exits_1(self, runner):
        async def mock_run(**kwargs):
            return {"id": "j1", "status": "failed", "error": "boom"}

        with patch("gen_podcast.cli.run_foreground", side_effect=mock_run):
            result = runner.invoke(
                main,
                ["generate", "--content", "hi", "--foreground"],
                catch_exceptions=False,
            )
        assert result.exit_code == 1

    def test_empty_content_exits_2(self, runner):
        result = runner.invoke(main, ["generate", "--content", "   "])
        assert result.exit_code == 2
        data = json.loads(result.output)
        assert "error" in data


class TestStatus:
    def test_status_by_id(self, runner, tmp_jobs_dir):
        status_mod.create_job("j1", {"ep": "test"})
        result = runner.invoke(main, ["status", "j1"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == "j1"
        assert data["status"] == "queued"

    def test_status_missing(self, runner):
        result = runner.invoke(main, ["status", "nope"])
        assert result.exit_code == 1

    def test_status_latest(self, runner, tmp_jobs_dir):
        status_mod.create_job("a", {})
        status_mod.create_job("b", {})
        result = runner.invoke(main, ["status", "--latest"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["id"] == "b"

    def test_status_no_args(self, runner):
        result = runner.invoke(main, ["status"])
        assert result.exit_code == 2

    def test_status_latest_no_jobs(self, runner, tmp_jobs_dir):
        result = runner.invoke(main, ["status", "--latest"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "error" in data
        assert "No jobs" in data["error"]

    def test_status_wait_polls_until_done(self, runner, tmp_jobs_dir, monkeypatch):
        status_mod.create_job("wj", {})
        status_mod.update_job("wj", status="running")

        call_count = {"n": 0}

        def fake_is_done(job_id):
            call_count["n"] += 1
            if call_count["n"] >= 3:
                status_mod.update_job("wj", status="completed")
                return True
            return False

        monkeypatch.setattr("gen_podcast.cli.is_job_done", fake_is_done)
        monkeypatch.setattr("gen_podcast.cli.time.sleep", lambda s: None)

        result = runner.invoke(main, ["status", "wj", "--wait", "--poll-interval", "0"])
        assert result.exit_code == 0
        assert call_count["n"] >= 3
        # extract JSON from stdout (stderr may be mixed in)
        output = result.output
        json_start = output.index("{")
        data = json.loads(output[json_start:])
        assert data["status"] == "completed"


class TestList:
    def test_list_empty(self, runner):
        result = runner.invoke(main, ["list"])
        assert result.exit_code == 0
        assert json.loads(result.output) == []

    def test_list_returns_jobs(self, runner, tmp_jobs_dir):
        status_mod.create_job("a", {})
        status_mod.create_job("b", {})
        result = runner.invoke(main, ["list"])
        data = json.loads(result.output)
        assert len(data) == 2


class TestProfiles:
    def test_profiles_list(self, runner):
        result = runner.invoke(main, ["profiles", "list"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "episodes" in data
        assert "speakers" in data

    def test_profiles_show_builtin(self, runner):
        result = runner.invoke(main, ["profiles", "show", "tech_discussion"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["source"] == "builtin"

    def test_profiles_show_from_file(self, runner, tmp_path, monkeypatch):
        from gen_podcast import profiles as prof_mod

        defaults_dir = tmp_path / "defaults"
        (defaults_dir / "episodes").mkdir(parents=True)
        (defaults_dir / "episodes" / "fancy.json").write_text(
            json.dumps({"name": "fancy", "num_segments": 5})
        )
        (defaults_dir / "speakers").mkdir(parents=True)
        monkeypatch.setattr(prof_mod, "DEFAULTS_DIR", defaults_dir)
        monkeypatch.setattr(prof_mod, "USER_PROFILES_DIR", tmp_path / "user")

        result = runner.invoke(main, ["profiles", "show", "fancy"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["name"] == "fancy"
        assert data["num_segments"] == 5

    def test_profiles_show_speaker_type(self, runner, tmp_path, monkeypatch):
        from gen_podcast import profiles as prof_mod

        defaults_dir = tmp_path / "defaults"
        (defaults_dir / "episodes").mkdir(parents=True)
        (defaults_dir / "speakers").mkdir(parents=True)
        (defaults_dir / "speakers" / "duo.json").write_text(
            json.dumps({"voices": ["a", "b"]})
        )
        monkeypatch.setattr(prof_mod, "DEFAULTS_DIR", defaults_dir)
        monkeypatch.setattr(prof_mod, "USER_PROFILES_DIR", tmp_path / "user")

        result = runner.invoke(main, ["profiles", "show", "duo", "--type", "speaker"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["voices"] == ["a", "b"]

    def test_profiles_show_speaker_builtin(self, runner):
        result = runner.invoke(
            main, ["profiles", "show", "tech_experts", "--type", "speaker"]
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["source"] == "builtin"

    def test_profiles_init(self, runner, tmp_path, monkeypatch):
        from gen_podcast import profiles as prof_mod

        user_dir = tmp_path / "user_profiles"
        for sub in ["episodes", "speakers"]:
            (user_dir / sub).mkdir(parents=True)
        monkeypatch.setattr(prof_mod, "USER_PROFILES_DIR", user_dir)

        result = runner.invoke(main, ["profiles", "init"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "count" in data


class TestGenerateProfileValidation:
    def test_invalid_episode_profile_exits_2(self, runner, monkeypatch):
        from gen_podcast import profiles as prof_mod
        monkeypatch.setattr(prof_mod, "USER_PROFILES_DIR", Path("/nonexistent/user"))
        monkeypatch.setattr(prof_mod, "DEFAULTS_DIR", Path("/nonexistent/defaults"))
        result = runner.invoke(
            main,
            ["generate", "--content", "hello", "--episode-profile", "bogus_profile"],
        )
        assert result.exit_code == 2
        data = json.loads(result.output)
        assert "error" in data
        assert "bogus_profile" in data["error"]

    def test_invalid_speaker_profile_exits_2(self, runner, tmp_path, monkeypatch):
        from gen_podcast import profiles as prof_mod
        # Create a valid episode profile file so that passes
        defaults_dir = tmp_path / "defaults"
        (defaults_dir / "episodes").mkdir(parents=True)
        (defaults_dir / "episodes" / "casual_duo.json").write_text('{"name": "casual_duo"}')
        (defaults_dir / "speakers").mkdir(parents=True)
        monkeypatch.setattr(prof_mod, "DEFAULTS_DIR", defaults_dir)
        monkeypatch.setattr(prof_mod, "USER_PROFILES_DIR", tmp_path / "user")
        result = runner.invoke(
            main,
            ["generate", "--content", "hello", "--speaker-profile", "bogus_speaker"],
        )
        assert result.exit_code == 2
        data = json.loads(result.output)
        assert "error" in data
        assert "bogus_speaker" in data["error"]

    def test_valid_profile_proceeds(self, runner, monkeypatch):
        with patch("gen_podcast.cli.spawn_background", return_value="job123"):
            result = runner.invoke(
                main,
                ["generate", "--content", "hello"],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["job_id"] == "job123"


class TestStatusPidCheck:
    def test_dead_pid_marks_failed(self, runner, tmp_jobs_dir, monkeypatch):
        status_mod.create_job("j_dead", {})
        status_mod.update_job("j_dead", status="running", pid=99999)

        monkeypatch.setattr("gen_podcast.cli.is_process_alive", lambda pid: False)

        result = runner.invoke(main, ["status", "j_dead"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "failed"
        assert "died" in data["error"].lower() or "alive" in data["error"].lower()

    def test_alive_pid_keeps_status(self, runner, tmp_jobs_dir, monkeypatch):
        status_mod.create_job("j_alive", {})
        status_mod.update_job("j_alive", status="running", pid=12345)

        monkeypatch.setattr("gen_podcast.cli.is_process_alive", lambda pid: True)

        result = runner.invoke(main, ["status", "j_alive"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "running"


class TestCleanupCommand:
    def test_cleanup_returns_json(self, runner, tmp_jobs_dir):
        result = runner.invoke(main, ["cleanup"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "deleted" in data
        assert "count" in data

    def test_cleanup_deletes_old_jobs(self, runner, tmp_jobs_dir):
        from datetime import datetime, timezone, timedelta
        status_mod.create_job("old_job", {})
        old_time = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
        status_mod.update_job("old_job", status="completed", started_at=old_time, completed_at=old_time)

        result = runner.invoke(main, ["cleanup", "--days", "30"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 1
        assert "old_job" in data["deleted"]


class TestDeleteCommand:
    def test_delete_terminal_job(self, runner, tmp_jobs_dir):
        status_mod.create_job("to_del", {})
        status_mod.update_job("to_del", status="completed")
        result = runner.invoke(main, ["delete", "to_del"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["deleted"] == "to_del"

    def test_delete_missing_job_exits_1(self, runner, tmp_jobs_dir):
        result = runner.invoke(main, ["delete", "ghost_job"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "error" in data

    def test_delete_running_job_exits_1(self, runner, tmp_jobs_dir):
        status_mod.create_job("active_job", {})
        status_mod.update_job("active_job", status="running")
        result = runner.invoke(main, ["delete", "active_job"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "error" in data


class TestConfigCommands:
    """Tests for `gen-podcast config` subcommands."""

    @pytest.fixture(autouse=True)
    def tmp_config_path(self, tmp_path, monkeypatch):
        from gen_podcast import config as config_mod
        monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.json")
        return tmp_path / "config.json"

    def test_config_show_empty(self, runner):
        result = runner.invoke(main, ["config", "show"])
        assert result.exit_code == 0
        assert json.loads(result.output) == {}

    def test_config_set_and_show(self, runner):
        result = runner.invoke(main, ["config", "set", "episode_profile", "tech_discussion"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["key"] == "episode_profile"

        result = runner.invoke(main, ["config", "show"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["episode_profile"] == "tech_discussion"

    def test_config_set_bad_key_exits_2(self, runner):
        result = runner.invoke(main, ["config", "set", "invalid_key", "value"])
        assert result.exit_code == 2
        data = json.loads(result.output)
        assert "error" in data

    def test_config_set_bad_value_exits_2(self, runner):
        result = runner.invoke(main, ["config", "set", "timeout", "abc"])
        assert result.exit_code == 2
        data = json.loads(result.output)
        assert "error" in data

    def test_config_unset(self, runner):
        runner.invoke(main, ["config", "set", "episode_profile", "tech_discussion"])
        result = runner.invoke(main, ["config", "unset", "episode_profile"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["removed"] is True

        # Verify it's gone
        result = runner.invoke(main, ["config", "show"])
        data = json.loads(result.output)
        assert "episode_profile" not in data

    def test_config_reset(self, runner):
        runner.invoke(main, ["config", "set", "episode_profile", "tech_discussion"])
        result = runner.invoke(main, ["config", "reset"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["reset"] is True

        # Config should be empty after reset
        result = runner.invoke(main, ["config", "show"])
        data = json.loads(result.output)
        assert data == {}


class TestCleanupWithIncludeOutput:
    def test_cleanup_include_output_flag_accepted(self, runner, tmp_jobs_dir):
        from gen_podcast import status as status_mod2
        with patch("gen_podcast.cli.cleanup_jobs", return_value=[]) as mock_cleanup:
            result = runner.invoke(main, ["cleanup", "--include-output"])
        assert result.exit_code == 0
        mock_cleanup.assert_called_once()
        _, kwargs = mock_cleanup.call_args
        assert kwargs.get("include_output") is True

    def test_cleanup_without_flag_passes_false(self, runner, tmp_jobs_dir):
        with patch("gen_podcast.cli.cleanup_jobs", return_value=[]) as mock_cleanup:
            result = runner.invoke(main, ["cleanup"])
        assert result.exit_code == 0
        mock_cleanup.assert_called_once()
        _, kwargs = mock_cleanup.call_args
        assert kwargs.get("include_output") is False


class TestDeleteWithIncludeOutput:
    def test_delete_include_output_flag_accepted(self, runner, tmp_jobs_dir):
        status_mod.create_job("del_out_job", {})
        status_mod.update_job("del_out_job", status="completed")
        with patch("gen_podcast.cli.delete_job", return_value=True) as mock_del:
            result = runner.invoke(main, ["delete", "del_out_job", "--include-output"])
        assert result.exit_code == 0
        mock_del.assert_called_once_with("del_out_job", include_output=True)

    def test_delete_without_flag_passes_false(self, runner, tmp_jobs_dir):
        status_mod.create_job("del_no_out", {})
        status_mod.update_job("del_no_out", status="completed")
        with patch("gen_podcast.cli.delete_job", return_value=True) as mock_del:
            result = runner.invoke(main, ["delete", "del_no_out"])
        assert result.exit_code == 0
        mock_del.assert_called_once_with("del_no_out", include_output=False)


class TestGenerateWithConfigDefaults:
    @pytest.fixture(autouse=True)
    def tmp_config_path(self, tmp_path, monkeypatch):
        from gen_podcast import config as config_mod
        monkeypatch.setattr(config_mod, "CONFIG_PATH", tmp_path / "config.json")
        return tmp_path / "config.json"

    def test_config_episode_profile_used_when_flag_not_given(self, runner, tmp_jobs_dir, tmp_path, monkeypatch):
        from gen_podcast import config as config_mod
        # Set config default
        config_mod.set_config("episode_profile", "tech_discussion")

        with patch("gen_podcast.cli.spawn_background", return_value="cfg_job") as mock_spawn:
            result = runner.invoke(
                main,
                ["generate", "--content", "test content"],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["job_id"] == "cfg_job"

        # The episode profile from config should be passed to spawn_background
        mock_spawn.assert_called_once()
        _, kwargs = mock_spawn.call_args
        assert kwargs.get("episode_profile_name") == "tech_discussion"
