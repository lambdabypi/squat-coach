"""Environment handling.

One helper, because the same mistake bit three settings at once.

`.env` files carry keys with empty values - ours ships that way, so every variable a user has
not filled in is present-but-empty. `os.environ.get(name, default)` returns that empty string
rather than the default, so `ALLOWED_ORIGINS=` became an allowlist of `[""]`, `ANTHROPIC_MODEL=`
became a model id of `""`, and `ANTHROPIC_WORKSPACE_ID=` would have sent an empty header.

The CORS one was the expensive failure: the API answered every request correctly but without
CORS headers, and the browser reported only "Failed to fetch" - a symptom that points at the
server being down, which it wasn't.

Empty means unset. Always read environment variables through `env()`.
"""

from __future__ import annotations

import os


def env(name: str, default: str | None = None) -> str | None:
    """Return the variable's value, treating empty or whitespace-only as unset."""
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    return value if value else default


def env_list(name: str, default: list[str]) -> list[str]:
    """Comma-separated list, ignoring blank entries. Falls back to `default` if unset."""
    raw = env(name)
    if raw is None:
        return default
    items = [part.strip() for part in raw.split(",") if part.strip()]
    return items or default


def env_bool(name: str, default: bool = False) -> bool:
    raw = env(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}
