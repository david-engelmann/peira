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
from peira.metrics import PerCaseResult

ARTIFACT_VERSION = "2"

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
    # Run seed: recorded on every call record for reproducibility.
    seed: int = 0
    # Concurrency cap the run was dispatched with. The AIMD controller
    # adapts within [1, max_concurrency]; it is a performance parameter,
    # not a measurement input (records are identical for any limit),
    # but it is sealed for provenance.
    max_concurrency: int = 0

    def compute_lock(self) -> str:
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
                "seed": self.seed,
                "max_concurrency": self.max_concurrency,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

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
        "seed": int,
        "max_concurrency": int,
    }
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
        "seed": 0,
        "max_concurrency": 0,
    }
    # Integer fields where a JSON `true` must not pass as an integer
    # (bool subclasses int).
    _INT_FIELDS: ClassVar[tuple] = ("seed", "max_concurrency")

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
                "dispatch_limit",
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
        confidence = record.get("confidence")
        if confidence is not None and not _is_num(confidence):
            raise ValueError(
                f"{where} field 'confidence' must be a number or null, "
                f"got {type(confidence).__name__}"
            )
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
            if key not in cls._FIELD_TYPES:
                raise ValueError(f"unknown artifact field: {key!r}")
        for key in cls._REQUIRED_FIELDS:
            if key not in d:
                raise ValueError(f"artifact is missing required field: {key!r}")
        for key, typ in cls._FIELD_TYPES.items():
            if key in cls._INT_FIELDS:
                continue  # checked below with the bool-rejecting message
            if key in d and not isinstance(d[key], typ):
                raise ValueError(
                    f"artifact field {key!r} must be {typ.__name__}, "
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
