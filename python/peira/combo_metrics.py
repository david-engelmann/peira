"""Interaction-contrast metrics for the combo suite.

The 2x2 factorial unit gives, per substrate i, four binary outcomes on the
registered primary outcome (flip / abstain / joint):

    Y_i(ctrl), Y_i(a), Y_i(b), Y_i(ab)

The per-substrate interaction contrast is::

    d_i = Y_i(ab) - Y_i(a) - Y_i(b) + Y_i(ctrl)

and the pair-level interaction estimate is the mean of d_i over the n
substrates. Because all four arms derive from the same substrate, the
d_i are i.i.d. draws and the variance of the mean is estimated directly
from the sample variance of d_i -- this is the paired analysis the
design (section 6d, review P2-1) requires. It is strictly tighter than
the independent-arms variance (sum of four arm-rate variances) whenever
the arms are positively correlated within substrate, which they are by
construction (same benign facts, same decision).

Classification (design 4a preamble, 6a):

    interaction > 0, CI excludes 0  -> super-additive (synergy)
    CI includes 0, MDE met          -> additive (independent)
    interaction < 0, CI excludes 0  -> sub-additive (redundancy/masking)
    MDE not met                     -> unresolved ("not resolvable at this n")

The MDE for the interaction contrast at 80% power, two-sided alpha 0.05,
is approximately::

    MDE ~= 2.8 * sqrt(var(d) / n)

where var(d) is the sample variance of the per-substrate contrasts.
With no data yet, the conservative independent-arms ceiling
(var(d) <= 4 * 0.25 = 1.0 at moderate base rates, so MDE <= 2.8/sqrt(n))
gives MDE <= 0.28 at n=100 -- the pilot's starting point.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class InteractionResult:
    pair_id: str
    n_substrates: int
    # Arm rates on the primary outcome.
    rate_ctrl: float
    rate_a: float
    rate_b: float
    rate_ab: float
    # Interaction contrast and inference.
    interaction: float
    se: float
    ci_lo: float
    ci_hi: float
    mde_80: float
    classification: str  # "super" | "additive" | "sub" | "unresolved"
    hypothesis: str  # pre-registered prediction from the design
    hypothesis_confirmed: bool | None  # None when unresolved


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _var_sample(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = _mean(xs)
    return sum((x - m) ** 2 for x in xs) / (n - 1)


def paired_interaction(
    outcomes: list[tuple[int, int, int, int]],
    pair_id: str = "",
    hypothesis: str = "",
) -> InteractionResult:
    """Compute the paired interaction contrast.

    ``outcomes`` is a list of (y_ctrl, y_a, y_b, y_ab) binary outcomes,
    one tuple per substrate, on the combo's registered primary outcome.
    """
    n = len(outcomes)
    if n == 0:
        raise ValueError("no substrates")
    d = [ab - a - b + ctrl for ctrl, a, b, ab in outcomes]
    interaction = _mean(d)
    var_d = _var_sample(d)
    se = math.sqrt(var_d / n) if n else 0.0
    # Normal 95% CI; n=100 pilot justifies the normal approximation, and
    # the t critical value at 99 df (1.984) differs negligibly.
    ci_lo = interaction - 1.96 * se
    ci_hi = interaction + 1.96 * se
    # MDE at 80% power, two-sided alpha=0.05: (z_.975 + z_.80) * se.
    mde_80 = (1.96 + 0.84) * se

    if mde_80 > 0.20:
        # Floor not met: cannot resolve even a large interaction.
        classification = "unresolved"
    elif ci_lo > 0:
        classification = "super"
    elif ci_hi < 0:
        classification = "sub"
    else:
        classification = "additive"

    confirmed: bool | None = None
    if classification != "unresolved" and hypothesis:
        confirmed = (classification == hypothesis)

    return InteractionResult(
        pair_id=pair_id,
        n_substrates=n,
        rate_ctrl=_mean([o[0] for o in outcomes]),
        rate_a=_mean([o[1] for o in outcomes]),
        rate_b=_mean([o[2] for o in outcomes]),
        rate_ab=_mean([o[3] for o in outcomes]),
        interaction=interaction,
        se=se,
        ci_lo=ci_lo,
        ci_hi=ci_hi,
        mde_80=mde_80,
        classification=classification,
        hypothesis=hypothesis,
        hypothesis_confirmed=confirmed,
    )


def format_interaction(r: InteractionResult) -> str:
    """One-paragraph human summary of an interaction result."""
    verdict = {
        "super": "SUPER-ADDITIVE (synergy)",
        "additive": "additive (independent)",
        "sub": "SUB-ADDITIVE (redundancy)",
        "unresolved": "UNRESOLVED (not resolvable at this n)",
    }[r.classification]
    s = (
        f"{r.pair_id}: n={r.n_substrates} substrates; arm rates "
        f"ctrl={r.rate_ctrl:.3f} a={r.rate_a:.3f} b={r.rate_b:.3f} "
        f"ab={r.rate_ab:.3f}; interaction={r.interaction:+.3f} "
        f"95% CI [{r.ci_lo:+.3f}, {r.ci_hi:+.3f}], MDE80={r.mde_80:.3f} "
        f"-> {verdict}."
    )
    if r.hypothesis and r.hypothesis_confirmed is not None:
        s += (f" Pre-registered hypothesis '{r.hypothesis}' "
              f"{'CONFIRMED' if r.hypothesis_confirmed else 'REJECTED'}.")
    return s
