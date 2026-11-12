"""Phase 10 API: public hosted jobs, URL/repo POST, SSRF denylist, hosted key rules."""

import shutil

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from evalpilot.api.app import create_app  # noqa: E402
from evalpilot.api.settings import ApiSettings  # noqa: E402
from evalpilot.audit.intake import IntakeError  # noqa: E402
from evalpilot.config import load_settings  # noqa: E402

from tests.api.test_api import ORIGIN, client  # noqa: E402

CARD = '{"name":"x"}'


@pytest.fixture
def ref_runs(root, tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    shutil.copytree(root / "runs" / "reference", runs / "reference")
    monkeypatch.setenv("EVALPILOT_RUNS_DIR", str(runs))
    return runs


@pytest.fixture
def jobs_api(ref_runs, root):
    return client(root, mode="jobs")


@pytest.fixture
def hosted_jobs(ref_runs, root):
    return client(root, mode="jobs", hosted=True)


def test_readonly_post_still_403(ref_runs, root):
    r = client(root).post("/api/audits", data={"system_card_json": CARD, "engines": "config"})
    assert r.status_code == 403


def test_jobs_url_without_permission_is_400(jobs_api):
    r = jobs_api.post("/api/audits", data={"target_url": "https://bot.example/chat", "system_card_json": CARD,
                                           "engines": "config"})
    assert r.status_code == 400
    assert "permission" in r.json()["detail"]


def test_jobs_url_with_permission_is_202(jobs_api):
    r = jobs_api.post("/api/audits", data={"target_url": "https://bot.example/chat", "authorized": "true",
                                           "system_card_json": CARD, "engines": "config"})
    assert r.status_code == 202, r.text
    assert r.json()["status"] in ("queued", "running", "done", "failed")


def test_jobs_public_github_repo_is_accepted(jobs_api, monkeypatch):
    def fail_download(*_a, **_k):
        raise IntakeError("download stub")

    monkeypatch.setattr("evalpilot.audit.intake.download_repo", fail_download)
    r = jobs_api.post("/api/audits", data={"repo": "https://github.com/x/y", "system_card_json": CARD,
                                           "engines": "config"})
    assert r.status_code == 202, r.text


@pytest.mark.parametrize("repo", [
    "http://github.com/x/y",
    "https://gitlab.com/x/y",
    "https://github.com/x/y/tree/main",
    "not-a-url",
])
def test_jobs_rejects_non_public_github_repo(jobs_api, repo):
    r = jobs_api.post("/api/audits", data={"repo": repo, "system_card_json": CARD, "engines": "config"})
    assert r.status_code == 400, (repo, r.text)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/chat",
    "https://127.0.0.1/chat",
    "https://169.254.169.254/",
    "https://10.0.0.1/chat",
    "http://example.com/chat",
    "https://localhost/chat",
    "https://metadata.google.internal/",
])
def test_hosted_jobs_rejects_ssrf_urls(hosted_jobs, url):
    r = hosted_jobs.post("/api/audits", data={"target_url": url, "authorized": "true", "system_card_json": CARD,
                                              "engines": "config"})
    assert r.status_code == 400, (url, r.text)


def test_hosted_jobs_allows_public_https_url(hosted_jobs):
    r = hosted_jobs.post("/api/audits", data={"target_url": "https://bot.example/chat", "authorized": "true",
                                              "system_card_json": CARD, "engines": "config"})
    assert r.status_code == 202, r.text


def test_jobs_connection_test_with_permission(ref_runs, root):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"reply": "hello from the bot"})

    mock = httpx.Client(transport=httpx.MockTransport(handler))
    c = TestClient(create_app(load_settings(root), ApiSettings(allowed_origins=(ORIGIN,), mode="jobs"),
                              inline_jobs=True, target_client=mock))
    denied = c.post("/api/connection-test", json={"url": "https://bot.example/chat", "authorized": False})
    assert denied.status_code == 400
    ok = c.post("/api/connection-test", json={"url": "https://bot.example/chat", "authorized": True})
    assert ok.status_code == 200 and ok.json()["ok"] is True


def test_hosted_connection_test_rejects_loopback(hosted_jobs):
    r = hosted_jobs.post("/api/connection-test", json={"url": "http://127.0.0.1/chat", "authorized": True})
    assert r.status_code == 400


def test_jobs_draft_from_repo_is_not_403(jobs_api, monkeypatch):
    def fail_download(*_a, **_k):
        raise IntakeError("download stub")

    monkeypatch.setattr("evalpilot.audit.intake.download_repo", fail_download)
    r = jobs_api.post("/api/system-card/draft", data={"repo": "https://github.com/x/y"})
    assert r.status_code == 400
    assert "download stub" in r.json()["detail"]


def test_job_record_survives_an_api_restart(ref_runs, root):
    first = client(root, mode="jobs")
    r = first.post("/api/audits", data={"system_card_json": CARD, "engines": "config", "name": "persist"})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    assert r.json()["status"] == "done"
    second = client(root, mode="jobs")
    found = second.get(f"/api/jobs/{job_id}")
    assert found.status_code == 200, found.text
    body = found.json()
    assert body["job_id"] == job_id and body["status"] == "done" and body["name"] == "persist"
