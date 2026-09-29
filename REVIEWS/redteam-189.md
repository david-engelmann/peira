# Red-team audit: PR #189 (C-1 Stuart-Maxwell)

**Auditor:** independent red-team (depth-2 subagent). **Date:** 2026-09-29.
**Scope:** `git diff 7ced5cab8a8687685e2fed7ea5062e25e1759726..HEAD` in
`~/workspace/peira-189-gate` (branch `c1-stuart-maxwell`, includes the
uncommitted repair layer on top of PR head `01aa8c7d`). No builder or
coordinator claims were trusted; every check below was re-derived or
re-run independently.

**Method.** Independent numpy reference implementations (textbook
Stuart-Maxwell, `d'V+d` with `df = rank(V)` via SVD pinv), cross-checks
against scipy 1.11.4 (`scipy.stats.chi2.sf`, available in this sandbox but
not a repo dependency), randomized fuzzing (8k tables vs reference, 20k
tables + all 19,683 tiny 3-category tables for crash-hunting), adversarial
hand-built tables, a mechanical scan of new doc lines for banned characters,
and line-by-line reading of the final code state.

**Verdict: 1 P2, 2 P3s. The core statistic is mathematically correct.**
One real defect (withholding floor counts the wrong thing, contradicting the
docstring's own R-07 claim). Two minor robustness gaps. Everything else the
PR claims checked out, including the tricky df accounting across disconnected
components, which I initially suspected and then proved correct.

---

## Findings

### P2 — `stuart_maxwell_p_value` applies the <10 floor to total paired flips, not discordant pairs; contradicts the docstring's R-07 claim

**File:** `python/peira/metrics.py:6686` (`n = sum(sum(row.values()) for row in table.values())`)

**Evidence.** R-07's floor is on discordant pairs (`_mcnemar_p_value_py`,
metrics.py:1004: `n = b + c; if n < 10: return None`). The Stuart-Maxwell
generalization of "discordant pairs" is the **off-diagonal mass**: diagonal
counts cancel out of both `d` (`row_i - col_i`) and `V`
(`V_ii = row_i + col_i - 2*n_ii`, `V_ij = -(n_ij + n_ji)`), so they are
ancillary to the test. But the C-1 floor counts them:

```python
t = {2x2 over ("deny-to-approve","to-abstain"): b=9, c=0, plus 5 diagonal}
stuart_maxwell_p_value(t)  # -> 0.0027 (reported)
mcnemar_p_value(9, 0)      # -> None (R-07 withholds: b+c=9 < 10)
```

The docstring at metrics.py:6676-6679 says the floor exists "mirroring
R-07's <10-discordant withholding floor for McNemar" — the code does not
implement a <10-discordant floor. Consequences:

1. In the exact case where the PR claims "reduces exactly to McNemar," the
   p-value reporting rule disagrees with R-07's McNemar p-value.
2. The floor is gameable by diagonal mass: 1000 diagonal agreements + 2
   discordant flips (verified: `diagonal heavy + thin offdiag` case) gets an
   asymptotic p-value computed from 2 discordant pairs, exactly the regime
   R-07 withholds on.

**Fix.** Count off-diagonal mass, which makes the 2-category reduction
exactly consistent with R-07:

```python
cats = list(table.keys())
n_discordant = sum(table[c][o] for c in cats for o in cats if o != c)
if n_discordant < 10:
    return None
```

Update the docstring/docs wording ("fewer than 10 discordant flips") and add
a distinguishing test (10 total flips with <10 off-diagonal must withhold;
the existing `test_withheld_below_10`/`test_exactly_10_not_withheld` pass
under either rule and would not catch a regression).

