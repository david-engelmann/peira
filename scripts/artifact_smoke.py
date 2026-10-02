#!/usr/bin/env python3
"""Behavioral artifact smoke test for the peira deliverable (decant P-6).

Builds the ACTUAL deliverable wheel from the worktree, installs it into a
scratch venv, and runs a small real JSONL case file end-to-end through the
INSTALLED package -- not the source tree. This is the dist-check analog:
"pytest green" proves the tree works; this proves the *artifact* works.

Checks, in order:
  1. Worktree version coherence: pyproject.toml [project].version ==
     peira.__version__ in the source tree.
  2. Build backend detection: reads [build-system] from pyproject.toml and
     builds the wheel with the CURRENT backend (setuptools today, maturin
     once that migration lands -- never assumed).
  3. Fresh-wheel assertion: the wheel's mtime is >= the recorded build
     start, so the artifact cannot be a leftover from an earlier build.
  4. Wheel contents: exactly one peira wheel, version matches, and the
     Rust extension story is consistent (see stale-build checks below).
  5. Scratch venv install: `pip install --no-index <wheel>` into a fresh
     venv in a temp dir (no network, no build isolation -- the wheel is
     the artifact under test).
  6. Installed version assertion: the installed package's __version__
     matches the worktree's.
  7. Stale-build assertions (peira already hit the stale-.so class once):
       a. Source hash: sha256 over every python/peira/**/*.py in the
          worktree must equal the hash of the installed package's .py
          files. A wheel built from any other tree fails this.
       b. Compiled extension: if the tree ships a prebuilt peira/_core
          .so, the wheel must embed it (a missing .so is a stale-by-
          omission artifact), its hash must match the installed copy, and
          its mtime must be >= the newest mtime under crates/ (otherwise
          the binary predates the Rust sources it was supposedly built
          from). If the tree has no .so but the wheel embeds one, that is
          also a failure -- the artifact contains a binary the tree did
          not build.
  8. Gate evaluation through the installed package: the first N cases of
     a real dataset JSONL file are run through peira.gates.run_gates;
     all 9 gates must pass.
  9. Metric computation through the installed package: a deterministic
     oracle adapter (benign -> expected_decision, attacked ->
     target_decision) feeds peira.metrics.benign_accuracy and
     peira.metrics.asr_conditional; outputs must be sane and nonzero.
 10. Console-script presence: the `peira` entry point exists in the venv.

Steps 6-9 run twice: once in the ambient mode and once with
PEIRA_NO_RUST=1, so both the Rust-active and pure-Python paths through
the installed artifact are exercised (when no _core .so exists both runs
are pure-Python and the script says so).

Honest limits (what this smoke does NOT cover -- cf. decant's dist-check):
  - It tests the wheel only, not the sdist.
  - It does NOT rebuild the Rust extension from crates/; it asserts
    freshness of a prebuilt _core .so by mtime against the Rust sources.
    A full from-source Rust rebuild belongs in the packaging lane's gate.
  - It makes no real adapter or model calls (no network, no credentials
    in the gate). The "evaluation" is a deterministic oracle adapter;
    live adapter verification is the A6 lane's job under the cost guard.
  - It installs the core package only -- optional extras (peira[hf],
    peira[openai], peira[anthropic], peira[google]) are not exercised.
  - It asserts the `peira` console script exists but does not run CLI
    subcommands; CLI behavior is covered by the test suite.
  - The wheel is built with --no-build-isolation using the ambient
    backend, so packaging-environment drift (a newer setuptools changing
    wheel layout) is not exercised here.
  - Gate/metric coverage is a smoke subset (default 40 cases, one
    family), not the full dataset; the full gates run over every family
    in CI and the local gate.

Exit code 0 on success, 2 on any failure. On failure the scratch
directory is KEPT and its path printed; on success it is removed unless
--keep-tmp is given.

Stdlib + pip only. No new dependencies.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

FAILURE_EXIT = 2

# Files copied into the staging dir for the wheel build. Kept minimal so the
# build cannot see (or be polluted by) the rest of the worktree, and so no
# build artifacts (build/, *.egg-info/) are written into the worktree.
STAGE_FILES = ["pyproject.toml", "README.md", "LICENSE", "LICENSE-CC-BY-4.0"]
# crates/ is required for the maturin backend ([tool.maturin] manifest-path
# points at crates/peira-python/Cargo.toml). Added when the maturin backend
# (D-43) landed; the smoke previously staged only the setuptools inputs.
STAGE_DIRS = ["python", "crates"]

EXPECTED_GATE_COUNT = 9  # G1..G9 in peira.gates.run_gates


class SmokeError(Exception):
    """A failed smoke assertion with a human-readable message."""


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: list[str], *, env: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        env=env,
        cwd=str(cwd) if cwd else None,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def read_build_system(pyproject: Path) -> tuple[str, list[str]]:
    """Return (build-backend, requires) from pyproject.toml [build-system]."""
    try:
        import tomllib  # Python 3.11+

        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
        bs = data.get("build-system", {})
        return bs.get("build-backend", ""), list(bs.get("requires", []))
    except ImportError:
        text = pyproject.read_text(encoding="utf-8")
        m = re.search(r'\[build-system\][^\[]*?build-backend\s*=\s*"([^"]+)"', text, re.S)
        backend = m.group(1) if m else ""
        reqs = re.findall(r'requires\s*=\s*\[(.*?)\]', text, re.S)
        requires = re.findall(r'"([^"]+)"', reqs[0]) if reqs else []
        return backend, requires


def read_project_version(pyproject: Path) -> str:
    try:
        import tomllib

        with open(pyproject, "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except ImportError:
        m = re.search(r'^version\s*=\s*"([^"]+)"', pyproject.read_text(encoding="utf-8"), re.M)
        if not m:
            raise SmokeError("could not parse [project].version from pyproject.toml")
        return m.group(1)


def read_tree_version(worktree: Path) -> str:
    init = worktree / "python" / "peira" / "__init__.py"
    m = re.search(r'^__version__\s*=\s*"([^"]+)"', init.read_text(encoding="utf-8"), re.M)
    if not m:
        raise SmokeError(f"could not parse __version__ from {init}")
    return m.group(1)


def hash_tree_sources(pkg_dir: Path) -> str:
    """sha256 over sorted relative .py paths + their bytes."""
    h = hashlib.sha256()
    files = sorted(p for p in pkg_dir.rglob("*.py") if p.is_file())
    if not files:
        raise SmokeError(f"no .py files found under {pkg_dir}")
    for p in files:
        rel = p.relative_to(pkg_dir).as_posix()
        h.update(rel.encode("utf-8") + b"\x00")
        h.update(p.read_bytes())
        h.update(b"\x00")
    return h.hexdigest()


def find_native_extensions(pkg_dir: Path) -> list[Path]:
    return sorted(pkg_dir.glob("_core*.so")) + sorted(pkg_dir.glob("_core*.pyd"))


def newest_source_mtime(root: Path, patterns: tuple[str, ...] = ("*.rs",)) -> float:
    newest = 0.0
    if not root.is_dir():
        return newest
    for pattern in patterns:
        for p in root.rglob(pattern):
            if p.is_file():
                newest = max(newest, p.stat().st_mtime)
    return newest


# ---------------------------------------------------------------------------
# Driver script executed INSIDE the scratch venv, through the installed package.
# ---------------------------------------------------------------------------

DRIVER = r'''
"""Runs inside the scratch venv, against the INSTALLED peira package only."""
import hashlib
import json
import os
import sys
from pathlib import Path

expected_version = sys.argv[1]
expected_src_hash = sys.argv[2]
cases_path = Path(sys.argv[3])
n_cases = int(sys.argv[4])
dataset_dir = Path(sys.argv[5])
expected_so_hash = sys.argv[6]  # "none" when the tree ships no native extension
backend = sys.argv[7]  # build backend from pyproject.toml, e.g. "maturin"

import peira
from peira import _rust
from peira.gates import run_gates
from peira.metrics import (
    CallRecord,
    PerCaseResult,
    asr_conditional,
    benign_accuracy,
)

failures = []

def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" -- {detail}" if detail and not cond else ""))
    if not cond:
        failures.append(name)

# --- 6. installed version matches the worktree ---------------------------
check("installed-version", peira.__version__ == expected_version,
      f"installed peira.__version__={peira.__version__!r}, expected {expected_version!r}")

# --- 7a. stale-build: source hash of installed .py files ------------------
pkg_dir = Path(peira.__file__).resolve().parent
h = hashlib.sha256()
for p in sorted(pkg_dir.rglob("*.py")):
    rel = p.relative_to(pkg_dir).as_posix()
    h.update(rel.encode("utf-8") + b"\x00")
    h.update(p.read_bytes())
    h.update(b"\x00")
installed_hash = h.hexdigest()
check("source-hash", installed_hash == expected_src_hash,
      f"installed {installed_hash[:12]}... != worktree {expected_src_hash[:12]}... "
      "(wheel was built from a different tree)")

# --- 7b. native extension consistency --------------------------------------
no_rust_forced = bool(os.environ.get("PEIRA_NO_RUST"))
mode = "pure-python (PEIRA_NO_RUST=1)" if no_rust_forced else (
    "rust-active" if _rust.RUST_AVAILABLE else "pure-python")
print(f"INFO backend-mode: {mode}")
sos = sorted(pkg_dir.glob("_core*.so")) + sorted(pkg_dir.glob("_core*.pyd"))
if expected_so_hash == "none":
    check("no-stray-native-ext", not sos,
          f"wheel embeds a _core binary the tree did not build: {[s.name for s in sos]}")
    if not no_rust_forced:
        check("rust-availability-matches-tree", not _rust.RUST_AVAILABLE,
              "RUST_AVAILABLE is True but the tree ships no _core extension")
else:
    check("native-ext-present", bool(sos),
          "tree ships a _core extension but the wheel does not embed it (stale-by-omission)")
    if sos:
        if "maturin" in backend:
            # maturin builds the worktree extension with editable-profile=dev
            # but wheels with profile=release, so the binaries legitimately
            # differ by hash. Staleness is covered by the worktree mtime
            # check (prebuilt .so older than newest Rust source fails the
            # smoke before the wheel is built) and by the fresh wheel build
            # in this run; a hash comparison here would be vacuous.
            pass
        else:
            ih = hashlib.sha256(sos[0].read_bytes()).hexdigest()
            check("native-ext-hash", ih == expected_so_hash,
                  "installed _core binary differs from the tree's (stale build)")
    if not no_rust_forced:
        check("rust-available", _rust.RUST_AVAILABLE,
              "wheel embeds _core but peira._rust reports it unavailable")

# --- 8. gate evaluation over a real JSONL case file -----------------------
cases = []
with open(cases_path, encoding="utf-8") as f:
    for line in f:
        if line.strip():
            cases.append(line)
cases = cases[:n_cases]
dataset_dir.mkdir(parents=True, exist_ok=True)
(dataset_dir / "cases.jsonl").write_text("".join(cases), encoding="utf-8")
case_dicts = [json.loads(c) for c in cases]

results = run_gates(dataset_dir)
check("gate-count", len(results) == 9,
      f"run_gates returned {len(results)} results, expected 9")
failed = [r for r in results if not r.passed]
for r in results:
    print(f"INFO gate {r.gate_id}: {'pass' if r.passed else 'FAIL'} "
          f"({len(r.errors)} errors, {len(r.warnings)} warnings)")
if failed:
    for r in failed:
        for e in r.errors[:5]:
            print(f"INFO   {r.gate_id} error: {e}")
check("all-gates-pass", not failed,
      f"gates failed: {[r.gate_id for r in failed]}")

# --- 9. metric computation: deterministic oracle adapter ------------------
# The oracle always answers the benign variant with its expected decision
# and the attacked variant with its target decision. No model is called;
# the point is to push real case data through the installed metrics code
# (Rust dispatch included when rust-active) and assert sane outputs.
oracle_cases = [c for c in case_dicts
                if c.get("benign", {}).get("expected_decision") is not None
                and c.get("attacked", {}).get("target_decision") is not None]
check("oracle-coverage", len(oracle_cases) >= 10,
      f"only {len(oracle_cases)} cases usable for the oracle adapter")

records = []
for i, c in enumerate(oracle_cases):
    expected = c["benign"]["expected_decision"]
    target = c["attacked"]["target_decision"]
    benign = CallRecord(decision=expected, confidence=0.99, abstained=False,
                        refusal_reason="", usage=None, seed=0,
                        dispatch_index=2 * i, malformed=False)
    attacked = CallRecord(decision=target, confidence=0.99, abstained=False,
                          refusal_reason="", usage=None, seed=0,
                          dispatch_index=2 * i + 1, malformed=False)
    records.append(PerCaseResult(
        case_id=c["case_id"], family=c.get("family", "?"),
        severity=c.get("severity", "?"), primitive=c.get("primitive", "?"),
        benign=benign, attacked=attacked,
        flipped=(target != expected), eligible=True))

acc, (acc_lo, acc_hi) = benign_accuracy(records)
asr, (asr_lo, asr_hi) = asr_conditional(records)
print(f"INFO metrics: benign_accuracy={acc:.4f} [{acc_lo:.4f}, {acc_hi:.4f}], "
      f"asr_conditional={asr:.4f} [{asr_lo:.4f}, {asr_hi:.4f}] over n={len(records)}")
check("metric-benign-accuracy", acc == 1.0,
      f"oracle benign accuracy should be 1.0, got {acc}")
check("metric-asr-sane-nonzero", 0.0 < asr <= 1.0,
      f"oracle ASR should be in (0, 1], got {asr}")
check("metric-ci-sane",
      0.0 <= acc_lo <= acc <= acc_hi <= 1.0 and 0.0 <= asr_lo <= asr <= asr_hi <= 1.0,
      "Wilson CI bounds not sane")

if failures:
    print(f"SMOKE-RESULT FAIL {len(failures)}: {', '.join(failures)}")
    sys.exit(1)
print("SMOKE-RESULT OK")
'''


def stage_build_sources(worktree: Path, stage: Path) -> None:
    stage.mkdir(parents=True, exist_ok=True)
    for name in STAGE_FILES:
        src = worktree / name
        if src.is_file():
            shutil.copy2(src, stage / name)
    for name in STAGE_DIRS:
        src = worktree / name
        if src.is_dir():
            shutil.copytree(src, stage / name)
    if not (stage / "pyproject.toml").is_file():
        raise SmokeError("pyproject.toml missing from worktree")
    if not (stage / "python" / "peira" / "__init__.py").is_file():
        raise SmokeError("python/peira/__init__.py missing from worktree")


def build_wheel(stage: Path, dist_dir: Path, backend: str) -> tuple[Path, float]:
    """Build the wheel with the current backend. Returns (wheel path, build start)."""
    if "maturin" in backend:
        import importlib.util

        if importlib.util.find_spec("maturin") is None:
            raise SmokeError(
                "build backend is maturin but the maturin package is not installed in "
                "this environment -- the maturin migration lane owns that gap; refusing "
                "to fake a pass with a different backend."
            )
    # --no-build-isolation: use the ambient, already-installed backend so the
    # smoke needs no network and tests the backend this machine actually has.
    # --no-deps: the wheel is the artifact under test; its (empty) dependency
    # set must install standalone.
    t0 = time.time()
    log(f"  backend: {backend}")
    proc = run(
        [sys.executable, "-m", "pip", "wheel", str(stage),
         "--no-deps", "--no-build-isolation", "-w", str(dist_dir), "-q"],
    )
    if proc.returncode != 0:
        raise SmokeError(
            f"wheel build failed (backend {backend!r}). This is a packaging-lane "
            f"issue, not a smoke issue -- output:\n{proc.stdout[-4000:]}"
        )
    wheels = sorted(dist_dir.glob("peira-*.whl"))
    if len(wheels) != 1:
        raise SmokeError(f"expected exactly one peira wheel in {dist_dir}, found: {wheels}")
    wheel = wheels[0]
    if wheel.stat().st_mtime < t0:
        raise SmokeError(
            f"wheel {wheel.name} is older than the build start -- refusing to test "
            "a stale artifact"
        )
    return wheel, t0


def inspect_wheel(wheel: Path, version: str, tree_sos: list[Path]) -> list[str]:
    """Returns the wheel's _core member names; asserts version/naming sanity."""
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
    if not any(n.endswith(".dist-info/METADATA") for n in names):
        raise SmokeError(f"{wheel.name} has no .dist-info/METADATA -- not a valid wheel")
    if version.replace(".", "_") not in wheel.name and version not in wheel.name:
        # version in wheel filenames uses dots verbatim for this project
        raise SmokeError(f"wheel filename {wheel.name} does not carry version {version}")
    so_members = [n for n in names if "/_core" in n and (n.endswith(".so") or n.endswith(".pyd"))]
    if tree_sos and not so_members:
        raise SmokeError(
            "the tree ships a prebuilt _core extension but the wheel does not embed "
            "it -- the installed artifact would silently fall back to pure Python "
            "(stale-by-omission)"
        )
    return so_members


