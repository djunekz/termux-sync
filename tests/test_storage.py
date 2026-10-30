import pytest

import termux_sync as ts


def populate(root, names):
    for index, name in enumerate(names):
        backup = root / name
        backup.mkdir(parents=True)
        ts.write_manifest(backup, {"name": name, "date": f"2026-01-0{index + 1}T00:00:00"})
        (backup / "home.tar.gz").write_bytes(b"data")


def make_progress():
    return ts.make_progress()


def test_get_storage_selects_backend(local_cfg):
    assert isinstance(ts.get_storage(local_cfg), ts.LocalStorage)
    assert isinstance(ts.get_storage(dict(local_cfg, storage="github", github_token="t", github_repo="a/b")), ts.GitHubStorage)


def test_get_storage_gdrive_requires_rclone(local_cfg, monkeypatch):
    monkeypatch.setattr(ts.shutil, "which", lambda name: None)
    with pytest.raises(ts.UserError) as info:
        ts.get_storage(dict(local_cfg, storage="gdrive"))
    assert info.value.title == "rclone not found"


def test_github_storage_requires_credentials(local_cfg):
    with pytest.raises(ts.UserError) as info:
        ts.GitHubStorage(dict(local_cfg, storage="github"))
    assert info.value.title == "GitHub is not configured"


def test_local_list_backups_empty_when_missing(local_cfg):
    assert ts.LocalStorage(local_cfg).list_backups() == []


def test_local_list_backups_newest_first_and_skips_invalid(local_cfg, tmp_path):
    root = tmp_path / "backups"
    populate(root, ["b1", "b2"])
    (root / "no-manifest").mkdir()
    (root / "stray.txt").write_text("x")
    names = [b["name"] for b in ts.LocalStorage(local_cfg).list_backups()]
    assert names == ["b2", "b1"]


def test_local_upload_and_download_round_trip(local_cfg, tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "a.txt").write_text("alpha")
    storage = ts.LocalStorage(local_cfg)
    with make_progress() as progress:
        location = storage.upload(source, "backup-1", progress)
        assert location.endswith("backup-1")
        target = tmp_path / "restored"
        storage.download("backup-1", target, progress)
    assert (target / "a.txt").read_text() == "alpha"


def test_local_download_missing_backup(local_cfg, tmp_path):
    with make_progress() as progress, pytest.raises(FileNotFoundError):
        ts.LocalStorage(local_cfg).download("ghost", tmp_path / "out", progress)


def test_local_delete_backup(local_cfg, tmp_path):
    populate(tmp_path / "backups", ["b1"])
    storage = ts.LocalStorage(local_cfg)
    storage.delete_backup("b1")
    assert storage.list_backups() == []


def test_local_delete_missing_backup(local_cfg):
    with pytest.raises(FileNotFoundError):
        ts.LocalStorage(local_cfg).delete_backup("ghost")


def test_local_delete_old_keeps_newest(local_cfg, tmp_path):
    import os

    root = tmp_path / "backups"
    populate(root, ["b1", "b2", "b3"])
    for index, name in enumerate(["b1", "b2", "b3"]):
        os.utime(root / name, (1000 + index, 1000 + index))
    ts.LocalStorage(local_cfg).delete_old(2)
    assert sorted(p.name for p in root.iterdir()) == ["b2", "b3"]


def test_local_delete_old_without_root(local_cfg):
    ts.LocalStorage(local_cfg).delete_old(1)


@pytest.mark.parametrize(
    ("code", "body", "title"),
    [
        (409, '{"message": "Git Repository is empty."}', "GitHub repository is empty"),
        (401, "{}", "Invalid GitHub token"),
        (403, '{"message": "API rate limit exceeded"}', "GitHub rate limit reached"),
        (403, '{"message": "Resource not accessible"}', "GitHub denied access"),
        (404, "{}", "GitHub repository not found"),
    ],
)
def test_github_http_error_mapping(local_cfg, code, body, title):
    storage = ts.GitHubStorage(dict(local_cfg, github_token="t", github_repo="a/b"))
    error = storage._http_error(code, body)
    assert isinstance(error, ts.UserError)
    assert error.title == title


