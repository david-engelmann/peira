"""Tests for the SemIf adapter (subprocess CLI).

No subprocesses are ever spawned: every test injects a fake ``runner=``
so the adapter never touches the filesystem, and ``shutil.which`` is
stubbed for the binary-resolution tests. The real ``_default_runner``
is tested with a mocked ``subprocess.run``.
"""

import json
import os
import subprocess
import unittest
from unittest import mock

from peira.adapters.base import CallContext, ProviderError, validate_output
from peira.adapters import semif as semif_mod
from peira.adapters.semif import (
    CLI_BINARY,
    MODEL_ID,
    MODEL_REVISION,
    SemifAdapter,
)

_CTX_DEFAULTS = {
    "case_id": "s1",
    "expected_decision": "deny",
    "target_decision": "approve",
    "attacked": True,
}


def _case_input(**over):
    d = {"prompt": "Decision: approve or deny?"}
    for k, v in over.items():
        if k not in _CTX_DEFAULTS:
            d[k] = v
    return d


def _ctx(**over):
    vals = dict(_CTX_DEFAULTS)
    vals.update(over)
    return CallContext(
        case_id=vals["case_id"],
        arm="attacked" if vals["attacked"] else "benign",
        expected_decision=vals["expected_decision"],
        target_decision=vals["target_decision"],
    )


def _runner_for(rows_by_id):
    """Fake runner: returns canned result rows, captures what it got."""
    seen = {}

    def fake(input_rows, argv, timeout_s):
        seen["input_rows"] = input_rows
        seen["argv"] = argv
        seen["timeout_s"] = timeout_s
        return [dict(rows_by_id[rid]) for rid in rows_by_id]

    fake.seen = seen
    return fake


def _decision_row(probs, **over):
    row = {"id": "decision", "probabilities": probs}
    row.update(over)
    return row


class TestSemifConstruction(unittest.TestCase):
    def _no_binary(self):
        return mock.patch.object(semif_mod.shutil, "which",
                                 return_value=None)

    def test_missing_binary_is_actionable(self):
        with self._no_binary():
            with self.assertRaises(FileNotFoundError) as cm:
                SemifAdapter()
        msg = str(cm.exception)
        self.assertIn("semif-score", msg)
        self.assertIn("theoleecj/semif", msg)

    def test_legacy_binary_fallback(self):
        def which(name):
            return None if name == CLI_BINARY else "/usr/local/bin/openjev-score"
        with mock.patch.object(semif_mod.shutil, "which", side_effect=which):
            a = SemifAdapter()
        self.assertEqual(a.binary, "openjev-score")

    def test_explicit_binary_missing_is_actionable(self):
        with self._no_binary():
            with self.assertRaises(FileNotFoundError) as cm:
                SemifAdapter(binary="/nope/semif-score")
        self.assertIn("/nope/semif-score", str(cm.exception))

    def test_injected_runner_skips_binary_check(self):
        def boom_which(name):
            raise AssertionError("which() must not be called")
        with mock.patch.object(semif_mod.shutil, "which",
                               side_effect=boom_which):
            a = SemifAdapter(runner=lambda *a: [])
        self.assertEqual(a.binary, CLI_BINARY)

    def test_model_and_revision_pinned(self):
        self.assertEqual(MODEL_ID, "Qwen/Qwen3.5-4B")
        self.assertEqual(MODEL_REVISION,
                         "851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a")
        # None resolves to the pinned model (sibling-adapter convention).
        self.assertEqual(SemifAdapter(runner=lambda *a: []).model,
                         MODEL_ID)
        with self.assertRaises(ValueError):
            SemifAdapter(runner=lambda *a: [], model="Qwen/Qwen3-4B")
        with self.assertRaises(ValueError):
            SemifAdapter(runner=lambda *a: [], model="")
        with self.assertRaises(ValueError):
            SemifAdapter(runner=lambda *a: [], revision="main")

    def test_extra_args_reject_input_output(self):
        # --input/--output are reserved for the adapter's temp files.
        with self.assertRaises(ValueError):
            SemifAdapter(runner=lambda *a: [],
                         extra_args=["--input", "x.jsonl"])
        with self.assertRaises(ValueError):
            SemifAdapter(runner=lambda *a: [],
                         extra_args=["--output", "y.jsonl"])

    def test_cache_namespace_and_version(self):
        a = SemifAdapter(runner=lambda *a: [])
        self.assertEqual(a.name, "semif")
        self.assertEqual(a.version, f"{MODEL_ID}@{MODEL_REVISION}")
        self.assertEqual(a.cache_namespace, f"semif:{MODEL_ID}@{MODEL_REVISION}")
        self.assertEqual(a.supported_primitives,
                         frozenset({"choice", "score", "abstain"}))


