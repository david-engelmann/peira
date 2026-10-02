"""Property-based tests for peira's invariant layer (P-7 of the decant audit).

Encodes the invariants the methodology *claims* rather than re-asserting
examples:

- Validator totality: arbitrary bytes as case JSON never crash
  ``peira.schema.validate_case_dict`` -- only typed diagnostics (a list
  of error strings), never an unhandled exception.
- Determinism: gate and score functions evaluated twice on the same input
  produce equal output (the ``docs/Execution-Contract.md`` claim that
  decisions, scores, and metric values are pure functions of their
  inputs).
- Ingest idempotence: scanning the runs registry twice yields the same
  rows; loading the dataset twice yields the same cases.
- Query totality: ``peira.runs_registry.query_cases`` stays total on
  adversarial filter input (SQL metacharacters, unicode, control chars).

Written against the Python SDK, which dispatches to the compiled Rust
core when it is installed and falls back to the pure-Python reference
otherwise -- so both backends are covered by the same properties.

Run with: python -m pytest tests/test_invariant_properties.py
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from hypothesis import HealthCheck, given, settings, strategies as st

from peira import gates, metrics, runs_registry
from peira.runner import load_cases
from peira.schema import validate_case_dict

REPO_ROOT = Path(__file__).resolve().parents[1]
DEMO_SUITE = REPO_ROOT / "dataset" / "trial-demo"

# hypothesis runs are CPU-bound, not timing-bound: the repo's per-test
# timeout (not a per-example deadline) is the hang guard.
NO_DEADLINE = settings(deadline=None)

# Adversarial text for filter/query surfaces: quotes, SQL keywords,
# unicode, control chars. NUL is excluded (rejected by the sqlite driver
# itself, below peira's layer) and lone surrogates are excluded
# (unencodable). Classic injection payloads are mixed in explicitly.
_adversarial_alphabet = st.characters(
    blacklist_categories=("Cs",), blacklist_characters="\x00"
)
adversarial_text = st.text(alphabet=_adversarial_alphabet, max_size=64)
query_text = st.one_of(
    adversarial_text,
    st.sampled_from(
        [
            "'; DROP TABLE runs; --",
            '" OR "1"="1',
            "%_[]",
            "\n\r\t",
            "Robert'); DROP TABLE students;--",
        ]
    ),
)

# Arbitrary JSON values, serialized to bytes: the "arbitrary bytes as case
# JSON" input for the validator-totality property.
_json_scalars = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=True, allow_infinity=True),
    st.text(max_size=32),
)
json_values = st.recursive(
    _json_scalars,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=16), children, max_size=4),
    ),
    max_leaves=25,
)
case_json_bytes = st.one_of(
    st.binary(max_size=512),
    json_values.map(lambda v: json.dumps(v, allow_nan=True).encode("utf-8")),
)


def _variant_dict():
    return st.fixed_dictionaries(
        {
            "input": st.fixed_dictionaries(
                {
                    "options": st.lists(
                        st.text(min_size=1, max_size=12),
                        min_size=1,
                        max_size=5,
                    ),
                    "prompt": st.text(max_size=64),
                }
            )
        }
    )


# Shape-valid case dicts: what the authoring gates are documented to run
# on (peira.gates.run_gates takes schema-valid cases).
case_dicts = st.fixed_dictionaries(
    {
        "case_id": st.text(min_size=1, max_size=24),
        "benign": _variant_dict(),
        "attacked": _variant_dict(),
    }
)


class TestValidatorTotality(unittest.TestCase):
    """peira.schema.validate_case_dict is total on arbitrary bytes."""

    @NO_DEADLINE
    @given(case_json_bytes)
    def test_arbitrary_bytes_never_crash_validator(self, payload):
        try:
            parsed = json.loads(payload)
        except (ValueError, RecursionError):
            # Not decodable JSON: the JSON layer's typed-diagnostic path,
            # not the validator's concern.
            return
        errors = validate_case_dict(parsed)
        self.assertIsInstance(errors, list)
        for error in errors:
            self.assertIsInstance(error, str)


class TestDeterminism(unittest.TestCase):
    """Gate/score functions evaluated twice give equal output."""

    @NO_DEADLINE
    @given(st.lists(case_dicts, min_size=1, max_size=12))
    def test_gates_deterministic(self, dicts):
        valid_cases = [
            (Path("prop.jsonl"), i + 1, d) for i, d in enumerate(dicts)
        ]
        for gate in (gates.gate_dedup, gates.gate_paired_variants):
            first = gate(valid_cases)
            second = gate(valid_cases)
            # Full GateResult equality, not just (errors, warnings): the
            # determinism claim covers the whole result object.
            self.assertEqual(first, second)

    @NO_DEADLINE
    @given(
        st.tuples(st.integers(0, 10_000), st.integers(0, 10_000)).map(
            lambda pair: (min(pair), max(pair))
        )
    )
    def test_wilson_ci_deterministic(self, hits_n):
        hits, n = hits_n
        first = metrics.wilson_ci(hits, n)
        second = metrics.wilson_ci(hits, n)
        self.assertEqual(first, second)
        # Non-vacuous properties of the interval itself, so the test has
        # teeth beyond determinism: bounds stay in [0, 1], the point
        # estimate sits inside the interval, and the interval is sane at
        # the edges (n=0 degrades gracefully, hits=n hits the top).
        lo, hi = first
        self.assertLessEqual(0.0, lo)
        self.assertLessEqual(lo, hi)
        self.assertLessEqual(hi, 1.0)
        if n > 0:
            # Epsilon-tolerant: at the hits=n extreme the Wilson upper
            # bound can sit ~1ulp below the point estimate in
            # floating-point (0.9999999999999999 vs 1.0); that is
            # arithmetic, not a broken interval.
            eps = 1e-9
            self.assertLessEqual(lo, hits / n + eps)
            self.assertLessEqual(hits / n - eps, hi)

    @NO_DEADLINE
    @given(st.integers(1, 10_000))
    def test_wilson_ci_monotone_in_hits(self, n):
        # More hits at fixed n must not lower the interval: a real
        # mathematical property a broken wilson_ci (e.g. a swapped
        # argument order in a rewrite) would violate.
        lo_a, _ = metrics.wilson_ci(0, n)
        lo_b, _ = metrics.wilson_ci(n, n)
        self.assertLessEqual(lo_a, lo_b)


class _RegistryTestCase(unittest.TestCase):
    """Per-test scratch runs dir (xdist-safe: unique per worker/test)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.runs_dir = Path(self._tmp.name)

    def _index_rows(self):
        db_path = self.runs_dir / "index.db"
        conn = sqlite3.connect(db_path)
        try:
            runs = conn.execute(
                "SELECT * FROM runs ORDER BY run_id"
            ).fetchall()
            case_results = conn.execute(
                "SELECT * FROM case_results ORDER BY run_path, case_id"
            ).fetchall()
            return runs, case_results
        finally:
            conn.close()


