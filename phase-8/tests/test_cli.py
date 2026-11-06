from evalpilot.cli import main
from evalpilot.llm import Ledger, Usage

COMMANDS = ["run", "grade", "label", "calibrate", "compare", "gate", "report", "verdict", "spend", "smoke", "audit", "audit-diff", "audit-report", "serve"]


def test_help_lists_all_commands(capsys):
    assert main(["--help"]) == 0
    out = capsys.readouterr().out
    for command in COMMANDS:
        assert command in out


def test_version_flag(capsys):
    assert main(["--version"]) == 0
    assert "evalpilot 0.8.0" in capsys.readouterr().out


def test_dry_run_offline_prints_plan_and_spend(capsys, root):
    assert main(["--root", str(root), "run", "--dry-run", "--provider", "offline"]) == 0
    out = capsys.readouterr().out
    assert "41 of 41" in out and "v1, v2, v3" in out and "123 planned" in out
    assert "Spend: $0.0000 / $3.00" in out


def test_dry_run_subset(capsys, root):
    assert main(["--root", str(root), "run", "--dry-run", "--version", "v3", "--cases", "fee_01,ent_02"]) == 0
    out = capsys.readouterr().out
    assert "2 of 41" in out and "2 planned" in out


def test_dry_run_unknown_case(capsys, root):
    assert main(["--root", str(root), "run", "--dry-run", "--cases", "nope"]) == 2
    assert "unknown case id" in capsys.readouterr().err


def test_bad_version_is_usage_error(root):
    assert main(["--root", str(root), "run", "--version", "v9"]) == 2


def test_run_offline_writes_123_traces(capsys, root, settings):
    assert main(["--root", str(root), "run", "--provider", "offline"]) == 0
    out = capsys.readouterr().out
    assert "v1: 41 traces" in out and "v2: 41 traces" in out and "v3: 41 traces" in out
    assert "Spend: $0.0000 / $3.00" in out and "this run: $0.0000" in out
    [run] = list(settings.runs_dir.iterdir())
    assert sum(1 for _ in (run / "traces.jsonl").open(encoding="utf-8")) == 123
    assert (run / "meta.json").is_file()


def test_run_subset(capsys, root):
    assert main(["--root", str(root), "run", "--provider", "offline", "--version", "v3", "--cases", "ent_01"]) == 0
    assert "v3: 1 traces" in capsys.readouterr().out


def test_run_openai_without_key_is_clear_error(capsys, root):
    assert main(["--root", str(root), "run", "--provider", "openai", "--cases", "fee_01"]) == 1
    assert "OPENAI_API_KEY is not set" in capsys.readouterr().err


def test_unknown_provider_is_error(capsys, root):
    assert main(["--root", str(root), "run", "--dry-run", "--provider", "anthropic"]) == 1
    assert "Unknown provider" in capsys.readouterr().err


def test_missing_model_env_is_error(monkeypatch, capsys, tmp_project):
    monkeypatch.delenv("EVALPILOT_BOT_MODEL")
    assert main(["--root", str(tmp_project), "run", "--dry-run"]) == 1
    assert "EVALPILOT_BOT_MODEL" in capsys.readouterr().err


def test_spend_empty_ledger(capsys, root):
    assert main(["--root", str(root), "spend"]) == 0
    assert "Spend: $0.0000 / $3.00 ($3.0000 left)" in capsys.readouterr().out


def test_spend_groups_by_model(capsys, root, settings):
    ledger = Ledger(settings.ledger_path)
    for model, usd in [("gpt-5.4-nano", 0.01), ("gpt-5.4-nano", 0.02), ("gpt-5.4-mini", 0.10)]:
        ledger.append(run_id="r", provider="openai", model=model, purpose="bot", usage=Usage(), cost=usd)
    assert main(["--root", str(root), "spend"]) == 0
    out = capsys.readouterr().out
    assert "gpt-5.4-nano" in out and "2 calls" in out and "$0.0300" in out
    assert "Spend: $0.1300 / $3.00" in out


def test_smoke_offline(capsys, root):
    assert main(["--root", str(root), "smoke", "--provider", "offline"]) == 0
    out = capsys.readouterr().out
    assert "reply    : pong" in out and "cost     : $0.000000" in out
    assert "Spend: $0.0000" in out


def test_smoke_openai_without_key_is_clear_error(capsys, root):
    assert main(["--root", str(root), "smoke", "--provider", "openai"]) == 1
    assert "OPENAI_API_KEY is not set" in capsys.readouterr().err


def test_smoke_refused_over_budget(capsys, root, settings, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr("evalpilot.llm.providers.openai_transport", lambda *a, **k: lambda r: None)
    Ledger(settings.ledger_path).append(
        run_id="old", provider="openai", model="gpt-5.4-mini", purpose="judge", usage=Usage(), cost=3.0
    )
    assert main(["--root", str(root), "smoke", "--provider", "openai"]) == 1
    assert "Budget reached" in capsys.readouterr().err