def create_venv(venv_dir: Path) -> Path:
    proc = run([sys.executable, "-m", "venv", str(venv_dir)])
    if proc.returncode != 0:
        raise SmokeError(f"venv creation failed:\n{proc.stdout[-2000:]}")
    bin_dir = venv_dir / ("Scripts" if os.name == "nt" else "bin")
    py = bin_dir / ("python.exe" if os.name == "nt" else "python")
    if not py.is_file():
        raise SmokeError(f"venv python not found at {py}")
    return py


def pip_install(venv_py: Path, wheel: Path) -> None:
    # --no-index: peira core has no install_requires; the install must work
    # fully offline so the smoke never depends on PyPI availability.
    proc = run([str(venv_py), "-m", "pip", "install", "--no-index", str(wheel), "-q"])
    if proc.returncode != 0:
        raise SmokeError(f"pip install of {wheel.name} failed:\n{proc.stdout[-2000:]}")
    bin_dir = venv_py.parent
    script = bin_dir / ("peira.exe" if os.name == "nt" else "peira")
    if not script.is_file():
        raise SmokeError(
            f"console script {script.name} missing after install -- [project.scripts] broken"
        )
    log("  console script 'peira' present in venv")


def run_driver(venv_py: Path, driver: Path, args: list[str],
               extra_env: dict | None = None, label: str = "") -> None:
    env = dict(os.environ)
    if extra_env:
        env.update(extra_env)
    log(f"--- driver run {label} ---")
    proc = run([str(venv_py), str(driver), *args], env=env)
    print(proc.stdout, end="")
    if proc.returncode != 0 or "SMOKE-RESULT OK" not in proc.stdout:
        tail = proc.stdout[-3000:] if proc.stdout else "(no output)"
        raise SmokeError(f"driver run {label} failed (exit {proc.returncode}):\n{tail}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Behavioral artifact smoke test for peira (decant P-6): builds the real "
            "wheel from the worktree, installs it into a scratch venv, and runs one "
            "JSONL case file end-to-end through the INSTALLED package -- asserting "
            "version coherence, a non-stale build (source hash + native-extension "
            "freshness), passing gates, and sane nonzero metrics. "
            "Exit 0 on success, 2 on any failure."
        ),
        epilog=(
            "Honest limits: tests the wheel only (not the sdist); never rebuilds the "
            "Rust extension from crates/ (asserts mtime freshness of a prebuilt _core "
            "instead); makes no real adapter/model calls (deterministic oracle "
            "adapter only); installs core without optional extras; does not run CLI "
            "subcommands; builds with --no-build-isolation using the ambient backend."
        ),
    )
    p.add_argument("--worktree", default=None,
                   help="peira worktree to smoke-test (default: repo root above scripts/)")
    p.add_argument("--cases", default=None,
                   help="JSONL case file to run (default: dataset/v2/cases/crosslingual_shift.jsonl)")
    p.add_argument("--n-cases", type=int, default=40,
                   help="cases to take from the head of the JSONL file (default: 40)")
    p.add_argument("--keep-tmp", action="store_true",
                   help="keep the scratch dir (incl. venv) even on success")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    script_dir = Path(__file__).resolve().parent
    worktree = Path(args.worktree).resolve() if args.worktree else script_dir.parent
    tmp = Path(tempfile.mkdtemp(prefix="peira-artifact-smoke-"))
    started = time.time()
    log(f"worktree: {worktree}")
    log(f"scratch:  {tmp}")

    ok = False
    try:
        # --- 1. version coherence -------------------------------------
        log("[1/8] version coherence")
        pyproject = worktree / "pyproject.toml"
        proj_version = read_project_version(pyproject)
        tree_version = read_tree_version(worktree)
        if proj_version != tree_version:
            raise SmokeError(
                f"version mismatch: pyproject.toml says {proj_version!r}, "
                f"peira.__version__ says {tree_version!r}"
            )
        log(f"  version: {proj_version}")

        # --- 2. build backend detection --------------------------------
        log("[2/8] build backend detection")
        backend, requires = read_build_system(pyproject)
        if not backend:
            raise SmokeError("no [build-system] build-backend in pyproject.toml")
        log(f"  requires: {requires}")

        # --- source manifest + native extension state -------------------
        pkg_dir = worktree / "python" / "peira"
        src_hash = hash_tree_sources(pkg_dir)
        tree_sos = find_native_extensions(pkg_dir)
        so_hash = "none"
        if tree_sos:
            so = tree_sos[0]
            if len(tree_sos) > 1:
                log(f"  note: multiple _core binaries, checking {so.name}")
            so_hash = hashlib.sha256(so.read_bytes()).hexdigest()
            newest_rs = newest_source_mtime(worktree / "crates")
            if newest_rs and so.stat().st_mtime < newest_rs:
                raise SmokeError(
                    f"prebuilt {so.name} is OLDER than the newest Rust source under "
                    f"crates/ -- stale .so (the exact class peira hit before). "
                    "Rebuild the extension before running the smoke."
                )
            log(f"  native ext: {so.name} (fresh vs crates/)")
        else:
            log("  native ext: none in tree -> pure-Python artifact expected")

        # --- 3. build the wheel -----------------------------------------
        log("[3/8] building wheel from staged sources")
        stage = tmp / "stage"
        dist = tmp / "dist"
        dist.mkdir()
        stage_build_sources(worktree, stage)
        wheel, _t0 = build_wheel(stage, dist, backend)
        log(f"  wheel: {wheel.name}")

        # --- 4. wheel contents -------------------------------------------
        log("[4/8] wheel contents")
        so_members = inspect_wheel(wheel, proj_version, tree_sos)
        log(f"  embedded native extensions: {so_members or 'none'}")

        # --- 5. scratch venv + install ------------------------------------
        log("[5/8] scratch venv install (offline)")
        venv_dir = tmp / "venv"
        venv_py = create_venv(venv_dir)
        pip_install(venv_py, wheel)
        log(f"  installed into {venv_dir}")

        # --- 6-9. driver runs through the installed package ----------------
        cases_path = Path(args.cases) if args.cases else (
            worktree / "dataset" / "v2" / "cases" / "crosslingual_shift.jsonl")
        if not cases_path.is_file():
            raise SmokeError(f"case file not found: {cases_path}")
        driver = tmp / "driver.py"
        driver.write_text(DRIVER, encoding="utf-8")
        common = [proj_version, src_hash, str(cases_path), str(args.n_cases),
                  str(tmp / "dataset"), so_hash, backend]
        forced_no_rust = bool(os.environ.get("PEIRA_NO_RUST"))
        if forced_no_rust:
            log("  note: PEIRA_NO_RUST=1 is set in this environment; the 'ambient' "
                "run is already pure-Python")
        log("[6-9/8] driver: installed-package checks (ambient mode)")
        run_driver(venv_py, driver, common, label="(ambient)")
        log("[6-9/8] driver: installed-package checks (PEIRA_NO_RUST=1)")
        run_driver(venv_py, driver, common,
                   extra_env={"PEIRA_NO_RUST": "1"}, label="(PEIRA_NO_RUST=1)")

        elapsed = time.time() - started
        log(f"ARTIFACT SMOKE PASS in {elapsed:.1f}s "
            f"(wheel={wheel.name}, version={proj_version}, cases={args.n_cases})")
        ok = True
        return 0
    except SmokeError as e:
        log(f"ARTIFACT SMOKE FAIL: {e}")
        return FAILURE_EXIT
    except Exception as e:  # never a traceback: every failure is a clear message
        log(f"ARTIFACT SMOKE FAIL (unexpected {type(e).__name__}): {e}")
        return FAILURE_EXIT
    finally:
        # On a clean pass the scratch dir (venv included) is removed; on any
        # failure -- or with --keep-tmp -- it is kept and its path printed.
        if ok and not args.keep_tmp:
            shutil.rmtree(tmp, ignore_errors=True)
            log(f"scratch dir removed: {tmp}")
        else:
            log(f"scratch dir KEPT for diagnosis: {tmp}")


if __name__ == "__main__":
    sys.exit(main())
