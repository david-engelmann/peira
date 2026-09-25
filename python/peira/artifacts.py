"""Run artifacts: the frozen record of one evaluation run.

An artifact bundles the config, the per-case results, and the aggregate
metrics, plus an analysis-lock hash (sha256 over a canonical JSON payload of
peira version, dataset version, adapter name, adapter version, suite,
config, results, and metrics). The hash is the mechanical guarantee behind
"no post-hoc editing": any change to inputs, reported metrics, or the
identified adapter version changes the lock, and CI verifies it.

Breaking change (2026-09-25): metrics are now lock-covered. Artifacts
sealed before this change will fail verify() — re-run to re-seal.

Breaking change (2026-09-25): adapter_version is now lock-covered. Two runs
that differ only in the adapter's pinned version produce different locks,
so "latest today" can never silently substitute for "latest last month".
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from peira import __version__ as peira_version
from peira.metrics import PerCaseResult

try:
    # Rust-accelerated SHA-256 (bit-exact vs hashlib); falls back below.
    from peira._peira_core import sha256_hex as _sha256_hex
except ImportError:

    def _sha256_hex(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()


@dataclass
class RunArtifact:
    artifact_version: str = "1"
    peira_version: str = peira_version
    dataset_version: str = "0.1.0-demo"
    adapter_name: str = ""
    adapter_version: str = ""
    suite: str = ""
    created_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    config: dict = field(default_factory=dict)
    results: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    analysis_lock: str = ""

    def compute_lock(self) -> str:
        # NOTE: metrics and adapter_version are lock-covered. Any post-hoc
        # edit to the headline numbers or the identified adapter version
        # invalidates the lock. sort_keys=True makes the payload
        # deterministic regardless of dict insertion order.
        payload = json.dumps(
            {
                "peira_version": self.peira_version,
                "dataset_version": self.dataset_version,
                "adapter_name": self.adapter_name,
                "adapter_version": self.adapter_version,
                "suite": self.suite,
                "config": self.config,
                "results": self.results,
                "metrics": self.metrics,
            },
            sort_keys=True,
        )
        return _sha256_hex(payload.encode())

    def seal(self) -> "RunArtifact":
        self.analysis_lock = self.compute_lock()
        return self

    def verify(self) -> bool:
        return self.analysis_lock == self.compute_lock()

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, s: str) -> "RunArtifact":
        d = json.loads(s)
        return cls(**d)


def results_to_dicts(results: list[PerCaseResult]) -> list[dict]:
    return [asdict(r) for r in results]
