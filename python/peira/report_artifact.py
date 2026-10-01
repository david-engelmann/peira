"""Versioned report artifacts: a sealed provenance record of a rendered report.

``peira report`` renders HTML from a run artifact, but the rendering
takes inputs beyond the artifact itself (buyer-cost parameters), so
the HTML alone is not reproducible. The report artifact binds
everything a re-render needs: the source artifact's identity and
analysis lock, the report parameters, the scored metric payload, and
an analysis lock over all of it.

Schema discipline mirrors RunArtifact: ``from_json`` is strict
(unknown fields rejected, non-"1" schema versions refused), and
``verify()`` detects any post-hoc edit to the sealed content.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar

from peira import __version__ as peira_version

REPORT_SCHEMA_VERSION = "1"

_REPORT_VERSION_REJECTION = (
    "unsupported report_schema_version {version!r}: this build reads "
    'report schema "1" only'
)


@dataclass
class ReportArtifact:
    artifact_kind: str = "report"
    report_schema_version: str = REPORT_SCHEMA_VERSION
    peira_version: str = peira_version
    generated_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    # Provenance of the rendered run artifact: everything needed to
    # locate and re-verify the exact bytes that were rendered.
    source: dict = field(default_factory=dict)
    # Report inputs beyond the artifact: buyer-cost parameters and
    # flips-per-incident change the rendering, so they are sealed
    # here. Empty when the report used defaults.
    report_params: dict = field(default_factory=dict)
    # The scored metric payload the report was rendered from.
    metrics: dict = field(default_factory=dict)
    analysis_lock: str = ""

    @staticmethod
    def source_provenance(
        artifact: Any, source_path: str
    ) -> dict[str, Any]:
        """Extract the provenance block from a sealed RunArtifact."""
        return {
            "path": str(source_path),
            "artifact_version": str(
                getattr(artifact, "artifact_version", "")
            ),
            "analysis_lock": str(getattr(artifact, "analysis_lock", "")),
            "env_sha256": str(getattr(artifact, "env_sha256", "")),
            "manifest_sha256": str(
                getattr(artifact, "manifest_sha256", "")
            ),
            "adapter_name": str(getattr(artifact, "adapter_name", "")),
            "adapter_version": str(
                getattr(artifact, "adapter_version", "")
            ),
            "suite": str(getattr(artifact, "suite", "")),
            "dataset_version": str(
                getattr(artifact, "dataset_version", "")
            ),
            "seed": getattr(artifact, "seed", 0),
        }

    @classmethod
    def from_run_artifact(
        cls,
        artifact: Any,
        *,
        report_params: dict[str, Any] | None,
        source_path: str,
    ) -> "ReportArtifact":
        """Build a report artifact from a sealed run artifact."""
        return cls(
            source=cls.source_provenance(artifact, source_path),
            report_params=dict(report_params or {}),
            metrics=(
                dict(artifact.metrics)
                if isinstance(getattr(artifact, "metrics", None), dict)
                else {}
            ),
        )

    def compute_lock(self) -> str:
        payload = json.dumps(
            {
                "peira_version": self.peira_version,
                "report_schema_version": self.report_schema_version,
                "source": self.source,
                "report_params": self.report_params,
                "metrics": self.metrics,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def seal(self) -> "ReportArtifact":
        self.analysis_lock = self.compute_lock()
        return self

    def verify(self) -> bool:
        return self.analysis_lock == self.compute_lock()

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    _FIELD_TYPES: ClassVar[dict] = {
        "artifact_kind": str,
        "report_schema_version": str,
        "peira_version": str,
        "generated_utc": str,
        "source": dict,
        "report_params": dict,
        "metrics": dict,
        "analysis_lock": str,
    }
    _REQUIRED_FIELDS: ClassVar[tuple] = (
        "artifact_kind",
        "report_schema_version",
        "peira_version",
        "source",
        "report_params",
        "metrics",
        "analysis_lock",
    )

    @classmethod
    def from_json(cls, s: str) -> "ReportArtifact":
        try:
            d = json.loads(s)
        except json.JSONDecodeError as e:
            raise ValueError(f"report artifact is not valid JSON: {e}") from e
        if not isinstance(d, dict):
            raise ValueError("report artifact must be a JSON object")
        for key in d:
            if key not in cls._FIELD_TYPES:
                raise ValueError(f"unknown report artifact field: {key!r}")
        for key in cls._REQUIRED_FIELDS:
            if key not in d:
                raise ValueError(
                    f"report artifact is missing required field: {key!r}"
                )
        for key, typ in cls._FIELD_TYPES.items():
            if not isinstance(d[key], typ):
                raise ValueError(
                    f"report artifact field {key!r} must be "
                    f"{typ.__name__}, got {type(d[key]).__name__}"
                )
        if d["artifact_kind"] != "report":
            raise ValueError(
                "not a report artifact "
                f"(artifact_kind={d['artifact_kind']!r})"
            )
        version = d["report_schema_version"]
        if version != REPORT_SCHEMA_VERSION:
            raise ValueError(
                _REPORT_VERSION_REJECTION.format(version=version)
            )
        return cls(**{k: d[k] for k in cls._FIELD_TYPES})
