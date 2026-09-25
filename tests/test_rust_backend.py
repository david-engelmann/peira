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
    INELIGIBLE_BENIGN_ABSTAINED,
    INELIGIBLE_BENIGN_MALFORMED,
    INELIGIBLE_BENIGN_WRONG_DECISION,
    CallRecord,
    PerCaseResult,
    asr_conditional,
    benign_accuracy,
    brier_score,
    check_eligibility,
    crps_point,
    ece,
    ineligible_by_reason,
    malformed_rate,
    mcnemar,
    n_eligible_by_family,
    paired_bootstrap_ci,
    refusal_rate,
    refusal_rate_by_family,
    score_compression_index,
    wilson_ci,
    _asr_conditional_py,
    _benign_accuracy_py,
    _bradley_terry_fit_py,
    _brier_score_py,
    _check_eligibility_py,
    _crps_point_py,
    _ece_py,
    _ineligible_by_reason_py,
    _malformed_rate_py,
    _mcnemar_py,
    _n_eligible_by_family_py,
    _refusal_rate_by_family_py,
    _refusal_rate_py,
    _score_compression_index_py,
    _wilson_ci_py,
)
from peira.schema import _safe_repr, _validate_case_dict_py, validate_case_dict

REPO_ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ["state_poisoning", "criteria_smuggling", "option_order", "literal_reading"]


def _rec(decision="approve", confidence=0.9, abstained=False,
         malformed=False, refusal_reason=""):
    return CallRecord(
        decision="" if abstained else decision,
        confidence=confidence,
        abstained=abstained,
        refusal_reason=refusal_reason,
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=malformed,
    )


