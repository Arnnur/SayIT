"""Website generation with Claude (Anthropic API, streaming)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Protocol

import anthropic

from .config import Settings
from .html_utils import HtmlExtractionError, extract_html, extract_title
from .prompts import SYSTEM_PROMPT, build_user_message

logger = logging.getLogger(__name__)

FALLBACK_BETA = "server-side-fallback-2026-07-01"
FAST_MODE_BETA = "fast-mode-2026-02-01"

ProgressCallback = Callable[[int], None]


class GenerationError(RuntimeError):
    """A user-facing error: the message is shown in the UI as is."""


@dataclass(frozen=True)
class GeneratedSite:
    html: str
    title: str


class SiteGenerator(Protocol):
    async def generate(
        self, prompt: str, on_progress: ProgressCallback | None = None
    ) -> GeneratedSite: ...


def build_request_params(settings: Settings, prompt: str) -> dict[str, Any]:
    """Arguments for client.beta.messages.stream(...)."""
    betas = [FALLBACK_BETA]
    params: dict[str, Any] = {
        "model": settings.claude_model,
        "max_tokens": settings.claude_max_tokens,
        # The system prompt never changes, so it is cached between requests.
        "system": [
            {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
        ],
        "messages": [{"role": "user", "content": build_user_message(prompt)}],
        # Opus 5.5 always thinks adaptively; effort controls how much (lower = faster).
        "output_config": {"effort": settings.claude_effort},
        # If a safety classifier declines, the API retries on a recommended fallback model.
        "fallbacks": "default",
        "betas": betas,
    }
    if settings.claude_fast_mode:
        betas.append(FAST_MODE_BETA)
        params["speed"] = "fast"
    return params


class ClaudeGenerator:
    def __init__(self, settings: Settings, client: Any | None = None):
        self.settings = settings
        # AsyncAnthropic() with api_key=None resolves credentials from the environment.
        self.client = client or anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)

    async def generate(
        self, prompt: str, on_progress: ProgressCallback | None = None
    ) -> GeneratedSite:
        params = build_request_params(self.settings, prompt)
        parts: list[str] = []
        received = 0
        try:
            async with self.client.beta.messages.stream(**params) as stream:
                async for text in stream.text_stream:
                    parts.append(text)
                    received += len(text)
                    if on_progress:
                        on_progress(received)
                message = await stream.get_final_message()
        except TypeError as exc:
            # The SDK raises this before sending anything when no credentials are configured.
            if "authentication" not in str(exc):
                raise
            raise GenerationError("Не задан ANTHROPIC_API_KEY (см. .env.example)") from exc
        except anthropic.AuthenticationError as exc:
            raise GenerationError("Неверный или отсутствующий ANTHROPIC_API_KEY") from exc
        except anthropic.PermissionDeniedError as exc:
            raise GenerationError("У API-ключа нет доступа к выбранной модели") from exc
        except anthropic.RateLimitError as exc:
            raise GenerationError("ИИ перегружен запросами, попробуйте через минуту") from exc
        except anthropic.APIConnectionError as exc:
            raise GenerationError("Нет соединения с Claude API, проверьте интернет") from exc
        except anthropic.APIStatusError as exc:
            logger.exception("Claude API error")
            raise GenerationError(f"Ошибка Claude API ({exc.status_code})") from exc

        if message.stop_reason == "refusal":
            raise GenerationError("Модель отклонила этот запрос. Попробуйте описать сайт иначе.")

        try:
            html = extract_html("".join(parts))
        except HtmlExtractionError as exc:
            if message.stop_reason == "max_tokens":
                raise GenerationError(
                    "Сайт получился слишком большим. Попробуйте описать его короче."
                ) from exc
            raise GenerationError("ИИ вернул ответ без сайта. Попробуйте ещё раз.") from exc

        return GeneratedSite(html=html, title=extract_title(html))
