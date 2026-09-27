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
import sys
from importlib.metadata import version as _pkg_version, PackageNotFoundError


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
    }


def fingerprint_env(env: dict | None = None) -> str:
    """Compute the SHA-256 fingerprint of an environment dict.

    Uses canonical JSON (sort_keys=True, no whitespace) so the digest
    is stable across runs and machines.
    """
    if env is None:
        env = collect_env()
    canonical = json.dumps(env, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def collect_and_fingerprint() -> tuple[dict, str]:
    """Collect the environment and return (env_dict, env_sha256)."""
    env = collect_env()
    return env, fingerprint_env(env)


def python_version_tuple() -> tuple[int, int, int]:
    """Current Python version as (major, minor, micro)."""
    return sys.version_info[:3]
