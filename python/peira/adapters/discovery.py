"""Third-party adapter discovery via ``entry_points`` (P-4).

The ``peira.adapters`` entry-point group is the plugin registry: a
third-party distribution registers ``<registry id> =
"package.module:ClassName"`` and peira resolves it without a
dotted-path hack and without vendoring the code.

Discovery never imports adapter code: :func:`discover` only reads
``importlib.metadata``. Loading (which executes the module) happens
in :func:`load_registered`, and the runner calls that inside the
subprocess shim for third-party adapters, never in its own process.
See ``docs/Plugin-Ecosystem-Design.md`` section 4.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from importlib import metadata

ENTRY_POINT_GROUP = "peira.adapters"
#: Distribution name of this project; its registrations are first-party.
FIRST_PARTY_DIST = "peira"
#: Registry ids: lowercase ASCII, no dots (dots unambiguously mean a
#: dotted path), not ``mock`` (reserved for the built-in).
ADAPTER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
RESERVED_NAMES = frozenset({"mock"})


class AdapterDiscoveryError(ValueError):
    """The adapter spec could not be resolved to one adapter."""


class AdapterNameCollisionError(AdapterDiscoveryError):
    """Two distributions registered the same registry id."""

    def __init__(self, registry_id: str, claimants: list[str]):
        self.registry_id = registry_id
        self.claimants = claimants
        super().__init__(
            f"adapter name {registry_id!r} claimed by multiple "
            f"distributions: {', '.join(claimants)}"
        )


class AdapterNameMismatchError(ValueError):
    """The loaded adapter's ``name`` did not match its registry id."""

    def __init__(self, registry_id: str, served_name: str):
        self.registry_id = registry_id
        self.served_name = served_name
        super().__init__(
            f"adapter name mismatch: registry {registry_id!r} "
            f"served {served_name!r}"
        )


@dataclass(frozen=True)
class AdapterRegistration:
    """One ``peira.adapters`` entry point."""

    registry_id: str
    #: The entry-point value: ``package.module`` or
    #: ``package.module:ClassName`` (same forms as the dotted-path loader).
    value: str
    dist_name: str | None
    dist_version: str | None
    first_party: bool


@dataclass(frozen=True)
class DiscoveryIssue:
    """A registry entry that could not be used (never fatal)."""

    registry_id: str | None
    message: str


@dataclass(frozen=True)
class DiscoveryResult:
    registrations: dict[str, AdapterRegistration]
    #: registry id -> every claimant (length > 1 means ambiguous).
    ambiguous: dict[str, list[AdapterRegistration]]
    issues: list[DiscoveryIssue] = field(default_factory=list)


def _normalize_dist(name: str | None) -> str | None:
    if name is None:
        return None
    return re.sub(r"[-_.]+", "-", name).lower()


def _validate_name(name: str) -> str | None:
    """Error string for an unusable registry id, else None."""
    if not ADAPTER_NAME_RE.match(name):
        return (
            f"adapter registry id {name!r} does not match "
            r"^[a-z0-9][a-z0-9_-]{1,63}$ (lowercase ASCII, no dots)"
        )
    if name in RESERVED_NAMES:
        return f"adapter registry id {name!r} is reserved"
    if name.startswith("peira-"):
        return (
            f"adapter registry id {name!r} uses the reserved 'peira-' prefix"
        )
    return None


def _is_trusted_first_party(reg: "AdapterRegistration") -> bool:
    """Verify a first-party claim by module location (P1-1).

    The dist ``Name`` is self-asserted metadata; a spoofed
    ``PEIRA-*.dist-info`` on sys.path could claim first-party status
    for attacker code. We resolve the entry-point module with
    ``importlib.util.find_spec`` (without importing) and require its
    origin to live under the already-imported, already-trusted
    ``peira`` package directory.
    """
    if not reg.first_party:
        return False
    try:
        import importlib.util  # noqa: PLC0415
        import peira  # noqa: PLC0415
    except ImportError:
        return False
    # Entry-point value: "package.module" or "package.module:ClassName"
    module_name = reg.value.split(":")[0]
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, AttributeError, ValueError):
        return False
    if spec is None or spec.origin is None:
        return False
    try:
        import os  # noqa: PLC0415

        peira_dir = os.path.dirname(os.path.abspath(peira.__file__))
        module_path = os.path.abspath(spec.origin)
        return module_path.startswith(peira_dir + os.sep)
    except OSError:
        return False


