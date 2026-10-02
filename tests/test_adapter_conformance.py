"""Tests for peira.adapters.conformance (P-4 conformance kit).

Drives the fake third-party distribution from
``tests/adapter_test_plugin.py`` through ``run_check``: the real
entry-point -> shim-child -> protocol path for every fixture.
"""

import asyncio
import json
import os
import tempfile
import unittest

from tests.adapter_test_plugin import PluginInstallMixin
from peira.adapters import conformance
from peira.adapters.conformance import (
    AdapterCheckError,
    run_check,
    verify_report,
    write_report,
)


def _suite(report, name):
    return next(s for s in report.suites if s.name == name)


def _check(report, suite_name, check_name):
    suite = _suite(report, suite_name)
    return next(c for c in suite.checks if c.name == check_name)


class ConformanceKitTest(PluginInstallMixin, unittest.TestCase):
    def _run(self, coro):
        return asyncio.run(coro)

    def test_good_adapter_passes(self):
        report = self._run(run_check("testplugin-conf-good"))
        self.assertEqual(report.verdict, "pass")
        self.assertEqual(report.transport, "subprocess")
        self.assertEqual(report.adapter_trust, "third-party")
        for suite in report.suites:
            self.assertTrue(suite.passed, f"suite {suite.name} failed")
        self.assertTrue(report.module_sha256)
        self.assertTrue(report.module_path)
        self.assertEqual(report.attestations.get("retry_posture"), True)
        self.assertEqual(report.attestation_failures, [])
        # 6.3 observations: observed, not declared.
        self.assertEqual(
            report.observations.primitives_observed.get("choice"), True)

    def test_nondeterministic_fails_determinism(self):
        report = self._run(run_check("testplugin-conf-nondeterministic"))
        self.assertEqual(report.verdict, "fail")
        self.assertFalse(_suite(report, "determinism").passed)

    def test_smuggler_fails_no_identifier_smuggling(self):
        report = self._run(run_check("testplugin-conf-smuggler"))
        self.assertEqual(report.verdict, "fail")
        check = _check(report, "metadata_invariance",
                       "no_identifier_smuggling")
        self.assertFalse(check.passed)

    def test_missing_attestation_fails(self):
        report = self._run(run_check("testplugin-conf-noattest"))
        self.assertEqual(report.verdict, "fail")
        self.assertTrue(
            any("retry_posture" in f
                for f in report.attestation_failures))

    def test_metaleak_fails_call_id_invariance(self):
        report = self._run(run_check("testplugin-conf-metaleak"))
        self.assertEqual(report.verdict, "fail")
        check = _check(report, "metadata_invariance",
                       "call_id_invariance")
        self.assertFalse(check.passed)

    def test_junk_sniffer_fails(self):
        report = self._run(run_check("testplugin-conf-junk-sniffer"))
        self.assertEqual(report.verdict, "fail")
        check = _check(report, "metadata_invariance", "junk_keys_ignored")
        self.assertFalse(check.passed)

    def test_declared_sampler_passes(self):
        report = self._run(run_check("testplugin-conf-sampler"))
        self.assertEqual(report.verdict, "pass")
        self.assertTrue(_suite(report, "determinism").passed)
        self.assertEqual(
            report.observations.sampling_posture_declared, "sampling")

    def test_steady_sampler_warns_but_passes(self):
        report = self._run(run_check("testplugin-conf-sampler-steady"))
        self.assertEqual(report.verdict, "pass")
        suite = _suite(report, "determinism")
        self.assertTrue(suite.passed)
        self.assertTrue(suite.warnings)

    def test_dotted_path_refused(self):
        with self.assertRaises(AdapterCheckError) as ctx:
            self._run(run_check("some.dotted.path"))
        self.assertIn("registry id", str(ctx.exception))

    def test_unknown_id_fails_closed(self):
        with self.assertRaises(Exception):
            self._run(run_check("no-such-adapter-xyz"))

    def test_verify_roundtrip(self):
        report = self._run(run_check("testplugin-conf-good"))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "check.json")
            write_report(report, path)
            ok, message = verify_report(path)
            self.assertTrue(ok, message)
            self.assertIn("verified", message)

    def test_verify_detects_tampering(self):
        report = self._run(run_check("testplugin-conf-good"))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "check.json")
            write_report(report, path)
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data["module_sha256"] = "0" * 64
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f)
            ok, message = verify_report(path)
            self.assertFalse(ok)
            self.assertIn("mismatch", message)

    def test_verify_rejects_garbage(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "check.json")
            with open(path, "w", encoding="utf-8") as f:
                f.write("not json")
            ok, _ = verify_report(path)
            self.assertFalse(ok)

    def test_advisory_scan_reports_but_never_fails(self):
        # The good adapter's module imports os/time: the scan may
        # flag nothing or only informational lines; either way the
        # verdict is unaffected by findings.
        report = self._run(run_check("testplugin-conf-good"))
        self.assertIsInstance(report.advisory_findings, list)
        self.assertEqual(report.verdict, "pass")


class InProcessDriverTest(unittest.TestCase):
    def test_inprocess_driver_decide_and_attestations(self):
        from types import SimpleNamespace

        from peira.adapters.base import CallContext, ChoiceOutput
        from peira.adapters.conformance import _InProcessDriver

        adapter = SimpleNamespace(
            name="stub",
            version="1",
            supported_primitives=frozenset({"choice"}),
            confidence_source="none",
            conformance_attestations={"retry_posture": "single-attempt"},
            decide=lambda ci, prim, ctx: ChoiceOutput(decision="approve"),
        )
        driver = _InProcessDriver(adapter, "d", "1", "/tmp/x.py", "abc")
        out = asyncio.run(
            driver.decide({"t": "x"}, "choice", CallContext(call_id="c")))
        self.assertEqual(out.decision, "approve")
        self.assertEqual(
            driver.attestations["retry_posture"], "single-attempt")
        asyncio.run(driver.close())

    def test_retry_posture_gate(self):
        from peira.adapters.conformance import _check_retry_posture

        # Third-party: True passes, description passes, missing fails.
        _, failures = _check_retry_posture({"retry_posture": True},
                                           "third-party")
        self.assertEqual(failures, [])
        _, failures = _check_retry_posture(
            {"retry_posture": "provider SDK retries twice with backoff"},
            "third-party")
        self.assertEqual(failures, [])
        _, failures = _check_retry_posture({}, "third-party")
        self.assertTrue(failures)
        _, failures = _check_retry_posture({"retry_posture": False},
                                           "third-party")
        self.assertTrue(failures)
        # First-party: not gated.
        _, failures = _check_retry_posture({}, "first-party")
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
