# Changelog

All notable changes to termux-sync will be documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Version numbers follow [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

### Planned

- Archive encryption using a user-provided password
- Selective restore (restore individual components instead of the full backup)
- Backup rotation by date in addition to count-based pruning
- Support for rclone remotes beyond Google Drive

---

## [1.1.1] - 2026-04-30

### Added

- Support installing with pypi `pip install termux-sync`

### Fixed

- Banner no longer appears on every command — it now shows only on `help`, `setup`, and `schedule` (interactive menus); all other commands (`backup`, `restore`, `list`, `status`, `logs`, `check`, `clear-cache`) proceed directly to output without the banner

---

## [1.1.0] - 2026-04-28

### Added

- `termux-sync check` — disk usage overview for Termux root, `~`, and `$PREFIX`; accepts an optional path argument (`check ~`, `check $PREFIX`, `check /custom/path`) with per-subfolder size breakdown
- `termux-sync clear-cache` — interactive cache cleaner with two confirmation prompts before removing `$PREFIX/tmp`, `~/.cache`, `~/.npm`, `~/.cargo/registry`, and `~/.cargo/git`
- `tsctl status` — show current installation status (script path, launcher, config directory, commit hash)
- PyPI packaging support — `termux-sync` can now be installed via `pip install termux-sync` using the new `pyproject.toml`
- GitHub Actions workflows: `ci.yml`, `codeql.yml`, `dependabot.yml`, `release-pypi.yml`
- Automated PyPI publish on GitHub release via OIDC trusted publishing

### Changed

- GitHub storage chunk size increased from 20 MB to 200 MB per part, reducing the number of split files for large backups
- `_write_daemon_script()` now resolves the script path dynamically using `__file__` instead of a hardcoded path — fixes daemon boot script when installed via `tsctl`
- `tsctl install` now purges stale `termux-sync` aliases from `.bashrc` / `.zshrc` before writing the launcher, preventing conflicts with previous installations
- `tsctl` shell configuration step no longer adds an alias — the `$PREFIX/bin` launcher is sufficient

### Fixed

- `termux-sync check` previously reported total Android filesystem size instead of Termux directory sizes
- Stale alias from a previous install overriding the correct launcher in active shell sessions
- Daemon boot script pointing to hardcoded development path (`~/files/project/termux-sync/termux-sync.py`)

---

## [1.0.0] - 2026-04-18

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
