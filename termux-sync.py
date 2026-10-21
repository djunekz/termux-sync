#!/usr/bin/env python3
"""
OPENSOURCE

termux-sync — Termux Backup & Restore Tool
==========================================
Backup and restore your entire Termux environment across devices.
Supports Local, Google Drive, and GitHub (private repo) storage.
"""

import os
import re
import sys
import json
import errno
import difflib
import traceback
import time
import shutil
import hashlib
import tarfile
import argparse
import datetime
import threading
import subprocess
from pathlib import Path
from typing import Optional

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.progress import (
        Progress, SpinnerColumn, BarColumn,
        TextColumn, TimeElapsedColumn, FileSizeColumn,
        TransferSpeedColumn, TaskProgressColumn,
    )
    from rich.table import Table, Column
    from rich.prompt import Prompt, Confirm
    from rich.text import Text
    from rich import box
    from rich.live import Live
    from rich.columns import Columns
    from rich.rule import Rule
    from rich.syntax import Syntax
    from rich.align import Align
    from rich.markup import escape
    from rich.padding import Padding
    RICH_AVAILABLE = True
except ImportError:
    if os.environ.get("_TERMUX_SYNC_BOOTSTRAP") != "1":
        sys.stderr.write("\n  termux-sync: installing required package 'rich' ...\n\n")
        _r = subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "rich"])
        if _r.returncode == 0:
            os.environ["_TERMUX_SYNC_BOOTSTRAP"] = "1"
            os.execv(sys.executable, [sys.executable] + sys.argv)
    sys.stderr.write(
        "\n  ERROR: the Python package 'rich' is required but could not be installed.\n"
        "  Install it manually, then run termux-sync again:\n\n"
        "      pip install rich\n\n"
    )
    sys.exit(1)

VERSION       = "1.3.0"
APP_NAME      = "termux-sync"
CONFIG_DIR    = Path.home() / ".config" / APP_NAME
CONFIG_FILE   = CONFIG_DIR / "config.json"
CRON_FILE     = CONFIG_DIR / "cron.json"
LOG_FILE      = CONFIG_DIR / "sync.log"
DEFAULT_DEST  = Path.home() / "termux-backups"

TERMUX_HOME   = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
TERMUX_FILES  = Path(os.environ.get("HOME", str(Path.home())))

BACKUP_ITEMS  = [
    ("packages",    "Installed package list",          None),
    ("home",        "Home directory (~)",              TERMUX_FILES),
    ("usr_etc",     "Termux config (/usr/etc)",        TERMUX_HOME / "etc"),
    ("usr_lib",     "Shared libraries (/usr/lib)",     TERMUX_HOME / "lib"),
]

BANNER = r"""
  ████████╗███████╗██████╗ ███╗   ███╗██╗   ██╗██╗  ██╗
  ╚══██╔══╝██╔════╝██╔══██╗████╗ ████║██║   ██║╚██╗██╔╝
     ██║   █████╗  ██████╔╝██╔████╔██║██║   ██║ ╚███╔╝
     ██║   ██╔══╝  ██╔══██╗██║╚██╔╝██║██║   ██║ ██╔██╗
     ██║   ███████╗██║  ██║██║ ╚═╝ ██║╚██████╔╝██╔╝ ██╗
     ╚═╝   ╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝ ╚═════╝ ╚═╝  ╚═╝
"""

def log(level: str, message: str):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(LOG_FILE, "a") as f:
        f.write(f"[{ts}] [{level.upper()}] {message}\n")


DEFAULT_CONFIG = {
    "storage": "local",
    "local_path": str(DEFAULT_DEST),
    "gdrive_folder_id": "",
    "github_token": "",
    "github_repo": "",
    "github_branch": "main",
    "compression": "gz",
    "exclude_patterns": [
        ".cache", ".npm", "__pycache__", "node_modules", ".gradle",
        ".android", ".thumbnails", "DCIM", "Movies", "Music",
        ".local/share/Trash", ".local/lib", ".java",
        ".m2", ".ivy2", "go/pkg", ".rustup/toolchains",
        ".cargo/registry", ".cargo/git"
    ],
    "max_backups": 5,
    "encrypt": False,
    "encrypt_password": "",
}


def load_config() -> dict:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE) as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise UserError(
                f"The config file is not valid JSON (line {e.lineno}, column {e.colno}).\n"
                f"File: {CONFIG_FILE}",
                hint="Fix the file by hand, or delete it and run [bold]termux-sync setup[/bold] again.",
                title="Config file is corrupted",
            ) from e
        for k, v in DEFAULT_CONFIG.items():
            data.setdefault(k, v)
        return data
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


console = Console()

DEBUG      = bool(os.environ.get("TERMUX_SYNC_DEBUG"))
ISSUES_URL = "https://github.com/djunekz/termux-sync/issues"


# ───────────────────────── Error handling ─────────────────────────
class UserError(Exception):
    """An expected, fixable problem. Shown as a clean message — no traceback."""

    def __init__(self, message: str, hint: str = "", title: str = "Cannot continue"):
        super().__init__(message)
        self.message = message
        self.hint    = hint      # may contain rich markup (written by us, not user input)
        self.title   = title


def print_error(title: str, message: str, hint: str = "", where: str = ""):
    """Render one tidy error panel. `message` is escaped; `hint` may use markup."""
    body = [f"[bold red]{escape(title)}[/bold red]", "", escape(message)]
    if where:
        body += ["", f"[dim]at {escape(where)}[/dim]"]
    if hint:
        body += ["", "[bold yellow]How to fix[/bold yellow]", hint]
    console.print()
    console.print(Panel(
        "\n".join(body),
        title="[bold red] ERROR [/bold red]",
        border_style="red",
        padding=(1, 2),
        expand=False,
    ))
    console.print()


def _origin(exc: BaseException) -> str:
    """Last stack frame that lives in this file, e.g. 'termux-sync.py:1217 in cmd_setup()'."""
    found, tb = "", exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == __file__:
            found = f"{Path(__file__).name}:{tb.tb_lineno} in {tb.tb_frame.f_code.co_name}()"
        tb = tb.tb_next
    return found


def _explain(exc: Exception) -> tuple:
    """Translate an exception into (title, message, hint)."""
    import urllib.error
    import socket

    if isinstance(exc, StreamAbort):          # upload failure while streaming
        exc = exc.original
    if isinstance(exc, UserError):
        return exc.title, exc.message, exc.hint
    if isinstance(exc, EOFError):
        return (
            "Input was closed",
            "termux-sync asked a question, but no answer could be read "
            "(the input stream ended, or you pressed Ctrl+D).",
            "Run the command directly in the Termux terminal — not through a pipe, "
            "script, or widget — and answer the prompts.",
        )
    if isinstance(exc, FileNotFoundError):
        return ("File or folder not found", str(exc.filename or exc),
                "Check that the path exists and is spelled correctly.")
    if isinstance(exc, PermissionError):
        return ("Permission denied", str(exc.filename or exc),
                "Pick a path inside your home directory, or run "
                "[bold]termux-setup-storage[/bold] to grant access to shared storage.")
    if isinstance(exc, OSError) and exc.errno == errno.ENOSPC:
        return ("Device is out of space", "There is not enough free storage to finish this.",
                "Free some space with [bold]termux-sync clear-cache[/bold] "
                "or check usage with [bold]termux-sync check[/bold].")
    if isinstance(exc, urllib.error.HTTPError):
        hint = "Check your token and repository name with [bold]termux-sync setup[/bold]."
        if exc.code in (401, 403):
            hint = "Your token is invalid, expired, or lacks the [bold]repo[/bold] scope. Create a new one and run [bold]termux-sync setup[/bold]."
        elif exc.code == 404:
            hint = "The repository or release was not found. Check the repo name in [bold]termux-sync setup[/bold]."
        return f"GitHub returned HTTP {exc.code}", str(exc.reason), hint
    if isinstance(exc, (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError)):
        return ("Network problem", str(getattr(exc, "reason", None) or exc),
                "Check your internet connection and try again.")
    if isinstance(exc, subprocess.CalledProcessError):
        cmd = exc.cmd if isinstance(exc.cmd, str) else " ".join(map(str, exc.cmd))
        return ("A command failed", f"{cmd}\nexit code {exc.returncode}",
                "Run that command by hand to see its full output.")
    if isinstance(exc, (RuntimeError, ValueError)):
        return "Operation failed", str(exc), "See the message above. Details are saved in the log."
    return (
        "Unexpected error",
        f"{type(exc).__name__}: {exc}",
        f"Run again with [bold]--debug[/bold] for the full traceback.\n"
        f"If it keeps happening, please report it:  [cyan]{ISSUES_URL}[/cyan]",
    )


def handle_crash(exc: Exception):
    """Log the full traceback to the log file; show a clean panel on screen."""
    try:
        log("ERROR", f"{type(exc).__name__}: {exc}")
        for line in "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).splitlines():
            log("TRACE", line)
    except Exception:
        pass

    console.print()                        # leave the half-finished prompt line
    title, message, hint = _explain(exc)
    expected = isinstance(getattr(exc, "original", exc), UserError)
    print_error(title, message, hint, where="" if expected and not DEBUG else _origin(exc))

    if DEBUG:
        console.print("[bold dim]Full traceback (--debug)[/bold dim]")
        console.print_exception(show_locals=False, max_frames=10, suppress=[sys.modules["rich"]])
        console.print()
    else:
        shown = str(LOG_FILE).replace(str(Path.home()), "~")
        console.print(f"  [dim]Log: {shown}[/dim]\n")


def print_banner():
    art_width = max(len(line) for line in BANNER.splitlines())
    if console.width >= art_width + 2:
        console.print(
            Align.center(
                f"[bold green]{BANNER}[/bold green]"))
    else:
        console.print()
        console.print(Align.center("[bold green]T E R M U X - S Y N C[/bold green]"))
        console.print()
    console.print(
        Align.center(
            f"[dim]Version: [/dim][bold white]v{VERSION}[/bold white]\n"
            f"[dim]Source: [/dim][bold white]https://github.com/djunekz/termux-sync[/bold white]\n"
            " • [dim]Termux Backup & Restore[/dim]\n"
            " • [dim]Opensource & License MIT[/dim]"
        )
    )
    console.print()


def note(text: str, style: str = ""):
    """Print wrapped text with a 2-space margin on both sides, so lines that
    wrap on a narrow screen stay aligned instead of jumping back to column 0."""
    console.print(Padding(text, (0, 1, 0, 2)), style=style)


def print_section(title: str, subtitle: str = ""):
    console.print()
    console.print(Rule(f"[bold yellow]{title}[/bold yellow]", style="yellow dim"))
    if subtitle:
        note(f"[dim]{subtitle}[/dim]")
    console.print()


def status_icon(ok: bool) -> str:
    return "[bold green]✓[/bold green]" if ok else "[bold red]✗[/bold red]"


def is_narrow() -> bool:
    """True on phone-sized terminals (Termux portrait is ~45 columns)."""
    return console.width < 72


