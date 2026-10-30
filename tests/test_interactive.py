import json
import subprocess

import pytest

import termux_sync as ts


class Script:
    def __init__(self, monkeypatch, prompts=(), confirms=()):
        self.prompts = list(prompts)
        self.confirms = list(confirms)
        monkeypatch.setattr(ts.Prompt, "ask", staticmethod(self._prompt))
        monkeypatch.setattr(ts.Confirm, "ask", staticmethod(self._confirm))

    def _prompt(self, *args, **kwargs):
        return self.prompts.pop(0)

    def _confirm(self, *args, **kwargs):
        return self.confirms.pop(0)


@pytest.fixture
def scripted(monkeypatch):
    def build(prompts=(), confirms=()):
        return Script(monkeypatch, prompts, confirms)

    return build


def test_setup_local_storage(config_home, scripted, capsys):
    scripted(prompts=["1", "/data/backups", "xz", "7"], confirms=[False])
    ts.cmd_setup()
    cfg = json.loads((config_home / "config.json").read_text())
    assert cfg["storage"] == "local"
    assert cfg["local_path"] == "/data/backups"
    assert cfg["compression"] == "xz"
    assert cfg["max_backups"] == 7
    assert "Configuration saved" in capsys.readouterr().out


def test_setup_retries_empty_path_and_bad_max_backups(config_home, scripted, capsys):
    scripted(prompts=["1", "  ", "/b", "gz", "zero", "0", "3"], confirms=[False])
    ts.cmd_setup()
    out = capsys.readouterr().out
    assert "Path cannot be empty" in out
    assert "whole number" in out
    assert json.loads((config_home / "config.json").read_text())["max_backups"] == 3


def test_setup_gdrive(config_home, scripted):
    scripted(prompts=["2", "folder123", "gz", "5"], confirms=[False])
    ts.cmd_setup()
    cfg = json.loads((config_home / "config.json").read_text())
    assert cfg["storage"] == "gdrive"
    assert cfg["gdrive_folder_id"] == "folder123"


def test_setup_github_validates_token_and_repo(config_home, scripted, capsys):
    scripted(
        prompts=["3", "", "ghp_abc", "", "bad", "/lead", "trail/", "owner/repo", "dev", "gz", "5"],
        confirms=[False],
    )
    ts.cmd_setup()
    out = capsys.readouterr().out
    assert "Token cannot be empty" in out
    assert "Repo cannot be empty" in out
    assert "Invalid format" in out
    cfg = json.loads((config_home / "config.json").read_text())
    assert cfg["github_token"] == "ghp_abc"
    assert cfg["github_repo"] == "owner/repo"
    assert cfg["github_branch"] == "dev"


def test_setup_github_keeps_saved_token(config_home, scripted, capsys):
    ts.save_config(dict(ts.DEFAULT_CONFIG, github_token="saved"))
    scripted(prompts=["3", "saved", "o/r", "main", "gz", "5"], confirms=[False])
    ts.cmd_setup()
    assert "already saved" in capsys.readouterr().out


def test_setup_custom_exclude_patterns(config_home, scripted):
    scripted(prompts=["1", "/b", "gz", "5", ".foo, .bar ,"], confirms=[True])
    ts.cmd_setup()
    cfg = json.loads((config_home / "config.json").read_text())
    assert cfg["exclude_patterns"] == [".foo", ".bar"]


def test_setup_blank_patterns_keep_defaults(config_home, scripted):
    scripted(prompts=["1", "/b", "gz", "5", "  "], confirms=[True])
    ts.cmd_setup()
    cfg = json.loads((config_home / "config.json").read_text())
    assert cfg["exclude_patterns"] == ts.DEFAULT_CONFIG["exclude_patterns"]


def test_schedule_enable(config_home, scripted, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ts, "CRON_FILE", config_home / "cron.json")
    monkeypatch.setattr(ts.Path, "home", classmethod(lambda cls: tmp_path))
    scripted(prompts=["x", "99", "4", "70", "oops", "15", "nightly"], confirms=[True])
    ts.cmd_schedule()
    out = capsys.readouterr().out
    assert "between 0 and 23" in out
    assert "between 0 and 59" in out
    assert "Invalid input" in out
    assert ts.load_schedule() == {"enabled": True, "hour": 4, "minute": 15, "label": "nightly"}
    script = tmp_path / ".termux" / "boot" / "termux-sync-daemon.sh"
    assert script.exists()
    assert "daemon" in script.read_text()
    assert script.stat().st_mode & 0o111


