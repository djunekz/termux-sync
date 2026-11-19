import hashlib
import io
import json
import os
import stat
import tarfile
import tempfile

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


def test_tmp_root_prefers_tmpdir(monkeypatch, tmp_path):
    monkeypatch.setenv("TMPDIR", str(tmp_path / "t"))
    assert ts._tmp_root() == tmp_path / "t"


def test_tmp_root_uses_prefix_tmp_when_present(monkeypatch, tmp_path):
    monkeypatch.delenv("TMPDIR", raising=False)
    (tmp_path / "tmp").mkdir()
    monkeypatch.setenv("PREFIX", str(tmp_path))
    assert ts._tmp_root() == tmp_path / "tmp"


def test_tmp_root_falls_back_to_system_temp(monkeypatch, tmp_path):
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.setenv("PREFIX", str(tmp_path / "missing"))
    assert ts._tmp_root() == type(tmp_path)(tempfile.gettempdir())


def test_save_config_survives_chmod_failure(config_home, monkeypatch):
    def refuse(*args, **kwargs):
        raise OSError("not allowed")

    monkeypatch.setattr(os, "chmod", refuse)
    ts.save_config({"a": 1})
    assert json.loads((config_home / "config.json").read_text()) == {"a": 1}


def test_local_delete_rejects_dot_names(tmp_path):
    storage = ts.LocalStorage({"local_path": str(tmp_path)})
    with pytest.raises(ValueError):
        storage.delete_backup("..")


def test_storage_excludes_ignores_source_itself(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    cfg = {"storage": "local", "local_path": str(home)}
    assert ts._storage_excludes(cfg, home) == []


def make_manifest_backup(root, name, files):
    folder = root / name
    folder.mkdir(parents=True)
    manifest = {
        "name": name,
        "date": "2026-01-01T00:00:00",
        "files": files,
        "packages": [],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))


def test_restore_refuses_unsafe_archive_names(local_cfg, tmp_path, answers, config_home):
    root = tmp_path / "backups"
    make_manifest_backup(
        root, "b1", {"home": {"archive": "../evil.tar.gz", "size": 1, "checksum": "x"}}
    )
    answers(confirm=True)
    ts.cmd_restore(local_cfg, backup_name="b1")
    log_text = (config_home / "sync.log").read_text()
    assert "Unsafe archive name in manifest" in log_text
    assert "Skipped unsafe archive name in manifest" in log_text


def test_delete_rejects_invalid_name(local_cfg, tmp_path, answers, capsys):
    root = tmp_path / "backups"
    make_manifest_backup(root, "b1", {})
    answers(confirm=True)
    ts.cmd_delete(local_cfg, backup_name="..")
    assert "Invalid backup name" in capsys.readouterr().out
    assert (root / "b1").exists()


def test_extract_logs_members_that_cannot_be_written(tmp_path, monkeypatch, config_home):
    source = tmp_path / "src"
    source.mkdir()
    (source / "f.txt").write_text("x")
    archive = tmp_path / "a.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        tf.add(source / "f.txt", arcname="f.txt")

    def refuse(self, *args, **kwargs):
        raise OSError("disk says no")

    monkeypatch.setattr(tarfile.TarFile, "extract", refuse)
    with ts.make_progress() as progress:
        ts.extract_archive(archive, tmp_path / "out", "a", progress)
    assert "Could not extract" in (config_home / "sync.log").read_text()


def test_extract_rejects_hardlink_escaping_destination(tmp_path, config_home):
    archive = tmp_path / "h.tar.gz"
    with tarfile.open(archive, "w:gz") as tf:
        info = tarfile.TarInfo("link")
        info.type = tarfile.LNKTYPE
        info.linkname = "../outside"
        tf.addfile(info)
    with ts.make_progress() as progress:
        ts.extract_archive(archive, tmp_path / "out", "h", progress)
    assert not (tmp_path / "out" / "link").exists()
    assert "Skipped unsafe archive member" in (config_home / "sync.log").read_text()


def _write_tar(path, members):
    with tarfile.open(path, "w:gz") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            tf.addfile(info, io.BytesIO(data))


def test_extract_rejects_members_outside_expected_root(tmp_path, config_home):
    archive = tmp_path / "usr_etc.tar.gz"
    _write_tar(archive, {"etc/motd": b"ok\n", "bin/sh": b"#!/bin/sh\necho pwned\n"})
    prefix = tmp_path / "prefix"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "sh").write_text("original")
    with ts.make_progress() as progress:
        ts.extract_archive(archive, prefix, "usr_etc.tar.gz", progress, expected_top="etc")
    assert (prefix / "etc" / "motd").read_text() == "ok\n"
    assert (prefix / "bin" / "sh").read_text() == "original"
    assert "outside expected root" in (config_home / "sync.log").read_text()


