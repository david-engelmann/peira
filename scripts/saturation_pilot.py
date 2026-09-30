#!/usr/bin/env python3
"""C-10 saturation pilot: run the D-37 policy over the v1 family inventory.

No official adapter runs exist yet (the perfection gate is closed), so
this pilot exercises the saturation machinery on the REAL v1 case
inventory (family ids and case ids from dataset/v1/cases.jsonl) with
SYNTHETIC adapter behavior: four mock adapters whose per-family target
ASRs are disclosed below and fixed by seed. The point of the pilot is
to validate the classification machinery and show what the report
looks like, not to claim any family is actually saturated.

The per-family target table is deliberately constructed to exercise
all four saturation states across the ten v1 families:

- discriminating: adapters spread out (resolvable pairs exist)
- exhausted: all adapters near zero (identical patterns, one seed)
- uniform_failure: all adapters mid-range (identical patterns)
- ceiling_saturated: all adapters near one (identical patterns)

Usage:
    python3 scripts/saturation_pilot.py            # write the report
    python3 scripts/saturation_pilot.py --json OUT # also write raw JSON

Outputs (repo-relative):
    docs/saturation-pilot-report.md
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "python"))

from peira.metrics import CallRecord, PerCaseResult  # noqa: E402
from peira.saturation import (  # noqa: E402
    ACTION_REAUTHOR_HARDER,
    ACTION_RETIRE_CANDIDATE,
    saturation_analysis,
)

# adapter -> family -> target ASR. Families sharing one seed get
# identical per-case patterns (zero inter-adapter gap by construction).
ADAPTERS = ["frontier-strong", "mid-a", "mid-b", "weak"]
TARGETS: dict[str, dict[str, float]] = {
    "confidence_spoofing": {
        "frontier-strong": 0.05, "mid-a": 0.25, "mid-b": 0.30,
        "weak": 0.60,
    },
    "criteria_smuggling": {
        "frontier-strong": 0.10, "mid-a": 0.20, "mid-b": 0.45,
        "weak": 0.55,
    },
    "distractor_flooding": {
        "frontier-strong": 0.01, "mid-a": 0.01, "mid-b": 0.01,
        "weak": 0.01,
    },
    "indirection": {
        "frontier-strong": 0.50, "mid-a": 0.50, "mid-b": 0.50,
        "weak": 0.50,
    },
    "literal_reading": {
        "frontier-strong": 0.15, "mid-a": 0.35, "mid-b": 0.40,
        "weak": 0.65,
    },
    "negation_games": {
        "frontier-strong": 0.55, "mid-a": 0.55, "mid-b": 0.55,
        "weak": 0.55,
    },
    "option_order": {
        "frontier-strong": 0.005, "mid-a": 0.005, "mid-b": 0.005,
        "weak": 0.005,
    },
    "policy_paraphrase": {
        "frontier-strong": 0.08, "mid-a": 0.30, "mid-b": 0.32,
        "weak": 0.58,
    },
    "score_anchoring": {
        "frontier-strong": 0.995, "mid-a": 0.995, "mid-b": 0.995,
        "weak": 0.995,
    },
    "state_poisoning": {
        "frontier-strong": 0.12, "mid-a": 0.28, "mid-b": 0.50,
        "weak": 0.62,
    },
}
# Families whose adapters share one seed (identical flip patterns).
SHARED_SEED_FAMILIES = {
    "distractor_flooding": 101,
    "indirection": 102,
    "negation_games": 103,
    "option_order": 104,
    "score_anchoring": 105,
}
def _stable_seed(*parts: str) -> int:
    """Deterministic seed from string parts.

    Python's ``hash()`` is salted per process (PYTHONHASHSEED), so it
    must never feed a seed when reproducibility is claimed. MD5 is
    stable across runs; it is a seed mixer here, not security.
    """
    h = hashlib.md5("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(h[:8], "little")


def _rec(decision: str) -> CallRecord:
    return CallRecord(
        decision=decision,
        confidence=0.9,
        abstained=False,
        refusal_reason="",
        usage=None,
        seed=0,
        dispatch_index=0,
        malformed=False,
    )


def load_case_ids() -> dict[str, list[str]]:
    by_family: dict[str, list[str]] = {}
    with open(REPO_ROOT / "dataset" / "v1" / "cases.jsonl",
              encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            by_family.setdefault(d["family"], []).append(d["case_id"])
    return by_family


def build_results(case_ids: dict[str, list[str]]
                  ) -> dict[str, list[PerCaseResult]]:
    runs: dict[str, list[PerCaseResult]] = {a: [] for a in ADAPTERS}
    for fam, ids in case_ids.items():
        if fam not in TARGETS:
            continue
        shared_seed = SHARED_SEED_FAMILIES.get(fam)
        # Shared-seed families draw ONE uniform per case; each adapter
        # flips when the draw falls below its target. Patterns are
        # nested and identical-draw, so inter-adapter gaps are pure
        # threshold effects. Other families draw independently per
        # adapter (per-adapter seeds).
        uniforms: dict[str, list[float]] = {}
        if shared_seed is not None:
            rng = random.Random(shared_seed)
            uniforms["_shared"] = [rng.random() for _ in ids]
        for adapter in ADAPTERS:
            if shared_seed is not None:
                draws = uniforms["_shared"]
            else:
                rng = random.Random(_stable_seed(adapter, fam))
                draws = [rng.random() for _ in ids]
            target = TARGETS[fam][adapter]
            for cid, u in zip(ids, draws):
                flipped = u < target
                runs[adapter].append(PerCaseResult(
                    case_id=cid,
                    family=fam,
                    severity="high",
                    primitive="choice",
                    benign=_rec("approve"),
                    attacked=_rec("deny" if flipped else "approve"),
                    flipped=flipped,
                    eligible=True,
                ))
    return runs


def render_markdown(analysis: dict) -> str:
    p = analysis["policy"]
    lines = [
        "# C-10 saturation pilot report",
        "",
        "Methodology pilot for the D-37 per-family saturation/retirement",
        "policy (`peira saturation`). No official adapter runs exist yet,",
        "so this pilot runs the real v1 case inventory (10 families x 200",
        "cases from `dataset/v1/cases.jsonl`) with SYNTHETIC adapter",
        "behavior: four mock adapters with disclosed per-family target",
        "ASRs (see `scripts/saturation_pilot.py`, fully seeded and",
        "reproducible). Nothing below is a claim about any real family.",
        "",
        "Policy echoed from the analysis: "
        f"floor {p['floor_threshold']}, ceiling {p['ceiling_threshold']}, "
        f"retirement after {p['retirement_releases']} consecutive "
        f"releases; variant-flip {p['variant_flip']}.",
        "",
        "## Closest to retirement",
        "",
        "| Family | State | Action | Resolvable pairs | Spread |",
        "|---|---|---|---|---|",
    ]
    for fam in analysis["closest_to_retirement"]:
        d = analysis["per_family"][fam]
        lines.append(
            f"| {fam} | {d['state']} | {d['action']} | "
            f"{d['resolvable_pairs']}/{d['total_pairs']} | "
            f"{d['spread']:.3f} |"
        )
    lines += [
        "",
        "## Per-adapter family ASR (Wilson 95%)",
        "",
        "| Family | " + " | ".join(ADAPTERS) + " |",
        "|---|---|---|---|---|",
    ]
    for fam in analysis["families"]:
        d = analysis["per_family"][fam]
        cells = []
        for ad in d["adapters"]:
            cells.append(
                f"{ad['asr']:.3f} [{ad['ci_lo']:.3f}, {ad['ci_hi']:.3f}]"
            )
        lines.append(f"| {fam} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Reading",
        "",
        "- `distractor_flooding` and `option_order` classify `exhausted`:",
        "  every adapter CI sits below the 0.05 floor with zero resolvable",
        "  pairs. They set the per-release exhaustion trigger; retirement",
        "  eligibility needs a second consecutive release plus the",
        "  variant-flip check (M-8), so nothing is eligible yet.",
        "- `score_anchoring` classifies `ceiling_saturated`: attacks",
        "  succeed on everyone. Action is harder variants, not retirement.",
        "- `indirection` and `negation_games` classify `uniform_failure`:",
        "  attacks work, but the families cannot rank adapters. Action is",
        "  harder variants.",
        "- The remaining five families discriminate: at least one adapter",
        "  pair resolves beyond the paired MDE.",
        "",
        "## Caveats",
        "",
        "- Adapter behavior is synthetic and disclosed; real runs may",
        "  classify every family `discriminating`.",
        "- One release observed: `releases_observed=1`, two required.",
        "- Variant-flip unmeasured: `exhausted` is a candidate, never an",
        "  automatic retirement.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", default=None,
                    help="also write the raw analysis JSON here")
    args = ap.parse_args()

    case_ids = load_case_ids()
    runs = build_results(case_ids)
    families = sorted(TARGETS)
    analysis = saturation_analysis(runs, families)

    out_md = REPO_ROOT / "docs" / "saturation-pilot-report.md"
    out_md.write_text(render_markdown(analysis), encoding="utf-8")
    print(f"pilot report: {out_md}")
    if args.json:
        out = Path(args.json)
        out.write_text(json.dumps(analysis, indent=2), encoding="utf-8")
        print(f"pilot JSON: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
