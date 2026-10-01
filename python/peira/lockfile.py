"""Lockfile drift check: warn, never fail, when the installed ML stack
drifts from the pinned lockfile.

docs/Reproducibility.md pins the reproducible environment in
requirements/all.lock. A run on a machine whose torch or transformers
differs from the pin is still a valid run, but its numbers may not
reproduce elsewhere, so the runner warns at run start for adapters
that execute the local ML stack (adapters/hf.py marks itself with
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

#: The lockfile that pins the full reproducible install (dev plus the
#: hf, openai, anthropic, and google extras), relative to the repo root.
LOCKFILE_REL = Path("requirements") / "all.lock"

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
    """Locate requirements/all.lock from the repo checkout, if present."""
    candidate = _repo_root() / LOCKFILE_REL
    return candidate if candidate.is_file() else None


def _normalize_name(name: str) -> str:
    return name.strip().lower().replace("_", "-")


def read_lock_pins(path: Path) -> dict[str, str]:
    """Parse ``name==version`` pins from a pip-compile lockfile.

    Only the first line of each stanza carries the pin; ``--hash``
    continuation lines and ``# via ...`` comments are skipped. Lines
    that are not plain pins (``-e``, ``--extra-index-url``, bare
    names) are ignored rather than misread.
    """
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
        out = stream if stream is not None else sys.stderr
        detail = ", ".join(
            f"{d.package} (locked {d.pinned}, installed {d.installed})"
            for d in drifts
        )
        print(
            "warning: local ML stack differs from requirements/all.lock: "
            f"{detail}. Results may not reproduce on a pinned install.",
            file=out,
        )
    return drifts
