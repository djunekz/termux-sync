import pytest

import termux_sync as ts


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, "0.0 B"),
        (1, "1.0 B"),
        (1023, "1023.0 B"),
        (1024, "1.0 KB"),
        (1536, "1.5 KB"),
        (1024**2, "1.0 MB"),
        (5 * 1024**3, "5.0 GB"),
        (2 * 1024**4, "2.0 TB"),
    ],
)
def test_human_size(size, expected):
    assert ts.human_size(size) == expected


def test_human_size_accepts_float_input():
    assert ts.human_size(2048.9) == "2.0 KB"


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0:00:00"),
        (59, "0:00:59"),
        (61, "0:01:01"),
        (3600, "1:00:00"),
        (3725.8, "1:02:05"),
    ],
)
def test_fmt_elapsed(seconds, expected):
    assert ts.fmt_elapsed(seconds) == expected


def test_backup_date_trims_iso_timestamp():
    assert ts._backup_date({"date": "2026-10-30T10:41:55.123"}) == "2026-10-30 10:41"


def test_backup_date_missing():
    assert ts._backup_date({}) == "—"


def test_backup_label_hidden_when_equal_to_name():
    assert ts._backup_label({"name": "a", "label": "a"}) == ""


def test_backup_label_returned_when_custom():
    assert ts._backup_label({"name": "a", "label": "before-reset"}) == "before-reset"


def test_backup_label_handles_none():
    assert ts._backup_label({"name": "a", "label": None}) == ""


def test_backup_size_sums_files():
    backup = {"files": {"home": {"size": 100}, "usr_etc": {"size": 50}, "packages": {}}}
    assert ts._backup_size(backup) == 150


def test_backup_size_without_files():
    assert ts._backup_size({"files": None}) == 0
    assert ts._backup_size({}) == 0


def test_short_path_prefix(monkeypatch):
    monkeypatch.setenv("PREFIX", "/opt/termux/usr")
    assert ts.short_path("/opt/termux/usr/bin/tar") == "$PREFIX/bin/tar"
    assert ts.short_path("/opt/termux/usr") == "$PREFIX"


def test_short_path_home(monkeypatch, tmp_path):
    monkeypatch.setenv("PREFIX", "/opt/termux/usr")
    monkeypatch.setattr(ts.Path, "home", classmethod(lambda cls: tmp_path))
    assert ts.short_path(tmp_path / ".config" / "app") == "~/.config/app"


def test_short_path_unrelated(monkeypatch):
    monkeypatch.setenv("PREFIX", "/opt/termux/usr")
    assert ts.short_path("/etc/hosts") == "/etc/hosts"


@pytest.mark.parametrize(
    ("part", "total", "color"),
    [(10, 100, "green"), (60, 100, "yellow"), (90, 100, "red")],
)
def test_pct_bar_color_thresholds(part, total, color):
    assert ts._pct_bar(part, total).startswith(f"[{color}]")


def test_pct_bar_zero_total():
    bar = ts._pct_bar(5, 0, width=10)
    assert "░" * 10 in bar
    assert "0.0%" in bar


def test_pct_bar_width():
    bar = ts._pct_bar(50, 100, width=10)
    assert bar.count("█") == 5
    assert bar.count("░") == 5
