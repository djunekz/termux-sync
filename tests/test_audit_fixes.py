import json
import stat
import tarfile

import pytest

import termux_sync as ts


def test_clean_backup_name_rejects_unsafe_values():
    assert ts._clean_backup_name("..") == ""
    assert ts._clean_backup_name("") == ""
    assert ts._clean_backup_name("../../etc") == "etc"
    assert ts._clean_backup_name("termux_backup_1") == "termux_backup_1"


def test_clean_label_replaces_special_characters():
    assert ts._clean_label("before reset") == "before_reset"
    assert "/" not in ts._clean_label("../a/b")


def test_save_config_uses_private_permissions(config_home):
    ts.save_config({"github_token": "secret"})
    mode = stat.S_IMODE((config_home / "config.json").stat().st_mode)
    assert mode == 0o600


def test_exclude_patterns_match_whole_components(tmp_path):
    root = tmp_path / "home"
    (root / ".cache").mkdir(parents=True)
    (root / ".cache" / "junk").write_text("x")
    (root / "a.cache.txt").write_text("keep")
    out = tmp_path / "h.tar.gz"

    class Progress:
        def add_task(self, *a, **k):
            return 1

        def update(self, *a, **k):
            pass

    ts.create_archive(root, out, "gz", [".cache"], "home", Progress())
    names = tarfile.open(out).getnames()
    assert "home/a.cache.txt" in names
    assert not any(n.startswith("home/.cache") for n in names)


def test_storage_excludes_skips_local_backup_folder_inside_source(tmp_path):
    home = tmp_path / "home"
    (home / "termux-backups").mkdir(parents=True)
    cfg = {"storage": "local", "local_path": str(home / "termux-backups")}
    assert ts._storage_excludes(cfg, home) == ["home/termux-backups"]
    assert ts._storage_excludes(dict(cfg, storage="github"), home) == []
    assert ts._storage_excludes(dict(cfg, local_path=str(tmp_path / "other")), home) == []


def test_backup_does_not_include_previous_local_backups(termux_tree, config_home, tmp_path):
    cfg = dict(ts.DEFAULT_CONFIG)
    cfg["local_path"] = str(termux_tree / "home" / "termux-backups")
    ts.cmd_backup(cfg, label="one")
    ts.cmd_backup(cfg, label="two")
    archives = sorted((termux_tree / "home" / "termux-backups").glob("*/home.tar.gz"))
    assert len(archives) == 2
    for archive in archives:
        assert not any("termux-backups" in n for n in tarfile.open(archive).getnames())


def test_local_delete_never_leaves_backup_folder(tmp_path):
    store = tmp_path / "store"
    (store / "b1").mkdir(parents=True)
    victim = tmp_path / "victim"
    victim.mkdir()
    storage = ts.LocalStorage({"local_path": str(store)})
    with pytest.raises((ValueError, FileNotFoundError)):
        storage.delete_backup("../victim")
    assert victim.exists()


def test_import_config_rejects_non_object(config_home, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps([1, 2, 3]))
    with pytest.raises(ts.UserError):
        ts.cmd_import_config(str(bad))


def test_logs_colour_warning_lines(config_home, capsys):
    ts.log("WARNING", "something odd")
    ts.cmd_logs(10)
    assert "something odd" in capsys.readouterr().out


def test_daemon_skips_backup_when_disabled_during_wait(config_home, monkeypatch):
    monkeypatch.setattr(ts, "CRON_FILE", config_home / "cron.json")
    ts.save_schedule({"enabled": True, "hour": 3, "minute": 0, "label": "auto"})
    calls = []

    def fake_sleep(seconds):
        calls.append(seconds)
        ts.save_schedule({"enabled": False, "hour": 3, "minute": 0, "label": "auto"})

    monkeypatch.setattr(ts.time, "sleep", fake_sleep)
    monkeypatch.setattr(ts, "cmd_backup", lambda cfg, label="": calls.append("backup"))
    ts.cmd_daemon(dict(ts.DEFAULT_CONFIG))
    assert "backup" not in calls
    assert len(calls) == 1
