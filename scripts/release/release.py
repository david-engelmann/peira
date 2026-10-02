"""Release orchestrator for peira (proposal P-8).

Usage:
    python scripts/release/release.py --version 1.2.3            # dry run
    python scripts/release/release.py --version 1.2.3 --publish  # for real

Dry run (default) executes everything except the upload: preflight, build,
and a report of what would be published. ``--publish`` additionally runs
``twine upload`` on the built artifacts and then the post-publish smoke
test against the real PyPI. Publishing requires the preflight to pass,
which requires a signed tag pointing at the reviewed main head.

Nothing here invents a version: the signed git tag is the single source of
truth, and the repo tree always carries 0.0.0 (see docs/Release.md).
"""

from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from scripts.release.build import run_build, sha256  # noqa: E402
from scripts.release.meta import channel_for, parse_release_version  # noqa: E402
from scripts.release.preflight import run_preflight  # noqa: E402
from scripts.release.smoke import run_smoke  # noqa: E402
from scripts.release.validate import ReleaseError  # noqa: E402

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def known_stable_tags() -> list[str]:
    """Stable versions from origin tags (best effort; empty on failure)."""
    try:
        proc = subprocess.run(
            ["git", "ls-remote", "--tags", "origin"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    from scripts.release.meta import stable_versions_from_ls_remote

    return stable_versions_from_ls_remote(proc.stdout)


def publish_artifacts(files: list[pathlib.Path]) -> None:
    try:
        import twine  # noqa: F401
    except ImportError:
        raise ReleaseError(
            "the 'twine' package is required to publish (pip install twine); "
            "set TWINE_USERNAME/TWINE_PASSWORD or configure ~/.pypirc"
        )
    proc = subprocess.run(
        [sys.executable, "-m", "twine", "upload", *(str(f) for f in files)],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise ReleaseError(
            "twine upload failed: "
            f"{(proc.stderr.strip().splitlines() or ['no stderr'])[-1]}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="peira release orchestrator")
    parser.add_argument("--version", required=True, help="release version or tag")
    parser.add_argument(
        "--publish",
        action="store_true",
        help="actually upload to PyPI (default is a dry run)",
    )
    parser.add_argument(
        "--skip-smoke", action="store_true", help="skip the post-publish smoke test"
    )
    parser.add_argument("--outdir", default="dist")
    args = parser.parse_args(argv)

    try:
        meta = parse_release_version(args.version)
        print(f"release {meta.tag} ({'PUBLISH' if args.publish else 'dry run'})")
        run_preflight(meta.version)
        channel = channel_for(meta.version, known_stable_tags())
        print(f"channel: {channel}")
        if channel == "backport":
            print(
                "note: backport release; it ships but never moves the 'latest' pointer"
            )
        outdir = REPO_ROOT / args.outdir
        files = run_build(meta.version, outdir)
        print("artifacts:")
        for f in files:
            print(f"  {f.name}  sha256:{sha256(f)}")

        if not args.publish:
            print("dry run complete: nothing uploaded.")
            print(f"re-run with --publish to upload {len(files)} files to PyPI.")
            return 0

        confirm = input(f"upload {meta.tag} to PyPI? type the tag to confirm: ").strip()
        if confirm != meta.tag:
            print("aborted: confirmation did not match the tag")
            return 1
        publish_artifacts(files)
        print(f"published {meta.tag} to PyPI")
        if not args.skip_smoke:
            run_smoke(meta.version)
        print(f"release {meta.tag} complete")
        return 0
    except ReleaseError as exc:
        print(f"release FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