def test_schedule_disable(config_home, scripted, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ts, "CRON_FILE", config_home / "cron.json")
    monkeypatch.setattr(ts.Path, "home", classmethod(lambda cls: tmp_path))
    scripted(confirms=[False])
    ts.cmd_schedule()
    assert "Auto-backup disabled" in capsys.readouterr().out
    assert ts.load_schedule()["enabled"] is False


def test_daemon_requires_enabled_schedule(config_home, monkeypatch, capsys):
    monkeypatch.setattr(ts, "CRON_FILE", config_home / "cron.json")
    ts.cmd_daemon(dict(ts.DEFAULT_CONFIG))
    assert "not enabled" in capsys.readouterr().out


def test_daemon_runs_backup_then_loops(config_home, monkeypatch):
    monkeypatch.setattr(ts, "CRON_FILE", config_home / "cron.json")
    ts.save_schedule({"enabled": True, "hour": 3, "minute": 0, "label": "auto"})
    sleeps = []
    backups = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 3:
            raise KeyboardInterrupt

    def fake_backup(cfg, label=""):
        backups.append(label)
        if len(backups) == 1:
            raise RuntimeError("first run fails")

    monkeypatch.setattr(ts.time, "sleep", fake_sleep)
    monkeypatch.setattr(ts, "cmd_backup", fake_backup)
    with pytest.raises(KeyboardInterrupt):
        ts.cmd_daemon(dict(ts.DEFAULT_CONFIG))
    assert backups == ["auto", "auto"]
    assert all(0 < s <= 86400 for s in sleeps)
    log_text = (config_home / "sync.log").read_text()
    assert "Daemon backup failed: first run fails" in log_text


def test_clear_cache_nothing_to_clear(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ts, "CACHE_TARGETS", [("~/.cache", tmp_path / "missing")])
    ts.cmd_clear_cache()
    assert "Nothing to clear" in capsys.readouterr().out


@pytest.fixture
def cache_dirs(monkeypatch, tmp_path):
    first = tmp_path / "cache_a"
    second = tmp_path / "cache_b"
    for folder in (first, second):
        (folder / "sub").mkdir(parents=True)
        (folder / "sub" / "file.bin").write_bytes(b"x" * 100)
        (folder / "top.bin").write_bytes(b"y" * 50)
    monkeypatch.setattr(ts, "CACHE_TARGETS", [("cache a", first), ("cache b", second)])
    return first, second


def test_clear_cache_all(cache_dirs, scripted, capsys):
    scripted(prompts=[""], confirms=[True, True])
    ts.cmd_clear_cache()
    for folder in cache_dirs:
        assert folder.exists()
        assert list(folder.iterdir()) == []
    assert "Done!" in capsys.readouterr().out


def test_clear_cache_selection(cache_dirs, scripted):
    scripted(prompts=["2"], confirms=[True, True])
    ts.cmd_clear_cache()
    first, second = cache_dirs
    assert (first / "top.bin").exists()
    assert list(second.iterdir()) == []


def test_clear_cache_invalid_selection(cache_dirs, scripted, capsys):
    scripted(prompts=["abc"])
    ts.cmd_clear_cache()
    assert "Invalid selection" in capsys.readouterr().out


def test_clear_cache_out_of_range_selection(cache_dirs, scripted, capsys):
    scripted(prompts=["9"])
    ts.cmd_clear_cache()
    assert "No targets selected" in capsys.readouterr().out


@pytest.mark.parametrize("confirms", [[False], [True, False]])
def test_clear_cache_abort(cache_dirs, scripted, capsys, confirms):
    scripted(prompts=[""], confirms=confirms)
    ts.cmd_clear_cache()
    assert "Aborted" in capsys.readouterr().out
    assert (cache_dirs[0] / "top.bin").exists()


def test_clear_cache_logs_entries_it_cannot_remove(cache_dirs, config_home, scripted, monkeypatch, capsys):
    def boom(path, *args, **kwargs):
        raise OSError("locked")

    monkeypatch.setattr(ts.shutil, "rmtree", boom)
    scripted(prompts=["1"], confirms=[True, True])
    ts.cmd_clear_cache()
    first = cache_dirs[0]
    assert not (first / "top.bin").exists()
    assert (first / "sub").exists()
    assert "Could not remove" in (config_home / "sync.log").read_text()
    assert "Done!" in capsys.readouterr().out


