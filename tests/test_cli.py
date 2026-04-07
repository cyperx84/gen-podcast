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
    def test_delete_existing_job(self, runner, tmp_jobs_dir):
        status_mod.create_job("to_del", {})
        result = runner.invoke(main, ["delete", "to_del"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["deleted"] == "to_del"

    def test_delete_missing_job_exits_1(self, runner, tmp_jobs_dir):
        result = runner.invoke(main, ["delete", "ghost_job"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "error" in data
