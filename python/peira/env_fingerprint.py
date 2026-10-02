"""Environment fingerprint: the missing link in run reproducibility.

Every run records a fingerprint of the environment it ran in. Today
RunArtifact records peira_version but not the Python version, torch
version, or CUDA version — two runs on different machines can produce
different numbers with no recorded explanation.

The fingerprint collects:
- python: Python version (platform.python_version())
- peira: installed peira version (or git SHA if installed editable)
- rust_backend: whether peira._core was available
- torch, transformers, numpy: versions if installed (None if not)
- cuda: torch.version.cuda if available, else "cpu" or "unavailable"
- os: platform.platform()

The output is canonical JSON (sort_keys=True) plus a SHA-256 digest.
The digest is stored as env_sha256 on RunArtifact and is part of the
analysis lock — any environment change invalidates the lock.
"""

from __future__ import annotations

import hashlib
import json
import platform
from importlib.metadata import version as _pkg_version, PackageNotFoundError

from peira._rust import _impl as _rust, STRICT_RUST


def _safe_version(pkg: str) -> str | None:
    """Return the installed version of pkg, or None if not installed."""
    try:
        return _pkg_version(pkg)
    except PackageNotFoundError:
        return None


def _torch_info() -> dict:
    """Collect torch/CUDA info, or mark as unavailable."""
    info: dict = {"installed": False, "version": None, "cuda": "unavailable"}
    try:
        import torch
    except ImportError:
        return info
    info["installed"] = True
    info["version"] = getattr(torch, "__version__", None)
    try:
        cuda_version = torch.version.cuda
    except Exception:
        cuda_version = None
    if cuda_version:
        info["cuda"] = str(cuda_version)
    else:
        # torch installed but no CUDA build or no GPU
        try:
            if torch.cuda.is_available():
                info["cuda"] = "unknown"
            else:
                info["cuda"] = "cpu"
        except Exception:
            info["cuda"] = "cpu"
    return info


def _peira_install_info() -> dict:
    """How peira is installed: version, and whether editable (dev)."""
    info: dict = {"version": None, "editable": False}
    try:
        from peira import __version__ as v
        info["version"] = v
    except ImportError:
        pass
    # Editable installs have a direct_url.json with
    # "dir_info": {"editable": true}. Check the distribution metadata.
    try:
        from importlib.metadata import distribution
        dist = distribution("peira")
        direct_url = dist.read_text("direct_url.json")
        if direct_url:
            url_info = json.loads(direct_url)
            info["editable"] = bool(
                url_info.get("dir_info", {}).get("editable", False)
            )
    except Exception:
        pass
    return info


def _rust_backend_info() -> dict:
    """Whether the Rust core extension is available."""
    info: dict = {"available": False, "version": None}
    try:
        from peira._rust import _impl
        if _impl is not None:
            info["available"] = True
            info["version"] = _impl.version()
    except Exception:
        pass
    return info


# -- R-17: performance state -----------------------------------------------

import os as _os
import warnings as _warnings


