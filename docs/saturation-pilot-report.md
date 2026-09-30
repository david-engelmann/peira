# C-10 saturation pilot report

Methodology pilot for the D-37 per-family saturation/retirement
policy (`peira saturation`). No official adapter runs exist yet,
so this pilot runs the real v1 case inventory (10 families x 200
cases from `dataset/v1/cases.jsonl`) with SYNTHETIC adapter
behavior: four mock adapters with disclosed per-family target
ASRs (see `scripts/saturation_pilot.py`, fully seeded and
reproducible). Nothing below is a claim about any real family.

Policy echoed from the analysis: floor 0.05, ceiling 0.95, retirement after 2 consecutive releases; variant-flip not yet measured; M-8 follow-up.

## Closest to retirement

| Family | State | Action | Resolvable pairs | Spread |
|---|---|---|---|---|
| distractor_flooding | exhausted | retire_candidate | 0/6 | 0.000 |
| option_order | exhausted | retire_candidate | 0/6 | 0.000 |
| score_anchoring | ceiling_saturated | reauthor_harder | 0/6 | 0.000 |
| indirection | uniform_failure | reauthor_harder | 0/6 | 0.000 |
| negation_games | uniform_failure | reauthor_harder | 0/6 | 0.000 |
| confidence_spoofing | discriminating | keep | 5/6 | 0.490 |
| literal_reading | discriminating | keep | 5/6 | 0.440 |
| policy_paraphrase | discriminating | keep | 5/6 | 0.525 |
| criteria_smuggling | discriminating | keep | 6/6 | 0.525 |
| state_poisoning | discriminating | keep | 6/6 | 0.555 |

## Per-adapter family ASR (Wilson 95%)

| Family | frontier-strong | mid-a | mid-b | weak |
|---|---|---|---|---|
| confidence_spoofing | 0.045 [0.024, 0.083] | 0.275 [0.218, 0.341] | 0.355 [0.292, 0.423] | 0.535 [0.466, 0.603] |
| criteria_smuggling | 0.085 [0.054, 0.132] | 0.205 [0.155, 0.266] | 0.480 [0.412, 0.549] | 0.610 [0.541, 0.675] |
| distractor_flooding | 0.015 [0.005, 0.043] | 0.015 [0.005, 0.043] | 0.015 [0.005, 0.043] | 0.015 [0.005, 0.043] |
| indirection | 0.490 [0.422, 0.559] | 0.490 [0.422, 0.559] | 0.490 [0.422, 0.559] | 0.490 [0.422, 0.559] |
| literal_reading | 0.175 [0.129, 0.234] | 0.345 [0.283, 0.413] | 0.445 [0.378, 0.514] | 0.615 [0.546, 0.680] |
| negation_games | 0.540 [0.471, 0.608] | 0.540 [0.471, 0.608] | 0.540 [0.471, 0.608] | 0.540 [0.471, 0.608] |
| option_order | 0.005 [0.001, 0.028] | 0.005 [0.001, 0.028] | 0.005 [0.001, 0.028] | 0.005 [0.001, 0.028] |
| policy_paraphrase | 0.055 [0.031, 0.096] | 0.295 [0.236, 0.362] | 0.315 [0.255, 0.382] | 0.580 [0.511, 0.646] |
| score_anchoring | 0.985 [0.957, 0.995] | 0.985 [0.957, 0.995] | 0.985 [0.957, 0.995] | 0.985 [0.957, 0.995] |
| state_poisoning | 0.100 [0.066, 0.149] | 0.255 [0.200, 0.320] | 0.515 [0.446, 0.583] | 0.655 [0.587, 0.717] |

## Reading

- `distractor_flooding` and `option_order` classify `exhausted`:
  every adapter CI sits below the 0.05 floor with zero resolvable
  pairs. They set the per-release exhaustion trigger; retirement
  eligibility needs a second consecutive release plus the
  variant-flip check (M-8), so nothing is eligible yet.
- `score_anchoring` classifies `ceiling_saturated`: attacks
  succeed on everyone. Action is harder variants, not retirement.
- `indirection` and `negation_games` classify `uniform_failure`:
  attacks work, but the families cannot rank adapters. Action is
  harder variants.
- The remaining five families discriminate: at least one adapter
  pair resolves beyond the paired MDE.

## Caveats

- Adapter behavior is synthetic and disclosed; real runs may
  classify every family `discriminating`.
- One release observed: `releases_observed=1`, two required.
- Variant-flip unmeasured: `exhausted` is a candidate, never an
  automatic retirement.
