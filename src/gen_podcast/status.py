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
