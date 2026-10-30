import json

import pytest

import termux_sync as ts


def test_load_config_defaults_when_file_missing(config_home):
    cfg = ts.load_config()
    assert cfg == ts.DEFAULT_CONFIG
    assert cfg is not ts.DEFAULT_CONFIG


def test_load_config_fills_missing_keys(config_home):
    (config_home / "config.json").write_text(json.dumps({"storage": "github", "max_backups": 9}))
    cfg = ts.load_config()
    assert cfg["storage"] == "github"
    assert cfg["max_backups"] == 9
    assert cfg["compression"] == ts.DEFAULT_CONFIG["compression"]
    assert cfg["exclude_patterns"] == ts.DEFAULT_CONFIG["exclude_patterns"]


def test_load_config_invalid_json_raises_user_error(config_home):
    (config_home / "config.json").write_text("{not json")
    with pytest.raises(ts.UserError) as info:
        ts.load_config()
    assert info.value.title == "Config file is corrupted"
    assert "line 1" in info.value.message


def test_save_then_load_round_trip(config_home):
    cfg = dict(ts.DEFAULT_CONFIG, storage="gdrive", gdrive_folder_id="abc123")
    ts.save_config(cfg)
    assert ts.load_config() == cfg


def test_save_config_creates_directory(tmp_path, monkeypatch):
    target = tmp_path / "nested" / "dir"
    monkeypatch.setattr(ts, "CONFIG_DIR", target)
    monkeypatch.setattr(ts, "CONFIG_FILE", target / "config.json")
    ts.save_config({"storage": "local"})
    assert json.loads((target / "config.json").read_text()) == {"storage": "local"}


def test_log_appends_formatted_lines(config_home):
    ts.log("info", "first")
    ts.log("error", "second")
    lines = (config_home / "sync.log").read_text().splitlines()
    assert len(lines) == 2
    assert lines[0].endswith("[INFO] first")
    assert lines[1].endswith("[ERROR] second")


def test_manifest_round_trip(tmp_path):
    meta = {"name": "backup-1", "files": {"home": {"size": 10}}}
    path = ts.write_manifest(tmp_path, meta)
    assert path == tmp_path / "manifest.json"
    assert ts.read_manifest(tmp_path) == meta


def test_read_manifest_missing(tmp_path):
    assert ts.read_manifest(tmp_path) is None


def test_default_config_values_are_sane():
    assert ts.DEFAULT_CONFIG["storage"] == "local"
    assert ts.DEFAULT_CONFIG["max_backups"] > 0
    assert ts.DEFAULT_CONFIG["encrypt"] is False
    assert ts.DEFAULT_CONFIG["github_token"] == ""
