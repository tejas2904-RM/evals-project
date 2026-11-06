import pytest

from evalpilot.cli import PLANNED, main

COMMANDS = ["run", "grade", "label", "calibrate", "compare", "gate", "report", "spend", "audit", "audit-diff", "audit-report"]


def test_help_lists_all_commands(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    for command in COMMANDS:
        assert command in out


def test_dry_run_offline(capsys, root):
    assert main(["--root", str(root), "run", "--dry-run", "--provider", "offline"]) == 0
    out = capsys.readouterr().out
    assert "41 of 41" in out
    assert "v1, v2, v3" in out
    assert "123 planned" in out


def test_dry_run_subset(capsys, root):
    assert main(["--root", str(root), "run", "--dry-run", "--version", "v3", "--cases", "fee_01,ent_02"]) == 0
    out = capsys.readouterr().out
    assert "2 of 41" in out and "2 planned" in out


def test_dry_run_unknown_case(capsys, root):
    assert main(["--root", str(root), "run", "--dry-run", "--cases", "nope"]) == 2
    assert "unknown case id" in capsys.readouterr().err


def test_bad_version_is_usage_error(root):
    with pytest.raises(SystemExit) as exc:
        main(["--root", str(root), "run", "--version", "v9"])
    assert exc.value.code == 2


def test_real_run_not_available_yet(capsys, root):
    assert main(["--root", str(root), "run", "--provider", "offline"]) == 2
    assert "Phase 3" in capsys.readouterr().err


def test_unknown_provider_is_error(capsys, root):
    assert main(["--root", str(root), "run", "--dry-run", "--provider", "anthropic"]) == 1
    assert "Unknown provider" in capsys.readouterr().err


def test_missing_model_env_is_error(monkeypatch, capsys, tmp_project):
    monkeypatch.delenv("EVALPILOT_BOT_MODEL")
    assert main(["--root", str(tmp_project), "run", "--dry-run"]) == 1
    assert "EVALPILOT_BOT_MODEL" in capsys.readouterr().err


@pytest.mark.parametrize("command", sorted(PLANNED))
def test_planned_commands_point_to_their_phase(capsys, command):
    assert main([command]) == 2
    assert f"Phase {PLANNED[command][1]}" in capsys.readouterr().err