def test_check_default_targets(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PREFIX", str(tmp_path / "usr"))
    (tmp_path / "usr").mkdir()
    (tmp_path / "file.bin").write_bytes(b"x" * 10)
    ts.cmd_check()
    out = capsys.readouterr().out
    assert "Home" in out
    assert "$PREFIX" in out


@pytest.mark.parametrize("alias", ["~", "$HOME", "home"])
def test_check_home_aliases_show_subdirectories(monkeypatch, tmp_path, capsys, alias):
    monkeypatch.setenv("HOME", str(tmp_path))
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.bin").write_bytes(b"x" * 2000)
    (tmp_path / "b.bin").write_bytes(b"x" * 100)
    ts.cmd_check(alias)
    out = capsys.readouterr().out
    assert "Home (~)" in out
    assert "docs" in out
    assert "b.bin" in out


@pytest.mark.parametrize("alias", ["$PREFIX", "prefix", "usr"])
def test_check_prefix_aliases(monkeypatch, tmp_path, capsys, alias):
    monkeypatch.setenv("PREFIX", str(tmp_path))
    ts.cmd_check(alias)
    assert "$PREFIX" in capsys.readouterr().out


def test_check_custom_path(tmp_path, capsys):
    (tmp_path / "a.bin").write_bytes(b"x" * 10)
    ts.cmd_check(str(tmp_path))
    out = capsys.readouterr().out
    assert "a.bin" in out
    assert "100.0%" in out


def test_check_missing_path(tmp_path, capsys):
    ts.cmd_check(str(tmp_path / "missing"))
    assert "Path not found" in capsys.readouterr().out


@pytest.mark.parametrize(
    "storage",
    [
        {"storage": "gdrive", "gdrive_folder_id": ""},
        {"storage": "github", "github_repo": "o/r", "github_branch": "dev"},
    ],
)
def test_status_for_remote_storage(config_home, monkeypatch, capsys, storage):
    monkeypatch.setattr(ts, "CRON_FILE", config_home / "cron.json")
    monkeypatch.setattr(ts.shutil, "which", lambda name: None)
    ts.save_schedule({"enabled": True, "hour": 1, "minute": 5, "label": "x"})
    ts.cmd_status(dict(ts.DEFAULT_CONFIG, **storage))
    out = capsys.readouterr().out
    assert storage["storage"].upper() in out
    assert "missing" in out
    assert "Daily at 01:05" in out


def test_status_counts_local_backups(config_home, local_cfg, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(ts, "CRON_FILE", config_home / "cron.json")
    (tmp_path / "backups" / "b1").mkdir(parents=True)
    ts.cmd_status(local_cfg)
    assert "Stored backups" in capsys.readouterr().out


def test_get_installed_packages_parses_dpkg(monkeypatch):
    output = "git\t\tinstall\npython\t\tinstall\nold\t\tdeinstall\n\nbroken\n"
    monkeypatch.setattr(
        ts.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=output, stderr="")
    )
    assert ts.get_installed_packages() == ["git", "python"]


def test_get_installed_packages_failure_returns_empty(monkeypatch):
    def boom(*args, **kwargs):
        raise FileNotFoundError("dpkg")

    monkeypatch.setattr(ts.subprocess, "run", boom)
    assert ts.get_installed_packages() == []


def test_install_packages_reports_failures(config_home, monkeypatch, capsys):
    def fake_run(cmd, **kwargs):
        if cmd[-1] == "bad":
            raise subprocess.CalledProcessError(1, cmd)
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(ts.subprocess, "run", fake_run)
    failed = ts.install_packages(["git", "bad"], ts.console)
    assert failed == ["bad"]
    assert "could not be installed" in capsys.readouterr().out
    assert "Packages failed to install: bad" in (config_home / "sync.log").read_text()


def test_install_packages_empty(capsys):
    assert ts.install_packages([], ts.console) == []
    assert "No packages to install" in capsys.readouterr().out


@pytest.mark.parametrize("width", [40, 120])
def test_print_banner(monkeypatch, capsys, width):
    monkeypatch.setattr(ts.console, "_width", width)
    ts.print_banner()
    out = capsys.readouterr().out
    assert f"v{ts.VERSION}" in out
    assert "Termux Backup & Restore" in out


def test_note_and_status_icon(capsys):
    ts.note("hello world")
    assert "hello world" in capsys.readouterr().out
    assert "✓" in ts.status_icon(True)
    assert "✗" in ts.status_icon(False)


def test_is_narrow_follows_console_width(monkeypatch):
    monkeypatch.setattr(ts.console, "_width", 45)
    assert ts.is_narrow() is True
    monkeypatch.setattr(ts.console, "_width", 120)
    assert ts.is_narrow() is False


def test_handle_crash_in_debug_mode_prints_traceback(config_home, monkeypatch, capsys):
    monkeypatch.setattr(ts, "DEBUG", True)
    try:
        raise KeyError("boom")
    except KeyError as exc:
        ts.handle_crash(exc)
    out = capsys.readouterr().out
    assert "Full traceback" in out
    assert "KeyError" in out


@pytest.mark.parametrize("command", ["update", "upgrade", "install", "remove", "config", "sync"])
def test_unknown_but_common_commands_show_hints(capsys, command):
    with pytest.raises(SystemExit) as info:
        ts.main([command])
    assert info.value.code == 2
    assert command in capsys.readouterr().out


@pytest.mark.parametrize("command", ["status", "logs", "check", "list", "clear-logs"])
def test_main_dispatches_commands(config_home, monkeypatch, tmp_path, capsys, command):
    monkeypatch.setattr(ts, "CRON_FILE", config_home / "cron.json")
    monkeypatch.setattr(ts.Confirm, "ask", staticmethod(lambda *a, **k: False))
    ts.main([command, str(tmp_path)] if command == "check" else [command])
    assert capsys.readouterr().out


def test_main_executes_as_script(monkeypatch, capsys):
    import runpy
    from pathlib import Path

    source = Path(ts.__file__)
    monkeypatch.setattr(ts.sys, "argv", [str(source), "--version"])
    runpy.run_path(str(source), run_name="__main__")
    assert f"termux-sync v{ts.VERSION}" in capsys.readouterr().out


class RcloneRecorder:
    def __init__(self, listing=None, manifests=None, fail_on=()):
        self.calls = []
        self.listing = listing or []
        self.manifests = manifests or {}
        self.fail_on = fail_on

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if cmd[1] in self.fail_on:
            raise subprocess.CalledProcessError(1, cmd)
        if cmd[1] == "lsjson":
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(self.listing), stderr="")
        if cmd[1] == "cat":
            name = cmd[2].split("/")[-2]
            if name not in self.manifests:
                raise subprocess.CalledProcessError(1, cmd)
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(self.manifests[name]), stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


