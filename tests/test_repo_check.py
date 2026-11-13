import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "repo_check.py"
spec = importlib.util.spec_from_file_location("repo_check", SCRIPT)
repo_check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repo_check)


def test_version_key_orders_numerically():
    assert repo_check.version_key("1.10.0") > repo_check.version_key("1.9.9")


def test_pypi_is_behind_when_release_missing_and_old_enough():
    assert repo_check.pypi_is_behind("1.3.6", {"1.3.5"}, 300)


def test_pypi_is_not_behind_inside_grace_period():
    assert not repo_check.pypi_is_behind("1.3.6", {"1.3.5"}, 10)


def test_pypi_is_not_behind_when_published():
    assert not repo_check.pypi_is_behind("1.3.6", {"1.3.6"}, 999)


def test_pypi_unknown_or_prerelease_is_ignored():
    assert not repo_check.pypi_is_behind("1.3.6", None, 999)
    assert not repo_check.pypi_is_behind("1.4.0-rc1", {"1.3.6"}, 999)


def test_release_age_handles_missing_value():
    assert repo_check.release_age_minutes("") is None
    assert repo_check.release_age_minutes("2020-01-01T00:00:00Z") > 0


def test_repository_versions_agree():
    versions = {
        repo_check.pyproject_version(),
        repo_check.source_version(),
        repo_check.lock_version(),
    }
    assert len(versions) == 1


def test_standalone_script_mirrors_package():
    assert not repo_check.mirror_drifted()
