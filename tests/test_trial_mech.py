"""Tests for the Trial-suite mechanism (run with: python -m unittest discover tests).

Covers the forward-compatible case schema (extras), the branded 100-case
Peira Trial in dataset/trial, dataset-version flow into run artifacts, and
the per-case report table. The Trial cases are the real pilot set — these
tests pin the mechanism around them.
"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

from peira.artifacts import RunArtifact
from peira.dataset import verify_manifest
from peira.gates import run_gates
from peira.runner import SUITE_DIRS, load_cases
from peira.schema import Case, validate_case_dict

REPO_ROOT = Path(__file__).resolve().parents[1]
TRIAL_DIR = REPO_ROOT / SUITE_DIRS["trial"]


def _valid_dict(**over):
    d = {
        "case_id": "t1",
        "family": "state_poisoning",
        "primitive": "choice",
        "severity": "high",
        "benign": {"input": {"prompt": "b", "options": ["deny", "approve"]}, "expected_decision": "deny"},
        "attacked": {"input": {"prompt": "b plus attack", "options": ["deny", "approve"]}, "target_decision": "approve"},
    }
    d.update(over)
    return d


class TestSchemaForwardCompat(unittest.TestCase):
    def test_validator_ignores_unknown_keys(self):
        d = _valid_dict(extra_field="anything", nested={"a": [1, 2]})
        self.assertEqual(validate_case_dict(d), [])

    def test_from_dict_preserves_extras(self):
        d = _valid_dict(canary="peira-trial-canary:x", run_config={"k": 1})
        c = Case.from_dict(d)
        self.assertEqual(c.extras, {"canary": "peira-trial-canary:x",
                                    "run_config": {"k": 1}})
        self.assertEqual(c.case_id, "t1")  # known fields unaffected

    def test_to_dict_round_trips_extras(self):
        d = _valid_dict(canary="peira-trial-canary:x")
        c = Case.from_dict(d)
        self.assertEqual(c.to_dict()["canary"], "peira-trial-canary:x")
        # And the round-tripped dict still validates.
        self.assertEqual(validate_case_dict(c.to_dict()), [])

    def test_no_extras_by_default(self):
        c = Case.from_dict(_valid_dict())
        self.assertEqual(c.extras, {})
        self.assertNotIn("extras", c.to_dict())

    def test_expected_score_round_trip(self):
        for v in (None, 0.0, 0.5, 1.0):
            d = _valid_dict()
            d["benign"]["expected_score"] = v
            c = Case.from_dict(d)
            self.assertEqual(c.benign.expected_score, v)
            self.assertEqual(c.to_dict()["benign"]["expected_score"], v)
            self.assertEqual(validate_case_dict(c.to_dict()), [])

    def test_expected_score_absent_is_none(self):
        c = Case.from_dict(_valid_dict())
        self.assertIsNone(c.benign.expected_score)
        # to_dict emits the key explicitly, like target_decision.
        self.assertIsNone(c.to_dict()["benign"]["expected_score"])


class TestTrialSuite(unittest.TestCase):
    def test_suite_dir_exists(self):
        self.assertTrue(TRIAL_DIR.is_dir(), f"{TRIAL_DIR} missing")

    def test_cases_load(self):
        cases = load_cases(TRIAL_DIR)
        self.assertEqual(len(cases), 100)

    def test_all_families_covered_evenly(self):
        from collections import Counter
        counts = Counter(c.family for c in load_cases(TRIAL_DIR))
        self.assertEqual(len(counts), 10)
        self.assertTrue(all(n == 10 for n in counts.values()), dict(counts))

    def test_gates_pass(self):
        from peira.dataset import iter_case_lines
        results = run_gates(TRIAL_DIR)
        errors = [e for r in results for e in r.errors]
        self.assertEqual(errors, [])

    def test_manifest_matches(self):
        self.assertEqual(verify_manifest(TRIAL_DIR), [])

    def test_manifest_version(self):
        manifest = json.loads((TRIAL_DIR / "manifest.json").read_text())
        self.assertEqual(manifest["dataset_version"], "1.0.5")
        self.assertEqual(manifest["files"]["cases.jsonl"]["n_cases"], 100)

    def test_canary_embedded(self):
        canary = (TRIAL_DIR / "CANARY.txt").read_text().strip()
        self.assertTrue(canary)
        for line in (TRIAL_DIR / "cases.jsonl").read_text().splitlines():
            if line.strip():
                self.assertIn(canary, line)


class TestTrialRunMechanism(unittest.TestCase):
    def _run_cli(self, *argv):
        env = dict(__import__("os").environ)
        env["PYTHONPATH"] = str(REPO_ROOT / "python") + ":" + env.get("PYTHONPATH", "")
        return subprocess.run(
            [sys.executable, "-m", "peira.cli", *argv],
            capture_output=True, text=True, env=env, cwd=REPO_ROOT,
        )

    def test_run_records_manifest_dataset_version(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            r = self._run_cli("run", "--adapter", "mock", "--suite", "trial",
                              "--out", tmp, "--dry-run")
            # dry-run first: config valid, nothing scored
            self.assertEqual(r.returncode, 0, r.stderr)
            r = self._run_cli("run", "--adapter", "mock", "--suite", "trial",
                              "--out", tmp)
            self.assertIn(r.returncode, (0, 3), r.stderr)  # 3 = ineligible, fine
            artifact = RunArtifact.from_json(
                Path(tmp, "mock-trial.json").read_text())
            self.assertEqual(artifact.dataset_version, "1.0.5")
            self.assertTrue(artifact.verify())
            self.assertEqual(len(artifact.results), 100)

    def test_dry_run_creates_no_output_dir(self):
        # --dry-run must have zero side effects: not even the --out
        # directory may be created.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = str(Path(tmp, "never-created"))
            r = self._run_cli("run", "--adapter", "mock", "--suite",
                              "trial-demo", "--out", out_dir, "--dry-run")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("dry run", r.stdout)
            self.assertFalse(Path(out_dir).exists())

    def test_report_has_per_case_table(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._run_cli("run", "--adapter", "mock", "--suite", "trial",
                          "--out", tmp)
            run_path = str(Path(tmp, "mock-trial.json"))
            out_path = str(Path(tmp, "report.html"))
            r = self._run_cli("report", "--run", run_path, "--out", out_path)
            self.assertEqual(r.returncode, 0, r.stderr)
            # Read raw bytes: the report must be valid UTF-8 regardless of
            # the platform default encoding (regression: ✓/✗ broke the
            # Windows quickstart when write_text used the locale default).
            html = Path(out_path).read_bytes().decode("utf-8")
            self.assertIn("Per-case results", html)
            self.assertIn("tr-sp-001", html)

    def test_report_escapes_author_controlled_strings(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self._run_cli("run", "--adapter", "mock", "--suite", "trial",
                          "--out", tmp)
            run_path = Path(tmp, "mock-trial.json")
            # Simulate author-controlled strings reaching the report: a
            # hostile case id, family label, and adapter name must all land
            # inert in the HTML (the analysis-lock warning is expected —
            # the report is still rendered).
            data = json.loads(run_path.read_text())
            data["results"][0]["case_id"] = "<script>alert('case')</script>"
            data["results"][0]["family"] = "<img src=x onerror=alert('fam')>"
            data["adapter_name"] = "<b>evil-adapter</b>"
            run_path.write_text(json.dumps(data))
            out_path = str(Path(tmp, "report.html"))
            r = self._run_cli("report", "--run", str(run_path),
                              "--out", out_path)
            self.assertEqual(r.returncode, 0, r.stderr)
            html = Path(out_path).read_text(encoding="utf-8")
            for raw in ("<script>alert('case')</script>",
                        "<img src=x onerror=alert('fam')>",
                        "<b>evil-adapter</b>"):
                self.assertNotIn(raw, html)
            self.assertIn("&lt;script&gt;", html)
            self.assertIn("&lt;img src=x onerror=alert(&#x27;fam&#x27;)&gt;",
                          html)
            self.assertIn("&lt;b&gt;evil-adapter&lt;/b&gt;", html)


if __name__ == "__main__":
    unittest.main()
