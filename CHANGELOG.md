# Changelog

All notable changes to termux-sync will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Version numbers follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Planned

- Single installation using pypi `pip install termux-sync`
- Archive encryption using a user-provided password
- Selective restore (restore individual components instead of the full backup)
- Backup rotation by date in addition to count-based pruning
- Support for rclone remotes beyond Google Drive

---

## [1.0.0] - 2026-04-16

Initial public release.

### Added

- `termux-sync backup` — creates a full backup of packages, home directory, `/usr/etc`, and shared libraries
- `termux-sync restore` — interactive backup picker with SHA-256 integrity verification before extraction
- `termux-sync list` — table view of all available backups with size and date
- `termux-sync setup` — interactive configuration wizard for storage backend and credentials
- `termux-sync schedule` — configure a daily auto-backup at a user-defined time
- `termux-sync daemon` — background process that triggers scheduled backups
- `termux-sync status` — shows current configuration and environment tool availability
- `termux-sync logs` — displays recent log entries with color coding by level
- Storage backend support: local filesystem, Google Drive (via rclone), GitHub private repository
- Backup manifest (`manifest.json`) with checksums, package list, timestamp, and source paths
- Compression options: `gz` (fast), `bz2` (balanced), `xz` (best compression)
- Default exclusion patterns for cache directories, build artifacts, and media files
- Configurable maximum backup count with automatic pruning of oldest backups
- Persistent log file at `~/.config/termux-sync/sync.log`
- Rich terminal UI with progress bars, panels, and tables
- `install.sh` — local installer for manual setup from a cloned repository
- `tsctl` — control tool for system-wide install, update, and uninstall via git clone
- Termux:Boot integration via auto-generated daemon script at `~/.termux/boot/termux-sync-daemon.sh`
- Graceful handling of Ctrl+C with cleanup of partial temporary files
- Auto-install of `rich` dependency if not present on first run