def discover() -> DiscoveryResult:
    """Read the ``peira.adapters`` registry without importing anything.

    Never raises for bad registry content: unusable entries land in
    ``issues`` and ambiguous names in ``ambiguous``. Callers that need
    one adapter use :func:`resolve_spec`, which fails closed.
    """
    by_name: dict[str, list[AdapterRegistration]] = {}
    issues: list[DiscoveryIssue] = []
    try:
        entry_points = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except Exception as exc:  # pragma: no cover - metadata backend failure
        return DiscoveryResult(
            {}, {}, [DiscoveryIssue(None, f"entry-point lookup failed: {exc}")]
        )
    for ep in entry_points:
        err = _validate_name(ep.name)
        if err is not None:
            issues.append(DiscoveryIssue(ep.name, err))
            continue
        dist = ep.dist
        dist_name = dist.metadata["Name"] if dist is not None else None
        reg = AdapterRegistration(
            registry_id=ep.name,
            value=ep.value,
            dist_name=dist_name,
            dist_version=dist.version if dist is not None else None,
            first_party=_normalize_dist(dist_name) == FIRST_PARTY_DIST,
        )
        # P1-1: dist Name is self-asserted; verify the module actually
        # lives inside the trusted peira package before honoring the
        # first-party claim.
        if reg.first_party and not _is_trusted_first_party(reg):
            reg = AdapterRegistration(
                registry_id=reg.registry_id,
                value=reg.value,
                dist_name=reg.dist_name,
                dist_version=reg.dist_version,
                first_party=False,
            )
        by_name.setdefault(ep.name, []).append(reg)
    registrations: dict[str, AdapterRegistration] = {}
    ambiguous: dict[str, list[AdapterRegistration]] = {}
    for name, regs in by_name.items():
        # Same distribution registering the same name twice (e.g. via
        # duplicate metadata) is not a conflict.
        seen: dict[tuple[str | None, str], AdapterRegistration] = {}
        for reg in regs:
            seen.setdefault(
                (_normalize_dist(reg.dist_name), reg.value), reg
            )
        unique = list(seen.values())
        if len(unique) == 1:
            registrations[name] = unique[0]
        else:
            ambiguous[name] = unique
    return DiscoveryResult(registrations, ambiguous, issues)


@dataclass(frozen=True)
class ResolvedSpec:
    """How an adapter spec resolved. ``kind`` is one of ``mock``,
    ``dotted``, or ``registry``. ``registration`` is set only for
    ``registry``."""

    kind: str
    registration: AdapterRegistration | None = None


def resolve_spec(spec: str, result: DiscoveryResult | None = None) -> ResolvedSpec:
    """Resolve an adapter spec without importing adapter code.

    Resolution order (unambiguous by construction: registry ids cannot
    contain dots): ``mock`` -> dotted path (contains ``.`` or ``:``)
    -> registry lookup. Unknown or ambiguous registry ids raise
    :class:`AdapterDiscoveryError`.
    """
    if spec == "mock":
        return ResolvedSpec("mock")
    if "." in spec or ":" in spec:
        return ResolvedSpec("dotted")
    result = result if result is not None else discover()
    if spec in result.ambiguous:
        claimants = [
            f"{r.dist_name} {r.dist_version}" for r in result.ambiguous[spec]
        ]
        raise AdapterNameCollisionError(spec, claimants)
    try:
        return ResolvedSpec("registry", result.registrations[spec])
    except KeyError:
        raise AdapterDiscoveryError(
            f"unknown adapter: {spec!r} (available: 'mock', a dotted path "
            f"like 'examples.minimal_adapter', or a registered adapter id; "
            f"see 'peira adapter list')"
        ) from None


def check_name_binding(registry_id: str, adapter: object) -> None:
    """Enforce the name-vs-attribute binding (design section 4.3).

    A package that registers one registry id but serves an adapter
    whose ``name`` differs fails closed: the confusion deputy cannot
    borrow a trusted name.
    """
    served = getattr(adapter, "name", None)
    if served != registry_id:
        raise AdapterNameMismatchError(registry_id, served)


def load_registered(registration: AdapterRegistration):
    """Import and instantiate a registered adapter.

    Executes the entry point's module: call only inside the subprocess
    shim (third-party) or for first-party / explicitly trusted
    adapters. Enforces the name-vs-attribute binding before returning.
    """
    eps = [
        ep
        for ep in metadata.entry_points(group=ENTRY_POINT_GROUP)
        if ep.name == registration.registry_id and ep.value == registration.value
    ]
    if not eps:
        raise AdapterDiscoveryError(
            f"adapter {registration.registry_id!r} vanished from the "
            f"registry between discovery and load"
        )
    candidate = eps[0].load()
    adapter = candidate() if isinstance(candidate, type) else candidate
    check_name_binding(registration.registry_id, adapter)
    return adapter
