# gen-podcast

CLI for podcast generation from any text content. Designed for both direct use and LLM agent consumption — all output is JSON, jobs run in the background with file-based tracking, and every option is flag-driven.

Wraps [podcast-creator](https://github.com/lfnovo/podcast-creator) with a persistent job system, profile management, and a clean agent-friendly interface.

---

## Installation

```bash
# Recommended: install as a global tool
uv tool install gen-podcast

# Or with pip
pip install gen-podcast
```

For development:

```bash
git clone https://github.com/cyperx/gen-podcast
cd gen-podcast
uv sync
```

---

## Quick Start

```bash
# Generate a podcast in the background (returns immediately with a job ID)
gen-podcast generate --content "The rise of agentic AI systems"

# Check on it
gen-podcast status --latest

# Wait for it to finish and get the result
gen-podcast status --latest --wait

# Generate synchronously (blocks until done)
gen-podcast generate --content-file article.txt --foreground

# Pipe content in
cat research.md | gen-podcast generate --stdin --briefing "deep technical dive"
```

---

## Commands Reference

### `generate`

Generate a podcast from content. Runs in the background by default; use `--foreground` to block.

```bash
gen-podcast generate [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--content TEXT` | — | Inline content string |
| `--content-file PATH` | — | Read content from a file |
| `--stdin` | — | Read content from stdin |
| `--briefing TEXT` | — | Instructions for tone, style, focus |
| `--briefing-file PATH` | — | Read briefing from a file |
| `--episode-profile TEXT` | `casual_duo` | Episode profile to use |
| `--speaker-profile TEXT` | — | Override episode's default speaker config |
| `--name TEXT` | — | Episode name (used in output filenames) |
| `--outline-provider TEXT` | — | Override outline LLM provider |
| `--outline-model TEXT` | — | Override outline LLM model |
| `--transcript-provider TEXT` | — | Override transcript LLM provider |
| `--transcript-model TEXT` | — | Override transcript LLM model |
| `--tts-provider TEXT` | — | Override TTS provider |
| `--tts-model TEXT` | — | Override TTS model |
| `--foreground` | `false` | Run synchronously instead of in background |
| `--timeout INT` | `3600` | Timeout in seconds (`0` = no timeout) |
| `--output-dir PATH` | — | Override output location |

Exactly one of `--content`, `--content-file`, or `--stdin` must be provided.

**Background mode** (default) — returns immediately:

```json
{
  "job_id": "a3f1c8d92b4e",
  "status": "queued"
}
```

**Foreground mode** (`--foreground`) — returns the completed job:

```json
{
  "id": "a3f1c8d92b4e",
  "status": "completed",
  "output": {
    "audio_file": "/Users/you/.gen-podcast/output/a3f1c8d92b4e/episode.mp3",
    "output_dir": "/Users/you/.gen-podcast/output/a3f1c8d92b4e",
    "transcript": [...],
    "outline": [...]
  }
}
```

---

### `status`

Check the status of a job. Detects zombie processes — if a background job's PID is no longer alive, the job is automatically marked `failed`.

```bash
gen-podcast status [JOB_ID] [OPTIONS]
```

| Flag | Description |
|------|-------------|
| `--latest` | Use the most recently created job |
| `--wait` | Poll until the job reaches a terminal state |
| `--poll-interval INT` | Seconds between polls when using `--wait` (default: `3`) |

```bash
# Check a specific job
gen-podcast status a3f1c8d92b4e

# Wait for the latest job to finish
gen-podcast status --latest --wait

# Custom poll interval
gen-podcast status --latest --wait --poll-interval 10
```

Output is the full job object (see [Job Lifecycle](#job-lifecycle)).

---

### `list`

List jobs, newest first.

```bash
gen-podcast list [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--status TEXT` | — | Filter by status (e.g. `completed`, `failed`) |
| `--limit INT` | `20` | Maximum number of results |

```bash
gen-podcast list
gen-podcast list --status failed
gen-podcast list --status completed --limit 5
```

---

### `delete`

Delete a job and its associated files (`.json`, `.log`, `.content`).

```bash
gen-podcast delete JOB_ID
```

```json
{ "deleted": "a3f1c8d92b4e" }
```

---

### `cleanup`

Delete old job files in bulk.

```bash
gen-podcast cleanup [OPTIONS]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--days INT` | `30` | Delete jobs older than this many days |
| `--all-statuses` | `false` | Include non-terminal jobs (default: terminal only) |

```bash
# Delete completed/failed jobs older than 30 days
gen-podcast cleanup

# Delete everything older than 7 days regardless of status
gen-podcast cleanup --days 7 --all-statuses
```

---

### `profiles list`

List all available profiles and their source tier.

```bash
gen-podcast profiles list
```

```json
{
  "episodes": {
    "casual_duo": "default",
    "tech_discussion": "builtin",
    "solo_expert": "builtin",
    "business_analysis": "builtin",
    "diverse_panel": "builtin",
    "my_custom": "user"
  },
  "speakers": {
    "duo": "default",
    "tech_experts": "builtin",
    "solo_expert": "builtin",
    "business_panel": "builtin"
  }
}
```

---

### `profiles show`

Print a profile's JSON configuration.

```bash
gen-podcast profiles show NAME [--type episode|speaker]
```

```bash
gen-podcast profiles show casual_duo
gen-podcast profiles show duo --type speaker
```

Built-in profiles (handled by `podcast-creator` internally) will return a note rather than a file.

---

### `profiles init`

Copy the bundled default profiles into `~/.gen-podcast/profiles/` so you can edit them.

```bash
gen-podcast profiles init
```

```json
{
  "copied": [
    "/Users/you/.gen-podcast/profiles/episodes/casual_duo.json",
    "/Users/you/.gen-podcast/profiles/speakers/duo.json"
  ],
  "count": 2
}
```

Existing files are not overwritten. Run this once, then edit the copies.

---

## Profile System

Profiles control the LLM models, TTS voices, and speaker personas used during generation. There are three tiers, resolved in this order:

| Tier | Location | Description |
|------|----------|-------------|
| `user` | `~/.gen-podcast/profiles/` | Your local customizations, highest priority |
| `default` | Bundled with `gen-podcast` | Shipped defaults (`casual_duo`, `duo`) |
| `builtin` | Inside `podcast-creator` | Library-managed profiles, no local file |

### Episode Profile Structure

Episode profiles control the outline and transcript LLMs, language, and segment count.

```json
{
  "name": "casual_duo",
  "description": "Two hosts casually discussing a topic",
  "speaker_config": "duo",
  "outline_provider": "openai",
  "outline_model": "gpt-4o",
  "transcript_provider": "openai",
  "transcript_model": "gpt-4o",
  "language": "en-US",
  "default_briefing": "Create an engaging, casual discussion between two knowledgeable hosts.",
  "num_segments": 5
}
```

### Speaker Profile Structure

Speaker profiles define TTS settings and the cast of speakers.

```json
{
  "name": "duo",
  "description": "Two complementary hosts",
  "tts_provider": "openai",
  "tts_model": "gpt-4o-mini-tts",
  "speakers": [
    {
      "name": "Alex",
      "voice_id": "nova",
      "backstory": "Tech enthusiast and educator",
      "personality": "Curious, warm, asks great follow-up questions"
    },
    {
      "name": "Sam",
      "voice_id": "echo",
      "backstory": "Industry practitioner with hands-on experience",
      "personality": "Direct, insightful, uses concrete examples"
    }
  ]
}
```

### Creating a Custom Profile

```bash
# Copy defaults to user config dir
gen-podcast profiles init

# Edit the episode profile
$EDITOR ~/.gen-podcast/profiles/episodes/casual_duo.json

# Or create a new one
cp ~/.gen-podcast/profiles/episodes/casual_duo.json \
   ~/.gen-podcast/profiles/episodes/my_profile.json

# Use it
gen-podcast generate --content "..." --episode-profile my_profile
```

---

## API Keys

API keys are read from environment variables first, then from `~/.gen-podcast/secrets/` as a fallback (one key per file, named after the lowercase env var with `_api_key` replaced by `-api-key`).

| Provider | Environment Variable | Secrets file |
|----------|---------------------|--------------|
| OpenAI | `OPENAI_API_KEY` | `~/.gen-podcast/secrets/openai-api-key` |
| Anthropic | `ANTHROPIC_API_KEY` | `~/.gen-podcast/secrets/anthropic-api-key` |
| Google | `GOOGLE_API_KEY` | `~/.gen-podcast/secrets/google-api-key` |
| Groq | `GROQ_API_KEY` | `~/.gen-podcast/secrets/groq-api-key` |
| Mistral | `MISTRAL_API_KEY` | `~/.gen-podcast/secrets/mistral-api-key` |
| DeepSeek | `DEEPSEEK_API_KEY` | `~/.gen-podcast/secrets/deepseek-api-key` |
| xAI | `XAI_API_KEY` | `~/.gen-podcast/secrets/xai-api-key` |
| ElevenLabs | `ELEVENLABS_API_KEY` | `~/.gen-podcast/secrets/elevenlabs-api-key` |

---

## Job Lifecycle

Jobs move through these states:

| Status | Terminal | Description |
|--------|----------|-------------|
| `queued` | No | Job created, background process not yet running |
| `running` | No | Process started, loading profiles |
| `generating_outline` | No | Building episode structure with LLM |
| `generating_transcript` | No | Writing dialogue with LLM |
| `generating_audio` | No | Synthesizing speech with TTS |
| `completed` | Yes | Audio file ready |
| `failed` | Yes | Error occurred (see `error` field) |

### File Locations

```
~/.gen-podcast/
  jobs/
    <job_id>.json      # Job status (atomically written)
    <job_id>.log       # stdout/stderr from background process
    <job_id>.content   # Temp file for inline content (background mode)
  output/
    <job_id>/          # Generated audio + artifacts
  profiles/
    episodes/          # User episode profiles
    speakers/          # User speaker profiles
```

### Background vs Foreground

**Background** (default): `spawn_background` forks a detached subprocess and returns the job ID immediately. The subprocess runs `generate --foreground --job-id <id>` internally. Progress is visible via `status`.

**Foreground** (`--foreground`): runs the full generation pipeline in the calling process. Useful when you need the result synchronously or want to capture output in a pipeline.

---

## LLM Agent Integration

All commands output JSON to stdout; errors and progress messages go to stderr. Exit codes: `0` success, `1` runtime error, `2` usage error.

### Typical Agent Workflow

```bash
# 1. Submit content (e.g. from a web scrape or file)
JOB=$(gen-podcast generate --stdin <<< "$CONTENT")
JOB_ID=$(echo "$JOB" | jq -r .job_id)

# 2. Poll until done (or use --wait to block)
RESULT=$(gen-podcast status "$JOB_ID" --wait)

# 3. Read the output path
AUDIO=$(echo "$RESULT" | jq -r '.output.audio_file')
```

### Using `--stdin` for Piped Content

```bash
# Pipe from any source
curl -s https://example.com/article | gen-podcast generate --stdin

# From a command
gh issue view 42 --json body -q .body | gen-podcast generate --stdin \
  --briefing "Discuss this GitHub issue and its implications"
```

### Using `--wait` for Blocking Calls

```bash
# Block until complete, then extract audio path
gen-podcast generate --content-file doc.txt --foreground \
  | jq -r '.output.audio_file'

# Or background + wait separately
gen-podcast generate --content-file doc.txt \
  | jq -r .job_id \
  | xargs -I{} gen-podcast status {} --wait \
  | jq -r '.output.audio_file'
```

### Completed Job Output Structure

```json
{
  "id": "a3f1c8d92b4e",
  "status": "completed",
  "started_at": "2025-01-15T10:00:00+00:00",
  "updated_at": "2025-01-15T10:04:32+00:00",
  "completed_at": "2025-01-15T10:04:32+00:00",
  "pid": 12345,
  "phase": null,
  "config": {
    "episode_profile": "casual_duo",
    "speaker_profile": null,
    "name": null,
    "model_overrides": {}
  },
  "output": {
    "audio_file": "/Users/you/.gen-podcast/output/a3f1c8d92b4e/episode.mp3",
    "output_dir": "/Users/you/.gen-podcast/output/a3f1c8d92b4e",
    "transcript": [...],
    "outline": [...]
  },
  "error": null
}
```

### Failed Job Output Structure

```json
{
  "id": "b7e2d1f43a8c",
  "status": "failed",
  "error": "TimeoutError: Generation timed out after 3600 seconds",
  "output": null
}
```

---

## Development

```bash
uv sync
uv run pytest tests/
```

The project uses `hatchling` as its build backend. Source lives in `src/gen_podcast/`. Default profiles are bundled at `src/gen_podcast/defaults/`.
