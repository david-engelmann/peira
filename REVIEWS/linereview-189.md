# Line-by-line diff review: PR #189 (C-1 Stuart-Maxwell)

Reviewed: `git diff 7ced5cab8a8687685e2fed7ea5062e25e1759726` against the
working tree (PR head `01aa8c7d` **plus** the uncommitted CodeRabbit repair
changes). Files: `python/peira/metrics.py`, `tests/test_stuart_maxwell.py`,
`docs/Flip-Direction.md`, `docs/Methodology.md`.

## Method

- Read every changed line; traced the math by hand and re-verified with an
  independent exact-arithmetic implementation (`Fraction`-based Gaussian
  elimination, independent BFS) over 2000 randomized tables: **zero
  mismatches** in statistic or df, and the no-cross-component-mass
  invariant held on all 2000 tables.
- Ran the test suite: 22/22 pass
  (`PYTHONPATH=python python3 -m unittest tests.test_stuart_maxwell`).
- Cross-validated every frozen reference against scipy 1.11.4 (the version
  the tests cite; scipy is used here only as an oracle, it remains absent
  from the code).

## Verdict

No P0/P1. The math is correct, the Gaussian elimination is sound, the BFS
partition is exact, the frozen references check out, and all four named
CodeRabbit repairs are complete. Findings are P2/P3 only.

### Verification results (all green)

1. **Stuart-Maxwell formula** (`_stuart_maxwell_component`, metrics.py:6481):
   `d_i = row_i - col_i` on the first k-1 categories, `V_ii = row_i + col_i
   - 2*n_ii`, `V_ij = -(n_ij + n_ji)` matches the standard Stuart-Maxwell
   form; stat = d' V^-1 d. Frozen table stat = 342/117 = 2.9230769230769...,
   test asserts 2.923076923077 (places=9): exact match.
2. **McNemar reduction**: for a 2-category component the code computes
   (n12-n21)^2/(n12+n21) exactly; asserted by tests and confirmed by hand.
3. **Gaussian elimination** (metrics.py:6526-6541): Gauss-Jordan with partial
   pivoting. Pivot search covers rows `col..m-1` (includes the current row),
   swap is correct, elimination covers all `r != col` starting the inner
   loop at `c2 = col` (entries left of col are already zero), RHS is
   `aug[i][m]`. Pivot `< 1e-12` raises before any division. Additionally,
   for a connected component V is exactly the weighted graph Laplacian of
   the off-diagonal adjacency, whose (k-1)x(k-1) principal submatrix is
   positive definite, so the singular-pivot `ValueError` is unreachable
   defensive code, not a live path.
4. **Connected-components partition** (`_stuart_maxwell_stat_py`,
   metrics.py:6540): BFS marks `seen` at discovery (no double-visit, no
   missed adjacency), scans all informative categories per pop, so every
   adjacency edge is covered and no component can be split. The
   component-local row/column sums are exact: if `c` in a component had
   off-diagonal mass with `o` outside it, `o` would be informative and
   adjacent, hence in the same component (verified as an assertion over
   2000 random tables). Diagonal-only categories are correctly excluded;
   a singleton informative category is impossible, so the `len(comp) >= 2`
   guard is harmless dead code.
5. **Frozen references**: p = 0.231879262848 == `scipy.stats.chi2.sf(stat,
   2)` to the digit; all 12 `_chi2_sf_py` refs match scipy to 4.3e-13; a
   wider grid (df 1..30, stat 0.01..100) matches scipy to 3.2e-15.
   df=1 `erfc(sqrt(stat/2))` path is the correct chi-square(1) survival.
