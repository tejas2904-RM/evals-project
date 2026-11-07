import json
import re
import shutil
import zipfile

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient  # noqa: E402

from evalpilot.api.app import RateLimiter, RedactedJSONResponse, create_app  # noqa: E402
from evalpilot.api.settings import ApiConfigError, ApiSettings  # noqa: E402
from evalpilot.cli import main  # noqa: E402
from evalpilot.config import load_settings  # noqa: E402

REFERENCE_RUN = "20261106T143944Z-v1-v2-v3"
BOT_AUDIT = "audit-20261106T151016Z-evalpilot-asterion-faq-bot-v3"
ORIGIN = "https://evalpilot.vercel.app"


@pytest.fixture
def ref_runs(root, tmp_path, monkeypatch):
    runs = tmp_path / "runs"
    shutil.copytree(root / "runs" / "reference", runs / "reference")
    monkeypatch.setenv("EVALPILOT_RUNS_DIR", str(runs))
    return runs


def client(root, **api) -> TestClient:
    api.setdefault("allowed_origins", (ORIGIN,))
    return TestClient(create_app(load_settings(root), ApiSettings(**api), inline_jobs=True))


@pytest.fixture
def api(ref_runs, root):
    return client(root)


@pytest.fixture
def jobs_api(ref_runs, root):
    return client(root, mode="jobs")


