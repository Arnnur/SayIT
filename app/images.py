"""Turn image placeholders written by the model into real photo URLs.

The model can't produce images, so it writes placeholders such as
``{{IMAGE:coffee latte art|800x600}}`` (English keywords | width x height).
We replace each one with a photo from Pexels (if a key is configured) or a
keyword-matched photo from LoremFlickr (no key needed).
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

PLACEHOLDER_RE = re.compile(r"\{\{IMAGE:([^|}]+?)(?:\|(\d{2,4})x(\d{2,4}))?\s*\}\}")
DEFAULT_SIZE = (1200, 800)
PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


@dataclass(frozen=True)
class ImageRequest:
    raw: str
    query: str
    width: int
    height: int


def find_image_placeholders(html: str) -> list[ImageRequest]:
    """All distinct placeholders in order of first appearance."""
    seen: dict[str, ImageRequest] = {}
    for match in PLACEHOLDER_RE.finditer(html):
        raw = match.group(0)
        if raw in seen:
            continue
        width = int(match.group(2)) if match.group(2) else DEFAULT_SIZE[0]
        height = int(match.group(3)) if match.group(3) else DEFAULT_SIZE[1]
        seen[raw] = ImageRequest(raw, match.group(1).strip(), width, height)
    return list(seen.values())


def fallback_image_url(query: str, width: int, height: int, seed: int) -> str:
    """LoremFlickr URL: photo by keywords; `lock` keeps the same photo on every load."""
    words = re.findall(r"[a-z0-9]+", query.lower())[:3] or ["abstract"]
    return f"https://loremflickr.com/{width}/{height}/{','.join(words)}?lock={seed}"


def _orientation(width: int, height: int) -> str:
    if width > height * 1.2:
        return "landscape"
    if height > width * 1.2:
        return "portrait"
    return "square"


async def _pexels_url(client: httpx.AsyncClient, api_key: str, req: ImageRequest) -> str | None:
    try:
        response = await client.get(
            PEXELS_SEARCH_URL,
            params={
                "query": req.query,
                "per_page": 1,
                "orientation": _orientation(req.width, req.height),
            },
            headers={"Authorization": api_key},
            timeout=10,
        )
        response.raise_for_status()
        photos = response.json().get("photos") or []
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Pexels search failed for %r: %s", req.query, exc)
        return None
    if not photos:
        return None
    original = photos[0]["src"]["original"]
    return f"{original}?auto=compress&cs=tinysrgb&w={req.width}&h={req.height}&fit=crop"


async def resolve_images(
    html: str,
    pexels_api_key: str | None = None,
    http_client: httpx.AsyncClient | None = None,
) -> str:
    """Replace every placeholder in `html` with a real image URL."""
    requests = find_image_placeholders(html)
    if not requests:
        return html

    urls: list[str | None] = [None] * len(requests)
    if pexels_api_key:
        own_client = http_client is None
        client = http_client or httpx.AsyncClient()
        try:
            urls = list(
                await asyncio.gather(*(_pexels_url(client, pexels_api_key, r) for r in requests))
            )
        finally:
            if own_client:
                await client.aclose()

    for seed, (req, url) in enumerate(zip(requests, urls), start=1):
        final = url or fallback_image_url(req.query, req.width, req.height, seed)
        html = html.replace(req.raw, quote(final, safe=":/?&=,%"))
    return html
