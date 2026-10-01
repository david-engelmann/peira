"""Build the release artifacts from a signed tag (proposal P-8).

Usage: ``python scripts/release/build.py --version 1.2.3 [--outdir dist/]``

Materializes ``git archive <tag>`` into a temp dir, stamps the tag version
via ``stamp.py``, then builds sdist + wheel with ``python -m build``. The
built wheel's METADATA version is asserted to equal the tag version, and
sha256 checksums are printed for the release record. The repo tree itself
is never modified; the temp tree is removed unless ``--keep-tree``.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import shutil
import subprocess
import sys
import tempfile
import zipfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from scripts.release.meta import parse_release_version  # noqa: E402
from scripts.release.preflight import run_preflight  # noqa: E402
from scripts.release.stamp import stamp_version  # noqa: E402
from scripts.release.validate import ReleaseError  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _check(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if proc.returncode != 0:
        raise ReleaseError(
            f"{' '.join(cmd)} failed: "
            f"{(proc.stderr.strip().splitlines() or ['no stderr'])[-1]}"
        )
    return proc


def materialize_tag(tag: str, dest: pathlib.Path) -> None:
    """Extract ``git archive <tag>`` into dest."""
    archive = subprocess.run(
        ["git", "archive", tag], cwd=REPO_ROOT, capture_output=True, check=False
    )
    if archive.returncode != 0:
        raise ReleaseError(
            f"git archive {tag} failed: {archive.stderr.decode().strip().splitlines()[-1]}"
        )
    proc = subprocess.run(
        ["tar", "-x", "-C", str(dest)],
        input=archive.stdout,
        capture_output=True,
    )
    if proc.returncode != 0:
        raise ReleaseError(
            f"extracting git archive {tag} failed: {proc.stderr.decode().strip()}"
        )


def build_artifacts(tree: pathlib.Path, outdir: pathlib.Path) -> list[pathlib.Path]:
    """Run ``python -m build`` in the stamped tree; return built files."""
    try:
        import build  # noqa: F401
    except ImportError:
        raise ReleaseError(
            "the 'build' package is required (pip install build) to build releases"
        )
    outdir.mkdir(parents=True, exist_ok=True)
    # Never let a stale artifact from an earlier run sneak into the upload set.
    for stale in outdir.glob("peira-*"):
        if stale.is_file():
            stale.unlink()
    _check(
        [sys.executable, "-m", "build", "--sdist", "--wheel", "--outdir", str(outdir)],
        cwd=tree,
    )
    files = sorted(outdir.glob("peira-*"))
    if not files:
        raise ReleaseError(f"python -m build produced no peira-* files in {outdir}")
    return files


def wheel_version(wheel: pathlib.Path) -> str:
    """Read the Version field from a wheel's METADATA."""
    with zipfile.ZipFile(wheel) as zf:
        meta_name = next(
            (n for n in zf.namelist() if n.endswith(".dist-info/METADATA")),
            None,
        )
        if meta_name is None:
            raise ReleaseError(f"{wheel.name} has no .dist-info/METADATA")
        for line in zf.read(meta_name).decode("utf-8").splitlines():
            if line.startswith("Version: "):
                return line[len("Version: ") :].strip()
    raise ReleaseError(f"{wheel.name} has no Version in METADATA")


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_build(
    version: str, outdir: pathlib.Path, keep_tree: bool = False
) -> list[pathlib.Path]:
    meta = parse_release_version(version)
    run_preflight(meta.version, verbose=False)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="peira-release-"))
    try:
        materialize_tag(meta.tag, tmp)
        stamped = stamp_version(tmp, meta.version)
        print(f"stamped {meta.version} into: {', '.join(stamped)}")
        files = build_artifacts(tmp, outdir)
        for f in files:
            if f.suffix == ".whl":
                got = wheel_version(f)
                if got != meta.version:
                    raise ReleaseError(
                        f"wheel METADATA version {got} != tag version {meta.version}"
                    )
            print(f"built {f.name}  sha256:{sha256(f)}")
        return files
    finally:
        if keep_tree:
            print(f"kept build tree at {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build release artifacts from a tag")
    parser.add_argument("--version", required=True, help="release version or tag")
    parser.add_argument("--outdir", default="dist", help="output dir for artifacts")
    parser.add_argument("--keep-tree", action="store_true")
    args = parser.parse_args(argv)
    try:
        run_build(args.version, pathlib.Path(args.outdir), keep_tree=args.keep_tree)
    except ReleaseError as exc:
        print(f"build FAIL: {exc}", file=sys.stderr)
        return 1
    print("build PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
