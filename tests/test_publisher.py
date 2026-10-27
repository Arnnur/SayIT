import asyncio
import hashlib
import json

import httpx

from app.publisher import (
    LocalPublisher,
    NetlifyPublisher,
    SiteStore,
    generate_site_id,
    is_valid_site_id,
)

HTML = "<!DOCTYPE html><html><body>hello</body></html>"


def test_generate_site_id_is_valid_and_unique():
    ids = {generate_site_id() for _ in range(200)}
    assert len(ids) == 200
    assert all(is_valid_site_id(i) for i in ids)


def test_is_valid_site_id_rejects_traversal():
    assert not is_valid_site_id("../etc")
    assert not is_valid_site_id("ABC123xyz")
    assert not is_valid_site_id("")


def test_store_roundtrip(tmp_path):
    store = SiteStore(tmp_path)
    store.save_html("abc123def0", HTML)
    store.save_meta("abc123def0", {"url": "https://x"})
    assert store.read_html("abc123def0") == HTML
    assert store.read_meta("abc123def0") == {"url": "https://x"}
    assert store.read_html("zzzzzz0000") is None
    assert store.read_meta("zzzzzz0000") is None


def test_local_publisher(tmp_path):
    store = SiteStore(tmp_path)
    result = asyncio.run(
        LocalPublisher(store).publish("abc123def0", HTML, base_url="http://host:8000/")
    )
    assert result.url == "http://host:8000/s/abc123def0/"
    assert result.provider == "local"
    assert result.warning is None
    assert store.read_html("abc123def0") == HTML


def _netlify_handler(calls, fail=False):
    sha1 = hashlib.sha1(HTML.encode()).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer nt"
        path = request.url.path
        if fail:
            return httpx.Response(500, json={"message": "boom"})
        if request.method == "POST" and path == "/api/v1/sites":
            return httpx.Response(
                201, json={"id": "site-1", "ssl_url": "https://sayit-abc123def0.netlify.app"}
            )
        if request.method == "POST" and path == "/api/v1/sites/site-1/deploys":
            assert json.loads(request.content) == {"files": {"/index.html": sha1}}
            return httpx.Response(200, json={"id": "dep-1", "required": [sha1], "state": "uploading"})
        if request.method == "PUT" and path == "/api/v1/deploys/dep-1/files/index.html":
            assert request.content == HTML.encode()
            return httpx.Response(200, json={})
        if request.method == "GET" and path == "/api/v1/deploys/dep-1":
            return httpx.Response(200, json={"id": "dep-1", "state": "ready"})
        return httpx.Response(404)

    return handler


def test_netlify_publisher_deploys(tmp_path):
    calls = []
    store = SiteStore(tmp_path)

    async def run():
        transport = httpx.MockTransport(_netlify_handler(calls))
        async with httpx.AsyncClient(transport=transport) as client:
            publisher = NetlifyPublisher(store, token="nt", http_client=client, poll_interval=0)
            return await publisher.publish("abc123def0", HTML, base_url="http://localhost")

    result = asyncio.run(run())
    assert result.url == "https://sayit-abc123def0.netlify.app"
    assert result.provider == "netlify"
    assert json.loads(calls[0].content) == {"name": "sayit-abc123def0"}
    assert [c.method for c in calls[:3]] == ["POST", "POST", "PUT"]
    # local copy is kept for the in-app preview
    assert store.read_html("abc123def0") == HTML


def test_netlify_failure_falls_back_to_local(tmp_path):
    store = SiteStore(tmp_path)

    async def run():
        transport = httpx.MockTransport(_netlify_handler([], fail=True))
        async with httpx.AsyncClient(transport=transport) as client:
            publisher = NetlifyPublisher(store, token="nt", http_client=client, poll_interval=0)
            return await publisher.publish("abc123def0", HTML, base_url="http://localhost")

    result = asyncio.run(run())
    assert result.provider == "local"
    assert result.url == "http://localhost/s/abc123def0/"
    assert "Netlify" in result.warning
