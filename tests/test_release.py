"""Unit tests for scripts/release (proposal P-8). Pure functions only; no
network, no git, no publishing. xdist-safe via tmp_path."""

import pathlib
import types

import pytest

import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from scripts.release import build as build_module  # noqa: E402
from scripts.release.meta import (  # noqa: E402
    ReleaseMeta,
    channel_for,
    compare_versions,
    parse_release_version,
    stable_versions_from_ls_remote,
)
from scripts.release import preflight as preflight_module  # noqa: E402
from scripts.release.preflight import (  # noqa: E402
    changelog_has_section,
    find_main_pinned_installs,
    find_main_pinned_links,
)
from scripts.release.stamp import STAMP_TARGETS, stamp_version  # noqa: E402
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


@pytest.mark.parametrize("good", ["0.0.0", "1.2.3", "10.20.30", "1.0.0rc1", "2.0.0a0", "3.1.0b2"])
def test_release_version_accepts_pep440(good):
    assert release_version(good) == good


@pytest.mark.parametrize(
    "bad", ["", "v1.2.3", "1.2", "1.2.3.4", "1.02.3", "latest", "1.2.x", " 1.2.3"]
)
def test_release_version_rejects_non_pep440(bad):
    with pytest.raises(ReleaseError):
        release_version(bad)


@pytest.mark.parametrize("semver", ["1.0.0-rc.1", "2.0.0-alpha", "1.2.3-beta.2"])
def test_release_version_rejects_semver_prerelease(semver):
    # SemVer prerelease syntax would normalize away from the tag; the error
    # points at the PEP 440 form so tag-is-version survives.
    with pytest.raises(ReleaseError, match="PEP 440"):
        release_version(semver)


@pytest.mark.parametrize("good", ["v0.0.0", "v1.2.3", "v10.20.30rc1"])
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
    assert parse_release_version("  v2.0.0rc1 ") == ReleaseMeta(
        "2.0.0rc1", "v2.0.0rc1"
    )
    with pytest.raises(ReleaseError):
        parse_release_version("nope")
    with pytest.raises(ReleaseError, match="PEP 440"):
        parse_release_version("v2.0.0-rc.1")