*Note (no severity):* with per-component subproblems, one could argue the
floor should apply per component (two components of 6 discordant pairs each
pass a total-10 floor while each component's approximation is thin). R-07 has
no such subdivision, so the simple off-diagonal-total fix above is the
defensible scope; per-component flooring is optional hardening.

### P3 — `stuart_maxwell` silently returns `(0.0, 0)` for tables keyed outside `DIRECTION_CATEGORIES`

**File:** `python/peira/metrics.py:6561`
(`cats = [c for c in DIRECTION_CATEGORIES if c in table]`)

**Evidence.** The public function validates squareness and non-negativity
(loud), but a vocabulary mismatch is silent:

```python
stuart_maxwell({"a": {"a": 3, "b": 1}, "b": {"a": 1, "b": 3}})
# -> (0.0, 0.0), no error; stuart_maxwell_p_value then returns 1.0
```

`(0.0, 0)` reads as "no directional difference" — the most misleading silent
answer for what is really malformed input (e.g. a typo'd category name or a
7x7 table including `"none"`). A superset table (six keys plus extras) is
likewise silently truncated.

**Fix.** Validate the vocabulary loudly, e.g. in `stuart_maxwell`:

```python
unknown = set(cats) - set(DIRECTION_CATEGORIES)
if unknown:
    raise ValueError(f"stuart_maxwell unknown direction categories: {sorted(unknown)}")
```

(A subset of the six still works as a generalized square table and can stay
allowed; the docstring contract is `direction_square_table` output.)

### P3 — `direction_square_table` silently double-counts duplicate `case_id`s in `results_a`

**File:** `python/peira/metrics.py:6458-6465`

**Evidence.** The set-equality check passes with duplicates, and the loop
counts each duplicate row:

```python
ra = [_r("c1"), _r("c1")]; rb = [_r("c1")]
direction_square_table(ra, rb)  # total == 2, pair counted twice
```

(A duplicate in `results_b` is masked by the dict, so A and B can also
silently disagree on multiplicity.)

**Fix.** Reject duplicates up front:

```python
if len({r.case_id for r in results_a}) != len(results_a) or \
        len(by_id_b) != len(results_b):
    raise ValueError("direction_square_table requires unique case_ids")
```

---

## What was verified clean (with evidence)

**1. The statistic is mathematically correct.** I wrote an independent
textbook reference (`d_i = row_i - col_i`, `V_ii = row_i + col_i - 2*n_ii`,
`V_ij = -(n_ij + n_ji)`, statistic `d'V+d`, `df = rank(V)` via SVD pinv) and
fuzzed 8,000 random tables (0-16 cells, counts 1-50, dense and sparse):
**zero mismatches in statistic or df**. The component decomposition
(`df = sum(|comp|-1)`) equals `rank(V)` exactly. (An earlier naive reference
of mine that solved jointly over all informative categories produced a df
mismatch; investigation showed the joint covariance is genuinely
rank-deficient there — each connected component's full Laplacian block is
singular of rank `|comp|-1` — so the repo's per-component df is the correct
generalization, and the docstring's "jointly solving disconnected components
would singularize the covariance matrix" is accurate.)

**2. McNemar reduction is exact.** 200 random two-category tables:
`stat == (b-c)^2/(b+c)`, `df == 1`, to 1e-9. Matches the repo's
`test_reduces_to_mcnemar_for_2x2`.

**3. Frozen reference values independently reproduced.** The
`test_known_value_fixed_reference` table gives `stat = 2.9230769230769234`,
`df = 2` under my numpy reference and `p = 0.23187926284819227` under
scipy 1.11.4 `chi2.sf` — matching the frozen `2.923076923077` /
`0.231879262848` to the asserted precision. `_chi2_sf_py` matched scipy to
<2e-9 across adversarial cases (df 1/2/5, stat 0/0.5/3.84/11.07/20,
negative stat, huge stat).

**4. No singular-covariance crash is reachable.** 20,000 random tables plus
all 19,683 count patterns over a 3-category table (counts 0-2): zero
`ValueError` raises. Reason: for a connected component, `V` is a reduced
graph Laplacian with edge weights `n_ij + n_ji > 0` on a connected graph,
hence positive definite by the Matrix-Tree theorem. The
`"covariance matrix is singular"` raise is unreachable defensive code, which
is fine. Huge counts (1e17, 1e18) compute without overflow and match scipy.

**5. `direction_square_table` edge cases.** Both-flip conditioning (P2-2)
correct: single-sided and neither-flipped pairs excluded; one-sided
ineligibility skipped; mismatched ids raise `ValueError`; reordered inputs
give identical tables; fixed 6x6 shape with zero-filled unobserved cells;
`flip_direction` vocabulary is the seven `FLIP_DIRECTIONS` and `"none"` is
filtered before indexing, so no `KeyError` is possible.

**6. Withholding mechanics (apart from the P2).** `n < 10 -> None`,
`n == 10` computed, `df < 1 -> 1.0` (consistent with R-07's `b+c == 0 -> 1.0`).

**7. Docs match code.** Flip-Direction.md C-1 section: both-flip
conditioning, off-diagonal-mass filter (not marginal mass — the doc wording
matches the code's `sum(table[c][o] + table[o][c] for o != c) > 0` filter
exactly), component summation of stat and df, `(0.0, 0)` fallback, six
categories retained, 2x2-to-McNemar reduction, marginal-homogeneity-not-
Bowker rationale. Methodology.md bullet is consistent. Mechanical scan of
all added doc lines: **zero em dashes, zero semicolons, zero colons**.

**8. No dependency leaks.** No `scipy`/`numpy` imports in `python/peira/` or
`tests/` (only comments); tests import stdlib + `peira` only. The base
tier's zero-third-party-runtime-dependency rule (AGENTS.md) is intact.

**9. David Q1 (never collapse the six categories).** `DIRECTION_CATEGORIES`
has exactly the six, no `"none"`; the table builder never merges keys; the
statistic drops diagonal-only categories from the solve but never merges
distinct categories (verified: stat identical with/without a diagonal-only
category present, and the six remain distinct table keys throughout).

**10. Tests.** All 22 pass against the worktree code. Note: this sandbox has
`peira` pip-installed pointing at a *different* worktree
(`peira-pr2-docs-remainder`), so a bare `python -m pytest` from the worktree
imports the wrong package (collection error observed); I ran with
`PYTHONPATH=<worktree>/python`. That is an environment quirk, not a repo
defect — but the gate runner should ensure the tested package is the
worktree's (CI installs from the checkout, so it is fine there).

## Suggested follow-ups for the parent

- Apply the P2 fix (off-diagonal floor) and the two P3 fixes, then re-run
  the three-review gate; the existing tests will need one new distinguishing
  test for the floor semantics.
- The full `tests/test_metrics.py` regression run was still going when this
  report was written (slow suite); the C-1 change is purely additive at end
  of file, but the gate should confirm the suite is green before merge.