@pytest.fixture
def gdrive(local_cfg, monkeypatch):
    monkeypatch.setattr(ts.shutil, "which", lambda name: "/usr/bin/rclone")

    def build(**kwargs):
        recorder = RcloneRecorder(**kwargs)
        monkeypatch.setattr(ts.subprocess, "run", recorder)
        return ts.GDriveStorage(dict(local_cfg, storage="gdrive", gdrive_folder_id="FID")), recorder

    return build


def test_gdrive_remote_path(gdrive):
    storage, _ = gdrive()
    assert storage._remote_path() == "termux-sync-gdrive:FID"
    assert storage._remote_path("b1") == "termux-sync-gdrive:FID/b1"


def test_gdrive_remote_path_without_folder(local_cfg, monkeypatch):
    monkeypatch.setattr(ts.shutil, "which", lambda name: "/usr/bin/rclone")
    storage = ts.GDriveStorage(dict(local_cfg, storage="gdrive"))
    assert storage._remote_path() == "termux-sync-gdrive:"


def test_gdrive_upload_and_download(gdrive, tmp_path):
    storage, recorder = gdrive()
    with ts.make_progress() as progress:
        assert storage.upload(tmp_path, "b1", progress) == "termux-sync-gdrive:FID/b1"
        storage.download("b1", tmp_path / "dl", progress)
    assert [call[1] for call in recorder.calls] == ["copy", "copy"]
    assert (tmp_path / "dl").exists()


def test_gdrive_list_backups_falls_back_to_listing(gdrive):
    listing = [
        {"Name": "b1", "ModTime": "2026-01-01T00:00:00Z"},
        {"Name": "b2", "ModTime": "2026-02-01T00:00:00Z"},
    ]
    manifests = {"b2": {"name": "b2", "date": "2026-02-01"}}
    storage, _ = gdrive(listing=listing, manifests=manifests)
    backups = storage.list_backups()
    assert [b["name"] for b in backups] == ["b2", "b1"]
    assert backups[1]["date"] == "2026-01-01T00:00:00Z"


def test_gdrive_list_backups_failure(gdrive):
    storage, _ = gdrive(fail_on=("lsjson",))
    assert storage.list_backups() == []


def test_gdrive_delete_old_purges_oldest(gdrive):
    listing = [{"Name": f"b{i}", "ModTime": f"2026-0{i}-01"} for i in (1, 2, 3)]
    storage, recorder = gdrive(listing=listing)
    storage.delete_old(1)
    purged = [call[2] for call in recorder.calls if call[1] == "purge"]
    assert purged == ["termux-sync-gdrive:FID/b2", "termux-sync-gdrive:FID/b1"]


def test_gdrive_delete_old_ignores_failures(gdrive):
    storage, _ = gdrive(fail_on=("lsjson",))
    storage.delete_old(1)


def test_gdrive_delete_backup_failure(gdrive):
    storage, _ = gdrive(fail_on=("purge",))
    with pytest.raises(RuntimeError, match="Failed to delete backup from Google Drive"):
        storage.delete_backup("b1")
