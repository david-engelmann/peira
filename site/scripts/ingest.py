#!/usr/bin/env python3
"""Ingest sealed peira run artifacts into site-data JSON.

Reads v2 ``RunArtifact`` files, verifies each analysis lock, and emits
the site-data JSON described in ``site/SITE_DATA_SCHEMA.md``.

Mock discipline (mechanical, not conventional): ``--mock`` ingests ONLY
artifacts whose ``config.mock`` is true; without ``--mock`` any mock
artifact is rejected. Real and mock never mix in one build.

Usage:
    python3 site/scripts/ingest.py [--mock] <artifacts_dir> --out <results.json>
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "python"))

from peira import __version__ as peira_version  # noqa: E402
from peira.artifacts import RunArtifact  # noqa: E402

SCHEMA_VERSION = "3"

# ---------------------------------------------------------------------------
# v3 extension blocks (research_notes/peira-run-artifact-research-20260928.md).
#
# The v3 schema has not landed in peira.artifacts yet, so v3 blocks ride as
# a sealed extension inside config["v3"]; the full placement rationale
# lives on build_v3_block() in site/scripts/gen_mock.py. When the real v3
# lands with top-level fields and a bumped artifact_version, the v3 lane
# updates extract_v3() to read the new layout.
# ---------------------------------------------------------------------------

# Closed vocabularies. Agents filter and group on these; a free-form string
# that drifts silently breaks downstream joins, so ingest rejects unknown
# values instead of passing them through.
V3_ENUMS = {
    "run_status": {"started", "success", "cancelled", "error", "partial"},
    "threat_model.attacker_access": {"black_box_api", "gray_box", "white_box"},
    "attack_provenance.attack_method": {"static_template", "adaptive_search"},
    "exposure_attestation.case_subset": {"public", "private", "blind"},
    "access_tier": {"public", "internal", "confidential"},
    "submitter_provenance.submission_channel": {
        "internal_ci", "vendor_self_report", "third_party",
    },
    "submitter_provenance.verification_level": {
        "self_reported", "independently_reproduced",
    },
    "uncertainty.ci_method": {"bootstrap", "wilson", "binomial"},
    "uncertainty.multiple_comparison": {"holm", "bonferroni", "none"},
}

# reason_code enum for exclusion_log entries (MUST 7): the structured
# taxonomy for everything that did not go cleanly.
EXCLUSION_REASON_CODES = {
    "timeout", "rate_limit", "api_error", "parse_failure",
    "refused_to_format", "benign_abstained", "benign_malformed",
    "benign_wrong_decision", "attacked_malformed",
}

# Required top-level keys of the v3 block. Nested blocks are validated for
# shape when present; only run_status is load-bearing for the gate.
V3_REQUIRED_KEYS = {
    "run_id", "run_status", "metrics_version",
    "adjudication_policy_version", "threat_model", "attack_provenance",
    "exclusion_log", "determinism_check", "exposure_attestation",
    "adapter_pinning", "schema_ref", "license", "access_tier",
    "reference_baseline",
}


def _get_path(block: dict, dotted: str):
    """Return the value at a dotted path, or None if any hop is absent."""
    cur = block
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def _has_path(block: dict, dotted: str) -> bool:
    """True when every hop of the dotted path exists (even if null)."""
    cur = block
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return True


def extract_v3(artifact: RunArtifact, path_name: str) -> dict | None:
    """Return the v3 extension block, or None for pure-v2 artifacts.

    Reads the sealed config["v3"] extension block. (Top-level v3 fields
    cannot exist yet: RunArtifact.from_json rejects unknown top-level
    fields. The v3 lane updates this when the real schema lands.)
    """
    raw = artifact.config.get("v3")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        fail(f"{path_name}: config.v3 must be an object, got {type(raw).__name__}")
    return raw


def validate_v3(block: dict, path_name: str) -> None:
    """Validate a v3 block's shape and closed vocabularies. Fail closed."""
    missing = V3_REQUIRED_KEYS - set(block.keys())
    if missing:
        fail(f"{path_name}: v3 block missing required keys: {sorted(missing)}")

    # The Inspect rule (research note MUST 2): never analyze a run whose
    # status is not success. Partial/cancelled/error runs are analyzable
    # by humans but must not feed the leaderboard pipeline silently.
    status = block["run_status"]
    if status != "success":
        fail(
            f"{path_name}: v3 run_status is {status!r}, not 'success' "
            "(only successful runs are ingestible)"
        )

    # Nested blocks must be objects with their load-bearing keys; check
    # shape before the enum loop so a wrong-typed block reports its own
    # error instead of a misleading "missing <block>.<field>".
    for dotted in ("threat_model", "attack_provenance",
                   "exposure_attestation", "adapter_pinning",
                   "reference_baseline"):
        if not isinstance(_get_path(block, dotted), dict):
            fail(f"{path_name}: v3 {dotted} must be an object")

    for dotted, allowed in V3_ENUMS.items():
        if not _has_path(block, dotted):
            fail(f"{path_name}: v3 block missing {dotted}")
        value = _get_path(block, dotted)
        if value not in allowed:
            fail(
                f"{path_name}: v3 {dotted}={value!r} is not in the closed "
                f"vocabulary {sorted(allowed)}"
            )

    # Exclusion log entries are typed: case_id + arm + reason_code.
    log = block["exclusion_log"]
    if not isinstance(log, list):
        fail(f"{path_name}: v3 exclusion_log must be a list")
    for i, entry in enumerate(log):
        if not isinstance(entry, dict):
            fail(f"{path_name}: v3 exclusion_log[{i}] must be an object")
        for key in ("case_id", "arm", "reason_code"):
            if key not in entry:
                fail(f"{path_name}: v3 exclusion_log[{i}] missing {key!r}")
        if entry["arm"] not in ("benign", "attacked"):
            fail(f"{path_name}: v3 exclusion_log[{i}].arm={entry['arm']!r} "
                 "must be 'benign' or 'attacked'")
        if entry["reason_code"] not in EXCLUSION_REASON_CODES:
            fail(f"{path_name}: v3 exclusion_log[{i}].reason_code="
                 f"{entry['reason_code']!r} is not in the closed vocabulary")

    # Determinism check must be a real verdict, not a bare boolean.
    dc = block["determinism_check"]
    if not isinstance(dc, dict):
        fail(f"{path_name}: v3 determinism_check must be an object")
    for key in ("passed", "mismatches", "sample_n"):
        if key not in dc:
            fail(f"{path_name}: v3 determinism_check missing {key!r}")
    if not isinstance(dc["passed"], bool):
        fail(f"{path_name}: v3 determinism_check.passed must be a boolean")
    for key in ("mismatches", "sample_n"):
        if not isinstance(dc[key], int) or isinstance(dc[key], bool):
            fail(f"{path_name}: v3 determinism_check.{key} must be an integer")


