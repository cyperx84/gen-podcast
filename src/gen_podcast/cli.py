"""gen-podcast CLI — all commands."""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid

import click

from gen_podcast.config import load_config, reset_config, set_config, unset_config
from gen_podcast.profiles import init_profiles, is_valid_episode_profile, is_valid_speaker_profile, list_profiles, load_episode_profile, load_speaker_profile, validate_episode_profile, validate_speaker_profile
from gen_podcast.runner import is_job_done, run_foreground, spawn_background
from gen_podcast.status import TERMINAL_STATUSES, cleanup_jobs, create_job, delete_job, is_process_alive, latest_job, list_jobs, read_job, update_job


def _json_out(data: object) -> None:
    """Print JSON to stdout."""
    click.echo(json.dumps(data, indent=2, default=str))


def _err(msg: str) -> None:
    """Print message to stderr."""
    click.echo(msg, err=True)


@click.group()
def main() -> None:
    """gen-podcast: Podcast generation CLI for LLM agents."""
    pass


@main.command()
@click.option("--content", default=None, help="Inline content text")
@click.option("--content-file", default=None, type=click.Path(exists=True), help="Read content from file")
@click.option("--stdin", "use_stdin", is_flag=True, help="Read content from stdin")
@click.option("--briefing", default=None, help="Generation instructions")
@click.option("--briefing-file", default=None, type=click.Path(exists=True), help="Read briefing from file")
@click.option("--episode-profile", default="casual_duo", help="Episode profile name")
@click.option("--speaker-profile", default=None, help="Speaker profile name (overrides episode's speaker_config)")
@click.option("--name", default=None, help="Episode name")
@click.option("--outline-provider", default=None, help="Override outline LLM provider")
@click.option("--outline-model", default=None, help="Override outline LLM model")
@click.option("--transcript-provider", default=None, help="Override transcript LLM provider")
@click.option("--transcript-model", default=None, help="Override transcript LLM model")
@click.option("--tts-provider", default=None, help="Override TTS provider")
@click.option("--tts-model", default=None, help="Override TTS model")
@click.option("--foreground", is_flag=True, help="Run synchronously (default: background)")
@click.option("--job-id", default=None, help="Resume existing job (internal use)")
@click.option("--output-dir", default=None, type=click.Path(), help="Override output location")
@click.option("--timeout", default=3600, type=int, help="Generation timeout in seconds (0 = no timeout)")
def generate(
    content: str | None,
    content_file: str | None,
    use_stdin: bool,
    briefing: str | None,
    briefing_file: str | None,
    episode_profile: str,
    speaker_profile: str | None,
    name: str | None,
    outline_provider: str | None,
    outline_model: str | None,
    transcript_provider: str | None,
    transcript_model: str | None,
    tts_provider: str | None,
    tts_model: str | None,
    foreground: bool,
    job_id: str | None,
    output_dir: str | None,
    timeout: int,
) -> None:
    """Generate a podcast from content."""
    cfg = load_config()
    if episode_profile == "casual_duo":
        episode_profile = cfg.get("episode_profile", episode_profile)
    if speaker_profile is None:
        speaker_profile = cfg.get("speaker_profile")
    if output_dir is None:
        output_dir = cfg.get("output_dir")
    if timeout == 3600:
        timeout = int(cfg.get("timeout", timeout))
    if outline_provider is None:
        outline_provider = cfg.get("outline_provider")
    if outline_model is None:
        outline_model = cfg.get("outline_model")
    if transcript_provider is None:
        transcript_provider = cfg.get("transcript_provider")
    if transcript_model is None:
        transcript_model = cfg.get("transcript_model")
    if tts_provider is None:
        tts_provider = cfg.get("tts_provider")
    if tts_model is None:
        tts_model = cfg.get("tts_model")

    # Resolve content
    resolved_content: str | None = None
    if use_stdin:
        resolved_content = sys.stdin.read()
    elif content_file:
        with open(content_file) as f:
            resolved_content = f.read()
    elif content:
        resolved_content = content

    if not resolved_content or not resolved_content.strip():
        _json_out({"error": "No content provided. Use --content, --content-file, or --stdin."})
        sys.exit(2)

    # Resolve briefing
    if briefing_file:
        with open(briefing_file) as f:
            briefing = f.read()

    # Validate profile names early (only if not a background-resumed job)
    if not job_id:
        if not is_valid_episode_profile(episode_profile):
            _json_out({"error": f"Unknown episode profile: {episode_profile!r}. Run 'gen-podcast profiles list' to see available profiles."})
            sys.exit(2)
        if speaker_profile and not is_valid_speaker_profile(speaker_profile):
            _json_out({"error": f"Unknown speaker profile: {speaker_profile!r}. Run 'gen-podcast profiles list' to see available profiles."})
            sys.exit(2)

    # Build model overrides
    model_overrides: dict[str, str] = {}
    if outline_provider:
        model_overrides["outline_provider"] = outline_provider
    if outline_model:
        model_overrides["outline_model"] = outline_model
    if transcript_provider:
        model_overrides["transcript_provider"] = transcript_provider
    if transcript_model:
        model_overrides["transcript_model"] = transcript_model
    if tts_provider:
        model_overrides["tts_provider"] = tts_provider
    if tts_model:
        model_overrides["tts_model"] = tts_model

    if foreground:
        # Synchronous execution
        jid = job_id or uuid.uuid4().hex[:12]
        if not job_id:
            config = {
                "episode_profile": episode_profile,
                "speaker_profile": speaker_profile,
                "name": name,
                "model_overrides": model_overrides,
            }
            create_job(jid, config)

        _err(f"Running podcast generation (job {jid})...")
        result = asyncio.run(
            run_foreground(
                job_id=jid,
                content=resolved_content,
                briefing=briefing,
                episode_profile_name=episode_profile,
                speaker_profile_name=speaker_profile,
                name=name,
                model_overrides=model_overrides or None,
                output_dir=output_dir,
                timeout=timeout or None,
            )
        )
        _json_out(result)
        if result.get("status") == "failed":
            sys.exit(1)
    else:
        # Background execution
        jid = spawn_background(
            content=resolved_content if not content_file else None,
            content_file=content_file,
            briefing=briefing,
            episode_profile_name=episode_profile,
            speaker_profile_name=speaker_profile,
            name=name,
            model_overrides=model_overrides or None,
            output_dir=output_dir,
            timeout=timeout or None,
        )
        _json_out({"job_id": jid, "status": "queued"})


