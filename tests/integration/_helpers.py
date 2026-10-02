"""Shared helpers for the peira integration suite.

The integration layer tests the whole pipeline end to end:
dataset -> runner -> metrics -> artifact -> report. These helpers keep
the suite fast (small deterministic case samples), xdist-safe (a fresh
run nonce per call, no shared mutable state), and honest (the mock
adapter is the only simulated component; everything else is the real
pipeline).
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from pathlib import Path

from peira.adapters.mock import MockAdapter
from peira.metrics import PerCaseResult, summarize
from peira.runner import load_cases, new_run_nonce, run_suite

ROOT = Path(__file__).resolve().parents[2]
V1_DIR = ROOT / "dataset" / "v1" / "cases"
V2_DIR = ROOT / "dataset" / "v2" / "cases"

#: Suite the integration runs bind to. The dataset *version* is read
#: from the sealed v1 manifest (see dataset_version()); the suite name
#: is a registry key from peira.runner.SUITE_DIRS, stable by design.
SUITE = "v1"


def dataset_version() -> str:
    with open(V1_DIR / "manifest.json") as f:
        return json.load(f)["dataset_version"]


def sample_v1_cases(n_per_family: int = 2):
    """Deterministic sample: the first ``n_per_family`` cases (by case_id)
    from each v1 family. The sample is stable across runs, machines, and
    backends because it is derived from sealed dataset content."""
    cases = load_cases(V1_DIR)
    by_family: dict[str, list] = defaultdict(list)
    for case in cases:
        by_family[case.family].append(case)
    sample = []
    for family in sorted(by_family):
        sample.extend(sorted(by_family[family], key=lambda c: c.case_id)[:n_per_family])
    return sample


def family_case_files() -> dict[str, list[Path]]:
    """Map family id -> case files shipped for it (v1 family files, v2
    per-family drafts). Families with no shipped cases are absent."""
    out: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(V1_DIR.glob("*.jsonl")):
        out[path.stem].append(path)
    if V2_DIR.is_dir():
        for path in sorted(V2_DIR.glob("*.jsonl")):
            out[path.stem].append(path)
    return dict(out)


def make_nonce() -> str:
    """A fresh run nonce per test: mock script namespaces never collide
    across tests, which keeps the suite xdist-safe."""
    return new_run_nonce() + "-" + uuid.uuid4().hex[:8]


def run_mock(cases, *, seed, nonce, flip_rate=0.5, max_concurrency=4):
    """Run cases through the deterministic mock adapter and return the
    sealed RunArtifact."""
    script = MockAdapter.script_for(cases, seed=seed, run_nonce=nonce)
    adapter = MockAdapter(flip_rate=flip_rate, script=script)
    return run_suite(
        adapter,
        cases,
        SUITE,
        dataset_version(),
        seed=seed,
        max_concurrency=max_concurrency,
        run_nonce=nonce,
    )


def summarize_results(artifact, n_boot=500, **kwargs):
    """summarize() over an artifact's sealed results. n_boot is lowered
    from the 10k default for suite speed; the bootstrap path is still
    exercised (CIs are computed, not skipped)."""
    results = [PerCaseResult.from_dict(d) for d in artifact.results]
    return summarize(results, n_boot=n_boot, **kwargs)


# -- Test-double adapters ------------------------------------------------
# The peira adapter protocol requires several class attributes. Test
# doubles share the honest declarations (rule-based, no real
# confidence signal) and refuse the conversational entry point;
# concrete doubles set name/version/cache_namespace and implement
# decide().


class TestAdapterBase:
    supported_primitives = frozenset({"choice", "score", "abstain"})
    confidence_source = "none"
    model_class = "rule-based"

    def decide_turn(self, *args, **kwargs):
        raise NotImplementedError("single-shot test double")


# -- Determinism-contract normalization ---------------------------------
# Mirrors the executable contract in tests/test_determinism.py: these
# fields are documented wall-clock / operational telemetry and are
# excluded from equality claims by docs/Execution-Contract.md.

_NONDETERMINISTIC_RECORD_FIELDS = ("dispatch_limit", "latency_ms_total", "timing_ms")
_NONDETERMINISTIC_METRIC_FIELDS = ("latency_ms", "timing_ms")


def normalize_result(entry: dict) -> dict:
    entry = dict(entry)
    for arm in ("benign", "attacked"):
        rec = dict(entry[arm])
        for field in _NONDETERMINISTIC_RECORD_FIELDS:
            if field in rec:
                rec[field] = 0
        usage = rec.get("usage")
        if isinstance(usage, dict):
            usage = dict(usage)
            usage["latency_ms"] = 0.0
            rec["usage"] = usage
        entry[arm] = rec
    return entry


def normalize_metrics(metrics: dict) -> dict:
    metrics = dict(metrics)
    for field in _NONDETERMINISTIC_METRIC_FIELDS:
        if field in metrics:
            metrics[field] = "excluded-by-contract"
    return metrics


def normalized_artifact_payload(artifact) -> dict:
    """The backend-parity payload: normalized results plus normalized
    metrics. Two pipelines computing the same answers produce identical
    payloads regardless of which backend (Rust / pure Python) ran."""
    return {
        "results": [normalize_result(d) for d in artifact.results],
        "metrics": normalize_metrics(summarize_results(artifact)),
        "verify": artifact.verify(),
    }
