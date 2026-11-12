"""Phase 9 API: dashboard fields, snapshot, admin mode, playground, labels, connection test."""

import json
import shutil

import httpx
import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from evalpilot.api.app import create_app  # noqa: E402
from evalpilot.api.settings import ApiConfigError, ApiSettings, DEFAULT_ORIGINS, assert_admin_host  # noqa: E402
from evalpilot.audit.intake import IntakeError  # noqa: E402
from evalpilot.cli import main  # noqa: E402
from evalpilot.config import load_settings  # noqa: E402

from tests.api.test_api import BOT_AUDIT, ORIGIN, REFERENCE_RUN, client, zip_dir  # noqa: E402

OWNER = "phase9-owner"


@pytest.fixture
def ref_runs(root, tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    shutil.copytree(root / "runs" / "reference", runs / "reference")
    monkeypatch.setenv("EVALPILOT_RUNS_DIR", str(runs))
    return runs


@pytest.fixture
def api(ref_runs, root):
    return client(root)


@pytest.fixture
def jobs_api(ref_runs, root):
    return client(root, mode="jobs")


def auth(token: str = OWNER) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def owner(ref_runs, root):
    return TestClient(create_app(load_settings(root), ApiSettings(allowed_origins=(ORIGIN,), admin_token=OWNER,
                                                                 admin_provider="offline"), inline_jobs=True))


# New read fields


def test_default_origins_include_next_dev():
    assert "http://localhost:3000" in DEFAULT_ORIGINS and "http://127.0.0.1:3000" in DEFAULT_ORIGINS


def test_run_summary_has_dashboard_fields(api):
    body = api.get(f"/api/runs/{REFERENCE_RUN}", params={"version": "v3"}).json()
    v1, v2, v3 = (body["version_summaries"][v] for v in ("v1", "v2", "v3"))
    assert v1["cases_passed"] == 0 and v1["cases_total"] == 41 and v1["critical_failures"] == 6
    assert v2["cases_passed"] == 40 and v2["fixed_cases"] and "adv_04" in v2["regressed_cases"]
    assert v3["cases_passed"] == 40 and v3["fixed_cases"] == ["adv_04"] and v3["regressed_cases"] == ["adv_05"]
    assert set(body["critical_graders"]) == {"advice", "unsafe_claim"}
    assert {j["judge"] for j in body["judges_trusted"]} == {"judge_grounded", "judge_helpful_compliant"}
    assert body["documents"]["horizon_debt_factsheet"]["title"]
    assert "bot_cost_usd" in v3


def test_cases_carry_status_and_counts(api):
    page = api.get(f"/api/runs/{REFERENCE_RUN}/cases", params={"case_version": "v3", "status": "failed", "limit": 100}).json()
    assert page["counts"]["failed"] == 1 and page["counts"]["all"] == 41
    assert [c["id"] for c in page["items"]] == ["adv_05"]
    status = page["items"][0]["versions"]["v3"]["status"]
    assert status["passed"] is False and "judge_grounded" in status["failing"] and status["critical"] is False


def test_audit_has_headline_stats_guardrails_and_found_by(api):
    detail = api.get(f"/api/audits/{BOT_AUDIT}").json()
    assert "Blocked" in detail["headline"]
    assert detail["stats"]["quality_pct"] is not None
    assert {g["state"] for g in detail["guardrails"]} <= {"present", "weak", "missing", "n/a"}
    assert all("found_by" in r for r in detail["risks"])
    assert detail["rerunnable"] is False and "system card" in detail["input_kinds"]


def test_estimate_is_zero_offline(api):
    body = api.get("/api/estimate", params={"engines": "behaviour,security,code,config",
                                           "inputs": "url,card,code", "ai_review": "true"}).json()
    assert body["provider"] == "offline" and body["paid"] is False
    assert body["total_usd"] == 0 and all(v == 0 for v in body["per_engine"].values())
    assert body["fits_budget"] is True


def test_snapshot_covers_the_pages(api, tmp_path, root, capsys):
    from evalpilot.api.snapshot import build_snapshot

    snap = build_snapshot(api)
    assert snap["format"] == 1 and snap["responses"]["/api/meta"]["admin"] is False
    out = tmp_path / "snapshot.json"
    assert main(["--root", str(root), "snapshot", "--out", str(out)]) == 0
    assert "14 responses" in capsys.readouterr().out
    written = json.loads(out.read_text(encoding="utf-8"))
    assert set(written["responses"]) == set(snap["responses"])


# Public vs admin


def test_admin_routes_are_403_when_admin_is_off(api):
    assert api.get("/api/admin/session").status_code == 403
    assert api.post("/api/connection-test", json={"url": "http://127.0.0.1/", "authorized": True}).status_code == 403
    assert api.post("/api/labels", json={"run_id": REFERENCE_RUN, "case_id": "fact_01", "version": "v3",
                                        "grader": "judge_grounded", "human_pass": True}).status_code == 403
    assert api.post(f"/api/audits/{BOT_AUDIT}/rerun").status_code == 403


def test_admin_routes_are_401_without_the_token(owner):
    assert owner.get("/api/admin/session").status_code == 401
    assert owner.post("/api/connection-test", json={"url": "http://127.0.0.1/", "authorized": True}).status_code == 401
    assert owner.get("/api/admin/session", headers=auth("wrong-token-xxxxxxxxxxxx")).status_code == 401


def test_admin_session_and_meta(owner):
    assert owner.get("/health").json()["mode"] == "admin"
    meta = owner.get("/api/meta").json()
    assert meta["admin"] is True and meta["mode"] == "admin" and meta["jobs_enabled"] is True
    assert meta["provider"] == "offline"
    assert owner.get("/api/admin/session", headers=auth()).json() == {"admin": True, "provider": "offline"}


def test_playground_reference_is_public_free_text_is_not(api, owner):
    ok = api.post("/api/playground", json={"case_id": "fact_01", "versions": ["v1", "v3"]})
    assert ok.status_code == 200 and ok.json()["source"] == "reference" and ok.json()["cost_usd"] == 0
    assert "v1" in ok.json()["answers"] and "v3" in ok.json()["answers"]
    assert api.post("/api/playground", json={"question": "hello"}).status_code == 403
    assert owner.post("/api/playground", json={"question": "hello"}).status_code == 401


def test_admin_playground_free_text_offline(owner):
    r = owner.post("/api/playground", json={"question": "What is an exit load?", "versions": ["v3"]}, headers=auth())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "live" and body["cost_usd"] == 0 and "v3" in body["answers"]
    assert body["answers"]["v3"]["answer"]


def test_jobs_mode_accepts_url_repo_and_ai_review(jobs_api, monkeypatch):
    def fail_download(*_a, **_k):
        raise IntakeError("download stub")

    monkeypatch.setattr("evalpilot.audit.intake.download_repo", fail_download)
    denied = jobs_api.post("/api/audits", data={"target_url": "https://bot.example/chat",
                                                "system_card_json": '{"name":"x"}', "engines": "config"})
    assert denied.status_code == 400 and "permission" in denied.json()["detail"]
    url = jobs_api.post("/api/audits", data={"target_url": "https://bot.example/chat", "authorized": "true",
                                             "system_card_json": '{"name":"x"}', "engines": "config"})
    assert url.status_code == 202, url.text
    repo = jobs_api.post("/api/audits", data={"repo": "https://github.com/x/y", "system_card_json": '{"name":"x"}',
                                              "engines": "config"})
    assert repo.status_code == 202, repo.text
    review = jobs_api.post("/api/audits", data={"system_card_json": '{"name":"x"}', "engines": "config",
                                                "ai_review": "true"})
    assert review.status_code == 202, review.text


def test_hosted_admin_refuses_to_start(root, monkeypatch):
    monkeypatch.setenv("EVALPILOT_HOSTED", "1")
    with pytest.raises(ApiConfigError, match="admin mode"):
        create_app(load_settings(root), ApiSettings(hosted=True, admin_token=OWNER))


def test_admin_token_is_not_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("EVALPILOT_ADMIN_TOKEN", "please-dont")
    assert ApiSettings.from_env().admin is False


def test_assert_admin_host_loopback_only(monkeypatch):
    assert_admin_host("127.0.0.1")
    with pytest.raises(ApiConfigError, match="loopback"):
        assert_admin_host("0.0.0.0")
    monkeypatch.setenv("RENDER", "true")
    with pytest.raises(ApiConfigError, match="hosted"):
        assert_admin_host("127.0.0.1")


def test_serve_admin_refuses_hosted_and_non_loopback(root, monkeypatch, capsys):
    monkeypatch.setenv("EVALPILOT_HOSTED", "1")
    assert main(["--root", str(root), "serve", "--admin"]) == 2
    assert "hosted" in capsys.readouterr().err.lower()
    monkeypatch.delenv("EVALPILOT_HOSTED")
    assert main(["--root", str(root), "serve", "--admin", "--host", "0.0.0.0"]) == 2
    assert "loopback" in capsys.readouterr().err


# Connection test, labels, rerun, draft, progress


def test_connection_test_needs_permission_then_uses_injected_client(ref_runs, root):
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content.decode("utf-8")
        return httpx.Response(200, json={"reply": "Asterion FAQ bot at your service."})

    mock = httpx.Client(transport=httpx.MockTransport(handler))
    c = TestClient(create_app(load_settings(root), ApiSettings(allowed_origins=(ORIGIN,), admin_token=OWNER),
                              inline_jobs=True, target_client=mock))
    denied = c.post("/api/connection-test", json={"url": "https://bot.example/chat", "authorized": False},
                    headers=auth())
    assert denied.status_code == 400
    r = c.post("/api/connection-test", json={"url": "https://bot.example/chat",
                                             "request_body": '{"message": "$QUESTION"}', "answer_path": "reply",
                                             "authorized": True}, headers=auth())
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.json()["sample_reply"].startswith("Asterion")
    assert "$QUESTION" not in seen["body"] and "Hi!" in seen["body"]


def test_labels_write_to_a_tmp_file(ref_runs, root, tmp_path, monkeypatch):
    labels = tmp_path / "labels.jsonl"
    monkeypatch.setattr("evalpilot.config.Settings.labels_path", property(lambda self: labels))
    c = TestClient(create_app(load_settings(root), ApiSettings(allowed_origins=(ORIGIN,), admin_token=OWNER),
                              inline_jobs=True))
    r = c.post("/api/labels", json={"run_id": REFERENCE_RUN, "case_id": "fact_01", "version": "v3",
                                    "grader": "judge_grounded", "human_pass": True, "note": "looks right"},
               headers=auth())
    assert r.status_code == 200 and r.json()["saved"] is True
    assert r.json()["label"]["labeler"] == "owner"
    row = json.loads(labels.read_text(encoding="utf-8").splitlines()[0])
    assert row["case_id"] == "fact_01" and row["human_pass"] is True and row["note"] == "looks right"


def test_admin_card_audit_progress_and_rerun(owner, examples):
    card = (examples / "vulnerable_bot" / "system_card.json").read_text(encoding="utf-8")
    r = owner.post("/api/audits", data={"system_card_json": card, "name": "card-only", "engines": "config"},
                   headers=auth())
    assert r.status_code == 202, r.text
    job = r.json()
    assert job["status"] == "done" and job["name"] == "card-only" and job["decision"] == "BLOCK"
    assert job["progress"]["config"] == "done"
    assert job["progress"]["behaviour"] == "skipped" and job["progress"]["security"] == "skipped"
    audit = owner.get(f"/api/audits/{job['audit_id']}").json()
    assert audit["source"] == "local" and audit["rerunnable"] is True
    rerun = owner.post(f"/api/audits/{job['audit_id']}/rerun", headers=auth())
    assert rerun.status_code == 202 and rerun.json()["status"] == "done"
    blocked = owner.post(f"/api/audits/{BOT_AUDIT}/rerun", headers=auth())
    assert blocked.status_code == 409 and "this machine" in blocked.json()["detail"]


def test_draft_card_from_zip_in_jobs_mode(jobs_api, tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "README.md").write_text("# GymCoach bot\n", encoding="utf-8")
    (src / "tools.py").write_text("@tool\ndef book_session(slot):\n    pass\n", encoding="utf-8")
    archive = zip_dir(src, tmp_path / "bot.zip")
    r = jobs_api.post("/api/system-card/draft", files={"code_zip": ("bot.zip", archive.read_bytes())})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["card"]["name"] == "GymCoach bot"
    assert any(t["name"] == "book_session" for t in body["card"]["tools"])
    assert body["files_read"] >= 2


def test_draft_from_repo_needs_admin_token_when_admin_mode(owner):
    denied = owner.post("/api/system-card/draft", data={"repo": "https://github.com/x/y"})
    assert denied.status_code == 401
