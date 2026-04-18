# Privacy

termux-sync is a local command-line tool. This document describes what data it handles, where that data goes, and what the project does not collect.

---

## What termux-sync handles

termux-sync creates archives of your Termux environment and stores or transfers them according to the storage backend you configure. The data it touches includes:

- Your home directory (`~`), which may contain personal files, scripts, SSH keys, API tokens stored in dotfiles, and other sensitive data
- Your installed package list
- Termux configuration files under `$PREFIX/etc`
- Shared libraries under `$PREFIX/lib`
- A GitHub Personal Access Token or rclone credentials if you configure a remote backend

This data never leaves your device except to the storage destination you explicitly configure.

---

## What the project does not collect

termux-sync does not collect, transmit, or store any data outside of your configured storage destination. Specifically:

- No analytics or telemetry of any kind
- No crash reports sent to any server
- No usage data, command history, or backup metadata sent to the project maintainers
- No network connections made by the tool itself except to your chosen storage backend (GitHub API or rclone remote)

The maintainers have no visibility into how many people use termux-sync, how often it runs, or what is in any user's backups.

---

## Storage backends

### Local storage

Backups are written to a path on your device that you configure. No data leaves your device. You are responsible for the security of that path.

### Google Drive

Backups are uploaded to Google Drive using rclone. rclone handles authentication with Google using OAuth credentials you configure yourself. termux-sync does not have access to your Google account credentials. Refer to [rclone's privacy documentation](https://rclone.org/privacy/) for details on how rclone interacts with Google's APIs.

### GitHub private repository

Backups are pushed to a GitHub repository using the GitHub API. Authentication uses a Personal Access Token that you generate and store in your local config file. The token is stored in plain text at `~/.config/termux-sync/config.json`. Treat this file as sensitive.

When using GitHub storage, your backup archives are uploaded to GitHub's servers. GitHub's privacy policy governs how that data is handled. Use a private repository to prevent public access. The project maintainers do not have access to your repository.

---

## Local data

termux-sync stores the following files on your device:

| Path | Contents |
|---|---|
| `~/.config/termux-sync/config.json` | Storage backend, credentials, and preferences |
| `~/.config/termux-sync/cron.json` | Auto-backup schedule settings |
| `~/.config/termux-sync/sync.log` | Operation log with timestamps |
| `~/.termux/boot/termux-sync-daemon.sh` | Boot script (created when scheduling auto-backup) |

These files are created with default Termux filesystem permissions. You are responsible for the security of your device and these files.

---

## Recommendations

- Use a GitHub Personal Access Token with the minimum required scope (`repo` only) and set an expiration date.
- Do not store sensitive credentials in your home directory if you back up to a repository that others have access to, even indirectly.
- If you use GitHub storage, always use a private repository.
- Review the contents of your backup archives periodically to confirm that sensitive files are excluded as expected.
- Rotate your GitHub token regularly and update it with `termux-sync setup`.

---

## Contact

For privacy-related concerns or questions, open a GitHub issue or contact the maintainers through the repository.
