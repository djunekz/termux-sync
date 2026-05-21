# termux-sync

Backup and restore your entire Termux environment across devices.

[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue?badge.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?badge.svg)](LICENSE)
[![Termux](https://img.shields.io/badge/Termux-compatible-brightgreen?badge.svg)](https://termux.dev)
[![Release to PyPI](https://github.com/djunekz/termux-sync/actions/workflows/release-pypi.yml/badge.svg?branch=main)](https://github.com/djunekz/termux-sync/actions/workflows/release-pypi.yml)

termux-sync captures your installed packages, home directory, and configuration files into a portable backup that can be fully restored on any device. Backups can be stored locally, uploaded to Google Drive via rclone, or pushed to a private GitHub repository.

---

## Features

| Feature | Description |
|---|---|
| Full backup | Packages, home directory, `/usr/etc` config, shared libraries |
| Full restore | Archive extraction and package reinstallation in one command |
| Delete backup | Remove a specific backup from any storage backend |
| Local storage | Save backups on-device or to any mounted path |
| Google Drive | Upload and retrieve via rclone |
| GitHub private repo | Push and pull using a Personal Access Token (200 MB per part) |
| Auto-backup | Built-in daily scheduler at a configurable time |
| Disk check | View storage usage for any path with per-folder breakdown |
| Cache cleaner | Selective or full cache removal with two-step confirmation |
| Log viewer | Color-coded log output with configurable line count |
| Clear logs | Truncate the log file in one command |
| Export config | Save configuration to a portable file (tokens redacted) |
| Import config | Load configuration from a previously exported file |
| Checksum verification | SHA-256 integrity check performed on every restore |
| Rich terminal UI | Colored progress bars, tables, and status panels |
| Persistent logging | Full log written to `~/.config/termux-sync/sync.log` |

---

## Requirements

```
Python 3.9+
python-pip
tar (included in Termux)
```

Optional dependencies depending on which storage backend you use:

- `rclone` — required for Google Drive (`pkg install rclone`)
- `git` — required for GitHub storage (`pkg install git`)
- `Termux:Boot` — required for auto-backup on device start (install from F-Droid)

---

## Installation

### Option 1 — PyPI

```bash
pip install rich
pip install termux-sync
```

> After installation, run `termux-sync` from anywhere.

### Option 2 — tsctl (recommended)

`tsctl` is the control tool that handles installation, updates, and removal. It downloads the latest release from GitHub and sets up the `termux-sync` command system-wide.

```bash
curl -fsSL https://raw.githubusercontent.com/djunekz/termux-sync/main/tsctl -o tsctl
chmod +x tsctl
bash tsctl install
```

> After installation, run `termux-sync` from anywhere.

### Option 3 — Manual (git clone)

```bash
pkg install python python-pip
git clone https://github.com/djunekz/termux-sync ~/termux-sync
cd ~/termux-sync
pip install rich
bash install.sh
```

> After installation, run `termux-sync` from anywhere.

---

## Setup

Run the interactive setup wizard before using termux-sync for the first time:

```bash
termux-sync setup
```

The wizard will ask you to choose a storage backend and provide any required credentials. You can also optionally customise the exclude patterns during setup.

### GitHub private repo (recommended)

1. Create a private GitHub repository, for example `my-termux-backup`
2. Go to **Settings → Developer Settings → Personal Access Tokens → Tokens (classic)**
3. Generate a token with the `repo` scope
4. Run `termux-sync setup` and select option **3 (GitHub)**
5. Enter your token and repository name in the format `username/repo`

---

## Command Reference

### Backup

```bash
termux-sync backup
termux-sync backup --label "before-new-phone"
```

### Restore

```bash
termux-sync restore                                          # interactive picker
termux-sync restore --name termux_backup_20240415_143000    # restore specific backup
```

### List all backups

```bash
termux-sync list
```

Displays name, date, label, package count, compression, version, and total size for each backup.

### Delete a backup

```bash
termux-sync delete                                          # interactive picker
termux-sync delete --name termux_backup_20240415_143000     # delete specific backup
```

Requires confirmation before deletion. Works with local, Google Drive, and GitHub storage.

### Setup wizard

```bash
termux-sync setup
```

### Schedule daily auto-backup

```bash
termux-sync schedule
```

### Check configuration and environment

```bash
termux-sync status
```

Shows storage backend, compression, schedule, app version, available tools, and (for local storage) the number of stored backups.

### View log entries

```bash
termux-sync logs
termux-sync logs --lines 100
```

### Clear log file

```bash
termux-sync clear-logs
```

Truncates `~/.config/termux-sync/sync.log` after a single confirmation prompt.

### Check disk usage

```bash
termux-sync check                              # overview: Termux root, ~, $PREFIX
termux-sync check ~                            # home directory + subfolder breakdown
termux-sync check $PREFIX                      # $PREFIX + subfolder breakdown
termux-sync check /data/data/com.termux/files  # custom path
```

### Clear cache

```bash
termux-sync clear-cache
```

Lists all detected cache directories with sizes. You can clear all of them or select specific entries by number. Two confirmation prompts are shown before anything is deleted.

Targets: `$PREFIX/tmp`, `~/.cache`, `~/.npm`, `~/.cargo/registry`, `~/.cargo/git`, `~/__pycache__`, `~/.gradle/caches`, `~/.m2/repository`, `~/go/pkg/mod/cache`

### Export configuration

```bash
termux-sync export-config
termux-sync export-config ~/my-backup-config.json
```

Saves the current configuration to a JSON file. `github_token` and `encrypt_password` are automatically redacted before writing.

### Import configuration

```bash
termux-sync import-config ~/my-backup-config.json
```

Loads configuration from a previously exported file. REDACTED placeholder values are skipped so existing credentials are never overwritten.

### Background daemon

```bash
termux-sync daemon &
```

Run as a background process — triggered automatically by the Termux:Boot script written by `termux-sync schedule`.

---

## Auto-Backup

Configure a daily automatic backup:

```bash
termux-sync schedule
```

To run automatically when your device boots, install [Termux:Boot](https://f-droid.org/en/packages/com.termux.boot/) from F-Droid. The schedule wizard writes the required boot script automatically:

```bash
cat ~/.termux/boot/termux-sync-daemon.sh   # view generated boot script
termux-sync daemon &                        # or start the daemon manually
```

---

## What Gets Backed Up

| Component | Path | Description |
|---|---|---|
| Package list | `dpkg --get-selections` | All installed packages |
| Home directory | `~` | Dotfiles, scripts, projects |
| Termux config | `$PREFIX/etc` | sources.list, motd, and other config files |
| Shared libraries | `$PREFIX/lib` | Libraries installed by Termux packages |

The following paths are excluded from the home directory backup by default:

`.cache`, `.npm`, `__pycache__`, `node_modules`, `.gradle`, `.android`, `.thumbnails`, `DCIM`, `Movies`, `Music`, `.local/share/Trash`, `.local/lib`, `.java`, `.m2`, `.ivy2`, `go/pkg`, `.rustup/toolchains`, `.cargo/registry`, `.cargo/git`

You can customise exclusions in `~/.config/termux-sync/config.json` or interactively during `termux-sync setup`.

---

## Configuration File

Location: `~/.config/termux-sync/config.json`

```json
{
  "storage": "github",
  "local_path": "~/termux-backups",
  "gdrive_folder_id": "",
  "github_token": "ghp_...",
  "github_repo": "username/my-termux-backup",
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
  "encrypt": false,
  "encrypt_password": ""
}
```

| Key | Default | Description |
|---|---|---|
| `storage` | `local` | Storage backend: `local`, `gdrive`, or `github` |
| `local_path` | `~/termux-backups` | Path for local backups |
| `gdrive_folder_id` | *(empty)* | Google Drive folder ID (leave empty for root) |
| `github_token` | *(empty)* | GitHub Personal Access Token with `repo` scope |
| `github_repo` | *(empty)* | Repository in `owner/repo` format |
| `github_branch` | `main` | Branch to push backups to |
| `compression` | `gz` | Compression: `gz` (fast), `bz2` (balanced), `xz` (best) |
| `exclude_patterns` | *(list)* | Paths excluded from home directory archive |
| `max_backups` | `5` | Maximum number of backups to keep before pruning |
| `encrypt` | `false` | Enable archive encryption (planned feature) |

---

## Backup Structure

Each backup is a directory containing:

```
backups/
└── termux_backup_20240415_143000/
    ├── manifest.json       metadata, checksums, package list, source paths, version
    ├── packages.txt        plain-text package list for reference
    ├── home.tar.gz         home directory archive
    └── usr_etc.tar.gz      Termux config archive (/usr/etc)
```

`manifest.json` records the termux-sync version, compression type, per-archive SHA-256 checksums, and source paths. The restore command reads this file to verify integrity before extracting anything.

---

## Migrating to a New Device

**On the old device** — create a labeled backup:

```bash
termux-sync backup --label "migration"
```

**On the new device** — install termux-sync and restore:

```bash
# Download and install tsctl
curl -fsSL https://raw.githubusercontent.com/djunekz/termux-sync/main/tsctl -o tsctl
chmod +x tsctl
bash tsctl install

# Configure with the same credentials as the old device
termux-sync setup

# Restore the latest backup
termux-sync restore
```

The restore process verifies checksums, extracts the archives, and reinstalls all packages automatically.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `rclone not found` | Run `pkg install rclone` then `rclone config` to authenticate |
| GitHub 401 error | Check that your token has the `repo` scope and has not expired |
| Archive too large | Add paths to `exclude_patterns` in `config.json`, or use `clear-cache` first |
| Restore overwrites wrong path | Check the `source` field in the backup's `manifest.json` |
| `termux-sync: command not found` | Run `tsctl install` or re-run `install.sh` |
| Daemon does not start on boot | Verify Termux:Boot is installed from F-Droid and opened at least once |
| GitHub upload fails on large backup | Add paths to `exclude_patterns` to reduce backup size |
| Cache not cleared | Run `termux-sync clear-cache` and confirm both prompts |
| Config lost after reinstall | Use `export-config` before uninstalling; `import-config` after reinstalling |
| Old backups not pruned on GDrive | Fixed in v1.2.0 — update with `tsctl updater` |

---

## Project Structure

```
termux-sync/
├── termux-sync.py          Main application
├── src/termux_sync/
│   └── __init__.py         PyPI package entry point (mirrors termux-sync.py)
├── install.sh              Local installer for manual setup
├── tsctl                   Control tool (install, updater, uninstall, status)
├── pyproject.toml          PyPI package configuration
├── CHANGELOG.md            Version history
├── FAQ.md                  Frequently asked questions
└── README.md               This file
```

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING](CONTRIBUTING.md) before opening a pull request.

For bug reports and feature requests, use the GitHub issue tracker and follow the provided templates.

---

## License

MIT License. See [LICENSE](LICENSE) for the full text.
