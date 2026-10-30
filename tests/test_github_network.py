import errno
import io
import json
import urllib.error
import urllib.parse

import pytest

import termux_sync as ts


class FakeResponse:
    def __init__(self, body=b"", status=200):
        self._buffer = io.BytesIO(body)
        self.status = status

    def read(self, size=-1):
        return self._buffer.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


UPLOAD_HOST = "uploads.github.com"


def is_upload_url(url):
    return urllib.parse.urlparse(url).hostname == UPLOAD_HOST


def http_error(code, body=b"{}"):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body))


class Router:
    def __init__(self):
        self.routes = []
        self.requests = []

    def add(self, method, fragment, *outcomes):
        self.routes.append([method, fragment, list(outcomes)])

    def __call__(self, request, timeout=None):
        method = request.get_method()
        url = request.full_url
        self.requests.append((method, url, request.data))
        for route in self.routes:
            if route[0] == method and route[1] in url:
                outcomes = route[2]
                outcome = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
                if isinstance(outcome, BaseException):
                    raise outcome
                if isinstance(outcome, FakeResponse):
                    return FakeResponse(outcome._buffer.getvalue(), outcome.status)
                return FakeResponse(json.dumps(outcome).encode())
        raise AssertionError(f"unrouted request: {method} {url}")


@pytest.fixture
def router(monkeypatch):
    instance = Router()
    monkeypatch.setattr("urllib.request.urlopen", instance)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    return instance


@pytest.fixture
def github(local_cfg):
    return ts.GitHubStorage(dict(local_cfg, storage="github", github_token="tok", github_repo="a/b"))


def test_api_returns_parsed_json(github, router):
    router.add("GET", "/repos/a/b", {"ok": True})
    assert github._api("GET", "/repos/a/b") == {"ok": True}


def test_api_sends_json_body(github, router):
    router.add("POST", "/releases", {"id": 1})
    github._api("POST", "/repos/a/b/releases", json={"tag_name": "t"})
    assert json.loads(router.requests[0][2]) == {"tag_name": "t"}


def test_api_handles_empty_and_no_content(github, router):
    router.add("DELETE", "/x", FakeResponse(b"", 204))
    router.add("GET", "/y", FakeResponse(b"", 200))
    assert github._api("DELETE", "/x") == {}
    assert github._api("GET", "/y") == {}


def test_api_translates_http_errors(github, router):
    router.add("GET", "/repos/a/b", http_error(401, b'{"message": "Bad credentials"}'))
    with pytest.raises(ts.UserError) as info:
        github._api("GET", "/repos/a/b")
    assert info.value.title == "Invalid GitHub token"


def test_push_file_creates_and_updates(github, router, tmp_path):
    local = tmp_path / "file.txt"
    local.write_text("hello")
    router.add("GET", "/contents/f.txt", http_error(404), {"sha": "abc"})
    router.add("PUT", "/contents/f.txt", {})
    github._push_file(local, "f.txt", "add file")
    github._push_file(local, "f.txt", "update file")
    puts = [json.loads(data) for method, _, data in router.requests if method == "PUT"]
    assert "sha" not in puts[0]
    assert puts[1]["sha"] == "abc"
    assert puts[0]["message"] == "add file"


def test_create_release_posts_expected_payload(github, router):
    router.add("POST", "/releases", {"id": 3})
    github._create_release("termux_backup_1")
    payload = json.loads(router.requests[0][2])
    assert payload["tag_name"] == "termux_backup_1"
    assert payload["draft"] is False


def test_upload_one_asset_success(github, router, tmp_path):
    asset = tmp_path / "home.tar.gz"
    asset.write_bytes(b"payload")
    router.add("POST", "uploads.github.com", {"id": 11})
    with ts.make_progress() as progress:
        task = progress.add_task("t", total=1)
        assert github._upload_one_asset(5, asset, task, progress) == {"id": 11}
    assert router.requests[0][2] == b"payload"
    assert "name=home.tar.gz" in router.requests[0][1]