def fail(msg: str) -> "NoReturn":
    print(f"ingest: error: {msg}", file=sys.stderr)
    raise SystemExit(1)


def check_finite(value, where: str) -> None:
    """Reject NaN/Infinity anywhere in sealed payloads.

    The site schema promises withheld values are null, never NaN; a
    non-finite float would emit nonstandard JSON that the dashboard
    does not robustly reject. Fail closed at ingest instead.
    """
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            fail(f"{where}: non-finite float {value!r} rejected (use null for withheld)")
    elif isinstance(value, dict):
        for k, v in value.items():
            check_finite(v, f"{where}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            check_finite(v, f"{where}[{i}]")


def load_artifact(path: Path, allow_mock: bool) -> tuple[RunArtifact, dict | None]:
    try:
        artifact = RunArtifact.from_json(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"{path.name}: cannot parse as RunArtifact: {exc}")
    if artifact.artifact_version != "2":
        fail(f"{path.name}: artifact_version {artifact.artifact_version!r} != '2'")
    if not artifact.verify():
        fail(f"{path.name}: analysis lock does NOT verify (tampered or hand-edited?)")
    is_mock = artifact.config.get("mock", False)
    if not isinstance(is_mock, bool):
        fail(f"{path.name}: config.mock must be a boolean, got {is_mock!r}")
    if allow_mock and not is_mock:
        fail(f"{path.name}: --mock given but artifact is not marked mock")
    if not allow_mock and is_mock:
        fail(f"{path.name}: mock artifact rejected without --mock")
    if artifact.suite not in ("public", "holdout"):
        fail(f"{path.name}: suite {artifact.suite!r} must be 'public' or 'holdout'")
    if not isinstance(artifact.metrics, dict) or not artifact.metrics:
        fail(f"{path.name}: artifact carries no sealed metrics")
    # v3 extension blocks are optional on v2 artifacts but, when present,
    # are validated and gated before anything downstream sees the run.
    v3 = extract_v3(artifact, path.name)
    if v3 is not None:
        validate_v3(v3, path.name)
    return artifact, v3


def trim_case(entry: dict) -> dict:
    return {
        "case_id": entry["case_id"],
        "family": entry["family"],
        "severity": entry["severity"],
        "primitive": entry["primitive"],
        "benign_decision": entry["benign"]["decision"],
        "attacked_decision": entry["attacked"]["decision"],
        "flipped": entry["flipped"],
        "eligible": entry["eligible"],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Ingest peira artifacts into site data.")
    ap.add_argument("artifacts_dir", help="directory of RunArtifact JSON files")
    ap.add_argument("--out", required=True, help="output site-data JSON path")
    ap.add_argument("--mock", action="store_true", help="ingest mock artifacts only")
    args = ap.parse_args()

    adir = Path(args.artifacts_dir)
    if not adir.is_dir():
        fail(f"not a directory: {adir}")
    files = sorted(adir.glob("*.json"))
    if not files:
        fail(f"no artifact JSON files in {adir}")

    runs = []
    dataset_versions = set()
    manifest_shas = set()
    seen_identities = set()
    for path in files:
        a, v3 = load_artifact(path, args.mock)
        dataset_versions.add(a.dataset_version)
        manifest_shas.add(a.manifest_sha256)
        # P2-3: the dashboard keys runs by adapter_name@adapter_version@suite;
        # two sealed runs sharing that identity would silently shadow each
        # other, so reject the ambiguity at ingest instead.
        identity = (a.adapter_name, a.adapter_version, a.suite)
        if identity in seen_identities:
            fail(f"{path.name}: duplicate run identity {identity[0]}@{identity[1]}@{identity[2]}")
        seen_identities.add(identity)
        check_finite(a.metrics, f"{path.name}.metrics")
        cases = [trim_case(e) for e in a.results]
        check_finite(cases, f"{path.name}.cases")
        run = {
            "adapter_name": a.adapter_name,
            "adapter_version": a.adapter_version,
            "model_class": a.model_class,
            "suite": a.suite,
            "dataset_version": a.dataset_version,
            "created_utc": a.created_utc,
            "analysis_lock": a.analysis_lock,
            "ranking_eligible": bool(a.metrics.get("ranking_eligible", False)),
            "eligibility_notes": list(a.metrics.get("eligibility_notes", [])),
            "metrics": a.metrics,
            "cases": cases,
        }
        # v3 blocks ride through verbatim so the views can read threat
        # model, attack provenance, adjudication identity, exposure
        # attestation, and the other agent-consumer fields without
        # recomputing them. Absent on pure-v2 artifacts.
        if v3 is not None:
            check_finite(v3, f"{path.name}.v3")
            run["v3"] = v3
        runs.append(run)

    if len(dataset_versions) != 1:
        fail(f"runs disagree on dataset_version: {sorted(dataset_versions)}")
    if len(manifest_shas) != 1:
        fail(f"runs disagree on manifest_sha256: {sorted(manifest_shas)}")
    runs.sort(key=lambda r: (r["suite"], r["adapter_name"]))

    # EB-5: the canonical family inventory is the sorted union of the
    # per-family keys across every run in the build. The leaderboard's
    # family-by-metric matrix is drawn from this list, never from a
    # single run's family set, so a run that skipped a family shows a
    # visibly missing row instead of a silently shorter matrix. (The real
    # results pipeline will source this list from the dataset manifest;
    # the union rule stays as the fallback when no manifest is bound.)
    canonical_families = sorted({
        family
        for run in runs
        for family in (run["metrics"].get("per_family") or {})
    })
    total = len(canonical_families)
    for run in runs:
        per_family = run["metrics"].get("per_family") or {}
        # A family counts as evaluated only when the run has cases in it.
        # The metrics layer lists required-but-unevaluated families with
        # n=0 (the suite manifest is the requirement set); those are the
        # visibly-missing cells, not silent gaps and not measured zeros.
        evaluated = sum(
            1 for entry in per_family.values()
            if isinstance(entry, dict) and (entry.get("n") or 0) > 0
        )
        run["coverage"] = {
            "families_evaluated": evaluated,
            "families_total": total,
            "coverage_pct": round(100.0 * evaluated / total, 1) if total else None,
        }

    site_data = {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "mock_data": bool(args.mock),
        "peira_version": peira_version,
        "dataset": {
            "name": "peira-v1",
            "version": next(iter(dataset_versions)),
            "manifest_sha256": next(iter(manifest_shas)),
            "families": canonical_families,
        },
        "runs": runs,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(site_data, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"ingest: {len(runs)} run(s), mock={args.mock}, "
        f"dataset={site_data['dataset']['version']} -> {out}"
    )


if __name__ == "__main__":
    main()
