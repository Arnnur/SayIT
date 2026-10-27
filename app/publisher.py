"""Storing and publishing generated sites.

- SiteStore        — keeps every site on disk: data/sites/<id>/index.html + meta.json.
- LocalPublisher   — the site is served by this server at /s/<id>/.
- NetlifyPublisher — the site is also deployed to <name>.netlify.app via the Netlify API
                     (falls back to LocalPublisher if Netlify fails).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import secrets
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)

SITE_ID_RE = re.compile(r"^[a-z0-9]{6,32}$")
_ID_ALPHABET = string.ascii_lowercase + string.digits
NETLIFY_API = "https://api.netlify.com/api/v1"


def generate_site_id(length: int = 10) -> str:
    # Lowercase letters/digits only: safe for URLs, file names and Netlify site names.
    return "".join(secrets.choice(_ID_ALPHABET) for _ in range(length))


def is_valid_site_id(site_id: str) -> bool:
    return bool(SITE_ID_RE.fullmatch(site_id))


class PublishError(RuntimeError):
    pass


@dataclass(frozen=True)
class PublishResult:
    site_id: str
    url: str
    provider: str  # "local" | "netlify"
    warning: str | None = None


class SiteStore:
    def __init__(self, data_dir: Path | str):
        self.root = Path(data_dir) / "sites"

    def _dir(self, site_id: str) -> Path:
        if not is_valid_site_id(site_id):
            raise ValueError(f"invalid site id: {site_id!r}")
        return self.root / site_id

    def save_html(self, site_id: str, html: str) -> None:
        directory = self._dir(site_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "index.html").write_text(html, encoding="utf-8")

    def read_html(self, site_id: str) -> str | None:
        path = self._dir(site_id) / "index.html"
        return path.read_text(encoding="utf-8") if path.is_file() else None

    def save_meta(self, site_id: str, meta: dict[str, Any]) -> None:
        directory = self._dir(site_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def read_meta(self, site_id: str) -> dict[str, Any] | None:
        path = self._dir(site_id) / "meta.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


class LocalPublisher:
    name = "local"

    def __init__(self, store: SiteStore):
        self.store = store

    async def publish(self, site_id: str, html: str, base_url: str) -> PublishResult:
        self.store.save_html(site_id, html)
        return PublishResult(site_id, f"{base_url.rstrip('/')}/s/{site_id}/", self.name)


class NetlifyPublisher:
    """Deploys a single index.html using Netlify's file-digest deploy API.

    1. POST /sites                      -> create an empty site "sayit-<id>"
    2. POST /sites/<site>/deploys       -> send {path: sha1}; Netlify answers which files it needs
    3. PUT  /deploys/<deploy>/files/... -> upload index.html
    4. GET  /deploys/<deploy>           -> wait until state == "ready"
    """

    name = "netlify"

    def __init__(
        self,
        store: SiteStore,
        token: str,
        http_client: httpx.AsyncClient | None = None,
        poll_interval: float = 1.0,
        max_polls: int = 20,
    ):
        self.store = store
        self.token = token
        self.local = LocalPublisher(store)
        self._client = http_client
        self.poll_interval = poll_interval
        self.max_polls = max_polls

    async def publish(self, site_id: str, html: str, base_url: str) -> PublishResult:
        local = await self.local.publish(site_id, html, base_url)  # always keep a local copy
        own_client = self._client is None
        client = self._client or httpx.AsyncClient(timeout=30)
        try:
            url = await self._deploy(client, site_id, html)
        except (httpx.HTTPError, PublishError, KeyError, ValueError) as exc:
            logger.exception("Netlify deploy failed for %s", site_id)
            return PublishResult(
                site_id,
                local.url,
                local.provider,
                warning=f"Не удалось опубликовать на Netlify ({exc}); сайт доступен на этом сервере.",
            )
        finally:
            if own_client:
                await client.aclose()
        return PublishResult(site_id, url, self.name)

    async def _deploy(self, client: httpx.AsyncClient, site_id: str, html: str) -> str:
        headers = {"Authorization": f"Bearer {self.token}"}
        body = html.encode("utf-8")
        sha1 = hashlib.sha1(body).hexdigest()

        site = await client.post(
            f"{NETLIFY_API}/sites", json={"name": f"sayit-{site_id}"}, headers=headers
        )
        site.raise_for_status()
        site_data = site.json()

        deploy = await client.post(
            f"{NETLIFY_API}/sites/{site_data['id']}/deploys",
            json={"files": {"/index.html": sha1}},
            headers=headers,
        )
        deploy.raise_for_status()
        deploy_data = deploy.json()
        deploy_id = deploy_data["id"]

        if sha1 in deploy_data.get("required", []):
            upload = await client.put(
                f"{NETLIFY_API}/deploys/{deploy_id}/files/index.html",
                content=body,
                headers={**headers, "Content-Type": "application/octet-stream"},
            )
            upload.raise_for_status()

        await self._wait_ready(client, deploy_id, headers)
        return site_data.get("ssl_url") or site_data["url"]

    async def _wait_ready(self, client: httpx.AsyncClient, deploy_id: str, headers: dict) -> None:
        for _ in range(self.max_polls):
            response = await client.get(f"{NETLIFY_API}/deploys/{deploy_id}", headers=headers)
            response.raise_for_status()
            state = response.json().get("state")
            if state == "ready":
                return
            if state == "error":
                raise PublishError("Netlify сообщил об ошибке деплоя")
            await asyncio.sleep(self.poll_interval)
        raise PublishError("Netlify не успел опубликовать сайт")