def make_progress(transient: bool = False, percent: bool = False) -> Progress:
    """One-line-per-task progress display that never wraps.

    The description column takes whatever width is left and is cut with "…"
    instead of pushing the bar/time onto a second line on narrow screens."""
    cols = [
        SpinnerColumn(),
        TextColumn(
            "{task.description}",
            table_column=Column(ratio=1, no_wrap=True, overflow="ellipsis"),
        ),
        BarColumn(bar_width=10 if is_narrow() else 24),
    ]
    if percent:
        cols.append(TaskProgressColumn())
    cols.append(TimeElapsedColumn())
    return Progress(*cols, console=console, expand=True, transient=transient)


def fmt_elapsed(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _backup_date(b: dict) -> str:
    return str(b.get("date", "—"))[:16].replace("T", " ")


def _backup_label(b: dict) -> str:
    label = b.get("label", "") or ""
    return "" if label == b.get("name") else label


def _backup_size(b: dict) -> int:
    return sum(v.get("size", 0) for v in (b.get("files") or {}).values())


def print_backup_list(backups: list, title: str = "Available Backups"):
    """Numbered backup list. Table on wide terminals, 2-line cards on phones."""
    if is_narrow():
        console.print(f"  [bold yellow]{title}[/bold yellow]\n")
        for i, b in enumerate(backups, 1):
            console.print(f"  [bold cyan]{i:>2}[/bold cyan]  [bold white]{escape(str(b.get('name', '—')))}[/bold white]")
            bits = [f"[green]{_backup_date(b)}[/green]"]
            if b.get("packages"):
                bits.append(f"[cyan]{len(b['packages'])} pkgs[/cyan]")
            if _backup_size(b):
                bits.append(f"[blue]{human_size(_backup_size(b))}[/blue]")
            if _backup_label(b):
                bits.append(f"[yellow]{escape(_backup_label(b))}[/yellow]")
            console.print("      " + " [dim]·[/dim] ".join(bits))
            console.print()
        return

    table = Table(
        box=box.ROUNDED,
        title=f"[bold yellow]{title}[/bold yellow]",
        show_header=True,
        header_style="bold cyan",
        padding=(0, 1),
    )
    table.add_column("#",    style="dim", width=3, justify="right")
    table.add_column("Name", style="bold white", no_wrap=True)
    table.add_column("Date", style="green", no_wrap=True)
    table.add_column("Pkgs", style="cyan", justify="right")
    table.add_column("Size", style="blue", justify="right")
    table.add_column("Label", style="yellow")
    for i, b in enumerate(backups, 1):
        table.add_row(
            str(i),
            escape(str(b.get("name", "—"))),
            _backup_date(b),
            str(len(b.get("packages", []))) if b.get("packages") else "—",
            human_size(_backup_size(b)) if _backup_size(b) else "—",
            escape(_backup_label(b)) or "—",
        )
    console.print(table)
    console.print()


def human_size(size_bytes: int) -> str:
    size_bytes = int(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"


def sha256(path: Path, chunk=1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk_data := f.read(chunk):
            h.update(chunk_data)
    return h.hexdigest()


def get_installed_packages() -> list[str]:
    try:
        result = subprocess.run(
            ["dpkg", "--get-selections"],
            capture_output=True, text=True, check=True
        )
        pkgs = []
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "install":
                pkgs.append(parts[0])
        return pkgs
    except Exception:
        return []


def install_packages(pkg_list: list[str], console: Console) -> list[str]:
    """Reinstall packages one by one. Returns the names that failed."""
    if not pkg_list:
        console.print("  [yellow]No packages to install.[/yellow]")
        return []
    failed: list[str] = []
    total = len(pkg_list)
    with make_progress(transient=True, percent=True) as progress:
        task = progress.add_task("[cyan]Installing…", total=total)
        for i, pkg in enumerate(pkg_list, 1):
            progress.update(task, description=f"[cyan]{i}/{total}  {escape(pkg)}")
            try:
                subprocess.run(
                    ["pkg", "install", "-y", pkg],
                    capture_output=True, check=True
                )
            except Exception:
                failed.append(pkg)
            progress.advance(task)
    console.print(f"  {status_icon(True)} Installed [bold green]{total - len(failed)}[/bold green] of {total} packages")
    if failed:
        console.print(f"  [yellow]⚠ {len(failed)} package(s) could not be installed (see log).[/yellow]")
        log("WARNING", "Packages failed to install: " + ", ".join(failed))
    return failed


def create_archive(
    source_path: Path,
    archive_path: Path,
    compression: str,
    excludes: list[str],
    label: str,
    progress: Progress,
    sink=None,
) -> Path:
    """Create a tar archive. With `sink` (a file-like object) the archive is streamed
    into it and nothing is written to `archive_path`."""
    valid_compressions = {"gz", "bz2", "xz"}
    if compression not in valid_compressions:
        compression = "gz"

    mode = f"w:{compression}"
    ext  = f".tar.{compression}"

    out = archive_path
    if not str(archive_path).endswith(ext):
        stem = archive_path.name
        for old_ext in (".tar.gz", ".tar.bz2", ".tar.xz", ".tar"):
            if stem.endswith(old_ext):
                stem = stem[: -len(old_ext)]
                break
        out = archive_path.parent / (stem + ext)

    task = progress.add_task(f"[cyan]{label}", total=None)
    if sink is not None and hasattr(sink, "attach"):
        sink.attach(progress, task, label)

    def _filter(tarinfo):
        for pat in excludes:
            if pat in tarinfo.name:
                return None
        return tarinfo

    unlocked: list[tuple[Path, int]] = []

    def _unlock(root: Path):
        for dp, dirs, files in os.walk(root):
            d = Path(dp)
            try:
                if not os.access(d, os.R_OK | os.X_OK):
                    m = d.stat().st_mode
                    d.chmod(m | 0o500)
                    unlocked.append((d, m))
            except Exception:
                pass
            for fname in files:
                fp = d / fname
                try:
                    if not os.access(fp, os.R_OK):
                        m = fp.stat().st_mode
                        fp.chmod(m | 0o400)
                        unlocked.append((fp, m))
                except Exception:
                    pass

    def _relock():
        for path, orig in reversed(unlocked):
            try:
                path.chmod(orig)
            except Exception:
                pass

    try:
        if source_path.is_dir():
            _unlock(source_path)
        if sink is not None:
            opened = tarfile.open(fileobj=sink, mode=f"w|{compression}")
        else:
            opened = tarfile.open(out, mode)
        with opened as tf:
            if source_path.is_dir():
                tf.add(source_path, arcname=source_path.name, filter=_filter)
            else:
                tf.add(source_path, arcname=source_path.name)
    finally:
        _relock()

    progress.update(task, total=1, completed=1, description=f"[green]{label} ✓")
    return out


def _safe_extract_member(member: tarfile.TarInfo, dest_path: Path):
    dest_root = dest_path.resolve()

    member_name = member.name
    if member_name.startswith("/") or member_name.startswith("\\"):
        raise ValueError(f"Unsafe absolute path in archive: {member_name!r}")
    if any(part == ".." for part in Path(member_name).parts):
        raise ValueError(f"Path traversal attempt in archive: {member_name!r}")

    target = (dest_path / member_name).resolve()
    try:
        target.relative_to(dest_root)
    except ValueError:
        raise ValueError(f"Archive member escapes destination: {member_name!r} -> {target}")

    if member.issym() or member.islnk():
        link_target = member.linkname
        if os.path.isabs(link_target):
            raise ValueError(f"Unsafe absolute link target in archive: {member_name!r} -> {link_target!r}")
        resolved_link = (target.parent / link_target).resolve()
        try:
            resolved_link.relative_to(dest_root)
        except ValueError:
            raise ValueError(f"Archive link escapes destination: {member_name!r} -> {link_target!r}")

    if member.ischr() or member.isblk() or member.isfifo():
        raise ValueError(f"Refusing device/fifo entry in archive: {member_name!r}")


def extract_archive(archive_path: Path, dest_path: Path, label: str, progress: Progress):
    task = progress.add_task(f"[cyan]{label}", total=None)
    dest_path.mkdir(parents=True, exist_ok=True)

    has_data_filter = hasattr(tarfile, "data_filter")

    with tarfile.open(archive_path, "r:*") as tf:
        for member in tf.getmembers():
            try:
                _safe_extract_member(member, dest_path)
            except ValueError as e:
                log("WARNING", f"Skipped unsafe archive member during restore: {e}")
                continue

            try:
                if has_data_filter:
                    tf.extract(member, dest_path, set_attrs=True, filter="data")
                else:
                    tf.extract(member, dest_path, set_attrs=True)
            except Exception:
                try:
                    member.uid = os.getuid()
                    member.gid = os.getgid()
                    if has_data_filter:
                        tf.extract(member, dest_path, set_attrs=False, filter="data")
                    else:
                        tf.extract(member, dest_path, set_attrs=False)
                except Exception:
                    pass
    progress.update(task, total=1, completed=1, description=f"[green]{label} ✓")


def write_manifest(backup_dir: Path, meta: dict):
    manifest_path = backup_dir / "manifest.json"
    with open(manifest_path, "w") as f:
        json.dump(meta, f, indent=2)
    return manifest_path


def read_manifest(backup_dir: Path) -> Optional[dict]:
    p = backup_dir / "manifest.json"
    if p.exists():
        with open(p) as f:
            return json.load(f)
    return None


class LocalStorage:
    def __init__(self, cfg: dict):
        self.root = Path(cfg["local_path"])

    def upload(self, backup_dir: Path, backup_name: str, progress: Progress) -> str:
        dest = self.root / backup_name
        task = progress.add_task("[cyan]Saving to local storage…", total=None)
        dest.mkdir(parents=True, exist_ok=True)
        for f in backup_dir.iterdir():
            shutil.copy2(f, dest / f.name)
        progress.update(task, total=1, completed=1, description="[green]Saved locally ✓")
        return str(dest)

    def list_backups(self) -> list[dict]:
        if not self.root.exists():
            return []
        backups = []
        try:
            dirs = sorted(self.root.iterdir(), reverse=True)
        except PermissionError:
            return []
        for d in dirs:
            if d.is_dir():
                manifest = read_manifest(d)
                if manifest:
                    backups.append(manifest)
        return backups

    def download(self, backup_name: str, dest: Path, progress: Progress):
        src = self.root / backup_name
        if not src.exists():
            raise FileNotFoundError(f"Backup not found: {src}")
        task = progress.add_task("[cyan]Loading from local storage…", total=None)
        dest.mkdir(parents=True, exist_ok=True)
        for f in src.iterdir():
            shutil.copy2(f, dest / f.name)
        progress.update(task, total=1, completed=1, description="[green]Loaded ✓")

    def delete_old(self, max_keep: int):
        if not self.root.exists():
            return
        try:
            dirs = sorted(self.root.iterdir(), key=lambda d: d.stat().st_mtime, reverse=True)
        except PermissionError:
            return
        dirs = [d for d in dirs if d.is_dir()]
        for old in dirs[max_keep:]:
            shutil.rmtree(old, ignore_errors=True)

    def delete_backup(self, backup_name: str):
        target = self.root / backup_name
        if not target.exists():
            raise FileNotFoundError(f"Backup not found: {target}")
        shutil.rmtree(target)


class GDriveStorage:
    REMOTE = "termux-sync-gdrive"

    def __init__(self, cfg: dict):
        self.folder_id = cfg.get("gdrive_folder_id", "")
        self._check_rclone()

    def _check_rclone(self):
        if shutil.which("rclone") is None:
            raise UserError(
                "Google Drive storage needs rclone, but it is not installed.",
                hint="Install it with [bold]pkg install rclone[/bold], then configure a remote "
                     "named [bold]termux-sync-gdrive[/bold] using [bold]rclone config[/bold].",
                title="rclone not found",
            )

    def _remote_path(self, name: str = "") -> str:
        base = f"{self.REMOTE}:"
        if self.folder_id:
            base += self.folder_id
        return f"{base}/{name}" if name else base

    def upload(self, backup_dir: Path, backup_name: str, progress: Progress) -> str:
        task = progress.add_task("[cyan]Uploading to Google Drive…", total=None)
        remote = self._remote_path(backup_name)
        subprocess.run(
            ["rclone", "copy", str(backup_dir), remote, "--progress"],
            check=True, capture_output=True
        )
        progress.update(task, total=1, completed=1, description="[green]Uploaded to Google Drive ✓")
        return remote

    def list_backups(self) -> list[dict]:
        try:
            result = subprocess.run(
                ["rclone", "lsjson", self._remote_path(), "--dirs-only"],
                capture_output=True, text=True, check=True
            )
            items = json.loads(result.stdout)
            backups = []
            for item in sorted(items, key=lambda x: x.get("ModTime", ""), reverse=True):
                try:
                    r = subprocess.run(
                        ["rclone", "cat", self._remote_path(f"{item['Name']}/manifest.json")],
                        capture_output=True, text=True, check=True
                    )
                    backups.append(json.loads(r.stdout))
                except Exception:
                    backups.append({"name": item["Name"], "date": item.get("ModTime", "")})
            return backups
        except Exception:
            return []

    def download(self, backup_name: str, dest: Path, progress: Progress):
        task = progress.add_task("[cyan]Downloading from Google Drive…", total=None)
        dest.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["rclone", "copy", self._remote_path(backup_name), str(dest)],
            check=True, capture_output=True
        )
        progress.update(task, total=1, completed=1, description="[green]Downloaded ✓")

    def delete_old(self, max_keep: int):
        try:
            result = subprocess.run(
                ["rclone", "lsjson", self._remote_path(), "--dirs-only"],
                capture_output=True, text=True, check=True
            )
            items = json.loads(result.stdout)
            items.sort(key=lambda x: x.get("ModTime", ""), reverse=True)
            for old in items[max_keep:]:
                try:
                    subprocess.run(
                        ["rclone", "purge", self._remote_path(old["Name"])],
                        capture_output=True, check=True
                    )
                except Exception:
                    pass
        except Exception:
            pass

    def delete_backup(self, backup_name: str):
        try:
            subprocess.run(
                ["rclone", "purge", self._remote_path(backup_name)],
                check=True, capture_output=True
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"Failed to delete backup from Google Drive: {e}") from e


class GitHubStorage:
    API = "https://api.github.com"

    def __init__(self, cfg: dict):
        self.token  = cfg.get("github_token", "")
        self.repo   = cfg.get("github_repo", "")
        self.branch = cfg.get("github_branch", "main")
        if not self.token or not self.repo:
            raise UserError(
                "GitHub storage is selected, but the token or repository is not set.",
                hint="Run [bold]termux-sync setup[/bold] and enter your Personal Access Token "
                     "and repo (owner/repo).",
                title="GitHub is not configured",
            )

    def _headers(self) -> dict:
        return {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
        }

    def _asset_headers(self) -> dict:
        return {
            "Authorization": f"token {self.token}",
            "Accept": "application/octet-stream",
        }

    def _asset_url(self, asset_id: int) -> str:
        return f"{self.API}/repos/{self.repo}/releases/assets/{asset_id}"

    def _api(self, method: str, endpoint: str, **kwargs):
        import urllib.request, urllib.error
        url  = f"{self.API}{endpoint}"
        data = json.dumps(kwargs.get("json", {})).encode() if "json" in kwargs else None
        req  = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                if resp.status == 204:
                    return {}
                body = resp.read()
                if not body:
                    return {}
                return json.loads(body)
        except urllib.error.HTTPError as e:
            raise self._http_error(e.code, e.read().decode(errors="replace")) from e

    def _http_error(self, code: int, raw: str) -> Exception:
        """Turn a GitHub API error response into a short, human-readable exception."""
        try:
            data   = json.loads(raw)
            msg    = str(data.get("message", "")).strip()
            extras = "; ".join(
                str(x.get("message")) for x in data.get("errors", [])
                if isinstance(x, dict) and x.get("message")
            )
        except Exception:
            msg, extras = raw.strip()[:300], ""
        blob = f"{msg} {extras}".lower()

        if code in (409, 422) and "empty" in blob:
            return UserError(
                f"The repository '{self.repo}' has no commits yet, and GitHub cannot "
                "create a release in an empty repository.",
                hint="Open the repository on GitHub, click [bold]Add a README[/bold] (or create "
                     "any file) and commit it. Then run the command again.",
                title="GitHub repository is empty",
            )
        if code == 401:
            return UserError(
                "GitHub rejected the token (bad credentials).",
                hint="Create a new token with the [bold]repo[/bold] scope at "
                     "[cyan]https://github.com/settings/tokens[/cyan], then run "
                     "[bold]termux-sync setup[/bold].",
                title="Invalid GitHub token",
            )
        if code == 403 and "rate limit" in blob:
            return UserError(
                "GitHub is limiting requests from this token for now.",
                hint="Wait a few minutes and try again.",
                title="GitHub rate limit reached",
            )
        if code == 403:
            return UserError(
                msg or "The token is not allowed to do this.",
                hint="Make sure the token has the [bold]repo[/bold] scope and can write to this repository.",
                title="GitHub denied access",
            )
        if code == 404:
            return UserError(
                f"Repository '{self.repo}' was not found, or the token cannot see it.",
                hint="Check the spelling (owner/repo) in [bold]termux-sync setup[/bold]. "
                     "For a private repository the token needs the [bold]repo[/bold] scope.",
                title="GitHub repository not found",
            )
        detail = ": ".join(x for x in (msg, extras) if x) or "no details"
        return RuntimeError(f"GitHub API error {code}: {detail}")

    def preflight(self):
        """Fail fast — before a long archive step — if the repo cannot hold a release."""
        self._api("GET", f"/repos/{self.repo}")                     # token + repo name
        self._api("GET", f"/repos/{self.repo}/commits?per_page=1")  # 409 if empty

    # ── streaming backup: parts are uploaded and deleted one by one ──
    def begin_stream(self, backup_name: str, work_dir: Path):
        work_dir.mkdir(parents=True, exist_ok=True)
        need = int(self.CHUNK_SIZE * 1.2)
        free = shutil.disk_usage(work_dir).free
        if free < need:
            raise UserError(
                f"Only {human_size(free)} is free, but about {human_size(need)} is needed "
                "to hold one upload part.",
                hint="Free some space with [bold]termux-sync clear-cache[/bold], or remove "
                     "files you no longer need, then try again.",
                title="Not enough free space",
            )
        release = self._get_release_by_tag(backup_name) or self._create_release(backup_name)
        self._stream = {"release_id": release["id"], "work_dir": work_dir}

    def stream_sink(self, base_name: str, progress: Progress):
        return _PartWriter(self, self._stream["release_id"], base_name,
                           self._stream["work_dir"], progress)

    def abort_stream(self, backup_name: str):
        """Best effort: remove a half-finished release so it never counts as a backup."""
        try:
            self.delete_backup(backup_name)
        except Exception:
            pass

    def _push_file(self, local_path: Path, remote_path: str, message: str):
        import base64
        content = base64.b64encode(local_path.read_bytes()).decode()
        sha = None
        try:
            r = self._api("GET", f"/repos/{self.repo}/contents/{remote_path}?ref={self.branch}")
            sha = r.get("sha")
        except Exception:
            pass

        payload = {
            "message": message,
            "content": content,
            "branch":  self.branch,
        }
        if sha:
            payload["sha"] = sha

        self._api("PUT", f"/repos/{self.repo}/contents/{remote_path}", json=payload)

    def _create_release(self, backup_name: str) -> dict:
        return self._api("POST", f"/repos/{self.repo}/releases", json={
            "tag_name":         backup_name,
            "name":             backup_name,
            "body":             f"termux-sync backup — {backup_name}",
            "draft":            False,
            "prerelease":       False,
            "target_commitish": self.branch,
        })

    def _get_release_by_tag(self, tag: str) -> Optional[dict]:
        try:
            return self._api("GET", f"/repos/{self.repo}/releases/tags/{tag}")
        except Exception:
            return None

    def _list_releases(self) -> list[dict]:
        try:
            return self._api("GET", f"/repos/{self.repo}/releases?per_page=100")
        except Exception:
            return []

    CHUNK_SIZE  = 200 * 1024 * 1024
    MAX_RETRIES = 8

    def _split_file(self, src: Path, tmp_dir: Path) -> list:
        size = src.stat().st_size
        if size <= self.CHUNK_SIZE:
            return [src]
        chunks = []
        idx = 0
        with open(src, "rb") as f:
            while True:
                data = f.read(self.CHUNK_SIZE)
                if not data:
                    break
                chunk_path = tmp_dir / f"{src.name}.part{idx:04d}"
                chunk_path.write_bytes(data)
                chunks.append(chunk_path)
                idx += 1
        return chunks

    def _upload_one_asset(self, release_id: int, local_path: Path,
                          progress_task, progress: Progress):
        import urllib.request, urllib.error, time as _time
        upload_url = (
            f"https://uploads.github.com/repos/{self.repo}/releases/{release_id}/assets"
            f"?name={local_path.name}"
        )
        file_size = local_path.stat().st_size
        progress.update(progress_task, total=file_size, completed=0)

        last_err = None
        for attempt in range(self.MAX_RETRIES):
            try:
                with open(local_path, "rb") as fobj:
                    data = fobj.read()
                headers = dict(self._headers())
                headers["Content-Type"]   = "application/octet-stream"
                headers["Content-Length"] = str(len(data))
                req = urllib.request.Request(
                    upload_url, data=data, headers=headers, method="POST"
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    result = json.loads(resp.read())
                progress.update(progress_task, completed=file_size)
                return result
            except urllib.error.HTTPError as e:
                # (HTTPError is a URLError subclass, so it must be handled first)
                body = e.read().decode(errors="replace")
                if e.code == 422:
                    progress.update(progress_task, completed=file_size,
                                    description=f"[yellow]{local_path.name} already uploaded, skipping")
                    return {}
                if e.code >= 500 or e.code == 429:      # temporary: retry
                    last_err = e
                    progress.update(progress_task,
                        description=f"[yellow]Retry {attempt+1}/{self.MAX_RETRIES} ({local_path.name})...")
                    _time.sleep(15 * (attempt + 1))
                    continue
                raise self._http_error(e.code, body) from e   # permanent: stop now
            except (urllib.error.URLError, OSError, ConnectionError) as e:
                if getattr(e, "errno", None) == errno.ENOSPC:
                    raise
                last_err = e
                wait = 15 * (attempt + 1)
                progress.update(progress_task,
                    description=f"[yellow]Retry {attempt+1}/{self.MAX_RETRIES} ({local_path.name})...")
                _time.sleep(wait)

        raise RuntimeError(
            f"Failed to upload {local_path.name} after {self.MAX_RETRIES} attempts: {last_err}"
        )

    def upload(self, backup_dir: Path, backup_name: str, progress: Progress) -> str:
        task = progress.add_task("[cyan]Creating GitHub Release...", total=None)
        existing = self._get_release_by_tag(backup_name)
        if existing:
            release = existing
        else:
            release = self._create_release(backup_name)
        release_id  = release["id"]
        release_url = release["html_url"]
        progress.update(task, total=1, completed=1,
                        description="[green]Release ready")

        existing_assets = {a["name"] for a in release.get("assets", [])}

        tmp_split = Path(os.environ.get("TMPDIR", "/data/data/com.termux/files/usr/tmp")) / f"termux-sync-split-{backup_name}"
        tmp_split.mkdir(parents=True, exist_ok=True)
        try:
            for f in sorted(backup_dir.iterdir()):
                if not f.is_file():
                    continue
                chunks = self._split_file(f, tmp_split)
                for chunk in chunks:
                    if chunk.name in existing_assets:
                        continue
                    progress.update(task, total=None, completed=0,
                                    description=f"[cyan]Uploading {escape(chunk.name)}")
                    asset_task = progress.add_task(
                        f"[cyan]{chunk.name}...", total=chunk.stat().st_size
                    )
                    try:
                        self._upload_one_asset(release_id, chunk, asset_task, progress)
                    finally:
                        progress.remove_task(asset_task)
        finally:
            shutil.rmtree(tmp_split, ignore_errors=True)

        progress.update(task, total=1, completed=1,
                        description="[green]Uploaded to GitHub Releases ✓")
        return release_url

    def list_backups(self) -> list[dict]:
        backups = []
        for rel in self._list_releases():
            tag = rel.get("tag_name", "")
            if not tag.startswith("termux_backup_"):
                continue
            manifest = None
            for asset in rel.get("assets", []):
                if asset["name"] == "manifest.json":
                    try:
                        import urllib.request
                        req = urllib.request.Request(
                            self._asset_url(asset["id"]),
                            headers=self._asset_headers()
                        )
                        with urllib.request.urlopen(req, timeout=30) as r:
                            manifest = json.loads(r.read())
                    except Exception:
                        pass
                    break
            backups.append(manifest or {
                "name": tag,
                "date": rel.get("created_at", ""),
                "label": "",
            })
        return backups

    def download(self, backup_name: str, dest: Path, progress: Progress):
        import urllib.request, re as _re, time as _time
        release = self._get_release_by_tag(backup_name)
        if not release:
            raise RuntimeError(f"No GitHub Release found for tag: {backup_name}")
        assets = sorted(release.get("assets", []), key=lambda a: a["name"])
        dest.mkdir(parents=True, exist_ok=True)

        # One overall task (bytes) instead of one row per part: with ~25 parts the
        # old per-file rows were taller than the screen and the display fell apart.
        n_files     = len(assets)
        total_bytes = sum(a.get("size", 0) for a in assets) or 1
        task        = progress.add_task("[cyan]Downloading…", total=total_bytes)
        done_bytes  = 0

        for n, asset in enumerate(assets, 1):
            url  = self._asset_url(asset["id"])
            name = asset["name"]
            out  = dest / name
            tag  = f"{n}/{n_files}"
            shown = re.sub(r"\.tar\.(gz|bz2|xz)", "", name) if is_narrow() else name
            last_err = None
            for attempt in range(8):
                got = 0
                try:
                    req = urllib.request.Request(url, headers=self._asset_headers())
                    with urllib.request.urlopen(req, timeout=120) as r, open(out, "wb") as fh:
                        while True:
                            block = r.read(1 << 18)
                            if not block:
                                break
                            fh.write(block)
                            got += len(block)
                            progress.update(
                                task, completed=min(done_bytes + got, total_bytes),
                                description=f"[cyan]{tag}  {escape(shown)}",
                            )
                    done_bytes += got
                    last_err = None
                    break
                except Exception as e:
                    if getattr(e, "errno", None) == errno.ENOSPC:
                        raise
                    last_err = e
                    progress.update(
                        task, completed=min(done_bytes, total_bytes),
                        description=f"[yellow]{tag}  retry {attempt+1}/8",
                    )
                    _time.sleep(15 * (attempt + 1))
            if last_err:
                raise RuntimeError(
                    f"Failed to download {name} after 8 attempts: {last_err}"
                )

        chunk_re = _re.compile(r"^(.+)\.part(\d{4})$")
        groups: dict = {}
        for f in sorted(dest.iterdir()):
            m = chunk_re.match(f.name)
            if m:
                groups.setdefault(m.group(1), []).append(f)

        for original_name, parts in groups.items():
            parts.sort(key=lambda p: p.name)
            group_total = sum(p.stat().st_size for p in parts) or 1
            progress.update(task, completed=0, total=group_total,
                            description=f"[cyan]Joining {escape(original_name)}")
            out_file = dest / original_name
            with open(out_file, "wb") as fout:
                for part in parts:
                    with open(part, "rb") as fin:
                        shutil.copyfileobj(fin, fout, 1 << 20)
                    progress.advance(task, part.stat().st_size)
                    part.unlink()

        progress.update(task, description="[green]Downloaded ✓")

    def delete_old(self, max_keep: int):
        releases = [
            r for r in self._list_releases()
            if r.get("tag_name", "").startswith("termux_backup_")
        ]
        releases.sort(key=lambda r: r.get("created_at", ""), reverse=True)
        for old in releases[max_keep:]:
            try:
                self._api("DELETE", f"/repos/{self.repo}/releases/{old['id']}")
                self._api("DELETE", f"/repos/{self.repo}/git/refs/tags/{old['tag_name']}")
            except Exception:
                pass

    def delete_backup(self, backup_name: str):
        release = self._get_release_by_tag(backup_name)
        if not release:
            raise FileNotFoundError(f"Backup '{backup_name}' not found in GitHub Releases.")
        try:
            self._api("DELETE", f"/repos/{self.repo}/releases/{release['id']}")
            self._api("DELETE", f"/repos/{self.repo}/git/refs/tags/{backup_name}")
        except Exception as e:
            raise RuntimeError(f"Failed to delete backup from GitHub: {e}") from e


class StreamAbort(Exception):
    """Raised when an upload fails while the archive is being streamed."""
    def __init__(self, original: Exception):
        super().__init__(str(original))
        self.original = original


class _PartWriter:
    """File-like sink for tarfile. Cuts the stream into CHUNK_SIZE parts and uploads
    each part as soon as it is full, then deletes it — so the device never needs room
    for the whole archive. Part names match what `restore` already reassembles."""

    def __init__(self, storage, release_id: int, base_name: str, work_dir: Path, progress: Progress):
        self.storage, self.release_id, self.base = storage, release_id, base_name
        self.work_dir, self.progress = work_dir, progress
        self.limit = storage.CHUNK_SIZE
        self.idx = 0                       # parts uploaded so far
        self.total = 0                     # bytes of the whole archive
        self.sha = hashlib.sha256()        # checksum of the whole archive
        self._fh = None
        self._path = None
        self._size = 0
        self._task = None
        self._label = base_name
        self._next_note = 0

    def attach(self, progress, task, label):
        self.progress, self._task, self._label = progress, task, label

    def _note(self):
        if self._task is not None:
            self.progress.update(
                self._task,
                description=f"[cyan]{self._label}  [dim]{human_size(self.total)} sent[/dim]",
            )

    def writable(self):
        return True

    def flush(self):
        pass

    def write(self, data) -> int:
        view, pos, n = memoryview(data), 0, len(data)
        while pos < n:
            if self._fh is not None and self._size >= self.limit:
                self._flush(final=False)
            if self._fh is None:
                self._path = self.work_dir / f"{self.base}.part{self.idx:04d}"
                self._fh, self._size = open(self._path, "wb"), 0
            piece = view[pos: pos + (self.limit - self._size)]
            self._fh.write(piece)
            self._size += len(piece)
            self.total += len(piece)
            self.sha.update(piece)
            pos += len(piece)
        if self.total >= self._next_note:
            self._next_note = self.total + (8 << 20)
            self._note()
        return n

    def _flush(self, final: bool):
        self._fh.close()
        self._fh = None
        path = self._path
        if final and self.idx == 0:        # small archive: one plain file, no ".part"
            plain = self.work_dir / self.base
            path.rename(plain)
            path = plain
        task = self.progress.add_task(f"[cyan]{path.name}…", total=max(path.stat().st_size, 1))
        try:
            self.storage._upload_one_asset(self.release_id, path, task, self.progress)
        except Exception as e:
            raise StreamAbort(e) from e
        finally:
            self.progress.remove_task(task)
            path.unlink(missing_ok=True)
        self.idx += 1
        self._note()

    def finish(self):
        """Upload the last (possibly partial) part."""
        if self._fh is not None:
            self._flush(final=True)

    def abort(self):
        """Drop whatever is still on disk."""
        try:
            if self._fh is not None:
                self._fh.close()
                self._fh = None
            if self._path is not None:
                Path(self._path).unlink(missing_ok=True)
        except Exception:
            pass


def get_storage(cfg: dict):
    s = cfg.get("storage", "local")
    if s == "gdrive":
        return GDriveStorage(cfg)
    if s == "github":
        return GitHubStorage(cfg)
    return LocalStorage(cfg)


def cmd_backup(cfg: dict, label: str = ""):
    print_section("BACKUP", "Creating a full snapshot of your Termux environment")

    timestamp   = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"termux_backup_{timestamp}"
    if label:
        backup_name += f"_{label.replace(' ', '_')}"

    tmp_dir = Path(os.environ.get("TMPDIR", "/data/data/com.termux/files/usr/tmp")) / backup_name
    tmp_dir.mkdir(parents=True, exist_ok=True)

    def _cleanup_tmp():
        shutil.rmtree(tmp_dir, ignore_errors=True)

    def _abort_backup():
        if streaming:
            storage.abort_stream(backup_name)
        _cleanup_tmp()

    compression = cfg.get("compression", "gz")
    if compression not in ("gz", "bz2", "xz"):
        console.print(f"  [yellow]⚠ Compression '{compression}' is invalid, falling back to 'gz'.[/yellow]")
        compression = "gz"

    excludes = cfg.get("exclude_patterns", [])
    storage  = get_storage(cfg)

    check_storage = getattr(storage, "preflight", None)
    if check_storage:
        console.print("  [bold]Check[/bold]   Verifying GitHub repository…")
        try:
            check_storage()
        except BaseException:
            _cleanup_tmp()
            raise
        console.print(f"  {status_icon(True)} Repository is ready\n")

    streaming = hasattr(storage, "begin_stream")
    if streaming:
        try:
            storage.begin_stream(backup_name, tmp_dir / ".parts")
        except BaseException:
            _cleanup_tmp()
            raise
        console.print(
            f"  {status_icon(True)} Streaming upload: the archive is sent in parts, "
            "so your device never holds a full copy\n"
        )

    meta = {
        "name":        backup_name,
        "date":        datetime.datetime.now().isoformat(),
        "label":       label,
        "termux_home": str(TERMUX_FILES),
        "termux_usr":  str(TERMUX_HOME),
        "storage":     cfg["storage"],
        "compression": compression,
        "version":     VERSION,
        "files":       {},
        "packages":    [],
    }

    console.print("  [bold]Step 1/4[/bold]  Collecting installed packages…")
    pkgs = get_installed_packages()
    meta["packages"] = pkgs
    pkg_file = tmp_dir / "packages.txt"
    pkg_file.write_text("\n".join(pkgs))
    console.print(f"  {status_icon(True)} Found [bold green]{len(pkgs)}[/bold green] installed packages")
    log("INFO", f"Collected {len(pkgs)} packages")

    console.print()
    console.print("  [bold]Step 2/4[/bold]  " +
                  ("Archiving & uploading directories…" if streaming else "Archiving directories…"))
    console.print()

    with make_progress() as progress:
        archive_items = [
            ("home",    "Home directory (~)",       TERMUX_FILES),
            ("usr_etc", "Termux config (/usr/etc)", TERMUX_HOME / "etc"),
        ]
        for key, label_text, src in archive_items:
            if not src.exists():
                console.print(f"  [yellow]⚠ Skipping {src} (not found)[/yellow]")
                continue
            out_path = tmp_dir / f"{key}.tar.{compression}"
            sink = storage.stream_sink(out_path.name, progress) if streaming else None
            try:
                actual_out = create_archive(src, out_path, compression, excludes, label_text,
                                            progress, sink=sink)
                if sink is not None:
                    sink.finish()
                    archive_size, checksum = sink.total, sink.sha.hexdigest()
                else:
                    checksum     = sha256(actual_out)
                    archive_size = actual_out.stat().st_size
                meta["files"][key] = {
                    "archive":  actual_out.name,
                    "size":     archive_size,
                    "checksum": checksum,
                    "source":   str(src),
                }
                log("INFO", f"Archived {src} → {actual_out.name} ({human_size(archive_size)})")
            except (StreamAbort, KeyboardInterrupt):
                if sink is not None:
                    sink.abort()
                for t in list(progress.tasks):
                    progress.remove_task(t.id)
                _abort_backup()
                raise
            except OSError as e:
                if sink is not None:
                    sink.abort()
                if e.errno == errno.ENOSPC:             # out of space: stop, don't continue silently
                    for t in list(progress.tasks):
                        progress.remove_task(t.id)
                    _abort_backup()
                    raise
                console.print(f"  [red]✗ Failed to archive {src}: {escape(str(e))}[/red]")
                log("ERROR", f"Archive failed for {src}: {e}")
            except Exception as e:
                if sink is not None:
                    sink.abort()
                console.print(f"  [red]✗ Failed to archive {src}: {escape(str(e))}[/red]")
                log("ERROR", f"Archive failed for {src}: {e}")

    console.print()
    console.print("  [bold]Step 3/4[/bold]  Writing manifest…")
    write_manifest(tmp_dir, meta)
    console.print(f"  {status_icon(True)} Manifest written")

    console.print()
    console.print(f"  [bold]Step 4/4[/bold]  Uploading to [bold cyan]{cfg['storage'].upper()}[/bold cyan]…")
    console.print()

    location = ""
    upload_error = None
    with make_progress() as progress:
        try:
            location = storage.upload(tmp_dir, backup_name, progress)
            storage.delete_old(cfg.get("max_backups", 5))
        except KeyboardInterrupt:
            _abort_backup()
            raise
        except Exception as e:
            upload_error = e
            for t in list(progress.tasks):          # drop the half-finished spinner line
                progress.remove_task(t.id)

    if upload_error is not None:
        log("ERROR", f"Upload failed: {upload_error}")
        title, message, hint = _explain(upload_error)
        print_error(f"Upload failed — {title}", message, hint)
        if streaming:
            _abort_backup()        # remove the incomplete release so it never counts as a backup
            console.print("  [dim]The incomplete backup was removed from GitHub.[/dim]\n")
        else:
            console.print("  [bold]Your backup files were kept[/bold] so the work is not lost:")
            console.print(f"  [white]{escape(str(tmp_dir))}[/white]", soft_wrap=True)
            console.print("  [dim]Delete them when you no longer need them:[/dim]")
            console.print(f"  rm -rf {escape(str(tmp_dir))}\n", soft_wrap=True)
        return

    shutil.rmtree(tmp_dir, ignore_errors=True)

    total_size = sum(v["size"] for v in meta["files"].values())

    console.print()
    console.print(Panel(
        f"[bold green]✓ Backup completed successfully![/bold green]\n\n"
        f"[dim]Name    [/dim] [white]{escape(backup_name)}[/white]\n"
        f"[dim]Date    [/dim] [white]{meta['date'][:19].replace('T', ' ')}[/white]\n"
        f"[dim]Packages[/dim] [white]{len(pkgs)}[/white]\n"
        f"[dim]Size    [/dim] [white]{human_size(total_size)}[/white]\n"
        f"[dim]Storage [/dim] [white]{cfg['storage'].upper()}[/white]\n"
        f"[dim]Location[/dim] [white]{escape(short_path(location))}[/white]",
        title="[bold yellow]Backup Summary[/bold yellow]",
        border_style="green",
        padding=(0, 2),
    ))
    log("INFO", f"Backup completed: {backup_name} ({human_size(total_size)})")


def cmd_restore(cfg: dict, backup_name: str = ""):
    print_section("RESTORE", "Restoring your Termux environment from a backup")

    storage = get_storage(cfg)

    console.print("  [bold]Fetching available backups…[/bold]")
    backups = storage.list_backups()

    if not backups:
        console.print("  [red]No backups found in the configured storage.[/red]")
        return

    if not backup_name:
        print_backup_list(backups)

        choice = Prompt.ask("  [bold]Enter backup number or name[/bold]", default="1")
        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(backups):
                console.print(f"  [red]Invalid number. Enter 1–{len(backups)}.[/red]")
                return
            backup_name = backups[idx]["name"]
        except ValueError:
            backup_name = choice

    safe_backup_name = os.path.basename(str(backup_name).replace("\\", "/")).strip()
    if not safe_backup_name or safe_backup_name in (".", "..") or "/" in safe_backup_name:
        console.print(f"  [red]✗ Invalid backup name: {backup_name!r}[/red]")
        return
    backup_name = safe_backup_name

    tmp_dir = Path(os.environ.get("TMPDIR", "/data/data/com.termux/files/usr/tmp")) / f"restore_{backup_name}"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    console.print()
    console.print("  [bold]Step 1/4[/bold]  Downloading backup…")
    t0 = time.monotonic()
    with make_progress(transient=True, percent=True) as progress:
        try:
            storage.download(backup_name, tmp_dir, progress)
        except Exception as e:
            progress.stop()
            console.print(f"  [red]✗ Download failed: {escape(str(e))}[/red]")
            log("ERROR", f"Download failed: {e}")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return
    dl_files = [f for f in tmp_dir.iterdir() if f.is_file()]
    console.print(
        f"  {status_icon(True)} Downloaded {len(dl_files)} files "
        f"[dim]({human_size(sum(f.stat().st_size for f in dl_files))}, "
        f"{fmt_elapsed(time.monotonic() - t0)})[/dim]"
    )

    manifest = read_manifest(tmp_dir)
    if not manifest:
        console.print("  [red]✗ Could not read manifest. Backup may be corrupted.[/red]")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return

    console.print()
    console.print("  [bold]Step 2/4[/bold]  Verifying checksums…")
    all_ok = True
    for key, info in manifest.get("files", {}).items():
        archive = tmp_dir / info["archive"]
        if not archive.exists():
            console.print(f"  [red]✗ Missing archive: {info['archive']}[/red]")
            all_ok = False
            continue
        cs = sha256(archive)
        ok = cs == info.get("checksum", cs)
        icon = status_icon(ok)
        console.print(f"  {icon} {info['archive']}  [dim]{cs[:12]}…[/dim]")
        if not ok:
            all_ok = False

    if not all_ok:
        if not Confirm.ask("  [yellow]Some checksums failed. Continue anyway?[/yellow]"):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return

    console.print()
    console.print(Panel(
        f"[dim]Backup  [/dim] [white]{escape(backup_name)}[/white]\n"
        f"[dim]Date    [/dim] [white]{manifest.get('date', '—')[:19].replace('T', ' ')}[/white]\n"
        f"[dim]Packages[/dim] [white]{len(manifest.get('packages', []))}[/white]\n"
        f"[dim]Archives[/dim] [white]{len(manifest.get('files', {}))}[/white]  "
        f"[dim]({human_size(_backup_size(manifest))})[/dim]",
        title="[bold yellow]Restore Preview[/bold yellow]",
        border_style="yellow",
        padding=(0, 2),
    ))
    console.print("  [yellow]⚠ This will overwrite existing files.[/yellow]")

    if not Confirm.ask("  [bold yellow]Proceed with restore?[/bold yellow]"):
        console.print("  [dim]Restore cancelled.[/dim]")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return

    console.print()
    console.print("  [bold]Step 3/4[/bold]  Extracting archives…")
    with make_progress() as progress:
        # Build the set of destinations this app is actually willing to restore into.
        # Manifest-supplied "source" values are attacker-controlled backup content
        # and must never be trusted as an extraction root — only used to double
        # check they agree with the known-safe root for that item key.
        allowed_roots = {}
        for item_key, _label, item_root in BACKUP_ITEMS:
            if item_root is not None:
                allowed_roots[item_key] = Path(item_root).resolve().parent

        for key, info in manifest.get("files", {}).items():
            archive = tmp_dir / info["archive"]

            src_dir = allowed_roots.get(key)
            if src_dir is None:
                # Unknown key not part of this app's known backup items — refuse
                # to derive a destination from untrusted manifest content.
                console.print(f"  [red]✗ Refusing unknown/untrusted restore target for {key!r}[/red]")
                log("WARNING", f"Refused restore for unknown manifest key: {key!r}")
                continue

            try:
                extract_archive(archive, src_dir, info["archive"], progress)
                log("INFO", f"Extracted {info['archive']} → {src_dir}")
            except Exception as e:
                console.print(f"  [red]✗ Extract failed: {escape(str(e))}[/red]")
                log("ERROR", f"Extract failed for {info['archive']}: {e}")

    pkgs = manifest.get("packages", [])
    if pkgs:
        console.print()
        console.print(f"  [bold]Step 4/4[/bold]  Reinstalling [bold green]{len(pkgs)}[/bold green] packages…")
        install_packages(pkgs, console)
        log("INFO", f"Reinstalled {len(pkgs)} packages")

    shutil.rmtree(tmp_dir, ignore_errors=True)

    console.print()
    console.print(Panel(
        "[bold green]✓ Restore completed successfully![/bold green]\n"
        "Please restart Termux for all changes to take effect.",
        title="[bold yellow]Restore Summary[/bold yellow]",
        border_style="green",
        padding=(0, 2),
    ))
    log("INFO", f"Restore completed from: {backup_name}")


def cmd_list(cfg: dict):
    print_section("BACKUP LIST", f"Storage: {cfg['storage'].upper()}")

    storage = get_storage(cfg)
    backups = storage.list_backups()

    if not backups:
        console.print("  [yellow]No backups found.[/yellow]")
        return

    console.print(f"  [bold yellow]{len(backups)} Backup(s) Found[/bold yellow]\n")

    for i, b in enumerate(backups, 1):
        tbl = Table(
            box=None if is_narrow() else box.ROUNDED,
            show_header=False,
            padding=(0, 1),
            title=f"[bold white]Backup #{i}[/bold white]",
        )
        tbl.add_column("Key",   style="dim cyan",  min_width=12)
        tbl.add_column("Value", style="bold white")

        tbl.add_row("Name",        escape(str(b.get("name", "—"))))
        tbl.add_row("Date",        b.get("date", "—")[:19].replace("T", " "))
        tbl.add_row("Label",       escape(_backup_label(b)) or "—")
        tbl.add_row("Packages",    str(len(b.get("packages", []))))
        tbl.add_row("Files",       str(len(b.get("files", {}))))
        tbl.add_row("Version",     b.get("version", "—"))
        tbl.add_row("Compression", b.get("compression", "—").upper() if b.get("compression") else "—")

        files_info = b.get("files", {})
        if files_info:
            total_sz = sum(v.get("size", 0) for v in files_info.values())
            tbl.add_row("Total size", human_size(total_sz))

        console.print(tbl)
        console.print()


def cmd_delete(cfg: dict, backup_name: str = ""):
    print_section("DELETE BACKUP", f"Storage: {cfg['storage'].upper()}")

    storage = get_storage(cfg)
    backups = storage.list_backups()

    if not backups:
        console.print("  [yellow]No backups found.[/yellow]")
        return

    print_backup_list(backups)

    if not backup_name:
        choice = Prompt.ask("  [bold]Enter backup number or name to delete[/bold]")
        try:
            idx = int(choice) - 1
            if idx < 0 or idx >= len(backups):
                console.print(f"  [red]Invalid number. Enter 1–{len(backups)}.[/red]")
                return
            backup_name = backups[idx]["name"]
        except ValueError:
            backup_name = choice

    console.print(f"\n  [bold red]Backup to be deleted:[/bold red] [white]{backup_name}[/white]")
    if not Confirm.ask("  [bold red]Are you sure? This cannot be undone.[/bold red]", default=False):
        console.print("  [dim]Cancelled.[/dim]")
        return

    try:
        storage.delete_backup(backup_name)
        console.print(f"\n  [bold green]✓ Backup '{backup_name}' deleted successfully.[/bold green]\n")
        log("INFO", f"Deleted backup: {backup_name}")
    except Exception as e:
        console.print(f"\n  [red]✗ Failed to delete backup: {escape(str(e))}[/red]\n")
        log("ERROR", f"Delete failed for {backup_name}: {e}")


def cmd_setup():
    print_banner()
    print_section("SETUP", "Configure termux-sync storage and preferences")

    cfg = load_config()

    console.print("  Choose your [bold]storage backend[/bold]:\n")
    console.print("  [bold cyan][1][/bold cyan]  Local storage   [dim]on device[/dim]")
    console.print("  [bold cyan][2][/bold cyan]  Google Drive    [dim]via rclone[/dim]")
    console.print("  [bold cyan][3][/bold cyan]  GitHub          [dim]private repo[/dim] [bold yellow]★ Recommended[/bold yellow]")
    console.print()

    choice = Prompt.ask("  Storage", choices=["1", "2", "3"], default="3")
    storage_map = {"1": "local", "2": "gdrive", "3": "github"}
    cfg["storage"] = storage_map[choice]

    if cfg["storage"] == "local":
        while True:
            val = Prompt.ask(
                "  Local backup path", default=cfg.get("local_path", str(DEFAULT_DEST))
            ).strip()
            if val:
                cfg["local_path"] = val
                break
            console.print("  [red]✗ Path cannot be empty.[/red]")

    elif cfg["storage"] == "gdrive":
        console.print()
        console.print("  [dim]Make sure rclone is configured with a remote named[/dim] [bold]termux-sync-gdrive[/bold]")
        console.print("  [dim]Run: [/dim][white]rclone config[/white]")
        cfg["gdrive_folder_id"] = Prompt.ask(
            "  Google Drive folder ID (leave blank for root)",
            default=cfg.get("gdrive_folder_id", "")
        )

    elif cfg["storage"] == "github":
        console.print()
        note(
            "[dim]Create a [bold]private repository[/bold] on GitHub and generate a"
            " Personal Access Token with [white]repo[/white] scope.[/dim]"
        )
        console.print("  [dim]Token page:[/dim]")
        console.print("  [white]https://github.com/settings/tokens[/white]", soft_wrap=True)
        console.print()

        existing_token = cfg.get("github_token", "")
        if existing_token:
            note("[dim]A token is already saved. Press Enter to keep it, or paste a new one.[/dim]")
        while True:
            val = Prompt.ask(
                "  GitHub token",
                default=existing_token,
                password=True,
                show_default=False,      # never print a saved token back to the screen
            ).strip()
            if val:
                cfg["github_token"] = val
                break
            console.print("  [red]✗ Token cannot be empty. Paste your Personal Access Token.[/red]")

        while True:
            val = Prompt.ask(
                "  GitHub repo [dim](owner/repo)[/dim]",
                default=cfg.get("github_repo", ""),
                show_default=bool(cfg.get("github_repo", "")),
            ).strip()
            if not val:
                console.print("  [red]✗ Repo cannot be empty. Enter in format: username/repo-name[/red]")
                continue
            if "/" not in val or val.startswith("/") or val.endswith("/"):
                console.print("  [red]✗ Invalid format. Use: username/repo-name  (e.g. djunekz/my-termux-backup)[/red]")
                continue
            cfg["github_repo"] = val
            break

        cfg["github_branch"] = Prompt.ask(
            "  Branch", default=cfg.get("github_branch", "main")
        )

    console.print()
    console.print("  [dim]Compression:  gz = fast · bz2 = balanced · xz = best[/dim]")
    cfg["compression"] = Prompt.ask(
        "  Compression",
        choices=["gz", "bz2", "xz"], default=cfg.get("compression", "gz")
    )
    while True:
        raw = Prompt.ask("  Max backups to keep", default=str(cfg.get("max_backups", 5))).strip()
        if raw.isdigit() and int(raw) >= 1:
            cfg["max_backups"] = int(raw)
            break
        console.print("  [red]✗ Enter a whole number of 1 or more.[/red]")

    console.print()
    current_patterns = cfg.get("exclude_patterns", [])
    preview = ", ".join(current_patterns[:4])
    if len(current_patterns) > 4:
        preview += f" … +{len(current_patterns) - 4} more"
    note(f"[dim]Exclude patterns ({len(current_patterns)}): {escape(preview)}[/dim]")
    if Confirm.ask("  Customise exclude patterns?", default=False):
        console.print()
        console.print(Padding(escape(", ".join(current_patterns)), (0, 0, 0, 4)), style="dim")
        console.print()
        note("[dim]Type the new list separated by commas. Press Enter to keep the list above.[/dim]")
        raw = Prompt.ask("  Patterns", default="", show_default=False)
        if raw.strip():
            cfg["exclude_patterns"] = [p.strip() for p in raw.split(",") if p.strip()]

    save_config(cfg)
    console.print()
    console.print(Panel(
        f"[bold green]✓ Configuration saved![/bold green]\n\n"
        f"[dim]Storage[/dim] [white]{cfg['storage'].upper()}[/white]\n"
        f"[dim]Config [/dim] [white]{escape(short_path(CONFIG_FILE))}[/white]",
        title="[bold yellow]Setup Summary[/bold yellow]",
        border_style="green", padding=(0, 2)
    ))
    log("INFO", f"Setup complete. Storage: {cfg['storage']}")


def load_schedule() -> dict:
    if CRON_FILE.exists():
        with open(CRON_FILE) as f:
            return json.load(f)
    return {"enabled": False, "hour": 2, "minute": 0, "label": "auto"}


def save_schedule(sched: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CRON_FILE, "w") as f:
        json.dump(sched, f, indent=2)


def cmd_schedule():
    print_banner()
    print_section("AUTO-BACKUP", "Schedule automatic backups")

    sched = load_schedule()

    console.print(f"  Current schedule: [bold]{'ENABLED' if sched['enabled'] else 'DISABLED'}[/bold]  "
                  f"@ [cyan]{sched['hour']:02d}:{sched['minute']:02d}[/cyan] daily")
    console.print()

    enable = Confirm.ask("  Enable auto-backup?", default=sched["enabled"])
    sched["enabled"] = enable

    if enable:
        while True:
            try:
                hour = int(Prompt.ask("  Hour (0–23)", default=str(sched["hour"])))
                if 0 <= hour <= 23:
                    break
                console.print("  [red]Please enter a number between 0 and 23.[/red]")
            except ValueError:
                console.print("  [red]Invalid input — please enter a number.[/red]")
        while True:
            try:
                minute = int(Prompt.ask("  Minute (0–59)", default=str(sched["minute"])))
                if 0 <= minute <= 59:
                    break
                console.print("  [red]Please enter a number between 0 and 59.[/red]")
            except ValueError:
                console.print("  [red]Invalid input — please enter a number.[/red]")
        sched["hour"]   = hour
        sched["minute"] = minute
        sched["label"]  = Prompt.ask("  Backup label", default=sched.get("label", "auto"))

    save_schedule(sched)
    _write_daemon_script()

    console.print()
    if enable:
        console.print(Panel(
            f"[bold green]✓ Auto-backup scheduled![/bold green]\n\n"
            f"  Time   : [white]{sched['hour']:02d}:{sched['minute']:02d}[/white] daily\n"
            f"  Label  : [white]{sched['label']}[/white]\n\n"
            f"  [dim]Start daemon with:[/dim]  [white]termux-sync daemon &[/white]\n"
            f"  [dim]Or add to Termux:Boot:[/dim]  [white]~/.termux/boot/start-sync.sh[/white]",
            border_style="green", padding=(1, 2)
        ))
    else:
        console.print("  [yellow]Auto-backup disabled.[/yellow]")

    log("INFO", f"Schedule updated: enabled={enable}, time={sched['hour']:02d}:{sched['minute']:02d}")


def _write_daemon_script():
    boot_dir = Path.home() / ".termux" / "boot"
    boot_dir.mkdir(parents=True, exist_ok=True)
    script = boot_dir / "termux-sync-daemon.sh"
    this_script = Path(os.path.abspath(__file__))
    script.write_text(
        "#!/data/data/com.termux/files/usr/bin/sh\n"
        "# Auto-generated by termux-sync\n"
        f"python3 \"{this_script}\" daemon &\n"
    )
    script.chmod(0o755)


def cmd_daemon(cfg: dict):
    sched = load_schedule()
    if not sched.get("enabled"):
        console.print("[yellow]Auto-backup is not enabled. Run: termux-sync schedule[/yellow]")
        return

    console.print(f"[dim]termux-sync daemon started. Scheduled at "
                  f"{sched['hour']:02d}:{sched['minute']:02d} daily.[/dim]")
    log("INFO", "Daemon started")

    while True:
        now    = datetime.datetime.now()
        target = now.replace(hour=sched["hour"], minute=sched["minute"], second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        sleep_sec = (target - now).total_seconds()
        log("INFO", f"Next backup in {sleep_sec/3600:.1f}h at {target.strftime('%H:%M')}")
        time.sleep(sleep_sec)
        log("INFO", "Auto-backup triggered by daemon")
        cfg = load_config()
        try:
            cmd_backup(cfg, label=sched.get("label", "auto"))
        except Exception as e:
            log("ERROR", f"Daemon backup failed: {e}")


def short_path(p) -> str:
    """Shorten long Termux paths for narrow screens: $PREFIX/bin/tar, ~/.config/..."""
    text   = str(p)
    prefix = os.environ.get("PREFIX", "/data/data/com.termux/files/usr")
    home   = str(Path.home())
    if text == prefix or text.startswith(prefix + "/"):
        return "$PREFIX" + text[len(prefix):]
    if text == home or text.startswith(home + "/"):
        return "~" + text[len(home):]
    return text


def cmd_status(cfg: dict):
    print_section("STATUS", "Current configuration and environment")

    sched = load_schedule()

    cfg_table = Table(box=box.ROUNDED, show_header=False, padding=(0, 1))
    cfg_table.add_column("Key",   style="dim cyan",   no_wrap=True)
    cfg_table.add_column("Value", style="bold white", overflow="fold")

    cfg_table.add_row("Storage backend", cfg.get("storage", "local").upper())
    if cfg["storage"] == "local":
        cfg_table.add_row("Local path",    short_path(cfg.get("local_path", "—")))
    elif cfg["storage"] == "gdrive":
        cfg_table.add_row("Drive folder",  cfg.get("gdrive_folder_id", "(root)") or "(root)")
    elif cfg["storage"] == "github":
        cfg_table.add_row("GitHub repo",   cfg.get("github_repo", "—"))
        cfg_table.add_row("Branch",        cfg.get("github_branch", "main"))
    cfg_table.add_row("Compression",     cfg.get("compression", "gz").upper())
    cfg_table.add_row("Max backups",     str(cfg.get("max_backups", 5)))
    cfg_table.add_row("Auto-backup",     "[green]ENABLED[/green]" if sched.get("enabled") else "[red]DISABLED[/red]")
    if sched.get("enabled"):
        cfg_table.add_row("Schedule",    f"Daily at {sched['hour']:02d}:{sched['minute']:02d}")
    cfg_table.add_row("App version",     f"v{VERSION}")
    for key, path in (("Config file", CONFIG_FILE), ("Log file", LOG_FILE)):
        folder, _, fname = short_path(path).rpartition("/")
        cfg_table.add_row(key, f"{escape(folder)}/\n{escape(fname)}")

    console.print(cfg_table)
    console.print()

    env_table = Table(box=box.ROUNDED, show_header=False, padding=(0, 1),
                      title="[bold yellow]Environment[/bold yellow]")
    env_table.add_column("Tool",   style="dim cyan", no_wrap=True)
    env_table.add_column("",       no_wrap=True, width=1)
    env_table.add_column("Path",   overflow="fold")

    storage = cfg.get("storage", "local")
    checks = [
        ("python3", shutil.which("python3"), True),
        ("dpkg",    shutil.which("dpkg"),    True),
        ("tar",     shutil.which("tar"),     True),
        ("rclone",  shutil.which("rclone"),  storage == "gdrive"),   # only needed for Google Drive
        ("git",     shutil.which("git"),     True),
        ("curl",    shutil.which("curl"),    True),
    ]
    for name, path, needed in checks:
        if path:
            env_table.add_row(name, "[green]✓[/green]", f"[green]{escape(short_path(path))}[/green]")
        elif needed:
            env_table.add_row(name, "[red]✗[/red]", f"[red]missing[/red] [dim]— pkg install {name}[/dim]")
        else:
            env_table.add_row(name, "[dim]–[/dim]", f"[dim]not needed for {storage.upper()}[/dim]")

    console.print(env_table)

    if cfg.get("storage") == "local":
        local_path = Path(cfg.get("local_path", str(DEFAULT_DEST)))
        if local_path.exists():
            try:
                count = sum(1 for d in local_path.iterdir() if d.is_dir())
                console.print()
                console.print(f"  [dim]Stored backups:[/dim] [bold white]{count}[/bold white] "
                               f"[dim]at {local_path}[/dim]")
            except Exception:
                pass


def cmd_logs(lines: int = 40):
    print_section("LOGS", str(LOG_FILE))
    if not LOG_FILE.exists():
        console.print("  [dim]No log file yet.[/dim]")
        return
    all_lines = LOG_FILE.read_text().splitlines()
    if not DEBUG:
        all_lines = [ln for ln in all_lines if "[TRACE]" not in ln]
    log_lines = all_lines[-lines:]
    if not log_lines:
        console.print("  [dim]No log entries.[/dim]")
        return
    if not DEBUG:
        console.print("  [dim]Tip: add --debug to also show saved tracebacks.[/dim]\n")
    for line in log_lines:
        safe = escape(line)
        if "[ERROR]" in line:
            console.print(f"  [red]{safe}[/red]")
        elif "[WARN]" in line:
            console.print(f"  [yellow]{safe}[/yellow]")
        elif "[TRACE]" in line:
            console.print(f"  [dim red]{safe}[/dim red]")
        else:
            console.print(f"  [dim]{safe}[/dim]")


def cmd_clear_logs():
    print_section("CLEAR LOGS", str(LOG_FILE))
    if not LOG_FILE.exists():
        console.print("  [dim]Log file does not exist — nothing to clear.[/dim]\n")
        return

    size = LOG_FILE.stat().st_size
    console.print(f"  Log file : [white]{LOG_FILE}[/white]")
    console.print(f"  Size     : [bold yellow]{human_size(size)}[/bold yellow]\n")

    if not Confirm.ask("  [bold]Clear all log entries?[/bold]", default=False):
        console.print("  [dim]Cancelled.[/dim]\n")
        return

    LOG_FILE.write_text("")
    console.print(f"\n  [bold green]✓ Log file cleared.[/bold green]\n")
    log("INFO", "Log file cleared by user")


def dir_size(path: Path) -> int:
    total = 0
    try:
        for entry in os.scandir(path):
            try:
                if entry.is_symlink():
                    continue
                if entry.is_dir(follow_symlinks=False):
                    total += dir_size(Path(entry.path))
                else:
                    total += entry.stat(follow_symlinks=False).st_size
            except (PermissionError, OSError):
                pass
    except (PermissionError, OSError):
        pass
    return total


def _pct_bar(part: int, total: int, width: int = 24) -> str:
    pct = part / total if total else 0
    filled = int(width * pct)
    color = "green" if pct < 0.5 else ("yellow" if pct < 0.8 else "red")
    return f"[{color}]{'█' * filled}{'░' * (width - filled)}[/{color}] [dim]{pct*100:.1f}%[/dim]"


def cmd_check(target: str = ""):
    print_section("DISK CHECK", "Storage usage overview")

    PREFIX      = Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr"))
    HOME        = Path.home()
    TERMUX_ROOT = Path("/data/data/com.termux/files")

    if not target:
        paths = [
            ("Termux root", TERMUX_ROOT),
            ("Home (~)",    HOME),
            ("$PREFIX",     PREFIX),
        ]
    else:
        t = target.strip()
        if t in ("~", "$HOME", "home"):
            resolved, label = HOME,        "Home (~)"
        elif t in ("$PREFIX", "prefix", "usr"):
            resolved, label = PREFIX,      "$PREFIX"
        elif t in ("/data/data/com.termux/files", "termux", "root"):
            resolved, label = TERMUX_ROOT, "Termux root"
        else:
            resolved = Path(t).expanduser().resolve()
            label    = str(resolved)

        if not resolved.exists():
            console.print(f"  [red]Path not found:[/red] {resolved}\n")
            return
        paths = [(label, resolved)]

    sizes = {}
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as prog:
        for label, path in paths:
            task = prog.add_task(f"[dim]Scanning {label}…", total=None)
            sizes[label] = dir_size(path)
            prog.remove_task(task)

    total_ref = sum(sizes.values()) or 1

    tbl = Table(box=box.ROUNDED, padding=(0, 2), show_header=True)
    tbl.add_column("Location", style="dim cyan",   min_width=16)
    tbl.add_column("Size",     style="bold white", min_width=10, justify="right")
    tbl.add_column("Usage",    min_width=36)

    for label, path in paths:
        sz = sizes[label]
        tbl.add_row(label, human_size(sz), _pct_bar(sz, total_ref))

    console.print(tbl)

    if len(paths) == 1:
        label, path = paths[0]
        _check_subdir_table(path, sizes[label])

    console.print()
    log("INFO", f"check ran on: {[str(p) for _, p in paths]}")


def _check_subdir_table(path: Path, parent_total: int):
    try:
        children = sorted(
            [c for c in path.iterdir() if not c.is_symlink()],
            key=lambda c: dir_size(c) if c.is_dir() else c.stat().st_size,
            reverse=True
        )[:12]
    except PermissionError:
        return

    if not children:
        return

    child_sizes = {}
    with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                  console=console, transient=True) as prog:
        for c in children:
            task = prog.add_task(f"[dim]  {c.name}…", total=None)
            child_sizes[c] = dir_size(c) if c.is_dir() else c.stat().st_size
            prog.remove_task(task)

    console.print()
    sub = Table(box=box.SIMPLE, padding=(0, 2), show_header=True)
    sub.add_column("Name",  style="dim cyan",   min_width=26)
    sub.add_column("Size",  style="bold white", min_width=10, justify="right")
    sub.add_column("Usage", min_width=30)

    for c, sz in sorted(child_sizes.items(), key=lambda x: x[1], reverse=True):
        icon = "📁 " if c.is_dir() else "📄 "
        sub.add_row(icon + c.name, human_size(sz), _pct_bar(sz, parent_total))

    console.print(sub)


CACHE_TARGETS = [
    ("$PREFIX/tmp",         Path(os.environ.get("PREFIX", "/data/data/com.termux/files/usr")) / "tmp"),
    ("~/.cache",            Path.home() / ".cache"),
    ("~/.npm",              Path.home() / ".npm"),
    ("~/.cargo/registry",   Path.home() / ".cargo" / "registry"),
    ("~/.cargo/git",        Path.home() / ".cargo" / "git"),
    ("~/__pycache__",       Path.home() / "__pycache__"),
    ("~/.gradle/caches",    Path.home() / ".gradle" / "caches"),
    ("~/.m2/repository",    Path.home() / ".m2" / "repository"),
    ("~/go/pkg/mod/cache",  Path.home() / "go" / "pkg" / "mod" / "cache"),
]


def cmd_clear_cache():
    print_section("CLEAR CACHE", "Remove temporary and cached files")

    existing = []
    for label, path in CACHE_TARGETS:
        if path.exists():
            size = dir_size(path)
            existing.append((label, path, size))

    if not existing:
        console.print("  [green]Nothing to clear — all cache directories are already empty.[/green]\n")
        return

    tbl = Table(box=box.ROUNDED, padding=(0, 2))
    tbl.add_column("#",               style="dim",        width=4)
    tbl.add_column("Cache directory", style="cyan",       min_width=20)
    tbl.add_column("Size",            style="bold white", min_width=10, justify="right")

    total_size = 0
    for i, (label, path, size) in enumerate(existing, 1):
        tbl.add_row(str(i), label, human_size(size))
        total_size += size

    console.print(tbl)
    console.print(f"\n  Total reclaimable: [bold yellow]{human_size(total_size)}[/bold yellow]\n")

    console.print("  [dim]Enter numbers to clear (comma-separated), or press Enter to select all:[/dim]")
    raw_choice = Prompt.ask("  Target (e.g. 1,3 or Enter=all)", default="")
    if raw_choice.strip():
        try:
            indices  = [int(x.strip()) - 1 for x in raw_choice.split(",") if x.strip()]
            selected = [existing[i] for i in indices if 0 <= i < len(existing)]
        except (ValueError, IndexError):
            console.print("  [red]Invalid selection. Aborting.[/red]\n")
            return
    else:
        selected = existing

    if not selected:
        console.print("  [yellow]No targets selected.[/yellow]\n")
        return

    first = Confirm.ask("  [bold]Proceed with clearing cache?[/bold]", default=False)
    if not first:
        console.print("\n  [yellow]Aborted.[/yellow]\n")
        return

    console.print()
    console.print("  [bold yellow]The following will be permanently deleted:[/bold yellow]\n")
    for label, path, size in selected:
        console.print(f"    [red]✗[/red]  {label}  [dim]({human_size(size)})[/dim]")
    console.print()

    second = Confirm.ask("  [bold red]Are you sure? This cannot be undone.[/bold red]", default=False)
    if not second:
        console.print("\n  [yellow]Aborted.[/yellow]\n")
        return

    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as prog:
        cleared = 0
        for label, path, size in selected:
            task = prog.add_task(f"[cyan]Clearing {label}…", total=None)
            try:
                if path.is_dir():
                    for child in path.iterdir():
                        try:
                            if child.is_dir() and not child.is_symlink():
                                shutil.rmtree(child)
                            else:
                                child.unlink(missing_ok=True)
                        except Exception as e:
                            log("WARN", f"Could not remove {child}: {escape(str(e))}")
                prog.update(task, total=1, completed=1,
                            description=f"[green]{label} cleared ({human_size(size)}) ✓")
                cleared += size
                log("INFO", f"Cleared cache: {path} ({human_size(size)})")
            except Exception as e:
                prog.update(task, total=1, completed=1,
                            description=f"[red]{label} failed: {e}")
                log("ERROR", f"Failed to clear {path}: {e}")

    console.print()
    console.print(f"  [bold green]Done![/bold green] Freed approximately [bold]{human_size(cleared)}[/bold]\n")


def cmd_export_config(output_path: str = ""):
    print_section("EXPORT CONFIG", "Save configuration to a file")

    cfg = load_config()

    safe_cfg = dict(cfg)
    if safe_cfg.get("github_token"):
        safe_cfg["github_token"] = "*** REDACTED ***"
    if safe_cfg.get("encrypt_password"):
        safe_cfg["encrypt_password"] = "*** REDACTED ***"

    if not output_path:
        output_path = Prompt.ask(
            "  Save to file",
            default=str(Path.home() / "termux-sync-config-export.json")
        )

    out = Path(output_path).expanduser()
    with open(out, "w") as f:
        json.dump(safe_cfg, f, indent=2)

    console.print(f"\n  [bold green]✓ Configuration exported to:[/bold green] [white]{out}[/white]\n")
    console.print("  [yellow]⚠ Token and password fields have been redacted from the export.[/yellow]\n")
    log("INFO", f"Config exported to {out}")


def cmd_import_config(input_path: str = ""):
    print_section("IMPORT CONFIG", "Load configuration from a file")

    if not input_path:
        input_path = Prompt.ask("  Path to config file")

    src = Path(input_path).expanduser()
    if not src.exists():
        raise UserError(str(src), hint="Check the path and try again.", title="File not found")

    try:
        with open(src) as f:
            new_cfg = json.load(f)
    except json.JSONDecodeError as e:
        raise UserError(
            f"{src}\nLine {e.lineno}, column {e.colno}: {e.msg}",
            hint="Make sure the file is a valid JSON export from [bold]termux-sync export-config[/bold].",
            title="Not a valid JSON file",
        ) from e

    existing = load_config()

    for k, v in new_cfg.items():
        if isinstance(v, str) and "REDACTED" in v:
            continue
        existing[k] = v

    if existing.get("compression") not in ("gz", "bz2", "xz"):
        existing["compression"] = "gz"

    save_config(existing)
    console.print(f"\n  [bold green]✓ Configuration imported from:[/bold green] [white]{src}[/white]\n")
    log("INFO", f"Config imported from {src}")


# ───────────────────────── Command line ─────────────────────────
COMMAND_GROUPS = [
    ("Backup & Restore", [
        ("backup",        "Create a new backup"),
        ("restore",       "Restore from a backup"),
        ("list",          "List all available backups"),
        ("delete",        "Delete a specific backup"),
    ]),
    ("Configuration", [
        ("setup",         "Interactive configuration wizard"),
        ("schedule",      "Configure auto-backup schedule"),
        ("daemon",        "Run background scheduler (used by Termux:Boot)"),
        ("export-config", "Export config to a file (tokens redacted)"),
        ("import-config", "Import config from a file"),
    ]),
    ("Maintenance", [
        ("status",        "Show current config and environment"),
        ("logs",          "Show recent log entries"),
        ("clear-logs",    "Clear / reset the log file"),
        ("check",         "Show disk usage (~, $PREFIX, or a custom path)"),
        ("clear-cache",   "Remove temporary and cached files"),
        ("help",          "Show this help"),
    ]),
]
COMMANDS = [name for _, items in COMMAND_GROUPS for name, _ in items]

OPTIONS = [
    ("-l, --label LABEL", "Label for this backup"),
    ("-n, --name NAME",   "Backup name to restore / delete"),
    ("--lines N",         "Lines to show in logs (default 40)"),
    ("--debug",           "Show the full traceback if something fails"),
    ("-v, --version",     "Print version and exit"),
    ("-h, --help",        "Show this help"),
]

EXAMPLES = [
    ("termux-sync setup",                              "first-time configuration"),
    ("termux-sync backup --label before-new-phone",    "create a labelled backup"),
    ("termux-sync list",                               "see all backups"),
    ("termux-sync restore",                            "pick a backup to restore"),
    ("termux-sync delete --name <backup-name>",        "delete a specific backup"),
    ("termux-sync logs --lines 100",                   "show the last 100 log lines"),
    ("termux-sync check ~",                            "disk usage of your home"),
    ("termux-sync import-config <file>",               "load a config file"),
]

# Commands people commonly try that live elsewhere.
COMMAND_HINTS = {
    "update":  "termux-sync has no built-in update command. Use [bold]tsctl updater[/bold] to update.",
    "upgrade": "To update, use [bold]tsctl updater[/bold].",
    "install": "To install or reinstall, use the install script, or [bold]tsctl[/bold].",
    "remove":  "To delete a backup use [bold]termux-sync delete[/bold]. To uninstall the tool use [bold]tsctl uninstall[/bold].",
    "config":  "Use [bold]termux-sync setup[/bold] to change settings, or [bold]termux-sync status[/bold] to view them.",
    "sync":    "Use [bold]termux-sync backup[/bold] to upload, or [bold]termux-sync restore[/bold] to download.",
}


def print_help():
    print_banner()
    console.print(f"  [bold]Usage:[/bold]  termux-sync [cyan]<command>[/cyan] [dim]{escape('[target] [options]')}[/dim]")
    console.print()

    for group, items in COMMAND_GROUPS:
        table = Table(box=None, show_header=False, padding=(0, 2), pad_edge=False)
        table.add_column(style="bold cyan", no_wrap=True)
        table.add_column()
        for name, desc in items:
            table.add_row(name, escape(desc))
        console.print(f"  [bold yellow]{group}[/bold yellow]")
        console.print(Padding(table, (0, 0, 1, 2)))

    table = Table(box=None, show_header=False, padding=(0, 2), pad_edge=False)
    table.add_column(style="green", no_wrap=True)
    table.add_column()
    for flag, desc in OPTIONS:
        table.add_row(escape(flag), escape(desc))
    console.print("  [bold yellow]Options[/bold yellow]")
    console.print(Padding(table, (0, 0, 1, 2)))

    console.print("  [bold yellow]Examples[/bold yellow]")
    for cmd, _ in EXAMPLES:
        console.print(f"    [dim]$[/dim] [white]{escape(cmd)}[/white]", soft_wrap=True)
    console.print()


class FriendlyParser(argparse.ArgumentParser):
    """argparse, but errors are shown as a tidy panel instead of a usage dump."""

    def error(self, message):
        m = re.search(r"invalid choice: '([^']*)'", message)
        if m:
            bad = m.group(1)
            hint_lines = []
            if bad in COMMAND_HINTS:
                hint_lines.append(COMMAND_HINTS[bad])
            close = [] if bad in COMMAND_HINTS else difflib.get_close_matches(bad, COMMANDS, n=3, cutoff=0.6)
            if close:
                hint_lines.append("Did you mean:  " + "   ".join(f"[bold cyan]{c}[/bold cyan]" for c in close))
            hint_lines.append("Run [bold]termux-sync help[/bold] to see all commands.")
            print_error("Unknown command", f"'{bad}' is not a termux-sync command.", "\n\n".join(hint_lines))
        else:
            nice = message.replace("argument --lines/", "--lines").replace("argument ", "")
            print_error("Invalid usage", nice,
                        "Run [bold]termux-sync help[/bold] to see the correct usage.")
        sys.exit(2)


def build_parser() -> argparse.ArgumentParser:
    parser = FriendlyParser(prog="termux-sync", add_help=False)
    parser.add_argument("command", nargs="?", default="help", choices=COMMANDS, metavar="command")
    parser.add_argument("target", nargs="?", default="")
    parser.add_argument("--label", "-l", default="")
    parser.add_argument("--name",  "-n", default="")
    parser.add_argument("--lines", default=40, type=int)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--version", "-v", action="store_true")
    parser.add_argument("--help", "-h", action="store_true")
    return parser


def _abort():
    console.print()
    console.print(
        Panel(
            "[bold yellow]Operation cancelled[/bold yellow]\n\n"
            "  You pressed [bold]Ctrl+C[/bold] — termux-sync was stopped.\n"
            "  [dim]Any partial temporary files have been cleaned up.[/dim]\n\n"
            "  Run the command again whenever you're ready.",
            border_style="yellow",
            padding=(1, 2),
            expand=False,
        )
    )
    sys.exit(130)


def main(argv=None):
    global DEBUG
    args = build_parser().parse_args(argv)
    DEBUG = DEBUG or args.debug

    if args.version:
        print(f"termux-sync v{VERSION}")
        return

    if args.help or args.command in (None, "help"):
        print_help()
        return

    try:
        cfg = load_config()
        handlers = {
            "setup":         lambda: cmd_setup(),
            "backup":        lambda: cmd_backup(cfg, label=args.label),
            "restore":       lambda: cmd_restore(cfg, backup_name=args.name),
            "list":          lambda: cmd_list(cfg),
            "delete":        lambda: cmd_delete(cfg, backup_name=args.name),
            "schedule":      lambda: cmd_schedule(),
            "daemon":        lambda: cmd_daemon(cfg),
            "status":        lambda: cmd_status(cfg),
            "logs":          lambda: cmd_logs(args.lines),
            "clear-logs":    lambda: cmd_clear_logs(),
            "check":         lambda: cmd_check(args.target or ""),
            "clear-cache":   lambda: cmd_clear_cache(),
            "export-config": lambda: cmd_export_config(args.target or ""),
            "import-config": lambda: cmd_import_config(args.target or ""),
        }
        handlers[args.command]()
    except KeyboardInterrupt:
        _abort()
    except Exception as exc:
        handle_crash(exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