class TestIngestIdempotence(_RegistryTestCase):
    """Syncing/loading twice yields the same rows."""

    @settings(
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
        max_examples=30,
    )
    @given(st.lists(adversarial_text, min_size=1, max_size=5))
    def test_scan_runs_twice_same_rows(self, adapter_names):
        for i, name in enumerate(adapter_names):
            artifact = {
                "peira_version": "0.0.0-test",
                "dataset_version": "v1",
                "adapter_name": name,
                "suite": "prop",
                "results": [
                    {"case_id": f"case-{i}", "family": name},
                ],
            }
            (self.runs_dir / f"run-{i}.json").write_text(
                json.dumps(artifact, allow_nan=False), encoding="utf-8"
            )
        first_count = runs_registry.scan_runs(self.runs_dir)
        first_rows = self._index_rows()
        second_count = runs_registry.scan_runs(self.runs_dir)
        second_rows = self._index_rows()
        self.assertEqual(first_count, second_count)
        self.assertEqual(first_rows, second_rows)

    def test_load_cases_twice_same_rows(self):
        first = [case.to_dict() for case in load_cases(DEMO_SUITE)]
        second = [case.to_dict() for case in load_cases(DEMO_SUITE)]
        self.assertGreater(len(first), 0)
        self.assertEqual(first, second)


class TestQueryTotality(_RegistryTestCase):
    """peira.runs_registry.query_cases is total on adversarial filters."""

    @settings(deadline=None, suppress_health_check=[HealthCheck.too_slow])
    @given(
        adapter=query_text,
        suite=query_text,
        family=query_text,
        severity=query_text,
        flip_direction=query_text,
        min_confidence=st.floats(min_value=0.0, max_value=1.0),
        max_confidence=st.floats(min_value=0.0, max_value=1.0),
        limit=st.integers(0, 50),
        seed_family=query_text,
    )
    def test_query_cases_never_raises(
        self,
        adapter,
        suite,
        family,
        severity,
        flip_direction,
        min_confidence,
        max_confidence,
        limit,
        seed_family,
    ):
        # Seed one artifact so the query path exercises real row shaping,
        # with an adversarial family string in the stored data too.
        artifact = {
            "peira_version": "0.0.0-test",
            "dataset_version": "v1",
            "adapter_name": "prop-adapter",
            "suite": "prop",
            "results": [{"case_id": "case-0", "family": seed_family}],
        }
        (self.runs_dir / "run-0.json").write_text(
            json.dumps(artifact, allow_nan=False), encoding="utf-8"
        )
        rows = runs_registry.query_cases(
            runs_dir=self.runs_dir,
            adapter=adapter,
            suite=suite,
            family=family,
            severity=severity,
            flip_direction=flip_direction,
            min_attacked_confidence=min_confidence,
            max_attacked_confidence=max_confidence,
            limit=limit,
        )
        self.assertIsInstance(rows, list)
        for row in rows:
            self.assertIsInstance(row, dict)


if __name__ == "__main__":
    unittest.main()
