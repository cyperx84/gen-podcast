"""Profile loading, env var injection, and defaults management."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

USER_PROFILES_DIR = Path.home() / ".gen-podcast" / "profiles"
DEFAULTS_DIR = Path(__file__).parent / "defaults"

# podcast-creator built-in profile names (pass through without loading a file)
BUILTIN_EPISODE_PROFILES = frozenset(
    {"tech_discussion", "solo_expert", "business_analysis", "diverse_panel"}
)
BUILTIN_SPEAKER_PROFILES = frozenset(
    {"tech_experts", "solo_expert", "business_panel"}
)

# Map provider names to their API key env vars
PROVIDER_KEY_MAP = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "xai": "XAI_API_KEY",
    "elevenlabs": "ELEVENLABS_API_KEY",
}


def _find_profile(subdir: str, name: str) -> dict | None:
    """Search user dir then defaults dir for a profile JSON file."""
    for base in [USER_PROFILES_DIR, DEFAULTS_DIR]:
        path = base / subdir / f"{name}.json"
        if path.exists():
            return json.loads(path.read_text())
    return None


def load_episode_profile(name: str) -> dict | None:
    """Load an episode profile by name.

    Returns None if not found as a file, signaling that the name
    should be passed through to podcast-creator as a built-in.
    """
    return _find_profile("episodes", name)


def load_speaker_profile(name: str) -> dict | None:
    """Load a speaker profile by name.

    Returns None if not found as a file, signaling built-in usage.
    """
    return _find_profile("speakers", name)


def _inject_key_for_provider(config: dict, provider: str | None) -> None:
    """Inject API key from env for a given provider into a config dict."""
    if not provider:
        return
    env_var = PROVIDER_KEY_MAP.get(provider.lower())
    if env_var:
        key = os.environ.get(env_var)
        if key:
            config["api_key"] = key


def inject_api_keys(episode: dict | None, speaker: dict | None) -> None:
    """Inject API keys from environment into profile dicts (mutates in place)."""
    if episode:
        # Outline config
        provider = episode.get("outline_provider")
        if provider:
            outline_config = episode.setdefault("outline_config", {})
            _inject_key_for_provider(outline_config, provider)
        # Transcript config
        provider = episode.get("transcript_provider")
        if provider:
            transcript_config = episode.setdefault("transcript_config", {})
            _inject_key_for_provider(transcript_config, provider)

    if speaker:
        # TTS config
        provider = speaker.get("tts_provider")
        if provider:
            tts_config = speaker.setdefault("tts_config", {})
            _inject_key_for_provider(tts_config, provider)


def _list_profile_files(subdir: str) -> dict[str, str]:
    """List profile names and their source (user/default)."""
    profiles: dict[str, str] = {}
    # Defaults first, user overrides second
    defaults_path = DEFAULTS_DIR / subdir
    if defaults_path.exists():
        for f in defaults_path.glob("*.json"):
            profiles[f.stem] = "default"
    user_path = USER_PROFILES_DIR / subdir
    if user_path.exists():
        for f in user_path.glob("*.json"):
            profiles[f.stem] = "user"
    return profiles


def list_profiles() -> dict:
    """List all available profiles."""
    episode_files = _list_profile_files("episodes")
    speaker_files = _list_profile_files("speakers")

    # Add built-in names not already covered by files
    episodes = {
        name: episode_files.get(name, "builtin")
        for name in sorted(set(episode_files.keys()) | BUILTIN_EPISODE_PROFILES)
    }
    speakers = {
        name: speaker_files.get(name, "builtin")
        for name in sorted(set(speaker_files.keys()) | BUILTIN_SPEAKER_PROFILES)
    }
    return {"episodes": episodes, "speakers": speakers}


def init_profiles() -> list[str]:
    """Copy default profiles to user config dir. Returns list of copied files."""
    copied: list[str] = []
    for subdir in ["episodes", "speakers"]:
        src_dir = DEFAULTS_DIR / subdir
        dst_dir = USER_PROFILES_DIR / subdir
        dst_dir.mkdir(parents=True, exist_ok=True)
        if not src_dir.exists():
            continue
        for src_file in src_dir.glob("*.json"):
            dst_file = dst_dir / src_file.name
            if not dst_file.exists():
                shutil.copy2(src_file, dst_file)
                copied.append(str(dst_file))
    return copied