def test_github_http_error_generic(local_cfg):
    storage = ts.GitHubStorage(dict(local_cfg, github_token="t", github_repo="a/b"))
    error = storage._http_error(500, "not json at all")
    assert isinstance(error, RuntimeError)
    assert "500" in str(error)


def test_github_headers_and_urls(local_cfg):
    storage = ts.GitHubStorage(dict(local_cfg, github_token="tok", github_repo="a/b"))
    assert storage._headers()["Authorization"] == "token tok"
    assert storage._asset_headers()["Accept"] == "application/octet-stream"
    assert storage._asset_url(7) == "https://api.github.com/repos/a/b/releases/assets/7"


def test_github_split_file_small_and_large(local_cfg, tmp_path):
    storage = ts.GitHubStorage(dict(local_cfg, github_token="t", github_repo="a/b"))
    storage.CHUNK_SIZE = 10
    small = tmp_path / "small.bin"
    small.write_bytes(b"12345")
    assert storage._split_file(small, tmp_path) == [small]
    large = tmp_path / "large.bin"
    large.write_bytes(b"x" * 25)
    parts = storage._split_file(large, tmp_path)
    assert [p.name for p in parts] == ["large.bin.part0000", "large.bin.part0001", "large.bin.part0002"]
    assert b"".join(p.read_bytes() for p in parts) == large.read_bytes()


class FakeStorage:
    CHUNK_SIZE = 10

    def __init__(self):
        self.uploaded = []

    def _upload_one_asset(self, release_id, path, task, progress):
        self.uploaded.append((path.name, path.read_bytes()))


