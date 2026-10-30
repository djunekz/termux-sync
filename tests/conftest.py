import pytest

import termux_sync as ts


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ts, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(ts, "LOG_FILE", tmp_path / "sync.log")
    return tmp_path