class TestSemifArgv(unittest.TestCase):
    def test_argv_pins_mode_model_revision(self):
        r = _runner_for({"decision": _decision_row({"deny": 1.0})})
        a = SemifAdapter(runner=r)
        a.decide(_case_input(), "choice", _ctx())
        argv = r.seen["argv"]
        self.assertEqual(argv[0], CLI_BINARY)
        self.assertIn("--mode", argv)
        self.assertEqual(argv[argv.index("--mode") + 1], "direct")
        self.assertEqual(argv[argv.index("--model") + 1], MODEL_ID)
        self.assertEqual(argv[argv.index("--revision") + 1], MODEL_REVISION)
        self.assertEqual(r.seen["timeout_s"], 600.0)

    def test_extra_args_appended(self):
        r = _runner_for({"decision": _decision_row({"deny": 1.0})})
        a = SemifAdapter(runner=r, extra_args=["--backend", "mlx"])
        a.decide(_case_input(), "choice", _ctx())
        argv = r.seen["argv"]
        self.assertEqual(argv[-2:], ["--backend", "mlx"])


class TestSemifChoice(unittest.TestCase):
    def test_choice_maps_winner_and_confidence(self):
        r = _runner_for({"decision": _decision_row(
            {"deny": 0.2, "approve": 0.7, "other": 0.1})})
        out = SemifAdapter(runner=r).decide(_case_input(), "choice", _ctx())
        self.assertEqual(validate_output(out, "choice"), [])
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.7)
        self.assertEqual(out.usage.model, MODEL_ID)

    def test_choice_input_row_shape(self):
        r = _runner_for({"decision": _decision_row({"deny": 1.0})})
        SemifAdapter(runner=r).decide(_case_input(), "choice", _ctx())
        rows = r.seen["input_rows"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["id"], "decision")
        self.assertEqual(row["state"], "Decision: approve or deny?")
        self.assertTrue(row["question"])
        option_ids = [o["id"] for o in row["options"]]
        # The SemIf input contract: options carry id + description.
        self.assertEqual(set(option_ids), {"deny", "approve", "other"})
        self.assertTrue(all(o["description"] for o in row["options"]))

    def test_choice_winner_outside_labels_is_terminal(self):
        r = _runner_for({"decision": _decision_row({"maybe": 0.9})})
        with self.assertRaises(ProviderError):
            SemifAdapter(runner=r).decide(_case_input(), "choice", _ctx())

    def test_unsupported_primitive(self):
        with self.assertRaises(ValueError):
            SemifAdapter(runner=lambda *a: []).decide(
                _case_input(), "bogus", _ctx())


class TestSemifScore(unittest.TestCase):
    def _score_runner(self, level_probs, decision_probs=None):
        rows = {
            "score": {"id": "score", "probabilities": level_probs},
            "decision": _decision_row(decision_probs or {"deny": 0.8,
                                                         "approve": 0.1,
                                                         "other": 0.1}),
        }
        return _runner_for(rows)

    def test_score_weighted_rubric(self):
        r = self._score_runner({"level-0": 0.0, "level-1": 0.0,
                                "level-2": 0.5, "level-3": 0.5,
                                "level-4": 0.0})
        out = SemifAdapter(runner=r).decide(_case_input(), "score", _ctx())
        self.assertEqual(validate_output(out, "score"), [])
        # expected level 2.5 / 4
        self.assertAlmostEqual(out.score, 0.625)
        self.assertEqual(out.decision, "deny")
        self.assertAlmostEqual(out.confidence, 0.8)

    def test_score_sends_two_rows(self):
        r = self._score_runner({"level-4": 1.0})
        SemifAdapter(runner=r).decide(_case_input(), "score", _ctx())
        self.assertEqual([row["id"] for row in r.seen["input_rows"]],
                         ["score", "decision"])
        score_row = r.seen["input_rows"][0]
        self.assertEqual(len(score_row["options"]), 5)
        self.assertEqual([o["id"] for o in score_row["options"]],
                         [f"level-{i}" for i in range(5)])

    def test_score_renormalizes(self):
        # Unnormalized typed scores still map to a valid 0..1 score.
        r = self._score_runner({"level-3": 30.0, "level-4": 10.0})
        out = SemifAdapter(runner=r).decide(_case_input(), "score", _ctx())
        self.assertAlmostEqual(out.score, 3.25 / 4)

    def test_score_zero_total_is_terminal(self):
        r = self._score_runner({"level-0": 0.0, "level-1": 0.0,
                                "level-2": 0.0, "level-3": 0.0,
                                "level-4": 0.0})
        with self.assertRaises(ProviderError):
            SemifAdapter(runner=r).decide(_case_input(), "score", _ctx())


