"""Tests for scripts/emit_leaderboard.py (run with: python -m unittest discover tests).

Builds small sealed artifacts programmatically — no dependence on
dataset/trial's contents. Covers the projection (artifact -> row), the
fail-closed verification behavior, and output determinism.
"""

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from peira.artifacts import RunArtifact


def _load_script():
    path = Path(__file__).resolve().parents[1] / "scripts" / "emit_leaderboard.py"
    spec = importlib.util.spec_from_file_location("emit_leaderboard", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


emit_leaderboard = _load_script()


def _call(decision="approve"):
    return {
        "decision": decision,
        "confidence": 0.9,
        "abstained": False,
        "refusal_reason": "",
        "usage": None,
        "seed": 0,
        "dispatch_index": 0,
        "malformed": False,
        "dispatch_limit": 1,
    }


def _entry(case_id, family, flipped, eligible=True, reason=""):
    return {
        "case_id": case_id,
        "family": family,
        "severity": "medium",
        "primitive": "choice",
        "benign": _call("approve"),
        "attacked": _call("deny" if flipped else "approve"),
        "flipped": flipped,
        "eligible": eligible,
        "ineligibility_reason": reason,
    }


def _metrics():
    return {
        "n_cases": 6,
        "n_eligible": 5,
        "asr_conditional": 0.6,
        "asr_ci95": [0.23, 0.88],
        "benign_accuracy": 1.0,
        "benign_accuracy_ci95": [0.56, 1.0],
        "malformed_rate": 0.0,
        "refusal_rate": 0.0,
        "refusal_rate_ci95": [0.0, 0.43],
        "ineligible_by_reason": {"benign abstained": 1},
        "ranking_eligible": False,
        "eligibility_notes": ["fewer than 200 eligible cases (5)"],
        "per_family": {
            "fam_a": {
                "n": 3,
                "n_eligible": 3,
                "asr": 1 / 3,
                "asr_ci95": [0.06, 0.79],
                "refusal_rate": 0.0,
            },
            "fam_b": {
                "n": 3,
                "n_eligible": 2,
                "asr": 1.0,
                "asr_ci95": [0.34, 1.0],
                "refusal_rate": 0.0,
            },
        },
    }


def _artifact(**overrides):
    results = [
        _entry("a1", "fam_a", True),
        _entry("a2", "fam_a", False),
        _entry("a3", "fam_a", False),
        _entry("b1", "fam_b", True),
        _entry("b2", "fam_b", True),
        _entry("b3", "fam_b", False, eligible=False, reason="benign abstained"),
    ]
    art = RunArtifact(
        **{
            "adapter_name": "mock",
            "adapter_version": "0.2.0",
            "suite": "trial",
            "dataset_version": "1.0.1",
            "manifest_sha256": "ab" * 32,
            "pricing_source": "unit-test",
            "pricing_date": "2026-09-23",
            "seed": 7,
            "created_utc": "2026-09-23T00:00:00+00:00",
            "results": results,
            **overrides,
        },
    )
    art.metrics = _metrics()
    return art.seal()


class TestEmitLeaderboard(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.artifact_path = self.root / "run.json"
        self.artifact_path.write_text(_artifact().to_json(), encoding="utf-8")
        self.out_path = self.root / "leaderboard.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _emit(self, *paths, **kwargs):
        # Projection tests opt out of suite exclusion: the fixture
        # artifact uses the trial suite, and these tests verify the row
        # shape, not the D-8 filter (covered separately below).
        kwargs.setdefault("exclude_suites", ())
        paths = [Path(p) for p in paths] or [self.artifact_path]
        return emit_leaderboard.emit_leaderboard(
            paths, self.out_path, generated_utc="2026-09-23T12:00:00+00:00",
            **kwargs,
        )

    def _row(self, doc):
        self.assertEqual(doc["n_rows"], 1)
        return doc["rows"][0]

    def test_row_projection(self):
        row = self._row(self._emit())
        digest = hashlib.sha256(
            self.artifact_path.read_bytes()
        ).hexdigest()
        self.assertEqual(row["run_id"], digest)
        self.assertEqual(row["artifact_sha256"], digest)
        self.assertEqual(row["adapter_name"], "mock")
        self.assertEqual(row["adapter_version"], "0.2.0")
        self.assertEqual(row["suite"], "trial")
        self.assertEqual(row["dataset_version"], "1.0.1")
        self.assertTrue(row["manifest_bound"])
        self.assertEqual(row["manifest_sha256"], "ab" * 32)
        self.assertEqual(row["seed"], 7)
        self.assertTrue(row["lock_verified"])
        self.assertEqual(len(row["analysis_lock"]), 64)
        self.assertEqual(row["n_cases"], 6)
        self.assertEqual(row["n_eligible"], 5)
        self.assertAlmostEqual(row["asr_conditional"], 0.6)
        self.assertFalse(row["ranking_eligible"])
        self.assertEqual(
            row["eligibility_notes"], ["fewer than 200 eligible cases (5)"]
        )
        self.assertEqual(
            row["ineligible_by_reason"], {"benign abstained": 1}
        )

    def test_per_family_values_passed_through(self):
        # The emitter does not compute intervals: these are the runner's
        # sealed Wilson CIs, passed through unchanged. (fam_a 1/3 ->
        # [0.0615, 0.7923]; fam_b 2/2 eligible -> [0.3424, 1.0].)
        row = self._row(self._emit())
        fam_a = row["per_family"]["fam_a"]
        self.assertEqual(fam_a["n"], 3)
        self.assertEqual(fam_a["n_eligible"], 3)
        self.assertAlmostEqual(fam_a["asr"], 1 / 3)
        self.assertEqual(fam_a["asr_ci95"], [0.06, 0.79])
        fam_b = row["per_family"]["fam_b"]
        self.assertEqual(fam_b["asr"], 1.0)
        self.assertEqual(fam_b["asr_ci95"], [0.34, 1.0])

    def test_document_envelope(self):
        doc = self._emit()
        self.assertEqual(doc["leaderboard_schema_version"], "1")
        self.assertEqual(doc["generated_utc"], "2026-09-23T12:00:00+00:00")
        self.assertEqual(doc["generator"], "scripts/emit_leaderboard.py")
        self.assertIn("emitter_peira_version", doc)
        # Written file parses and round-trips the returned document.
        on_disk = json.loads(self.out_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk, doc)

    def test_deterministic_bytes(self):
        self._emit()
        first = self.out_path.read_bytes()
        self._emit()
        self.assertEqual(self.out_path.read_bytes(), first)

    def test_rejects_tampered_artifact(self):
        tampered = json.loads(self.artifact_path.read_text(encoding="utf-8"))
        tampered["results"][0]["flipped"] = not tampered["results"][0][
            "flipped"
        ]
        bad = self.root / "tampered.json"
        bad.write_text(json.dumps(tampered), encoding="utf-8")
        with self.assertRaises(emit_leaderboard.LeaderboardError):
            emit_leaderboard.emit_leaderboard(
                [bad], self.out_path, generated_utc="2026-09-23T12:00:00+00:00"
            )

    def test_rejects_v1_artifact(self):
        v1 = self.root / "v1.json"
        v1.write_text(
            json.dumps(
                {
                    "artifact_version": "1",
                    "peira_version": "0.1.0",
                    "dataset_version": "x",
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaises(emit_leaderboard.LeaderboardError):
            emit_leaderboard.emit_leaderboard(
                [v1], self.out_path, generated_utc="2026-09-23T12:00:00+00:00"
            )

    def test_missing_metrics_key_fails(self):
        art = _artifact()
        art.metrics = {}
        nocov = self.root / "no-metrics.json"
        nocov.write_text(art.seal().to_json(), encoding="utf-8")
        with self.assertRaises(emit_leaderboard.LeaderboardError):
            emit_leaderboard.emit_leaderboard(
                [nocov],
                self.out_path,
                generated_utc="2026-09-23T12:00:00+00:00",
                exclude_suites=(),
            )

    def test_empty_input_fails(self):
        with self.assertRaises(emit_leaderboard.LeaderboardError):
            emit_leaderboard.emit_leaderboard(
                [], self.out_path, generated_utc="2026-09-23T12:00:00+00:00"
            )

    def test_directory_input_and_dedup(self):
        second = self.root / "runs"
        second.mkdir()
        (second / "run.json").write_bytes(self.artifact_path.read_bytes())
        other = second / "other.json"
        other.write_text(
            _artifact(adapter_name="other-mock").to_json(), encoding="utf-8"
        )
        paths = emit_leaderboard.collect_artifact_paths(
            [str(self.artifact_path)], str(second)
        )
        # Three paths in (root/run.json, runs/run.json, runs/other.json);
        # the first two are byte-identical, so they collapse to one row.
        self.assertEqual(len(paths), 3)
        doc = emit_leaderboard.emit_leaderboard(
            paths,
            self.out_path,
            generated_utc="2026-09-23T12:00:00+00:00",
            exclude_suites=(),
        )
        self.assertEqual(doc["n_rows"], 2)
        # Rows sorted by run_id regardless of input order.
        run_ids = [r["run_id"] for r in doc["rows"]]
        self.assertEqual(run_ids, sorted(run_ids))
        names = {r["adapter_name"] for r in doc["rows"]}
        self.assertEqual(names, {"mock", "other-mock"})

    def test_main_usage_error(self):
        rc = emit_leaderboard.main(["--out", str(self.out_path)])
        self.assertEqual(rc, 1)

    def test_main_ok(self):
        # The fixture uses the trial suite; the emitter excludes it by
        # default, so opt out to exercise the happy path via main().
        rc = emit_leaderboard.main(
            [
                str(self.artifact_path),
                "--out",
                str(self.out_path),
                "--exclude-suite=",
            ]
        )
        self.assertEqual(rc, 0)
        doc = json.loads(self.out_path.read_text(encoding="utf-8"))
        self.assertEqual(doc["n_rows"], 1)

    def test_trial_suite_excluded_by_default(self):
        # D-8: the trial fixture is excluded unless the caller opts out.
        doc = emit_leaderboard.emit_leaderboard(
            [self.artifact_path],
            self.out_path,
            generated_utc="2026-09-23T12:00:00+00:00",
        )
        self.assertEqual(doc["n_rows"], 0)
        self.assertEqual(doc["n_excluded_suites"], 1)
        self.assertEqual(doc["rows"], [])

    def test_exclude_suite_opt_out(self):
        doc = self._emit(exclude_suites=())
        self.assertEqual(doc["n_rows"], 1)
        self.assertEqual(doc["n_excluded_suites"], 0)

    def test_malformed_metric_shape_fails(self):
        # A string CI must fail loudly, not spread into a char list.
        art = _artifact()
        art.metrics = dict(_metrics())
        art.metrics["asr_ci95"] = "not-an-interval"
        bad = self.root / "bad-shape.json"
        bad.write_text(art.seal().to_json(), encoding="utf-8")
        with self.assertRaises(emit_leaderboard.LeaderboardError) as ctx:
            emit_leaderboard.emit_leaderboard(
                [bad],
                self.out_path,
                generated_utc="2026-09-23T12:00:00+00:00",
                exclude_suites=(),
            )
        self.assertIn("asr_ci95", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
