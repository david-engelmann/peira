"""Lockfile drift check: warn, never fail, when the installed ML stack
drifts from the pinned lockfile.

The reproducible environment is pinned in uv.lock (PEP 751); older
checkouts used requirements/all.lock, which is still honored when
present. A run on a machine whose torch or transformers differs from
the pin is still a valid run, but its numbers may not reproduce
elsewhere, so the runner warns at run start for adapters that execute
the local ML stack (adapters/hf.py marks itself with
``uses_local_ml_stack``). API adapters are unaffected: the local
environment does not score their calls, so no warning is emitted.

The check never raises: a broken or unreadable lockfile must not break
a run. It also never writes to the artifact: the environment dict
already records the actual installed versions, and env_sha256 seals
them into the analysis lock, so drift is detectable post-hoc.
"""

from __future__ import annotations

import sys
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path
from typing import Any, Callable, NamedTuple

#: Lockfiles that pin the reproducible install, in preference order,
#: relative to the repo root. uv.lock (PEP 751) is current;
#: requirements/all.lock is the legacy pip-compile layout.
LOCKFILE_RELS = (Path("uv.lock"), Path("requirements") / "all.lock")

#: Packages whose drift matters for locally-executed models. torch and
#: transformers change numerics; numpy changes array behavior under
#: them.
WATCHLIST = ("torch", "transformers", "numpy")


class Drift(NamedTuple):
    package: str
    pinned: str
    installed: str


def _repo_root() -> Path:
    # peira/lockfile.py -> peira -> python -> repo root.
    return Path(__file__).resolve().parents[2]


def find_lockfile() -> Path | None:
    """Locate the pinning lockfile from the repo checkout, if present.

    Prefers uv.lock; falls back to the legacy requirements/all.lock.
    """
    root = _repo_root()
    for rel in LOCKFILE_RELS:
        candidate = root / rel
        if candidate.is_file():
            return candidate
    return None


def _normalize_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def read_lock_pins(path: Path) -> dict[str, str]:
    """Parse ``name==version`` pins from a lockfile.

    Dispatches on format: uv.lock (PEP 751 TOML, ``[[package]]``
    sections) versus the legacy pip-compile layout (``name==version``
    lines; ``--hash`` continuations and ``# via ...`` comments are
    skipped). Lines that are not plain pins (``-e``,
    ``--extra-index-url``, bare names) are ignored rather than
    misread.
    """
    if path.name == "uv.lock":
        return _read_uv_lock_pins(path)
    return _read_pip_compile_pins(path)


def _read_pip_compile_pins(path: Path) -> dict[str, str]:
    pins: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", "-", " ")):
            continue
        if "==" not in line:
            continue
        name, _, version = line.partition("==")
        version = version.strip().split()[0].rstrip("\\").strip()
        name = _normalize_name(name)
        if name and version:
            pins[name] = version
    return pins


def _read_uv_lock_pins(path: Path) -> dict[str, str]:
    """Parse ``[[package]]`` name/version pairs from a uv.lock file.

    A minimal line-based TOML read: only the ``name`` and ``version``
    keys inside ``[[package]]`` sections are consumed, so this works
    on Python 3.10 (no tomllib) and adds no dependency. The lockfile
    format version line (``version = 1`` at the top) is outside any
    package section and is never mistaken for a pin.
    """
    pins: dict[str, str] = {}
    name: str | None = None
    in_package = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line == "[[package]]":
            in_package = True
            name = None
            continue
        if line.startswith("["):
            in_package = False
            name = None
            continue
        if not in_package:
            continue
        if line.startswith("name = "):
            name = _normalize_name(
                line.partition("=")[2].strip().strip('"').strip("'")
            )
        elif line.startswith("version = ") and name and name not in pins:
            version = line.partition("=")[2].strip().strip('"').strip("'")
            if version:
                pins[name] = version
    return pins


def installed_version(package: str) -> str | None:
    """Installed version of a package, or None when not installed."""
    try:
        return _pkg_version(_normalize_name(package))
    except PackageNotFoundError:
        return None


def check_drift(
    *,
    pins: dict[str, str] | None = None,
    installed: Callable[[str], str | None] | None = None,
) -> list[Drift]:
    """Compare lockfile pins against installed versions.

    Returns one Drift per watchlisted package whose installed version
    differs from the pin. Packages missing from the lockfile or not
    installed are skipped: an uninstallable pin is a lockfile problem,
    not a drift, and a missing package fails fast elsewhere.
    """
    if pins is None:
        lockfile = find_lockfile()
        if lockfile is None:
            return []
        try:
            pins = read_lock_pins(lockfile)
        except OSError:
            return []
    get_version = installed or installed_version
    drifts: list[Drift] = []
    for package in WATCHLIST:
        pinned = pins.get(_normalize_name(package))
        if not pinned:
            continue
        try:
            have = get_version(package)
        except Exception:
            continue
        if have is not None and have != pinned:
            drifts.append(Drift(package, pinned, have))
    return drifts


def warn_if_drifted(adapter: Any, stream: Any = None) -> list[Drift]:
    """Warn on stderr when a local-ML-stack adapter drifts from the lockfile.

    Only adapters with ``uses_local_ml_stack`` set (adapters/hf.py)
    are checked. Never raises: the warning is advisory, and a broken
    check must not break a run.
    """
    if not getattr(adapter, "uses_local_ml_stack", False):
        return []
    try:
        drifts = check_drift()
    except Exception:
        return []
    if drifts:
        lockfile = find_lockfile()
        lock_name = lockfile.name if lockfile is not None else "the lockfile"
        out = stream if stream is not None else sys.stderr
        detail = ", ".join(
            f"{d.package} (locked {d.pinned}, installed {d.installed})"
            for d in drifts
        )
        print(
            f"warning: local ML stack differs from {lock_name}: "
            f"{detail}. Results may not reproduce on a pinned install.",
            file=out,
        )
    return drifts
