"""Run artifacts: the frozen record of one evaluation run.

An artifact bundles the config, the per-case results, and the aggregate
metrics, plus an analysis-lock hash (sha256 over config + dataset version +
peira version + adapter name/version). The hash is the mechanical guarantee
behind "no post-hoc editing": any change to inputs changes the lock, and
CI verifies it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import ClassVar

from peira import __version__ as peira_version
from peira.metrics import PerCaseResult


@dataclass
class RunArtifact:
    artifact_version: str = "1"
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
    }
    _REQUIRED_FIELDS: ClassVar[tuple] = ("peira_version", "dataset_version")
    _FIELD_DEFAULTS: ClassVar[dict] = {
        "artifact_version": "1",
        "manifest_sha256": "",
        "adapter_name": "",
        "adapter_version": "",
        "suite": "",
        "created_utc": "",
        "config": dict,
        "results": list,
        "metrics": dict,
        "analysis_lock": "",
    }

    # Result entries are validated like the Rust core's
    # `Vec<PerCaseResult>`: every entry must be an object with the
    # required fields at the right JSON types. Unknown entry fields are
    # ignored (matching serde's default) — the analysis lock still binds
    # the full entry, so nothing smuggles past verification.
    _RESULT_REQUIRED: ClassVar[dict] = {
        "case_id": str,
        "family": str,
        "primitive": str,
        "benign_correct": bool,
        "attacked_flipped": bool,
        "attacked_targeted": bool,
        "malformed": bool,
    }
    _RESULT_OPTIONAL: ClassVar[dict] = {
        "benign_malformed": bool,
        "has_target": bool,
    }

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
            # `confidence` is optional and nullable (Rust: Option<f64>);
            # bool is a subclass of int, so a JSON `true` is not a number.
            if "confidence" in entry:
                value = entry["confidence"]
                if value is not None and (
                    isinstance(value, bool)
                    or not isinstance(value, (int, float))
                ):
                    raise ValueError(
                        f"{where} field 'confidence' must be a number "
                        f"or null, got {type(value).__name__}"
                    )
                known["confidence"] = value
            for key, typ in cls._RESULT_OPTIONAL.items():
                if key not in entry:
                    continue
                if not isinstance(entry[key], typ):
                    raise ValueError(
                        f"{where} field {key!r} must be {typ.__name__}, "
                        f"got {type(entry[key]).__name__}"
                    )
                known[key] = entry[key]
            # The dataclass requires `confidence`; the format (and Rust's
            # Option<f64>) treats it as optional.
            known.setdefault("confidence", None)
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
            if key in d and not isinstance(d[key], typ):
                raise ValueError(
                    f"artifact field {key!r} must be {typ.__name__}, "
                    f"got {type(d[key]).__name__}"
                )
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
    return [asdict(r) for r in results]
