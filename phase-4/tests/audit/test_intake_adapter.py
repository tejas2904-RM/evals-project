import json
import stat
import zipfile

import httpx
import pytest

from evalpilot.audit.adapters import AdapterConfig, AdapterError, HttpAdapter, json_path, load_adapter, render_body
from evalpilot.audit.intake import AuditInputs, IntakeError, download_repo, load_external_traces, parse_repo_url, prepare
from evalpilot.audit.safe_extract import UnsafeArchive, safe_extract

LIMITS = dict(max_files=100, max_total_bytes=1_000_000, max_file_bytes=10_000)


def make_zip(path, entries):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in entries.items():
            if isinstance(data, zipfile.ZipInfo):
                zf.writestr(data, b"target")
            else:
                zf.writestr(name, data)
    return path


# --- safe_extract -------------------------------------------------------------------------------

def test_extracts_and_unwraps_single_top_folder(tmp_path):
    z = make_zip(tmp_path / "a.zip", {"repo-main/app.py": "print('hi')\n", "repo-main/lib/util.py": "x = 1\n"})
    result = safe_extract(z, tmp_path / "out", **LIMITS)
    assert result.root.name == "repo-main"
    assert (result.root / "lib" / "util.py").read_text() == "x = 1\n"


@pytest.mark.parametrize("name", ["../evil.py", "a/../../evil.py", "/etc/passwd", "C:/Windows/evil.py", "..\\evil.py"])
def test_rejects_path_traversal_and_absolute_paths(tmp_path, name):
    z = make_zip(tmp_path / "a.zip", {name: "boom"})
    with pytest.raises(UnsafeArchive):
        safe_extract(z, tmp_path / "out", **LIMITS)
    assert not (tmp_path / "evil.py").exists()


def test_rejects_symlinks(tmp_path):
    info = zipfile.ZipInfo("link")
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    z = make_zip(tmp_path / "a.zip", {"link": info})
    with pytest.raises(UnsafeArchive, match="symlink"):
        safe_extract(z, tmp_path / "out", **LIMITS)


def test_rejects_too_many_files_and_zip_bombs(tmp_path):
    z = make_zip(tmp_path / "a.zip", {f"f{i}.py": "x" for i in range(5)})
    with pytest.raises(UnsafeArchive, match="files"):
        safe_extract(z, tmp_path / "out", **{**LIMITS, "max_files": 4})
    bomb = make_zip(tmp_path / "b.zip", {"big.txt": "0" * 50_000})
    with pytest.raises(UnsafeArchive, match="expands"):
        safe_extract(bomb, tmp_path / "out2", **{**LIMITS, "max_total_bytes": 10_000})


def test_skips_binary_and_oversized_files(tmp_path):
    z = make_zip(tmp_path / "a.zip", {"a.py": "x=1", "img.png": b"\x89PNG\x00\x00", "huge.txt": "y" * 20_000})
    result = safe_extract(z, tmp_path / "out", **LIMITS)
    assert result.skipped_binary == ["img.png"] and result.skipped_large == ["huge.txt"]
    assert [p.name for p in result.files] == ["a.py"]


def test_not_a_zip(tmp_path):
    (tmp_path / "a.zip").write_text("nope")
    with pytest.raises(UnsafeArchive):
        safe_extract(tmp_path / "a.zip", tmp_path / "out", **LIMITS)


# --- intake -------------------------------------------------------------------------------------

def test_url_needs_adapter_and_authorization(audit_cfg, settings, examples):
    with pytest.raises(IntakeError, match="--adapter"):
        prepare(AuditInputs(target_url="http://127.0.0.1:1"), audit_cfg, audit_id="a", default_cases=settings.cases_path)
    adapter = examples / "vulnerable_bot" / "adapter.toml"
    with pytest.raises(IntakeError, match="--authorized"):
        prepare(AuditInputs(target_url="http://127.0.0.1:1", adapter=adapter), audit_cfg, audit_id="a", default_cases=settings.cases_path)
    with pytest.raises(IntakeError, match="http"):
        prepare(AuditInputs(target_url="file:///etc/passwd", adapter=adapter, authorized=True), audit_cfg, audit_id="a",
                default_cases=settings.cases_path)


def test_url_intake_uses_adapter_cases_and_selects_live_engines(audit_cfg, settings, examples):
    intake = prepare(AuditInputs(target_url="http://127.0.0.1:1", adapter=examples / "vulnerable_bot" / "adapter.toml", authorized=True),
                     audit_cfg, audit_id="a", default_cases=settings.cases_path)
    assert intake.engines == ["behaviour", "security"]
    assert len(intake.cases) == 11 and intake.cases_source.endswith("eval_cases.jsonl")


def test_needs_some_input_and_one_code_source(audit_cfg, settings, tmp_path):
    with pytest.raises(IntakeError, match="at least one input"):
        prepare(AuditInputs(), audit_cfg, audit_id="a", default_cases=settings.cases_path)
    with pytest.raises(IntakeError, match="only one"):
        prepare(AuditInputs(path=tmp_path, zip_path=tmp_path / "a.zip"), audit_cfg, audit_id="a", default_cases=settings.cases_path)


def test_engine_selection_notes_skipped_engines(audit_cfg, settings, examples):
    intake = prepare(AuditInputs(path=examples / "fixed_bot", engines=["code", "security"]), audit_cfg, audit_id="a",
                     default_cases=settings.cases_path)
    assert intake.engines == ["code"] and any("security" in n for n in intake.notes)
    with pytest.raises(IntakeError, match="unknown engine"):
        prepare(AuditInputs(path=examples / "fixed_bot", engines=["magic"]), audit_cfg, audit_id="a", default_cases=settings.cases_path)


