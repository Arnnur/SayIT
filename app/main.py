"""FastAPI application: HTTP routes that glue all modules together."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StringConstraints

from .config import Settings
from .generator import ClaudeGenerator, SiteGenerator
from .jobs import JobManager
from .publisher import LocalPublisher, NetlifyPublisher, SiteStore, is_valid_site_id
from .qr import make_qr_png
from .rate_limit import RateLimiter

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

# Generated pages run in a sandbox: their scripts get an opaque origin and can't
# touch this service (its API, cookies, storage) even though they share our domain.
SITE_CSP = "sandbox allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox allow-modals"

Prompt = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=2000)]


class GenerateRequest(BaseModel):
    prompt: Prompt


def create_app(
    settings: Settings | None = None,
    generator: SiteGenerator | None = None,
    publisher=None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    store = SiteStore(settings.data_dir)
    if publisher is None:
        publisher = (
            NetlifyPublisher(store, settings.netlify_token)
            if settings.netlify_token
            else LocalPublisher(store)
        )
    jobs = JobManager(
        generator=generator or ClaudeGenerator(settings),
        publisher=publisher,
        store=store,
        pexels_api_key=settings.pexels_api_key,
        max_concurrent=settings.max_concurrent_jobs,
    )
    limiter = RateLimiter(settings.rate_limit_requests, settings.rate_limit_window_seconds)

    app = FastAPI(title="Say IT", version="0.1.0", description="Голос/текст → опубликованный сайт")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "publisher": publisher.name}

    @app.post("/api/generate", status_code=202)
    async def generate(body: GenerateRequest, request: Request) -> dict:
        client_ip = request.client.host if request.client else "unknown"
        if not limiter.allow(client_ip):
            raise HTTPException(429, "Слишком много запросов. Подождите несколько минут.")
        base_url = settings.public_base_url or str(request.base_url)
        job = jobs.create(body.prompt, base_url)
        return {"job_id": job.id}

    @app.get("/api/jobs/{job_id}")
    async def job_status(job_id: str) -> dict:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(404, "Задача не найдена")
        return job.to_dict()

    @app.get("/api/sites/{site_id}/qr.png")
    async def site_qr(site_id: str) -> Response:
        meta = store.read_meta(site_id) if is_valid_site_id(site_id) else None
        if meta is None:
            raise HTTPException(404, "Сайт не найден")
        return Response(
            make_qr_png(meta["url"]),
            media_type="image/png",
            headers={"Content-Disposition": f'attachment; filename="say-it-{site_id}.png"'},
        )

    @app.get("/s/{site_id}", include_in_schema=False)
    async def site_redirect(site_id: str) -> RedirectResponse:
        # Trailing slash matters: relative links inside the site resolve against it.
        return RedirectResponse(f"/s/{site_id}/", status_code=308)

    @app.get("/s/{site_id}/", include_in_schema=False)
    async def site_page(site_id: str) -> HTMLResponse:
        html = store.read_html(site_id) if is_valid_site_id(site_id) else None
        if html is None:
            raise HTTPException(404, "Сайт не найден")
        return HTMLResponse(
            html,
            headers={
                "Content-Security-Policy": SITE_CSP,
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            },
        )

    return app
