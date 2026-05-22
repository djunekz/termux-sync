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

## [1.2.1] - 2026-05-22

### Fixed

- **`setup` — required fields accepted empty input silently** — pressing Enter on the `GitHub Personal Access Token` and `GitHub repo (owner/repo)` prompts passed through an empty string, which would later cause a crash or silent failure when actually running a backup or restore. Both fields are now validated in a loop that keeps prompting until a non-empty value is provided, with a descriptive error message on each failed attempt.
  - `github_token`: re-prompts with `✗ Token cannot be empty. Paste your Personal Access Token.`
  - `github_repo`: re-prompts with `✗ Invalid format. Use: username/repo-name` if empty or if the value does not contain exactly one `/` in a valid position
  - `local_path`: re-prompts with `✗ Path cannot be empty.` if the user clears the default and submits nothing
- **`setup` — existing token not acknowledged** — when a GitHub token was already saved in config, the password prompt showed an empty field with no indication that a value already existed. A hint line is now printed before the prompt: `A token is already saved. Press Enter to keep it, or paste a new one.`
- **`KeyboardInterrupt` traceback instead of clean exit** — pressing Ctrl+C during any interactive prompt (e.g. `setup`, `schedule`, `restore`, `delete`) printed a full Python traceback instead of the intended cancellation panel. The root cause was that the `try/except KeyboardInterrupt` block only wrapped `main()` inside `if __name__ == "__main__"`, which is never executed when the script is invoked via a pip entry point or the tsctl launcher. The handler has been moved inside `main()` itself so it fires regardless of invocation method. The panel logic was extracted into a dedicated `_abort()` helper and `if __name__ == "__main__"` simplified to a bare `main()` call.

---

## [1.2.0] - 2026-05-22

### Added

- `termux-sync delete` — interactively list and permanently delete a specific backup; works across all three storage backends (local, Google Drive, GitHub Releases); requires double confirmation before deletion
- `termux-sync clear-logs` — truncate the log file at `~/.config/termux-sync/sync.log` after a single confirmation prompt
- `termux-sync export-config` — export current configuration to a JSON file with `github_token` and `encrypt_password` fields automatically redacted
- `termux-sync import-config <file>` — import configuration from a previously exported file; REDACTED placeholder values are silently skipped so live credentials are never overwritten
- `clear-cache` selective targeting — users can now enter a comma-separated list of cache directory numbers to clear only specific entries instead of always clearing all at once
- Additional cache targets for `clear-cache`: `~/__pycache__`, `~/.gradle/caches`, `~/.m2/repository`, `~/go/pkg/mod/cache`
- Backup manifest now records the `version` field (termux-sync version that created the backup)
- `termux-sync list` now displays `Version`, `Compression`, and `Total size` columns per backup entry
- `termux-sync status` now shows the stored backup count and path when using local storage
- `termux-sync check` table now includes a `Location` column header so each row is clearly labelled
- `GDriveStorage.delete_backup()` — new method to delete a single named backup folder from Google Drive via `rclone purge`
- `GitHubStorage.delete_backup()` — new method to delete a single GitHub Release and its associated tag
- `LocalStorage.delete_backup()` — new method to delete a single local backup directory

### Fixed

- **`create_archive()` — broken output path for files without double extensions** — the original `with_suffix().with_suffix()` chain produced incorrect filenames (e.g. `home.tar` instead of `home.tar.gz`). Replaced with a strip-then-append approach that correctly handles any input path.
- **`create_archive()` — no compression validation** — if `cfg["compression"]` held an unrecognised value, `tarfile.open()` raised an obscure low-level exception. Compression is now validated against `{"gz", "bz2", "xz"}` and silently falls back to `gz` with a warning.
- **`extract_archive()` — Python 3.12 deprecation** — `tf.extract(member, ..., set_attrs=True)` is deprecated in Python 3.12+. The fallback path now correctly uses `set_attrs=False` instead of repeating the same deprecated call.
- **`human_size()` — float input crash** — repeated `/= 1024` inside the loop converted the value to a `float`, but the function signature typed the parameter as `int`. Added an `int()` cast at entry to prevent downstream type errors.
- **`cmd_restore()` — `IndexError` on out-of-range backup number** — entering `0`, a negative number, or a number larger than the backup count raised an unhandled `IndexError`. The input is now validated against the list length with a user-friendly error message.
- **`cmd_restore()` — temp directory leaked on early exit** — on manifest read failure or when the user rejected the checksum-failure prompt, the temporary download directory was left on disk. Now cleaned up on all early-return code paths.
- **`cmd_schedule()` — crash on non-integer hour/minute input** — `int(Prompt.ask(...))` raised `ValueError` on non-numeric input. Both fields are now validated in a loop that keeps prompting until a valid value is entered.
- **`GDriveStorage.delete_old()` — was a no-op** — the method body contained only `pass`, meaning old backups on Google Drive were never pruned regardless of the `max_backups` setting. Now correctly calls `rclone purge` on entries beyond `max_keep`.
- **`LocalStorage.download()` — no existence check** — attempting to restore a backup that did not exist on disk would silently fail during the `iterdir()` call instead of raising a clear error. Now raises `FileNotFoundError` with the full path before any I/O is attempted.
- **`LocalStorage.list_backups()` and `delete_old()` — unhandled `PermissionError`** — `iterdir()` could raise `PermissionError` on restricted directories. Both methods now catch the exception and return gracefully.
- **`cmd_daemon()` — config not reloaded between scheduled runs** — the daemon captured `cfg` at startup and reused the same object for every subsequent backup cycle. Changes made via `termux-sync setup` required restarting the daemon to take effect. The daemon now calls `load_config()` before each backup run.
- **`cmd_backup()` — archive checksum recorded against wrong filename** — when `create_archive()` corrected the output path, the caller still referenced the uncorrected `out_path` name in the manifest. The manifest now uses the path actually returned by `create_archive()`.
- **`load_config()` — missing forward-compatibility for new keys** — configs saved by older versions lacked new default keys. `load_config()` now applies `setdefault()` for every key in `DEFAULT_CONFIG` so all fields are always present.

### Changed

- Version bumped from `1.1.2` → `1.2.0` in `termux-sync.py`, `src/termux_sync/__init__.py`, and `pyproject.toml`
- `cmd_list()` backup table title changed from `Files Backup - N` to `Backup #N` for consistency

---

## [1.1.2] - 2026-05-13

### Fixed

- Remove urls in authors pyproject.toml - use project.urls
- Error _tmp in `tsctl`
- `install.sh` - bugs sync local and release version
- `tsctl` - verified official repo
- `install.sh` - verified install from official repo

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
