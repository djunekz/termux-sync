import json
import tarfile

import pytest

import termux_sync as ts


def run_backup(local_cfg, label=""):
    ts.cmd_backup(local_cfg, label=label)
    backups = ts.LocalStorage(local_cfg).list_backups()
    assert backups
    return backups[0]


def test_create_archive_honours_excludes(termux_tree, tmp_path):
    out = tmp_path / "home.tar.gz"
    with ts.make_progress() as progress:
        result = ts.create_archive(termux_tree / "home", out, "gz", [".cache"], "home", progress)
    with tarfile.open(result) as tf:
        names = tf.getnames()
    assert "home/.bashrc" in names
    assert not any(".cache" in name for name in names)


def test_create_archive_invalid_compression_falls_back(termux_tree, tmp_path):
    out = tmp_path / "home.tar.gz"
    with ts.make_progress() as progress:
        result = ts.create_archive(termux_tree / "home", out, "zip", [], "home", progress)
    assert result.name.endswith(".tar.gz")
    assert tarfile.is_tarfile(result)


@pytest.mark.parametrize("compression", ["gz", "bz2", "xz"])
def test_create_archive_extension_follows_compression(termux_tree, tmp_path, compression):
    with ts.make_progress() as progress:
        result = ts.create_archive(
            termux_tree / "usr" / "etc", tmp_path / "etc.tar.gz", compression, [], "etc", progress
        )
    assert result.name == f"etc.tar.{compression}"


def test_create_archive_into_sink(termux_tree):
    import io

    buffer = io.BytesIO()
    with ts.make_progress() as progress:
        ts.create_archive(termux_tree / "usr" / "etc", termux_tree / "unused", "gz", [], "etc", progress, sink=buffer)
    buffer.seek(0)
    with tarfile.open(fileobj=buffer) as tf:
        assert "etc/motd" in tf.getnames()


def test_create_archive_restores_permissions(termux_tree, tmp_path):
    locked = termux_tree / "home" / "projects" / "notes.txt"
    locked.chmod(0o000)
    try:
        with ts.make_progress() as progress:
            result = ts.create_archive(termux_tree / "home", tmp_path / "h.tar.gz", "gz", [], "home", progress)
        with tarfile.open(result) as tf:
            assert "home/projects/notes.txt" in tf.getnames()
        assert locked.stat().st_mode & 0o777 == 0o000
    finally:
        locked.chmod(0o644)


def test_extract_archive_round_trip(termux_tree, tmp_path):
    with ts.make_progress() as progress:
        archive = ts.create_archive(termux_tree / "usr" / "etc", tmp_path / "etc.tar.gz", "gz", [], "etc", progress)
        dest = tmp_path / "out"
        ts.extract_archive(archive, dest, "etc", progress)
    assert (dest / "etc" / "motd").read_text() == "welcome\n"


def test_extract_archive_skips_unsafe_members(tmp_path, config_home):
    archive = tmp_path / "evil.tar"
    payload = tmp_path / "payload.txt"
    payload.write_text("owned")
    with tarfile.open(archive, "w") as tf:
        tf.add(payload, arcname="safe.txt")
        tf.add(payload, arcname="../escape.txt")
    dest = tmp_path / "dest"
    with ts.make_progress() as progress:
        ts.extract_archive(archive, dest, "evil", progress)
    assert (dest / "safe.txt").exists()
    assert not (tmp_path / "escape.txt").exists()
    assert "Skipped unsafe archive member" in (config_home / "sync.log").read_text()


def test_backup_creates_manifest_with_checksums(termux_tree, local_cfg, capsys):
    backup = run_backup(local_cfg, label="before reset")
    assert backup["label"] == "before reset"
    assert backup["name"].endswith("_before_reset")
    assert backup["packages"] == ["git", "python"]
    assert set(backup["files"]) == {"home", "usr_etc"}
    for info in backup["files"].values():
        assert len(info["checksum"]) == 64
        assert info["size"] > 0
    assert "Backup completed successfully" in capsys.readouterr().out


def test_backup_applies_retention(termux_tree, local_cfg, monkeypatch):
    import itertools

    ticks = itertools.count()
    monkeypatch.setattr(
        ts.datetime, "datetime", type("D", (ts.datetime.datetime,), {"now": classmethod(lambda cls: cls(2026, 1, 1, 0, 0, next(ticks)))})
    )
    config = dict(local_cfg, max_backups=2)
    for _ in range(4):
        ts.cmd_backup(config)
    assert len(ts.LocalStorage(config).list_backups()) == 2


def test_backup_invalid_compression_warns_and_uses_gz(termux_tree, local_cfg, capsys):
    backup = run_backup(dict(local_cfg, compression="rar"))
    assert backup["files"]["home"]["archive"].endswith(".tar.gz")
    assert "invalid" in capsys.readouterr().out