def test_zip_intake_extracts_to_temp_and_cleans_up(audit_cfg, settings, tmp_path):
    z = make_zip(tmp_path / "bot.zip", {"bot-main/app.py": "x = 1\n"})
    intake = prepare(AuditInputs(zip_path=z), audit_cfg, audit_id="a", default_cases=settings.cases_path)
    root = intake.code_root
    assert (root / "app.py").is_file() and intake.engines == ["code", "config"] and intake.hashes["archive"]
    intake.cleanup()
    assert not root.exists()


def test_unsafe_zip_is_intake_error(audit_cfg, settings, tmp_path):
    z = make_zip(tmp_path / "bot.zip", {"../x.py": "x"})
    with pytest.raises(IntakeError, match="unsafe archive"):
        prepare(AuditInputs(zip_path=z), audit_cfg, audit_id="a", default_cases=settings.cases_path)


@pytest.mark.parametrize("url,ref", [("https://gitlab.com/a/b", "main"), ("http://github.com/a/b", "main"),
                                     ("https://github.com/a/b/tree/x", "main"), ("https://github.com/a/b", "../../x"),
                                     ("https://github.com/a/b", "main;rm -rf")])
def test_repo_url_validation(url, ref):
    with pytest.raises(IntakeError):
        parse_repo_url(url, ref)


def test_repo_url_ok():
    assert parse_repo_url("https://github.com/acme/bot.git", "v1.2") == ("acme", "bot", "https://github.com/acme/bot/archive/v1.2.zip")


def test_download_enforces_size_cap_and_host(tmp_path):
    big = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x" * 5000)))
    with pytest.raises(IntakeError, match="cap"):
        download_repo("https://github.com/a/b/archive/main.zip", tmp_path / "r.zip", 1000, big)
    evil = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"x")))
    with pytest.raises(IntakeError, match="redirect"):
        download_repo("https://evil.example/a.zip", tmp_path / "r.zip", 1000, evil)


def test_external_traces(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text(json.dumps({"query": "fee?", "answer": "0.62% [doc_a]", "context": "TER 0.62%"}) + "\n", encoding="utf-8")
    [t] = load_external_traces(path, "audit-x")
    assert t.version == "ext" and t.citations == ["doc_a"] and t.context == ["TER 0.62%"] and t.run_id == "audit-x"
    path.write_text(json.dumps({"q": "x"}) + "\n", encoding="utf-8")
    with pytest.raises(IntakeError):
        load_external_traces(path, "audit-x")


# --- adapter ------------------------------------------------------------------------------------

def test_load_example_adapter(examples):
    cfg = load_adapter(examples / "vulnerable_bot" / "adapter.toml")
    assert cfg.answer_path == "$.reply" and cfg.citations_path == "$.sources" and cfg.cases.name == "eval_cases.jsonl"


def test_adapter_requires_answer_path(tmp_path):
    (tmp_path / "a.toml").write_text("[request]\nmethod = 'POST'\n", encoding="utf-8")
    with pytest.raises(AdapterError, match="answer_jsonpath"):
        load_adapter(tmp_path / "a.toml")


def test_json_path_subset():
    data = {"a": {"b": [{"c": "x"}]}}
    assert json_path(data, "$.a.b[0].c") == "x"
    assert json_path(data, "$.a.missing") is None and json_path(data, "$.a.b[5]") is None


def test_render_body_json_escapes_message():
    body = render_body('{"message": "{message}", "session_id": "{session_id}"}', 'he said "hi"\n{x}', "s1")
    assert json.loads(body) == {"message": 'he said "hi"\n{x}', "session_id": "s1"}


def _adapter(handler, **kw):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return HttpAdapter("http://bot.test", AdapterConfig(citations_path="$.sources"), rate_per_s=kw.pop("rate", 100), timeout_s=5,
                       client=client, **kw)


def test_adapter_sends_and_parses():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"reply": "hello", "sources": ["doc_a"]})

    reply = _adapter(handler).send("hi", "s1")
    assert reply.ok and reply.answer == "hello" and reply.citations == ["doc_a"]
    assert seen == [{"message": "hi", "session_id": "s1"}]


def test_adapter_reports_http_errors_and_timeouts():
    assert _adapter(lambda r: httpx.Response(429, json={"error": "slow down"})).send("x", "s").status == 429

    def timeout(request):
        raise httpx.ReadTimeout("slow", request=request)

    reply = _adapter(timeout).send("x", "s")
    assert reply.status == 0 and reply.error == "timeout" and not reply.ok


def test_adapter_rate_limits_with_fake_clock():
    now = [0.0]
    sleeps = []
    adapter = _adapter(lambda r: httpx.Response(200, json={"reply": "ok"}), rate=2, sleep=lambda s: sleeps.append(s),
                       clock=lambda: now[0])
    adapter.send("a", "s")
    adapter.send("b", "s")
    adapter.send("c", "s", throttle=False)
    assert sleeps == [0.5]


def test_adapter_auth_header_comes_from_env(monkeypatch):
    cfg = AdapterConfig(auth_header_env="BOT_TOKEN")
    with pytest.raises(AdapterError, match="BOT_TOKEN"):
        HttpAdapter("http://bot.test", cfg, rate_per_s=1, timeout_s=1)
    monkeypatch.setenv("BOT_TOKEN", "Bearer t0k")
    got = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: got.append(r.headers["Authorization"]) or httpx.Response(200, json={"reply": ""})))
    HttpAdapter("http://bot.test", cfg, rate_per_s=100, timeout_s=1, client=client).send("x", "s")
    assert got == ["Bearer t0k"]
