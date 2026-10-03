# Pilot Analysis UI/Presentation Review

Date: 2026-10-03
Reviewer: ANALYSIS-VISUALIZATION lane
Scope: `site/` dashboard + `python/peira/pilot_report.py` output

## Verdict

PASS with recommendations. The dashboard is honest and well-structured.

## Strengths

1. **Mock labeling.** Every mock surface carries a visible "mock" badge
   or note (`site.js` lines 12, 97, 287, 417, 676). No silent mock data.
2. **Metric explanations.** The leaderboard's "How to read this table"
   section explains conditional ASR, benign accuracy, and eligibility
   in plain language.
3. **Division separation.** Guardrails and LLM baselines rank within
   their divisions, never blended. The sealed division declaration is
   checked at ingest.
4. **CI visibility.** 95% intervals shown alongside point estimates.

## Recommendations (non-blocking)

1. **Cost display.** The frontier page notes mock builds have no pricing.
   When real pilot costs land, verify the cost axis uses log scale --
   linear scale on costs spanning $0.46 to $39 will compress the cheap
   models into an unreadable cluster. The `cost_scatter_svg` in
   `pilot_charts.py` already uses log scale; the site should match.

2. **Heatmap color accessibility.** The green-to-red ASR scale in
   `family_heatmap_svg` is intuitive but not colorblind-safe. Consider
   adding pattern or numeric redundancy (the cell values already serve
   this; ensure they remain visible at all zoom levels).

3. **Nemenyi interpretation.** The rank chart's whisker note explains
   non-overlap = significant. Add one sentence for non-statisticians:
   "If two models' bars overlap, we cannot confidently say one is
   better."

4. **Sample size visibility.** Per-family n_eligible should be visible
   on hover or in a tooltip on the heatmap. A 0.50 ASR on n=10 is not
   the same evidence as 0.50 on n=400.

## Checks performed

- [x] No unlabeled mock data on any page
- [x] No em dashes, colons in headers, or AI-writing tells in user-facing copy
- [x] All charts have text alternatives (aria-label)
- [x] No JavaScript-required rendering in the pilot HTML report
- [x] Division vocabulary consistent across pages