def zip_dir(src, dest, extra=None):
    with zipfile.ZipFile(dest, "w") as z:
        for p in sorted(src.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                z.write(p, p.relative_to(src).as_posix())
        for name, text in (extra or {}).items():
            z.writestr(name, text)
    return dest


# Read endpoints


def test_health_and_meta(api):
    h = api.get("/health").json()
    assert h["status"] == "ok" and h["mode"] == "readonly" and h["reference_runs"] == [REFERENCE_RUN]
    m = api.get("/api/meta").json()
    assert m["jobs_enabled"] is False and m["versions"] == ["v1", "v2", "v3"] and len(m["graders"]) == 8


def test_run_summary_matches_the_report_builder(api, ref_runs, root):
    from evalpilot.report.build import Sources, audit_dirs, build_context, select_audits

    body = api.get(f"/api/runs/{REFERENCE_RUN}").json()
    ref = ref_runs / "reference"
    run = ref / REFERENCE_RUN
    ctx = build_context(load_settings(root), Sources(run, select_audits(audit_dirs(ref / "audits"), run, "v3"),
                                                     ref / "spend.jsonl", load_settings(root).labels_path, "v3"))
    assert body["matrix"] == ctx["matrix"] and body["gates"] == ctx["gates"] and body["final"] == ctx["final"]
    assert "cases" not in body and {a["role"] for a in body["audits"]} == {"bot", "fixed", "vulnerable"}
    assert body["spend"]["total_usd"] == pytest.approx(ctx["spend"]["total_usd"])


def test_verdict_endpoint_equals_cli_verdict(api, ref_runs, root, capsys):
    assert main(["--root", str(root), "verdict", "--version", "v3", "--run", f"reference/{REFERENCE_RUN}"]) == 1
    capsys.readouterr()
    cli = json.loads((ref_runs / "reference" / REFERENCE_RUN / "verdict_v3.json").read_text(encoding="utf-8"))
    assert api.get("/api/verdict", params={"version": "v3"}).json() == cli
    assert cli["decision"] == "BLOCK" and cli["audit_id"] == BOT_AUDIT


def test_runs_list(api):
    [run] = api.get("/api/runs").json()
    assert run["run_id"] == REFERENCE_RUN and run["provider"] == "openai" and run["versions"] == ["v1", "v2", "v3"]


def test_case_filters_and_pagination(api):
    url = f"/api/runs/{REFERENCE_RUN}/cases"
    everything = api.get(url, params={"limit": 100}).json()
    assert everything["total"] == 41 and len(everything["items"]) == 41
    page = api.get(url, params={"limit": 5, "offset": 40}).json()
    assert page["total"] == 41 and len(page["items"]) == 1
    failing = api.get(url, params={"failing": "judge_grounded", "case_version": "v3"}).json()
    assert [c["id"] for c in failing["items"]] == ["adv_05"]
    assert set(failing["items"][0]["versions"]) == {"v3"}
    fees = api.get(url, params={"category": "fee", "limit": 100}).json()
    assert fees["total"] == 7 and {c["category"] for c in fees["items"]} == {"fee"}
    assert api.get(url, params={"q": "ITR-2"}).json()["total"] == 1


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_case_paging_bounds(api, params):
    assert api.get(f"/api/runs/{REFERENCE_RUN}/cases", params=params).status_code == 422


@pytest.mark.parametrize("url,status", [
    ("/api/runs/20991231T000000Z-v1", 404),
    ("/api/runs/..%2F..%2Fetc", 404),
    ("/api/audits/audit-nope", 404),
    ("/api/audits/..%5Cintake", 404),
    ("/api/audits/audit-nope/export.md", 404),
    (f"/api/audits/{BOT_AUDIT}/export.html", 404),
    ("/api/jobs/nope", 404),
    ("/api/verdict?version=v9", 400),
    (f"/api/runs/{REFERENCE_RUN}?version=latest", 400),
    (f"/api/runs/{REFERENCE_RUN}/cases?failing=nonsense", 400),
])
def test_bad_ids_and_params(api, url, status):
    r = api.get(url)
    assert r.status_code == status and "detail" in r.json()


def test_audits_list_and_detail(api):
    audits = api.get("/api/audits").json()
    assert {a["role"]: a["decision"] for a in audits} == {"bot": "BLOCK", "vulnerable": "BLOCK", "fixed": "SHIP"}
    assert all(a["source"] == "reference" for a in audits)
    detail = api.get(f"/api/audits/{BOT_AUDIT}").json()
    severities = [r["severity"] for r in detail["risks"]]
    assert severities == sorted(severities, reverse=True) and detail["coverage"] and detail["verdict"]["decision"] == "BLOCK"


def test_exports(api):
    md = api.get(f"/api/audits/{BOT_AUDIT}/export.md")
    assert md.status_code == 200 and md.headers["content-type"].startswith("text/markdown")
    assert "## Risk register" in md.text and "attachment" in md.headers["content-disposition"]
    pdf = api.get(f"/api/audits/{BOT_AUDIT}/export.pdf")
    assert pdf.status_code == 200 and pdf.headers["content-type"] == "application/pdf" and pdf.content.startswith(b"%PDF")


def test_responses_are_json_with_security_headers(api):
    r = api.get(f"/api/runs/{REFERENCE_RUN}/cases", params={"limit": 100})
    assert r.headers["content-type"] == "application/json"
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["referrer-policy"] == "no-referrer"


def test_json_bodies_are_redacted():
    key = "sk-proj-AbCdEfGhIjKlMnOpQrStUvWxYz0123456789abcd"  # secret-check: allow
    body = RedactedJSONResponse({"answer": f"the key is {key}"}).body.decode("utf-8")
    assert key not in body and json.loads(body)["answer"].startswith("the key is sk-")


# CORS


def test_cors_allows_only_listed_origins(api):
    ok = api.get("/health", headers={"Origin": ORIGIN})
    assert ok.headers.get("access-control-allow-origin") == ORIGIN
    evil = api.get("/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers
    preflight = api.options("/api/audits", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert preflight.status_code == 400


def test_cors_origin_regex_for_vercel_previews(ref_runs, root):
    c = client(root, allowed_origin_regex=r"https://evalpilot-[a-z0-9-]+\.vercel\.app")
    origin = "https://evalpilot-git-feature-x.vercel.app"
    assert c.get("/health", headers={"Origin": origin}).headers.get("access-control-allow-origin") == origin


# Modes, uploads, jobs


def test_readonly_refuses_uploads(api):
    r = api.post("/api/audits", files={"traces": ("t.jsonl", b"{}")})
    assert r.status_code == 403


def test_jobs_mode_needs_a_file(jobs_api):
    assert jobs_api.post("/api/audits", data={"trace_version": "v3"}).status_code == 400


def test_upload_audit_of_vulnerable_bot_blocks(jobs_api, examples, tmp_path, ref_runs):
    archive = zip_dir(examples / "vulnerable_bot", tmp_path / "vb.zip")
    card = (examples / "vulnerable_bot" / "system_card.json").read_bytes()
    r = jobs_api.post("/api/audits", files={"code_zip": ("vb.zip", archive.read_bytes()), "system_card": ("card.json", card)})
    assert r.status_code == 202
    job = jobs_api.get(f"/api/jobs/{r.json()['job_id']}").json()
    assert job["status"] == "done" and job["decision"] == "BLOCK" and "offline" in job["notes"][0]
    audit = jobs_api.get(f"/api/audits/{job['audit_id']}").json()
    assert audit["source"] == "upload" and audit["verdict"]["decision"] == "BLOCK"
    assert any(a["audit_id"] == job["audit_id"] for a in jobs_api.get("/api/audits").json())
    assert not list(tmp_path.glob("evalpilot-upload-*"))


def test_upload_traces_with_version(jobs_api, root):
    traces = (root / "runs" / "reference" / REFERENCE_RUN / "traces.jsonl").read_bytes()
    r = jobs_api.post("/api/audits", files={"traces": ("traces.jsonl", traces)}, data={"trace_version": "v3"})
    job = r.json()
    assert r.status_code == 202 and job["status"] == "done", job
    intake = jobs_api.get(f"/api/audits/{job['audit_id']}").json()
    assert intake["engines"] == ["behaviour"]


def test_uploaded_code_is_never_executed(jobs_api, tmp_path):
    marker = tmp_path / "PWNED"
    payload = f"open(r'{marker}', 'w').write('x')\n"
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("print('hello')\n", encoding="utf-8")
    archive = zip_dir(src, tmp_path / "trap.zip", {"setup.py": payload, "conftest.py": payload, "pkg/__init__.py": payload})
    r = jobs_api.post("/api/audits", files={"code_zip": ("trap.zip", archive.read_bytes())})
    assert r.json()["status"] == "done" and not marker.exists()


def test_zip_slip_upload_fails_cleanly(jobs_api, tmp_path):
    archive = tmp_path / "slip.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("../../escape.py", "x = 1\n")
    job = jobs_api.post("/api/audits", files={"code_zip": ("slip.zip", archive.read_bytes())}).json()
    assert job["status"] == "failed" and job["error"] and "evalpilot-upload-" not in job["error"]
    assert not (tmp_path.parent / "escape.py").exists()


@pytest.mark.parametrize("size", [200_000, 10_000])
def test_upload_size_cap(ref_runs, root, size):
    """200 kB trips the Content-Length guard; 10 kB passes it but exceeds the 1 kB file budget."""
    c = client(root, mode="jobs", max_upload_bytes=1024)
    r = c.post("/api/audits", files={"traces": ("t.jsonl", b"x" * size)})
    assert r.status_code == 413


def test_bad_trace_version_rejected(jobs_api):
    r = jobs_api.post("/api/audits", files={"traces": ("t.jsonl", b"{}")}, data={"trace_version": "v3;rm"})
    assert r.status_code == 400


def test_post_rate_limit(ref_runs, root):
    c = client(root, mode="jobs", post_per_minute=2)
    codes = [c.post("/api/audits", data={"trace_version": "v3"}).status_code for _ in range(3)]
    assert codes == [400, 400, 429]


def test_rate_limiter_window():
    limiter = RateLimiter(2)
    assert limiter.allow("a", 0) and limiter.allow("a", 1) and not limiter.allow("a", 2)
    assert limiter.allow("b", 2) and limiter.allow("a", 61.5)


# Hosted safety


def test_hosted_api_refuses_to_start_with_a_paid_key(ref_runs, root, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")  # secret-check: allow
    with pytest.raises(ApiConfigError, match="must not hold paid keys"):
        create_app(load_settings(root), ApiSettings(hosted=True))


def test_render_env_marks_the_api_hosted(monkeypatch):
    monkeypatch.setenv("RENDER", "true")
    api = ApiSettings.from_env()
    assert api.hosted and api.trust_forwarded_for and api.mode == "readonly"


@pytest.mark.parametrize("env,match", [
    ({"EVALPILOT_API_MODE": "admin"}, "EVALPILOT_API_MODE"),
    ({"EVALPILOT_ALLOWED_ORIGINS": "*"}, "explicitly"),
    ({"EVALPILOT_MAX_UPLOAD_MB": "lots"}, "integer"),
    ({"EVALPILOT_POST_PER_MINUTE": "0"}, ">= 1"),
])
def test_bad_api_env(monkeypatch, env, match):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(ApiConfigError, match=match):
        ApiSettings.from_env()


def test_origins_from_env(monkeypatch):
    monkeypatch.setenv("EVALPILOT_ALLOWED_ORIGINS", "https://a.vercel.app/, https://b.example")
    assert ApiSettings.from_env().allowed_origins == ("https://a.vercel.app", "https://b.example")


def test_render_blueprint_is_offline_and_keyless(root):
    text = (root / "render.yaml").read_text(encoding="utf-8")
    assert "create_app --factory" in text and "healthCheckPath: /health" in text
    keys = re.findall(r"^\s*- key: (\w+)", text, re.M)
    assert "EVALPILOT_API_MODE" in keys and not {"OPENAI_API_KEY", "GROQ_API_KEY"} & set(keys)
    assert re.search(r"key: EVALPILOT_API_MODE\s+value: readonly", text)
