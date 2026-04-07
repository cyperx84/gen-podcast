"""User config file management (~/.gen-podcast/config.json)."""

from __future__ import annotations

import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".gen-podcast" / "config.json"

# Keys that can be set in config, mapped to their type for coercion
VALID_CONFIG_KEYS: dict[str, type] = {
    "episode_profile": str,
    "speaker_profile": str,
    "output_dir": str,
    "timeout": int,
    "outline_provider": str,
    "outline_model": str,
    "transcript_provider": str,
    "transcript_model": str,
    "tts_provider": str,
    "tts_model": str,
}


def load_config() -> dict:
    """Load config from ~/.gen-podcast/config.json. Returns empty dict if missing."""
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _write_config(data: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2))


def set_config(key: str, value: str) -> None:
    """Set a config key. Raises ValueError for unknown keys."""
    if key not in VALID_CONFIG_KEYS:
        raise ValueError(f"Unknown config key: {key!r}. Valid keys: {sorted(VALID_CONFIG_KEYS)}")
    coerce = VALID_CONFIG_KEYS[key]
    data = load_config()
    try:
        data[key] = coerce(value)
    except (ValueError, TypeError) as e:
        raise ValueError(f"Invalid value for {key!r}: {e}") from e
    _write_config(data)


def unset_config(key: str) -> bool:
    """Remove a key from config. Returns True if it existed."""
    if key not in VALID_CONFIG_KEYS:
        raise ValueError(f"Unknown config key: {key!r}. Valid keys: {sorted(VALID_CONFIG_KEYS)}")
    data = load_config()
    if key not in data:
        return False
    del data[key]
    _write_config(data)
    return True


def reset_config() -> None:
    """Delete the config file entirely."""
    if CONFIG_PATH.exists():
        CONFIG_PATH.unlink()
