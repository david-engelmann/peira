"""Unit tests for dataset manifest tooling (run with: python -m unittest discover tests)."""

import json
import tempfile
import unittest
from pathlib import Path

from peira.dataset import (
    MANIFEST_NAME,
    build_manifest,
    read_manifest,
    sha256_file,
    verify_manifest,
    verify_manifest_sealed,
    write_manifest,
)


def _case(case_id, family="state_poisoning", severity="high",
          primitive="choice"):
    return {
        "case_id": case_id,
        "family": family,
        "primitive": primitive,
        "severity": severity,
        "benign": {"input": {"prompt": "p", "options": ["a", "b"]},
                   "expected_decision": "a"},
        "attacked": {"input": {"prompt": "p!", "options": ["a", "b"]},
                     "target_decision": "b"},
        "notes": "",
    }


class TestDatasetManifest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_cases(self, name="cases.jsonl", cases=None):
        cases = cases if cases is not None else [
            _case("c1"), _case("c2", family="indirection")]
        path = self.dir / name
        path.write_text("\n".join(json.dumps(c) for c in cases) + "\n")
        return path

    def test_build_manifest_counts(self):
        self._write_cases()
        (self.dir / "CANARY.txt").write_text("peira-canary:test\n")
        m = build_manifest(self.dir, "1.0.0")
        self.assertEqual(m["dataset"], "peira-v1")
        self.assertEqual(m["dataset_version"], "1.0.0")
        entry = m["files"]["cases.jsonl"]
        self.assertEqual(entry["kind"], "cases")
        self.assertEqual(entry["n_cases"], 2)
        self.assertEqual(entry["n_by_family"],
                         {"indirection": 1, "state_poisoning": 1})
        self.assertEqual(entry["n_by_severity"], {"high": 2})
        self.assertEqual(entry["n_by_primitive"], {"choice": 2})
        self.assertEqual(len(entry["sha256"]), 64)
        self.assertEqual(m["files"]["CANARY.txt"]["kind"], "artifact")
        self.assertNotIn(MANIFEST_NAME, m["files"])

    def test_write_and_verify_ok(self):
        self._write_cases()
        out = write_manifest(self.dir, build_manifest(self.dir, "1.0.0"))
        self.assertEqual(out.name, MANIFEST_NAME)
        self.assertEqual(verify_manifest(self.dir), [])
        # manifest is deterministic apart from the timestamp
        m1 = json.loads(out.read_text())
        m2 = build_manifest(self.dir, "1.0.0")
        self.assertEqual(m1["files"], m2["files"])

    def test_verify_detects_tamper(self):
        path = self._write_cases()
        write_manifest(self.dir, build_manifest(self.dir, "1.0.0"))
        path.write_text(path.read_text().replace('"p!"', '"p?"'))
        errors = verify_manifest(self.dir)
        self.assertTrue(any("sha256 mismatch" in e for e in errors),
                        errors)

    def test_verify_detects_missing_file(self):
        path = self._write_cases()
        write_manifest(self.dir, build_manifest(self.dir, "1.0.0"))
        path.unlink()
        errors = verify_manifest(self.dir)
        self.assertTrue(any("missing on disk" in e for e in errors), errors)

    def test_build_rejects_invalid_case(self):
        bad = _case("c1")
        del bad["severity"]
        self._write_cases(cases=[bad])
        with self.assertRaises(ValueError) as ctx:
            build_manifest(self.dir, "1.0.0")
        self.assertIn("cases.jsonl:1", str(ctx.exception))

    def test_build_rejects_bad_json(self):
        path = self._write_cases()
        path.write_text(path.read_text() + "{not json}\n")
        with self.assertRaises(ValueError):
            build_manifest(self.dir, "1.0.0")

    def test_verify_missing_manifest(self):
        self._write_cases()
        with self.assertRaises(FileNotFoundError):
            read_manifest(self.dir)

    def test_build_missing_dir(self):
        with self.assertRaises(FileNotFoundError):
            build_manifest(self.dir / "nope", "1.0.0")


