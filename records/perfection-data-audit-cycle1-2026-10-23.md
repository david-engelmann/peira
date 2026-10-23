# Perfection program — data integrity audit, cycle 1 (2026-10-23)

Scope: every number on the live board (https://peiratrial.dev/, payload-publish26)
reconciled to its sealed source artifact in `~/workspace/peira-trial/publish-runs/`.
AUDIT ONLY — no fixes, no deploys. Classification: DEFECT (board disagrees with
source or with the project's own stated rule), PRESENTATION QUESTION (board
follows a rule a reader could misread), CLEAN.

## Headline

The measurement numbers are sound: **396 of 396 row fields across all 36 rows
match their sealed artifacts, all 37 artifacts pass `verify()`, and a fresh
render of the payload reproduces the live page byte for byte.** Two defects,
both in how the page *describes* its own numbers, not in the numbers:

- **D1 (priority): the page names the wrong robustness-tax benchmarks.**
- **D2: the model tiles undercount distinct models (33 vs 35 displayed)
  because three unrelated models share `adapter_version` "1.0".**

---

## DEFECTS

### D1 — Robustness tax: notes and card copy name slice rows as the benchmark setters; the numbers were computed against Jev 1.14 and Claude Sonnet (PRIORITY)

**What the tax numbers actually use** (generation code:
`peira/dashboard.py::_apply_robustness_tax_column` — the frontier is the
ranked cohort that ran the most cases, here the 27 full-suite rows at
n_cases 4,701; slice rows are excluded per PR #476). Recomputed from the
payload, the frontier is set by exactly one row per metric:

- Benign accuracy setter: **jev / jev-1.14.0 at 0.9872** (unique max over the cohort)
- Attacked ECE setter: **anthropic-structured / claude-sonnet-5-5 at 0.0479** (unique min over the cohort)

All 27 printed cohort taxes recompute exactly from
`(0.9872 − benign) + (ECE − 0.0479)`. Sample (printed vs both frontiers):

| row | printed tax | cohort frontier (jev 0.9872 / sonnet 0.0479) | note-stated frontier (benign 1.0 / ECE 0.0032) |
|---|---|---|---|
| jev-114-v2-trial | 0.0579 | 0.0579 | 0.1154 |
| anthropic-v2-trial (Sonnet) | 0.0047 | 0.0047 | 0.0622 |
| celeris-v2-trial | 0.0316 | 0.0316 | 0.0891 |
| clef-v2-trial | 0.0179 | 0.0179 | 0.0754 |
| laya-multilingual-v2-trial | 0.5059 | 0.5059 | 0.5634 |
| anthropic-fable-v2-trial | 0.0108 | 0.0108 | 0.0683 |

Every printed tax sits exactly **0.0575 below** the note-frontier value
(0.0128 benign gap + 0.0447 ECE gap, constant across rows). The two setter
rows prove it from their own cards: Jev 1.14's tax (0.0579) is purely its ECE
shortfall from Sonnet (0.1058 − 0.0479) with zero benign shortfall, and
Sonnet's tax (0.0047) is purely its benign shortfall from Jev
(0.9872 − 0.9825) with zero ECE shortfall.

**What the page claims** (verbatim from the live HTML):

- Footer note ("Severity and robust tax"): "Robust tax … adds a ranked run's
  benign accuracy shortfall from the best ranked benign accuracy and its
  attacked ECE shortfall from the best ranked attacked ECE, in points. **On
  this page the benchmarks are the best ranked runs, granite-guardian-hap-125m,
  Shieldstral-1.0-3B and 3 others at 100.0% for benign accuracy and
  granite-guardian-hap-125m at 0.003 for attacked ECE.**"
- granite-guardian-hap-125m card, tax row label: "**ROBUST TAX · IT SETS
  BOTH RANKED BENCHMARKS**" — on a card whose tax value is n/a (slice rows
  carry no tax).
- Cards caption: "robust tax adds the benign accuracy and attacked ECE
  shortfalls from **the best ranked runs**, in points"; every full-suite
  card's tax label reads "ROBUST TAX · VS BEST RANKED RUNS".

The named setters are the frontier over **all** ranked rows including the
five 373-case slices (benign 1.0 held by granite-hap, shieldstral,
qwen3guard, protectai, granite-guardian — verified: exactly those five rows
sit at benign_accuracy 1.0; ECE min over all ranked is granite-hap 0.0032).
Those names are accurate as all-ranked statements; they are **not** the
benchmarks the tax column was computed against. Root cause: the renderer's
notes component (`report_html/components/notes.py`) and the cards'
`sets_benchmarks` flag compute benchmark holders over all ranked rows,
while the generation layer restricts the frontier to the full-suite cohort.
A reader who recomputes any tax from the page's stated benchmarks gets a
number 5.75 points higher than the printed tax, on every taxed row.

### D2 — Tile counting: three distinct models collapse into one "model" (33/29 printed; 35/31 displayed)

The tiles group entries by `_model_key` = **adapter_version alone**
(`report_html/_data.py`, used by `components/kpi.py`). Three unrelated
models carry the generic adapter_version "1.0":

- shieldstral-v2-trial (adapter shieldstral, model mistralai/Shieldstral-1.0-3B)
- qwen3guard-v2-trial (adapter qwen3guard-gen, model Qwen/Qwen3Guard-Gen-4B)
- granite-guardian-v2-trial (adapter granite-guardian, model ibm-granite/granite-guardian-4.1-8b)

Recomputed tile counts under three identity rules (printed: **33 TESTED ·
29 RANKED · 4 FLAGGED**):

| rule | tested | ranked | flagged |
|---|---|---|---|
| adapter_version alone (renderer as shipped) | 33 | 29 | 4 |
| (adapter_name, adapter_version) pair — PR #460 / Admission-Rules rule | 36 | 32 | 4 |
| display_name (distinct served models actually displayed) | 35 | 31 | 4 |

The board fails the counting rule its own documents prescribe:
`docs/Admission-Rules.md` ("Model identity") states a row is "identified by
the pair of adapter_version … and adapter_name … **Neither field alone is
the identity**", and PR #460's commit message states the tiles "count
distinct models by the (adapter_name, adapter_version) pair through one
shared helper" — the helper it shipped keys on adapter_version only. (The
pair rule itself overcounts the other way: it counts gpt-6-luna's two wires
as two models, the very thing #460 was fixing; the served-model count,
35/31/4, is the one that matches the 35 distinctly named models the page
displays.)

