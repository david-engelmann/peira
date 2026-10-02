"""Post-publish smoke test for a peira release (proposal P-8).

Usage: ``python scripts/release/smoke.py --version 1.2.3``

Creates a clean venv in a temp dir, installs ``peira==<version>`` from the
real PyPI (explicit index, no local paths), then asserts the installed
package imports, reports the right version, and answers ``peira --version``.
Catches the "published but broken" class: bad metadata, missing files in
the sdist/wheel, or an import-time crash.

The trial dataset ships with the repo, not the wheel, so the README
quickstart's ``peira run --suite trial`` step needs a checkout and cannot
run in the clean venv. The smoke covers the install surface the wheel
actually provides. If the dataset ever ships inside the wheel, extend the
smoke with a ``peira run --adapter mock --suite trial`` pass.

Needs network access to PyPI. Never run against a local path or a test
index unless ``--index-url`` is explicitly overridden.
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from scripts.release.meta import parse_release_version  # noqa: E402
from scripts.release.validate import ReleaseError  # noqa: E402

PYPI_INDEX = "https://pypi.org/simple"


def _check(cmd: list[str], what: str) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise ReleaseError(
            f"{what} failed: "
            f"{(proc.stderr.strip().splitlines() or proc.stdout.strip().splitlines() or ['no output'])[-1]}"
        )
    return proc.stdout.strip()


def run_smoke(version: str, index_url: str = PYPI_INDEX) -> None:
    meta = parse_release_version(version)
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="peira-smoke-"))
    try:
        venv = tmp / "venv"
        print(f"creating clean venv at {venv}")
        _check([sys.executable, "-m", "venv", str(venv)], "venv creation")
        vpy = str(venv / "bin" / "python")
        _check(
            [vpy, "-m", "pip", "install", "--quiet",
             "--index-url", index_url, f"peira=={meta.version}"],
            f"pip install peira=={meta.version} from {index_url}",
        )
        print(f"installed peira=={meta.version} from {index_url}")
        reported = _check(
            [vpy, "-c", "import importlib.metadata; print(importlib.metadata.version('peira'))"],
            "reading installed version",
        )
        if reported != meta.version:
            raise ReleaseError(
                f"installed version {reported} != expected {meta.version}"
            )
        print(f"ok: importlib.metadata reports {reported}")
        out = _check([vpy, "-c", "import peira; print(peira.__version__)"],
                     "importing peira")
        if out != meta.version:
            raise ReleaseError(f"peira.__version__ is {out}, expected {meta.version}")
        print(f"ok: peira imports, __version__ == {out}")
        cli = _check([str(venv / "bin" / "peira"), "--version"], "peira --version")
        if meta.version not in cli:
            raise ReleaseError(f"peira --version did not mention {meta.version}: {cli!r}")
        print(f"ok: peira --version -> {cli}")
        _check([str(venv / "bin" / "peira"), "--help"], "peira --help")
        print("ok: peira --help exits 0 (full CLI wiring)")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Post-publish smoke test")
    parser.add_argument("--version", required=True, help="released version or tag")
    parser.add_argument("--index-url", default=PYPI_INDEX)
    args = parser.parse_args(argv)
    try:
        run_smoke(args.version, index_url=args.index_url)
    except ReleaseError as exc:
        print(f"smoke FAIL: {exc}", file=sys.stderr)
        return 1
    print("smoke PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
