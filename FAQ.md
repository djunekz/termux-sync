# Frequently Asked Questions

---

## Installation

**How do I install termux-sync?**

The recommended method is to use `tsctl`, the control tool:

```bash
curl -fsSL https://raw.githubusercontent.com/djunekz/termux-sync/main/tsctl -o tsctl
chmod +x tsctl
./tsctl install
```

This downloads the latest release from GitHub and registers the `termux-sync` command system-wide. After installation, you can discard the downloaded `tsctl` file — a copy is installed at `$PREFIX/bin/tsctl`.

**Can I install termux-sync without internet access?**

Yes. Clone or download the repository manually, then run `bash install.sh` from the project directory. All dependencies (`python`, `python-pip`, `rich`) need to be available through the Termux package manager or already installed.

**What does `tsctl install` put on my device?**

The release script is placed at `$PREFIX/lib/termux-sync/termux-sync.py`. A launcher script is written to `$PREFIX/bin/termux-sync` so the command is available everywhere. Nothing is written outside of the Termux prefix and your home directory.

**How do I update termux-sync?**

```bash
tsctl updater
```

This fetches the latest release from GitHub, verifies its SHA-256 checksum, and refreshes the launcher.

**How do I uninstall termux-sync?**

```bash
tsctl uninstall
```

This removes the launcher, install directory, config directory, and any shell aliases. Your backup archives are not deleted.

**What Python version is required?**

Python 3.9 or later. The only third-party dependency is `rich`, which is installed automatically on first run if missing.

---

## Storage Backends

**Which storage backend should I use?**

GitHub private repository is recommended for most users. It is reliable, free for private repositories, and makes it straightforward to restore on any new device. Local storage is useful if you prefer to keep data entirely on-device or on a mounted drive. Google Drive requires rclone to be configured and is better suited to users who already use rclone for other purposes.

**How do I set up GitHub storage?**

1. Create a private GitHub repository.
2. Generate a Personal Access Token with the `repo` scope at **Settings → Developer Settings → Personal Access Tokens → Tokens (classic)**.
3. Run `termux-sync setup` and choose option 3.
4. Enter your token and repository name in `username/repo` format.

**What rclone remote name does termux-sync expect for Google Drive?**

termux-sync uses a remote named `termux-sync-gdrive`. Run `rclone config` and create a remote with exactly that name. The `gdrive_folder_id` in your config narrows the upload to a specific folder within that Drive; leave it empty to use the root.

**Can I switch storage backends after the initial setup?**

Yes. Run `termux-sync setup` again and choose a different backend. Existing backups in the old location are not moved automatically — use `termux-sync list` on the old backend first to note what you have, then switch.

**How do I move my config to a new device?**

Run `termux-sync export-config` on the old device to save a sanitised copy of your configuration (tokens are redacted). Transfer the file to the new device, then run `termux-sync import-config <file>`. Re-enter any credentials that were redacted by running `termux-sync setup` afterwards.

---

## Backup and Restore

**What exactly gets backed up?**

Four components are archived: the installed package list (via `dpkg --get-selections`), your home directory (`~`), the Termux configuration directory (`$PREFIX/etc`), and shared libraries (`$PREFIX/lib`).

**How large will my backup be?**

It depends on what is in your home directory. The default exclusion list removes common large directories such as `.cache`, `node_modules`, `.cargo/registry`, `.rustup/toolchains`, and media folders. A typical Termux environment with a few development tools usually produces a backup between 50 MB and 300 MB.

**How do I reduce the backup size?**

Add paths to `exclude_patterns` in `~/.config/termux-sync/config.json`. You can edit the file directly or customise patterns interactively during `termux-sync setup`. Running `termux-sync clear-cache` before a backup also helps by removing build caches before they are archived.

**How many backups are kept?**

The `max_backups` setting in your config controls this. The default is 5. When a new backup is created and the count exceeds this limit, the oldest backup is deleted automatically. For Google Drive, this pruning was broken before v1.2.0 — update with `tsctl updater` if you are on an older version.

**How does restore work?**

Running `termux-sync restore` shows an interactive list of available backups. After you select one, SHA-256 checksums from the manifest are verified against the actual archives before any extraction takes place. If verification passes, the archives are extracted and packages are reinstalled.

**How do I delete a backup I no longer need?**

```bash
termux-sync delete
```

This shows an interactive list of backups and asks for confirmation before deleting. You can also target a specific backup directly:

```bash
termux-sync delete --name termux_backup_20240415_143000
```

Deletion works across all storage backends (local, Google Drive, GitHub Releases).

**Can I restore individual files instead of the full backup?**

Not through termux-sync directly. You can extract specific files manually from the archive:

```bash
tar -tzf ~/termux-backups/termux_backup_TIMESTAMP/home.tar.gz | grep filename
tar -xzf ~/termux-backups/termux_backup_TIMESTAMP/home.tar.gz path/to/file
```

**What does the manifest.json contain?**

Each backup includes a `manifest.json` with the backup name, creation timestamp, label, storage backend, compression type, termux-sync version, per-archive SHA-256 checksums, source paths, and the full list of installed packages.

**What happens if restore fails partway through?**

