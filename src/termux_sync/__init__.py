#!/usr/bin/env python3
"""
OPENSOURCE

termux-sync — Termux Backup & Restore Tool
==========================================
Backup and restore your entire Termux environment across devices.
Supports Local, Google Drive, and GitHub (private repo) storage.
"""

import os
import sys
import json
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
    from rich.table import Table
    from rich.prompt import Prompt, Confirm
    from rich.text import Text
    from rich import box
    from rich.live import Live
    from rich.columns import Columns
    from rich.rule import Rule
    from rich.syntax import Syntax
    from rich.align import Align
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

VERSION       = "1.2.3"
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
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            data.setdefault(k, v)
        return data
    return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


console = Console()


def print_banner():
    console.print(
        Align.center(
            f"[bold green]{BANNER}[/bold green]"))
    console.print(
        Align.center(
            f"[dim]Version: [/dim][bold white]v{VERSION}[/bold white]\n"
            f"[dim]Source: [/dim][bold white]https://github.com/djunekz/termux-sync[/bold white]\n"
            " • [dim]Termux Backup & Restore[/dim]\n"
            " • [dim]Opensource & License MIT[/dim]"
        )
    )
    console.print()


def print_section(title: str, subtitle: str = ""):
    console.print()
    console.print(Rule(f"[bold yellow]  {title}  [/bold yellow]", style="yellow dim"))
    if subtitle:
        console.print(f"  [dim]{subtitle}[/dim]")
    console.print()


def status_icon(ok: bool) -> str:
    return "[bold green]✓[/bold green]" if ok else "[bold red]✗[/bold red]"


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


def install_packages(pkg_list: list[str], console: Console):
    if not pkg_list:
        console.print("  [yellow]No packages to install.[/yellow]")
        return
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Installing packages…", total=len(pkg_list))
        for pkg in pkg_list:
            try:
                subprocess.run(
                    ["pkg", "install", "-y", pkg],
                    capture_output=True, check=True
                )
            except Exception:
                pass
            progress.advance(task)