def _read_sysfs(path: str) -> str | None:
    """Read a sysfs/procfs file, returning None when unreadable."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return None


def _cpu_governor() -> str | None:
    """CPU frequency governor (Linux), e.g. 'performance' or 'powersave'."""
    return _read_sysfs(
        "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
    )


def _boost_state() -> str | None:
    """Turbo/boost state: 'on', 'off', or None when unreadable.

    Checks the generic cpufreq boost flag first, then the Intel
    pstate no_turbo flag (inverted: 0 means turbo is on).
    """
    boost = _read_sysfs("/sys/devices/system/cpu/cpufreq/boost")
    if boost == "1":
        return "on"
    if boost == "0":
        return "off"
    no_turbo = _read_sysfs(
        "/sys/devices/system/cpu/intel_pstate/no_turbo"
    )
    if no_turbo == "0":
        return "on"
    if no_turbo == "1":
        return "off"
    return None


def _affinity() -> list[int] | None:
    """CPUs this process may run on, or None when unavailable."""
    try:
        return sorted(_os.sched_affinity(0))
    except (AttributeError, OSError):
        return None


def _smt_enabled() -> bool | None:
    """Whether SMT/hyperthreading is on: cpu0 shares its core, or not."""
    siblings = _read_sysfs(
        "/sys/devices/system/cpu/cpu0/topology/thread_siblings_list"
    )
    if siblings is None:
        return None
    # "0" -> one thread per core; "0-1" or "0,1" -> shared core.
    return "," in siblings or "-" in siblings


def _observed_mhz() -> float | None:
    """Current CPU frequency in MHz, or None when unreadable.

    A point sample, not a sustained measurement: it documents the
    state at collection time so a reader can sanity-check the
    latency numbers, not a benchmark of the machine.
    """
    cur_khz = _read_sysfs(
        "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"
    )
    if cur_khz:
        try:
            return round(float(cur_khz) / 1000.0, 1)
        except ValueError:
            pass
    cpuinfo = _read_sysfs("/proc/cpuinfo")
    if cpuinfo:
        for line in cpuinfo.splitlines():
            if line.startswith("cpu MHz"):
                try:
                    return round(float(line.split(":")[1].strip()), 1)
                except (ValueError, IndexError):
                    pass
    return None


def collect_perf_state() -> dict:
    """Performance-relevant OS/CPU state (R-17).

    Latency numbers are only comparable within one run on one
    machine. This block records the state needed to tell whether a
    cross-run latency comparison is even legitimate: CPU governor,
    boost state, process affinity, SMT state, and an observed
    frequency sample. Unavailable sources are recorded as None with
    a warning, never an exception — a fingerprint must not fail
    because sysfs is unreadable.
    """
    missing: list[str] = []
    governor = _cpu_governor()
    if governor is None:
        missing.append("cpu_governor")
    boost = _boost_state()
    if boost is None:
        missing.append("boost_state")
    affinity = _affinity()
    if affinity is None:
        missing.append("affinity")
    smt = _smt_enabled()
    if smt is None:
        missing.append("smt")
    mhz = _observed_mhz()
    if mhz is None:
        missing.append("observed_mhz")
    if missing:
        _warnings.warn(
            "peira env fingerprint: perf-state sources unavailable, "
            f"recorded as None: {', '.join(missing)}"
        )
    return {
        "cpu_governor": governor,
        "boost_state": boost,
        "affinity": affinity,
        "smt": smt,
        "observed_mhz": mhz,
    }


def collect_env() -> dict:
    """Collect the full environment fingerprint as a dict.

    All values are JSON-serializable. Missing optional dependencies are
    recorded as None, not omitted — the fingerprint must be stable and
    explicit about what was absent.
    """
    torch_info = _torch_info()
    return {
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "peira": _peira_install_info(),
        "rust_backend": _rust_backend_info(),
        "torch": {
            "version": torch_info["version"],
            "cuda": torch_info["cuda"],
        },
        "transformers": _safe_version("transformers"),
        "numpy": _safe_version("numpy"),
        "os": platform.platform(),
        "architecture": platform.machine(),
        "perf_state": collect_perf_state(),
    }


def fingerprint_env_py(env: dict | None = None) -> str:
    """Reference implementation of :func:`fingerprint_env` (pure Python).

    Compute the SHA-256 fingerprint of an environment dict.

    Uses canonical JSON (sort_keys=True, no whitespace) so the digest
    is stable across runs and machines.
    """
    if env is None:
        env = collect_env()
    canonical = json.dumps(env, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def fingerprint_env(env: dict | None = None) -> str:
    """Compute the SHA-256 fingerprint of an environment dict.

    Uses canonical JSON (sort_keys=True, no whitespace) so the digest
    is stable across runs and machines.

    Dispatches to the Rust core when available (environment collection
    itself stays in Python — it is platform I/O); the pure-Python
    :func:`fingerprint_env_py` is the reference and the fallback.
    """
    if env is None:
        env = collect_env()
    if _rust is not None:
        try:
            return _rust.env_fingerprint_env(env)
        except (TypeError, ValueError, OverflowError):
            if STRICT_RUST:
                raise
    return fingerprint_env_py(env)


def collect_and_fingerprint() -> tuple[dict, str]:
    """Collect the environment and return (env_dict, env_sha256)."""
    env = collect_env()
    return env, fingerprint_env(env)