termux-sync verifies checksums before extracting. If a checksum fails, extraction does not begin. If the process is interrupted after extraction starts, the partially restored state may be inconsistent. In that case, run `termux-sync restore` again with the same backup to complete the process, or choose a different backup.

---

## Auto-Backup

**How do I set up automatic backups?**

Run `termux-sync schedule` and enter the time you want the daily backup to run. Then either start the daemon manually (`termux-sync daemon &`) or install Termux:Boot from F-Droid to have it start automatically on device boot.

**Where is the Termux:Boot script written?**

At `~/.termux/boot/termux-sync-daemon.sh`. This script is generated automatically when you run `termux-sync schedule`.

**Does the daemon pick up config changes without a restart?**

Yes, as of v1.2.0. The daemon reloads `~/.config/termux-sync/config.json` before each scheduled backup run, so changes made via `termux-sync setup` take effect at the next backup without needing to restart the daemon.

**The daemon is not running after a reboot. What is wrong?**

Make sure Termux:Boot is installed from F-Droid (not Google Play) and that you have opened the Termux:Boot app at least once to grant it the required permissions. Check that the boot script exists at `~/.termux/boot/termux-sync-daemon.sh`.

---

## Configuration

**Where is the config file?**

At `~/.config/termux-sync/config.json`. You can edit it directly with any text editor or regenerate it by running `termux-sync setup`.

**Where are the logs?**

At `~/.config/termux-sync/sync.log`. View them in-app with `termux-sync logs` or read the file directly:

```bash
cat ~/.config/termux-sync/sync.log
```

**How do I clear the log file?**

```bash
termux-sync clear-logs
```

This truncates the file after a single confirmation prompt. A new entry recording the clear action is written immediately after.

**What compression format should I use?**

`gz` is the default and is fast enough for most use cases. Use `bz2` for a balance of speed and size. Use `xz` if storage space is the primary concern and you do not mind slower backup times.

**How do I back up my termux-sync configuration itself?**

```bash
termux-sync export-config ~/termux-sync-config-export.json
```

This writes a sanitised copy of your config (tokens and passwords redacted) to the specified path. Store it somewhere safe — for example, upload it to cloud storage or note your credentials separately. To restore it on a new device:

```bash
termux-sync import-config ~/termux-sync-config-export.json
termux-sync setup   # re-enter any credentials that were redacted
```

**What happens if I have an old config file without newer keys?**

termux-sync automatically fills in missing keys with their default values when loading a config created by an older version. You will never get a crash due to a missing key.

---

## Cache Cleaning

**What directories does `clear-cache` target?**

| Directory | Contents |
|---|---|
| `$PREFIX/tmp` | Termux temporary files |
| `~/.cache` | General application cache |
| `~/.npm` | npm package cache |
| `~/.cargo/registry` | Rust crate registry cache |
| `~/.cargo/git` | Rust git dependency cache |
| `~/__pycache__` | Python bytecode cache |
| `~/.gradle/caches` | Gradle build cache |
| `~/.m2/repository` | Maven local repository cache |
| `~/go/pkg/mod/cache` | Go module download cache |

**Can I clear only specific cache directories?**

Yes. When you run `termux-sync clear-cache`, the tool lists all detected directories with their sizes. You can enter a comma-separated list of numbers to select only the ones you want to clear (for example `1,3,5`). Press Enter with no input to select all.

**Is it safe to clear `$PREFIX/tmp`?**

Generally yes, as long as no Termux processes are actively using files in that directory. Do not run `clear-cache` while a long-running process is working in `/tmp`.

---

## Errors and Troubleshooting

**I get "command not found" when running `termux-sync`.**

The launcher at `$PREFIX/bin/termux-sync` may be missing. Run `tsctl status` to check the installation state. If the launcher is missing, run `tsctl install` or re-run `bash install.sh`.

**GitHub returns a 401 error.**

Your Personal Access Token has expired, been revoked, or was created without the `repo` scope. Generate a new token and update it by running `termux-sync setup`.

**The backup archive is unexpectedly large.**

Check your home directory for large files or directories not covered by the default exclusion list. Add them to `exclude_patterns` in your config. Common culprits are language toolchain caches, virtual environments, downloaded datasets, and large media files. Run `termux-sync check ~` to see which subdirectories are using the most space.

**Restore says the checksum does not match.**

The backup archive may have been corrupted during upload. Try restoring from a different backup if one is available, or create a new backup from the source device.

**`rclone not found` error when using Google Drive.**

Install rclone with `pkg install rclone` and configure a remote named `termux-sync-gdrive` by running `rclone config`.

**Old backups are not being deleted from Google Drive.**

This was a bug in versions before v1.2.0 where `GDriveStorage.delete_old()` was a no-op. Update with `tsctl updater` to fix it.

**I restored but some files are missing.**

Check whether the missing paths were in the exclusion list at the time the backup was created. You can inspect the backup's `manifest.json` to see exactly which archives were included and what their source paths were.

**The schedule I set is not being followed.**

Make sure the daemon is running (`termux-sync daemon &`) and that Termux:Boot is properly configured if you rely on it for auto-start. Check `termux-sync logs` for any errors from previous daemon runs.