def test_backup_keeps_files_when_upload_fails(termux_tree, local_cfg, monkeypatch, capsys):
    def boom(self, backup_dir, name, progress):
        raise RuntimeError("disk exploded")

    monkeypatch.setattr(ts.LocalStorage, "upload", boom)
    ts.cmd_backup(local_cfg)
    out = capsys.readouterr().out
    assert "Upload failed" in out
    assert "were kept" in out


def test_list_shows_backups(termux_tree, local_cfg, capsys):
    run_backup(local_cfg, label="first")
    capsys.readouterr()
    ts.cmd_list(local_cfg)
    out = capsys.readouterr().out
    assert "1 Backup(s) Found" in out
    assert "first" in out


def test_list_empty(local_cfg, capsys):
    ts.cmd_list(local_cfg)
    assert "No backups found" in capsys.readouterr().out


def test_delete_with_confirmation(termux_tree, local_cfg, answers, capsys):
    backup = run_backup(local_cfg)
    answers(confirm=True)
    ts.cmd_delete(local_cfg, backup_name=backup["name"])
    assert ts.LocalStorage(local_cfg).list_backups() == []
    assert "deleted successfully" in capsys.readouterr().out


def test_delete_cancelled(termux_tree, local_cfg, answers, capsys):
    backup = run_backup(local_cfg)
    answers(confirm=False)
    ts.cmd_delete(local_cfg, backup_name=backup["name"])
    assert len(ts.LocalStorage(local_cfg).list_backups()) == 1
    assert "Cancelled" in capsys.readouterr().out


def test_delete_by_number(termux_tree, local_cfg, answers):
    run_backup(local_cfg)
    answers(confirm=True, prompt="1")
    ts.cmd_delete(local_cfg)
    assert ts.LocalStorage(local_cfg).list_backups() == []


def test_delete_invalid_number(termux_tree, local_cfg, answers, capsys):
    run_backup(local_cfg)
    answers(confirm=True, prompt="9")
    ts.cmd_delete(local_cfg)
    assert "Invalid number" in capsys.readouterr().out


def test_delete_without_backups(local_cfg, capsys):
    ts.cmd_delete(local_cfg)
    assert "No backups found" in capsys.readouterr().out


def test_restore_round_trip(termux_tree, local_cfg, answers, capsys):
    backup = run_backup(local_cfg)
    (termux_tree / "home" / ".bashrc").write_text("tampered\n")
    (termux_tree / "home" / "projects" / "notes.txt").unlink()
    answers(confirm=True)
    ts.cmd_restore(local_cfg, backup_name=backup["name"])
    assert (termux_tree / "home" / ".bashrc").read_text() == "alias ll='ls -l'\n"
    assert (termux_tree / "home" / "projects" / "notes.txt").read_text() == "remember the milk\n"
    assert "Restore completed successfully" in capsys.readouterr().out


def test_restore_cancelled_leaves_files_alone(termux_tree, local_cfg, answers):
    backup = run_backup(local_cfg)
    (termux_tree / "home" / ".bashrc").write_text("tampered\n")
    answers(confirm=False)
    ts.cmd_restore(local_cfg, backup_name=backup["name"])
    assert (termux_tree / "home" / ".bashrc").read_text() == "tampered\n"


def test_restore_rejects_path_in_backup_name(termux_tree, local_cfg, answers, capsys):
    run_backup(local_cfg)
    answers(confirm=True)
    ts.cmd_restore(local_cfg, backup_name="..")
    assert "Invalid backup name" in capsys.readouterr().out


def test_restore_without_backups(local_cfg, capsys):
    ts.cmd_restore(local_cfg)
    assert "No backups found" in capsys.readouterr().out


def test_restore_refuses_unknown_manifest_keys(termux_tree, local_cfg, answers, capsys):
    backup = run_backup(local_cfg)
    manifest_path = ts.LocalStorage(local_cfg).root / backup["name"] / "manifest.json"
    data = json.loads(manifest_path.read_text())
    data["files"]["evil"] = dict(data["files"]["home"])
    manifest_path.write_text(json.dumps(data))
    answers(confirm=True)
    ts.cmd_restore(local_cfg, backup_name=backup["name"])
    assert "Refusing unknown/untrusted restore target" in capsys.readouterr().out


def test_restore_detects_checksum_mismatch(termux_tree, local_cfg, answers, capsys):
    backup = run_backup(local_cfg)
    archive = ts.LocalStorage(local_cfg).root / backup["name"] / backup["files"]["usr_etc"]["archive"]
    archive.write_bytes(b"corrupted")
    (termux_tree / "home" / ".bashrc").write_text("tampered\n")
    answers(confirm=False)
    ts.cmd_restore(local_cfg, backup_name=backup["name"])
    out = capsys.readouterr().out
    assert "Restore completed" not in out
    assert (termux_tree / "home" / ".bashrc").read_text() == "tampered\n"


