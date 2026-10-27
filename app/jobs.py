"""Background jobs: one job = one website being generated.

Pipeline: generating (Claude) -> images -> publishing -> QR -> done.
The browser polls GET /api/jobs/<id> to show progress.
Jobs live in memory: restarting the server forgets them (sites stay on disk).
"""

from __future__ import annotations

import asyncio
import enum
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from .generator import GenerationError, SiteGenerator
from .images import resolve_images
from .publisher import SiteStore, generate_site_id
from .qr import make_qr_png, png_data_url

logger = logging.getLogger(__name__)

# A typical generated site is ~20-30k characters; used only to estimate the progress bar.
EXPECTED_CHARS = 25_000
MAX_JOBS_KEPT = 500


class JobStatus(str, enum.Enum):
    QUEUED = "queued"
    GENERATING = "generating"
    IMAGES = "images"
    PUBLISHING = "publishing"
    DONE = "done"
    ERROR = "error"


STATUS_MESSAGES = {
    JobStatus.QUEUED: "В очереди…",
    JobStatus.GENERATING: "ИИ проектирует и пишет сайт…",
    JobStatus.IMAGES: "Подбираем изображения…",
    JobStatus.PUBLISHING: "Публикуем сайт в интернете…",
    JobStatus.DONE: "Готово!",
    JobStatus.ERROR: "Ошибка",
}


@dataclass
class Job:
    id: str
    prompt: str
    status: JobStatus = JobStatus.QUEUED
    progress: int = 0
    chars: int = 0
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    def set_status(self, status: JobStatus, progress: int | None = None) -> None:
        self.status = status
        if progress is not None:
            self.progress = progress

    def to_dict(self) -> dict[str, Any]:
        end = self.finished_at or time.time()
        return {
            "id": self.id,
            "status": self.status.value,
            "message": STATUS_MESSAGES[self.status],
            "progress": self.progress,
            "chars": self.chars,
            "elapsed_seconds": round(end - self.created_at, 1),
            "result": self.result,
            "error": self.error,
        }


class JobManager:
    def __init__(
        self,
        generator: SiteGenerator,
        publisher: Any,
        store: SiteStore,
        pexels_api_key: str | None = None,
        max_concurrent: int = 3,
    ):
        self.generator = generator
        self.publisher = publisher
        self.store = store
        self.pexels_api_key = pexels_api_key
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent))
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task] = set()

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def create(self, prompt: str, base_url: str) -> Job:
        """Register a job and start it in the background. Must be called inside the event loop."""
        self._forget_old_jobs()
        job = Job(id=secrets.token_urlsafe(9), prompt=prompt)
        self._jobs[job.id] = job
        task = asyncio.create_task(self.run(job, base_url))
        # Keep a reference so the task isn't garbage-collected mid-run.
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    async def run(self, job: Job, base_url: str) -> None:
        async with self._semaphore:
            try:
                await self._pipeline(job, base_url)
            except GenerationError as exc:
                self._fail(job, str(exc))
            except Exception:
                logger.exception("Job %s crashed", job.id)
                self._fail(job, "Внутренняя ошибка сервера. Попробуйте ещё раз.")

    async def _pipeline(self, job: Job, base_url: str) -> None:
        job.set_status(JobStatus.GENERATING, 5)

        def on_progress(chars: int) -> None:
            job.chars = chars
            job.progress = 5 + min(80, int(80 * chars / EXPECTED_CHARS))

        site = await self.generator.generate(job.prompt, on_progress)

        job.set_status(JobStatus.IMAGES, 88)
        html = await resolve_images(site.html, pexels_api_key=self.pexels_api_key)

        job.set_status(JobStatus.PUBLISHING, 93)
        site_id = generate_site_id()
        published = await self.publisher.publish(site_id, html, base_url)

        qr_png = make_qr_png(published.url)
        self.store.save_meta(
            site_id,
            {
                "url": published.url,
                "title": site.title,
                "prompt": job.prompt,
                "provider": published.provider,
                "created_at": time.time(),
            },
        )

        job.result = {
            "site_id": site_id,
            "url": published.url,
            "preview_url": f"/s/{site_id}/",
            "title": site.title,
            "provider": published.provider,
            "warning": published.warning,
            "qr_data_url": png_data_url(qr_png),
            "qr_download_url": f"/api/sites/{site_id}/qr.png",
        }
        job.finished_at = time.time()
        job.set_status(JobStatus.DONE, 100)

    def _fail(self, job: Job, message: str) -> None:
        job.error = message
        job.finished_at = time.time()
        job.set_status(JobStatus.ERROR)

    def _forget_old_jobs(self) -> None:
        if len(self._jobs) < MAX_JOBS_KEPT:
            return
        finished = [j for j in self._jobs.values() if j.finished_at is not None]
        for job in sorted(finished, key=lambda j: j.created_at)[: len(finished) // 2]:
            del self._jobs[job.id]