class TestSemifAbstain(unittest.TestCase):
    def test_abstain_yes_means_abstain(self):
        r = _runner_for({"abstain": {"id": "abstain",
                                     "probabilities": {"yes": 0.8,
                                                       "no": 0.2}}})
        out = SemifAdapter(runner=r).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(validate_output(out, "abstain"), [])
        self.assertEqual(out.decision, "abstain")
        self.assertAlmostEqual(out.confidence, 0.6)  # |2*.8-1|

    def test_abstain_no_returns_expected(self):
        r = _runner_for({"abstain": {"id": "abstain",
                                     "probabilities": {"yes": 0.2,
                                                       "no": 0.8}}})
        out = SemifAdapter(runner=r).decide(_case_input(), "abstain", _ctx())
        self.assertEqual(out.decision, "deny")

    def test_abstain_input_is_yes_no_question(self):
        r = _runner_for({"abstain": {"id": "abstain",
                                     "probabilities": {"yes": 0.1,
                                                       "no": 0.9}}})
        SemifAdapter(runner=r).decide(_case_input(), "abstain", _ctx())
        row = r.seen["input_rows"][0]
        self.assertEqual(row["id"], "abstain")
        self.assertEqual([o["id"] for o in row["options"]], ["yes", "no"])
        # NOTE: SemIf has no "noul" wire type — the abstain primitive is
        # an ordinary yes/no question (see the adapter docstring).
        self.assertNotIn("noul", json.dumps(row))

    def test_abstain_missing_yes_is_terminal(self):
        r = _runner_for({"abstain": {"id": "abstain",
                                     "probabilities": {"no": 1.0}}})
        with self.assertRaises(ProviderError):
            SemifAdapter(runner=r).decide(_case_input(), "abstain", _ctx())


class TestSemifOutputShapes(unittest.TestCase):
    """The CLI's output keys are UNVERIFIED — the parser is tolerant."""

    def test_alternative_probability_keys(self):
        for key in ("option_scores", "scores", "option_probabilities"):
            r = _runner_for({"decision": {"id": "decision",
                                          key: {"approve": 0.9,
                                                "deny": 0.05,
                                                "other": 0.05}}})
            out = SemifAdapter(runner=r).decide(_case_input(), "choice",
                                                _ctx())
            self.assertEqual(out.decision, "approve", msg=key)

    def test_list_of_option_objects(self):
        r = _runner_for({"decision": {"id": "decision", "probabilities": [
            {"id": "deny", "probability": 0.1},
            {"id": "approve", "probability": 0.85},
            {"id": "other", "probability": 0.05},
        ]}})
        out = SemifAdapter(runner=r).decide(_case_input(), "choice", _ctx())
        self.assertEqual(out.decision, "approve")
        self.assertAlmostEqual(out.confidence, 0.85)

    def test_bare_list_parallel_to_labels(self):
        # [deny, approve, other] order — the labels offered on attacked.
        r = _runner_for({"decision": {"id": "decision",
                                      "probabilities": [0.1, 0.8, 0.1]}})
        out = SemifAdapter(runner=r).decide(_case_input(), "choice", _ctx())
        self.assertEqual(out.decision, "approve")

    def test_unrecognized_shape_is_terminal(self):
        r = _runner_for({"decision": {"id": "decision",
                                      "mystery": {"approve": 1.0}}})
        with self.assertRaises(ProviderError):
            SemifAdapter(runner=r).decide(_case_input(), "choice", _ctx())

    def test_missing_row_is_terminal(self):
        r = _runner_for({})  # no rows at all
        with self.assertRaises(ProviderError):
            SemifAdapter(runner=r).decide(_case_input(), "choice", _ctx())

    def test_non_list_runner_result_is_terminal(self):
        with self.assertRaises(ProviderError):
            SemifAdapter(runner=lambda *a: {"decision": {}}).decide(
                _case_input(), "choice", _ctx())

    def test_runner_provider_error_propagates(self):
        def boom(input_rows, argv, timeout_s):
            raise ProviderError("semif CLI exited with status 1: boom")
        with self.assertRaises(ProviderError) as cm:
            SemifAdapter(runner=boom).decide(_case_input(), "choice", _ctx())
        self.assertIsNone(cm.exception.status_code)  # terminal

    def test_revision_mismatch_noted_in_transcript(self):
        r = _runner_for({"decision": _decision_row(
            {"deny": 1.0}, model_revision="deadbeef")})
        out = SemifAdapter(runner=r).decide(_case_input(), "choice", _ctx())
        self.assertIn("revision_note", out.transcript)
        self.assertIn("deadbeef", out.transcript["revision_note"])

    def test_matching_revision_no_note(self):
        r = _runner_for({"decision": _decision_row(
            {"deny": 1.0}, model_revision=MODEL_REVISION)})
        out = SemifAdapter(runner=r).decide(_case_input(), "choice", _ctx())
        self.assertNotIn("revision_note", out.transcript)

    def test_transcript_carries_argv_flags(self):
        r = _runner_for({"decision": _decision_row({"deny": 1.0})})
        out = SemifAdapter(runner=r).decide(_case_input(), "choice", _ctx())
        self.assertIn("--revision", out.transcript["argv"])
        self.assertEqual(out.transcript["binary"], CLI_BINARY)


