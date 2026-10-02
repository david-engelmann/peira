"""Tests for the signals layer (python/peira/signals.py, P-9).

Run with: PYTHONPATH=python python3 -m pytest tests/test_signals.py
"""

import json
import unittest

from peira.signals import (
    DEFAULT_THRESHOLDS,
    ISSUE_TYPES,
    VOLUME_TYPES,
    MAX_VOLUME_SCORE,
    MIN_ISSUE_SCORE,
    check_success,
    detect_signals,
    empty_registry,
    roll_forward,
)


def _row(adapter, asr=0.3, ci=(0.2, 0.4), benign=0.95, ece=0.05,
         n_eligible=400):
    return {
        "adapter_name": adapter,
        "asr_conditional": asr,
        "asr_ci95": list(ci),
        "benign_accuracy": benign,
        "ece_attacked": ece,
        "n_eligible": n_eligible,
        "ranking_eligible": True,
    }


def _leaderboard(*rows):
    return {"ranked": list(rows), "unranked": []}


def _run_payload(adapter, families=None, abstention=0.05):
    fams = {}
    for fam, asr, n, cost in (families or []):
        fams[fam] = {"family": fam, "asr": asr, "asr_ci95": [asr - 0.05, asr + 0.05],
                     "n_eligible": n, "cost_usd": cost}
    return {
        "headline": {"abstention_rate": abstention},
        "families": fams,
    }


class DetectTest(unittest.TestCase):
    def test_quiet_leaderboard_emits_no_signals(self):
        lb = _leaderboard(_row("a"))
        self.assertEqual(detect_signals(lb), [])

    def test_regression_detected_against_previous(self):
        prev = _leaderboard(_row("a", asr=0.20))
        curr = _leaderboard(_row("a", asr=0.30))
        signals = detect_signals(curr, previous_leaderboard=prev)
        kinds = [s["type"] for s in signals]
        self.assertIn("asr_regression", kinds)
        sig = next(s for s in signals if s["type"] == "asr_regression")
        self.assertAlmostEqual(sig["evidence"]["delta"], 0.10)
        # Falsifiable success metric names the bar.
        self.assertIn("0.20", sig["success_metric"])

    def test_small_delta_is_not_a_regression(self):
        prev = _leaderboard(_row("a", asr=0.20))
        curr = _leaderboard(_row("a", asr=0.22))
        signals = detect_signals(curr, previous_leaderboard=prev)
        self.assertNotIn("asr_regression", [s["type"] for s in signals])

    def test_high_asr_family(self):
        lb = _leaderboard(_row("a"))
        payloads = {"a": _run_payload("a", [("prompt_injection", 0.65, 400, 1.0),
                                            ("jailbreak", 0.10, 400, 1.0)])}
        signals = detect_signals(lb, run_payloads=payloads)
        fam = [s for s in signals if s["type"] == "high_asr_family"]
        self.assertEqual(len(fam), 1)
        self.assertEqual(fam[0]["evidence"]["family"], "prompt_injection")

    def test_tiny_family_does_not_trigger(self):
        lb = _leaderboard(_row("a"))
        payloads = {"a": _run_payload("a", [("prompt_injection", 0.90, 5, 1.0)])}
        signals = detect_signals(lb, run_payloads=payloads)
        self.assertNotIn("high_asr_family", [s["type"] for s in signals])

    def test_benign_utility_drop(self):
        lb = _leaderboard(_row("a", benign=0.70))
        signals = detect_signals(lb)
        self.assertIn("benign_utility_drop", [s["type"] for s in signals])

    def test_calibration_gap(self):
        lb = _leaderboard(_row("a", ece=0.25))
        signals = detect_signals(lb)
        self.assertIn("calibration_gap", [s["type"] for s in signals])

    def test_abstention_spike(self):
        lb = _leaderboard(_row("a"))
        payloads = {"a": _run_payload("a", abstention=0.40)}
        signals = detect_signals(lb, run_payloads=payloads)
        self.assertIn("abstention_spike", [s["type"] for s in signals])

    def test_underpowered_is_volume_class(self):
        lb = _leaderboard(_row("a", ci=(0.05, 0.60)))
        signals = detect_signals(lb)
        vol = [s for s in signals if s["type"] == "underpowered"]
        self.assertEqual(len(vol), 1)
        self.assertLessEqual(vol[0]["score"], MAX_VOLUME_SCORE)

    def test_cost_concentration(self):
        lb = _leaderboard(_row("a"))
        fams = [(f"fam{i}", 0.10, 400, 10.0 if i < 3 else 0.5) for i in range(6)]
        payloads = {"a": _run_payload("a", fams)}
        signals = detect_signals(lb, run_payloads=payloads)
        self.assertIn("cost_concentration", [s["type"] for s in signals])

    def test_scoring_invariant_volume_never_outranks_issue(self):
        # Worst volume signal still scores below the weakest issue signal.
        lb = _leaderboard(_row("a", asr=0.9, ci=(0.0, 1.0), benign=0.5,
                               ece=0.5))
        payloads = {"a": _run_payload(
            "a",
            [("prompt_injection", 0.9, 400, 10.0),
             ("jailbreak", 0.9, 400, 10.0),
             ("f3", 0.1, 400, 10.0),
             ("f4", 0.1, 400, 0.1),
             ("f5", 0.1, 400, 0.1),
             ("f6", 0.1, 400, 0.1)],
            abstention=0.5)}
        prev = _leaderboard(_row("a", asr=0.1))
        signals = detect_signals(lb, run_payloads=payloads,
                                 previous_leaderboard=prev)
        issue_scores = [s["score"] for s in signals if s["type"] in ISSUE_TYPES]
        volume_scores = [s["score"] for s in signals if s["type"] in VOLUME_TYPES]
        self.assertTrue(issue_scores and volume_scores)
        self.assertLess(max(volume_scores), min(issue_scores))
        self.assertGreaterEqual(min(issue_scores), MIN_ISSUE_SCORE)

    def test_deterministic_order(self):
        # Score-descending first: benign_utility_drop scores 85.0,
        # calibration_gap scores 60.0, so benign must come first even
        # when the adapter sorts last alphabetically.
        lb = _leaderboard(_row("b", benign=0.5, ece=0.5),
                          _row("a", benign=0.5, ece=0.5))
        ids = [s["signal_id"] for s in detect_signals(lb)]
        self.assertEqual(ids, ["benign-utility-drop:a", "benign-utility-drop:b",
                              "calibration-gap:a", "calibration-gap:b"])

    def test_missing_values_degrade_to_no_signal(self):
        lb = _leaderboard({"adapter_name": "a", "ranking_eligible": True})
        self.assertEqual(detect_signals(lb), [])


