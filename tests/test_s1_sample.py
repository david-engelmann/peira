"""Unit tests for scripts/s1_sample.py (run with: python -m unittest discover tests)."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import s1_sample  # noqa: E402


def _make_cases_dir(root: Path, families=("fam_a", "fam_b"), n=6) -> Path:
    cases = root / "cases"
    cases.mkdir(parents=True)
    for fam in families:
        with open(cases / f"{fam}.jsonl", "w", encoding="utf-8") as f:
            for i in range(1, n + 1):
                # family slug embedded so IDs are unique across families
                f.write(json.dumps({"case_id": f"v1-{fam}-{i:03d}"}) + "\n")
    return cases


def _exclusions(root: Path, excluded) -> Path:
    p = root / "exclusions.json"
    p.write_text(json.dumps({
        "excluded_ids": excluded,
        "sources": {"audit_50": [], "pr5_in_place": []},
    }), encoding="utf-8")
    return p


class SampleTest(unittest.TestCase):
    def test_deterministic_byte_identical(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = _make_cases_dir(root)
            excl = _exclusions(root, ["v1-fam_a-001"])
            out1, out2 = root / "s1.json", root / "s2.json"
            args = ["--seed", "20260928", "--per-family", "2",
                    "--exclude", str(excl), "--cases", str(cases),
                    "--timestamp", "2026-09-28T00:00:00+00:00"]
            self.assertEqual(s1_sample.main(args + ["--out", str(out1)]), 0)
            self.assertEqual(s1_sample.main(args + ["--out", str(out2)]), 0)
            self.assertEqual(out1.read_bytes(), out2.read_bytes())

    def test_different_seed_different_sample(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = _make_cases_dir(root, n=20)
            excl = _exclusions(root, ["v1-fam_a-001"])
            outs = []
            for seed in ("20260928", "1"):
                out = root / f"s{seed}.json"
                s1_sample.main(["--seed", seed, "--per-family", "5",
                                "--exclude", str(excl), "--cases", str(cases),
                                "--out", str(out),
                                "--timestamp", "2026-09-28T00:00:00+00:00"])
                outs.append(json.loads(out.read_text()))
            ids1 = [c["case_id"] for c in outs[0]["cases"]]
            ids2 = [c["case_id"] for c in outs[1]["cases"]]
            self.assertNotEqual(ids1, ids2)

    def test_exclusions_honored_and_counts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = _make_cases_dir(root, n=6)
            excluded = ["v1-fam_a-001", "v1-fam_a-002"]
            excl = _exclusions(root, excluded)
            out = root / "s.json"
            s1_sample.main(["--seed", "20260928", "--per-family", "2",
                            "--exclude", str(excl), "--cases", str(cases),
                            "--out", str(out),
                            "--timestamp", "2026-09-28T00:00:00+00:00"])
            doc = json.loads(out.read_text())
            ids = [c["case_id"] for c in doc["cases"]]
            for x in excluded:
                self.assertNotIn(x, ids)
            # per-family counts exact, replacements drawn from same family
            from collections import Counter
            fams = Counter(c["family"] for c in doc["cases"])
            self.assertEqual(dict(fams), {"fam_a": 2, "fam_b": 2})
            self.assertEqual(len(set(ids)), 4)
            # manifest records seed, prng, exclusions
            self.assertEqual(doc["seed"], 20260928)
            self.assertIn("random.Random", doc["prng"])
            self.assertEqual(doc["excluded_ids"], sorted(excluded))
            self.assertEqual(doc["n"], 4)

    def test_missing_exclusions_file_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = _make_cases_dir(root)
            with self.assertRaises(SystemExit):
                s1_sample.main(["--seed", "20260928", "--per-family", "2",
                                "--exclude", str(root / "nope.json"),
                                "--cases", str(cases),
                                "--out", str(root / "s.json")])

    def test_empty_exclusions_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = _make_cases_dir(root)
            excl = _exclusions(root, [])
            with self.assertRaises(SystemExit):
                s1_sample.main(["--seed", "20260928", "--per-family", "2",
                                "--exclude", str(excl),
                                "--cases", str(cases),
                                "--out", str(root / "s.json")])

    def test_frame_too_small_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = _make_cases_dir(root, n=3)
            excl = _exclusions(root, ["v1-fam_a-001"])
            with self.assertRaises(SystemExit):
                s1_sample.main(["--seed", "20260928", "--per-family", "3",
                                "--exclude", str(excl),
                                "--cases", str(cases),
                                "--out", str(root / "s.json")])

    def test_timestamp_override_recorded(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            cases = _make_cases_dir(root)
            excl = _exclusions(root, ["v1-fam_a-001"])
            out = root / "s.json"
            s1_sample.main(["--seed", "20260928", "--per-family", "2",
                            "--exclude", str(excl), "--cases", str(cases),
                            "--out", str(out),
                            "--timestamp", "2030-01-01T00:00:00+00:00"])
            doc = json.loads(out.read_text())
            self.assertEqual(doc["drawn_utc"], "2030-01-01T00:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
