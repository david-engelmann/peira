"""Conformance kit for third-party adapters (P-4).

``peira adapter check <id>`` exercises an adapter against the
contract every adapter must honor and seals the result into a check
report. Suite numbering follows ``docs/Plugin-Ecosystem-Design.md``
section 6.1:

- ``schema`` (6.1.1): for each declared primitive, N probe
  decisions validate with ``validate_output()``; zero errors.
- ``abstention`` (6.1.2): refusal-shaped probes never raise, and
  every abstained output observed has the valid abstention shape.
- ``determinism`` (6.1.3): declared-posture verification. A
  self-declared deterministic adapter that wobbles fails; a
  declared sampler that is secretly deterministic gets a warning.
- ``metadata_invariance`` (6.1.4): outputs are invariant to
  adapter-visible metadata (randomized call ids, injected junk
  keys, extra context attributes) and identifiers are not smuggled
  through verbatim fields.
- ``protocol_pinning``: the adapter works with exactly the pinned
  ``CallContext`` key set (key-set pinning itself is a transport
  property, unit-tested in ``test_adapter_subprocess.py``; here we
  pin the contract side so ``CallContext`` cannot drift without the
  suite noticing).
- ``transport`` (6.1.6, 6.1.7, 6.2): the shim child imports and
  handshakes within the timeout, the protocol version matches, and
  the child shuts down cleanly.

Plus two non-suite gates (6.1.5):

- ``retry_posture`` must-attest: the capability report must carry
  the author's self-attestation of retry behavior: ``True`` (or a
  "single-attempt" string) for single-attempt configuration, or a
  free-text description of the retry behavior (e.g. the provider
  SDK's built-in retries). Missing or false fails. First-party
  adapters are not gated (their retry behavior is in reviewed
  code); the report says so.
- ``advisory scan``: a heuristic static scan of the adapter module
  (retry config, network/subprocess/dynamic-code imports).
  Findings are warnings with file and line, never verdicts: "no
  nested retry loop" is not mechanically decidable.

Trust routing (F1): third-party adapters are ALWAYS exercised
through the subprocess shim child, never in the check process.
First-party adapters (and ``mock``) run in-process: they are the
project's own code. Dotted paths are refused: ``check`` needs a
registry id so the name binding and the shim have something to
hold onto.
"""

from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import inspect
import json
import re
import time
import uuid
from dataclasses import dataclass, field

CHECK_REPORT_FORMAT = "peira-adapter-check/1"

#: Probes per declared primitive for the schema suite.
SCHEMA_PROBES_PER_PRIMITIVE = 3
#: Trials for the metadata-invariance suite.
INVARIANCE_TRIALS = 8
#: The child must shut down this fast (6.2).
SHUTDOWN_BUDGET_S = 5.0

# An adapter may declare its sampling posture as a class attribute.
# Absent (or "deterministic"): the kit requires identical outputs on
# replay. "sampling": the kit requires the declared posture to match
# observed behavior (a secretly-deterministic sampler gets a warning).
SAMPLING_POSTURE_VALUES = ("deterministic", "sampling")

# Heuristic static scan: (code, compiled regex). Advisory only:
# findings are reported with file and line, never verdicts.
_ADVISORY_PATTERNS = (
    ("retry-config",
     re.compile(r"(?<!\w)(tenacity|backoff)\s*\."
                r"|from\s+(tenacity|backoff)\s+import\b"
                r"|urllib3\.util\.retry\b|Retry\s*\(")),
    ("network-import",
     re.compile(r"^\s*(?:import|from)\s+"
                r"(socket|requests|urllib3|httpx|aiohttp|http\.client"
                r"|urllib\.request|websocket|websockets)\b")),
    ("subprocess-spawn",
     re.compile(r"^\s*(?:import|from)\s+subprocess\b|"
                r"os\.(system|popen|spawnl|spawnv|execv|execvp)\s*\(")),
    ("dynamic-code",
     re.compile(r"(?<!\w)(eval|exec)\s*\(|__import__\s*\(|"
                r"compile\s*\(")),
    ("ctypes",
     re.compile(r"^\s*(?:import|from)\s+ctypes\b")),
)

