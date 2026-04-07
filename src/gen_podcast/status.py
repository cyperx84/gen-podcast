"""Job status file CRUD with atomic writes."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

JOBS_DIR = Path.home() / ".gen-podcast" / "jobs"

VALID_STATUSES = frozenset(
    {
        "queued",
        "running",
        "generating_outline",
        "generating_transcript",
        "generating_audio",
        "completed",
        "failed",
    }
)

TERMINAL_STATUSES = frozenset({"completed", "failed"})


@dataclass
class JobStatus:
    id: str
    status: str
    started_at: str
    updated_at: str
    phase: str | None = None
    completed_at: str | None = None
    pid: int | None = None
    config: dict = field(default_factory=dict)
    output: dict | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> JobStatus:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_process_alive(pid: int) -> bool:
    """Return True if the process with the given PID is alive.

    PermissionError means the process exists but we can't signal it (e.g. different user),
    so we conservatively treat it as alive to avoid falsely marking jobs as failed.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists, just not ours to signal


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _write_atomic(path: Path, data: dict) -> None:
    """Write JSON atomically via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def create_job(job_id: str, config: dict) -> JobStatus:
    """Create a new job in queued state."""
    now = _now_iso()
    job = JobStatus(
        id=job_id,
        status="queued",
        started_at=now,
        updated_at=now,
        config=config,
    )
    _write_atomic(_job_path(job_id), job.to_dict())
    return job


def read_job(job_id: str) -> JobStatus | None:
    """Read a single job by ID."""
    path = _job_path(job_id)
    if not path.exists():
        return None
    data = json.loads(path.read_text())
    return JobStatus.from_dict(data)


def update_job(job_id: str, **fields: object) -> JobStatus:
    """Atomic read-modify-write of job status."""
    job = read_job(job_id)
    if job is None:
        raise ValueError(f"Job {job_id} not found")
    for key, value in fields.items():
        if not hasattr(job, key):
            raise ValueError(f"Unknown field: {key}")
        setattr(job, key, value)
    job.updated_at = _now_iso()
    _write_atomic(_job_path(job_id), job.to_dict())
    return job


def list_jobs(
    status_filter: str | None = None, limit: int = 20
) -> list[JobStatus]:
    """List jobs sorted by started_at descending."""
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    jobs: list[JobStatus] = []
    for path in JOBS_DIR.glob("*.json"):
        if path.name.endswith(".tmp"):
            continue
        try:
            data = json.loads(path.read_text())
            job = JobStatus.from_dict(data)
        except (json.JSONDecodeError, TypeError):
            continue
        if status_filter and job.status != status_filter:
            continue
        jobs.append(job)
    jobs.sort(key=lambda j: j.started_at, reverse=True)
    return jobs[:limit]


def latest_job() -> JobStatus | None:
    """Return the most recently created job."""
    jobs = list_jobs(limit=1)
    return jobs[0] if jobs else None


def delete_job(job_id: str) -> bool:
    """Delete job files for the given job ID.

    Removes <job_id>.json, <job_id>.log, and <job_id>.content from JOBS_DIR.
    Returns True if the .json file existed and was deleted, False otherwise.
    """
    json_path = JOBS_DIR / f"{job_id}.json"
    existed = json_path.exists()
    for suffix in (".json", ".log", ".content"):
        path = JOBS_DIR / f"{job_id}{suffix}"
        try:
            path.unlink()
        except FileNotFoundError:
            pass
    return existed


def cleanup_jobs(older_than_days: int = 30, terminal_only: bool = True) -> list[str]:
    """Delete jobs older than the given number of days.

    Args:
        older_than_days: Age threshold in days (compared against started_at).
        terminal_only: When True, only delete jobs in TERMINAL_STATUSES.

    Returns:
        List of deleted job IDs.
    """
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now(timezone.utc).timestamp() - older_than_days * 86400
    deleted: list[str] = []
    for path in JOBS_DIR.glob("*.json"):
        if path.name.endswith(".tmp"):
            continue
        try:
            data = json.loads(path.read_text())
            job = JobStatus.from_dict(data)
        except (json.JSONDecodeError, TypeError):
            continue
        if terminal_only and job.status not in TERMINAL_STATUSES:
            continue
        started = datetime.fromisoformat(job.started_at)
        if started.timestamp() < cutoff:
            if delete_job(job.id):
                deleted.append(job.id)
    return deleted