class TestManifestTrustBoundary(unittest.TestCase):
    """Path traversal and single-read verification (H6)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_manifest(self, files):
        write_manifest(self.dir, {"files": files})

    def test_dotdot_entry_is_reported_not_followed(self):
        # A manifest entry for ../outside.jsonl must not hash a file
        # outside the dataset root — it is reported, not followed.
        outside = self.dir.parent / "outside.jsonl"
        outside.write_text("trap\n")
        try:
            self._write_manifest(
                {"../outside.jsonl": {"kind": "cases", "sha256": "0" * 64}})
            errors = verify_manifest(self.dir)
            self.assertEqual(len(errors), 1, errors)
            self.assertIn("unsafe file name in manifest", errors[0])
        finally:
            outside.unlink(missing_ok=True)

    def test_separators_and_absolute_paths_rejected(self):
        for evil in ["sub/dir.jsonl", "back\\slash.jsonl", "/abs.jsonl",
                     "a..b.jsonl", ""]:
            with self.subTest(evil=evil):
                self._write_manifest(
                    {evil: {"kind": "cases", "sha256": "0" * 64}})
                errors = verify_manifest(self.dir)
                self.assertTrue(
                    any("unsafe file name in manifest" in e for e in errors),
                    (evil, errors))

    def test_sealed_verify_returns_digest_of_verified_bytes(self):
        # verify_manifest_sealed returns the parsed manifest and the
        # digest of the same bytes it verified: callers seal that digest
        # into the analysis lock with no re-read in between.
        cases = self.dir / "cases.jsonl"
        cases.write_text(
            json.dumps(_case("c1")) + "\n")
        write_manifest(self.dir, build_manifest(self.dir, "1.0.0"))
        manifest, digest, errors = verify_manifest_sealed(self.dir)
        self.assertEqual(errors, [])
        self.assertEqual(digest, sha256_file(self.dir / MANIFEST_NAME))
        self.assertEqual(manifest["dataset_version"], "1.0.0")

    def test_minimal_manifest_accepted(self):
        # read_manifest only requires the `files` section, like Python.
        (self.dir / MANIFEST_NAME).write_text('{"files": {}}')
        self.assertEqual(read_manifest(self.dir), {"files": {}})

    def test_modified_file_reports_mismatch_not_parse_error(self):
        # Hash-before-parse from the same bytes: a modified file reports a
        # digest mismatch and is never parsed, so garbage bytes that could
        # not parse still surface as exactly one mismatch error.
        cases = self.dir / "cases.jsonl"
        cases.write_text(json.dumps(_case("c1")) + "\n")
        write_manifest(self.dir, build_manifest(self.dir, "1.0.0"))
        cases.write_bytes(b"\x00\x01not json at all\xff\n")
        errors = verify_manifest(self.dir)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("sha256 mismatch", errors[0])
        self.assertNotIn("invalid JSON", errors[0])

    def test_entry_without_sha256_is_mismatch_not_crash(self):
        # A hand-written entry missing `sha256` (Python tolerates it)
        # reports a mismatch — it never crashes and never parses first.
        cases = self.dir / "cases.jsonl"
        cases.write_text(json.dumps(_case("c1")) + "\n")
        self._write_manifest({"cases.jsonl": {"kind": "cases"}})
        errors = verify_manifest(self.dir)
        self.assertEqual(len(errors), 1, errors)
        self.assertIn("sha256 mismatch", errors[0])

    def test_verify_reads_each_file_exactly_once(self):
        # Single-read contract: verifying one case file performs exactly
        # two reads total (the manifest, then the case file) — the digest
        # and the parse share the case file's bytes.
        from unittest import mock

        cases = self.dir / "cases.jsonl"
        cases.write_text(json.dumps(_case("c1")) + "\n")
        write_manifest(self.dir, build_manifest(self.dir, "1.0.0"))
        real_read_bytes = Path.read_bytes
        reads: list[str] = []

        def counting(self):
            reads.append(self.name)
            return real_read_bytes(self)

        with mock.patch.object(Path, "read_bytes", autospec=True,
                               side_effect=counting):
            errors = verify_manifest(self.dir)
        self.assertEqual(errors, [])
        self.assertEqual(sorted(reads), ["cases.jsonl", "manifest.json"])

    def test_empty_dir_builds(self):
        m = build_manifest(self.dir, "0.0.0")
        self.assertEqual(m["files"], {})


class TestBuildManifestSeal(unittest.TestCase):
    """The release seal in `peira dataset build-manifest`: semver
    versions, severity notes on critical cases, and no silent
    same-version rewrites."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_cases(self, cases):
        path = self.dir / "cases.jsonl"
        path.write_text("\n".join(json.dumps(c) for c in cases) + "\n")
        return path

    def _args(self, version="1.0.0", require_reviews=False):
        import argparse
        return argparse.Namespace(dir=str(self.dir), version=version,
                                  name="peira-v1",
                                  require_reviews=require_reviews)

    def _build(self, **kw):
        import contextlib
        import io
        from peira.cli import cmd_dataset_build_manifest
        with contextlib.redirect_stderr(io.StringIO()):
            return cmd_dataset_build_manifest(self._args(**kw))

    def test_rejects_non_semver_version(self):
        self._write_cases([_case("c1")])
        for bad in ("v1", "1.0", "1.0.0.0", "latest", ""):
            self.assertEqual(self._build(version=bad), 1, bad)
        self.assertFalse((self.dir / MANIFEST_NAME).exists())

    def test_accepts_prerelease_semver(self):
        self._write_cases([_case("c1")])
        self.assertEqual(self._build(version="0.1.0-trial"), 0)

    def test_refuses_critical_without_notes(self):
        self._write_cases([_case("c1", severity="critical")])
        self.assertEqual(self._build(), 1)
        self.assertFalse((self.dir / MANIFEST_NAME).exists())

    def test_allows_critical_with_notes(self):
        case = _case("c1", severity="critical")
        case["notes"] = "wire transfer is irreversible"
        self._write_cases([case])
        self.assertEqual(self._build(), 0)

    def test_refuses_same_version_content_change(self):
        path = self._write_cases([_case("c1")])
        self.assertEqual(self._build(version="1.0.0"), 0)
        sealed = (self.dir / MANIFEST_NAME).read_bytes()
        path.write_text(path.read_text().replace('"p!"', '"p?"'))
        self.assertEqual(self._build(version="1.0.0"), 1)
        # the sealed manifest is untouched by the refused rebuild
        self.assertEqual((self.dir / MANIFEST_NAME).read_bytes(), sealed)
        self.assertEqual(read_manifest(self.dir)["dataset_version"], "1.0.0")

    def test_allows_idempotent_rebuild(self):
        self._write_cases([_case("c1")])
        self.assertEqual(self._build(version="1.0.0"), 0)
        self.assertEqual(self._build(version="1.0.0"), 0)
        self.assertEqual(verify_manifest(self.dir), [])

    def test_allows_new_version_after_change(self):
        path = self._write_cases([_case("c1")])
        self.assertEqual(self._build(version="1.0.0"), 0)
        path.write_text(path.read_text().replace('"p!"', '"p?"'))
        self.assertEqual(self._build(version="1.1.0"), 0)
        self.assertEqual(verify_manifest(self.dir), [])

    def test_dataset_new_prints_severity_hint(self):
        import argparse
        import contextlib
        import io
        from peira.cli import cmd_dataset_new
        from peira.templates import template_help
        args = argparse.Namespace(family="state_poisoning", id="sp-042",
                                  severity="high", primitive=None, out=None)
        err = io.StringIO()
        with contextlib.redirect_stderr(err), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cmd_dataset_new(args), 0)
        hint = template_help("state_poisoning")["severity_hint"]
        self.assertIn(hint, err.getvalue())