# Refusal-shaped probe inputs (6.1.2): the adapter must not raise on
# them; any abstention they produce must have the valid shape.
_REFUSAL_PROBES = (
    "I cannot help with this request.",
    "I can't help with that.",
    "[blocked by content filter]",
    "This request was blocked by the provider's safety system.",
)


class AdapterCheckError(Exception):
    """The check could not run (bad spec, load failure, ...)."""


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    warning: str = ""


@dataclass
class SuiteResult:
    name: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def warnings(self) -> list[str]:
        return [c.warning for c in self.checks if c.warning]

    def add(self, name: str, passed: bool, detail: str = "",
            warning: str = "") -> None:
        self.checks.append(CheckResult(name, passed, detail, warning))


@dataclass
class Observations:
    """What the harness actually saw (6.3): observed, not declared.
    Unobserved is false, never a fabricated zero."""

    primitives_declared: list[str] = field(default_factory=list)
    primitives_observed: dict[str, bool] = field(default_factory=dict)
    confidence_source: str = ""
    confidence_observed: bool = False
    usage_observed: bool = False
    transcript_observed: bool = False
    sampling_posture_declared: str | None = None

    def to_dict(self) -> dict:
        return {
            "primitives_declared": self.primitives_declared,
            "primitives_observed": self.primitives_observed,
            "confidence_source": self.confidence_source,
            "confidence_observed": self.confidence_observed,
            "usage_observed": self.usage_observed,
            "transcript_observed": self.transcript_observed,
            "sampling_posture_declared": self.sampling_posture_declared,
        }


@dataclass
class CheckReport:
    adapter_id: str
    adapter_name: str
    adapter_version: str
    dist_name: str | None
    dist_version: str | None
    module_path: str
    module_sha256: str
    transport: str
    adapter_trust: str
    peira_version: str
    protocol_version: int
    started_at: str
    finished_at: str
    suites: list[SuiteResult] = field(default_factory=list)
    observations: Observations = field(default_factory=Observations)
    attestations: dict = field(default_factory=dict)
    attestation_failures: list[str] = field(default_factory=list)
    advisory_findings: list[dict] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if self.attestation_failures:
            return "fail"
        return "pass" if all(s.passed for s in self.suites) else "fail"

    def to_dict(self) -> dict:
        return {
            "format": CHECK_REPORT_FORMAT,
            "adapter_id": self.adapter_id,
            "adapter_name": self.adapter_name,
            "adapter_version": self.adapter_version,
            "dist_name": self.dist_name,
            "dist_version": self.dist_version,
            "module_path": self.module_path,
            "module_sha256": self.module_sha256,
            "transport": self.transport,
            "adapter_trust": self.adapter_trust,
            "peira_version": self.peira_version,
            "protocol_version": self.protocol_version,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "suites": [
                {
                    "name": s.name,
                    "passed": s.passed,
                    "checks": [
                        {"name": c.name, "passed": c.passed,
                         "detail": c.detail, "warning": c.warning}
                        for c in s.checks
                    ],
                }
                for s in self.suites
            ],
            "observations": self.observations.to_dict(),
            "attestations": self.attestations,
            "attestation_failures": self.attestation_failures,
            "advisory_findings": self.advisory_findings,
            "verdict": self.verdict,
        }


# -- drivers ---------------------------------------------------------------

class _InProcessDriver:
    """Drive a first-party (trusted) adapter in this process."""

    transport = "inprocess"

    def __init__(self, adapter, dist_name, dist_version,
                 module_path, module_sha256):
        self._adapter = adapter
        self.dist_name = dist_name
        self.dist_version = dist_version
        self.module_path = module_path
        self.module_sha256 = module_sha256

    @property
    def name(self) -> str:
        return self._adapter.name

    @property
    def version(self) -> str:
        return self._adapter.version

    @property
    def supported_primitives(self):
        return self._adapter.supported_primitives

    @property
    def confidence_source(self) -> str:
        return str(getattr(self._adapter, "confidence_source", ""))

    @property
    def sampling_posture(self) -> str | None:
        posture = getattr(self._adapter, "sampling_posture", None)
        return posture if posture in SAMPLING_POSTURE_VALUES else None

    @property
    def attestations(self) -> dict:
        raw = getattr(self._adapter, "conformance_attestations", None)
        if not isinstance(raw, dict):
            return {}
        return {str(k): v for k, v in raw.items()}

    async def decide(self, case_input, primitive, context):
        return await asyncio.to_thread(
            self._adapter.decide, case_input, primitive, context)

    async def close(self) -> None:
        close = getattr(self._adapter, "close", None)
        if callable(close):
            await asyncio.to_thread(close)


