import json
import subprocess
import sys

import pytest

from evalpilot.audit.engines import code_scan
from evalpilot.audit.engines.code_scan import load_rules, run_code_scan, scan_bandit, scan_rules, scan_secrets_regex
from evalpilot.audit.files import SourceFile, iter_text_files

RULES = {r.id: r for r in load_rules()}

# rule id -> (file name, vulnerable text, safe text)
CASES = {
    "llm-output-eval": ("t.py", "x = eval(llm_reply)", "x = ast.literal_eval(llm_reply)"),
    "llm-output-shell": ("t.py", 'subprocess.run(f"echo {answer}", shell=True)', 'subprocess.run(["echo", "fixed"])'),
    "llm-output-raw-html": ("r.py", "return f\"<div>{answer}</div>\"", "return f\"<div>{html.escape(answer)}</div>\""),
    "prompt-concat-user-into-system": ("b.py", 'msgs = [{"role": "system", "content": f"{PROMPT} {message}"}]',
                                       'msgs = [{"role": "system", "content": PROMPT}, {"role": "user", "content": message}]'),
    "no-max-tokens": ("c.py", "r = client.chat.completions.create(model=M, messages=m)",
                      "r = client.chat.completions.create(model=M, messages=m, max_completion_tokens=300)"),
    "temperature-on-reasoning-model": ("c.py", 'MODEL = "gpt-5.4-mini"\nTEMPERATURE = 0.9', 'MODEL = "gpt-5.4-mini"\nREASONING = "none"'),
    "trust-remote-code": ("i.py", "m = load(name, trust_remote_code=True)", "m = load(name, revision=SHA)"),
    "unpinned-requirement": ("requirements.txt", "httpx\n", "httpx==0.28.1\n# comment\n"),
    "log-prompt-pii": ("b.py", 'log.info("prompt=%s", prompt)', 'log.info("prompt chars=%d", len(prompt))'),
    "vector-query-no-filter": ("b.py", "docs = INDEX.query(text)", "docs = INDEX.query(text, filter={'tenant': t})"),
    "ingest-untrusted-no-tag": ("i.py", "html = urlopen(u).read()\nINDEX.add(doc_id, html)",
                                "html = urlopen(u).read()\nINDEX.add(doc_id, html, source='scraped', trusted=False)"),
    "tool-write-no-confirm": ("t.py", "def send_email(to, body):\n    smtp.send(to, body)",
                              "def send_email(to, body, confirmed_by):\n    require_confirmation(confirmed_by)\n    smtp.send(to, body)"),
}


def test_every_rule_has_a_case():
    assert set(CASES) == set(RULES)


@pytest.mark.parametrize("rule_id", sorted(CASES))
def test_rule_fires_on_vulnerable_code(rule_id):
    name, bad, _ = CASES[rule_id]
    findings, checks = scan_rules([SourceFile(name, bad)], [RULES[rule_id]])
    assert [f.check_id for f in findings] == [f"code/{rule_id}"]
    assert findings[0].evidence[0].location.startswith(f"{name}:")
    assert checks[0].passed is False


@pytest.mark.parametrize("rule_id", sorted(CASES))
def test_rule_quiet_on_safe_code(rule_id):
    name, _, good = CASES[rule_id]
    findings, checks = scan_rules([SourceFile(name, good)], [RULES[rule_id]])
    assert findings == []
    assert all(c.passed for c in checks)


def test_file_line_evidence_and_redaction():
    key = "sk-proj-" + "Q" * 6 + "abcdefghijklmnopqrstu9876"
    findings, _ = scan_secrets_regex([SourceFile("config.py", f'# x\nOPENAI_API_KEY = "{key}"\n')])
    [f] = findings
    assert f.evidence[0].location == "config.py:2" and key not in f.evidence[0].excerpt and f.merge_key == "secret:config.py"


def test_gitleaks_wrapper_parses_report(monkeypatch, tmp_path):
    calls = []

    def fake_run(argv, timeout=0):
        calls.append(argv)
        if argv[1] == "detect":
            report = argv[argv.index("--report-path") + 1]
            with open(report, "w", encoding="utf-8") as fh:
                json.dump([{"RuleID": "openai-api-key", "File": str(tmp_path / "config.py"), "StartLine": 3, "Match": "REDACTED"}], fh)
        return subprocess.CompletedProcess(argv, 0, stdout="8.18.0", stderr="")

    monkeypatch.setattr(code_scan, "run_tool", fake_run)
    monkeypatch.setattr(code_scan.shutil, "which", lambda b: "/usr/bin/gitleaks")
    monkeypatch.setattr(code_scan, "bandit_version", lambda: None)
    result = run_code_scan(tmp_path, [SourceFile("config.py", "x = 1")])
    [f] = [f for f in result.findings if f.check_id.startswith("gitleaks/")]
    assert f.evidence[0].location == "config.py:3" and f.merge_key == "secret:config.py"
    assert "--redact" in calls[0] and "--no-git" in calls[0]
    assert result.stats["tools"]["gitleaks"] == "8.18.0"


