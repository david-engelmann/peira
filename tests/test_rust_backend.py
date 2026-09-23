"""Backend parity: the Rust accelerator must be indistinguishable from the
pure-Python reference (run with: python -m unittest discover tests).

These tests pass whether or not `peira._core` is built: they compare the
public dispatched functions against the `_xxx_py` reference
implementations. A CI job builds the extension and re-runs the suite so
the Rust paths are covered as well.
"""

import json
import os
import random
import subprocess
import sys
import unittest
from pathlib import Path

import peira
from peira import _rust
from peira.metrics import (
    PerCaseResult,
    asr_conditional,
    benign_accuracy,
    brier_score,
    check_eligibility,
    ece,
    malformed_rate,
    mcnemar,
    n_eligible_by_family,
    paired_bootstrap_ci,
    targeted_attack_success,
    wilson_ci,
    _asr_conditional_py,
    _benign_accuracy_py,
    _brier_score_py,
    _check_eligibility_py,
    _ece_py,
    _malformed_rate_py,
    _mcnemar_py,
    _n_eligible_by_family_py,
    _targeted_attack_success_py,
    _wilson_ci_py,
)
from peira.schema import _validate_case_dict_py, validate_case_dict

REPO_ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ["state_poisoning", "criteria_smuggling", "option_order", "literal_reading"]


def _corpus(n=300, seed=7):
    rng = random.Random(seed)
    return [
        PerCaseResult(
            case_id=f"c{i}",
            family=rng.choice(FAMILIES),
            primitive=rng.choice(["choice", "score", "noul"]),
            benign_correct=rng.random() < 0.75,
            attacked_flipped=rng.random() < 0.35,
            attacked_targeted=rng.random() < 0.12,
            malformed=rng.random() < 0.03,
            confidence=(rng.random() if rng.random() < 0.6 else None),
            benign_malformed=rng.random() < 0.03,
            has_target=rng.random() < 0.5,
        )
        for i in range(n)
    ]


def _valid_case(**over):
    d = {
        "case_id": "c1",
        "family": "state_poisoning",
        "primitive": "choice",
        "severity": "high",
        "benign": {"input": {"q": "x"}, "expected_decision": "a"},
        "attacked": {"input": {"q": "x!"}, "target_decision": "b"},
        "notes": "héllo",
    }
    d.update(over)
    return d


class TestMetricsParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = _corpus()
        cls.rng = random.Random(11)
        cls.probs = [cls.rng.random() for _ in range(200)]
        cls.labels = [cls.rng.randrange(2) for _ in range(200)]

    def test_asr_conditional(self):
        self.assertEqual(asr_conditional(self.results),
                         _asr_conditional_py(self.results))

    def test_benign_accuracy(self):
        self.assertEqual(benign_accuracy(self.results),
                         _benign_accuracy_py(self.results))

    def test_targeted_attack_success(self):
        self.assertEqual(targeted_attack_success(self.results),
                         _targeted_attack_success_py(self.results))

    def test_targeted_attack_success_none(self):
        # No case names a target: rate is None, not zero.
        rs = _corpus(seed=9)
        rs = [r for r in rs if not r.has_target] or rs[:0]
        self.assertEqual(targeted_attack_success(rs), (None, 0))

    def test_malformed_rate(self):
        self.assertEqual(malformed_rate(self.results),
                         _malformed_rate_py(self.results))

    def test_wilson_ci(self):
        self.assertEqual(wilson_ci(7, 10), _wilson_ci_py(7, 10))
        self.assertEqual(wilson_ci(0, 0), _wilson_ci_py(0, 0))

    def test_wilson_ci_custom_z_stays_python(self):
        # The Rust core hardcodes z = 1.96; a custom z must use the
        # reference implementation even when the extension is installed.
        self.assertEqual(wilson_ci(7, 10, z=2.0), _wilson_ci_py(7, 10, z=2.0))

    def test_ece(self):
        self.assertAlmostEqual(ece(self.probs, self.labels),
                               _ece_py(self.probs, self.labels))

    def test_brier_score(self):
        # ~1 ulp: the reference uses Python's compensated builtin sum().
        self.assertAlmostEqual(brier_score(self.probs, self.labels),
                               _brier_score_py(self.probs, self.labels))

    def test_mcnemar(self):
        self.assertEqual(mcnemar(13, 5), _mcnemar_py(13, 5))
        self.assertEqual(mcnemar(0, 0), _mcnemar_py(0, 0))

    def test_n_eligible_by_family(self):
        got = n_eligible_by_family(self.results, FAMILIES)
        want = _n_eligible_by_family_py(self.results, FAMILIES)
        self.assertEqual(got, want)
        self.assertEqual(list(got), list(want))  # insertion order too

    def test_n_eligible_by_family_no_required(self):
        got = n_eligible_by_family(self.results)
        want = _n_eligible_by_family_py(self.results)
        self.assertEqual(got, want)
        self.assertEqual(list(got), list(want))

    def test_check_eligibility(self):
        self.assertEqual(check_eligibility(self.results, FAMILIES),
                         _check_eligibility_py(self.results, FAMILIES))

    def test_check_eligibility_empty(self):
        self.assertEqual(check_eligibility([], FAMILIES),
                         _check_eligibility_py([], FAMILIES))

    def test_bootstrap_never_dispatches(self):
        # paired_bootstrap_ci always uses the Python PRNG (Mersenne Twister),
        # even with the extension installed: pin it to an independent
        # reimplementation of the reference algorithm.
        xs = [0.1, 0.4, 0.35, 0.8, 0.55, 0.9]
        ys = [0.2, 0.3, 0.5, 0.7, 0.6, 0.85]
        rng = random.Random(3)
        n = len(xs)
        diffs = []
        for _ in range(2000):
            idx = [rng.randrange(n) for _ in range(n)]
            diffs.append(sum(xs[i] for i in idx) / n
                         - sum(ys[i] for i in idx) / n)
        diffs.sort()
        want = (diffs[int(0.025 * 2000)], diffs[int(0.975 * 2000)])
        self.assertEqual(paired_bootstrap_ci(xs, ys, seed=3), want)


