# Security Policy

## Supported Versions

Only the latest release of termux-sync receives security fixes. Older versions are not maintained.

| Version | Supported |
|---|---|
| 1.0.x (latest) | Yes |
| older | No |

---

## Reporting a Vulnerability

Do not open a public GitHub issue for security vulnerabilities. Public disclosure before a fix is available puts other users at risk.

To report a vulnerability, contact the maintainers privately by opening a [GitHub Security Advisory](https://github.com/djunekz/termux-sync/security/advisories/new) on the repository. Describe the issue, the steps to reproduce it, and the potential impact. You will receive a response within 7 days.

If a fix is possible, the maintainers will prepare a patch and coordinate a disclosure timeline with you before releasing it.

---

## Token and Credential Handling

termux-sync stores configuration, including GitHub Personal Access Tokens, in `~/.config/termux-sync/config.json`. This file is created with default permissions on your device and is only as secure as your device's filesystem.

Recommendations:

- Use a token with the minimum required scope. For GitHub storage, only the `repo` scope is needed.
- Set a token expiration date. Rotate tokens periodically.
- If your device is shared or compromised, revoke your tokens immediately from the GitHub settings page.
- Do not commit your `config.json` file to any repository.

---

## Backup Security

Backups are stored as plain tar archives. They are not encrypted by default.

If you use GitHub as a storage backend, ensure the repository is private. A public repository will expose your home directory and configuration files to anyone.

If you use local storage, ensure the backup path is on a storage volume that is not accessible to other applications.

Encryption support is planned for a future release. Until then, treat your backups with the same sensitivity as the data they contain.