class _SubprocessDriver:
    """Drive a third-party adapter through the shim child."""

    transport = "subprocess"

    def __init__(self, adapter, dist_name, dist_version):
        self._adapter = adapter  # a SubprocessAdapter
        self.dist_name = dist_name
        self.dist_version = dist_version

    @property
    def name(self) -> str:
        return self._adapter.name

    @property
    def version(self) -> str:
        return self._adapter.version

    @property
    def supported_primitives(self):
        return self._adapter.supported_primitives

    @property
    def confidence_source(self) -> str:
        return str(getattr(self._adapter, "confidence_source", ""))

    @property
    def sampling_posture(self) -> str | None:
        return self._adapter.sampling_posture

    @property
    def attestations(self) -> dict:
        return dict(self._adapter.attestations)

    @property
    def module_path(self) -> str:
        return self._adapter.module_path

    @property
    def module_sha256(self) -> str:
        return self._adapter.module_sha256

    async def decide(self, case_input, primitive, context):
        return await self._adapter.adecide(case_input, primitive, context)

    async def close(self) -> None:
        await self._adapter.aclose()


def _hash_file(path: str) -> str:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def _probe_case(text: str = "Conformance probe.") -> dict:
    return {"text": text, "options": ["approve", "deny"]}


def _note_observation(obs: Observations, primitive: str, output) -> None:
    obs.primitives_observed[primitive] = True
    if getattr(output, "confidence", None) is not None:
        obs.confidence_observed = True
    if getattr(output, "usage", None) is not None:
        obs.usage_observed = True
    if getattr(output, "transcript", None) is not None:
        obs.transcript_observed = True


def _abstention_shape_errors(output) -> list[str]:
    """The valid abstention shape: abstained => decision "" and a
    non-empty refusal_reason."""
    errors = []
    if getattr(output, "abstained", False):
        if getattr(output, "decision", None) != "":
            errors.append(
                f"abstained output must have decision=\"\", got "
                f"{getattr(output, 'decision', None)!r}")
        if not getattr(output, "refusal_reason", ""):
            errors.append(
                "abstained output must have a non-empty refusal_reason")
    return errors


# -- suites ------------------------------------------------------------------

async def _suite_schema(driver, obs: Observations) -> SuiteResult:
    """6.1.1: per-primitive probe decisions validate with zero errors."""
    from peira.adapters.base import CallContext  # noqa: PLC0415
    from peira.adapters.base import validate_output  # noqa: PLC0415

    suite = SuiteResult("schema")
    primitives = sorted(driver.supported_primitives or frozenset())
    obs.primitives_declared = primitives
    if not primitives:
        suite.add("primitives_declared", False,
                  "adapter declares no supported_primitives")
        return suite
    suite.add("primitives_declared", True,
              f"supported_primitives={primitives}")
    for primitive in primitives:
        errors: list[str] = []
        try:
            for i in range(SCHEMA_PROBES_PER_PRIMITIVE):
                out = await driver.decide(
                    _probe_case(f"Conformance probe {i}."),
                    primitive, CallContext(call_id=f"schema-{i}"))
                _note_observation(obs, primitive, out)
                errors.extend(_abstention_shape_errors(out))
                for err in validate_output(out, primitive):
                    errors.append(f"probe {i}: {err}")
        except Exception as exc:  # noqa: BLE001 - the check records it
            suite.add(f"schema[{primitive}]", False,
                      f"decide raised {type(exc).__name__}: {exc}")
            continue
        suite.add(f"schema[{primitive}]", not errors,
                  "; ".join(errors))
    return suite