Knock-on symptoms of the same key, all verified in the live HTML:

- **Lead band tile**: the top tie band holds 3 entries (granite-hap 0.0%,
  shieldstral 0.6%, qwen3guard 0.8%) and the ranking caption correctly says
  "the top 3 intervals overlap, a tie", but the tile prints "**2 MODELS
  TIED AT THE TOP**" because the band's versions are {125m, 1.0, 1.0}.
- The three "1.0" cards each carry a "**Wire · …**" note ("Wire ·
  Shieldstral", "Wire · Qwen3Guard Gen", "Wire · Granite Guardian"),
  presenting three different models as wires of one model.
- The counting note under the tiles ("Tiles count distinct models · ranks
  count entries · some models appear on two wires") is triggered by this
  collision as well as by the genuine gpt-6-luna two-wire case.

This is the same identity-collision hazard the project already met with
Kev 0.8B (an artifact stamped with the 4B's adapter_version), here on the
counting side rather than the row side.

---

## PRESENTATION QUESTIONS

### P1 — Scatter: caption claims a point per model with a recorded cost; three models with a recorded cost of $0.00 have no point

The chart plots a point only when `total_cost_usd > 0` and ASR is present
(log cost axis). Verified against the rendered page (design harness PASS;
26 labels / 26 points on both desktop and mobile; the plotted rank set
{6–23, 25, 26, 30, 32} plus 4 flagged matches the rule exactly; the chart's
own `<desc>` enumerates precisely the 26 plotted points with costs, ASRs,
ranks and tie bands). Excluded rows (10):

- cost unrecorded (None): granite-hap, shieldstral, qwen3guard, protectai,
  granite-guardian (the five slices), decider, strands-decider
- **cost recorded as $0.00: kev-4b, laya-multilingual, semif** — these have
  a recorded cost (9,402 priced calls, `total_cost_usd` 0.0 in their
  artifacts) but cannot sit on a log axis.

The scatter caption reads "one point per model with a recorded cost", which
is true of 26 of the 29 models that have a recorded cost. The exclusion of
local/self-hosted runs is the known design rule; the caption wording is the
part a reader can falsify from the payload.

### P2 — The suite size (4,701 cases) is printed nowhere on the page

The renderer's PAIRED CASES tile is omitted by design when run populations
mix (n_cases consensus fails: 4,701 and 373 coexist; footer provenance
states "case counts vary by run"). A visitor can read eligible bases
(364 to 4,640 per model) and the slices' 373, but no surface states that the
full suite is 4,701 paired cases. No printed number is wrong; the board's
scale is simply never stated.

### P3 — Re-run segment counts rest on the trial record, not the sealed artifacts

The Run notes block states: "The first 1,610 cases of the gemini-3.8-flash
run and the first 3,274 cases of the kimi-k3 run were re-run under fixed
adapters on 12 October 2026". These counts are hard-coded in the renderer
(`_data.py::_RERUN_SEGMENTS`, keyed by run_id) with a comment citing the
2026-10-12 segment re-run audit notes; they are not derivable from the
sealed artifacts. Consistency checks pass (google artifact call_date
2026-10-12; moonshot created 2026-10-13T00:07Z = 12 October in
America/New_York; both runs carry 4,701 cases, above the segment sizes).
Flagged so the owner knows this one prose claim's evidence is the trial
record rather than a seal.

### P4 — Payload top-level suite/dataset_version are null

`payload-publish26.json` carries `suite: null, dataset_version: null` at
top level; the page's "suite v2, dataset 2.6.0" rests on the unanimous row
values (all 36 rows agree). No reader impact; noted for the freeze pass.

---

## CLEAN — verified reconciliations

### Live page identity
- Live md5 (fetched 2026-10-23): `0a8148a49ce807232ef8e338dae28f03` =
  staged `~/workspace/peira-dashpub/dist/index.html` md5 = stated publish26 md5.
- Re-rendering `payload-publish26.json` with the dashpub renderer
  (`render_html.py`) reproduces dist/index.html **byte-identically**
  (same md5). Every printed number below is therefore a deterministic
  function of the audited payload.
- The page's printed provenance hash, "payload sha256 598dc5067cc77e31…",
  equals the SHA-256 of `payload-publish26.json` exactly.

### Row-by-row reconciliation (the core check)
36 payload rows ↔ 36 staged artifacts (run_id = file stem, 1:1). **396
field comparisons, 0 mismatches**: adapter_name, adapter_version,
asr_conditional, asr_ci95 (both bounds), benign_accuracy, malformed_rate,
ece_attacked (vs artifact `metrics.calibration.attacked.ece`), n_cases,
n_eligible, total_cost_usd, ranking_eligible — each payload value equals
the artifact's metrics value (within the 4-dp storage rounding, tolerance
0.000051; in fact all matched at stored precision). Sample anchors:
celeris ASR 0.1696 [0.159, 0.1807], benign 0.9785, n_eligible 4,600;
jev-1.14.0 ASR 0.1106, benign 0.9872; fable ASR 0.2850, cost $130.3128.

### Artifact integrity
`RunArtifact.from_json(...).verify()` returns **True for all 36 staged
artifacts** (and for the unpublished Clef omni seal, §below).

### Rank order and tie bands
- Stated rule (generation code): ranked rows sort by asr_conditional
  ascending, unusable ASRs last. Payload ranked order is non-decreasing in
  ASR with **no exact point-estimate ties**; the page's rank numbers
  (cards, hero, registry) follow it; card ASR sequence equals the renderer
  display order for all 36 entries.
- Tie bands (CI-overlap, greedy common-intersection) replicated from the
  payload CIs: **(1–3), (5–14), (15–16), (17–20), (21–23), (24–28),
  (29–31)** — identical to the ranking caption, the hero `<desc>`, the
  card chips and the scatter key note.
- Admission split: the 4 unranked rows all carry reason
  "ranking-ineligible: malformed_rate above 5%" (malformed 0.0619, 0.0728,
  0.1070, 0.1191); max ranked malformed is 0.0423 ≤ 0.05. The printed
  admission rule ("at or under 5%") matches.

### Robustness tax values (as numbers — see D1 for the prose)
27/27 cohort taxes recompute exactly; the five slice rows carry tax None;
unranked rows carry no tax key. Tax keyed by (adapter_name,
adapter_version) per PR #458; no duplicate pair identities in the cohort.

### Tiles other than the model count
- Lead band figure "0.0–0.8%": tied[0] ASR 0.0% to tied[-1] ASR 0.8%
  (qwen3guard 0.0080). (The "2 MODELS" wording is D2.)
- Retrieval poisoning range "0.0–84.3%": min granite-hap 0.0, max xai
  0.8428 over 36 family cells. ✓
- Cost spread "≥$0.05 to ≥$130.31, pplx-decider-v1.1-27b to
  claude-fable-5-1": min recorded cost pplx 0.0582 (floored to $0.05),
  max fable 130.3128 (floored to $130.31). ✓
- Bases note "headline bases 364 to 4,640 per model · family bases 41 to
  470": n_eligible min shieldstral 364, max jev-114 4,640; family-cell
  n_eligible min 41, max 470 over 376 recorded cells. ✓
- "11 family ASRs": exactly 11 families in the payload. ✓

### Scatter set
26 plotted / 10 excluded per the cost rule (enumerated in P1); harness
`check_scatter_labels.py` PASS (26 labels, 26 points, no overlaps, both
variants); plotted rank/flag set extracted from the page matches the rule
exactly; per-point costs and ASRs in the chart `<desc>` match the payload
(e.g. terra $12.83 rank 6; pplx $0.05 rank 17; fable $130.31 rank 32).

### Slice rows (PR #476)
The five 373-case abstain slices (granite-hap, shieldstral, qwen3guard,
protectai, granite-guardian): tax None on every surface (cards print n/a);
full served-model identities printed in card notes (ibm-granite/
granite-guardian-hap-125m; mistralai/Shieldstral-1.0-3B; Qwen/
Qwen3Guard-Gen-4B; protectai/deberta-v3-base-prompt-injection-v2;
ibm-granite/granite-guardian-4.1-8b) and in the run register; eligible
cases print 373 (shieldstral 364 eligible of 373). Hash-bearing full
identities (decider, semif) print in full in card notes. ✓

### Cards, hero, heatmap, calibration, malformed, register
- Cards: all 36 in display order; ASR + CI, benign, malformed, eligible,
  ECE, Brier, calib n and share, severity flips and bases match the
  payload under the renderer's documented formatters (Decimal half-up;
  count-exact derivations where the payload proves them — the page's own
  footer discloses last-place differences from printed roundings).
  Two sampled last-digit cases are formatter-exact, not errors:
  shieldstral ASR prints 0.6% from stored 0.0055 (half-up of 0.55);
  or-solar card CI prints 16.3%–18.5% from the count-derived Wilson
  interval vs the stored rounded [0.1635, 0.1855].
- Hero chart: 36 rows, ranks 1–32 plus flagged bullets interleaved by ASR,
  values match.
- Heatmap: header families in fixed order; spot row (grok-4) — all 11
  cells match payload families exactly (retrieval 84.3% · n 458;
  crypto 39.5% · n 420; verbosity 17.0% · n 470; …).
- Calibration panels: all 36 panels present, ordered by attacked ECE
  ascending; the (ECE, Brier, n) triple of every panel matches the
  payload's calibration block (granite-hap 0.003/0.000/373 first;
  laya-multilingual 0.360/0.333/3,728 last); every panel carries 15
  reliability bins, as the caption states.
