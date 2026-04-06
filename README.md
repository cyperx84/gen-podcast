# gen-podcast

Standalone CLI for podcast generation, designed for LLM agent consumption.

Wraps the [podcast-creator](https://github.com/lfnovo/podcast-creator) library with JSON output, file-based job tracking, and profile management.

## Install

```bash
uv sync
```

## Quick Start

```bash
# Generate a podcast (background mode)
gen-podcast generate --content "AI is transforming how we work" --briefing "casual discussion"

# Check status
gen-podcast status --latest --wait

# Generate synchronously
gen-podcast generate --content-file article.txt --briefing "deep dive" --foreground
```

## Commands

### `generate`

```
gen-podcast generate [OPTIONS]
  --content TEXT          Inline content
  --content-file PATH    Read content from file
  --stdin                Read content from stdin
  --briefing TEXT        Generation instructions
  --briefing-file PATH   Read briefing from file
  --episode-profile TEXT  Episode profile [default: casual_duo]
  --speaker-profile TEXT  Speaker profile override
  --name TEXT            Episode name
  --outline-provider     Override outline LLM provider
  --outline-model        Override outline LLM model
  --transcript-provider  Override transcript LLM provider
  --transcript-model     Override transcript LLM model
  --tts-provider         Override TTS provider
  --tts-model            Override TTS model
  --foreground           Run synchronously
  --output-dir PATH      Override output location
```

### `status`

```
gen-podcast status [JOB_ID]
  --latest     Show most recent job
  --wait       Poll until terminal state
```

### `list`

```
gen-podcast list [--status STATUS] [--limit N]
```

### `profiles`

```
gen-podcast profiles list          # List all profiles
gen-podcast profiles show NAME     # Show profile contents
gen-podcast profiles init          # Copy defaults to ~/.gen-podcast/profiles/
```

## Configuration

API keys are read from environment variables:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `GOOGLE_API_KEY`
- `GROQ_API_KEY`
- `ELEVENLABS_API_KEY`

## File Locations

```
~/.gen-podcast/
  profiles/episodes/    # User episode profiles
  profiles/speakers/    # User speaker profiles
  jobs/                 # Job status files + logs
  output/               # Generated audio + artifacts
```

## Development

```bash
uv sync
uv run pytest tests/
```
