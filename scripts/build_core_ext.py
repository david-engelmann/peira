#!/usr/bin/env python3
"""Build the optional Rust accelerator (`peira._core`, PyO3).

Compiles `crates/peira-python` and installs the resulting extension module
into `python/peira/` so `from peira import _core` works in this checkout:

    python scripts/build_core_ext.py

The extension is never required: every hot path in `peira.metrics` and
`peira.schema` falls back to the pure-Python reference implementation when
it is absent, so `pip install peira` needs no Rust toolchain. Rebuilding is
only needed after changing `crates/peira-core` or `crates/peira-python`.

Pass `--debug` for a faster debug build (slower at runtime).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG_DIR = ROOT / "python" / "peira"

# cdylib file names produced by cargo, per platform.
CANDIDATES = ("_core.dll", "lib_core.so", "lib_core.dylib")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--debug", action="store_true",
                        help="build in debug mode (faster build, slower runtime)")
    args = parser.parse_args()

    cargo = shutil.which("cargo")
    if cargo is None:
        print("error: the `cargo` binary was not found on PATH.", file=sys.stderr)
        print("Install the Rust toolchain (https://rustup.rs) or keep using the",
              file=sys.stderr)
        print("pure-Python implementation, which needs no build step.", file=sys.stderr)
        return 2

    profile = "debug" if args.debug else "release"
    cmd = [cargo, "build", "-p", "peira-python"]
    if not args.debug:
        cmd.append("--release")
    print(f"$ {' '.join(cmd)}  (in {ROOT})")
    try:
        subprocess.run(cmd, cwd=ROOT, check=True)
    except subprocess.CalledProcessError as e:
        print(f"error: cargo build failed (exit {e.returncode}).", file=sys.stderr)
        return 1

    target_dir = ROOT / "target" / profile
    src = next((target_dir / name for name in CANDIDATES
                if (target_dir / name).is_file()), None)
    if src is None:
        print(f"error: no cdylib found in {target_dir} "
              f"(looked for {', '.join(CANDIDATES)}).", file=sys.stderr)
        return 1

    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    dest = PKG_DIR / f"_core{suffix}"
    shutil.copy2(src, dest)
    print(f"installed {dest.relative_to(ROOT)}")

    # Sanity check: the module must import and report the core version.
    check = subprocess.run(
        [sys.executable, "-c",
         "import sys; sys.path.insert(0, 'python'); "
         "from peira import _core; print('peira._core', _core.version())"],
        cwd=ROOT, capture_output=True, text=True,
    )
    if check.returncode != 0:
        print("error: built extension failed to import:", file=sys.stderr)
        print(check.stderr, file=sys.stderr)
        return 1
    print(check.stdout.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
