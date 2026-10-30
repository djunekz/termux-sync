import pytest

import termux_sync as ts


@pytest.fixture(autouse=True)
def isolated_tmpdir(tmp_path, monkeypatch):
    scratch = tmp_path / "scratch-tmp"
    scratch.mkdir()
    monkeypatch.setenv("TMPDIR", str(scratch))


@pytest.fixture
def config_home(tmp_path, monkeypatch):
    monkeypatch.setattr(ts, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(ts, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(ts, "LOG_FILE", tmp_path / "sync.log")
    return tmp_path


@pytest.fixture
def termux_tree(tmp_path, monkeypatch):
    home = tmp_path / "termux" / "home"
    usr = tmp_path / "termux" / "usr"
    (home / "projects").mkdir(parents=True)
    (home / ".bashrc").write_text("alias ll='ls -l'\n")
    (home / "projects" / "notes.txt").write_text("remember the milk\n")
    (home / ".cache").mkdir()
    (home / ".cache" / "junk.bin").write_bytes(b"x" * 64)
    (usr / "etc").mkdir(parents=True)
    (usr / "etc" / "motd").write_text("welcome\n")
    (tmp_path / "tmp").mkdir()
    monkeypatch.setenv("TMPDIR", str(tmp_path / "tmp"))
    monkeypatch.setattr(ts, "TERMUX_FILES", home)
    monkeypatch.setattr(ts, "TERMUX_HOME", usr)
    monkeypatch.setattr(
        ts,
        "BACKUP_ITEMS",
        [
            ("packages", "Installed package list", None),
            ("home", "Home directory (~)", home),
            ("usr_etc", "Termux config (/usr/etc)", usr / "etc"),
            ("usr_lib", "Shared libraries (/usr/lib)", usr / "lib"),
        ],
    )
    monkeypatch.setattr(ts, "get_installed_packages", lambda: ["git", "python"])
    return tmp_path / "termux"


@pytest.fixture
def local_cfg(config_home, tmp_path):
    cfg = dict(ts.DEFAULT_CONFIG)
    cfg["local_path"] = str(tmp_path / "backups")
    return cfg


@pytest.fixture
def answers(monkeypatch):
    def configure(confirm=True, prompt=""):
        monkeypatch.setattr(ts.Confirm, "ask", staticmethod(lambda *a, **k: confirm))
        monkeypatch.setattr(ts.Prompt, "ask", staticmethod(lambda *a, **k: prompt))

    return configure