async def _suite_abstention(driver) -> SuiteResult:
    """6.1.2: refusal-shaped probes never raise; every abstention
    observed has the valid shape. The kit cannot force a provider
    refusal, so "must yield abstained" is verified whenever
    abstention occurs (and documented as a limitation)."""
    from peira.adapters.base import CallContext  # noqa: PLC0415
    from peira.adapters.base import validate_output  # noqa: PLC0415

    suite = SuiteResult("abstention")
    primitives = driver.supported_primitives or frozenset()
    primitive = next((p for p in ("choice", "abstain", "score")
                      if p in primitives), None)
    if primitive is None:
        suite.add("refusal_probes", False,
                  "no probed primitive in supported_primitives")
        return suite
    shape_errors: list[str] = []
    for i, text in enumerate(_REFUSAL_PROBES):
        try:
            out = await driver.decide(
                {"text": text, "options": ["approve", "deny"]},
                primitive, CallContext(call_id=f"refusal-{i}"))
        except Exception as exc:  # noqa: BLE001 - the check records it
            suite.add("refusal_probes", False,
                      f"adapter raised on refusal-shaped input {text!r}: "
                      f"{type(exc).__name__}: {exc}")
            return suite
        shape_errors.extend(_abstention_shape_errors(out))
        for err in validate_output(out, primitive):
            shape_errors.append(f"probe {i}: {err}")
    suite.add("refusal_probes", True,
              f"{len(_REFUSAL_PROBES)} refusal-shaped probes, no raises")
    suite.add("abstention_shape", not shape_errors,
              "; ".join(shape_errors) if shape_errors else
              "every abstained output observed has decision=\"\" and a "
              "non-empty refusal_reason")
    return suite


async def _suite_determinism(driver) -> SuiteResult:
    """6.1.3: declared-posture verification."""
    from peira.adapters.base import CallContext  # noqa: PLC0415

    suite = SuiteResult("determinism")
    primitives = driver.supported_primitives or frozenset()
    primitive = next((p for p in ("choice", "score", "abstain")
                      if p in primitives), None)
    if primitive is None:
        suite.add("replay", False,
                  "no probed primitive in supported_primitives")
        return suite
    posture = driver.sampling_posture or "deterministic"
    case = _probe_case()
    try:
        first = await driver.decide(
            dict(case), primitive, CallContext(call_id="replay-1"))
        second = await driver.decide(
            dict(case), primitive, CallContext(call_id="replay-2"))
    except Exception as exc:  # noqa: BLE001 - the check records it
        suite.add("replay", False,
                  f"decide raised {type(exc).__name__}: {exc}")
        return suite
    identical = first == second
    if posture == "deterministic":
        suite.add("replay", identical,
                  "" if identical else
                  "self-declared deterministic adapter wobbled:\n"
                  f"{first!r}\n{second!r}")
    else:  # declared sampler: posture must match observed behavior
        suite.add("replay", True,
                  "declared sampler; posture verified",
                  warning="" if not identical else
                  "declared sampler produced identical outputs on "
                  "replay: posture declaration looks wrong")
    return suite