6. **CodeRabbit repair completeness**:
   - Docs colons: zero colons remain in the new C-1 sections of both docs
     (verified by scan; remaining colons in Flip-Direction.md are in
     pre-existing sections).
   - Contradictory comment ("at least one adapter flipped" vs both-flip
     code): fixed to "both adapters flipped" (metrics.py:6418).
   - Diagonal-only/disconnected singularity: fixed via informative-filter
     + connected-components partition; old `ValueError` on <2 live
     categories replaced by the documented `(0.0, 0)` contract, and both
     docstrings (`stuart_maxwell`, `_stuart_maxwell_stat_py`) plus
     Flip-Direction.md describe the new contract accurately.
   - Undeclared scipy in tests: removed; frozen refs + version-pinned
     comments in place.

## Findings

### P2

**P2-1 (tests/test_stuart_maxwell.py:281) — `_chi2_sf_py` has no guard for
df=0 on direct calls.** `stuart_maxwell_p_value` guards with `if df < 1:
return 1.0`, but a direct `_chi2_sf_py(stat, 0)` with `stat > 0` hits
`total = 1.0 / a` with `a = 0.0` and raises `ZeroDivisionError`. The
function is private and all current callers are guarded, so this is
latent only. Fix suggestion: add `if df < 1: return 1.0` at the top of
`_chi2_sf_py` (mirrors the caller guard; also covers negative df).

### P3

**P3-1 (metrics.py:6455) — `direction_square_table` silently collapses
duplicate case_ids in `results_b`.** `by_id_b = {r.case_id: r ...}` keeps
only the last duplicate, and the set-equality check cannot detect
duplicates, so a caller bug (same case twice) is silently masked while
`results_a` duplicates would double-count. Fix suggestion: assert
`len(by_id_b) == len(results_b)` (and same for `results_a`) before the
set comparison.

**P3-2 (metrics.py:6573-6578) — `stuart_maxwell` validates squareness over
all keys but `_stuart_maxwell_stat_py` silently drops keys outside
`DIRECTION_CATEGORIES`.** E.g. a 7x7 table including `"none"` passes
validation, then the `"none"` row/column mass vanishes without warning.
Fix suggestion: reject keys not in `DIRECTION_CATEGORIES` with
`ValueError` in `stuart_maxwell` (one line: `if set(cats) -
set(DIRECTION_CATEGORIES): raise ValueError(...)`), or document the
drop in the docstring.

**P3-3 (tests/test_stuart_maxwell.py:60) — stale editing artifact in a
comment.** `# Adapter B: approve -> approve... no flip. Use abstain
instead.` reads like a mid-edit note; B's arm is approve-benign /
abstained-attacked throughout. Fix suggestion: rewrite as `# Adapter B:
approve -> abstain (to-abstain).`.

**P3-4 (metrics.py:6522-6524) — degenerate-case comment says "diagonal
component" but the check is `all(d == 0)`.** A component can have all-zero
marginal differences without being diagonal (e.g. symmetric off-diagonal
pairs, as in `test_holds_when_marginals_match`), and the early return is
correct for all such cases. The comment is narrower than the code but not
wrong. Fix suggestion: "Degenerate case: all marginal differences are
zero (e.g. a diagonal or symmetric component)."

## Non-findings (checked, deliberately not raised)

- Summing component statistics/df assumes the subproblems are independent;
  this is the standard treatment for tables with zero-mass category
  blocks (dropping them is what the pre-repair code did too, just without
  handling the disconnected case), and the docstring states the
  asymptotic claim plainly.
- `max(0.0, stat)`: stat is mathematically non-negative; the clamp only
  absorbs float noise. Fine.
- `1e-12` tolerances: `d` entries are integer-valued, so the degenerate
  check is exact in practice; the pivot threshold cannot false-trigger on
  legitimate integer-count pivots at these table sizes.
- Test `test_known_value_fixed_reference` asserting `df == 2` exactly and
  stat/p to 9/6 places is a genuine computation check, not vacuous; the
  end-to-end test asserts `p < 0.001` on a real 30-count off-diagonal
  table (stat = 30.0, df = 1). No vacuous tests found.
- Style matches surrounding conventions (type hints, `:func:`/`:data:`
  docstring roles, snake_case, module section banners).
