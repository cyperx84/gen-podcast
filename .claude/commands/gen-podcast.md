---
allowed-tools: Read, Write, Edit, Bash, Grep, Glob
description: Generate a podcast from content using the gen-podcast CLI
---

# Podcast Generation Workflow

You are generating a podcast using the `gen-podcast` CLI. Follow these steps:

## 1. Gather Content

Collect the content for the podcast. Sources can be:
- Files the user points to (read them)
- Text the user provides directly
- Context from the current conversation

Combine all content into a single text block. Write it to a temporary file:

```bash
cat > /tmp/podcast_content.txt << 'CONTENT_EOF'
<paste content here>
CONTENT_EOF
```

## 2. Compose Briefing

Based on the user's intent, write a clear briefing that tells the podcast generator:
- What tone to use (casual, technical, educational)
- What to focus on or emphasize
- Any specific structure requests

## 3. Generate

Run the CLI in background mode:

```bash
gen-podcast generate \
  --content-file /tmp/podcast_content.txt \
  --briefing "Your briefing here" \
  --episode-profile casual_duo
```

This outputs JSON with a `job_id`.

## 4. Poll Status

Check progress:

```bash
gen-podcast status --latest --wait
```

This blocks until the job completes or fails.

## 5. Report Results

When complete, report to the user:
- The audio file path from the output JSON
- Offer to show the transcript
- If failed, show the error message

## Available Profiles

List profiles with: `gen-podcast profiles list`

Common episode profiles:
- `casual_duo` — Two hosts casually discussing (default)
- `tech_discussion` — Technical discussion between experts
- `solo_expert` — Single expert educational format
- `business_analysis` — Business panel discussion

## Model Overrides

Override specific models:
```bash
gen-podcast generate \
  --content-file /tmp/content.txt \
  --briefing "..." \
  --outline-provider anthropic \
  --outline-model claude-sonnet-4-20250514 \
  --tts-provider openai \
  --tts-model gpt-4o-mini-tts
```
