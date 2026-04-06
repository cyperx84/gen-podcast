"""gen-podcast CLI — all commands."""

from __future__ import annotations

import asyncio
import json
import sys
import time

import click

from gen_podcast.profiles import init_profiles, list_profiles, load_episode_profile, load_speaker_profile
from gen_podcast.runner import is_job_done, run_foreground, spawn_background
from gen_podcast.status import latest_job, list_jobs, read_job


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
) -> None:
    """Generate a podcast from content."""
    # Resolve content
    resolved_content: str | None = None
    if use_stdin:
        resolved_content = sys.stdin.read()
    elif content_file:
        resolved_content = open(content_file).read()
    elif content:
        resolved_content = content

    if not resolved_content or not resolved_content.strip():
        _json_out({"error": "No content provided. Use --content, --content-file, or --stdin."})
        sys.exit(2)

    # Resolve briefing
    if briefing_file:
        briefing = open(briefing_file).read()

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
        import uuid

        jid = job_id or uuid.uuid4().hex[:12]
        if not job_id:
            from gen_podcast.status import create_job

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
    _json_out(job.to_dict())


@main.command(name="list")
@click.option("--status", "status_filter", default=None, help="Filter by status")
@click.option("--limit", default=20, type=int, help="Max results")
def list_cmd(status_filter: str | None, limit: int) -> None:
    """List jobs."""
    jobs = list_jobs(status_filter=status_filter, limit=limit)
    _json_out([j.to_dict() for j in jobs])


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
        _json_out(data)


@profiles.command(name="init")
def profiles_init() -> None:
    """Copy default profiles to ~/.gen-podcast/profiles/."""
    copied = init_profiles()
    _json_out({"copied": copied, "count": len(copied)})


if __name__ == "__main__":
    main()