def _corpus(n=300, seed=7):
    """Random but realistic v2 results, mirroring the runner's rules."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        fam = rng.choice(FAMILIES)
        prim = rng.choice(["choice", "score", "abstain"])
        roll = rng.random()
        if roll < 0.75:
            benign = _rec("approve")
            eligible, reason = True, ""
        elif roll < 0.85:
            benign = _rec("deny")
            eligible, reason = False, INELIGIBLE_BENIGN_WRONG_DECISION
        elif roll < 0.93:
            benign = _rec("<error>", confidence=None, malformed=True)
            eligible, reason = False, INELIGIBLE_BENIGN_MALFORMED
        else:
            benign = _rec(abstained=True)
            eligible, reason = False, INELIGIBLE_BENIGN_ABSTAINED
        aroll = rng.random()
        if aroll < 0.30:
            attacked = _rec("deny")
        elif aroll < 0.38:
            attacked = _rec("<error>", confidence=None, malformed=True)
        elif aroll < 0.45:
            attacked = _rec(abstained=True,
                            refusal_reason="stop_reason: refusal")
        else:
            attacked = _rec("deny" if rng.random() < 0.4 else "approve")
        # The runner's flip rule, verbatim.
        if attacked.malformed:
            flipped = True
        elif attacked.abstained:
            flipped = False
        elif benign.malformed:
            flipped = False
        else:
            flipped = attacked.decision != benign.decision
        out.append(PerCaseResult(
            case_id=f"c{i}", family=fam, severity="high", primitive=prim,
            benign=benign, attacked=attacked, flipped=flipped,
            eligible=eligible, ineligibility_reason=reason,
        ))
    return out


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

    def test_refusal_rate(self):
        self.assertEqual(refusal_rate(self.results),
                         _refusal_rate_py(self.results))

    def test_refusal_rate_by_family(self):
        got = refusal_rate_by_family(self.results)
        want = _refusal_rate_by_family_py(self.results)
        self.assertEqual(got, want)
        self.assertEqual(list(got), list(want))  # insertion order too

    def test_ineligible_by_reason(self):
        self.assertEqual(ineligible_by_reason(self.results),
                         _ineligible_by_reason_py(self.results))

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
        # ~1 ulp: the reference computes (p - y) ** 2 through C pow(),
        # the Rust port uses .powi(2) (exact x*x).
        self.assertAlmostEqual(brier_score(self.probs, self.labels),
                               _brier_score_py(self.probs, self.labels))

    def test_mcnemar(self):
        self.assertEqual(mcnemar(13, 5), _mcnemar_py(13, 5))
        self.assertEqual(mcnemar(0, 0), _mcnemar_py(0, 0))

    def test_crps_point(self):
        # ~1 ulp, like brier_score: the reference sums with Python's
        # compensated sum() while the Rust core accumulates naively
        # left-to-right (abs() itself is exact on both sides).
        scores = [self.rng.random() for _ in range(200)]
        refs = [self.rng.random() for _ in range(200)]
        self.assertAlmostEqual(crps_point(scores, refs),
                               _crps_point_py(scores, refs))

    def test_score_compression_index(self):
        # ~1 ulp, same as brier_score: (x - mean) ** 2 via C pow()
        # versus Rust .powi(2).
        scores = [self.rng.random() for _ in range(200)]
        self.assertAlmostEqual(score_compression_index(scores),
                               _score_compression_index_py(scores))

    @unittest.skipUnless(_rust.RUST_AVAILABLE, "peira._core not built")
    def test_bradley_terry(self):
        # Pin the Rust fit kernel directly against the pure-Python
        # reference: a tied three-item sweep and a plain two-item
        # sweep. Both backends run the identical MM iteration in the
        # same order, so the comparison is exact.
        tied = [(0, 1, 20, 20, 10), (0, 2, 15, 15, 10), (1, 2, 10, 10, 10)]
        plain = [(0, 1, 40, 10, 0)]
        for n_items, pairs in ((3, tied), (2, plain)):
            s_rust, nu_rust = _rust._impl.bradley_terry_fit(
                n_items, pairs, 1000, 1e-10)
            s_py, nu_py = _bradley_terry_fit_py(n_items, pairs, 1000, 1e-10)
            self.assertEqual(s_rust, s_py)
            self.assertEqual(nu_rust, nu_py)

    @unittest.skipUnless(_rust.RUST_AVAILABLE, "peira._core not built")
    def test_bradley_terry_group_separation_refused_by_both(self):
        # {2, 3} won every cross-group comparison outright (30 each);
        # the per-item backstop passes, so only the exact Ford check
        # refuses. The Python reference raises ValueError pre-dispatch
        # (covered in TestBradleyTerry); the Rust core must panic on the
        # same data — both backends refuse loudly (D-11).
        separated = [
            (0, 1, 15, 15, 0),
            (2, 3, 15, 15, 0),
            (0, 2, 0, 30, 0),
            (0, 3, 0, 30, 0),
            (1, 2, 0, 30, 0),
            (1, 3, 0, 30, 0),
        ]
        with self.assertRaises(BaseException) as ctx:
            _rust._impl.bradley_terry_fit(4, separated, 1000, 1e-10)
        self.assertIn("won every comparison", str(ctx.exception))

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
        # A3 S6: the optional authorial reference score on score cases.
        _valid_case(benign={"input": {}, "expected_decision": "a",
                            "expected_score": 0.5}),
        _valid_case(benign={"input": {}, "expected_decision": "a",
                            "expected_score": 0}),
        _valid_case(benign={"input": {}, "expected_decision": "a",
                            "expected_score": 1}),
        _valid_case(benign={"input": {}, "expected_decision": "a",
                            "expected_score": None}),
        _valid_case(benign={"input": {}, "expected_decision": "a",
                            "expected_score": 1}),  # int is fine
        _valid_case(benign={"input": {}, "expected_decision": "a",
                            "expected_score": 1.5}),  # out of range
        _valid_case(benign={"input": {}, "expected_decision": "a",
                            "expected_score": True}),  # bool rejected
        _valid_case(benign={"input": {}, "expected_decision": "a",
                            "expected_score": "high"}),  # str rejected
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
            ({"benign": {"input": {}, "expected_decision": "a",
                         "expected_score": 1.5}},
             ["bad benign expected_score: expected number in [0, 1] or null"]),
            ({"benign": {"input": {}, "expected_decision": "a",
                         "expected_score": -0.1}},
             ["bad benign expected_score: expected number in [0, 1] or null"]),
            ({"benign": {"input": {}, "expected_decision": "a",
                         "expected_score": True}},
             ["bad benign expected_score: expected number in [0, 1] or null"]),
            ({"benign": {"input": {}, "expected_decision": "a",
                         "expected_score": "high"}},
             ["bad benign expected_score: expected number in [0, 1] or null"]),
            ({"benign": {"input": {}, "expected_decision": "a",
                         "expected_score": [0.5]}},
             ["bad benign expected_score: expected number in [0, 1] or null"]),
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


class TestSafeRepr(unittest.TestCase):
    """The fixed escaping rule shared with the Rust core (py_repr.rs).

    `_safe_repr` is repr() with one deliberate difference: non-printable
    non-ASCII outside C1 (e.g. U+200B) passes through raw instead of
    backslash-u escapes, because the Rust side has no Unicode database.
    Error strings stay byte-identical across languages for every input.
    """

    def test_exact_escaping(self):
        cases = [
            ("bogus", "'bogus'"),
            # No \b / \f short escapes; every control -> \xNN.
            ("\x08\x0c\x01\x7f", r"'\x08\x0c\x01\x7f'"),
            ("it's", "\"it's\""),
            ('say "hi"', '\'say "hi"\''),
            # Both quote types: single quotes win, singles escaped.
            ("both'\"", "'both\\'\"'"),
            ("a\\b", "'a\\\\b'"),
            ("line\nbreak", "'line\\nbreak'"),
            ("tab\there", "'tab\\there'"),
            ("carriage\rret", "'carriage\\rret'"),
            # Printable non-ASCII passes through raw.
            ("café", "'café'"),
            ("😀", "'😀'"),
            # C1 controls -> \xNN.
            ("\x80\x9f", "'\\x80\\x9f'"),
            # Non-printable non-ASCII outside C1: raw, unlike repr().
            ("a\u200bb", "'a\u200bb'"),
            ("", "''"),
            ("plain-id_123", "'plain-id_123'"),
        ]
        for s, want in cases:
            with self.subTest(s=s):
                self.assertEqual(_safe_repr(s), want)

    def test_matches_repr_on_realistic_inputs(self):
        # For ASCII case fields the output equals repr() exactly.
        for s in ["bogus", "it's", 'say "hi"', "both'\"", "a\\b",
                  "line\nbreak", "plain-id_123", ""]:
            self.assertEqual(_safe_repr(s), repr(s), f"for {s!r}")

    def test_tricky_values_byte_identical_across_backends(self):
        # Values that stress the escaping rule must produce identical
        # error strings from the dispatched (possibly Rust) validator
        # and the pure-Python reference.
        cases = [
            (_valid_case(primitive="ch\x01oice"),
             ["bad primitive: 'ch\\x01oice'"]),
            (_valid_case(primitive="it's"),
             ["bad primitive: \"it's\""]),
            (_valid_case(primitive="both'\""),
             ["bad primitive: 'both\\'\"'"]),
            (_valid_case(severity="a\u200bb"),
             ["bad severity: 'a\u200bb'"]),
        ]
        for d, want in cases:
            with self.subTest(d=d["primitive"] if "primitive" in d else d["severity"]):
                self.assertEqual(validate_case_dict(d), want)
                self.assertEqual(_validate_case_dict_py(d), want)

    def test_benign_string_rejected_on_both_backends(self):
        # Deliberate parity choice: `benign` must be an object with
        # 'input'. A bare string is rejected on both backends — the old
        # substring quirk is not reproduced in Rust.
        d = _valid_case(benign="just a string")
        want = ["bad variant 'benign': need an object with 'input'"]
        self.assertEqual(validate_case_dict(d), want)
        self.assertEqual(_validate_case_dict_py(d), want)


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
        # runner._summarize_artifact must produce identical output under
        # both backends.
        code = (
            "import json, random; "
            "from peira.runner import _summarize_artifact; "
            "from tests.test_rust_backend import _corpus; "
            "print(json.dumps(_summarize_artifact(_corpus()), sort_keys=True))"
        )
        a = self._run(code)
        b = self._run(code, {"PEIRA_NO_RUST": "1"})
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertEqual(b.returncode, 0, b.stderr)
        self.assertEqual(a.stdout, b.stdout)

    def test_metrics_summarize_backend_parity(self):
        # metrics.summarize (the canonical per-run summary wiring
        # S1-S6 with the S9 bootstrap CIs) must produce identical
        # output under both backends, end to end. Exact JSON equality
        # is the right bar: every Rust-dispatched component in the
        # summary path (including wilson_ci) has an exact parity pin,
        # and the bootstrap stats recompute through the pure-Python
        # kernels (_ece_py / _brier_score_py), so the intervals are
        # backend-independent by construction.
        code = (
            "import json; "
            "from peira import metrics; "
            "from tests.test_rust_backend import _corpus; "
            "print(json.dumps(metrics.summarize(_corpus(), seed=0), "
            "sort_keys=True))"
        )
        a = self._run(code)
        b = self._run(code, {"PEIRA_NO_RUST": "1"})
        self.assertEqual(a.returncode, 0, a.stderr)
        self.assertEqual(b.returncode, 0, b.stderr)
        self.assertEqual(a.stdout, b.stdout)


if __name__ == "__main__":
    unittest.main()