def create_archive(
    source_path: Path,
    archive_path: Path,
    compression: str,
    excludes: list[str],
    label: str,
    progress: Progress,
) -> Path:
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
        with tarfile.open(out, mode) as tf:
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
            console.print("[red]rclone not found. Install: pkg install rclone[/red]")
            sys.exit(1)

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
            console.print("[red]GitHub token and repo are required. Run: termux-sync setup[/red]")
            sys.exit(1)

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
            body = e.read().decode()
            raise RuntimeError(f"GitHub API error {e.code}: {body}") from e

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
            except (urllib.error.URLError, OSError, ConnectionError) as e:
                last_err = e
                wait = 15 * (attempt + 1)
                progress.update(progress_task,
                    description=f"[yellow]Retry {attempt+1}/{self.MAX_RETRIES} ({local_path.name})...")
                _time.sleep(wait)
            except urllib.error.HTTPError as e:
                body = e.read().decode()
                if e.code == 422:
                    progress.update(progress_task, completed=file_size,
                                    description=f"[yellow]{local_path.name} already uploaded, skipping")
                    return {}
                raise RuntimeError(f"Asset upload failed {e.code}: {body}") from e

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
                    asset_task = progress.add_task(
                        f"[cyan]{chunk.name}...", total=chunk.stat().st_size
                    )
                    self._upload_one_asset(release_id, chunk, asset_task, progress)
                    progress.update(asset_task, description=f"[green]{chunk.name} done")
        finally:
            shutil.rmtree(tmp_split, ignore_errors=True)

        progress.update(task, description="[green]Uploaded to GitHub Releases")
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
                "label": rel.get("name", tag),
            })
        return backups

    def download(self, backup_name: str, dest: Path, progress: Progress):
        import urllib.request, re as _re, time as _time
        release = self._get_release_by_tag(backup_name)
        if not release:
            raise RuntimeError(f"No GitHub Release found for tag: {backup_name}")
        assets = sorted(release.get("assets", []), key=lambda a: a["name"])
        dest.mkdir(parents=True, exist_ok=True)

        dl_task = progress.add_task("[cyan]Downloading from GitHub...", total=len(assets))

        for asset in assets:
            url  = self._asset_url(asset["id"])
            out  = dest / asset["name"]
            size = asset.get("size", 0)
            f_task = progress.add_task(f"[cyan]{asset['name']}...", total=max(size, 1))
            last_err = None
            for attempt in range(8):
                try:
                    req = urllib.request.Request(url, headers=self._asset_headers())
                    with urllib.request.urlopen(req, timeout=120) as r:
                        data = r.read()
                    out.write_bytes(data)
                    progress.update(f_task, completed=size,
                                    description=f"[green]{asset['name']} done")
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    progress.update(f_task,
                        description=f"[yellow]Retry {attempt+1}/8 ({asset['name']})...")
                    _time.sleep(15 * (attempt + 1))
            if last_err:
                raise RuntimeError(
                    f"Failed to download {asset['name']} after 8 attempts: {last_err}"
                )
            progress.advance(dl_task)

        chunk_re = _re.compile(r"^(.+)\.part(\d{4})$")
        groups: dict = {}
        for f in sorted(dest.iterdir()):
            m = chunk_re.match(f.name)
            if m:
                groups.setdefault(m.group(1), []).append(f)

        if groups:
            assemble_task = progress.add_task(
                "[cyan]Reassembling chunks...", total=len(groups)
            )
            for original_name, parts in groups.items():
                parts.sort(key=lambda p: p.name)
                out_file = dest / original_name
                with open(out_file, "wb") as fout:
                    for part in parts:
                        fout.write(part.read_bytes())
                        part.unlink()
                progress.update(assemble_task,
                    description=f"[green]Reassembled {original_name}",
                    advance=1)
            progress.update(assemble_task, description="[green]Chunks reassembled")

        progress.update(dl_task, description="[green]Downloaded from GitHub")

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

    compression = cfg.get("compression", "gz")
    if compression not in ("gz", "bz2", "xz"):
        console.print(f"  [yellow]⚠ Compression '{compression}' is invalid, falling back to 'gz'.[/yellow]")
        compression = "gz"

    excludes = cfg.get("exclude_patterns", [])
    storage  = get_storage(cfg)

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
    console.print("  [bold]Step 2/4[/bold]  Archiving directories…")
    console.print()

    with Progress(
        SpinnerColumn(),
        TextColumn("  {task.description}"),
        BarColumn(bar_width=30),
        TextColumn("[dim]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console,
        expand=False,
    ) as progress:
        archive_items = [
            ("home",    "Home directory (~)",       TERMUX_FILES),
            ("usr_etc", "Termux config (/usr/etc)", TERMUX_HOME / "etc"),
        ]
        for key, label_text, src in archive_items:
            if not src.exists():
                console.print(f"  [yellow]⚠ Skipping {src} (not found)[/yellow]")
                continue
            out_path = tmp_dir / f"{key}.tar.{compression}"
            try:
                actual_out = create_archive(src, out_path, compression, excludes, label_text, progress)
                checksum = sha256(actual_out)
                meta["files"][key] = {
                    "archive":  actual_out.name,
                    "size":     actual_out.stat().st_size,
                    "checksum": checksum,
                    "source":   str(src),
                }
                log("INFO", f"Archived {src} → {actual_out.name} ({human_size(actual_out.stat().st_size)})")
            except Exception as e:
                console.print(f"  [red]✗ Failed to archive {src}: {e}[/red]")
                log("ERROR", f"Archive failed for {src}: {e}")

    console.print()
    console.print("  [bold]Step 3/4[/bold]  Writing manifest…")
    write_manifest(tmp_dir, meta)
    console.print(f"  {status_icon(True)} Manifest written")

    console.print()
    console.print(f"  [bold]Step 4/4[/bold]  Uploading to [bold cyan]{cfg['storage'].upper()}[/bold cyan]…")
    console.print()

    location = ""
    with Progress(
        SpinnerColumn(),
        TextColumn("  {task.description}"),
        BarColumn(bar_width=30),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        try:
            location = storage.upload(tmp_dir, backup_name, progress)
            storage.delete_old(cfg.get("max_backups", 5))
        except KeyboardInterrupt:
            _cleanup_tmp()
            raise
        except Exception as e:
            console.print(f"  [red]✗ Upload failed: {e}[/red]")
            log("ERROR", f"Upload failed: {e}")
            _cleanup_tmp()
            return

    shutil.rmtree(tmp_dir, ignore_errors=True)

    total_size = sum(v["size"] for v in meta["files"].values())

    console.print()
    console.print(Panel(
        f"[bold green]✓ Backup completed successfully![/bold green]\n\n"
        f"  [dim]Name      :[/dim]  [white]{backup_name}[/white]\n"
        f"  [dim]Date      :[/dim]  [white]{meta['date'][:19].replace('T', ' ')}[/white]\n"
        f"  [dim]Packages  :[/dim]  [white]{len(pkgs)}[/white]\n"
        f"  [dim]Total size:[/dim]  [white]{human_size(total_size)}[/white]\n"
        f"  [dim]Storage   :[/dim]  [white]{cfg['storage'].upper()}[/white]\n"
        f"  [dim]Location  :[/dim]  [white]{location}[/white]",
        title="[bold yellow]  Backup Summary  [/bold yellow]",
        border_style="green",
        padding=(1, 2),
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
        table = Table(
            box=box.ROUNDED,
            title="[bold yellow]Available Backups[/bold yellow]",
            show_header=True,
            header_style="bold cyan",
            padding=(0, 1),
        )
        table.add_column("#",        style="dim",        width=4)
        table.add_column("Name",     style="bold white",  min_width=30)
        table.add_column("Date",     style="green")
        table.add_column("Label",    style="yellow")
        table.add_column("Packages", style="cyan",       justify="right")
        table.add_column("Storage",  style="blue")

        for i, b in enumerate(backups, 1):
            table.add_row(
                str(i),
                b.get("name", "—"),
                b.get("date", "—")[:19].replace("T", " "),
                b.get("label", "") or "—",
                str(len(b.get("packages", []))),
                b.get("storage", cfg["storage"]).upper(),
            )

        console.print(table)
        console.print()

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
    with Progress(
        SpinnerColumn(),
        TextColumn("  {task.description}"),
        BarColumn(bar_width=30),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        try:
            storage.download(backup_name, tmp_dir, progress)
        except Exception as e:
            console.print(f"  [red]✗ Download failed: {e}[/red]")
            log("ERROR", f"Download failed: {e}")
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return

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
        console.print(f"  {icon} {info['archive']}  [dim]{cs[:16]}…[/dim]")
        if not ok:
            all_ok = False

    if not all_ok:
        if not Confirm.ask("  [yellow]Some checksums failed. Continue anyway?[/yellow]"):
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return

    console.print()
    console.print(Panel(
        f"  [bold]About to restore:[/bold]\n\n"
        f"  Backup   : [white]{backup_name}[/white]\n"
        f"  Date     : [white]{manifest.get('date', '—')[:19].replace('T', ' ')}[/white]\n"
        f"  Packages : [white]{len(manifest.get('packages', []))}[/white]\n"
        f"  Archives : [white]{len(manifest.get('files', {}))}[/white]",
        title="[bold yellow]  Restore Preview  [/bold yellow]",
        border_style="yellow",
        padding=(1, 2),
    ))

    if not Confirm.ask("\n  [bold yellow]Proceed with restore? This will overwrite existing files.[/bold yellow]"):
        console.print("  [dim]Restore cancelled.[/dim]")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return

    console.print()
    console.print("  [bold]Step 3/4[/bold]  Extracting archives…")
    with Progress(
        SpinnerColumn(),
        TextColumn("  {task.description}"),
        BarColumn(bar_width=30),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
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
                console.print(f"  [red]✗ Extract failed: {e}[/red]")
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
        "[bold green]✓ Restore completed successfully![/bold green]\n\n"
        "  Please restart Termux for all changes to take effect.",
        title="[bold yellow]  Restore Summary  [/bold yellow]",
        border_style="green",
        padding=(1, 2),
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
            box=box.ROUNDED,
            show_header=False,
            padding=(0, 2),
            title=f"[bold white]Backup #{i}[/bold white]",
        )
        tbl.add_column("Key",   style="dim cyan",  min_width=20)
        tbl.add_column("Value", style="bold white")

        tbl.add_row("Name",        b.get("name", "—"))
        tbl.add_row("Date",        b.get("date", "—")[:19].replace("T", " "))
        tbl.add_row("Label",       b.get("label", "") or "—")
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

    table = Table(
        box=box.ROUNDED,
        title="[bold yellow]Available Backups[/bold yellow]",
        show_header=True,
        header_style="bold cyan",
        padding=(0, 1),
    )
    table.add_column("#",     style="dim",        width=4)
    table.add_column("Name",  style="bold white",  min_width=30)
    table.add_column("Date",  style="green")
    table.add_column("Label", style="yellow")

    for i, b in enumerate(backups, 1):
        table.add_row(
            str(i),
            b.get("name", "—"),
            b.get("date", "—")[:19].replace("T", " "),
            b.get("label", "") or "—",
        )

    console.print(table)
    console.print()

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
        console.print(f"\n  [red]✗ Failed to delete backup: {e}[/red]\n")
        log("ERROR", f"Delete failed for {backup_name}: {e}")


def cmd_setup():
    print_banner()
    print_section("SETUP", "Configure termux-sync storage and preferences")

    cfg = load_config()

    console.print("  Choose your [bold]storage backend[/bold]:\n")
    console.print("  [bold cyan][1][/bold cyan]  Local storage  (saves on device)")
    console.print("  [bold cyan][2][/bold cyan]  Google Drive   (via rclone)")
    console.print("  [bold cyan][3][/bold cyan]  GitHub         (private repository) [bold yellow]★ Recommended[/bold yellow]")
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
        console.print(
            "  [dim]Create a [bold]private repository[/bold] on GitHub and generate a"
            " Personal Access Token with [white]repo[/white] scope.[/dim]"
        )
        console.print("  [dim]Token URL:[/dim] [white]https://github.com/settings/tokens[/white]")
        console.print()

        existing_token = cfg.get("github_token", "")
        if existing_token:
            console.print("  [dim]A token is already saved. Press Enter to keep it, or paste a new one.[/dim]")
        while True:
            val = Prompt.ask(
                "  GitHub Personal Access Token",
                default=existing_token,
                password=True,
            ).strip()
            if val:
                cfg["github_token"] = val
                break
            console.print("  [red]✗ Token cannot be empty. Paste your Personal Access Token.[/red]")

        while True:
            val = Prompt.ask(
                "  GitHub repo (owner/repo)", default=cfg.get("github_repo", "")
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
    cfg["compression"] = Prompt.ask(
        "  Compression (gz=fast, bz2=balanced, xz=best)",
        choices=["gz", "bz2", "xz"], default=cfg.get("compression", "gz")
    )
    cfg["max_backups"] = int(Prompt.ask(
        "  Max backups to keep", default=str(cfg.get("max_backups", 5))
    ))

    console.print()
    current_patterns = cfg.get("exclude_patterns", [])
    preview = ", ".join(current_patterns[:5]) + ("…" if len(current_patterns) > 5 else "")
    console.print(f"  [dim]Current exclude patterns: {preview}[/dim]")
    if Confirm.ask("  Customise exclude patterns?", default=False):
        console.print("  [dim]Enter patterns separated by commas (leave blank to keep defaults):[/dim]")
        raw = Prompt.ask("  Patterns", default=",".join(current_patterns))
        if raw.strip():
            cfg["exclude_patterns"] = [p.strip() for p in raw.split(",") if p.strip()]

    save_config(cfg)
    console.print()
    console.print(Panel(
        f"[bold green]✓ Configuration saved![/bold green]\n\n"
        f"  Config file: [white]{CONFIG_FILE}[/white]\n"
        f"  Storage    : [white]{cfg['storage'].upper()}[/white]",
        border_style="green", padding=(1, 2)
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


def cmd_status(cfg: dict):
    print_section("STATUS", "Current configuration and environment")

    sched = load_schedule()

    cfg_table = Table(box=box.ROUNDED, show_header=False, padding=(0, 2))
    cfg_table.add_column("Key",   style="dim cyan",   min_width=20)
    cfg_table.add_column("Value", style="bold white")

    cfg_table.add_row("Storage backend", cfg.get("storage", "local").upper())
    if cfg["storage"] == "local":
        cfg_table.add_row("Local path",    cfg.get("local_path", "—"))
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
    cfg_table.add_row("Config file",     str(CONFIG_FILE))
    cfg_table.add_row("Log file",        str(LOG_FILE))

    console.print(cfg_table)
    console.print()

    env_table = Table(box=box.ROUNDED, show_header=False, padding=(0, 2),
                      title="[bold yellow]Environment[/bold yellow]")
    env_table.add_column("Tool",   style="dim cyan", min_width=20)
    env_table.add_column("Status")

    checks = [
        ("python3", shutil.which("python3")),
        ("dpkg",    shutil.which("dpkg")),
        ("tar",     shutil.which("tar")),
        ("rclone",  shutil.which("rclone")),
        ("git",     shutil.which("git")),
        ("curl",    shutil.which("curl")),
    ]
    for name, path in checks:
        if path:
            env_table.add_row(name, f"[green]✓ {path}[/green]")
        else:
            env_table.add_row(name, "[red]✗ not found[/red]")

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
    log_lines = LOG_FILE.read_text().splitlines()[-lines:]
    for line in log_lines:
        if "[ERROR]" in line:
            console.print(f"  [red]{line}[/red]")
        elif "[WARN]" in line:
            console.print(f"  [yellow]{line}[/yellow]")
        else:
            console.print(f"  [dim]{line}[/dim]")


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
                            log("WARN", f"Could not remove {child}: {e}")
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
        console.print(f"  [red]File not found: {src}[/red]\n")
        return

    try:
        with open(src) as f:
            new_cfg = json.load(f)
    except json.JSONDecodeError as e:
        console.print(f"  [red]Invalid JSON file: {e}[/red]\n")
        return

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


def ensure_dependencies():
    try:
        import rich
    except ImportError:
        print("Installing required Python packages (rich)…")
        subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "rich"], check=True)
        print("Done. Please re-run termux-sync.")
        sys.exit(0)


def main():
    ensure_dependencies()

    parser = argparse.ArgumentParser(
        prog="termux-sync",
        description="Termux Backup & Restore — sync your environment across devices",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Commands:
  backup         Create a new backup
  restore        Restore from a backup
  list           List all available backups
  delete         Delete a specific backup
  setup          Interactive configuration wizard
  schedule       Configure auto-backup schedule
  daemon         Run background scheduler (called by Termux:Boot)
  status         Show current config and environment
  logs           Show recent log entries
  clear-logs     Clear / reset the log file
  check          Show disk usage (check ~, $PREFIX, or a custom path)
  clear-cache    Remove temporary and cached files
  export-config  Export config to a file (tokens redacted)
  import-config  Import config from a file

Examples:
  termux-sync setup
  termux-sync backup --label "before-new-phone"
  termux-sync list
  termux-sync restore
  termux-sync delete
  termux-sync delete --name termux_backup_20240501_120000
  termux-sync schedule
  termux-sync status
  termux-sync logs --lines 100
  termux-sync clear-logs
  termux-sync check
  termux-sync check ~
  termux-sync check $PREFIX
  termux-sync clear-cache
  termux-sync export-config
  termux-sync import-config ~/termux-sync-config-export.json
        """,
    )
    parser.add_argument("command", nargs="?", default="help",
                        choices=["backup", "restore", "list", "delete", "setup", "schedule",
                                 "daemon", "status", "logs", "clear-logs", "check",
                                 "clear-cache", "export-config", "import-config", "help"])
    parser.add_argument("target",  nargs="?", default="",  help="Optional path for check / import-config")
    parser.add_argument("--label",   "-l", default="",    help="Label for this backup")
    parser.add_argument("--name",    "-n", default="",    help="Backup name to restore / delete")
    parser.add_argument("--lines",         default=40, type=int, help="Lines to show in logs")
    parser.add_argument("--version", "-v", action="store_true",  help="Print version and exit")

    args = parser.parse_args()

    if args.version:
        print(f"termux-sync v{VERSION}")
        return

    if args.command == "help" or args.command is None:
        print_banner()
        parser.print_help()
        return

    cfg = load_config()

    try:
        if args.command == "setup":
            cmd_setup()
        elif args.command == "backup":
            cmd_backup(cfg, label=args.label)
        elif args.command == "restore":
            cmd_restore(cfg, backup_name=args.name)
        elif args.command == "list":
            cmd_list(cfg)
        elif args.command == "delete":
            cmd_delete(cfg, backup_name=args.name)
        elif args.command == "schedule":
            cmd_schedule()
        elif args.command == "daemon":
            cmd_daemon(cfg)
        elif args.command == "status":
            cmd_status(cfg)
        elif args.command == "logs":
            cmd_logs(args.lines)
        elif args.command == "clear-logs":
            cmd_clear_logs()
        elif args.command == "check":
            cmd_check(args.target or "")
        elif args.command == "clear-cache":
            cmd_clear_cache()
        elif args.command == "export-config":
            cmd_export_config(args.target or "")
        elif args.command == "import-config":
            cmd_import_config(args.target or "")
    except KeyboardInterrupt:
        _abort()


def _abort():
    console.print()
    console.print()
    console.print(
        Panel(
            "[bold yellow]Operation cancelled[/bold yellow]\n\n"
            "  You pressed [bold]Ctrl+C[/bold] — termux-sync was stopped.\n"
            "  [dim]Any partial temporary files have been cleaned up.[/dim]\n\n"
            "  Run the command again whenever you're ready.",
            border_style="yellow",
            padding=(1, 2),
        )
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
