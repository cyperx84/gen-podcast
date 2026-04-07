"""Podcast generation orchestration — foreground and background modes."""

from __future__ import annotations

import asyncio
import subprocess
import sys
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from gen_podcast.profiles import inject_api_keys, load_episode_profile, load_speaker_profile
from gen_podcast.status import TERMINAL_STATUSES, create_job, read_job, update_job

OUTPUT_DIR = Path.home() / ".gen-podcast" / "output"
JOBS_DIR = Path.home() / ".gen-podcast" / "jobs"

DEFAULT_TIMEOUT = 3600


def _build_config_dict(
    content_source: str,
    briefing: str | None,
    episode_profile_name: str,
    speaker_profile_name: str | None,
    name: str | None,
    model_overrides: dict | None,
) -> dict:
    """Build the config dict stored in job status."""
    return {
        "content_source": content_source,
        "briefing": briefing,
        "episode_profile": episode_profile_name,
        "speaker_profile": speaker_profile_name,
        "name": name,
        "model_overrides": model_overrides or {},
    }


async def run_foreground(
    job_id: str,
    content: str,
    briefing: str | None,
    episode_profile_name: str,
    speaker_profile_name: str | None,
    name: str | None,
    model_overrides: dict | None = None,
    output_dir: str | None = None,
    timeout: int | None = DEFAULT_TIMEOUT,
) -> dict:
    """Run podcast generation synchronously. Returns the final job status dict."""
    from podcast_creator import configure, create_podcast

    episode_name = name or job_id
    out = Path(output_dir) if output_dir else OUTPUT_DIR / job_id
    out.mkdir(parents=True, exist_ok=True)

    def _to_json_safe(obj):
        if obj is None:
            return None
        if isinstance(obj, list):
            return [_to_json_safe(i) for i in obj]
        if isinstance(obj, dict):
            return {k: _to_json_safe(v) for k, v in obj.items()}
        if hasattr(obj, "model_dump"):
            return _to_json_safe(obj.model_dump())
        if hasattr(obj, "__dict__"):
            return _to_json_safe(obj.__dict__)
        return obj

    try:
        update_job(job_id, status="running", phase="loading_profiles")

        # Load profiles
        episode = load_episode_profile(episode_profile_name)
        speaker_name = speaker_profile_name
        if not speaker_name and episode:
            speaker_name = episode.get("speaker_config")
        speaker = load_speaker_profile(speaker_name) if speaker_name else None

        # Apply model overrides
        overrides = model_overrides or {}
        if episode:
            for key in [
                "outline_provider",
                "outline_model",
                "transcript_provider",
                "transcript_model",
            ]:
                if key in overrides:
                    episode[key] = overrides[key]

        if speaker:
            for key in ["tts_provider", "tts_model"]:
                if key in overrides:
                    speaker[key] = overrides[key]

        # Inject API keys from environment
        inject_api_keys(episode, speaker)

        # Resolve briefing: explicit > episode default > generic
        effective_briefing = briefing
        if not effective_briefing and episode:
            effective_briefing = episode.get("default_briefing")
        if not effective_briefing:
            effective_briefing = "Create an engaging podcast discussion about the provided content."

        # Configure podcast-creator with profiles
        if episode:
            configure(
                "episode_config",
                {"profiles": {episode_profile_name: episode}},
            )
        if speaker and speaker_name:
            configure(
                "speakers_config",
                {"profiles": {speaker_name: speaker}},
            )

        # Generate
        update_job(job_id, status="generating_outline", phase="outline")
        coro = create_podcast(
            content=content,
            briefing=effective_briefing,
            episode_name=episode_name,
            output_dir=str(out),
            speaker_config=speaker_name or "",
            episode_profile=episode_profile_name,
        )
        if timeout is not None:
            result = await asyncio.wait_for(coro, timeout=timeout)
        else:
            result = await coro

        # Success
        output_data = {
            "audio_file": str(result.get("final_output_file_path", "")),
            "transcript": _to_json_safe(result.get("transcript")),
            "outline": _to_json_safe(result.get("outline")),
            "output_dir": str(out),
        }
        job = update_job(
            job_id,
            status="completed",
            phase=None,
            output=output_data,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        return job.to_dict()

    except asyncio.TimeoutError:
        error_msg = f"Generation timed out after {timeout} seconds"
        job = update_job(
            job_id,
            status="failed",
            phase=None,
            error=error_msg,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        return job.to_dict()

    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        job = update_job(
            job_id,
            status="failed",
            phase=None,
            error=error_msg,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        return job.to_dict()


def spawn_background(
    content: str | None,
    content_file: str | None,
    briefing: str | None,
    episode_profile_name: str,
    speaker_profile_name: str | None,
    name: str | None,
    model_overrides: dict | None = None,
    output_dir: str | None = None,
    timeout: int | None = DEFAULT_TIMEOUT,
) -> str:
    """Spawn a background generation process. Returns the job ID."""
    job_id = uuid.uuid4().hex[:12]

    config = _build_config_dict(
        content_source=content_file or "<inline>",
        briefing=briefing,
        episode_profile_name=episode_profile_name,
        speaker_profile_name=speaker_profile_name,
        name=name,
        model_overrides=model_overrides,
    )
    create_job(job_id, config)

    # Build CLI args for foreground execution
    cmd = [sys.executable, "-m", "gen_podcast.cli", "generate", "--foreground", "--job-id", job_id]

    if content_file:
        cmd.extend(["--content-file", content_file])
    elif content:
        # Write content to a temp file to avoid shell escaping issues
        tmp_content = JOBS_DIR / f"{job_id}.content"
        tmp_content.parent.mkdir(parents=True, exist_ok=True)
        tmp_content.write_text(content)
        cmd.extend(["--content-file", str(tmp_content)])

    if briefing:
        cmd.extend(["--briefing", briefing])

    cmd.extend(["--episode-profile", episode_profile_name])
    if speaker_profile_name:
        cmd.extend(["--speaker-profile", speaker_profile_name])
    if name:
        cmd.extend(["--name", name])
    if output_dir:
        cmd.extend(["--output-dir", output_dir])
    if timeout is not None:
        cmd.extend(["--timeout", str(timeout)])

    if model_overrides:
        for key, value in model_overrides.items():
            # Convert outline_provider -> --outline-provider
            flag = f"--{key.replace('_', '-')}"
            cmd.extend([flag, value])

    # Spawn detached process
    log_path = JOBS_DIR / f"{job_id}.log"
    log_file = open(log_path, "w")
    proc = subprocess.Popen(
        cmd,
        start_new_session=True,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    log_file.close()
    update_job(job_id, pid=proc.pid)

    return job_id


def is_job_done(job_id: str) -> bool:
    """Check if a job has reached a terminal state."""
    job = read_job(job_id)
    return job is not None and job.status in TERMINAL_STATUSES
