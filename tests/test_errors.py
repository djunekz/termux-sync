import errno
import socket
import subprocess
import tarfile
import urllib.error

import pytest

import termux_sync as ts


def http_error(code, reason="reason"):
    return urllib.error.HTTPError("https://api.github.com", code, reason, {}, None)


def test_user_error_passes_fields_through():
    exc = ts.UserError("bad input", hint="try again", title="Oops")
    assert ts._explain(exc) == ("Oops", "bad input", "try again")


def test_user_error_default_title():
    assert ts.UserError("x").title == "Cannot continue"


def test_stream_abort_unwraps_original():
    original = ts.UserError("inner", title="Inner")
    assert ts._explain(ts.StreamAbort(original))[0] == "Inner"


def test_eof_error():
    title, _, hint = ts._explain(EOFError())
    assert title == "Input was closed"
    assert "terminal" in hint


def test_file_not_found_shows_filename():
    exc = FileNotFoundError(errno.ENOENT, "missing", "/tmp/nope")
    title, message, _ = ts._explain(exc)
    assert title == "File or folder not found"
    assert message == "/tmp/nope"


def test_permission_error():
    exc = PermissionError(errno.EACCES, "denied", "/root/x")
    title, message, hint = ts._explain(exc)
    assert title == "Permission denied"
    assert message == "/root/x"
    assert "termux-setup-storage" in hint


def test_out_of_space():
    title, _, hint = ts._explain(OSError(errno.ENOSPC, "No space left on device"))
    assert title == "Device is out of space"
    assert "clear-cache" in hint


@pytest.mark.parametrize(
    ("code", "fragment"),
    [(401, "invalid, expired"), (403, "invalid, expired"), (404, "not found"), (500, "token and repository")],
)
def test_http_errors(code, fragment):
    title, _, hint = ts._explain(http_error(code))
    assert title == f"GitHub returned HTTP {code}"
    assert fragment in hint


def test_url_error_is_network_problem():
    title, message, _ = ts._explain(urllib.error.URLError("dns failure"))
    assert title == "Network problem"
    assert message == "dns failure"


@pytest.mark.parametrize("exc", [socket.timeout("slow"), TimeoutError("slow"), ConnectionResetError("reset")])
def test_connection_errors(exc):
    assert ts._explain(exc)[0] == "Network problem"


def test_called_process_error_joins_command():
    exc = subprocess.CalledProcessError(2, ["tar", "-czf", "out.tgz"])
    title, message, _ = ts._explain(exc)
    assert title == "A command failed"
    assert message == "tar -czf out.tgz\nexit code 2"


def test_called_process_error_string_command():
    exc = subprocess.CalledProcessError(1, "ls /nope")
    assert ts._explain(exc)[1].startswith("ls /nope")


@pytest.mark.parametrize("exc", [RuntimeError("boom"), ValueError("boom")])
def test_runtime_and_value_errors(exc):
    assert ts._explain(exc) == ("Operation failed", "boom", "See the message above. Details are saved in the log.")


def test_unknown_exception_mentions_issue_tracker():
    title, message, hint = ts._explain(KeyError("k"))
    assert title == "Unexpected error"
    assert message.startswith("KeyError")
    assert ts.ISSUES_URL in hint


def test_origin_returns_empty_without_traceback():
    assert ts._origin(ValueError("no traceback")) == ""


def test_origin_points_at_module_frame(tmp_path):
    member = tarfile.TarInfo("/abs")
    try:
        ts._safe_extract_member(member, tmp_path)
    except ValueError as exc:
        assert "_safe_extract_member()" in ts._origin(exc)
    else:
        pytest.fail("expected ValueError")


def test_handle_crash_writes_log(config_home, capsys):
    try:
        raise ts.UserError("visible message", title="Visible title")
    except ts.UserError as exc:
        ts.handle_crash(exc)
    out = capsys.readouterr().out
    assert "Visible title" in out
    assert "visible message" in out
    log_text = (config_home / "sync.log").read_text()
    assert "[ERROR] UserError: visible message" in log_text
    assert "[TRACE]" in log_text


def test_print_error_escapes_markup(capsys):
    ts.print_error("Title", "[bold]not markup[/bold]")
    assert "[bold]not markup[/bold]" in capsys.readouterr().out