def test_schedule_defaults_and_round_trip(config_home, monkeypatch):
    monkeypatch.setattr(ts, "CRON_FILE", config_home / "cron.json")
    assert ts.load_schedule() == {"enabled": False, "hour": 2, "minute": 0, "label": "auto"}
    ts.save_schedule({"enabled": True, "hour": 5, "minute": 30, "label": "nightly"})
    assert ts.load_schedule()["hour"] == 5


def test_logs_without_file(config_home, capsys):
    ts.cmd_logs()
    assert "No log file yet" in capsys.readouterr().out


def test_logs_hide_traces_unless_debug(config_home, capsys, monkeypatch):
    ts.log("INFO", "hello")
    ts.log("TRACE", "stack line")
    ts.cmd_logs()
    out = capsys.readouterr().out
    assert "hello" in out
    assert "stack line" not in out
    monkeypatch.setattr(ts, "DEBUG", True)
    ts.cmd_logs()
    assert "stack line" in capsys.readouterr().out


def test_logs_respect_line_limit(config_home, capsys):
    for index in range(10):
        ts.log("INFO", f"entry-{index}")
    ts.cmd_logs(lines=2)
    out = capsys.readouterr().out
    assert "entry-9" in out
    assert "entry-0" not in out


def test_clear_logs(config_home, answers, capsys):
    ts.log("INFO", "something")
    answers(confirm=True)
    ts.cmd_clear_logs()
    remaining = (config_home / "sync.log").read_text()
    assert "something" not in remaining
    assert "Log file cleared by user" in remaining
    assert "Log file cleared" in capsys.readouterr().out


def test_clear_logs_cancelled(config_home, answers):
    ts.log("INFO", "keep me")
    answers(confirm=False)
    ts.cmd_clear_logs()
    assert "keep me" in (config_home / "sync.log").read_text()


def test_dir_size_counts_files_and_skips_symlinks(tmp_path):
    (tmp_path / "a.bin").write_bytes(b"x" * 100)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.bin").write_bytes(b"x" * 50)
    (tmp_path / "link").symlink_to(tmp_path / "a.bin")
    assert ts.dir_size(tmp_path) == 150


def test_dir_size_missing_path(tmp_path):
    assert ts.dir_size(tmp_path / "missing") == 0


def test_export_config_redacts_secrets(config_home, tmp_path, capsys):
    ts.save_config(dict(ts.DEFAULT_CONFIG, github_token="ghp_secret", encrypt_password="hunter2"))
    out = tmp_path / "export.json"
    ts.cmd_export_config(str(out))
    data = json.loads(out.read_text())
    assert data["github_token"] == "*** REDACTED ***"
    assert data["encrypt_password"] == "*** REDACTED ***"
    assert "ghp_secret" not in out.read_text()


def test_import_config_keeps_existing_secrets(config_home, tmp_path):
    ts.save_config(dict(ts.DEFAULT_CONFIG, github_token="real-token"))
    incoming = tmp_path / "in.json"
    incoming.write_text(json.dumps({"github_token": "*** REDACTED ***", "max_backups": 9, "compression": "lzma"}))
    ts.cmd_import_config(str(incoming))
    cfg = ts.load_config()
    assert cfg["github_token"] == "real-token"
    assert cfg["max_backups"] == 9
    assert cfg["compression"] == "gz"


def test_import_config_missing_file(config_home, tmp_path):
    with pytest.raises(ts.UserError) as info:
        ts.cmd_import_config(str(tmp_path / "nope.json"))
    assert info.value.title == "File not found"


def test_import_config_invalid_json(config_home, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{oops")
    with pytest.raises(ts.UserError) as info:
        ts.cmd_import_config(str(bad))
    assert info.value.title == "Not a valid JSON file"


def test_print_backup_list_wide_and_narrow(monkeypatch, capsys):
    backups = [{"name": "b1", "date": "2026-01-01T10:00:00", "packages": ["git"], "label": "L", "files": {"home": {"size": 2048}}}]
    ts.print_backup_list(backups)
    assert "b1" in capsys.readouterr().out
    monkeypatch.setattr(ts, "is_narrow", lambda: True)
    ts.print_backup_list(backups)
    out = capsys.readouterr().out
    assert "b1" in out
    assert "2.0 KB" in out


def test_status_check_and_help_render(termux_tree, local_cfg, config_home, monkeypatch, capsys):
    monkeypatch.setattr(ts, "CRON_FILE", config_home / "cron.json")
    ts.cmd_status(local_cfg)
    ts.cmd_check(str(termux_tree / "home"))
    ts.print_help()
    assert capsys.readouterr().out
