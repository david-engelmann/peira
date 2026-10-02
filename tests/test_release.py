"""Unit tests for scripts/release (proposal P-8). Pure functions only; no
network, no git, no publishing. xdist-safe via tmp_path."""

import pathlib

import pytest

import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scripts.release.meta import (  # noqa: E402
    ReleaseMeta,
    channel_for,
    compare_versions,
    parse_release_version,
    stable_versions_from_ls_remote,
)
from scripts.release.preflight import (  # noqa: E402
    changelog_has_section,
    find_main_pinned_installs,
)
from scripts.release.stamp import stamp_version  # noqa: E402
from scripts.release.validate import (  # noqa: E402
    ReleaseError,
    absolute_path,
    commit_sha,
    release_tag,
    release_version,
    safe_path,
    version_from_tag,
)


# validate.py


@pytest.mark.parametrize("good", ["0.0.0", "1.2.3", "10.20.30", "1.0.0-rc.1", "2.0.0-alpha"])
def test_release_version_accepts_semver(good):
    assert release_version(good) == good


@pytest.mark.parametrize(
    "bad", ["", "v1.2.3", "1.2", "1.2.3.4", "1.02.3", "latest", "1.2.x", " 1.2.3"]
)
def test_release_version_rejects_non_semver(bad):
    with pytest.raises(ReleaseError):
        release_version(bad)


@pytest.mark.parametrize("good", ["v0.0.0", "v1.2.3", "v10.20.30-rc.1"])
def test_release_tag_accepts_v_prefixed(good):
    assert release_tag(good) == good


@pytest.mark.parametrize("bad", ["1.2.3", "V1.2.3", "v1.2", "v", "v1.2.3 "])
def test_release_tag_rejects(bad):
    with pytest.raises(ReleaseError):
        release_tag(bad)


def test_version_from_tag_strips_v():
    assert version_from_tag("v1.2.3") == "1.2.3"
    with pytest.raises(ReleaseError):
        version_from_tag("1.2.3")


def test_commit_sha():
    sha = "a" * 40
    assert commit_sha("head", sha) == sha
    with pytest.raises(ReleaseError):
        commit_sha("head", "abc")
    with pytest.raises(ReleaseError):
        commit_sha("head", "A" * 40)


def test_safe_path():
    assert safe_path("out", "dist/peira-1.0.tar.gz") == "dist/peira-1.0.tar.gz"
    with pytest.raises(ReleaseError):
        safe_path("out", "-rf")
    with pytest.raises(ReleaseError):
        safe_path("out", "a;b")


def test_absolute_path():
    assert absolute_path("root", "/tmp/x") == "/tmp/x"
    with pytest.raises(ReleaseError):
        absolute_path("root", "relative/x")


# meta.py


def test_parse_release_version():
    assert parse_release_version("1.2.3") == ReleaseMeta("1.2.3", "v1.2.3")
    assert parse_release_version("v1.2.3") == ReleaseMeta("1.2.3", "v1.2.3")
    assert parse_release_version("  v2.0.0-rc.1 ") == ReleaseMeta(
        "2.0.0-rc.1", "v2.0.0-rc.1"
    )
    with pytest.raises(ReleaseError):
        parse_release_version("nope")


def test_stable_versions_from_ls_remote():
    output = (
        "abc123\trefs/tags/v1.0.0\n"
        "def456\trefs/tags/v1.0.0^{}\n"
        "aaa111\trefs/tags/v1.1.0-rc.1\n"
        "bbb222\trefs/tags/v2.0.0\n"
        "ccc333\trefs/tags/not-a-version\n"
        "ddd444\trefs/heads/main\n"
    )
    assert stable_versions_from_ls_remote(output) == ["1.0.0", "2.0.0"]


def test_stable_versions_from_ls_remote_empty():
    assert stable_versions_from_ls_remote("") == []
    assert stable_versions_from_ls_remote("garbage\nno tabs here") == []


def test_compare_versions():
    assert compare_versions("1.2.3", "1.2.3") == 0
    assert compare_versions("1.2.4", "1.2.3") > 0
    assert compare_versions("1.2.3", "2.0.0") < 0
    assert compare_versions("1.10.0", "1.9.0") > 0


