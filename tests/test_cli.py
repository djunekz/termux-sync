import re
from pathlib import Path

import pytest

import termux_sync as ts


def test_version_flag_prints_version(capsys):
    ts.main(["--version"])
    assert capsys.readouterr().out.strip() == f"termux-sync v{ts.VERSION}"


def test_short_version_flag(capsys):
    ts.main(["-v"])
    assert ts.VERSION in capsys.readouterr().out


def test_help_command_lists_commands(capsys):
    ts.main(["help"])
    out = capsys.readouterr().out
    for name in ("backup", "restore", "list"):
        assert name in out


def test_no_arguments_shows_help(capsys):
    ts.main([])
    assert "backup" in capsys.readouterr().out


def test_unknown_command_exits_with_usage_code(capsys):
    with pytest.raises(SystemExit) as info:
        ts.main(["backpu"])
    assert info.value.code == 2
    out = capsys.readouterr().out
    assert "Unknown command" in out
    assert "backup" in out


def test_invalid_option_value_exits(capsys):
    with pytest.raises(SystemExit) as info:
        ts.main(["logs", "--lines", "many"])
    assert info.value.code == 2
    assert "Invalid usage" in capsys.readouterr().out


def test_parser_defaults():
    args = ts.build_parser().parse_args([])
    assert args.command == "help"
    assert args.lines == 40
    assert args.label == ""
    assert args.debug is False


def test_parser_reads_options():
    args = ts.build_parser().parse_args(["backup", "--label", "pre-update", "--debug"])
    assert args.command == "backup"
    assert args.label == "pre-update"
    assert args.debug is True


def test_all_listed_commands_are_registered():
    assert len(ts.COMMANDS) == len(set(ts.COMMANDS))
    assert {"backup", "restore", "list", "delete", "setup"} <= set(ts.COMMANDS)


def test_command_failure_exits_with_one(config_home, monkeypatch, capsys):
    def explode(cfg, label=""):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(ts, "cmd_backup", explode)
    with pytest.raises(SystemExit) as info:
        ts.main(["backup"])
    assert info.value.code == 1
    assert "simulated failure" in capsys.readouterr().out


def test_keyboard_interrupt_exits_with_130(config_home, monkeypatch, capsys):
    def interrupt(cfg):
        raise KeyboardInterrupt

    monkeypatch.setattr(ts, "cmd_list", interrupt)
    with pytest.raises(SystemExit) as info:
        ts.main(["list"])
    assert info.value.code == 130
    assert "Operation cancelled" in capsys.readouterr().out


def test_package_and_project_versions_match():
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
    assert match is not None
    assert match.group(1) == ts.VERSION
