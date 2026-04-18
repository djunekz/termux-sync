# Governance

This document describes how termux-sync is maintained, how decisions are made, and how contributors can take on larger roles in the project.

---

## Project Structure

termux-sync is an open source project maintained by a small group of contributors. It does not have a formal governance board or voting process. Decisions are made through discussion in GitHub issues and pull requests, with the current maintainers having final say.

---

## Roles

### User

Anyone who installs and uses termux-sync. Users are encouraged to report bugs, ask questions, and suggest features through GitHub issues.

### Contributor

Anyone who has opened a pull request that was merged into the repository. Contributors are listed in the repository's contributor graph. There are no special permissions associated with this role.

### Maintainer

Maintainers have write access to the repository. They review pull requests, triage issues, cut releases, and manage repository settings. The current maintainer is listed in the repository's About section.

Maintainers are responsible for:

- Reviewing and merging pull requests in a reasonable timeframe
- Responding to security reports
- Keeping dependencies and documentation up to date
- Tagging releases and updating the changelog

### Becoming a Maintainer

There is no formal application process. If you have made consistent, high-quality contributions over time and are interested in taking on a maintainer role, open an issue and raise the topic. The decision is made by the current maintainers based on demonstrated judgment, reliability, and familiarity with the codebase.

---

## Decision Making

Most decisions are made by lazy consensus: if a change is proposed in a pull request and no maintainer objects within a reasonable review window, it is considered approved and can be merged.

For larger changes — new storage backends, changes to the backup format, breaking changes to the CLI, or changes to the governance model itself — an issue should be opened for discussion before implementation begins. This allows the community to provide input before significant work is invested.

If maintainers disagree on a decision and cannot reach consensus through discussion, the most active maintainer on the repository at that time makes the final call.

---

## Releasing

Releases follow Semantic Versioning. A new release is tagged when:

- A meaningful set of bug fixes has accumulated, or
- A notable new feature has been added and stabilized, or
- A security fix needs to be distributed

The release process:

1. Update `VERSION` in `termux-sync.py`
2. Add an entry to `CHANGELOG.md` under the new version number
3. Create and push a version tag in the form `vX.Y.Z`
4. The release workflow creates a GitHub Release automatically with the archive and changelog entry

Pre-release versions use the format `vX.Y.Z-beta.N` or `vX.Y.Z-rc.N`.

---

## Forking

termux-sync is released under the MIT License. You are free to fork the project and maintain your own version. If you fork and make significant improvements, consider opening pull requests back to the original repository so others can benefit.

---

## Changes to This Document

Changes to this governance document follow the same process as any other change: open a pull request, discuss, and merge with maintainer approval.
