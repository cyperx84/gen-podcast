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