def test_stable_versions_from_ls_remote():
    output = (
        "abc123\trefs/tags/v1.0.0\n"
        "def456\trefs/tags/v1.0.0^{}\n"
        "aaa111\trefs/tags/v1.1.0rc1\n"
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
    # PEP 440 prerelease ordering: a < b < rc < stable.
    assert compare_versions("1.2.3a0", "1.2.3b0") < 0
    assert compare_versions("1.2.3b0", "1.2.3rc1") < 0
    assert compare_versions("1.2.3rc1", "1.2.3") < 0
    assert compare_versions("1.2.3rc1", "1.2.3rc2") < 0
    assert compare_versions("1.2.3rc1", "1.2.4a0") < 0


def test_channel_for():
    assert channel_for("1.0.0rc1", ["1.0.0", "2.0.0"]) == "prerelease"
    assert channel_for("2.0.0", ["1.0.0", "2.0.0"]) == "latest"
    assert channel_for("3.0.0", ["1.0.0", "2.0.0"]) == "latest"
    assert channel_for("1.5.0", ["1.0.0", "2.0.0"]) == "backport"
    assert channel_for("1.0.0", []) == "latest"


# stamp.py


def _tree(tmp_path, pyproject_version="0.0.0", init_version="0.0.0", cargo=False):
    (tmp_path / "python" / "peira").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "peira"\nversion = "%s"\nrequires-python = ">=3.10"\n'
        '[project.urls]\nDocumentation = '
        '"https://github.com/david-engelmann/peira/tree/v0.0.0/docs"\n'
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


def test_stamp_version_ignores_cargo(tmp_path):
    """Rust crates are versioned independently; never stamped."""
    stamped = stamp_version(_tree(tmp_path, cargo=True), "2.0.0")
    assert stamped == ["pyproject.toml", "python/peira/__init__.py"]
    cargo_text = (tmp_path / "crates/peira-python/Cargo.toml").read_text()
    assert 'version = "0.0.0"' in cargo_text


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


def test_build_artifacts_clears_stale_files(tmp_path, monkeypatch):
    tree = tmp_path / "tree"
    tree.mkdir()
    outdir = tmp_path / "dist"
    outdir.mkdir()
    stale = outdir / "peira-0.0.1-py3-none-any.whl"
    stale.write_text("stale")
    monkeypatch.setitem(sys.modules, "build", types.ModuleType("build"))
    fresh = outdir / "peira-9.9.9-py3-none-any.whl"

    def fake_check(cmd, cwd=None):
        fresh.write_text("fresh")
        return ""

    monkeypatch.setattr(build_module, "_check", fake_check)
    files = build_module.build_artifacts(tree, outdir)
    assert not stale.exists(), "stale artifact from an earlier run leaked into dist/"
    assert files == [fresh]


def test_build_artifacts_requires_build_package(tmp_path, monkeypatch):
    monkeypatch.delitem(sys.modules, "build", raising=False)
    with pytest.raises(build_module.ReleaseError, match="pip install build"):
        build_module.build_artifacts(tmp_path, tmp_path)


def _write_repo_tree(root, *, duplicate_url=False):
    url_marker = "tree/v0.0.0/docs"
    if duplicate_url:
        url_marker += "\n# tree/v0.0.0/docs"
    (root / "pyproject.toml").write_text(
        '[project]\nversion = "0.0.0"\n'
        f'Documentation = "https://github.com/david-engelmann/peira/{url_marker}"\n'
    )
    pkg = root / "python" / "peira"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text('__version__ = "0.0.0"\n')


def test_stamp_version_stamps_docs_url(tmp_path):
    _write_repo_tree(tmp_path)
    stamped = stamp_version(tmp_path, "9.9.9")
    assert sorted(stamped) == ["pyproject.toml", "python/peira/__init__.py"]
    pyproject = (tmp_path / "pyproject.toml").read_text()
    assert 'version = "9.9.9"' in pyproject
    assert "tree/v9.9.9/docs" in pyproject
    assert "v0.0.0" not in pyproject
    init = (tmp_path / "python" / "peira" / "__init__.py").read_text()
    assert '__version__ = "9.9.9"' in init


def test_stamp_version_duplicate_url_marker_fails(tmp_path):
    _write_repo_tree(tmp_path, duplicate_url=True)
    with pytest.raises(ReleaseError, match="refusing to guess"):
        stamp_version(tmp_path, "9.9.9")


def test_stamp_targets_cover_docs_url():
    markers = [(rel, marker) for rel, marker, _ in STAMP_TARGETS]
    assert ("pyproject.toml", "tree/v0.0.0/docs") in markers


def test_check_repo_unstamped_mirrors_stamp(tmp_path, monkeypatch):
    _write_repo_tree(tmp_path)
    monkeypatch.setattr(preflight_module, "REPO_ROOT", tmp_path)
    preflight_module.check_repo_unstamped()  # must not raise


def test_check_repo_unstamped_catches_duplicate(tmp_path, monkeypatch):
    _write_repo_tree(tmp_path, duplicate_url=True)
    monkeypatch.setattr(preflight_module, "REPO_ROOT", tmp_path)
    with pytest.raises(ReleaseError, match="exactly once"):
        preflight_module.check_repo_unstamped()


def test_find_main_pinned_links():
    files = {
        "README.md": "see https://github.com/david-engelmann/peira/tree/main/docs\n",
        "docs/Install.md": (
            "raw: https://github.com/david-engelmann/peira/blob/main/install.sh\n"
            "pinned: https://github.com/david-engelmann/peira/tree/v1.2.3/docs\n"
            "placeholder: https://github.com/david-engelmann/peira/tree/v0.0.0/docs\n"
        ),
    }
    hits = find_main_pinned_links(files)
    assert hits == ["README.md:1", "docs/Install.md:1"]
    assert find_main_pinned_links({"README.md": "no links here\n"}) == []


def test_wheel_version_reads_metadata(tmp_path):
    import zipfile

    whl = tmp_path / "peira-9.9.9-py3-none-any.whl"
    with zipfile.ZipFile(whl, "w") as zf:
        zf.writestr(
            "peira-9.9.9.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: peira\nVersion: 9.9.9\n",
        )
    assert build_module.wheel_version(whl) == "9.9.9"


def test_wheel_version_missing_raises(tmp_path):
    import zipfile

    whl = tmp_path / "peira-9.9.9-py3-none-any.whl"
    with zipfile.ZipFile(whl, "w") as zf:
        zf.writestr(
            "peira-9.9.9.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: peira\n",
        )
    with pytest.raises(ReleaseError, match="no Version in METADATA"):
        build_module.wheel_version(whl)


def test_wheel_version_no_metadata_raises(tmp_path):
    import zipfile

    whl = tmp_path / "peira-9.9.9-py3-none-any.whl"
    with zipfile.ZipFile(whl, "w") as zf:
        zf.writestr("peira-9.9.9.dist-info/WHEEL", "Wheel-Version: 1.0\n")
    with pytest.raises(ReleaseError, match="no .dist-info/METADATA"):
        build_module.wheel_version(whl)