def test_upload_one_asset_treats_existing_asset_as_done(github, router, tmp_path):
    asset = tmp_path / "home.tar.gz"
    asset.write_bytes(b"payload")
    router.add("POST", "uploads.github.com", http_error(422, b'{"message": "already_exists"}'))
    with ts.make_progress() as progress:
        task = progress.add_task("t", total=1)
        assert github._upload_one_asset(5, asset, task, progress) == {}


def test_upload_one_asset_retries_temporary_failures(github, router, tmp_path):
    asset = tmp_path / "home.tar.gz"
    asset.write_bytes(b"payload")
    router.add("POST", "uploads.github.com", http_error(503), http_error(429), {"id": 2})
    with ts.make_progress() as progress:
        task = progress.add_task("t", total=1)
        assert github._upload_one_asset(5, asset, task, progress) == {"id": 2}
    assert len(router.requests) == 3


def test_upload_one_asset_stops_on_permanent_failure(github, router, tmp_path):
    asset = tmp_path / "home.tar.gz"
    asset.write_bytes(b"payload")
    router.add("POST", "uploads.github.com", http_error(401))
    with ts.make_progress() as progress:
        task = progress.add_task("t", total=1)
        with pytest.raises(ts.UserError):
            github._upload_one_asset(5, asset, task, progress)
    assert len(router.requests) == 1


def test_upload_one_asset_gives_up_after_network_errors(github, router, tmp_path):
    asset = tmp_path / "home.tar.gz"
    asset.write_bytes(b"payload")
    router.add("POST", "uploads.github.com", urllib.error.URLError("offline"))
    with ts.make_progress() as progress:
        task = progress.add_task("t", total=1)
        with pytest.raises(RuntimeError, match="after 8 attempts"):
            github._upload_one_asset(5, asset, task, progress)
    assert len(router.requests) == github.MAX_RETRIES


def test_upload_one_asset_raises_when_disk_is_full(github, router, tmp_path):
    asset = tmp_path / "home.tar.gz"
    asset.write_bytes(b"payload")
    router.add("POST", "uploads.github.com", OSError(errno.ENOSPC, "No space left"))
    with ts.make_progress() as progress:
        task = progress.add_task("t", total=1)
        with pytest.raises(OSError):
            github._upload_one_asset(5, asset, task, progress)
    assert len(router.requests) == 1


def test_upload_creates_release_and_skips_existing_assets(github, router, tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "manifest.json").write_text("{}")
    (source / "home.tar.gz").write_bytes(b"data")
    router.add("GET", "/releases/tags/b1", http_error(404))
    router.add("POST", "/repos/a/b/releases", {"id": 9, "html_url": "https://github.com/a/b/releases/b1"})
    router.add("POST", "uploads.github.com", {"id": 1})
    with ts.make_progress() as progress:
        url = github.upload(source, "b1", progress)
    assert url == "https://github.com/a/b/releases/b1"
    uploads = [req for req in router.requests if is_upload_url(req[1])]
    assert len(uploads) == 2