def test_part_writer_streams_parts_and_cleans_up(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    storage = FakeStorage()
    with make_progress() as progress:
        writer = ts._PartWriter(storage, 1, "archive.tar.gz", work, progress)
        assert writer.writable() is True
        written = writer.write(b"a" * 25)
        assert written == 25
        writer.finish()
    assert [name for name, _ in storage.uploaded] == [
        "archive.tar.gz.part0000",
        "archive.tar.gz.part0001",
        "archive.tar.gz.part0002",
    ]
    assert b"".join(data for _, data in storage.uploaded) == b"a" * 25
    assert writer.total == 25
    assert list(work.iterdir()) == []


def test_part_writer_small_archive_is_single_plain_file(tmp_path):
    storage = FakeStorage()
    with make_progress() as progress:
        writer = ts._PartWriter(storage, 1, "tiny.tar.gz", tmp_path, progress)
        writer.write(b"abc")
        writer.finish()
    assert storage.uploaded == [("tiny.tar.gz", b"abc")]


def test_part_writer_abort_removes_partial_file(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    storage = FakeStorage()
    with make_progress() as progress:
        writer = ts._PartWriter(storage, 1, "x.tar.gz", work, progress)
        writer.write(b"abc")
        writer.abort()
    assert list(work.iterdir()) == []


def test_part_writer_wraps_upload_failure(tmp_path):
    class Failing(FakeStorage):
        def _upload_one_asset(self, *args):
            raise RuntimeError("network down")

    with make_progress() as progress:
        writer = ts._PartWriter(Failing(), 1, "x.tar.gz", tmp_path, progress)
        writer.write(b"abc")
        with pytest.raises(ts.StreamAbort) as info:
            writer.finish()
    assert str(info.value.original) == "network down"


class FakeApi:
    def __init__(self, responses=None, failing=()):
        self.calls = []
        self.responses = responses or {}
        self.failing = failing

    def __call__(self, method, endpoint, **kwargs):
        self.calls.append((method, endpoint, kwargs))
        if (method, endpoint) in self.failing:
            raise RuntimeError("api failure")
        return self.responses.get((method, endpoint), {})


@pytest.fixture
def github(local_cfg):
    return ts.GitHubStorage(dict(local_cfg, github_token="tok", github_repo="a/b", github_branch="main"))


def test_github_preflight_calls_repo_and_commits(github, monkeypatch):
    api = FakeApi()
    monkeypatch.setattr(github, "_api", api)
    github.preflight()
    assert [call[1] for call in api.calls] == ["/repos/a/b", "/repos/a/b/commits?per_page=1"]


def test_github_get_release_by_tag_returns_none_on_error(github, monkeypatch):
    monkeypatch.setattr(github, "_api", FakeApi(failing={("GET", "/repos/a/b/releases/tags/missing")}))
    assert github._get_release_by_tag("missing") is None


def test_github_list_backups_reads_names_and_skips_other_releases(github, monkeypatch):
    releases = [
        {"tag_name": "termux_backup_1", "created_at": "2026-01-01T00:00:00Z", "assets": []},
        {"tag_name": "v1.0.0", "assets": []},
    ]
    monkeypatch.setattr(github, "_api", FakeApi({("GET", "/repos/a/b/releases?per_page=100"): releases}))
    backups = github.list_backups()
    assert [b["name"] for b in backups] == ["termux_backup_1"]
    assert backups[0]["label"] == ""


def test_github_list_releases_returns_empty_on_failure(github, monkeypatch):
    monkeypatch.setattr(github, "_api", FakeApi(failing={("GET", "/repos/a/b/releases?per_page=100")}))
    assert github._list_releases() == []


def test_github_delete_old_removes_release_and_tag(github, monkeypatch):
    releases = [
        {"id": 3, "tag_name": "termux_backup_3", "created_at": "2026-03"},
        {"id": 2, "tag_name": "termux_backup_2", "created_at": "2026-02"},
        {"id": 1, "tag_name": "termux_backup_1", "created_at": "2026-01"},
    ]
    api = FakeApi({("GET", "/repos/a/b/releases?per_page=100"): releases})
    monkeypatch.setattr(github, "_api", api)
    github.delete_old(2)
    deleted = [call[1] for call in api.calls if call[0] == "DELETE"]
    assert deleted == ["/repos/a/b/releases/1", "/repos/a/b/git/refs/tags/termux_backup_1"]


def test_github_delete_backup_missing(github, monkeypatch):
    monkeypatch.setattr(github, "_api", FakeApi(failing={("GET", "/repos/a/b/releases/tags/ghost")}))
    with pytest.raises(FileNotFoundError):
        github.delete_backup("ghost")


def test_github_delete_backup_wraps_failures(github, monkeypatch):
    api = FakeApi(
        {("GET", "/repos/a/b/releases/tags/b1"): {"id": 9}},
        failing={("DELETE", "/repos/a/b/releases/9")},
    )
    monkeypatch.setattr(github, "_api", api)
    with pytest.raises(RuntimeError, match="Failed to delete backup from GitHub"):
        github.delete_backup("b1")


def test_github_begin_stream_requires_free_space(github, tmp_path, monkeypatch):
    monkeypatch.setattr(ts.shutil, "disk_usage", lambda path: type("U", (), {"free": 1})())
    with pytest.raises(ts.UserError) as info:
        github.begin_stream("b1", tmp_path / "work")
    assert info.value.title == "Not enough free space"


def test_github_begin_stream_reuses_existing_release(github, tmp_path, monkeypatch):
    monkeypatch.setattr(github, "_api", FakeApi({("GET", "/repos/a/b/releases/tags/b1"): {"id": 5}}))
    github.begin_stream("b1", tmp_path / "work")
    with ts.make_progress() as progress:
        writer = github.stream_sink("home.tar.gz", progress)
    assert writer.release_id == 5


def test_github_abort_stream_swallows_errors(github, monkeypatch):
    monkeypatch.setattr(github, "_api", FakeApi(failing={("GET", "/repos/a/b/releases/tags/b1")}))
    github.abort_stream("b1")