class TestSemifDefaultRunner(unittest.TestCase):
    """The real _default_runner with a mocked subprocess.run (no spawn)."""

    def _run(self, rows, run_side_effect, timeout_s=30.0):
        argv = ["semif-score", "--mode", "direct", "--model", MODEL_ID,
                "--revision", MODEL_REVISION]
        with mock.patch.object(semif_mod.subprocess, "run",
                               side_effect=run_side_effect) as m:
            out = semif_mod._default_runner(rows, argv, timeout_s)
        return out, m

    def _ok_run(self, output_rows, stderr=""):
        def effect(cmd, **kwargs):
            out_path = cmd[cmd.index("--output") + 1]
            in_path = cmd[cmd.index("--input") + 1]
            with open(in_path, encoding="utf-8") as f:
                effect.seen_rows = [json.loads(line) for line in f
                                    if line.strip()]
            with open(out_path, "w", encoding="utf-8") as f:
                for row in output_rows:
                    f.write(json.dumps(row) + "\n")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr=stderr)
        return effect

    def test_success_roundtrip(self):
        rows = [{"id": "decision", "state": "s", "question": "q",
                 "options": [{"id": "deny", "description": "d"}]}]
        effect = self._ok_run([{"id": "decision",
                                "probabilities": {"deny": 1.0}}])
        out, m = self._run(rows, effect)
        self.assertEqual(out[0]["probabilities"], {"deny": 1.0})
        # The input file got exactly our rows.
        self.assertEqual(effect.seen_rows, rows)
        # Timeout was passed through.
        self.assertEqual(m.call_args.kwargs["timeout"], 30.0)

    def test_nonzero_exit_is_terminal(self):
        def effect(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 1, stdout="",
                                               stderr="CUDA OOM\n" * 10)
        with self.assertRaises(ProviderError) as cm:
            self._run([{"id": "x"}], effect)
        err = cm.exception
        self.assertIsNone(err.status_code)
        self.assertIn("status 1", str(err))
        self.assertIn("CUDA OOM", str(err))

    def test_timeout_is_terminal(self):
        def effect(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 30.0)
        with self.assertRaises(ProviderError) as cm:
            self._run([{"id": "x"}], effect)
        self.assertIsNone(cm.exception.status_code)
        self.assertIn("timed out", str(cm.exception))

    def test_missing_binary_at_spawn_is_actionable(self):
        def effect(cmd, **kwargs):
            raise FileNotFoundError(2, "No such file", "semif-score")
        with self.assertRaises(ProviderError) as cm:
            self._run([{"id": "x"}], effect)
        self.assertIn("semif-score", str(cm.exception))
        self.assertIn("theoleecj/semif", str(cm.exception))

    def test_unparseable_output_is_terminal(self):
        def effect(cmd, **kwargs):
            out_path = cmd[cmd.index("--output") + 1]
            with open(out_path, "w", encoding="utf-8") as f:
                f.write("not json\n")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        with self.assertRaises(ProviderError):
            self._run([{"id": "x"}], effect)


if __name__ == "__main__":
    unittest.main()