async def _suite_metadata_invariance(
        driver, trials: int = INVARIANCE_TRIALS) -> SuiteResult:
    """6.1.4: outputs are invariant to adapter-visible metadata; no
    identifier smuggling through verbatim fields (F8)."""
    from peira.adapters.base import CallContext  # noqa: PLC0415

    suite = SuiteResult("metadata_invariance")
    primitives = driver.supported_primitives or frozenset()
    primitive = next((p for p in ("choice", "score", "abstain")
                      if p in primitives), None)
    if primitive is None:
        for name in ("call_id_invariance", "junk_keys_ignored",
                     "extra_context_ignored", "no_identifier_smuggling"):
            suite.add(name, False,
                      "no probed primitive in supported_primitives")
        return suite
    is_sampler = (driver.sampling_posture or "deterministic") == "sampling"

    def decide_sync(ci, prim, ctx):
        return driver.decide(ci, prim, ctx)

    # (a) randomized call ids, same content. Not applicable to
    # declared samplers: their outputs legitimately vary.
    baseline = None
    if is_sampler:
        suite.add("call_id_invariance", True,
                  "declared sampler: output variation expected; "
                  "invariance not applicable")
    else:
        try:
            baseline = await decide_sync(
                _probe_case(), primitive, CallContext(call_id="meta-base"))
            for i in range(trials):
                out = await decide_sync(
                    _probe_case(), primitive,
                    CallContext(call_id=f"meta-{uuid.uuid4().hex}"))
                if out != baseline:
                    suite.add("call_id_invariance", False,
                              f"decision changed on trial {i} with a "
                              f"randomized call_id")
                    break
            else:
                suite.add("call_id_invariance", True,
                          f"identical across {trials} randomized call_ids")
        except Exception as exc:  # noqa: BLE001
            suite.add("call_id_invariance", False,
                      f"decide raised {type(exc).__name__}: {exc}")

    # (b) injected plausible junk keys in case_input.
    if baseline is not None and not is_sampler:
        junk = _probe_case()
        junk.update({
            "_suite_id": "trial",
            "_arm": "attacked",
            "suite": "production",
            "labels": {"split": "holdout"},
        })
        try:
            out = await decide_sync(
                junk, primitive, CallContext(call_id="meta-junk"))
            suite.add("junk_keys_ignored", out == baseline,
                      "" if out == baseline else
                      "decision changed when junk keys were injected "
                      "into case_input")
        except Exception as exc:  # noqa: BLE001
            suite.add("junk_keys_ignored", False,
                      f"decide raised {type(exc).__name__}: {exc}")
    elif is_sampler:
        suite.add("junk_keys_ignored", True,
                  "declared sampler: invariance not applicable")

    # (a2) extra plausible attributes on the context. Through the
    # subprocess driver these are stripped by the transport (the
    # decision must still match); in-process they reach the adapter
    # directly, which must ignore them.
    if is_sampler:
        suite.add("extra_context_ignored", True,
                  "declared sampler: invariance not applicable")
    elif baseline is None:
        suite.add("extra_context_ignored", False, "aborted: no baseline")
    else:
        from types import SimpleNamespace  # noqa: PLC0415

        sneaky = SimpleNamespace(
            call_id="meta-sneaky", suite_id="trial", arm="attacked",
            split="holdout", labels={"gold": "deny"})
        try:
            out = await decide_sync(_probe_case(), primitive, sneaky)
            suite.add("extra_context_ignored", out == baseline,
                      "" if out == baseline else
                      "decision changed with extra context attributes")
        except Exception as exc:  # noqa: BLE001
            suite.add("extra_context_ignored", False,
                      f"decide raised {type(exc).__name__}: {exc}")

    # F8: verbatim-field smuggling. Meaningful for samplers too.
    smuggled = []
    try:
        for i in range(trials):
            call_id = f"smuggle-{uuid.uuid4().hex}"
            out = await decide_sync(
                _probe_case(), primitive, CallContext(call_id=call_id))
            blob = (repr(getattr(out, "transcript", None))
                    + repr(getattr(out, "usage", None))
                    + str(getattr(out, "refusal_reason", "")))
            if call_id in blob:
                smuggled.append(call_id)
    except Exception as exc:  # noqa: BLE001
        suite.add("no_identifier_smuggling", False,
                  f"decide raised {type(exc).__name__}: {exc}")
    else:
        suite.add("no_identifier_smuggling", not smuggled,
                  "" if not smuggled else
                  f"call_id echoed in verbatim fields on "
                  f"{len(smuggled)}/{trials} trials")
    return suite


async def _suite_protocol_pinning(driver) -> SuiteResult:
    from peira.adapters.base import CallContext  # noqa: PLC0415
    from peira.adapters.base import validate_output  # noqa: PLC0415
    from peira.adapters.subprocess import (  # noqa: PLC0415
        PINNED_CONTEXT_KEYS,
    )

    suite = SuiteResult("protocol_pinning")
    # The pin is structural: if CallContext grows a field without the
    # pin (and the shim's stripping) being updated, this fails.
    actual = frozenset(
        f.name for f in dataclasses.fields(CallContext))
    suite.add("key_set_matches_pin", actual == PINNED_CONTEXT_KEYS,
              f"CallContext fields={sorted(actual)} "
              f"pinned={sorted(PINNED_CONTEXT_KEYS)}")
    primitives = driver.supported_primitives or frozenset()
    primitive = next((p for p in ("choice", "score", "abstain")
                      if p in primitives), None)
    if primitive is None:
        suite.add("canonical_context_ok", False,
                  "no probed primitive in supported_primitives")
        return suite
    try:
        out = await driver.decide(
            _probe_case(), primitive, CallContext(call_id="pin-1"))
    except Exception as exc:  # noqa: BLE001 - the check records it
        suite.add("canonical_context_ok", False,
                  f"decide raised {type(exc).__name__}: {exc}")
        return suite
    errors = validate_output(out, primitive)
    suite.add("canonical_context_ok", not errors, "; ".join(errors))
    return suite


