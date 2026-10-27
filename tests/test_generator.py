import asyncio
from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.generator import ClaudeGenerator, GenerationError, build_request_params

HTML = "<!DOCTYPE html><html><head><title>Арома</title></head><body>ok</body></html>"


class FakeStream:
    def __init__(self, chunks, stop_reason="end_turn"):
        self.chunks = chunks
        self.stop_reason = stop_reason

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def text_stream(self):
        async def gen():
            for chunk in self.chunks:
                yield chunk

        return gen()

    async def get_final_message(self):
        return SimpleNamespace(stop_reason=self.stop_reason, content=[])


class FakeClient:
    def __init__(self, stream):
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(stream=self._stream))
        self._stream_obj = stream

    def _stream(self, **params):
        self.calls.append(params)
        return self._stream_obj


def test_build_request_params_defaults():
    params = build_request_params(Settings(), "Сайт для кофейни")
    assert params["model"] == "claude-opus-5-5"
    assert params["output_config"] == {"effort": "low"}
    assert params["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in params["betas"]
    assert "speed" not in params
    assert params["messages"][-1]["role"] == "user"
    assert "Сайт для кофейни" in params["messages"][-1]["content"]
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "thinking" not in params  # adaptive thinking is the default on Opus 5.5


def test_build_request_params_fast_mode():
    params = build_request_params(replace(Settings(), claude_fast_mode=True), "x")
    assert params["speed"] == "fast"
    assert "fast-mode-2026-02-01" in params["betas"]


def test_generate_streams_progress_and_returns_site():
    client = FakeClient(FakeStream(["```html\n", HTML[:20], HTML[20:], "\n```"]))
    progress = []
    site = asyncio.run(
        ClaudeGenerator(Settings(), client=client).generate("кофейня", progress.append)
    )
    assert site.html == HTML
    assert site.title == "Арома"
    assert progress == sorted(progress) and progress[-1] > 0
    assert client.calls[0]["model"] == "claude-opus-5-5"


def test_generate_raises_on_refusal():
    client = FakeClient(FakeStream([""], stop_reason="refusal"))
    with pytest.raises(GenerationError, match="отклон"):
        asyncio.run(ClaudeGenerator(Settings(), client=client).generate("x"))


def test_generate_raises_when_no_html():
    client = FakeClient(FakeStream(["Не могу"]))
    with pytest.raises(GenerationError):
        asyncio.run(ClaudeGenerator(Settings(), client=client).generate("x"))
