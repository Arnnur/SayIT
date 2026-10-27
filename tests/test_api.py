from conftest import FakeGenerator, wait_for_job

from app.generator import GenerationError

PROMPT = "Создай сайт для кофейни в Алматы с меню и формой брони"


def test_index_page_served(make_client):
    response = make_client().get("/")
    assert response.status_code == 200
    assert "Say IT" in response.text


def test_health(make_client):
    data = make_client().get("/api/health").json()
    assert data == {"status": "ok", "publisher": "local"}


def test_health_reports_netlify(make_client):
    assert make_client(netlify_token="nt").get("/api/health").json()["publisher"] == "netlify"


def test_full_generation_flow(make_client):
    generator = FakeGenerator()
    client = make_client(generator)

    response = client.post("/api/generate", json={"prompt": f"  {PROMPT}  "})
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    job = wait_for_job(client, job_id)
    assert job["status"] == "done", job
    assert job["progress"] == 100
    assert generator.prompts == [PROMPT]

    result = job["result"]
    site_id = result["site_id"]
    assert result["url"] == f"http://testserver/s/{site_id}/"
    assert result["preview_url"] == f"/s/{site_id}/"
    assert result["title"] == "Кофейня Арома"
    assert result["provider"] == "local"
    assert result["qr_data_url"].startswith("data:image/png;base64,")
    assert result["qr_download_url"] == f"/api/sites/{site_id}/qr.png"

    site = client.get(result["preview_url"])
    assert site.status_code == 200
    assert "Кофейня Арома" in site.text
    assert "{{IMAGE" not in site.text
    assert "sandbox" in site.headers["content-security-policy"]

    qr = client.get(result["qr_download_url"])
    assert qr.status_code == 200
    assert qr.headers["content-type"] == "image/png"
    assert "attachment" in qr.headers["content-disposition"]


def test_public_base_url_is_used(make_client):
    client = make_client(public_base_url="https://sayit.example.com/")
    job_id = client.post("/api/generate", json={"prompt": PROMPT}).json()["job_id"]
    result = wait_for_job(client, job_id)["result"]
    assert result["url"] == f"https://sayit.example.com/s/{result['site_id']}/"


def test_site_without_trailing_slash_redirects(make_client):
    client = make_client()
    job_id = client.post("/api/generate", json={"prompt": PROMPT}).json()["job_id"]
    site_id = wait_for_job(client, job_id)["result"]["site_id"]
    response = client.get(f"/s/{site_id}", follow_redirects=False)
    assert response.status_code in (307, 308)
    assert response.headers["location"].endswith(f"/s/{site_id}/")


def test_prompt_validation(make_client):
    client = make_client()
    assert client.post("/api/generate", json={"prompt": "  a "}).status_code == 422
    assert client.post("/api/generate", json={"prompt": "x" * 2001}).status_code == 422
    assert client.post("/api/generate", json={}).status_code == 422


def test_rate_limit(make_client):
    client = make_client(rate_limit_requests=2)
    codes = [client.post("/api/generate", json={"prompt": PROMPT}).status_code for _ in range(3)]
    assert codes == [202, 202, 429]


def test_generation_error_is_reported(make_client):
    client = make_client(FakeGenerator(error=GenerationError("Модель отклонила запрос")))
    job_id = client.post("/api/generate", json={"prompt": PROMPT}).json()["job_id"]
    job = wait_for_job(client, job_id)
    assert job["status"] == "error"
    assert job["error"] == "Модель отклонила запрос"
    assert job["result"] is None


def test_unexpected_error_hides_details(make_client):
    client = make_client(FakeGenerator(error=RuntimeError("secret stack info")))
    job_id = client.post("/api/generate", json={"prompt": PROMPT}).json()["job_id"]
    job = wait_for_job(client, job_id)
    assert job["status"] == "error"
    assert "secret" not in job["error"]


def test_unknown_ids_return_404(make_client):
    client = make_client()
    assert client.get("/api/jobs/nope").status_code == 404
    assert client.get("/s/abcdef1234/").status_code == 404
    assert client.get("/s/BAD..ID/").status_code == 404
    assert client.get("/api/sites/abcdef1234/qr.png").status_code == 404