class SuccessCheckTest(unittest.TestCase):
    def test_regression_success_when_asr_recovers(self):
        prev = _leaderboard(_row("a", asr=0.20))
        curr = _leaderboard(_row("a", asr=0.30))
        sig = next(s for s in detect_signals(curr, previous_leaderboard=prev)
                   if s["type"] == "asr_regression")
        recovered = _leaderboard(_row("a", asr=0.18))
        self.assertTrue(check_success(sig, recovered))
        still_bad = _leaderboard(_row("a", asr=0.30))
        self.assertFalse(check_success(sig, still_bad))

    def test_family_success(self):
        lb = _leaderboard(_row("a"))
        payloads = {"a": _run_payload("a", [("prompt_injection", 0.65, 400, 1.0)])}
        sig = next(s for s in detect_signals(lb, run_payloads=payloads)
                   if s["type"] == "high_asr_family")
        fixed = {"a": _run_payload("a", [("prompt_injection", 0.30, 400, 1.0)])}
        self.assertTrue(check_success(sig, lb, fixed))
        self.assertFalse(check_success(sig, lb, payloads))

    def test_unknown_check_kind_is_false(self):
        self.assertFalse(check_success(
            {"success_check": {"kind": "nope"}}, _leaderboard()))


class RegistryTest(unittest.TestCase):
    def test_roll_forward_lifecycle(self):
        prev = _leaderboard(_row("a", asr=0.20))
        curr = _leaderboard(_row("a", asr=0.30))
        signals = detect_signals(curr, previous_leaderboard=prev)
        reg = roll_forward(empty_registry(), signals, curr, report_id="2026-10")
        sid = signals[0]["signal_id"]
        self.assertEqual(reg["signals"][sid]["status"], "open")
        self.assertEqual(reg["signals"][sid]["months_open"], 1)
        # Still open next month: counter increments.
        reg2 = roll_forward(reg, signals, curr, report_id="2026-11")
        self.assertEqual(reg2["signals"][sid]["status"], "open")
        self.assertEqual(reg2["signals"][sid]["months_open"], 2)
        # Recovered: becomes implemented and stays there.
        fixed = _leaderboard(_row("a", asr=0.18))
        fixed_signals = detect_signals(fixed, previous_leaderboard=curr)
        reg3 = roll_forward(reg2, fixed_signals, fixed, report_id="2026-12")
        self.assertEqual(reg3["signals"][sid]["status"], "implemented")
        reg4 = roll_forward(reg3, fixed_signals, fixed, report_id="2027-01")
        self.assertEqual(reg4["signals"][sid]["status"], "implemented")

    def test_new_signal_ids_enter_open(self):
        lb = _leaderboard(_row("a", benign=0.5))
        signals = detect_signals(lb)
        reg = roll_forward(empty_registry(), signals, lb, report_id="2026-10")
        self.assertTrue(all(e["status"] == "open" for e in reg["signals"].values()))

    def test_roll_forward_does_not_mutate_input(self):
        # The module promises purity: the caller's registry must be
        # untouched by a roll_forward call.
        prev = _leaderboard(_row("a", asr=0.20))
        curr = _leaderboard(_row("a", asr=0.30))
        signals = detect_signals(curr, previous_leaderboard=prev)
        reg = roll_forward(empty_registry(), signals, curr, report_id="2026-10")
        snapshot = json.dumps(reg, sort_keys=True)
        roll_forward(reg, signals, curr, report_id="2026-11")
        self.assertEqual(json.dumps(reg, sort_keys=True), snapshot)

    def test_detect_signals_output_is_json_safe(self):
        # Malformed payload values must not break the JSON-safe promise:
        # tuples become lists, non-data values are dropped.
        payloads = {"a": {"families": {
            "prompt_injection": {
                "asr": 0.70, "n_eligible": 400,
                "asr_ci95": (0.60, 0.80),  # tuple instead of list
                "cost_usd": object(),  # non-data value: must be dropped
            }}}}
        signals = detect_signals({}, run_payloads=payloads)
        sig = next(s for s in signals if s["type"] == "high_asr_family")
        self.assertIsInstance(sig["evidence"]["asr_ci95"], list)
        self.assertNotIn("cost_usd", sig["evidence"])
        blob = json.dumps(signals)
        self.assertIn("[0.6, 0.8]", blob)

    def test_non_finite_floats_are_json_safe(self):
        # NaN/inf must never reach the output: they are not valid
        # strict JSON and NaN defeats every numeric comparison.
        # f1 fires high_asr_family with an inf inside its CI; f2's NaN
        # n_eligible must degrade to "no signal", never a crash.
        payloads = {"a": {"families": {
            "f1": {"asr": 0.70, "n_eligible": 400,
                   "asr_ci95": [0.60, float("inf")], "cost_usd": 1.0},
            "f2": {"asr": 0.70, "n_eligible": float("nan"),
                   "cost_usd": 1.0},
        }, "headline": {"abstention_rate": 0.05}}}
        signals = detect_signals({}, run_payloads=payloads)
        self.assertEqual(
            [s["signal_id"] for s in signals], ["high-asr-family:a:f1"])
        sig = signals[0]
        self.assertEqual(sig["evidence"]["asr_ci95"], [0.60, None])
        blob = json.dumps(signals)
        self.assertNotIn("NaN", blob)
        self.assertNotIn("Infinity", blob)
        # Strict-JSON parse of the whole blob must succeed.
        json.loads(blob, parse_constant=lambda x: (_ for _ in ()).throw(
            ValueError(x)))

    def test_roll_forward_skips_corrupt_registry_entries(self):
        # A hand-edited or corrupted registry must not abort the whole
        # roll-forward: non-dict entries are replaced by fresh signals.
        lb = _leaderboard(_row("a", asr=0.3))
        prev = _leaderboard(_row("a", asr=0.20))
        signals = detect_signals(lb, previous_leaderboard=prev)
        sid = next(s["signal_id"] for s in signals
                   if s["type"] == "asr_regression")
        reg = {"version": 1, "signals": {sid: "notadict"}}
        out = roll_forward(reg, signals, lb, report_id="2026-10")
        entry = out["signals"][sid]
        self.assertEqual(entry["status"], "open")
        self.assertEqual(entry["months_open"], 1)

    def test_roll_forward_adopts_latest_success_bar(self):
        # A re-emitted signal tracks the current report's promise, not
        # the first month's bar.
        prev = _leaderboard(_row("a", asr=0.20))
        curr = _leaderboard(_row("a", asr=0.30))
        reg = roll_forward(empty_registry(),
                           detect_signals(curr, previous_leaderboard=prev),
                           curr, report_id="2026-10")
        sid = next(iter(reg["signals"]))
        self.assertEqual(reg["signals"][sid]["success_check"]["value"], 0.20)
        worse = _leaderboard(_row("a", asr=0.40))
        reg = roll_forward(reg,
                           detect_signals(worse, previous_leaderboard=curr),
                           worse, report_id="2026-11")
        entry = reg["signals"][sid]
        self.assertEqual(entry["success_check"]["value"], 0.30)
        self.assertEqual(entry["months_open"], 2)
        self.assertEqual(entry["status"], "open")


if __name__ == "__main__":
    unittest.main()
