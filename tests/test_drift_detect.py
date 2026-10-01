"""Tests for the ASR drift detector (scripts/drift_detect.py)."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import drift_detect  # noqa: E402


def _metrics(asr, n, families=None, dataset_version="2.4.0",
             benign_accuracy=0.9, env_sha256="abc123", adapter_name="x",
             targeted_asr=None):
    m = {
        "asr_conditional": asr,
        "n_eligible": n,
        "benign_accuracy": benign_accuracy,
        "dataset_version": dataset_version,
        "adapter_name": adapter_name,
        "env_sha256": env_sha256,
        "per_family": {},
    }
    if targeted_asr is not None:
        m["targeted_asr"] = targeted_asr
    for fam, (fasr, fn) in (families or {}).items():
        m["per_family"][fam] = {"asr": fasr, "n": fn}
    return m


class TestZTest(unittest.TestCase):
    def test_identical_proportions(self):
        z, p = drift_detect.z_test(10, 100, 10, 100)
        self.assertAlmostEqual(z, 0.0)
        self.assertAlmostEqual(p, 1.0)

    def test_clear_difference_is_significant(self):
        z, p = drift_detect.z_test(10, 400, 80, 400)
        self.assertLess(p, 1e-6)

    def test_zero_variance(self):
        z, p = drift_detect.z_test(0, 100, 0, 100)
        self.assertEqual(p, 1.0)


class TestCompareSlice(unittest.TestCase):
    def test_drift_up_detected(self):
        r = drift_detect.compare_slice(
            (0.10, 400), (0.20, 400), alpha=0.05,
            min_n=30, effect_floor=0.02)
        self.assertEqual(r["verdict"], "DRIFT UP")

    def test_drift_down_detected(self):
        r = drift_detect.compare_slice(
            (0.20, 400), (0.10, 400), alpha=0.05,
            min_n=30, effect_floor=0.02)
        self.assertEqual(r["verdict"], "DRIFT DOWN")

    def test_stable_when_unchanged(self):
        r = drift_detect.compare_slice(
            (0.15, 400), (0.15, 400), alpha=0.05,
            min_n=30, effect_floor=0.02)
        self.assertEqual(r["verdict"], "STABLE")

    def test_insufficient_data_below_floor(self):
        r = drift_detect.compare_slice(
            (0.10, 10), (0.50, 10), alpha=0.05,
            min_n=30, effect_floor=0.02)
        self.assertEqual(r["verdict"], "INSUFFICIENT DATA")

    def test_watch_when_significant_but_small(self):
        # Huge n makes a 1-point move significant, but it is below the
        # 2-point effect floor, so it must be WATCH, not DRIFT UP.
        r = drift_detect.compare_slice(
            (0.10, 20000), (0.11, 20000), alpha=0.05,
            min_n=30, effect_floor=0.02)
        self.assertLess(r["p"], 0.05)
        self.assertEqual(r["verdict"], "WATCH")


class TestDriftReport(unittest.TestCase):
    def test_report_detects_family_drift(self):
        base = _metrics(0.12, 800, {"f1": (0.10, 400), "f2": (0.14, 400)})
        curr = _metrics(0.18, 800, {"f1": (0.26, 400), "f2": (0.14, 400)})
        report = drift_detect.drift_report(base, curr)
        self.assertIn("DRIFT UP", report)
        # f2 did not move: it must read STABLE, not drift.
        for line in report.splitlines():
            if line.startswith("| f2 |"):
                self.assertIn("STABLE", line)

    def test_dataset_mismatch_refuses(self):
        base = _metrics(0.12, 800, dataset_version="2.3.0")
        curr = _metrics(0.18, 800, dataset_version="2.4.0")
        report = drift_detect.drift_report(base, curr)
        self.assertIn("Not comparable", report)
        self.assertNotIn("DRIFT UP", report)

    def test_utility_check_present(self):
        base = _metrics(0.12, 800, benign_accuracy=0.90)
        curr = _metrics(0.18, 800, benign_accuracy=0.75)
        report = drift_detect.drift_report(base, curr)
        self.assertIn("75.0%", report)
        self.assertIn("model degradation", report)

    def test_utility_prefers_targeted_asr_block(self):
        base = _metrics(0.12, 800, benign_accuracy=0.90,
                        targeted_asr={"benign_utility": 0.88})
        curr = _metrics(0.18, 800, benign_accuracy=0.90,
                        targeted_asr={"benign_utility": 0.70})
        report = drift_detect.drift_report(base, curr)
        # The targeted_asr figure (0.88 -> 0.70) wins over the flat
        # top-level benign_accuracy (0.90 -> 0.90).
        self.assertIn("70.0%", report)
        self.assertIn("targeted_asr.benign_utility", report)
        val, src = drift_detect._benign_utility(base)
        self.assertEqual(val, 0.88)
        self.assertEqual(src, "targeted_asr.benign_utility")

    def test_utility_falls_back_to_benign_accuracy(self):
        m = _metrics(0.12, 800, benign_accuracy=0.90)
        val, src = drift_detect._benign_utility(m)
        self.assertEqual(val, 0.90)
        self.assertEqual(src, "benign_accuracy")

    def test_series_identity_conflict_blocks_comparison(self):
        base_m = _metrics(0.12, 800)
        curr_m = _metrics(0.18, 800)
        del base_m["adapter_name"]
        del curr_m["adapter_name"]
        base = {"adapter_name": "x", "dataset_version": "2.4.0",
                "metrics": base_m}
        curr = {"adapter_name": "y", "dataset_version": "2.4.0",
                "metrics": curr_m}
        report = drift_detect.drift_report(base, curr)
        self.assertIn("## Not comparable", report)
        self.assertIn("one adapter on one suite", report)

    def test_series_identity_allows_pin_changes(self):
        base = {"adapter_name": "x", "dataset_version": "2.4.0",
                "adapter_version": "v1", "metrics": _metrics(0.12, 800)}
        curr = {"adapter_name": "x", "dataset_version": "2.4.0",
                "adapter_version": "v2", "metrics": _metrics(0.18, 800)}
        self.assertEqual(drift_detect.check_comparable(base, curr), [])

    def test_all_insufficient_data_is_not_stability(self):
        base = _metrics(0.12, 10)
        curr = _metrics(0.18, 10)
        report = drift_detect.drift_report(base, curr)
        self.assertIn("No usable data", report)
        self.assertNotIn("stable across the series", report)

    def test_identity_fields_read_from_artifact_level(self):
        # Real run artifacts carry adapter/dataset/pin fields at the
        # artifact level, outside the metrics block.
        base = {"adapter_name": "x", "dataset_version": "2.4.0",
                "adapter_version": "v1",
                "metrics": _metrics(0.12, 800)}
        curr = {"adapter_name": "x", "dataset_version": "2.4.0",
                "adapter_version": "v1",
                "metrics": _metrics(0.18, 800)}
        report = drift_detect.drift_report(base, curr)
        self.assertIn("adapter=x", report)
        self.assertIn("pin=v1", report)
        self.assertIn("dataset=2.4.0", report)

    def test_bonferroni_scales_with_families(self):
        # With 25 families the corrected alpha is about 0.002. A signal
        # that is significant at the uncorrected 0.05 level (p ~ 0.02)
        # must not survive the correction.
        fams = {f"f{i}": (0.10, 400) for i in range(25)}
        base = _metrics(0.10, 10000, fams)
        moved = dict(fams)
        moved["f0"] = (0.155, 400)
        curr = _metrics(0.101, 10000, moved)
        _, uncorrected_p = drift_detect.z_test(40, 400, 62, 400)
        self.assertLess(uncorrected_p, 0.05)
        report = drift_detect.drift_report(base, curr)
        f0_line = next(
            line for line in report.splitlines() if line.startswith("| f0 |"))
        self.assertNotIn("DRIFT UP", f0_line)


class TestLoadMetrics(unittest.TestCase):
    def test_accepts_full_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.json"
            path.write_text(json.dumps({
                "metrics": _metrics(0.1, 100),
                "analysis_lock": "deadbeef",
            }), encoding="utf-8")
            doc = drift_detect.load_metrics(path)
        m = drift_detect.metrics_block(doc)
        self.assertEqual(m["asr_conditional"], 0.1)
        self.assertEqual(doc["analysis_lock"], "deadbeef")

    def test_accepts_bare_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrics.json"
            path.write_text(json.dumps(_metrics(0.2, 100)), encoding="utf-8")
            m = drift_detect.load_metrics(path)
        self.assertEqual(m["asr_conditional"], 0.2)

    def test_rejects_garbage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.json"
            path.write_text("not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                drift_detect.load_metrics(path)


class TestCli(unittest.TestCase):
    def test_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_p = Path(tmp) / "base.json"
            curr_p = Path(tmp) / "curr.json"
            base_p.write_text(json.dumps(_metrics(
                0.10, 800, {"f1": (0.10, 400)})), encoding="utf-8")
            curr_p.write_text(json.dumps(_metrics(
                0.20, 800, {"f1": (0.24, 400)})), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "drift_detect.py"),
                 str(base_p), str(curr_p)],
                capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("DRIFT UP", proc.stdout)

    def test_cli_refuses_incomparable(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_p = Path(tmp) / "base.json"
            curr_p = Path(tmp) / "curr.json"
            base_p.write_text(
                json.dumps(_metrics(0.10, 800, dataset_version="2.3.0")),
                encoding="utf-8")
            curr_p.write_text(
                json.dumps(_metrics(0.20, 800, dataset_version="2.4.0")),
                encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "drift_detect.py"),
                 str(base_p), str(curr_p)],
                capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Not comparable", proc.stdout)

    def test_cli_null_metrics_is_a_clean_error(self):
        # {"metrics": null} must follow the documented error path:
        # a concise message and exit 2, not a traceback and exit 1.
        with tempfile.TemporaryDirectory() as tmp:
            base_p = Path(tmp) / "base.json"
            curr_p = Path(tmp) / "curr.json"
            base_p.write_text(
                json.dumps({"metrics": None}), encoding="utf-8")
            curr_p.write_text(
                json.dumps(_metrics(0.20, 800)), encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(REPO_ROOT / "scripts" / "drift_detect.py"),
                 str(base_p), str(curr_p)],
                capture_output=True, text=True, check=False)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("drift_detect:", proc.stderr)
        self.assertNotIn("Traceback", proc.stderr)


if __name__ == "__main__":
    unittest.main()