def test_upload_reuses_existing_release_and_assets(github, router, tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    (source / "home.tar.gz").write_bytes(b"data")
    (source / "subdir").mkdir()
    release = {"id": 9, "html_url": "u", "assets": [{"name": "home.tar.gz"}]}
    router.add("GET", "/releases/tags/b1", release)
    with ts.make_progress() as progress:
        assert github.upload(source, "b1", progress) == "u"
    assert not [req for req in router.requests if is_upload_url(req[1])]


def test_list_backups_reads_manifest_asset(github, router):
    releases = [
        {
            "tag_name": "termux_backup_1",
            "created_at": "2026-01-01",
            "assets": [{"id": 4, "name": "manifest.json"}],
        },
        {
            "tag_name": "termux_backup_2",
            "created_at": "2026-02-01",
            "assets": [{"id": 5, "name": "manifest.json"}],
        },
    ]
    router.add("GET", "/releases?per_page=100", releases)
    router.add("GET", "/releases/assets/4", {"name": "termux_backup_1", "label": "from manifest"})
    router.add("GET", "/releases/assets/5", http_error(500))
    backups = github.list_backups()
    assert backups[0]["label"] == "from manifest"
    assert backups[1]["name"] == "termux_backup_2"
    assert backups[1]["label"] == ""


def test_download_joins_parts_and_downloads_plain_files(github, router, tmp_path):
    release = {
        "assets": [
            {"id": 1, "name": "home.tar.gz.part0000", "size": 3},
            {"id": 2, "name": "home.tar.gz.part0001", "size": 3},
            {"id": 3, "name": "manifest.json", "size": 2},
        ]
    }
    router.add("GET", "/releases/tags/b1", release)
    router.add("GET", "/releases/assets/1", FakeResponse(b"abc"))
    router.add("GET", "/releases/assets/2", FakeResponse(b"def"))
    router.add("GET", "/releases/assets/3", FakeResponse(b"{}"))
    destination = tmp_path / "dl"
    with ts.make_progress() as progress:
        github.download("b1", destination, progress)
    assert (destination / "home.tar.gz").read_bytes() == b"abcdef"
    assert (destination / "manifest.json").read_bytes() == b"{}"
    assert not list(destination.glob("*.part*"))


def test_download_unknown_release(github, router, tmp_path):
    router.add("GET", "/releases/tags/ghost", http_error(404))
    with ts.make_progress() as progress, pytest.raises(RuntimeError, match="No GitHub Release"):
        github.download("ghost", tmp_path / "dl", progress)


def test_download_retries_then_fails(github, router, tmp_path):
    router.add("GET", "/releases/tags/b1", {"assets": [{"id": 1, "name": "manifest.json", "size": 2}]})
    router.add("GET", "/releases/assets/1", urllib.error.URLError("offline"))
    with ts.make_progress() as progress, pytest.raises(RuntimeError, match="after 8 attempts"):
        github.download("b1", tmp_path / "dl", progress)


def test_download_stops_when_disk_is_full(github, router, tmp_path):
    router.add("GET", "/releases/tags/b1", {"assets": [{"id": 1, "name": "manifest.json", "size": 2}]})
    router.add("GET", "/releases/assets/1", OSError(errno.ENOSPC, "No space left"))
    with ts.make_progress() as progress, pytest.raises(OSError):
        github.download("b1", tmp_path / "dl", progress)


def github_router(router, upload=None):
    router.add("POST", "uploads.github.com", upload if upload is not None else {"id": 1})
    router.add("GET", "/repos/a/b/commits", {})
    router.add("GET", "/repos/a/b/releases/tags/", http_error(404), {"id": 7, "html_url": "https://rel", "assets": []})
    router.add("GET", "/repos/a/b/releases?per_page=100", [])
    router.add("GET", "/repos/a/b", {})
    router.add("POST", "/repos/a/b/releases", {"id": 7, "html_url": "https://rel"})
    router.add("DELETE", "/repos/a/b", {})


def test_streaming_backup_to_github(termux_tree, local_cfg, router, capsys):
    github_router(router)
    config = dict(local_cfg, storage="github", github_token="tok", github_repo="a/b")
    ts.cmd_backup(config)
    out = capsys.readouterr().out
    assert "Streaming upload" in out
    assert "Backup completed successfully" in out
    names = [url.split("name=")[1] for method, url, _ in router.requests if is_upload_url(url)]
    assert any(name.startswith("home.tar") for name in names)
    assert "manifest.json" in names


def test_streaming_backup_aborts_and_removes_release_on_failure(termux_tree, local_cfg, router):
    github_router(router, upload=http_error(401))
    config = dict(local_cfg, storage="github", github_token="tok", github_repo="a/b")
    with pytest.raises(ts.StreamAbort) as info:
        ts.cmd_backup(config)
    assert isinstance(info.value.original, ts.UserError)
    assert info.value.original.title == "Invalid GitHub token"
    assert any(method == "DELETE" for method, _, _ in router.requests)


def test_backup_stops_when_repository_check_fails(termux_tree, local_cfg, router):
    router.add("GET", "/repos/a/b", http_error(404))
    config = dict(local_cfg, storage="github", github_token="tok", github_repo="a/b")
    with pytest.raises(ts.UserError) as info:
        ts.cmd_backup(config)
    assert info.value.title == "GitHub repository not found"
