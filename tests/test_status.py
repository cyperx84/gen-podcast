"""Tests for job status CRUD."""

import json
from pathlib import Path

import pytest

from gen_podcast import status as mod


@pytest.fixture(autouse=True)
def tmp_jobs_dir(tmp_path, monkeypatch):
    """Redirect JOBS_DIR to a temp directory."""
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    monkeypatch.setattr(mod, "JOBS_DIR", jobs)
    return jobs


class TestCreateJob:
    def test_creates_json_file(self, tmp_jobs_dir):
        job = mod.create_job("abc123", {"episode_profile": "casual_duo"})
        assert job.id == "abc123"
        assert job.status == "queued"
        assert (tmp_jobs_dir / "abc123.json").exists()

    def test_config_stored(self, tmp_jobs_dir):
        cfg = {"episode_profile": "casual_duo", "briefing": "test"}
        job = mod.create_job("x1", cfg)
        assert job.config == cfg


class TestReadJob:
    def test_read_existing(self, tmp_jobs_dir):
        mod.create_job("j1", {})
        job = mod.read_job("j1")
        assert job is not None
        assert job.id == "j1"

    def test_read_missing(self, tmp_jobs_dir):
        assert mod.read_job("nonexistent") is None


class TestUpdateJob:
    def test_update_status(self, tmp_jobs_dir):
        mod.create_job("j1", {})
        job = mod.update_job("j1", status="running", phase="outline")
        assert job.status == "running"
        assert job.phase == "outline"

        # Verify persisted
        reloaded = mod.read_job("j1")
        assert reloaded.status == "running"

    def test_update_missing_raises(self, tmp_jobs_dir):
        with pytest.raises(ValueError, match="not found"):
            mod.update_job("nope", status="running")

    def test_update_unknown_field_raises(self, tmp_jobs_dir):
        mod.create_job("j1", {})
        with pytest.raises(ValueError, match="Unknown field"):
            mod.update_job("j1", bogus="value")


class TestListJobs:
    def test_list_empty(self, tmp_jobs_dir):
        assert mod.list_jobs() == []

    def test_list_returns_sorted(self, tmp_jobs_dir):
        mod.create_job("a", {})
        mod.create_job("b", {})
        mod.create_job("c", {})
        jobs = mod.list_jobs()
        assert len(jobs) == 3
        # Most recent first
        assert jobs[0].id == "c"

    def test_list_with_status_filter(self, tmp_jobs_dir):
        mod.create_job("a", {})
        mod.create_job("b", {})
        mod.update_job("b", status="running")
        jobs = mod.list_jobs(status_filter="running")
        assert len(jobs) == 1
        assert jobs[0].id == "b"

    def test_list_with_limit(self, tmp_jobs_dir):
        for i in range(5):
            mod.create_job(f"j{i}", {})
        assert len(mod.list_jobs(limit=2)) == 2

    def test_ignores_tmp_files(self, tmp_jobs_dir):
        mod.create_job("j1", {})
        (tmp_jobs_dir / "j1.json.tmp").write_text("{}")
        assert len(mod.list_jobs()) == 1

    def test_ignores_malformed_files(self, tmp_jobs_dir):
        mod.create_job("j1", {})
        (tmp_jobs_dir / "bad.json").write_text("not json {{{")
        assert len(mod.list_jobs()) == 1


class TestLatestJob:
    def test_latest_empty(self, tmp_jobs_dir):
        assert mod.latest_job() is None

    def test_latest_returns_most_recent(self, tmp_jobs_dir):
        mod.create_job("old", {})
        mod.create_job("new", {})
        assert mod.latest_job().id == "new"


class TestAtomicWrite:
    def test_no_tmp_file_remains(self, tmp_jobs_dir):
        mod.create_job("j1", {})
        tmp_files = list(tmp_jobs_dir.glob("*.tmp"))
        assert tmp_files == []
