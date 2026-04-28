# termux-sync

Backup and restore your entire Termux environment across devices.

[![Python 3.8+](https://img.shields.io/badge/python-3.8%2B-blue?style=flat-square)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)
[![Termux](https://img.shields.io/badge/Termux-compatible-brightgreen?style=flat-square)](https://termux.dev)

termux-sync captures your installed packages, home directory, and configuration files into a portable backup that can be fully restored on any device. Backups can be stored locally, uploaded to Google Drive via rclone, or pushed to a private GitHub repository.

---

## Features

| Feature | Description |
|---|---|
| Full backup | Packages, home directory, `/usr/etc` config, shared libraries |
| Full restore | Archive extraction and package reinstallation in one command |
| Local storage | Save backups on-device or to any mounted path |
| Google Drive | Upload and retrieve via rclone |
| GitHub private repo | Push and pull using a Personal Access Token (200 MB per part) |
| Auto-backup | Built-in daily scheduler at a configurable time |
| Disk check | View storage usage for any path with per-folder breakdown |
| Cache cleaner | Interactive two-step confirmation before removing cache |
| Checksum verification | SHA-256 integrity check performed on every restore |
| Rich terminal UI | Colored progress bars, tables, and status panels |
| Persistent logging | Full log written to `~/.config/termux-sync/sync.log` |

---

## Requirements

```
Python 3.8+
python-pip
tar (included in Termux)
```

Optional dependencies depending on which storage backend you use:

- `rclone` — required for Google Drive (`pkg install rclone`)
- `git` — required for GitHub storage (`pkg install git`)
- `Termux:Boot` — required for auto-backup on device start (install from F-Droid)

---

## Installation

### Option 1 — tsctl (recommended)

`tsctl` is the control tool that handles installation, updates, and removal. It clones the repository to a stable location and sets up the `termux-sync` command system-wide.

```bash
curl -fsSL https://raw.githubusercontent.com/djunekz/termux-sync/main/tsctl -o tsctl
chmod +x tsctl
bash tsctl install
```

> After installation, you can run `termux-sync` from anywhere

### Option 2 — Manual (git clone)

```bash
pkg install python python-pip
git clone https://github.com/djunekz/termux-sync ~/termux-sync
cd ~/termux-sync
pip install rich
bash install.sh
```

> After installation, you can run `termux-sync` from anywhere

---

## Setup

Run the interactive setup wizard before using termux-sync for the first time:

```bash
termux-sync setup
```

The wizard will ask you to choose a storage backend and provide any required credentials.

### GitHub private repo (recommended)

1. Create a private GitHub repository, for example `my-termux-backup`
2. Go to Settings > Developer Settings > Personal Access Tokens > Tokens (classic)
3. Generate a token with the `repo` scope
4. Run `termux-sync setup` and select option 3 (GitHub)
5. Enter your token and repository name in the format `username/repo`

---

## Command Usage

### Run the setup wizard
```bash
termux-sync setup
```

### Create a backup
```bash
termux-sync backup
termux-sync backup --label "before-new-phone"
```

### List all available backups
```bash
termux-sync list
```

### Restore from backup (interactive picker)
```bash
termux-sync restore
```

### Restore a specific backup by name
```bash
termux-sync restore --name termux_backup_20240415_143000
```

### Configure daily auto-backup
```bash
termux-sync schedule
```

### Check configuration and environment
```bash
termux-sync status
```

### View recent log entries
```bash
termux-sync logs
termux-sync logs --lines 100
```

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

Removes: `$PREFIX/tmp`, `~/.cache`, `~/.npm`, `~/.cargo/registry`, `~/.cargo/git`

> Two confirmation prompts before anything is deleted.

---

## Auto-Backup

Configure a daily automatic backup:

```bash
termux-sync schedule
```

To run automatically when your device boots, install [Termux:Boot](https://f-droid.org/en/packages/com.termux.boot/) from F-Droid. The setup wizard writes the required boot script automatically:

### View the generated boot script
```bash
cat ~/.termux/boot/termux-sync-daemon.sh
```
Or start the daemon manually in the current session

```bash
termux-sync daemon &
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

You can add or remove exclusions in `~/.config/termux-sync/config.json`.

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
| `compression` | `gz` | Compression type: `gz` (fast), `bz2` (balanced), `xz` (best) |
| `max_backups` | `5` | Maximum number of backups to keep before pruning |
| `encrypt` | `false` | Enable archive encryption (not yet implemented) |

---

## Backup Structure

Each backup is a directory containing four files:

```
backups/
└── termux_backup_20240415_143000/
    ├── manifest.json       metadata, checksums, package list, source paths
    ├── packages.txt        plain text package list for reference
    ├── home.tar.gz         home directory archive
    └── usr_etc.tar.gz      Termux config archive (/usr/etc)
```

The `manifest.json` file is read by the restore command to verify archive integrity via SHA-256 checksums before extracting anything.

---

## Migrating to a New Device

On the old device, create a labeled backup:

```bash
termux-sync backup --label "migration"
```

### On the new device, install termux-sync and restore:

Download and run tsctl
```bash
curl -fsSL https://raw.githubusercontent.com/djunekz/termux-sync/main/tsctl -o tsctl
chmod +x tsctl
bash tsctl install
```

Run setup with the same credentials as the old device
```bash
termux-sync setup
```

Restore the latest backup
```bash
termux-sync restore
```

The restore process will verify checksums, extract the archives, and reinstall all packages.

---

## Troubleshooting

| Problem | Solution |
|---|---|
| `rclone not found` | Run `pkg install rclone` then `rclone config` to authenticate |
| GitHub 401 error | Check that your token has the `repo` scope and has not expired |
| Archive too large | Add paths to `exclude_patterns` in `config.json` |
| Restore overwrites wrong path | Check the `source` field in the backup's `manifest.json` |
| `termux-sync: command not found` | Run `tsctl install` or re-run `install.sh` |
| Daemon does not start on boot | Verify that Termux:Boot is installed and has permission to run |
| GitHub upload fails on large backup | Default chunk is 200 MB per part — add paths to `exclude_patterns` to reduce size |
| Cache not cleared | Run `termux-sync clear-cache` and confirm both prompts |

---

## Project Structure

```
termux-sync/
├── termux-sync.py    Main application (backup, restore, schedule, daemon, check, clear-cache)
├── install.sh        Local installer for manual setup
├── tsctl             Control tool (install, updater, uninstall, status via git clone)
└── README.md         This file
```

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING](CONTRIBUTING.md) before opening a pull request.

For bug reports and feature requests, use the GitHub issue tracker and follow the provided templates.

---

## License

MIT License. See [LICENSE](LICENSE) for the full text.