class TestValidateParity(unittest.TestCase):
    CASES = [
        _valid_case(),
        {"case_id": "x"},  # missing keys
        _valid_case(primitive="nope"),
        _valid_case(severity="nope"),
        _valid_case(benign={"input": {}}),  # missing expected_decision
        _valid_case(attacked="not-a-dict"),
        _valid_case(extra="ignored", nested={"a": [1, 2.5, None, True]}),
        _valid_case(benign={"input": {"n": 2**63},  # big but valid u64
                            "expected_decision": "a"}),
        # Declared JSON types are enforced (P1-2): each of these used to
        # pass validation and crash or mis-score downstream.
        _valid_case(case_id=42),
        _valid_case(family=["x"]),
        _valid_case(primitive=5),
        _valid_case(severity=None),
        _valid_case(benign={"input": "oops", "expected_decision": "a"}),
        _valid_case(benign={"input": {}, "expected_decision": 42}),
        _valid_case(benign=5),  # not a dict at all
        _valid_case(attacked={"input": {}, "target_decision": 5}),
        _valid_case(notes=5),
        5,  # scalar top-level: all six keys "missing", not a crash
        [1, 2],  # list top-level: same
    ]

    def test_parity(self):
        for d in self.CASES:
            with self.subTest(d=d):
                self.assertEqual(validate_case_dict(d),
                                 _validate_case_dict_py(d))

    def test_type_error_strings_pinned(self):
        # The exact strings are the cross-backend contract: the Rust
        # core must emit them byte-identically.
        expect = [
            ({"case_id": 42}, ["bad case_id: expected string"]),
            ({"family": ["x"]}, ["bad family: expected string"]),
            ({"primitive": 5}, ["bad primitive: expected string"]),
            ({"severity": None}, ["bad severity: expected string"]),
            ({"benign": {"input": "oops", "expected_decision": "a"}},
             ["bad benign input: expected object"]),
            ({"benign": {"input": {}, "expected_decision": 42}},
             ["bad benign expected_decision: expected string"]),
            ({"benign": 5},
             ["bad variant 'benign': need an object with 'input'"]),
            ({"attacked": {"input": {}, "target_decision": 5}},
             ["bad attacked target_decision: expected string or null"]),
            ({"notes": 5}, ["bad notes: expected string"]),
        ]
        for over, want in expect:
            with self.subTest(over=over):
                d = _valid_case(**over)
                self.assertEqual(validate_case_dict(d), want)
                self.assertEqual(_validate_case_dict_py(d), want)

    def test_unrepresentable_falls_back(self):
        # Values with no JSON representation cannot cross into Rust; the
        # wrapper must fall back to the reference instead of raising.
        for d in [
            dict(self.CASES[0], notes=float("nan")),
            dict(self.CASES[0], notes=float("inf")),
            {"case_id": "x", "big": 10**30},
            {1: "non-string key", "case_id": "x"},
            {"case_id": "x", "bad": object()},
        ]:
            with self.subTest(d=str(d)[:40]):
                self.assertEqual(validate_case_dict(d),
                                 _validate_case_dict_py(d))


@unittest.skipUnless(_rust.RUST_AVAILABLE, "peira._core not built")
class TestRustExtension(unittest.TestCase):
    def test_version_matches_package(self):
        from peira import _core
        self.assertEqual(_core.version(), peira.__version__)

    def test_canonical_json_matches_dumps(self):
        from peira import _core
        d = {"b": [1, 2.5, None, True, {"x": "héllo ✓"}],
             "a": {"z": 1e-7, "neg": -0.0}}
        self.assertEqual(_core.canonical_json(d),
                         json.dumps(d, sort_keys=True))

    def test_canonical_pretty_matches_dumps(self):
        from peira import _core
        d = {"b": [1, None], "a": "x"}
        self.assertEqual(_core.canonical_pretty(d),
                         json.dumps(d, indent=2, sort_keys=True))


class TestNoRustFallback(unittest.TestCase):
    """PEIRA_NO_RUST=1 forces the pure-Python backend (subprocess)."""

    def _run(self, code, env_extra=None):
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join([
            str(REPO_ROOT / "python"),
            str(REPO_ROOT),
            env.get("PYTHONPATH", ""),
        ])
        env.update(env_extra or {})
        return subprocess.run([sys.executable, "-c", code],
                              capture_output=True, text=True, env=env)

    def test_flag_disables_rust(self):
        r = self._run(
            "from peira._rust import RUST_AVAILABLE, _impl\n"
            "assert RUST_AVAILABLE is False, RUST_AVAILABLE\n"
            "assert _impl is None\n"
            "import peira.metrics as m\n"
            "assert m._rust is None\n"
            "print('ok')",
            {"PEIRA_NO_RUST": "1"},
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("ok", r.stdout)

    def test_summarize_backend_parity(self):
        # runner.summarize must produce identical output under both backends.
        code = (
            "import json, random; "
            "from peira.runner import summarize; "
            "from tests.test_rust_backend import _corpus; "
            "print(json.dumps(summarize(_corpus()), sort_keys=True))"
        )
        a = self._run(code)
        b = self._run(code, {"PEIRA_NO_RUST": "1"})
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertEqual(b.returncode, 0, b.stderr)
        self.assertEqual(a.stdout, b.stdout)


if __name__ == "__main__":
    unittest.main()
