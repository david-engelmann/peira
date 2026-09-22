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

    @classmethod
    def from_json(cls, s: str) -> "RunArtifact":
        d = json.loads(s)
        return cls(**d)


def results_to_dicts(results: list[PerCaseResult]) -> list[dict]:
    return [asdict(r) for r in results]