def test_channel_for():
    assert channel_for("1.0.0-rc.1", ["1.0.0", "2.0.0"]) == "prerelease"
    assert channel_for("2.0.0", ["1.0.0", "2.0.0"]) == "latest"
    assert channel_for("3.0.0", ["1.0.0", "2.0.0"]) == "latest"
    assert channel_for("1.5.0", ["1.0.0", "2.0.0"]) == "backport"
    assert channel_for("1.0.0", []) == "latest"


# stamp.py


def _tree(tmp_path, pyproject_version="0.0.0", init_version="0.0.0", cargo=False):
    (tmp_path / "python" / "peira").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "peira"\nversion = "%s"\nrequires-python = ">=3.10"\n'
        % pyproject_version
    )
    (tmp_path / "python" / "peira" / "__init__.py").write_text(
        '__version__ = "%s"\n' % init_version
    )
    if cargo:
        (tmp_path / "crates" / "peira-python").mkdir(parents=True)
        (tmp_path / "crates" / "peira-python" / "Cargo.toml").write_text(
            '[package]\nname = "peira"\nversion = "0.0.0"\n'
        )
    return tmp_path


def test_stamp_version_happy_path(tmp_path):
    stamped = stamp_version(_tree(tmp_path), "1.2.3")
    assert stamped == ["pyproject.toml", "python/peira/__init__.py"]
    assert 'version = "1.2.3"' in (tmp_path / "pyproject.toml").read_text()
    assert 'requires-python = ">=3.10"' in (tmp_path / "pyproject.toml").read_text()
    assert '__version__ = "1.2.3"' in (tmp_path / "python/peira/__init__.py").read_text()


def test_stamp_version_rejects_bad_version(tmp_path):
    with pytest.raises(ReleaseError):
        stamp_version(_tree(tmp_path), "not-a-version")


def test_stamp_version_missing_marker_fails_loud(tmp_path):
    tree = _tree(tmp_path, pyproject_version="9.9.9")
    with pytest.raises(ReleaseError):
        stamp_version(tree, "1.2.3")


def test_stamp_version_double_marker_fails_loud(tmp_path):
    tree = _tree(tmp_path)
    p = tree / "pyproject.toml"
    p.write_text(p.read_text() + 'version = "0.0.0"\n')
    with pytest.raises(ReleaseError):
        stamp_version(tree, "1.2.3")


def test_stamp_version_cargo_optional(tmp_path):
    stamped = stamp_version(_tree(tmp_path, cargo=True), "2.0.0")
    assert "crates/peira-python/Cargo.toml" in stamped
    cargo_text = (tmp_path / "crates/peira-python/Cargo.toml").read_text()
    assert 'version = "2.0.0"' in cargo_text
    assert 'name = "peira"' in cargo_text


def test_stamp_version_missing_pyproject_fails(tmp_path):
    tree = _tree(tmp_path)
    (tree / "pyproject.toml").unlink()
    with pytest.raises(ReleaseError):
        stamp_version(tree, "1.2.3")


# preflight pure helpers


def test_changelog_has_section():
    text = "# Changelog\n\n## [1.2.3]\n\n### Added\n\n- things\n\n## [1.2.2]\n"
    assert changelog_has_section(text, "1.2.3")
    assert changelog_has_section(text, "1.2.2")
    assert not changelog_has_section(text, "1.2.4")
    assert not changelog_has_section(text, "1.2")  # no prefix match


def test_find_main_pinned_installs():
    files = {
        "README.md": "pip install peira==1.2.3\n",
        "docs/Install.md": (
            "curl -fsSL https://raw.githubusercontent.com/david-engelmann/peira/main/install.sh | sh\n"
            "pip install git+https://github.com/david-engelmann/peira@main\n"
        ),
    }
    hits = find_main_pinned_installs(files)
    assert len(hits) == 2
    assert all(h.startswith("docs/Install.md:") for h in hits)

    clean = {"README.md": "pip install peira==1.2.3\n"}
    assert find_main_pinned_installs(clean) == []
