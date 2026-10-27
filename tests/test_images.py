import asyncio

import httpx

from app.images import fallback_image_url, find_image_placeholders, resolve_images


def test_find_placeholders_with_size():
    html = '<img src="{{IMAGE:coffee latte art|800x600}}">'
    [req] = find_image_placeholders(html)
    assert req.query == "coffee latte art"
    assert (req.width, req.height) == (800, 600)
    assert req.raw == "{{IMAGE:coffee latte art|800x600}}"


def test_find_placeholders_default_size():
    [req] = find_image_placeholders("background: url('{{IMAGE:mountains}}')")
    assert (req.width, req.height) == (1200, 800)


def test_find_placeholders_deduplicates():
    html = "{{IMAGE:cat|400x400}} {{IMAGE:cat|400x400}} {{IMAGE:dog|400x400}}"
    assert [r.query for r in find_image_placeholders(html)] == ["cat", "dog"]


def test_fallback_url_is_keyword_based_and_stable():
    url = fallback_image_url("Coffee Latte, art!", 800, 600, seed=3)
    assert url == "https://loremflickr.com/800/600/coffee,latte,art?lock=3"


def test_fallback_url_handles_empty_query():
    assert fallback_image_url("!!!", 100, 100, seed=1).startswith(
        "https://loremflickr.com/100/100/abstract"
    )


def test_resolve_without_pexels_uses_fallback():
    html = '<img src="{{IMAGE:coffee|800x600}}"><img src="{{IMAGE:tea|800x600}}">'
    out = asyncio.run(resolve_images(html))
    assert "{{IMAGE" not in out
    assert "loremflickr.com/800/600/coffee" in out
    assert "loremflickr.com/800/600/tea" in out


def test_resolve_with_pexels():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={"photos": [{"src": {"original": "https://images.pexels.com/p/1.jpeg"}}]},
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await resolve_images(
                '<img src="{{IMAGE:coffee shop|640x480}}">',
                pexels_api_key="pk",
                http_client=client,
            )

    out = asyncio.run(run())
    assert seen[0].headers["Authorization"] == "pk"
    assert seen[0].url.params["query"] == "coffee shop"
    assert "https://images.pexels.com/p/1.jpeg?auto=compress&cs=tinysrgb&w=640&h=480&fit=crop" in out


def test_resolve_falls_back_when_pexels_fails_or_empty():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.params["query"] == "broken":
            return httpx.Response(500)
        return httpx.Response(200, json={"photos": []})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await resolve_images(
                "{{IMAGE:broken|10x10}} {{IMAGE:nothing|10x10}}",
                pexels_api_key="pk",
                http_client=client,
            )

    out = asyncio.run(run())
    assert "loremflickr.com/10/10/broken" in out
    assert "loremflickr.com/10/10/nothing" in out
