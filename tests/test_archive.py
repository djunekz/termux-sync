import hashlib
import tarfile

import pytest

import termux_sync as ts


def make_member(name, kind=tarfile.REGTYPE, linkname=""):
    member = tarfile.TarInfo(name)
    member.type = kind
    member.linkname = linkname
    return member


def test_sha256_matches_hashlib(tmp_path):
    data = b"termux-sync" * 1000
    path = tmp_path / "blob.bin"
    path.write_bytes(data)
    assert ts.sha256(path) == hashlib.sha256(data).hexdigest()


def test_sha256_small_chunks(tmp_path):
    path = tmp_path / "blob.bin"
    path.write_bytes(b"abcdefghij")
    assert ts.sha256(path, chunk=3) == hashlib.sha256(b"abcdefghij").hexdigest()


def test_sha256_empty_file(tmp_path):
    path = tmp_path / "empty"
    path.write_bytes(b"")
    assert ts.sha256(path) == hashlib.sha256(b"").hexdigest()


def test_safe_member_accepts_regular_file(tmp_path):
    ts._safe_extract_member(make_member("home/user/.bashrc"), tmp_path)


def test_safe_member_accepts_internal_symlink(tmp_path):
    member = make_member("home/link", tarfile.SYMTYPE, "target.txt")
    ts._safe_extract_member(member, tmp_path)


def test_safe_member_rejects_absolute_path(tmp_path):
    with pytest.raises(ValueError, match="absolute path"):
        ts._safe_extract_member(make_member("/etc/passwd"), tmp_path)


def test_safe_member_rejects_traversal(tmp_path):
    with pytest.raises(ValueError, match="traversal"):
        ts._safe_extract_member(make_member("home/../../evil"), tmp_path)


def test_safe_member_rejects_absolute_symlink(tmp_path):
    member = make_member("home/link", tarfile.SYMTYPE, "/etc/shadow")
    with pytest.raises(ValueError, match="absolute link"):
        ts._safe_extract_member(member, tmp_path)


def test_safe_member_rejects_escaping_symlink(tmp_path):
    member = make_member("home/link", tarfile.SYMTYPE, "../../outside")
    with pytest.raises(ValueError, match="escapes destination"):
        ts._safe_extract_member(member, tmp_path)


def test_safe_member_rejects_escaping_hardlink(tmp_path):
    member = make_member("home/hard", tarfile.LNKTYPE, "../../outside")
    with pytest.raises(ValueError, match="escapes destination"):
        ts._safe_extract_member(member, tmp_path)


@pytest.mark.parametrize("kind", [tarfile.CHRTYPE, tarfile.BLKTYPE, tarfile.FIFOTYPE])
def test_safe_member_rejects_special_files(tmp_path, kind):
    with pytest.raises(ValueError, match="device/fifo"):
        ts._safe_extract_member(make_member("dev/node", kind), tmp_path)
