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
        assert reloaded is not None
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
        latest = mod.latest_job()
        assert latest is not None
        assert latest.id == "new"


class TestAtomicWrite:
    def test_no_tmp_file_remains(self, tmp_jobs_dir):
        mod.create_job("j1", {})
        tmp_files = list(tmp_jobs_dir.glob("*.tmp"))
        assert tmp_files == []


class TestIsProcessAlive:
    def test_alive_process(self):
        import os
        # Current process is always alive
        assert mod.is_process_alive(os.getpid()) is True

    def test_dead_process(self, monkeypatch):
        def fake_kill(pid, sig):
            raise ProcessLookupError
        monkeypatch.setattr("os.kill", fake_kill)
        assert mod.is_process_alive(99999) is False

    def test_permission_error(self, monkeypatch):
        def fake_kill(pid, sig):
            raise PermissionError
        monkeypatch.setattr("os.kill", fake_kill)
        # PermissionError means process exists but we can't signal it — treat as alive
        assert mod.is_process_alive(1) is True


class TestDeleteJob:
    def test_deletes_json(self, tmp_jobs_dir):
        mod.create_job("del1", {})
        assert (tmp_jobs_dir / "del1.json").exists()
        result = mod.delete_job("del1")
        assert result is True
        assert not (tmp_jobs_dir / "del1.json").exists()

    def test_returns_false_for_missing(self, tmp_jobs_dir):
        assert mod.delete_job("ghost") is False

    def test_deletes_log_and_content(self, tmp_jobs_dir):
        mod.create_job("del2", {})
        (tmp_jobs_dir / "del2.log").write_text("log")
        (tmp_jobs_dir / "del2.content").write_text("content")
        mod.delete_job("del2")
        assert not (tmp_jobs_dir / "del2.log").exists()
        assert not (tmp_jobs_dir / "del2.content").exists()

    def test_tolerates_missing_log(self, tmp_jobs_dir):
        mod.create_job("del3", {})
        # no .log or .content file — should not raise
        result = mod.delete_job("del3")
        assert result is True


class TestCleanupJobs:
    def _make_old_job(self, job_id, days_ago, terminal=True):
        """Create a job with started_at backdated by days_ago."""
        from datetime import datetime, timezone, timedelta
        job = mod.create_job(job_id, {})
        old_time = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        if terminal:
            mod.update_job(job_id, status="completed", started_at=old_time, completed_at=old_time)
        else:
            mod.update_job(job_id, started_at=old_time)
        return job

    def test_deletes_old_terminal_jobs(self, tmp_jobs_dir):
        self._make_old_job("old1", days_ago=40, terminal=True)
        self._make_old_job("old2", days_ago=35, terminal=True)
        deleted = mod.cleanup_jobs(older_than_days=30)
        assert set(deleted) == {"old1", "old2"}
        assert not (tmp_jobs_dir / "old1.json").exists()

    def test_keeps_recent_jobs(self, tmp_jobs_dir):
        self._make_old_job("recent", days_ago=5, terminal=True)
        deleted = mod.cleanup_jobs(older_than_days=30)
        assert deleted == []
        assert (tmp_jobs_dir / "recent.json").exists()

    def test_skips_non_terminal_by_default(self, tmp_jobs_dir):
        self._make_old_job("running_old", days_ago=40, terminal=False)
        deleted = mod.cleanup_jobs(older_than_days=30, terminal_only=True)
        assert deleted == []

    def test_all_statuses_flag(self, tmp_jobs_dir):
        self._make_old_job("running_old", days_ago=40, terminal=False)
        deleted = mod.cleanup_jobs(older_than_days=30, terminal_only=False)
        assert "running_old" in deleted


@pytest.fixture
def tmp_output_dir(tmp_path, monkeypatch):
    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(mod, "OUTPUT_DIR", out)
    return out


class TestDeleteJobWithOutput:
    def test_include_output_removes_output_dir(self, tmp_jobs_dir, tmp_output_dir):
        mod.create_job("out1", {})
        mod.update_job("out1", status="completed")
        job_out = tmp_output_dir / "out1"
        job_out.mkdir()
        (job_out / "episode.mp3").write_text("audio")

        mod.delete_job("out1", include_output=True)

        assert not (tmp_jobs_dir / "out1.json").exists()
        assert not job_out.exists()

    def test_include_output_false_keeps_output_dir(self, tmp_jobs_dir, tmp_output_dir):
        mod.create_job("out2", {})
        mod.update_job("out2", status="completed")
        job_out = tmp_output_dir / "out2"
        job_out.mkdir()
        (job_out / "episode.mp3").write_text("audio")

        mod.delete_job("out2", include_output=False)

        assert not (tmp_jobs_dir / "out2.json").exists()
        assert job_out.exists()

    def test_include_output_no_output_dir_is_noop(self, tmp_jobs_dir, tmp_output_dir):
        mod.create_job("out3", {})
        mod.update_job("out3", status="completed")
        # No output dir created for this job
        result = mod.delete_job("out3", include_output=True)
        assert result is True


class TestCleanupJobsWithOutput:
    def _make_old_job(self, job_id, days_ago, terminal=True):
        from datetime import datetime, timezone, timedelta
        mod.create_job(job_id, {})
        old_time = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
        if terminal:
            mod.update_job(job_id, status="completed", started_at=old_time, completed_at=old_time)
        else:
            mod.update_job(job_id, started_at=old_time)

    def test_include_output_removes_output_dir(self, tmp_jobs_dir, tmp_output_dir):
        self._make_old_job("cln1", days_ago=40)
        job_out = tmp_output_dir / "cln1"
        job_out.mkdir()
        (job_out / "episode.mp3").write_text("audio")

        deleted = mod.cleanup_jobs(older_than_days=30, include_output=True)

        assert "cln1" in deleted
        assert not job_out.exists()

    def test_include_output_false_keeps_output_dir(self, tmp_jobs_dir, tmp_output_dir):
        self._make_old_job("cln2", days_ago=40)
        job_out = tmp_output_dir / "cln2"
        job_out.mkdir()
        (job_out / "episode.mp3").write_text("audio")

        deleted = mod.cleanup_jobs(older_than_days=30, include_output=False)

        assert "cln2" in deleted
        assert job_out.exists()

    def test_malformed_started_at_is_skipped(self, tmp_jobs_dir):
        mod.create_job("bad_date", {})
        mod.update_job("bad_date", status="completed")
        # Manually overwrite the file with a bad started_at
        job_path = tmp_jobs_dir / "bad_date.json"
        data = json.loads(job_path.read_text())
        data["started_at"] = "not-a-date"
        job_path.write_text(json.dumps(data))

        # Should not raise, should just skip the malformed job
        deleted = mod.cleanup_jobs(older_than_days=0)
        assert "bad_date" not in deleted