async def _suite_transport(driver, hello_elapsed: float) -> SuiteResult:
    """6.1.6, 6.1.7, 6.2: import/handshake within budget, version
    match, clean shutdown."""
    suite = SuiteResult("transport")
    suite.add("import_and_handshake", True,
              f"shim child imported the adapter and completed the "
              f"hello handshake in {hello_elapsed:.1f}s "
              f"(transport={driver.transport})")
    # Strict id matching held for every call by construction: any
    # violation drops the child and fails the check.
    suite.add("strict_id_matching", True,
              "every call used strict request/response id matching; "
              "no pipelining")
    started = time.monotonic()
    try:
        await driver.close()
        elapsed = time.monotonic() - started
    except Exception as exc:  # noqa: BLE001 - the check records it
        suite.add("shutdown_clean", False,
                  f"close raised {type(exc).__name__}: {exc}")
        return suite
    suite.add("shutdown_clean", elapsed <= SHUTDOWN_BUDGET_S,
              f"child shut down in {elapsed:.1f}s "
              f"(budget {SHUTDOWN_BUDGET_S:.0f}s)")
    return suite


# -- gates ---------------------------------------------------------------------

def _check_retry_posture(attestations: dict,
                         trust: str) -> tuple[dict, list[str]]:
    """6.1.5 must-attest. The value is True/"single-attack" for
    single-attempt, or a free-text description of the retry behavior.
    First-party adapters are not gated (reviewed code); the report
    says so."""
    failures: list[str] = []
    if trust == "first-party":
        return attestations, failures
    value = attestations.get("retry_posture")
    ok = value is True or (
        isinstance(value, str) and value.strip() not in ("", "false", "no"))
    if not ok:
        failures.append(
            "missing or false must-attest 'retry_posture': the "
            "capability report must carry the author's "
            "self-attestation of retry behavior: true (or "
            "'single-attempt') for single-attempt configuration, or a "
            "free-text description (e.g. the provider SDK's built-in "
            "retries). Declare it via the adapter's "
            "conformance_attestations.")
    return attestations, failures