class TestDatasetStatus(unittest.TestCase):
    """`peira dataset status`: one view of the authoring pipeline."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_cases(self, cases):
        path = self.dir / "cases.jsonl"
        path.write_text("\n".join(json.dumps(c) for c in cases) + "\n")
        return path

    def _status(self, dir=None):
        import argparse
        import contextlib
        import io
        from peira.cli import cmd_dataset_status
        args = argparse.Namespace(dir=str(dir or self.dir))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(io.StringIO()):
            rc = cmd_dataset_status(args)
        return rc, out.getvalue()

    def test_trial_suite_is_release_ready(self):
        trial = Path(__file__).resolve().parents[1] / "dataset" / "trial"
        rc, out = self._status(trial)
        self.assertEqual(rc, 0)
        self.assertIn("status: release-ready", out)
        self.assertIn("gates: 8/8 passed", out)
        self.assertIn("manifest: current", out)

    def test_empty_dir_is_not_release_ready(self):
        rc, out = self._status()
        self.assertEqual(rc, 1)
        self.assertIn("manifest: absent", out)
        self.assertIn("status: not release-ready", out)

    def test_gate_errors_block_release(self):
        self._write_cases([_case("c1"), _case("c1")])  # duplicate id: G3
        rc, out = self._status()
        self.assertEqual(rc, 1)
        self.assertIn("FAIL", out)
        self.assertIn("status: not release-ready", out)

    def test_pending_reviews_block_release(self):
        self._write_cases([_case("c1", severity="critical")])
        rc, out = self._status()
        self.assertEqual(rc, 1)
        self.assertIn("1 pending", out)
        self.assertIn("status: not release-ready", out)

    def test_stale_manifest_blocks_release(self):
        from peira.cli import cmd_dataset_build_manifest
        import argparse
        import contextlib
        import io
        path = self._write_cases([_case("c1")])
        args = argparse.Namespace(dir=str(self.dir), version="1.0.0",
                                  name="peira-v1", require_reviews=False)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cmd_dataset_build_manifest(args), 0)
        rc, out = self._status()
        self.assertEqual(rc, 0)
        path.write_text(path.read_text().replace('"p!"', '"p?"'))
        rc, out = self._status()
        self.assertEqual(rc, 1)
        self.assertIn("manifest: STALE", out)

    def test_missing_dir_is_user_error(self):
        rc, out = self._status(self.dir / "nope")
        self.assertEqual(rc, 1)


class TestIterCases(unittest.TestCase):
    """The shared case-file walk: one loop, fail-fast with file:line."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, name, text):
        (self.dir / name).write_text(text, encoding="utf-8")

    def test_yields_path_lineno_and_case(self):
        from peira.dataset import iter_cases
        self._write("b.jsonl", json.dumps(_case("c2")) + "\n")
        self._write("a.jsonl",
                    "\n" + json.dumps(_case("c1")) + "\n"
                    + json.dumps(_case("c3")) + "\n")
        got = [(p.name, n, c["case_id"]) for p, n, c in iter_cases(self.dir)]
        # Files in sorted order; blank lines skipped; line numbers are
        # the file's own (the leading blank is line 1).
        self.assertEqual(got, [("a.jsonl", 2, "c1"), ("a.jsonl", 3, "c3"),
                               ("b.jsonl", 1, "c2")])

    def test_invalid_json_raises_with_file_and_line(self):
        from peira.dataset import iter_cases
        self._write("cases.jsonl",
                    json.dumps(_case("c1")) + "\n{bad json}\n")
        with self.assertRaises(ValueError) as ctx:
            list(iter_cases(self.dir))
        self.assertIn("cases.jsonl:2: invalid JSON", str(ctx.exception))

    def test_schema_violation_raises_with_file_and_line(self):
        from peira.dataset import iter_cases
        bad = _case("c1")
        del bad["severity"]
        self._write("cases.jsonl", json.dumps(bad) + "\n")
        with self.assertRaises(ValueError) as ctx:
            list(iter_cases(self.dir))
        self.assertIn("cases.jsonl:1:", str(ctx.exception))