- Malformed chart `<desc>`: all 36 (name, rate) pairs match the payload,
  worst first (qwen3-235b 11.9% … 0.0% tail).
- Run register: 36/36 rows — adapter, version, pricing version and local
  (America/New_York) run date all match payload provenance.
- Footer provenance: "suite v2, dataset 2.6.0, manifest sha256
  cb89cc9955347250…" matches every artifact's manifest hash prefix;
  "runs from 6 to 22 October 2026" matches the created_utc window
  (xai 6 Oct → celeris 22 Oct, local dates).
- Methodology prose: "Intervals are Wilson 95% confidence intervals" —
  artifacts carry `uncertainty.ci_method = wilson, ci_level = 0.95`. ✓
- Severity note: "confidence intervals reach about 20.9 points to one side
  at the widest" — widest one-sided distance is exactly 20.9 points
  (granite-guardian critical: rate 0.1053, CI [0.0294, 0.3139]). ✓

### Unpublished seals (freeze-pass candidates)
- **Clef omni** (`~/workspace/peira-trial/artifacts/clef-omni-v2-trial.json`):
  md5 `adb1b64b924c5e02972438a868894583` (matches the owner's adb1b64b);
  `verify()` **True**; run_status success, termination complete; 4,701
  results. Metrics confirmed independently from the artifact: **ASR
  0.2024 [0.191, 0.2142], benign 0.9832, malformed 0.0045, attacked ECE
  0.0934, n_cases 4,701, n_eligible 4,615, spent $0.4732** — every figure
  equals the owner's stated values. Its tax at the freeze pass (against
  the current frontier) would be (0.9872 − 0.9832) + (0.0934 − 0.0479) =
  0.0495, and its ASR 0.2024 would slot between rank 23 (clef-flash
  0.1908) and rank 24 (decider 0.2149) on the current field.
- **Controls**: celeris and pplx-decider seals in `artifacts/` are
  byte-identical to the staged publish-runs copies (md5 2089c0ae… and
  b49abee0… respectively), and both verify True (within the 37 above).

---

## Counts

- Rows reconciled: 36/36 · field comparisons: 396 · mismatches: 0
- Artifacts verify() True: 37/37 (36 staged + Clef omni)
- Taxes recomputed: 27/27 exact · tie bands replicated: 7/7
- Registry rows: 36/36 · calibration panels: 36/36 · scatter points: 26/26
- **DEFECTS: 2** (D1 tax-benchmark prose; D2 tile model-identity counting)
- **PRESENTATION QUESTIONS: 4** (P1 scatter caption vs $0.00-cost models;
  P2 suite size unstated; P3 re-run counts sourced from trial record;
  P4 null top-level payload fields)
