from evalpilot.secret_check import _walk, main, scan

FAKE = "sk-proj-" + "Z9" * 15  # assembled at runtime so this file never holds a key-shaped literal


def test_flags_key_outside_allowlist(tmp_path):
    (tmp_path / "app.py").write_text(f'KEY = "{FAKE}"\n', encoding="utf-8")
    [hit] = scan(tmp_path, ["app.py"])
    assert (hit.path, hit.line, hit.rule) == ("app.py", 1, "openai-key")
    assert FAKE not in hit.masked


def test_vulnerable_bot_and_inline_allow_are_skipped(tmp_path):
    (tmp_path / "examples" / "vulnerable_bot").mkdir(parents=True)
    (tmp_path / "examples" / "vulnerable_bot" / "config.py").write_text(f'K = "{FAKE}"\n', encoding="utf-8")
    (tmp_path / "t.py").write_text(f'K = "{FAKE}"  # secret-check: allow\n', encoding="utf-8")
    assert scan(tmp_path, ["examples/vulnerable_bot/config.py", "t.py"]) == []


def test_walk_skips_env_cache_and_unreferenced_runs(tmp_path):
    for rel in (".env", ".cache/spend.jsonl", "runs/2026/traces.jsonl", "runs/reference/x/grades.jsonl", "src/a.py"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("x", encoding="utf-8")
    assert _walk(tmp_path) == ["runs/reference/x/grades.jsonl", "src/a.py"]


def test_main_exit_codes(tmp_path, capsys):
    (tmp_path / "ok.py").write_text("print('hi')\n", encoding="utf-8")
    assert main([str(tmp_path)]) == 0
    (tmp_path / "bad.py").write_text(f'K = "{FAKE}"\n', encoding="utf-8")
    assert main([str(tmp_path)]) == 1
    assert "bad.py:1: openai-key" in capsys.readouterr().out


def test_project_tree_is_clean(root):
    assert main([str(root)]) == 0