@main.command()
@click.argument("job_id", required=False)
@click.option("--latest", is_flag=True, help="Show the most recent job")
@click.option("--wait", is_flag=True, help="Poll until job reaches terminal state")
@click.option("--poll-interval", default=3, type=int, help="Seconds between polls (with --wait)")
def status(job_id: str | None, latest: bool, wait: bool, poll_interval: int) -> None:
    """Check job status."""
    if latest:
        job = latest_job()
        if not job:
            _json_out({"error": "No jobs found"})
            sys.exit(1)
        job_id = job.id
    elif not job_id:
        _json_out({"error": "Provide a JOB_ID or use --latest"})
        sys.exit(2)

    if wait:
        _err(f"Waiting for job {job_id}...")
        while not is_job_done(job_id):
            time.sleep(poll_interval)

    job = read_job(job_id)
    if not job:
        _json_out({"error": f"Job {job_id} not found"})
        sys.exit(1)

    # Mark zombie jobs as failed if process is no longer alive
    if job.status not in ("completed", "failed") and job.pid is not None:
        if not is_process_alive(job.pid):
            job = update_job(job.id, status="failed", error="Process died unexpectedly (PID no longer alive)")

    _json_out(job.to_dict())


@main.command(name="list")
@click.option("--status", "status_filter", default=None, help="Filter by status")
@click.option("--limit", default=20, type=int, help="Max results")
def list_cmd(status_filter: str | None, limit: int) -> None:
    """List jobs."""
    jobs = list_jobs(status_filter=status_filter, limit=limit)
    _json_out([j.to_dict() for j in jobs])


@main.command()
@click.option("--days", default=30, type=int, help="Delete jobs older than this many days")
@click.option("--all-statuses", is_flag=True, help="Include non-terminal jobs (default: terminal only)")
@click.option("--include-output", is_flag=True, help="Also delete output audio/transcript files")
def cleanup(days: int, all_statuses: bool, include_output: bool) -> None:
    """Delete old job files."""
    deleted = cleanup_jobs(older_than_days=days, terminal_only=not all_statuses, include_output=include_output)
    _json_out({"deleted": deleted, "count": len(deleted)})


@main.command()
@click.argument("job_id")
@click.option("--include-output", is_flag=True, help="Also delete output audio/transcript files")
def delete(job_id: str, include_output: bool) -> None:
    """Delete a job and its associated files."""
    job = read_job(job_id)
    if not job:
        _json_out({"error": f"Job {job_id} not found"})
        sys.exit(1)
    if job.status not in TERMINAL_STATUSES:
        _json_out({"error": f"Job {job_id} is still {job.status!r}. Only terminal jobs can be deleted."})
        sys.exit(1)
    delete_job(job_id, include_output=include_output)
    _json_out({"deleted": job_id})


@main.group()
def profiles() -> None:
    """Manage podcast profiles."""
    pass


@profiles.command(name="list")
def profiles_list() -> None:
    """List all available profiles."""
    _json_out(list_profiles())


@profiles.command(name="show")
@click.argument("name")
@click.option("--type", "profile_type", default="episode", type=click.Choice(["episode", "speaker"]))
def profiles_show(name: str, profile_type: str) -> None:
    """Show a profile's contents."""
    if profile_type == "episode":
        data = load_episode_profile(name)
    else:
        data = load_speaker_profile(name)

    if data is None:
        _json_out({"name": name, "source": "builtin", "note": "This is a podcast-creator built-in profile; no local file to display."})
    else:
        if profile_type == "episode":
            warnings = validate_episode_profile(data)
        else:
            warnings = validate_speaker_profile(data)
        if warnings:
            data = {**data, "_warnings": warnings}
        _json_out(data)


@profiles.command(name="init")
def profiles_init() -> None:
    """Copy default profiles to ~/.gen-podcast/profiles/."""
    copied = init_profiles()
    _json_out({"copied": copied, "count": len(copied)})


@main.group()
def config() -> None:
    """Manage default settings (~/.gen-podcast/config.json)."""
    pass


@config.command(name="show")
def config_show() -> None:
    """Show current config."""
    _json_out(load_config())


@config.command(name="set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a config value. Valid keys: episode_profile, speaker_profile, output_dir, timeout, outline_provider, outline_model, transcript_provider, transcript_model, tts_provider, tts_model."""
    try:
        set_config(key, value)
        _json_out({"key": key, "value": value})
    except ValueError as e:
        _json_out({"error": str(e)})
        sys.exit(2)


@config.command(name="unset")
@click.argument("key")
def config_unset(key: str) -> None:
    """Remove a config value."""
    removed = unset_config(key)
    _json_out({"key": key, "removed": removed})


@config.command(name="reset")
def config_reset() -> None:
    """Delete the config file."""
    reset_config()
    _json_out({"reset": True})


if __name__ == "__main__":
    main()