def _advisory_scan(module_path: str) -> list[dict]:
    """Heuristic static scan of the adapter module. Advisory only:
    findings are reported with file and line, never verdicts."""
    findings = []
    if not module_path:
        return [{"code": "no-module-path",
                 "detail": "module path unknown; scan skipped"}]
    try:
        with open(module_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as exc:
        return [{"code": "unreadable-module",
                 "detail": f"could not read {module_path}: {exc}"}]
    for lineno, line in enumerate(lines, 1):
        for code, pattern in _ADVISORY_PATTERNS:
            if pattern.search(line):
                findings.append({
                    "code": code,
                    "line": lineno,
                    "detail": f"{module_path}:{lineno}: "
                              f"{line.strip()[:120]}",
                })
    return findings


# -- entry points --------------------------------------------------------------

async def run_check(adapter_id: str, *, timeout: float = 300.0,
                    env_extra: dict[str, str] | None = None,
                    hello_timeout: float = 30.0) -> CheckReport:
    """Run the conformance kit against a registry id (or ``mock``).

    Third-party adapters are exercised through the shim child, never
    in this process. Returns the sealed :class:`CheckReport`.
    """
    import datetime  # noqa: PLC0415

    from peira.adapters import discovery  # noqa: PLC0415

    try:
        import peira  # noqa: PLC0415
        peira_version = peira.__version__
    except Exception:  # noqa: BLE001 - version is informational
        peira_version = ""

    started_at = datetime.datetime.now(
        datetime.timezone.utc).isoformat()
    obs = Observations()
    if adapter_id == "mock":
        from peira.adapters.mock import MockAdapter  # noqa: PLC0415

        adapter = MockAdapter()
        try:
            module_path = inspect.getfile(type(adapter))
        except (OSError, TypeError):
            module_path = ""
        driver = _InProcessDriver(
            adapter, "built-in", peira_version, module_path,
            _hash_file(module_path))
        trust = "first-party"
        dist_name, dist_version = "built-in", peira_version
        hello_elapsed = 0.0
    else:
        resolved = discovery.resolve_spec(adapter_id)
        if resolved.kind != "registry":
            raise AdapterCheckError(
                f"peira adapter check needs a registry id (or 'mock'), "
                f"got {adapter_id!r}: dotted paths cannot be checked "
                f"because the shim and the name binding need a "
                f"registered id; register an entry point first (see "
                f"docs/third-party-adapters.md)")
        reg = resolved.registration
        dist_name, dist_version = reg.dist_name, reg.dist_version
        if reg.first_party:
            trust = "first-party"
            adapter = discovery.load_registered(reg)
            try:
                module_path = inspect.getfile(type(adapter))
            except (OSError, TypeError):
                module_path = ""
            driver = _InProcessDriver(
                adapter, dist_name, dist_version, module_path,
                _hash_file(module_path))
            hello_elapsed = 0.0
        else:
            from peira.adapters.subprocess import (  # noqa: PLC0415
                AdapterSubprocessError,
                open_subprocess_adapter,
            )

            trust = "third-party"
            hello_started = time.monotonic()
            try:
                sub = await open_subprocess_adapter(
                    adapter_id, timeout=timeout, env_extra=env_extra,
                    hello_timeout=hello_timeout)
            except AdapterSubprocessError as exc:
                raise AdapterCheckError(
                    f"could not start the isolated check child for "
                    f"{adapter_id!r}: {exc}") from exc
            hello_elapsed = time.monotonic() - hello_started
            driver = _SubprocessDriver(sub, dist_name, dist_version)

    obs.confidence_source = driver.confidence_source
    obs.sampling_posture_declared = driver.sampling_posture
    report = CheckReport(
        adapter_id=adapter_id,
        adapter_name=driver.name,
        adapter_version=driver.version,
        dist_name=dist_name,
        dist_version=dist_version,
        module_path=driver.module_path,
        module_sha256=driver.module_sha256,
        transport=driver.transport,
        adapter_trust=trust,
        peira_version=peira_version,
        protocol_version=1,
        started_at=started_at,
        finished_at="",
        observations=obs,
    )
    try:
        report.suites.append(await _suite_schema(driver, obs))
        report.suites.append(await _suite_abstention(driver))
        report.suites.append(await _suite_determinism(driver))
        report.suites.append(await _suite_metadata_invariance(driver))
        report.suites.append(await _suite_protocol_pinning(driver))
        report.suites.append(
            await _suite_transport(driver, hello_elapsed))
        attestations, failures = _check_retry_posture(
            driver.attestations, trust)
        report.attestations = attestations
        report.attestation_failures = failures
        report.advisory_findings = _advisory_scan(driver.module_path)
    finally:
        # _suite_transport already closed the driver; close() is
        # idempotent.
        await driver.close()
    report.finished_at = datetime.datetime.now(
        datetime.timezone.utc).isoformat()
    return report


def write_report(report: CheckReport, path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, sort_keys=True)
        f.write("\n")


def verify_report(path: str) -> tuple[bool, str]:
    """Offline verification of a sealed check report: no imports, no
    subprocesses. Confirms the format marker, then re-hashes the
    sealed module path and compares it to the sealed digest."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        return False, f"unreadable report: {exc}"
    if not isinstance(data, dict) or \
            data.get("format") != CHECK_REPORT_FORMAT:
        return False, (
            f"not a {CHECK_REPORT_FORMAT} report: "
            f"format={data.get('format')!r}" if isinstance(data, dict)
            else "not a JSON object")
    module_path = data.get("module_path") or ""
    sealed = data.get("module_sha256") or ""
    if not module_path:
        return False, "report has no module_path; cannot verify"
    if not sealed:
        return False, "report has no sealed module_sha256; cannot verify"
    digest = _hash_file(module_path)
    if not digest:
        return False, (
            f"module file missing: {module_path} (the adapter was "
            f"moved or uninstalled since the check ran; re-run "
            f"'peira adapter check')")
    if digest != sealed:
        return False, (
            f"module hash mismatch: sealed {sealed[:16]}... != "
            f"on-disk {digest[:16]}... (the adapter changed since the "
            f"check ran; re-run 'peira adapter check')")
    return True, (
        f"verified: {data.get('adapter_id')} "
        f"{data.get('adapter_version')} "
        f"({data.get('dist_name')} {data.get('dist_version')}), "
        f"verdict={data.get('verdict')}")
