# Re-review of post-review fixes: PR #189 (C-1 Stuart-Maxwell) delta

Scope: uncommitted changes in `~/workspace/peira-189-gate` (branch
`c1-stuart-maxwell`) versus committed HEAD `01aa8c7`, covering
`python/peira/metrics.py`, `tests/test_stuart_maxwell.py`,
`docs/Flip-Direction.md`, `docs/Methodology.md`. Two full reviews
(`REVIEWS/redteam-189.md`, `REVIEWS/linereview-189.md`) ran first;
this covers only the fixes applied after them.

Note: the delta is larger than the six listed items. It also contains
a refactor of `_stuart_maxwell_stat_py` into `_stuart_maxwell_component`
(connected components over off-diagonal adjacency, diagonal-only
categories dropped as uninformative). That refactor was reviewed here
too.

## Test run

`cd ~/workspace/peira-189-gate && PYTHONPATH=$PWD/python PEIRA_NO_RUST=1
python3 -m unittest tests.test_stuart_maxwell` -- **26/26 pass.**

## Fix-by-fix verification

### 1. Off-diagonal withholding floor -- OK, R-07-consistent

`stuart_maxwell_p_value` now computes
`n_discordant = sum(table[c][o] for c in cats for o in cats if o != c)`
and withholds iff that is < 10 (`metrics.py:6720`).

- Verified the 2-category reduction triggers **iff b+c<10** across
  boundary cases (1,1),(4,5),(0,9),(5,5),(6,6),(9,10), and that the
  non-withheld p-value equals the McNemar chi-square path
  `chi2.sf((b-c)^2/(b+c), 1)` exactly.
- Diagonal mass should never count: diagonal entries cancel out of the
  SM statistic entirely (d_i = row_i - col_i unchanged;
  V_ii = row_i + col_i - 2*n_ii subtracts the diagonal back out), so
  they are genuinely ancillary to the test, not just a convention.
  The docstring's rationale is correct, and no table exists where
  diagonal mass would legitimately need to count.
- Doc wording consistent across `Flip-Direction.md` ("fewer than 10
  discordant flips"), `Methodology.md` ("Withheld below 10 discordant
  flips"), and the docstring ("fewer than 10 discordant (off-diagonal)
  flips").

### 2. `_chi2_sf_py` df<1 guard -- OK, and it fixes a real crash

Guard `if df < 1: return 1.0` is the first check
(`metrics.py:6642`). Verified against the HEAD version: the old code
called as `_chi2_sf_py(5.0, 0)` **raised `ValueError: math domain
error`** (falls into the continued-fraction branch with a=0, hits
`math.log(0)`), so the task's question is answered yes -- there was a
real raise path for df<1 with stat>0, reachable by direct callers.
The new guard closes it.

Placement is correct: it precedes the `stat <= 0` and `df == 1`
branches, and `stuart_maxwell_p_value` independently returns 1.0 on
df<1 before calling it, so the two guards are consistent. Minor
leniency note (not a finding): a negative df (caller bug) now
silently returns 1.0 instead of raising; acceptable for a private
helper.

### 3. Vocabulary validation in `stuart_maxwell` -- OK

Unknown keys raise `ValueError` with a sorted key list
(`metrics.py:6618`); square-shape and non-negativity checks unchanged.
Verified: subsets of the six categories are accepted and return
identical results under reversed dict insertion order (the internal
`[c for c in DIRECTION_CATEGORIES if c in table]` filter keeps
ordering canonical -- no interaction bug). `"none"` key is rejected.

### 4. Duplicate case_id rejection in `direction_square_table` -- OK

Raises on duplicates within `results_a` and within `results_b`
separately (`metrics.py:6458`); the cross-list same-id requirement is
untouched, so the legitimate matching case raises nothing. No false
positive: the checks are strictly intra-list.

### 5. Connected-component refactor (unlisted in the fix summary) -- OK

- Diagonal-only categories are now excluded as uninformative. This is
  a deliberate df change versus HEAD (old code counted them as live
  categories, inflating df by 1 without any effect on the statistic),
  and the new behavior is strictly more correct.
- The component solve's "row/column sums are exact" claim holds:
  cross-component off-diagonal pairs are zero by construction, and
  diagonal-only categories contribute zero off-diagonal, so summing
  over `comp` equals summing over all categories.
- Cross-validated against an independent `scipy.linalg.solve`
  reference implementation: exact agreement (1e-9) on the test's
  frozen table (stat 2.923076923077, df 2, p 0.231879262848 -- the
  frozen reference values in `test_known_value_fixed_reference` are
  confirmed correct against scipy 1.11.4) and on 300 randomized
  connected tables.
- 2-category single components reduce exactly to McNemar
  (`test_disconnected_components_sum` pins the additive case).

### 6. Tests -- OK

New tests (`test_diagonal_mass_does_not_count_toward_floor`,
`test_duplicate_case_ids_raise`, `test_unknown_categories_raise`,
`test_chi2_sf_zero_df`) all target the fixed behaviors and pass.
`test_holds_when_marginals_match` now uses 12 discordant flips,
correctly clearing the floor. The scipy-dependent tests were replaced
with frozen references whose provenance comment cites scipy 1.11.4 --
the frozen values were independently re-verified above, so this is
not trust-me data.

### 7. Doc wording (colons / semicolons / em dashes) -- OK

Python codepoint scan (U+2014, U+2013, U+003A, U+003B) over all added
lines in the docs diff: **zero hits**. The doc rewrite also removed
pre-existing colons (e.g. `## C-1:` heading, bullet-list colons).

## Findings

No new findings. All six listed fixes and the unlisted
connected-component refactor verify clean against independent
re-implementation.
