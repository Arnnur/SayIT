"""Shared pytest fixtures.

Tests never call real external services: Claude is replaced by FakeGenerator,
Netlify/Pexels by httpx.MockTransport.
"""

from __future__ import annotations

import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.generator import GeneratedSite, GenerationError
from app.main import create_app

SAMPLE_HTML = """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"><title>Кофейня Арома</title></head>
<body>
  <h1>Кофейня Арома</h1>
  <img src="{{IMAGE:coffee latte art|800x600}}" alt="Латте">
</body>
</html>"""


class FakeGenerator:
    """Stands in for ClaudeGenerator: returns fixed HTML or raises."""

    def __init__(self, html: str = SAMPLE_HTML, error: Exception | None = None):
        self.html = html
        self.error = error
        self.prompts: list[str] = []

    async def generate(self, prompt, on_progress=None):
        self.prompts.append(prompt)
        if on_progress:
            on_progress(len(self.html) // 2)
            on_progress(len(self.html))
        if self.error:
            raise self.error
        return GeneratedSite(html=self.html, title="Кофейня Арома")


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(anthropic_api_key="test-key", data_dir=tmp_path / "data")


@pytest.fixture
def fake_generator() -> FakeGenerator:
    return FakeGenerator()


@pytest.fixture
def make_client(settings):
    """Factory: build a TestClient with custom generator/settings overrides."""
    clients: list[TestClient] = []

    def _make(generator=None, **overrides) -> TestClient:
        app = create_app(
            settings=replace(settings, **overrides),
            generator=generator or FakeGenerator(),
        )
        client = TestClient(app)
        client.__enter__()  # keep the event loop alive for background jobs
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)


def wait_for_job(client: TestClient, job_id: str, timeout: float = 5.0) -> dict:
    """Poll the job endpoint until it reaches a final state."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        data = client.get(f"/api/jobs/{job_id}").json()
        if data["status"] in ("done", "error"):
            return data
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} did not finish in {timeout}s")


__all__ = ["FakeGenerator", "GenerationError", "SAMPLE_HTML", "wait_for_job"]
