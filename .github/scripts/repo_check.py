import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "termux-sync"
LAG_GRACE_MINUTES = 90


def read(path):
    return (ROOT / path).read_text(encoding="utf-8")


def first_match(pattern, text):
    found = re.search(pattern, text, re.M)
    return found.group(1) if found else ""


def version_key(version):
    return tuple(int(part) for part in re.findall(r"\d+", version)[:3])


def pyproject_version():
    return first_match(r'^version\s*=\s*"([^"]+)"', read("pyproject.toml"))


def source_version():
    return first_match(r'^VERSION\s*=\s*"([^"]+)"', read("src/termux_sync/__init__.py"))


def lock_version():
    return first_match(r'name = "termux-sync"\nversion = "([^"]+)"', read("uv.lock"))


def changelog_version():
    return first_match(r"^## \[(\d+\.\d+\.\d+[^\]]*)\]", read("CHANGELOG.md"))


def mirror_drifted():
    package = ROOT / "src" / "termux_sync" / "__init__.py"
    script = ROOT / "termux-sync.py"
    return package.read_bytes() != script.read_bytes()


def pypi_versions():
    url = f"https://pypi.org/pypi/{PACKAGE}/json"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            return set(json.load(response).get("releases", {}))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def release_age_minutes(published_at):
    if not published_at:
        return None
    moment = datetime.datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    delta = datetime.datetime.now(datetime.timezone.utc) - moment
    return delta.total_seconds() / 60


def pypi_is_behind(release_version, published, age_minutes):
    if not release_version or published is None or "-" in release_version:
        return False
    if release_version in published:
        return False
    return age_minutes is None or age_minutes >= LAG_GRACE_MINUTES


def collect_problems(env):
    problems = []
    versions = {
        "pyproject.toml": pyproject_version(),
        "src/termux_sync/__init__.py": source_version(),
        "uv.lock": lock_version(),
        "CHANGELOG.md": changelog_version(),
    }
    if len(set(versions.values())) > 1:
        listing = ", ".join(f"{name} = {value or 'missing'}" for name, value in versions.items())
        problems.append(f"Version numbers disagree: {listing}.")

    drift = mirror_drifted()
    if drift:
        problems.append("`termux-sync.py` differs from `src/termux_sync/__init__.py`.")

    release = env.get("LATEST_RELEASE", "").lstrip("v")
    current = versions["pyproject.toml"]
    if release and current and version_key(current) > version_key(release):
        problems.append(
            f"`pyproject.toml` is at {current} but the latest GitHub release is {release}."
        )

    published = pypi_versions()
    if published is None:
        problems.append("Could not read the package list from PyPI.")
    lag = pypi_is_behind(
        release, published, release_age_minutes(env.get("LATEST_RELEASE_AT", ""))
    )
    if lag:
        problems.append(f"GitHub release {release} is not on PyPI yet.")

    for label, key in (("Lint", "LINT_OUTCOME"), ("Tests", "TESTS_OUTCOME")):
        if env.get(key) == "failure":
            problems.append(f"{label} failed against the latest dependencies.")

    return problems, drift, lag


def write_outputs(problems, drift, lag):
    lines = ["Automated check by the repository bot.", ""]
    if problems:
        lines += [f"- {item}" for item in problems]
    else:
        lines.append("Everything is in order.")
    (ROOT / "health-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    target = os.environ.get("GITHUB_OUTPUT")
    if target:
        with open(target, "a", encoding="utf-8") as handle:
            handle.write(f"problems={len(problems)}\n")
            handle.write(f"mirror_drift={'true' if drift else 'false'}\n")
            handle.write(f"pypi_lag={'true' if lag else 'false'}\n")


def main():
    problems, drift, lag = collect_problems(os.environ)
    write_outputs(problems, drift, lag)
    for item in problems:
        print(item)
    return 0


if __name__ == "__main__":
    sys.exit(main())
