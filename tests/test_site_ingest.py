"""Tests for site/scripts/ingest.py, the sealed run-artifact ingestion gates.

Covers the fail-closed behavior the display pipeline depends on: broken
locks, mock/real mixups, dataset-version and manifest disagreement,
invalid suites, duplicate run identities, non-finite metrics, and the
verbatim-metrics contract. Fixtures are built with the real peira
artifact code path.

The v3 tests cover the sealed extension blocks (config["v3"], per
research_notes/peira-run-artifact-research-20260928.md): shape validation,
closed vocabularies, the run_status=="success" gate (the Inspect rule:
never analyze a non-successful run), and verbatim carry-through into the
site data. Artifacts without v3 blocks keep ingesting unchanged.
"""

import copy
import json
import math
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INGEST = REPO / "site" / "scripts" / "ingest.py"
sys.path.insert(0, str(REPO / "python"))
sys.path.insert(0, str(REPO / "site" / "scripts"))

from peira.artifacts import RunArtifact, results_to_dicts  # noqa: E402
from peira.metrics import CallRecord, PerCaseResult, summarize  # noqa: E402
from gen_mock import build_v3_block  # noqa: E402


def _record(decision, malformed=False):
    return CallRecord(
        decision=decision,
        confidence=0.9,
        abstained=False,
        refusal_reason="",
        usage=None,
        seed=1,
        dispatch_index=0,
        malformed=malformed,
    )


def _result(i, attacked_decision):
    attacked = _record(attacked_decision)
    flipped = attacked_decision != "deny"
    return PerCaseResult(
        case_id=f"ingest-test-{i:04d}",
        family="prompt_injection",
        severity="high",
        primitive="choice",
        benign=_record("deny"),
        attacked=attacked,
        flipped=flipped,
        eligible=True,
    )


def _results_and_summary(n):
    """n eligible mock results plus their sealed metrics summary."""
    results = [_result(i, "allow" if i % 2 else "deny") for i in range(n)]
    return results, summarize(results, n_boot=50)


def make_artifact(path, *, mock=True, suite="public", dataset_version="1.1.1",
                   corrupt_lock=False, manifest_sha256="mock",
                   adapter_name="mock-test", adapter_version="mock-1",
                   metrics_tweak=None, v3=True):
    """Build a sealed test artifact.

    v3=True attaches a valid v3 extension block built by the real
    gen_mock.build_v3_block; v3=None omits it (no prototype block);
    pass a dict to use a custom block (mutated for gate tests).
    """
    results, summary = _results_and_summary(24)
    if metrics_tweak:
        metrics_tweak(summary)
    config = {"mock": mock}
    if v3 is True:
        config["v3"] = build_v3_block(
            random.Random(1234), results, summary, suite, 7,
            "2026-09-29T00:00:00+00:00",
        )
    elif v3 is not None:
        config["v3"] = v3
    art = RunArtifact(
        artifact_version="3",
        peira_version="0.1.0",
        dataset_version=dataset_version,
        adapter_name=adapter_name,
        adapter_version=adapter_version,
        suite=suite,
        created_utc="2026-09-29T00:00:00+00:00",
        config=config,
        results=results_to_dicts(results),
        metrics=summary,
        manifest_sha256=manifest_sha256,
        model_class="rule-based",
        confidence_source="verbalized",
        termination="complete",
        cases_completed=24,
        cases_planned=24,
        seed=7,
    )
    art.seal()
    data = json.loads(art.to_json())
    if corrupt_lock:
        data["analysis_lock"] = "0" * 64
    path.write_text(json.dumps(data))


def _mutate_v3_block(**overrides):
    """Return a valid v3 block with top-level keys overridden (deep)."""
    results, summary = _results_and_summary(24)
    block = build_v3_block(random.Random(1234), results, summary, "public",
                           7, "2026-09-29T00:00:00+00:00")
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(block.get(key), dict):
            block[key] = {**block[key], **value}
        else:
            block[key] = value
    return block


def run_ingest(artifacts_dir, out_path, extra=()):
    cmd = [sys.executable, str(INGEST), *extra, str(artifacts_dir),
           "--out", str(out_path)]
    return subprocess.run(cmd, capture_output=True, text=True)


class IngestGatesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.arts = self.dir / "arts"
        self.arts.mkdir()
        self.out = self.dir / "results.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _one(self, **kw):
        make_artifact(self.arts / "a.json", **kw)

    def test_valid_mock_ingest(self):
        self._one(mock=True, suite="public")
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(self.out.read_text())
        # top-level contract
        self.assertEqual(data["schema_version"], "2")
        self.assertTrue(data["mock_data"])
        self.assertEqual(data["dataset"]["version"], "1.1.1")
        self.assertEqual(data["dataset"]["manifest_sha256"], "mock")
        self.assertEqual(len(data["runs"]), 1)
        run = data["runs"][0]
        self.assertEqual(run["adapter_name"], "mock-test")
        self.assertEqual(run["suite"], "public")
        # v3 blocks ride through verbatim
        self.assertIn("v3", run)
        self.assertEqual(run["v3"]["run_status"], "success")
        # metrics are verbatim from the sealed artifact: recompute and compare
        results = [_result(i, "allow" if i % 2 else "deny") for i in range(24)]
        expected_metrics = summarize(results, n_boot=50)
        self.assertEqual(run["metrics"], expected_metrics)
        # case rows carry the documented schema keys, nothing else
        self.assertEqual(len(run["cases"]), 24)
        for c in run["cases"]:
            self.assertEqual(
                sorted(c.keys()),
                ["attacked_decision", "benign_decision", "case_id", "eligible",
                 "family", "flipped", "primitive", "severity"],
            )

    def test_broken_lock_rejected(self):
        self._one(mock=True, corrupt_lock=True)
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("lock", r.stderr.lower())

    def test_mock_rejected_without_flag(self):
        self._one(mock=True)
        r = run_ingest(self.arts, self.out)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("mock", r.stderr.lower())

    def test_real_rejected_with_mock_flag(self):
        self._one(mock=False)
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("mock", r.stderr.lower())

    def test_dataset_version_mismatch(self):
        make_artifact(self.arts / "a.json", mock=True, dataset_version="1.1.1")
        make_artifact(self.arts / "b.json", mock=True, dataset_version="9.9.9",
                      adapter_name="mock-test-2")
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("dataset", r.stderr.lower())

    def test_invalid_suite_rejected(self):
        self._one(mock=True, suite="staging")
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertNotEqual(r.returncode, 0)

    def test_manifest_sha_mismatch_rejected(self):
        make_artifact(self.arts / "a.json", mock=True, manifest_sha256="aaa")
        make_artifact(self.arts / "b.json", mock=True, manifest_sha256="bbb",
                      adapter_name="mock-test-2")
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("manifest", r.stderr.lower())

    def test_non_boolean_mock_rejected(self):
        self._one(mock="false")
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("boolean", r.stderr.lower())

    def test_duplicate_run_identity_rejected(self):
        make_artifact(self.arts / "a.json", mock=True)
        make_artifact(self.arts / "b.json", mock=True)  # same name/version/suite
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("duplicate", r.stderr.lower())

    def test_nan_metric_rejected(self):
        def inject_nan(summary):
            summary["asr_conditional"] = math.nan
        self._one(mock=True, metrics_tweak=inject_nan)
        r = run_ingest(self.arts, self.out, extra=["--mock"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("non-finite", r.stderr.lower())


class IngestV3Test(unittest.TestCase):
    """v3 extension blocks: validation, the run_status gate, carry-through."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.arts = self.dir / "arts"
        self.arts.mkdir()
        self.out = self.dir / "results.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _one(self, **kw):
        make_artifact(self.arts / "a.json", **kw)

    def _ingest(self):
        return run_ingest(self.arts, self.out, extra=["--mock"])

    def test_v3_carried_through_verbatim(self):
        self._one(mock=True)
        r = self._ingest()
        self.assertEqual(r.returncode, 0, r.stderr)
        run = json.loads(self.out.read_text())["runs"][0]
        v3 = run["v3"]
        # every research-note block present (SHOULD 24 is results-level,
        # not block-level; see build_v3_block)
        for key in ("run_id", "parent_run_id", "supersedes", "run_status",
                    "metrics_version", "adjudication_policy_version",
                    "threat_model", "attack_provenance", "exclusion_log",
                    "determinism_check", "exposure_attestation",
                    "adapter_pinning", "schema_ref", "license",
                    "access_tier", "retention_policy", "reference_baseline",
                    "run_group_id", "repetition_index",
                    "planned_repetitions", "uncertainty", "hardware",
                    "wall_clock", "retry_policy", "cache_policy",
                    "per_family", "submitter_provenance", "dependency_lock",
                    "threshold_policy_version", "sampling_plan"):
            self.assertIn(key, v3, f"v3 missing {key}")
        # typed per-family list has the documented shape
        self.assertTrue(v3["per_family"])
        for entry in v3["per_family"]:
            self.assertEqual(
                sorted(entry.keys()),
                ["asr", "ci_hi", "ci_lo", "family", "n", "n_eligible"],
            )

    def test_v3_exclusion_log_matches_ineligible_cases(self):
        # one ineligible case (malformed benign arm): the v3 block built
        # from these results must log exactly that case with its reason
        from dataclasses import replace
        results, _ = _results_and_summary(8)
        bad = replace(
            _result(99, "deny"),
            benign=_record("deny", malformed=True),
            eligible=False,
            ineligibility_reason="benign_malformed",
            flipped=False,
        )
        results.append(bad)
        summary = summarize(results, n_boot=50)
        config = {
            "mock": True,
            "v3": build_v3_block(random.Random(99), results, summary,
                                 "public", 7, "2026-09-29T00:00:00+00:00"),
        }
        art = RunArtifact(
            artifact_version="3", peira_version="0.1.0",
            dataset_version="1.1.1", adapter_name="mock-test",
            adapter_version="mock-1", suite="public",
            created_utc="2026-09-29T00:00:00+00:00", config=config,
            results=results_to_dicts(results), metrics=summary,
            manifest_sha256="mock", model_class="rule-based",
            confidence_source="verbalized", termination="complete",
            cases_completed=9, cases_planned=9, seed=7,
        )
        art.seal()
        (self.arts / "a.json").write_text(art.to_json())
        r = self._ingest()
        self.assertEqual(r.returncode, 0, r.stderr)
        log = json.loads(self.out.read_text())["runs"][0]["v3"]["exclusion_log"]
        self.assertEqual(len(log), 1)
        self.assertEqual(log[0]["case_id"], "ingest-test-0099")
        self.assertEqual(log[0]["arm"], "benign")
        self.assertEqual(log[0]["reason_code"], "benign_malformed")

    def test_v3_exclusion_log_accepts_attacked_arm(self):
        # the generator only ever emits benign-arm exclusions (it mirrors
        # gen_case eligibility), so exercise the attacked arm by mutation:
        # ingest must accept it and carry it through verbatim
        block = _mutate_v3_block()
        block["exclusion_log"] = [{
            "case_id": "ingest-test-0001",
            "arm": "attacked",
            "reason_code": "attacked_malformed",
        }]
        self._one(mock=True, v3=block)
        r = self._ingest()
        self.assertEqual(r.returncode, 0, r.stderr)
        log = json.loads(self.out.read_text())["runs"][0]["v3"]["exclusion_log"]
        self.assertEqual(log, [{
            "case_id": "ingest-test-0001",
            "arm": "attacked",
            "reason_code": "attacked_malformed",
        }])

    def test_non_success_run_status_rejected(self):
        for status in ("started", "cancelled", "error", "partial"):
            with self.subTest(status=status):
                self._one(mock=True,
                          v3=_mutate_v3_block(run_status=status))
                r = self._ingest()
                self.assertNotEqual(r.returncode, 0, r.stderr)
                self.assertIn("success", r.stderr.lower())

    def test_v3_bad_enum_rejected(self):
        self._one(mock=True, v3=_mutate_v3_block(
            threat_model={"attacker_access": "telepathy"}))
        r = self._ingest()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("attacker_access", r.stderr)

    def test_v3_bad_exposure_enum_rejected(self):
        self._one(mock=True, v3=_mutate_v3_block(
            exposure_attestation={"case_subset": "holdout"}))
        r = self._ingest()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("case_subset", r.stderr)

    def test_v3_missing_required_key_rejected(self):
        block = _mutate_v3_block()
        del block["threat_model"]
        self._one(mock=True, v3=block)
        r = self._ingest()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("threat_model", r.stderr)

    def test_v3_non_object_rejected(self):
        self._one(mock=True, v3="not-a-dict")
        r = self._ingest()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("v3", r.stderr.lower())

    def test_v3_bad_exclusion_entry_rejected(self):
        block = _mutate_v3_block()
        block["exclusion_log"] = [
            {"case_id": "x", "arm": "benign", "reason_code": "vibes"}
        ]
        self._one(mock=True, v3=block)
        r = self._ingest()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("reason_code", r.stderr)

    def test_v3_bad_determinism_check_rejected(self):
        block = _mutate_v3_block()
        block["determinism_check"] = {"passed": "yes"}
        self._one(mock=True, v3=block)
        r = self._ingest()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("determinism_check", r.stderr)

    def test_no_v3_block_still_ingests(self):
        # artifacts without the prototype v3 block ingest exactly as
        # before, with no v3 key on the run object
        self._one(mock=True, v3=None)
        r = self._ingest()
        self.assertEqual(r.returncode, 0, r.stderr)
        run = json.loads(self.out.read_text())["runs"][0]
        self.assertNotIn("v3", run)

    def test_v3_tamper_breaks_lock(self):
        # the v3 block is sealed: editing it after seal breaks verify()
        self._one(mock=True)
        data = json.loads((self.arts / "a.json").read_text())
        data["config"]["v3"]["license"] = "ALL-RIGHTS-RESERVED"
        (self.arts / "a.json").write_text(json.dumps(data))
        r = self._ingest()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("lock", r.stderr.lower())


if __name__ == "__main__":
    unittest.main()
