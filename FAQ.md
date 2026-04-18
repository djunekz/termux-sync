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

This clones the repository to a permanent location and registers the `termux-sync` command system-wide. After installation, you can discard the downloaded `tsctl` file — a copy is installed at `$PREFIX/bin/tsctl`.

**Can I install termux-sync without internet access?**

Yes. Clone or download the repository manually, then run `bash install.sh` from the project directory. All dependencies (`python`, `python-pip`, `rich`) need to be available through the Termux package manager or already installed.

**What does `tsctl install` put on my device?**

The repository is cloned to `$PREFIX/lib/termux-sync`. A launcher script is written to `$PREFIX/bin/termux-sync` so the command is available everywhere. Nothing is written outside of the Termux prefix and your home directory.

**How do I update termux-sync?**

```bash
tsctl updater
```

This fetches the latest commits from the main branch and refreshes the launcher.

**How do I uninstall termux-sync?**

```bash
tsctl uninstall
```

This removes the launcher, install directory, config directory, and any shell aliases. Your backup archives are not deleted.

---

## Storage Backends

**Which storage backend should I use?**

GitHub private repository is recommended for most users. It is reliable, free for private repositories, and makes it straightforward to restore on any new device. Local storage is useful if you prefer to keep data entirely on-device or on a mounted drive. Google Drive requires rclone to be configured and is better suited to users who already use rclone for other purposes.

**How do I set up GitHub storage?**

1. Create a private GitHub repository.
2. Generate a Personal Access Token with the `repo` scope at Settings > Developer Settings > Personal Access Tokens > Tokens (classic).
3. Run `termux-sync setup` and choose option 3.
4. Enter your token and repository name in `username/repo` format.

**What rclone remote name does termux-sync use for Google Drive?**

termux-sync uses the folder ID stored in `gdrive_folder_id` in your config file. You need to configure an rclone remote named `gdrive` before using this backend. Run `rclone config` and follow the setup for Google Drive.

**Can I switch storage backends after the initial setup?**

Yes. Run `termux-sync setup` again and choose a different backend. Existing backups in the old location are not moved automatically.

---

## Backup and Restore

**What exactly gets backed up?**

Four components are archived: the installed package list (via `dpkg --get-selections`), your home directory (`~`), the Termux configuration directory (`$PREFIX/etc`), and shared libraries (`$PREFIX/lib`).

**How large will my backup be?**

It depends on what is in your home directory. The default exclusion list removes common large directories such as `.cache`, `node_modules`, `.cargo/registry`, `.rustup/toolchains`, and media folders. A typical Termux environment with a few development tools usually produces a backup between 50 MB and 300 MB.

**How do I reduce the backup size?**

Add paths to `exclude_patterns` in `~/.config/termux-sync/config.json`. You can also switch to `xz` compression for better compression ratios, though it is slower.

**How many backups are kept?**

The `max_backups` setting in your config controls this. The default is 5. When a new backup is created and the count exceeds this limit, the oldest backup is deleted automatically.

**How does restore work?**

Running `termux-sync restore` shows an interactive list of available backups. After you select one, SHA-256 checksums from the manifest are verified against the actual archives before any extraction takes place. If verification passes, the archives are extracted and packages are reinstalled.

**Can I restore individual files instead of the full backup?**

Not through termux-sync directly. You can extract specific files manually from the archive:

```bash
tar -tzf ~/termux-backups/termux_backup_TIMESTAMP/home.tar.gz | grep filename
tar -xzf ~/termux-backups/termux_backup_TIMESTAMP/home.tar.gz path/to/file
```

**What happens if restore fails partway through?**

termux-sync verifies checksums before extracting. If a checksum fails, extraction does not begin. If the process is interrupted after extraction starts, the partially restored state may be inconsistent. In that case, run `termux-sync restore` again with the same backup to complete the process, or run `termux-sync restore` with a different backup.

---

## Auto-Backup

**How do I set up automatic backups?**

Run `termux-sync schedule` and enter the time you want the daily backup to run. Then either start the daemon manually (`termux-sync daemon &`) or install Termux:Boot from F-Droid to have it start automatically on device boot.

**Where is the Termux:Boot script written?**

At `~/.termux/boot/termux-sync-daemon.sh`. This script is generated automatically when you run `termux-sync schedule`.

**The daemon is not running after a reboot. What is wrong?**

Make sure Termux:Boot is installed from F-Droid (not Google Play) and that you have opened the Termux:Boot app at least once to grant it the required permissions.

---

## Configuration

**Where is the config file?**

At `~/.config/termux-sync/config.json`. You can edit it directly with any text editor or regenerate it by running `termux-sync setup`.

**Where are the logs?**

At `~/.config/termux-sync/sync.log`. View them in-app with `termux-sync logs` or read the file directly with `cat ~/.config/termux-sync/sync.log`.

**What compression format should I use?**

`gz` is the default and is fast enough for most use cases. Use `bz2` for a balance of speed and size. Use `xz` if storage space is the primary concern and you do not mind slower backup times.

---

## Errors and Troubleshooting

**I get "command not found" when running `termux-sync`.**

The launcher at `$PREFIX/bin/termux-sync` may be missing. Run `tsctl status` to check the installation state. If the launcher is missing, run `tsctl install` again or re-run `bash install.sh`.

**GitHub returns a 401 error.**

Your Personal Access Token has expired, been revoked, or was created without the `repo` scope. Generate a new token and update it by running `termux-sync setup`.

**The backup archive is unexpectedly large.**

Check your home directory for large files or directories that are not covered by the default exclusion list. Add them to `exclude_patterns` in your config. Common culprits are language toolchain caches, virtual environments, and downloaded datasets.

**Restore says the checksum does not match.**

The backup archive may be corrupted. This can happen if the upload to your storage backend was interrupted. Try restoring from a different backup if one is available, or create a new backup from the source device.

**`rclone not found` error when using Google Drive.**

Install rclone with `pkg install rclone` and then configure a remote with `rclone config`. The remote must be named `gdrive` for termux-sync to use it.
