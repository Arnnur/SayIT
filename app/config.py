"""Application settings, read from environment variables (or a .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    return int(value) if value and value.strip() else default


def _env_str(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


@dataclass(frozen=True)
class Settings:
    # Claude. The key may be None: the SDK then falls back to other credential sources.
    anthropic_api_key: str | None = None
    claude_model: str = "claude-opus-5-5"
    claude_effort: str = "low"
    claude_fast_mode: bool = False
    claude_max_tokens: int = 32000

    # Publishing: with a Netlify token sites go to *.netlify.app, otherwise this server hosts them.
    netlify_token: str | None = None
    # Public address of this server, e.g. https://sayit.onrender.com. Empty = use the request host.
    public_base_url: str | None = None
    data_dir: Path = Path("data")

    # Images: with a Pexels key photos come from Pexels, otherwise from LoremFlickr.
    pexels_api_key: str | None = None

    # Abuse protection
    rate_limit_requests: int = 5
    rate_limit_window_seconds: int = 600
    max_concurrent_jobs: int = 3

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        return cls(
            anthropic_api_key=_env_str("ANTHROPIC_API_KEY"),
            claude_model=_env_str("CLAUDE_MODEL") or cls.claude_model,
            claude_effort=_env_str("CLAUDE_EFFORT") or cls.claude_effort,
            claude_fast_mode=_env_bool("CLAUDE_FAST_MODE", cls.claude_fast_mode),
            claude_max_tokens=_env_int("CLAUDE_MAX_TOKENS", cls.claude_max_tokens),
            netlify_token=_env_str("NETLIFY_TOKEN"),
            public_base_url=_env_str("PUBLIC_BASE_URL"),
            data_dir=Path(_env_str("DATA_DIR") or cls.data_dir),
            pexels_api_key=_env_str("PEXELS_API_KEY"),
            rate_limit_requests=_env_int("RATE_LIMIT_REQUESTS", cls.rate_limit_requests),
            rate_limit_window_seconds=_env_int(
                "RATE_LIMIT_WINDOW_SECONDS", cls.rate_limit_window_seconds
            ),
            max_concurrent_jobs=_env_int("MAX_CONCURRENT_JOBS", cls.max_concurrent_jobs),
        )
