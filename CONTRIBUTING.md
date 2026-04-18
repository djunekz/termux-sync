# Contributing to termux-sync

Thank you for taking the time to contribute. This document covers how to report issues, suggest features, and submit code changes.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Reporting Bugs](#reporting-bugs)
- [Requesting Features](#requesting-features)
- [Development Setup](#development-setup)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Code Style](#code-style)
- [Commit Messages](#commit-messages)

---

## Code of Conduct

This project follows a simple standard: be respectful and constructive. Harassment, personal attacks, and dismissive comments are not acceptable. If you see a violation, open an issue or contact a maintainer directly.

---

## Reporting Bugs

Before opening a new issue, search the existing issues to make sure the bug has not already been reported.

When filing a bug report, include:

- Your Termux version (`termux-info` output or `pkg list-installed | grep termux`)
- Your Android version
- The termux-sync version (`termux-sync --version`)
- The storage backend you are using (local, gdrive, or github)
- The full command you ran
- The complete error output, including any log lines from `termux-sync logs`
- Steps to reproduce the problem

Use the bug report issue template when creating the issue.

---

## Requesting Features

Open a GitHub issue using the feature request template. Describe the problem you want to solve, not just the solution you have in mind. This helps maintainers understand the use case and consider alternative approaches.

---

## Development Setup

termux-sync is designed to run on Termux. To work on it:

```bash
# Install dependencies
pkg install python python-pip git

# Fork the repository on GitHub, then clone your fork
git clone https://github.com/YOUR_USERNAME/termux-sync ~/termux-sync
cd ~/termux-sync

# Install Python dependencies
pip install rich

# Run directly from the source
python termux-sync.py --help
```

There is no build step. The main application is `termux-sync.py` and the control tool is `tsctl`.

---

## Submitting a Pull Request

1. Fork the repository and create a branch from `main`.
2. Use a descriptive branch name such as `fix/restore-checksum` or `feat/bz2-compression`.
3. Make your changes. Keep each pull request focused on a single concern.
4. Test your changes on a real Termux environment if possible.
5. Update documentation in `README.md` or other `.md` files if your change affects user-facing behavior.
6. Open a pull request against the `main` branch and fill in the pull request template.

Pull requests that lack context, break existing commands, or introduce large unrelated changes may be closed without merging.

---

## Code Style

- Follow the existing style in `termux-sync.py`. The file uses 4-space indentation and standard Python conventions.
- Shell scripts (`install.sh`, `tsctl`) use 4-space indentation and `set -euo pipefail`.
- Keep functions focused. If a function is growing large, consider splitting it.
- Add inline comments for non-obvious logic. Avoid comments that just restate what the code does.
- Do not introduce new Python dependencies beyond the standard library and `rich` without discussion in an issue first.

---

## Commit Messages

Write commit messages in the imperative mood: "Fix restore path mismatch" not "Fixed restore path mismatch".

Structure:

```
Short summary (under 72 characters)

Longer explanation if needed. Describe why the change was made, not
just what was changed. Reference relevant issues with #number.
```

Examples of good commit messages:

```
Fix SHA-256 verification skipping empty archives
Add bz2 compression support to backup command
Update tsctl to handle missing git gracefully
```

---

## Questions

If you are unsure whether something is a bug or a feature, open an issue and describe what you are seeing. Maintainers are happy to help clarify.
