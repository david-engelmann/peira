"""Mock adapter: deterministic, offline, zero-dependency.

Used for the 30-second quickstart and CI. It answers the benign variant
correctly and flips on a fixed, seeded subset of attacked variants, so
decisions are reproducible for a given (seed, cases): the same seed
always yields the same flips and confidences. Call ids, however, are
namespaced per run (see ``new_run_nonce``), so transcripts from two
executions are unlinkable even with the same seed.

The mock is a test double, and its simulation data reaches it the way a
test double's should: explicitly, through the constructor — never through
the production ``decide()`` protocol. Under B2 (D-25 amended 2026-09-25)
the adapter-visible ``CallContext`` carries no case id, no arm, and no
gold, so the mock cannot read its simulation inputs off the context the
way it used to. Instead the harness builds a script
(``MockAdapter.script_for``) mapping each call's pseudonymous id to its
simulation inputs, and hands it to the constructor. The runner never
sees or touches the script; the boundary stays clean.

On a flip it moves toward the case's own target decision; without a
usable target it toggles the classic approve/deny pair. Its score
positive class is "approve" (see ``ScoreOutput``). Confidence is derived
deterministically from the seed and case id (high when deciding as
expected, lower on flips). It reports no token usage (nothing real was
called) and never abstains. This is a mechanism exerciser, not a
baseline — no benchmark claim may rest on mock-adapter numbers.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from peira.adapters.base import (
    AdapterOutput,
    CallContext,
    ChoiceOutput,
    AbstainOutput,
    ScoreOutput,
)


@dataclass(frozen=True)
class _ScriptedCall:
    """One scripted call: the simulation inputs for a single decide() call.

    Built by the harness (never by the adapter, never from the
    production context): which arm this call is, the gold decisions for
    it, and a stable per-case identity string used ONLY to seed the
    deterministic flip/confidence hashes. The harness keys the script
    by the adapter-visible pseudonymous call id.
    """

    arm: str  # "benign" | "attacked"
    expected_decision: str
    target_decision: str | None
    hash_id: str


class MockAdapter:
    """A deterministic fake decision model."""

    name = "mock"
    version = "0.2.0"
    supported_primitives = frozenset({"choice", "score", "abstain"})

    def __init__(
        self,
        flip_rate: float = 0.4,
        seed: str = "peira-mock-v1",
        script: dict[str, _ScriptedCall] | None = None,
    ) -> None:
        self.flip_rate = flip_rate
        self.seed = seed
        # The simulation script: call_id -> _ScriptedCall. Built
        # explicitly by the harness (see script_for); the mock never
        # derives simulation inputs from the production context.
        self._script = script
        # The mock is deterministic given (seed, flip_rate): namespace
        # the cache on both, so a different mock config never shares
        # entries. (Caching the mock itself buys nothing — it is
        # instant — but the namespace must still be correct.)
        self.cache_namespace = f"mock:{seed}:{flip_rate}"

    @staticmethod
    def script_for(
        cases: Any,
        *,
        seed: int = 0,
        dispatch_base: int = 0,
        run_nonce: str,
    ) -> dict[str, _ScriptedCall]:
        """Build a simulation script for a list of cases.

        The harness (``peira run --adapter mock``, tests) calls this
        with the loaded cases, the run seed, and the SAME ``run_nonce``
        the run will use (see ``new_run_nonce``); the runner's dispatch
        indices are suite-position-derived (benign = ``dispatch_base +
        2i``, attacked = ``dispatch_base + 2i + 1``), so the script keys
        line up with the pseudonymous call ids the runner will
        generate. For ``run_case`` pass a single case with the same
        ``seed``/``dispatch_base``/``run_nonce`` the call uses.
        ``run_nonce`` is required — a script built under the wrong
        namespace matches nothing, so guessing is worse than failing
        fast.
        """
        # Imported here: runner imports nothing from this module, so
        # there is no cycle, and importing this module never requires
        # the runner.
        from peira.runner import _pseudonymous_call_id

        script: dict[str, _ScriptedCall] = {}
        for i, case in enumerate(cases):
            expected = case.benign.expected_decision
            target = case.attacked.target_decision
            script[
                _pseudonymous_call_id(
                    run_nonce, seed, dispatch_base + 2 * i
                )
            ] = _ScriptedCall(
                arm="benign",
                expected_decision=expected,
                target_decision=None,
                hash_id=case.case_id,
            )
            script[
                _pseudonymous_call_id(
                    run_nonce, seed, dispatch_base + 2 * i + 1
                )
            ] = _ScriptedCall(
                arm="attacked",
                expected_decision=expected,
                target_decision=target,
                hash_id=case.case_id,
            )
        return script

    def _flips(self, hash_id: str) -> bool:
        digest = hashlib.sha256(f"{self.seed}:{hash_id}".encode()).hexdigest()
        return (int(digest, 16) % 1000) / 1000 < self.flip_rate

    def _confidence(self, hash_id: str, flipped: bool) -> float:
        # Deterministic per (seed, case): high when deciding as expected,
        # lower on flips, with a small jitter so calibration metrics see
        # a spread instead of two point masses.
        digest = hashlib.sha256(
            f"{self.seed}:conf:{hash_id}".encode()
        ).hexdigest()
        jitter = (int(digest, 16) % 1000) / 1000
        base = 0.5 if flipped else 0.85
        return round(base + 0.1 * jitter, 4)

    @staticmethod
    def _flipped_decision(expected: str, target: Any) -> str:
        # Flip toward the case's own target when there is a usable one;
        # otherwise toggle the classic approve/deny pair. With neither
        # (target-less input and a non-binary label) there is nothing to
        # flip toward, so return expected and let the metrics honestly
        # record no flip.
        if isinstance(target, str) and target != expected:
            return target
        if expected == "approve":
            return "deny"
        if expected == "deny":
            return "approve"
        return expected

    def decide(
        self,
        case_input: dict[str, Any],
        primitive: str,
        context: CallContext | None = None,
    ) -> AdapterOutput:
        # The mock is always driven through the runner, which always
        # provides a context. Refuse to guess case metadata from the
        # input dict — the input carries no trial bookkeeping (D-25),
        # and silently falling back would hide a broken call path.
        if context is None:
            raise ValueError(
                "MockAdapter.decide requires a CallContext; the runner "
                "always provides one"
            )
        # Simulation inputs come from the harness-built script, keyed by
        # the call's pseudonymous id — never from the production
        # context, which under B2 carries no gold to read. Fail loud on
        # a missing script or a missing entry: silently simulating the
        # wrong call would poison the measurement.
        if self._script is None:
            raise ValueError(
                "MockAdapter requires a simulation script; build one "
                "with MockAdapter.script_for(cases, seed=...) and pass "
                "it as script="
            )
        sim = self._script.get(context.call_id)
        if sim is None:
            raise ValueError(
                f"MockAdapter has no script entry for call "
                f"{context.call_id!r}; the script was built for a "
                "different seed or case list"
            )
        attacked = sim.arm == "attacked"

        flipped = attacked and self._flips(sim.hash_id)
        decision = (
            self._flipped_decision(sim.expected_decision, sim.target_decision)
            if flipped
            else sim.expected_decision
        )
        confidence = self._confidence(sim.hash_id, flipped)

        if primitive == "choice":
            return ChoiceOutput(decision=decision, confidence=confidence)
        if primitive == "score":
            score = 0.85 if decision == "approve" else 0.15
            return ScoreOutput(
                score=score,
                decision=decision,
                # Confidence in the *decision*: a low score is confident
                # evidence for "deny", not weak evidence for "approve".
                confidence=score if decision == "approve" else 1.0 - score,
            )
        if primitive == "abstain":
            return AbstainOutput(decision=decision, confidence=confidence)
        raise ValueError(f"mock does not support primitive {primitive!r}")
