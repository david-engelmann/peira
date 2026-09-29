"""Run artifacts: the versioned record of one evaluation run.

An artifact bundles the config, the per-case results, and the aggregate
metrics, plus an analysis-lock hash (sha256 over the lock payload). The
hash is the mechanical guarantee behind "no post-hoc editing": any change
to inputs changes the lock, and CI verifies it.

Artifact format versions:
- v1 (pre-2026-09-23): flat per-case results. REJECTED by this build —
  v1 artifacts predate the v2 measurement contract and cannot be
  migrated; re-run the adapter to produce a v2 artifact.
- v2 (current): per-case results carry full per-variant call records
  (decision, confidence, abstention, refusal reason, usage, seed,
  dispatch index), eligibility flags with ineligibility reasons, and
  run-level pricing provenance (source + pin date) and seed. The lock
  payload covers pricing_source, pricing_date, and seed alongside the
  v1 fields: they are measurement inputs, so they are lock inputs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import ClassVar

from peira import __version__ as peira_version
from peira._rust import _impl as _rust
from peira.adapters.base import _unit_interval
from peira.metrics import PerCaseResult

ARTIFACT_VERSION = "2"

#: Measurement-contract version: the semantics the run was executed
#: under (abstention semantics, flip definition, eligibility rules).
#: ARTIFACT_VERSION covers the schema; the contract version covers the
#: meaning. A future semantics change bumps this (not the artifact
#: version) so old runs stay loadable but are never silently
#: reinterpreted under new rules.
CONTRACT_VERSION = "1"

_V1_REJECTION = (
    "unsupported artifact_version {version!r}: v1 artifacts predate the "
    "v2 measurement contract and cannot be loaded or migrated — re-run "
    "the adapter to produce a v2 artifact"
)


def _is_int(v: object) -> bool:
    # bool subclasses int; a JSON `true` is not an integer.
    return isinstance(v, int) and not isinstance(v, bool)


def _is_num(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


@dataclass
class RunArtifact:
    artifact_version: str = ARTIFACT_VERSION
    peira_version: str = peira_version
    dataset_version: str = "0.1.0-demo"
    adapter_name: str = ""
    adapter_version: str = ""  # pinned by the adapter; part of the lock
    suite: str = ""
    created_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    config: dict = field(default_factory=dict)
    results: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    analysis_lock: str = ""
    # SHA-256 of the suite manifest.json bytes as verified before scoring.
    # A label (`dataset_version`) says which dataset this claims to be;
    # this digest proves the exact bytes. Empty when the suite ships no
    # manifest — the run is then explicitly unbound, not silently bound.
    manifest_sha256: str = ""
    # Pricing provenance: which pinned table priced this run's calls.
    pricing_source: str = ""
    pricing_date: str = ""
    # Machine-identifiable pricing table version (pricing.json's
    # pricing_version, e.g. "2026-09-25.1"): a cost figure is always
    # traceable to the exact table version that produced it. Runs are
    # never re-priced in place: a price change ships as a new table
    # version, and old artifacts keep their sealed numbers.
    pricing_version: str = ""
    # The measurement contract this run was executed under (see
    # CONTRACT_VERSION): abstention semantics, flip definition,
    # eligibility rules.
    contract_version: str = CONTRACT_VERSION
    # How the run ended: "complete" (all planned cases scored),
    # "budget" (stopped by --budget-usd; see budget_usd/spent_usd),
    # "timeout"/"operator" reserved for future termination causes.
    # Budget-terminated runs are analyzable but never rank: a lucky
    # prefix of easy cases must not top a leaderboard.
    termination: str = "complete"
    # Hard spend cap in USD for this run (None = uncapped). The runner
    # enforces it pre-dispatch with a 1.5x running-mean projection and
    # drains in-flight calls; it never kills a paid call mid-flight.
    budget_usd: float | None = None
    # Actual priced spend at seal time (runner-computed, same table as
    # the call records). May overshoot budget_usd by at most one
    # in-flight wave: dispatched calls always complete.
    spent_usd: float = 0.0
    # Cases scored vs planned. Equal on complete runs; on
    # budget-terminated runs completed < planned and the artifact is
    # partial-but-sealed (analyzable, not rankable).
    cases_completed: int = 0
    cases_planned: int = 0
    # Run seed: recorded on every call record for reproducibility.
    seed: int = 0
    # Concurrency cap the run was dispatched with. The AIMD controller
    # adapts within [1, max_concurrency]; it is a performance parameter,
    # not a measurement input (records are identical for any limit),
    # but it is sealed for provenance.
    max_concurrency: int = 0
    # Environment fingerprint (Layer 1b): the full environment dict plus
    # its SHA-256 digest. Recorded at run start; part of the analysis
    # lock. Two runs with different env_sha256 are explained, not
    # mysterious.
    env: dict = field(default_factory=dict)
    env_sha256: str = ""
    # Measurement framework (§3.7-3.8, §3.11-3.15): adapter registration
    # metadata and longitudinal provenance. model_class documents the
    # adapter kind (guardrail, llm-baseline, hybrid, rule-based);
    # confidence_source documents where the confidence came from
    # (verbalized, token-logprob, guardrail-score, none). These are
    # documented vocabularies, not enforced enums: validation
    # type-checks str only. decode_params
    # is a JSON blob (temperature, top-p, max tokens, ...). All default
    # to "" for artifacts predating them.
    model_class: str = ""
    confidence_source: str = ""
    checkpoint_hash: str = ""
    api_version: str = ""
    call_date: str = ""
    decode_params: str = ""
    template_hash: str = ""
    case_set_tag: str = ""
    cost_scenario_version: str = ""

    def _compute_lock_py(self) -> str:
        """Reference implementation of :meth:`compute_lock` (pure Python)."""
        payload = json.dumps(
            {
                "peira_version": self.peira_version,
                "dataset_version": self.dataset_version,
                "adapter_name": self.adapter_name,
                "adapter_version": self.adapter_version,
                "suite": self.suite,
                "config": self.config,
                "results": self.results,
                "manifest_sha256": self.manifest_sha256,
                "pricing_source": self.pricing_source,
                "pricing_date": self.pricing_date,
                "pricing_version": self.pricing_version,
                "contract_version": self.contract_version,
                "termination": self.termination,
                "budget_usd": self.budget_usd,
                "spent_usd": self.spent_usd,
                "cases_completed": self.cases_completed,
                "cases_planned": self.cases_planned,
                "seed": self.seed,
                "max_concurrency": self.max_concurrency,
                # NOTE: metrics are lock-covered (P0-1, 2026-09-25). Any
                # post-hoc edit to the headline numbers invalidates the
                # lock. Pre-2026-09-25 artifacts sealed without metrics in
                # the lock will fail verify() — acceptable per blank-canvas.
                "metrics": self.metrics,
                # Environment fingerprint (Layer 1b, 2026-09-27): the env
                # is a measurement input. A different torch/CUDA/Python
                # can change numbers; the lock must catch it.
                "env_sha256": self.env_sha256,
                # Measurement framework (M-6/M-7, 2026-09-28): adapter
                # registration metadata and longitudinal provenance are
                # measurement inputs; the lock must catch post-hoc edits.
                "model_class": self.model_class,
                "confidence_source": self.confidence_source,
                "checkpoint_hash": self.checkpoint_hash,
                "api_version": self.api_version,
                "call_date": self.call_date,
                "decode_params": self.decode_params,
                "template_hash": self.template_hash,
                "case_set_tag": self.case_set_tag,
                "cost_scenario_version": self.cost_scenario_version,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def compute_lock(self) -> str:
        """SHA-256 analysis lock over the artifact's lock-covered fields.

        Dispatches to the Rust core when available; the pure-Python
        :meth:`_compute_lock_py` is the reference and the fallback.
        """
        if _rust is not None:
            try:
                return _rust.artifact_lock_payload(
                    self.peira_version,
                    self.dataset_version,
                    self.manifest_sha256,
                    self.adapter_name,
                    self.adapter_version,
                    self.suite,
                    self.config,
                    self.results,
                    self.pricing_source,
                    self.pricing_date,
                    self.pricing_version,
                    self.contract_version,
                    self.termination,
                    self.budget_usd,
                    self.spent_usd,
                    self.cases_completed,
                    self.cases_planned,
                    self.seed,
                    self.max_concurrency,
                    self.metrics,
                    self.env_sha256,
                    self.model_class,
                    self.confidence_source,
                    self.checkpoint_hash,
                    self.api_version,
                    self.call_date,
                    self.decode_params,
                    self.template_hash,
                    self.case_set_tag,
                    self.cost_scenario_version,
                )
            except (TypeError, ValueError, OverflowError):
                pass
        return self._compute_lock_py()

    def seal(self) -> "RunArtifact":
        self.analysis_lock = self.compute_lock()
        return self

    def verify(self) -> bool:
        return self.analysis_lock == self.compute_lock()

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    # Field name -> expected JSON type. `peira_version` and
    # `dataset_version` are required: the lock is meaningless without the
    # identifiers it binds. Every other field defaults exactly like the
    # Rust core's `RunArtifact` (missing `config`/`metrics` become `{}`),
    # so a minimal hand-written artifact loads identically on both
    # backends. Unknown fields are rejected: silently accepting a
    # newer/renamed field could verify a lock under changed semantics.
    _FIELD_TYPES: ClassVar[dict] = {
        "artifact_version": str,
        "peira_version": str,
        "dataset_version": str,
        "manifest_sha256": str,
        "adapter_name": str,
        "adapter_version": str,
        "suite": str,
        "created_utc": str,
        "config": dict,
        "results": list,
        "metrics": dict,
        "analysis_lock": str,
        "pricing_source": str,
        "pricing_date": str,
        "pricing_version": str,
        "contract_version": str,
        "termination": str,
        "cases_completed": int,
        "cases_planned": int,
        "seed": int,
        "max_concurrency": int,
        "env": dict,
        "env_sha256": str,
        # Measurement framework (§3.7-3.8, §3.11-3.15): adapter
        # registration metadata and longitudinal provenance.
        "model_class": str,
        "confidence_source": str,
        "checkpoint_hash": str,
        "api_version": str,
        "call_date": str,
        "decode_params": str,
        "template_hash": str,
        "case_set_tag": str,
        "cost_scenario_version": str,
    }
    # Numeric fields needing the bool-rejecting _is_num check (a JSON
    # integer 0 must pass for spent_usd; a JSON `true` must not).
    # budget_usd additionally allows null (uncapped run).
    _NUM_FIELDS: ClassVar[tuple] = ("spent_usd",)
    _NULLABLE_NUM_FIELDS: ClassVar[tuple] = ("budget_usd",)
    _REQUIRED_FIELDS: ClassVar[tuple] = ("peira_version", "dataset_version")
    _FIELD_DEFAULTS: ClassVar[dict] = {
        "artifact_version": ARTIFACT_VERSION,
        "manifest_sha256": "",
        "adapter_name": "",
        "adapter_version": "",
        "suite": "",
        "created_utc": "",
        "config": dict,
        "results": list,
        "metrics": dict,
        "analysis_lock": "",
        "pricing_source": "",
        "pricing_date": "",
        "pricing_version": "",
        "contract_version": CONTRACT_VERSION,
        "termination": "complete",
        "budget_usd": None,
        "spent_usd": 0.0,
        "cases_completed": 0,
        "cases_planned": 0,
        "seed": 0,
        "max_concurrency": 0,
        "env": dict,
        "env_sha256": "",
    }
    # Integer fields where a JSON `true` must not pass as an integer
    # (bool subclasses int).
    _INT_FIELDS: ClassVar[tuple] = (
        "seed", "max_concurrency", "cases_completed", "cases_planned",
    )

    # v2 result entries: per-variant call records plus scoring flags.
    # Every entry field is required and strictly typed (unknown entry
    # fields are rejected, like unknown top-level fields — the v1
    # loader's leniency here was a hole, closed pre-launch). `usage` is
    # the one nullable record field: null means the adapter reported no
    # token accounting.
    _RESULT_REQUIRED: ClassVar[dict] = {
        "case_id": str,
        "family": str,
        "severity": str,
        "primitive": str,
        "benign": dict,
        "attacked": dict,
        "flipped": bool,
        "eligible": bool,
        "ineligibility_reason": str,
    }
    _CALL_RECORD_FIELDS: ClassVar[dict] = {
        "decision": str,
        "abstained": bool,
        "refusal_reason": str,
        "malformed": bool,
    }
    _USAGE_FIELDS: ClassVar[dict] = {
        "model": str,
    }

    @classmethod
    def _checked_usage(cls, usage: object, where: str) -> None:
        if usage is None:
            return
        if not isinstance(usage, dict):
            raise ValueError(
                f"{where} field 'usage' must be an object or null, "
                f"got {type(usage).__name__}"
            )
        for key in usage:
            if key not in (
                "model", "tokens_in", "tokens_out", "latency_ms", "cost_usd",
                "price_table_ref",
            ):
                raise ValueError(f"{where} has unknown usage field: {key!r}")
        for key in ("model", "tokens_in", "tokens_out", "latency_ms", "cost_usd"):
            if key not in usage:
                raise ValueError(f"{where} usage is missing field: {key!r}")
        if not isinstance(usage["model"], str):
            raise ValueError(
                f"{where} usage field 'model' must be str, "
                f"got {type(usage['model']).__name__}"
            )
        for key in ("tokens_in", "tokens_out"):
            if not _is_int(usage[key]):
                raise ValueError(
                    f"{where} usage field {key!r} must be an integer, "
                    f"got {type(usage[key]).__name__}"
                )
            if usage[key] < 0:
                raise ValueError(
                    f"{where} usage field {key!r} must be non-negative, "
                    f"got {usage[key]}"
                )
        for key in ("latency_ms", "cost_usd"):
            if not _is_num(usage[key]):
                raise ValueError(
                    f"{where} usage field {key!r} must be a number, "
                    f"got {type(usage[key]).__name__}"
                )
            if not usage[key] >= 0:
                raise ValueError(
                    f"{where} usage field {key!r} must be non-negative, "
                    f"got {usage[key]}"
                )

    @classmethod
    def _checked_call_record(cls, record: object, where: str) -> dict:
        if not isinstance(record, dict):
            raise ValueError(
                f"{where} must be an object, got {type(record).__name__}"
            )
        for key in record:
            if key not in (
                "decision", "confidence", "abstained", "refusal_reason",
                "usage", "seed", "dispatch_index", "malformed",
                "dispatch_limit", "score", "latency_ms_total", "timed_out",
                "cached",
            ):
                raise ValueError(f"{where} has unknown field: {key!r}")
        for key in (
            "decision", "abstained", "refusal_reason",
            "seed", "dispatch_index", "malformed", "dispatch_limit",
        ):
            if key not in record:
                raise ValueError(f"{where} is missing field: {key!r}")
        for key, typ in cls._CALL_RECORD_FIELDS.items():
            if not isinstance(record[key], typ):
                raise ValueError(
                    f"{where} field {key!r} must be {typ.__name__}, "
                    f"got {type(record[key]).__name__}"
                )
        # timed_out is a bool flag like malformed/abstained: a JSON
        # `true`/`false` only (bool check first: isinstance(True, int)
        # is True, so the int fields below would accept it).
        timed_out = record.get("timed_out", False)
        if not isinstance(timed_out, bool):
            raise ValueError(
                f"{where} field 'timed_out' must be a boolean, "
                f"got {type(timed_out).__name__}"
            )
        # cached marks response-cache hits (no provider call was made):
        # same bool-only treatment as timed_out.
        cached = record.get("cached", False)
        if not isinstance(cached, bool):
            raise ValueError(
                f"{where} field 'cached' must be a boolean, "
                f"got {type(cached).__name__}"
            )
        # latency_ms_total is cumulative wall-clock ms (all attempts +
        # backoff); absent in pre-Phase-0 artifacts. Numeric, never a
        # bool, never negative.
        total_lat = record.get("latency_ms_total", 0.0)
        if not _is_num(total_lat) or total_lat < 0:
            raise ValueError(
                f"{where} field 'latency_ms_total' must be a "
                f"non-negative number, got {total_lat!r}"
            )
        for key, typ in cls._CALL_RECORD_FIELDS.items():
            if not isinstance(record[key], typ):
                raise ValueError(
                    f"{where} field {key!r} must be {typ.__name__}, "
                    f"got {type(record[key]).__name__}"
                )
        confidence = record.get("confidence")
        if confidence is not None and not _is_num(confidence):
            raise ValueError(
                f"{where} field 'confidence' must be a number or null, "
                f"got {type(confidence).__name__}"
            )
        # A3 S6: the adapter's raw score for score-primitive calls; null
        # for other primitives and absent in pre-S6 artifacts. The score
        # space is the unit interval — the same rule as the adapter-output
        # contract (adapters/base.py::_unit_interval): NaN/Infinity (which
        # Python's json accepts but serde_json rejects at parse) and
        # out-of-range values fail the strict loader, so both backends
        # agree on what an artifact may contain.
        score = record.get("score")
        if score is not None:
            err = _unit_interval("score", score)
            if err is not None:
                raise ValueError(f"{where} field 'score': {err}")
        for key in ("seed", "dispatch_index", "dispatch_limit"):
            if not _is_int(record[key]):
                raise ValueError(
                    f"{where} field {key!r} must be an integer, "
                    f"got {type(record[key]).__name__}"
                )
        if "usage" not in record:
            raise ValueError(f"{where} is missing field: 'usage'")
        cls._checked_usage(record["usage"], where)
        return record

    @classmethod
    def _checked_results(cls, entries: list) -> list[dict]:
        """Validate result entries, returning clean dicts for the dataclass."""
        clean: list[dict] = []
        for i, entry in enumerate(entries):
            where = f"artifact results entry {i}"
            if not isinstance(entry, dict):
                raise ValueError(
                    f"{where} must be an object, "
                    f"got {type(entry).__name__}"
                )
            for key in entry:
                if key not in cls._RESULT_REQUIRED:
                    raise ValueError(f"{where} has unknown field: {key!r}")
            known: dict = {}
            for key, typ in cls._RESULT_REQUIRED.items():
                if key not in entry:
                    raise ValueError(
                        f"{where} is missing required field: {key!r}"
                    )
                if not isinstance(entry[key], typ):
                    raise ValueError(
                        f"{where} field {key!r} must be {typ.__name__}, "
                        f"got {type(entry[key]).__name__}"
                    )
                known[key] = entry[key]
            known["benign"] = cls._checked_call_record(
                entry["benign"], f"{where} benign"
            )
            known["attacked"] = cls._checked_call_record(
                entry["attacked"], f"{where} attacked"
            )
            clean.append(known)
        return clean

    @classmethod
    def from_json(cls, s: str) -> "RunArtifact":
        try:
            d = json.loads(s)
        except json.JSONDecodeError as e:
            raise ValueError(f"artifact is not valid JSON: {e}") from e
        if not isinstance(d, dict):
            raise ValueError("artifact must be a JSON object")
        for key in d:
            if (
                key not in cls._FIELD_TYPES
                and key not in cls._NUM_FIELDS
                and key not in cls._NULLABLE_NUM_FIELDS
            ):
                raise ValueError(f"unknown artifact field: {key!r}")
        for key in cls._REQUIRED_FIELDS:
            if key not in d:
                raise ValueError(f"artifact is missing required field: {key!r}")
        for key, typ in cls._FIELD_TYPES.items():
            if key in cls._INT_FIELDS:
                continue  # checked below with the bool-rejecting message
            if key not in d:
                continue
            if not isinstance(d[key], typ):
                raise ValueError(
                    f"artifact field {key!r} must be {typ.__name__}, "
                    f"got {type(d[key]).__name__}"
                )
        for key in cls._NUM_FIELDS:
            if key in d and not _is_num(d[key]):
                raise ValueError(
                    f"artifact field {key!r} must be a number, "
                    f"got {type(d[key]).__name__}"
                )
        for key in cls._NULLABLE_NUM_FIELDS:
            if key in d and d[key] is not None and not _is_num(d[key]):
                raise ValueError(
                    f"artifact field {key!r} must be a number or null, "
                    f"got {type(d[key]).__name__}"
                )
        for key in cls._INT_FIELDS:
            if key in d and not _is_int(d[key]):
                raise ValueError(
                    f"artifact field {key!r} must be an integer, "
                    f"got {type(d[key]).__name__}"
                )
        version = d.get("artifact_version", ARTIFACT_VERSION)
        if version != ARTIFACT_VERSION:
            raise ValueError(_V1_REJECTION.format(version=version))
        fields = {
            key: (default() if callable(default) else default)
            for key, default in cls._FIELD_DEFAULTS.items()
        }
        fields.update(d)
        if "results" in d:
            # Validated, but kept as plain dicts: the runner stores results
            # as dicts (see results_to_dicts), and compute_lock serializes
            # them directly — PerCaseResult objects would break seal().
            fields["results"] = cls._checked_results(d["results"])
        return cls(**fields)


def results_to_dicts(results: list[PerCaseResult]) -> list[dict]:
    import dataclasses

    # asdict recurses into the nested CallRecord/CallUsage dataclasses,
    # producing the plain-dict entry shape the artifact seals.
    return [dataclasses.asdict(r) for r in results]
