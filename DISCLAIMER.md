# Disclaimer

## No Warranty

termux-sync is provided as-is, without warranty of any kind, express or implied. The authors and contributors make no guarantees about correctness, reliability, fitness for a particular purpose, or freedom from defects.

The full license text, including the warranty disclaimer, is in the [LICENSE](LICENSE) file.

---

## Use at Your Own Risk

termux-sync reads, archives, and restores files from your Termux home directory and system configuration. Incorrect use, a bug in the software, or an interrupted operation may result in lost, overwritten, or corrupted files.

Before relying on termux-sync as your primary backup solution:

- Verify that your backups are complete and restorable by running `termux-sync restore` on a test device or in a fresh Termux installation.
- Confirm that sensitive files are excluded from backups as you intend.
- Understand that a backup stored on an external service (GitHub, Google Drive) is subject to that service's availability and terms.

The project maintainers are not responsible for data loss resulting from the use of termux-sync.

---

## Third-Party Services

termux-sync can be configured to store backups on GitHub or Google Drive. These are third-party services with their own terms of service, privacy policies, and availability guarantees. termux-sync has no affiliation with GitHub or Google. Use of these services through termux-sync is governed by your agreements with those providers.

rclone is a third-party open source tool used for Google Drive transfers. Its behavior, reliability, and any issues arising from its use are outside the scope of termux-sync.

---

## Security

Backup archives created by termux-sync may contain sensitive data, including SSH keys, API tokens, and configuration secrets stored in your home directory. These archives are not encrypted by default.

The project makes no guarantee that your backups are protected against unauthorized access. You are responsible for ensuring that your chosen storage backend is properly secured and access-controlled.

---

## Termux Compatibility

termux-sync is designed for use within the Termux terminal environment on Android. It has not been tested on Termux forks, modified Termux installations, or other Unix-like environments on Android. Behavior in unsupported environments is undefined.

Package reinstallation during restore depends on the Termux package repository being available and the packages being present at the time of restore. Packages that have been removed from the repository since the backup was created may not reinstall successfully.