class TestAtomicWriteText(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_and_overwrite(self):
        from peira.dataset import atomic_write_text
        target = self.dir / "out.txt"
        atomic_write_text(target, "one")
        self.assertEqual(target.read_text(encoding="utf-8"), "one")
        atomic_write_text(target, "two")
        self.assertEqual(target.read_text(encoding="utf-8"), "two")
        # No temp files left behind.
        self.assertEqual([p.name for p in self.dir.iterdir()], ["out.txt"])

    def test_missing_parent_dir_fails_clean(self):
        from peira.dataset import atomic_write_text
        with self.assertRaises(OSError):
            atomic_write_text(self.dir / "nope" / "out.txt", "x")
        self.assertFalse((self.dir / "nope").exists())


class TestDatasetCIChecks(unittest.TestCase):
    """The dataset-checks CI job (gates + manifest verification) must stay
    green on the committed Trial suite — the same checks the job
    runs on every push."""

    TRIAL_DIR = str(Path(__file__).resolve().parents[1] / "dataset" / "trial")

    def test_trial_passes_gates_and_manifest_verify(self):
        import argparse
        from peira.cli import cmd_dataset_gates, cmd_dataset_verify_manifest

        gates_args = argparse.Namespace(dir=self.TRIAL_DIR)
        self.assertEqual(cmd_dataset_gates(gates_args), 0)
        verify_args = argparse.Namespace(dir=self.TRIAL_DIR)
        self.assertEqual(cmd_dataset_verify_manifest(verify_args), 0)


if __name__ == "__main__":
    unittest.main()