def test_regex_rules_still_run_when_gitleaks_misses_a_key(monkeypatch, tmp_path):
    def fake_run(argv, timeout=0):
        if argv[1] == "detect":
            with open(argv[argv.index("--report-path") + 1], "w", encoding="utf-8") as fh:
                fh.write("[]")
        return subprocess.CompletedProcess(argv, 0, stdout="8.24.0", stderr="")

    monkeypatch.setattr(code_scan, "run_tool", fake_run)
    monkeypatch.setattr(code_scan.shutil, "which", lambda b: "/usr/bin/gitleaks")
    monkeypatch.setattr(code_scan, "bandit_version", lambda: None)
    key = "sk-proj-" + "W" * 6 + "abcdefghijklmnopqrstu5555"
    result = run_code_scan(tmp_path, [SourceFile("config.py", f'KEY = "{key}"')])
    assert result.stats["tools"]["gitleaks"] == "8.24.0"
    assert [f.check_id for f in result.findings] == ["regex-secret/openai-key"]


def test_without_gitleaks_uses_regex_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(code_scan.shutil, "which", lambda b: None)
    monkeypatch.setattr(code_scan, "bandit_version", lambda: None)
    key = "sk-proj-" + "W" * 6 + "abcdefghijklmnopqrstu5555"
    result = run_code_scan(tmp_path, [SourceFile("config.py", f'KEY = "{key}"')])
    assert result.stats["tools"] == {"gitleaks": "not found (regex fallback)", "bandit": "not installed (pip install bandit)"}
    assert [f.check_id for f in result.findings] == ["regex-secret/openai-key"]
    assert any("bandit not installed" in n for n in result.notes)


def test_gitleaks_failure_falls_back(monkeypatch, tmp_path):
    monkeypatch.setattr(code_scan.shutil, "which", lambda b: "/usr/bin/gitleaks")
    monkeypatch.setattr(code_scan, "run_tool", lambda argv, timeout=0: subprocess.CompletedProcess(argv, 1, "", "boom"))
    monkeypatch.setattr(code_scan, "bandit_version", lambda: None)
    result = run_code_scan(tmp_path, [])
    assert result.stats["tools"]["gitleaks"] == "not found (regex fallback)" and any("gitleaks failed" in n for n in result.notes)


@pytest.mark.skipif(code_scan.bandit_version() is None, reason="bandit not installed")
def test_bandit_maps_eval_and_shell(examples):
    root = examples / "vulnerable_bot"
    files = iter_text_files(root, max_files=100, max_file_bytes=100_000)
    findings, _ = scan_bandit(root, files)
    by_id = {f.check_id: f for f in findings}
    assert by_id["bandit/B307"].merge_key == "exec-model-output:tools.py"
    assert by_id["bandit/B602"].merge_key == "shell-model-output:tools.py"
    assert "eval(" in by_id["bandit/B307"].evidence[0].excerpt


BOOBY_TRAP = "import pathlib; pathlib.Path(r'{sentinel}').write_text('{name} was executed')\n"


def test_target_code_is_never_executed(monkeypatch, tmp_path, settings):
    """Every file that Python, pip or pytest would run on import/install writes a sentinel if executed."""
    from evalpilot.audit.intake import AuditInputs
    from evalpilot.audit.run import AuditOptions, run_audit

    repo = tmp_path / "trap"
    (repo / "pkg").mkdir(parents=True)
    sentinel = tmp_path / "EXECUTED"
    for name in ("setup.py", "conftest.py", "sitecustomize.py", "pkg/__init__.py", "pkg/__main__.py", "app.py"):
        (repo / name).write_text(BOOBY_TRAP.format(sentinel=sentinel, name=name) + "x = eval(llm_reply)\n", encoding="utf-8")
    (repo / "requirements.txt").write_text("requests\n", encoding="utf-8")
    (repo / "Makefile").write_text("all:\n\tpython app.py\n", encoding="utf-8")

    argvs = []
    real_run = subprocess.run

    def spy(argv, *a, **kw):
        argvs.append(list(argv))
        return real_run(argv, *a, **kw)

    monkeypatch.setattr(code_scan.subprocess, "run", spy)
    result = run_audit(settings, AuditInputs(path=repo), AuditOptions(provider="offline", out_dir=tmp_path / "runs"))

    assert not sentinel.exists()
    assert any(f.check_id == "code/llm-output-eval" for f in result.findings)
    for argv in argvs:
        is_bandit = argv[:3] == [sys.executable, "-m", "bandit"]
        is_gitleaks = "gitleaks" in argv[0].lower()
        assert is_bandit or is_gitleaks, argv
        assert not any(a.endswith(("setup.py", "app.py", "conftest.py")) for a in argv), argv