def test_restore_usr_etc_archive_cannot_touch_prefix_bin(
    local_cfg, tmp_path, answers, config_home, monkeypatch
):
    prefix = tmp_path / "prefix"
    home = tmp_path / "files" / "home"
    (prefix / "etc").mkdir(parents=True)
    (prefix / "bin").mkdir()
    home.mkdir(parents=True)
    (prefix / "bin" / "sh").write_text("original")
    monkeypatch.setattr(ts, "TERMUX_HOME", prefix)
    monkeypatch.setattr(ts, "TERMUX_FILES", home)
    monkeypatch.setattr(
        ts,
        "BACKUP_ITEMS",
        [
            ("packages", "Installed package list", None),
            ("home", "Home directory (~)", home),
            ("usr_etc", "Termux config (/usr/etc)", prefix / "etc"),
        ],
    )

    root = tmp_path / "backups"
    folder = root / "evil"
    folder.mkdir(parents=True)
    arc = folder / "usr_etc.tar.gz"
    _write_tar(arc, {"etc/motd": b"ok\n", "bin/sh": b"echo pwned\n"})
    checksum = hashlib.sha256(arc.read_bytes()).hexdigest()
    (folder / "manifest.json").write_text(json.dumps({
        "name": "evil",
        "date": "2026-01-01T00:00:00",
        "files": {"usr_etc": {"archive": "usr_etc.tar.gz", "size": arc.stat().st_size,
                              "checksum": checksum}},
        "packages": [],
    }))
    answers(confirm=True)
    ts.cmd_restore(local_cfg, backup_name="evil")
    assert (prefix / "etc" / "motd").read_text() == "ok\n"
    assert (prefix / "bin" / "sh").read_text() == "original"


def test_install_packages_refuses_option_like_names(monkeypatch, config_home):
    calls = []
    monkeypatch.setattr(ts.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    failed = ts.install_packages(["git", "--allow-unauthenticated", "-oAPT::Foo=1"], ts.console)
    assert calls == [["pkg", "install", "-y", "--", "git"]]
    assert failed == ["--allow-unauthenticated", "-oAPT::Foo=1"]


def _write_special_tar(path, entries):
    with tarfile.open(path, "w:gz") as tf:
        for name, kind, payload in entries:
            info = tarfile.TarInfo(name)
            info.mode = 0o755
            if kind == "sym":
                info.type = tarfile.SYMTYPE
                info.linkname = payload
                tf.addfile(info)
            elif kind == "hard":
                info.type = tarfile.LNKTYPE
                info.linkname = payload
                tf.addfile(info)
            else:
                info.size = len(payload)
                tf.addfile(info, io.BytesIO(payload))


def test_extract_blocks_symlink_pivot_out_of_expected_root(tmp_path, config_home):
    prefix = tmp_path / "prefix"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "sh").write_text("original")
    archive = tmp_path / "evil.tar.gz"
    _write_special_tar(archive, [("etc", "sym", "bin"), ("etc/sh", "file", b"PWNED")])
    with ts.make_progress() as progress:
        ts.extract_archive(archive, prefix, "usr_etc", progress, expected_top="etc")
    assert (prefix / "bin" / "sh").read_text() == "original"
    assert not (prefix / "etc").is_symlink()


def test_extract_blocks_hardlink_to_file_outside_expected_root(tmp_path, config_home):
    prefix = tmp_path / "prefix"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "sh").write_text("original")
    archive = tmp_path / "evil.tar.gz"
    _write_special_tar(archive, [("etc/x", "hard", "bin/sh"), ("etc/x", "file", b"PWNED")])
    with ts.make_progress() as progress:
        ts.extract_archive(archive, prefix, "usr_etc", progress, expected_top="etc")
    assert (prefix / "bin" / "sh").read_text() == "original"


def test_extract_allows_relative_symlink_inside_expected_root(tmp_path, config_home):
    prefix = tmp_path / "prefix"
    prefix.mkdir()
    archive = tmp_path / "ok.tar.gz"
    _write_special_tar(
        archive,
        [("etc/real.conf", "file", b"data"), ("etc/link.conf", "sym", "real.conf")],
    )
    with ts.make_progress() as progress:
        ts.extract_archive(archive, prefix, "usr_etc", progress, expected_top="etc")
    assert (prefix / "etc" / "link.conf").read_text() == "data"


def test_extract_blocks_write_through_existing_symlink_inside_root(tmp_path, config_home):
    prefix = tmp_path / "prefix"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "sh").write_text("original")
    (prefix / "etc").mkdir()
    (prefix / "etc" / "link").symlink_to("../bin")
    archive = tmp_path / "evil.tar.gz"
    _write_special_tar(archive, [("etc/link/sh", "file", b"PWNED")])
    with ts.make_progress() as progress:
        ts.extract_archive(archive, prefix, "usr_etc", progress, expected_top="etc")
    assert (prefix / "bin" / "sh").read_text() == "original"
    assert "escapes" in (config_home / "sync.log").read_text()
