"""peira doctor: local machine readiness checker.

Read-only and side-effect free: no network calls, no downloads, no file
writes. Every check is defensive — a failed probe reports "unknown",
never raises.

Adapter authors declare requirements via an optional ``doctor_requirements``
classmethod on the adapter class::

    @classmethod
    def doctor_requirements(cls) -> list[dict]:
        return [
            {"kind": "env_var", "name": "OPENAI_API_KEY",
             "hint": "export OPENAI_API_KEY=..."},
            {"kind": "python_package", "name": "laya",
             "hint": "pip install laya"},
            {"kind": "binary", "name": "semif-score",
             "alternatives": ["openjev-score"],
             "hint": "clone github.com/theoleecj/semif and pip install -e '.[test]'"},
            {"kind": "ram_gb", "min": 1.5,
             "detail": "smallest Kev model needs ~1.5GB RAM"},
            {"kind": "disk_gb", "min": 5,
             "detail": "Laya weights need ~5GB disk"},
            {"kind": "gpu", "nvidia": True, "scope": "server",
             "detail": "openjev-sglang server needs an NVIDIA GPU on its host",
             "hint": "deploy the server on a CUDA machine"},
        ]

Requirement kinds the doctor knows how to check:
  env_var        — os.environ has the name (value never printed).
                   Multiple env_var entries are treated as any-of:
                   if ANY of them is set, every env_var entry is
                   satisfied. This matches the adapters' real
                   ``_resolve_api_key`` lookup-order semantics
                   (first-set-wins). A case that needs TWO vars set
                   would need a new requirement kind — do not overload
                   env_var for it.
  python_package — importlib.util.find_spec(name) is not None
  binary         — shutil.which(name) is not None
  ram_gb         — system RAM >= min (uses available RAM when known;
                   reports "unknown" when only total is known, e.g. macOS)
  disk_gb        — free disk on cwd volume >= min
  gpu            — a GPU was detected; "nvidia": True requires the
                   detected GPU string to contain "NVIDIA"
                   (case-sensitive substring match)

Optional per-requirement fields:
  scope          — "local" (default) or "server". Hardware requirements
                   (ram_gb, disk_gb, gpu) with "scope": "server" are NOT
                   evaluated against this machine's measurements —
                   the verdict is "unknown" with the detail
                   "server-side requirement — doctor cannot probe the
                   remote host; verify with a dry-run". Server-backed
                   adapters (e.g. kev, openjev-sglang) also get the
                   reachability caveat appended to their verdict detail:
                   "server reachability not checked by doctor (no
                   network calls) — verify with the dry-run".
  detail / hint  — author-written strings shown to the user.

When an adapter defines no ``doctor_requirements``, the doctor falls back
to generic inference: a class-level ``_env_vars`` tuple is checked as
env_var requirements; otherwise the adapter is reported with status
"unknown" and a note that it declares no requirements.

Deferred (deliberately not implemented):
  --fail-on / --json — exit code stays 0 unconditionally (doctor is
  informational, not a gate; see cmd_doctor). Scriptable thresholds and
  machine-readable output are future flags, not bugs.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Shared detail strings for server-scoped requirements
# ---------------------------------------------------------------------------

_SERVER_SIDE_DETAIL = (
    "server-side requirement — doctor cannot probe the remote host; "
    "verify with a dry-run"
)
_SERVER_REACHABILITY_CAVEAT = (
    "server reachability not checked by doctor (no network calls) — "
    "verify with the dry-run"
)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class CheckResult:
    """One system/installation/dataset/pricing check."""

    name: str
    status: str  # "ok" | "warn" | "fail" | "unknown"
    detail: str
    hint: str = ""


@dataclass
class AdapterReadiness:
    """Readiness verdict for one adapter."""

    adapter_name: str
    status: str
    # "ready" | "missing_dependency" | "missing_api_key"
    #   | "insufficient_hardware" | "unknown"
    detail: str
    hint: str = ""


@dataclass
class SystemInfo:
    python_version: str = "unknown"
    ram_total_gb: float | None = None
    ram_available_gb: float | None = None
    disk_free_gb: float | None = None
    cpu_count: int | None = None
    gpu: str | None = None  # human-readable, e.g. "NVIDIA RTX 4090 (24GB)"
    platform: str = ""


@dataclass
class DoctorReport:
    system: SystemInfo = field(default_factory=SystemInfo)
    system_checks: list[CheckResult] = field(default_factory=list)
    install_checks: list[CheckResult] = field(default_factory=list)
    dataset_checks: list[CheckResult] = field(default_factory=list)
    adapters: list[AdapterReadiness] = field(default_factory=list)
    pricing_checks: list[CheckResult] = field(default_factory=list)
    adapter_modules_failed: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# System probes (stdlib only, never raise)
# ---------------------------------------------------------------------------

def _read_ram_linux() -> tuple[float | None, float | None]:
    """(total_gb, available_gb) from /proc/meminfo, or (None, None)."""
    try:
        total = available = None
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total = int(line.split()[1]) / 1024 / 1024
                elif line.startswith("MemAvailable:"):
                    available = int(line.split()[1]) / 1024 / 1024
        return total, available
    except (OSError, ValueError):
        return None, None


def _read_ram_sysconf() -> tuple[float | None, float | None]:
    """POSIX fallback via os.sysconf (total only)."""
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        total = pages * page_size / 1024 / 1024 / 1024
        return total, None
    except (ValueError, OSError, AttributeError):
        return None, None


def _read_ram_macos() -> tuple[float | None, float | None]:
    try:
        out = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0:
            total = int(out.stdout.strip()) / 1024 / 1024 / 1024
            return total, None
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return None, None


def probe_system() -> SystemInfo:
    """Collect system facts. Never raises; unknown fields stay None."""
    info = SystemInfo()
    info.platform = f"{platform.system()} {platform.release()} ({platform.machine()})"
    info.python_version = platform.python_version()
    try:
        info.cpu_count = os.cpu_count()
    except OSError:
        pass

    # RAM
    total, available = None, None
    try:
        if sys.platform.startswith("linux"):
            total, available = _read_ram_linux()
        elif sys.platform == "darwin":
            total, available = _read_ram_macos()
        if total is None:
            total, available = _read_ram_sysconf()
    except Exception:
        pass
    info.ram_total_gb = total
    # Provenance matters: `available` stays None when the probe only knew
    # total (e.g. macOS, sysconf fallback). Callers report available as
    # unknown in that case instead of silently substituting total.
    info.ram_available_gb = available

    # Disk (current volume)
    try:
        usage = shutil.disk_usage(Path.cwd())
        info.disk_free_gb = usage.free / 1024 / 1024 / 1024
    except OSError:
        pass

    # GPU
    info.gpu = probe_gpu()
    return info


def probe_gpu() -> str | None:
    """Human-readable GPU description, or None if none detected.

    Never raises, never takes more than ~5s.
    """
    # NVIDIA via nvidia-smi
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            # Take the first GPU; multi-GPU detail is beyond doctor's remit.
            first = out.stdout.strip().splitlines()[0]
            parts = [p.strip() for p in first.split(",")]
            if len(parts) == 2:
                name, mem_mb = parts
                try:
                    mem_gb = int(mem_mb) / 1024
                    return f"NVIDIA {name} ({mem_gb:.0f}GB)"
                except ValueError:
                    return f"NVIDIA {name}"
            # Garbage stdout (e.g. a driver warning printed by a broken
            # wrapper) is NOT a GPU detection — fall through to "no GPU".
            # A strict == 2 parse is what keeps false positives out.
    except (OSError, subprocess.SubprocessError):
        pass

    # Apple Silicon: ARM64 macOS always has an integrated GPU.
    try:
        if sys.platform == "darwin" and platform.machine() == "arm64":
            chip = platform.processor() or "Apple Silicon"
            # platform.processor() is often empty; try sysctl for the chip name.
            try:
                out = subprocess.run(
                    ["sysctl", "-n", "machdep.cpu.brand_string"],
                    capture_output=True, text=True, timeout=5,
                )
                if out.returncode == 0 and out.stdout.strip():
                    chip = out.stdout.strip()
            except (OSError, subprocess.SubprocessError):
                pass
            return f"{chip} (integrated GPU)"
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Check implementations
# ---------------------------------------------------------------------------

def check_system(info: SystemInfo) -> list[CheckResult]:
    results: list[CheckResult] = []

    # Python version (need 3.12+)
    try:
        parts = info.python_version.split(".")
        major, minor = int(parts[0]), int(parts[1])
        ok = (major, minor) >= (3, 12)
        results.append(CheckResult(
            name="Python",
            status="ok" if ok else "fail",
            detail=f"{info.python_version} (need 3.12+)",
            hint="" if ok else "install Python 3.12 or newer",
        ))
    except (ValueError, IndexError, AttributeError):
        results.append(CheckResult("Python", "unknown", "could not detect", ""))

    # RAM
    ram = info.ram_available_gb
    if ram is None:
        detail = "could not detect"
        if info.ram_total_gb is not None:
            # macOS probes only know total; don't label total "available".
            detail = (f"{info.ram_total_gb:.1f}GB total installed; "
                      "available memory unknown")
        results.append(CheckResult("RAM", "unknown", detail, ""))
    elif ram < 4:
        results.append(CheckResult(
            "RAM", "fail", f"{ram:.1f}GB available (need 4GB minimum)",
            "self-hosted adapters need more RAM; API adapters are fine",
        ))
    elif ram < 8:
        results.append(CheckResult(
            "RAM", "warn", f"{ram:.1f}GB available (8GB+ recommended)",
            "larger self-hosted models (Kev 4b+, SemIf) may not fit",
        ))
    else:
        results.append(CheckResult("RAM", "ok", f"{ram:.1f}GB available", ""))

    # Disk
    disk = info.disk_free_gb
    if disk is None:
        results.append(CheckResult("Disk", "unknown", "could not detect", ""))
    elif disk < 10:
        results.append(CheckResult(
            "Disk", "warn", f"{disk:.1f}GB free (10GB+ recommended)",
            "model weights need several GB; free up disk space",
        ))
    else:
        results.append(CheckResult("Disk", "ok", f"{disk:.1f}GB free", ""))

    # GPU
    if info.gpu:
        results.append(CheckResult("GPU", "ok", info.gpu, ""))
    else:
        results.append(CheckResult(
            "GPU", "warn", "none detected",
            "self-hosted GPU adapters (openjev-sglang) need an NVIDIA GPU; "
            "CPU adapters and API adapters are unaffected",
        ))

    # CPU
    if info.cpu_count:
        results.append(CheckResult(
            "CPU", "ok", f"{info.cpu_count} cores ({info.platform})", ""))
    else:
        results.append(CheckResult("CPU", "unknown", "could not detect", ""))

    return results


def check_installation() -> list[CheckResult]:
    results: list[CheckResult] = []

    # peira imports and reports a version
    try:
        import peira  # noqa: PLC0415
        version = getattr(peira, "__version__", "unknown")
        results.append(CheckResult(
            "peira", "ok", f"version {version}, import works", ""))
    except ImportError as e:
        results.append(CheckResult(
            "peira", "fail", f"import failed: {e}",
            "install with `pip install -e .` from the repo root"))
        return results  # nothing else can be checked

    # Rust core (optional accelerator)
    try:
        from peira._rust import RUST_AVAILABLE  # noqa: PLC0415
        if RUST_AVAILABLE:
            results.append(CheckResult(
                "Rust core", "ok", "peira._core extension importable", ""))
        else:
            results.append(CheckResult(
                "Rust core", "warn", "not built; pure-Python fallback active",
                "run `python scripts/build_core_ext.py` for the accelerator "
                "(optional — results are identical)"))
    except ImportError:
        results.append(CheckResult("Rust core", "unknown",
                                   "could not probe", ""))

    return results


def check_datasets(repo_root: Path) -> list[CheckResult]:
    """Verify each suite's manifest. Imported lazily so doctor works even
    if dataset tooling has issues (each failure is a result, not a crash)."""
    results: list[CheckResult] = []
    try:
        from peira.runner import SUITE_DIRS  # noqa: PLC0415
        from peira.dataset import (  # noqa: PLC0415
            iter_case_lines, verify_manifest,
        )
    except ImportError as e:
        return [CheckResult("datasets", "fail",
                            f"could not load dataset tooling: {e}", "")]

    for suite, rel in sorted(SUITE_DIRS.items()):
        suite_dir = repo_root / rel
        if not suite_dir.exists():
            results.append(CheckResult(
                f"dataset:{suite}", "fail",
                f"directory {rel} not found",
                f"check that {rel} exists in the repo"))
            continue
        manifest = suite_dir / "manifest.json"
        if not manifest.exists():
            results.append(CheckResult(
                f"dataset:{suite}", "fail", "manifest.json missing",
                f"run `peira dataset build-manifest --dir {rel} "
                f"--version <ver>`"))
            continue
        try:
            errors = verify_manifest(suite_dir)
        except Exception as e:  # manifest unreadable/corrupt
            results.append(CheckResult(
                f"dataset:{suite}", "fail",
                f"manifest unreadable: {e}", ""))
            continue
        if errors:
            detail = f"manifest verification failed: {errors[0]}"
            if len(errors) > 1:
                detail += f" (+{len(errors) - 1} more)"
            results.append(CheckResult(
                f"dataset:{suite}", "fail", detail,
                "the dataset files do not match the manifest — "
                "re-clone or rebuild the manifest"))
            continue
        # Count cases (cheap: streams the file; iter_case_lines parses
        # each line as JSON, skipping unparseable lines).
        try:
            n = sum(1 for _ in iter_case_lines(suite_dir))
        except Exception:
            n = -1
        # Short manifest hash for the report
        try:
            import hashlib  # noqa: PLC0415
            digest = hashlib.sha256(
                manifest.read_bytes()).hexdigest()[:8]
        except OSError:
            digest = "?"
        count_str = f"{n} cases" if n >= 0 else "case count unknown"
        results.append(CheckResult(
            f"dataset:{suite}", "ok",
            f"{count_str}, manifest verified ({digest})", ""))
    return results


def check_pricing() -> list[CheckResult]:
    try:
        from peira.pricing import load_pricing_table  # noqa: PLC0415
    except ImportError as e:
        return [CheckResult("pricing", "fail",
                            f"could not load pricing tooling: {e}", "")]
    try:
        table = load_pricing_table()
    except RuntimeError as e:
        return [CheckResult("pricing", "fail", str(e),
                            "check python/peira/data/pricing.json")]
    models = table.get("models", {})
    if not models:
        return [CheckResult("pricing", "fail", "pricing table has no models",
                            "")]
    date = str(table.get("date", "unknown date"))
    # The source field can be a long provenance paragraph; keep the
    # report readable with a short excerpt.
    source = str(table.get("source", "unknown source"))
    if len(source) > 80:
        source = source[:77] + "..."
    return [CheckResult(
        "pricing", "ok",
        f"{len(models)} models priced ({source}, {date})", "")]


# ---------------------------------------------------------------------------
# Adapter discovery and requirement checking
# ---------------------------------------------------------------------------

def _adapter_modules() -> list[str]:
    """Importable adapter module names. Never raises.

    (Returns just a list — import failures are tracked separately in
    ``discover_adapters``, so there is no failed half to report here.)
    """
    adapters_dir = Path(__file__).resolve().parent / "adapters"
    return [
        f"peira.adapters.{path.stem}"
        for path in sorted(adapters_dir.glob("*.py"))
        if not path.name.startswith("_")
    ]


def _iter_adapter_classes(module: Any) -> list[type]:
    """Classes in the module that look like adapters.

    A class counts when it defines a string ``name`` and a ``decide``
    attribute. Abstract bases are excluded explicitly via
    ``_doctor_skip = True`` on the base class (checked in
    ``discover_adapters``). In addition, names containing "base" are
    skipped as a documented backstop: intermediate abstract bases may
    inherit a placeholder ``name`` without re-declaring the opt-out in
    their own ``__dict__`` (e.g. ``_ClassifierBase`` before it got an
    explicit skip), and no shipped adapter has "base" in its name — so
    the backstop can only hide an adapter that a future author named
    "...base...", which a failing ``discover_adapters``-count test would
    surface. The explicit opt-out is the mechanism; the heuristic is the
    net.
    Never raises.
    """
    found: list[type] = []
    for attr_name in dir(module):
        try:
            obj = getattr(module, attr_name)
        except Exception:
            continue
        if not isinstance(obj, type):
            continue
        # Must be defined in this module (not imported from elsewhere).
        if getattr(obj, "__module__", None) != module.__name__:
            continue
        name = getattr(obj, "name", None)
        if not isinstance(name, str) or not name:
            continue
        # Backstop: abstract helpers carry "base" in their placeholder name.
        if "base" in name.lower():
            continue
        if not hasattr(obj, "decide"):
            continue
        found.append(obj)
    return found


def discover_adapters() -> tuple[list[type], list[str]]:
    """(adapter classes, failed module names).

    Guards are ``except Exception``, so this never raises ``Exception`` —
    but a ``BaseException`` (KeyboardInterrupt, SystemExit) raised at
    adapter import time would still propagate. No adapter does that today.
    """
    classes: list[type] = []
    failed: list[str] = []
    for mod_name in _adapter_modules():
        try:
            module = importlib.import_module(mod_name)
        except Exception:
            failed.append(mod_name)
            continue
        try:
            classes.extend(_iter_adapter_classes(module))
        except Exception:
            failed.append(mod_name)
    # Deduplicate by adapter name (subclasses may repeat a parent's name).
    seen: set[str] = set()
    unique: list[type] = []
    for cls in sorted(classes, key=lambda c: str(getattr(c, "name", ""))):
        name = str(getattr(cls, "name", ""))
        if name in seen:
            continue
        seen.add(name)
        unique.append(cls)
    # Drop classes that opt out of doctor discovery (abstract bases whose
    # `name` is a placeholder overridden by every subclass). Check
    # __dict__ so subclasses don't inherit the opt-out.
    concrete = [c for c in unique
                if not c.__dict__.get("_doctor_skip", False)]
    return concrete, failed


def _env_var_is_set(name: str) -> bool:
    """Presence check: empty or whitespace-only values count as missing.

    A var like ``OPENAI_API_KEY=""`` (common after a bad export or a
    redacted template) must report missing, not satisfy the requirement.
    """
    value = os.environ.get(name)
    return value is not None and value.strip() != ""


def _is_server_scoped(req: dict[str, Any]) -> bool:
    return str(req.get("scope", "")).lower() == "server"


def _check_requirement(req: dict[str, Any], info: SystemInfo) -> CheckResult | None:
    """Check one requirement dict. Returns None when satisfied, else a
    CheckResult describing the problem. Never raises."""
    kind = req.get("kind", "")
    name = str(req.get("name", kind))
    hint = str(req.get("hint", ""))
    detail = str(req.get("detail", ""))

    try:
        if kind == "env_var":
            if _env_var_is_set(name):
                return None
            return CheckResult(
                name, "fail", detail or f"{name} not set",
                hint or f"export {name}=...")

        if kind == "python_package":
            if importlib.util.find_spec(name) is not None:
                return None
            return CheckResult(
                name, "fail", detail or f"python package {name!r} not installed",
                hint or f"pip install {name}")

        if kind == "binary":
            names = [name]
            alt = req.get("alternatives")
            if isinstance(alt, list):
                names.extend(str(a) for a in alt if isinstance(a, str))
            if any(shutil.which(n) is not None for n in names):
                return None
            shown = " or ".join(f"{n!r}" for n in names)
            return CheckResult(
                name, "fail", detail or f"{shown} not on PATH",
                hint or f"install {names[0]} and ensure it is on PATH")

        if kind == "ram_gb":
            if _is_server_scoped(req):
                # Needed on the serving host, not this machine — doctor
                # cannot probe the remote host, so never verdict on it.
                return CheckResult(name, "unknown", _SERVER_SIDE_DETAIL, hint)
            need = float(req.get("min", 0))
            have = info.ram_available_gb
            if have is None:
                return CheckResult(name, "unknown",
                                   detail or "could not detect RAM", hint)
            if have >= need:
                return None
            return CheckResult(
                name, "fail",
                detail or f"needs {need:.1f}GB RAM, {have:.1f}GB available",
                hint or "free up RAM or use a bigger machine")

        if kind == "disk_gb":
            if _is_server_scoped(req):
                return CheckResult(name, "unknown", _SERVER_SIDE_DETAIL, hint)
            need = float(req.get("min", 0))
            have = info.disk_free_gb
            if have is None:
                return CheckResult(name, "unknown",
                                   detail or "could not detect disk space",
                                   hint)
            if have >= need:
                return None
            return CheckResult(
                name, "fail",
                detail or f"needs {need:.1f}GB free disk, {have:.1f}GB free",
                hint or "free up disk space")

        if kind == "gpu":
            if _is_server_scoped(req):
                return CheckResult(name, "unknown", _SERVER_SIDE_DETAIL, hint)
            gpu = info.gpu or ""
            if req.get("nvidia"):
                # Case-sensitive substring match on the detected GPU
                # string, e.g. "NVIDIA GeForce ...". probe_gpu only
                # produces such strings from real nvidia-smi output.
                if "NVIDIA" in gpu:
                    return None
                return CheckResult(
                    name, "fail",
                    detail or "no NVIDIA GPU detected",
                    hint or "run on a machine with an NVIDIA GPU")
            if gpu:
                return None
            return CheckResult(
                name, "fail", detail or "no GPU detected",
                hint or "run on a machine with a GPU")

        return CheckResult(name, "unknown",
                           f"unknown requirement kind {kind!r}", "")
    except Exception as e:
        return CheckResult(name, "unknown",
                           f"requirement check failed: {e}", "")


def _generic_requirements(cls: type) -> list[dict[str, Any]]:
    """Fallback requirements when the adapter declares none.

    A class-level ``_env_vars`` tuple becomes env_var requirements —
    this covers every ``_StructuredLLMBase`` subclass without per-class
    boilerplate.
    """
    env_vars = getattr(cls, "_env_vars", ())
    reqs: list[dict[str, Any]] = []
    if isinstance(env_vars, (tuple, list)):
        for var in env_vars:
            if isinstance(var, str) and var:
                # Multiple vars in lookup order: the adapter accepts any
                # one of them, so report them as a group.
                reqs.append({"kind": "env_var", "name": var})
    return reqs


def _any_env_var_set(names: list[str]) -> bool:
    return any(_env_var_is_set(n) for n in names)


def check_adapter(cls: type, info: SystemInfo) -> AdapterReadiness:
    """Readiness verdict for one adapter class. Never raises."""
    name = str(getattr(cls, "name", cls.__name__))
    try:
        # Explicit requirements win; fall back to generic inference.
        reqs: list[dict[str, Any]] | None = None
        doctor_fn = getattr(cls, "doctor_requirements", None)
        if callable(doctor_fn):
            try:
                declared = doctor_fn()
                if isinstance(declared, list):
                    reqs = declared
            except Exception:
                reqs = None
        if reqs is None:
            reqs = _generic_requirements(cls)

        if not reqs:
            return AdapterReadiness(
                name, "unknown",
                "declares no requirements; import works",
                "smoke-test with "
                f"`peira run --adapter {name} --suite trial-demo --dry-run`")

        # A server-scoped requirement (e.g. RAM or an NVIDIA GPU on the
        # serving host) is never probed locally; the verdict must say so
        # explicitly — never let "all requirements met" be the whole story
        # when the most important requirement was never checked.
        server_scoped = any(
            isinstance(r, dict) and _is_server_scoped(r) for r in reqs)

        # env_var groups: the adapter accepts any-of several vars, so if
        # at least one is set the whole group is satisfied.
        env_names = [str(r["name"]) for r in reqs
                     if isinstance(r, dict) and r.get("kind") == "env_var"]
        env_satisfied = _any_env_var_set(env_names) if env_names else False

        # (requirement kind, problem) for each unsatisfied requirement.
        unsatisfied: list[tuple[str, CheckResult]] = []
        for req in reqs:
            if not isinstance(req, dict):
                continue
            kind = str(req.get("kind", ""))
            if kind == "env_var" and env_satisfied:
                continue
            problem = _check_requirement(req, info)
            if problem is not None:
                unsatisfied.append((kind, problem))

        if not unsatisfied:
            detail = "all requirements met"
            if server_scoped:
                detail += f"; {_SERVER_REACHABILITY_CAVEAT}"
            return AdapterReadiness(name, "ready", detail, "")

        kinds = {k for k, _ in unsatisfied}
        details = "; ".join(p.detail for _, p in unsatisfied)
        # Dedupe hints, preserving order (several requirements often share
        # one fix, e.g. torch + transformers -> pip install 'peira[hf]').
        seen_hints: list[str] = []
        for _, p in unsatisfied:
            if p.hint and p.hint not in seen_hints:
                seen_hints.append(p.hint)
        hints = "; ".join(seen_hints)
        if server_scoped:
            details += f"; {_SERVER_REACHABILITY_CAVEAT}"

        # An unknowable measurement must not be labeled insufficient or
        # missing: a server-side requirement, an unprobeable local value,
        # or an unknown kind is honestly "unknown". Check this before the
        # hardware/env classifications below.
        if any(p.status == "unknown" for _, p in unsatisfied):
            return AdapterReadiness(name, "unknown", details, hints)
        if kinds <= {"ram_gb", "disk_gb", "gpu"}:
            return AdapterReadiness(
                name, "insufficient_hardware", details, hints)
        if kinds <= {"env_var"}:
            return AdapterReadiness(name, "missing_api_key", details, hints)
        return AdapterReadiness(name, "missing_dependency", details, hints)
    except Exception as e:
        return AdapterReadiness(name, "unknown",
                                f"readiness check failed: {e}", "")


# ---------------------------------------------------------------------------
# Orchestration and formatting
# ---------------------------------------------------------------------------

_STATUS_MARK = {"ok": "✓", "warn": "!", "fail": "✗", "unknown": "?"}
_ADAPTER_MARK = {
    "ready": "✓",
    "missing_dependency": "✗",
    "missing_api_key": "✗",
    "insufficient_hardware": "✗",
    "unknown": "?",
}


def run_doctor(repo_root: Path) -> DoctorReport:
    """Run every check. Read-only; never raises."""
    report = DoctorReport()
    try:
        report.system = probe_system()
    except Exception:
        pass
    try:
        report.system_checks = check_system(report.system)
    except Exception:
        pass
    try:
        report.install_checks = check_installation()
    except Exception:
        pass
    try:
        report.dataset_checks = check_datasets(repo_root)
    except Exception:
        pass
    try:
        classes, failed = discover_adapters()
        report.adapter_modules_failed = failed
        for cls in classes:
            try:
                report.adapters.append(check_adapter(cls, report.system))
            except Exception:
                report.adapters.append(AdapterReadiness(
                    str(getattr(cls, "name", "?")), "unknown",
                    "check crashed", ""))
    except Exception:
        pass
    try:
        report.pricing_checks = check_pricing()
    except Exception:
        pass
    return report


def format_report(report: DoctorReport) -> str:
    """Human-readable report. Pure function of the report."""
    lines: list[str] = []
    w = lines.append
    w("Peira Doctor")
    w("============")
    w("")

    def section(title: str, checks: list[CheckResult]) -> None:
        w(f"{title}:")
        if not checks:
            w("  (no checks ran)")
        for c in checks:
            mark = _STATUS_MARK.get(c.status, "?")
            w(f"  {c.name}: {mark} {c.detail}")
            if c.hint and c.status in ("warn", "fail"):
                w(f"    hint: {c.hint}")
        w("")

    section("System", report.system_checks)
    section("Installation", report.install_checks)
    section("Dataset", report.dataset_checks)
    section("Pricing", report.pricing_checks)

    w("Adapters:")
    if not report.adapters:
        w("  (none discovered)")
    for a in report.adapters:
        mark = _ADAPTER_MARK.get(a.status, "?")
        status_label = a.status.upper().replace("_", " ")
        w(f"  {a.adapter_name}: {mark} {status_label}"
          + (f" — {a.detail}" if a.detail else ""))
        if a.hint and a.status != "ready":
            w(f"    hint: {a.hint}")
    if report.adapter_modules_failed:
        w("  modules that failed to import: "
          + ", ".join(report.adapter_modules_failed))
    w("")

    ready = sum(1 for a in report.adapters if a.status == "ready")
    total = len(report.adapters)
    w(f"Summary: {ready}/{total} adapters ready. "
      f"Run `peira run --adapter <name> --suite trial-demo --dry-run` "
      f"to smoke-test.")
    return "\n".join(lines)
