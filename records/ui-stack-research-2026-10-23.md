# Front-end stack research for the peira board, 2026-10-23

Round 4 of the UI perfection program. Decision-grade memo for the owner.
Question: what stack replaces the hand-rolled HTML/CSS/SVG renderer for
https://peiratrial.dev/ , judged on this page's actual needs: dense
statistical charts (ranking with CI whiskers and tie bands, cost-vs-ASR
scatter with labeled points, attack-family heatmap, reliability /
calibration diagram, small multiples), 36 model cards, a compare view,
one frozen payload JSON from the existing Python pipeline, static
hosting on Cloudflare Pages, LinkedIn and social traffic landing on it.

Current page census (owner screenshots plus dist/index.html, 810 KB, 40
inline SVGs, one style block, one script tag): KPI tiles, model ranking,
attack family heatmap, cost vs ASR scatter, malformed rate chart,
calibration, 36 model cards, compare-two-models, notes. Everything is
Python string templates rendering static SVG. Interactions are near
zero, and the owner census found the failure modes that matter: tied
rank labels overlapping wire lines, long model ids truncating into
bars, heatmap headers wrapping, n/a blocks reading as missing data.

Method note: stack claims below come from the sites' own served HTML
and payloads, fetched 2026-10-23, from shipped library builds, and
from official docs. Bundle figures are bundlephobia minified plus
gzip for the full package unless stated otherwise.

## 1. Field study

### Artificial Analysis (artificialanalysis.ai)
Stack, verified from served HTML: Next.js (/_next/static chunks), and
the charts arrive server-rendered as Recharts markup
(recharts-responsive-container and recharts-wrapper classes are in the
initial HTML of /models, so charts are visible before any client JS
runs). Patterns worth stealing:
- One signature chart per claim, repeated as a module down the page.
  The famous one is Intelligence Index vs Cost per Task, a scatter with
  a Pareto frontier line and a shaded "most attractive quadrant".
- Every chart carries a short plain-language reading note directly
  under it, stating what the metric is, which direction is better, and
  how it was computed, with methodology one click away.
- Any model name or chart row clicks through to a dedicated per-model
  page, and a model selector customizes which models each chart shows.
- An FAQ block answers the questions readers actually arrive with,
  which doubles as the search surface.
Design read: restrained palette, generous spacing, the chart is the
hero of each section and the prose serves the chart. This is the
beauty bar for our rebuild.

### LMArena (arena.ai, formerly lmarena.ai)
Stack, verified: Next.js (redirects to arena.ai, /_next/static
chunks). Patterns worth stealing:
- Table-first leaderboard. The served payload carries rankUpper and
  rankLower per model, meaning rank uncertainty from the confidence
  interval is published in the table itself rather than hidden. Our
  tie bands are the same idea and deserve the same first-class
  treatment instead of a wall of microcopy.
- Category leaderboards (text, vision, coding, and so on) as filtered
  views of one dataset, plus per-model pages.
- The credibility signal is the vote count printed next to the score.
  Our equivalent is the case count and the interval, and both should
  sit on the row, not in a footnote.

### Scale SEAL (labs.scale.com/leaderboard)
Stack, verified: the leaderboard lives at labs.scale.com and is
Next.js (/_next/static chunks). Patterns worth stealing:
- Many benchmark leaderboards under one masthead with a benchmark
  switcher, each leaderboard a clean table with a short framing note
  about who evaluated and how.
- Expert-evaluation framing up top (who ran it, what it measures)
  before any number appears. Our masthead should state the threat
  model and the case count before the first tile.

### OpenRouter (openrouter.ai/rankings)
Stack, verified: Next.js (/_next/static chunks); charts render on the
client. Patterns worth stealing, from their own rankings docs:
- Top Models is a ranked bar chart over time with the top nine models
  named and the rest grouped as Others. Grouping the tail is how a
  dense chart stays readable, and our scatter needs the same
  discipline for its crowded regions.
- A "How to read these rankings" note that says plainly what the chart
  does NOT measure (theirs says the rankings do not rank models by
  accuracy or benchmark performance). Our scatter needs exactly one
  such sentence about zero-cost self-hosted models.

### Stanford HELM (crfm.stanford.edu/helm)
Stack, verified: the crfm-helm repo carries a dedicated React front
end (helm-frontend alongside the Python package), and the served
leaderboard shell references Recharts. Patterns:
- Credibility through completeness. Dense tables, every scenario
  broken out, everything downloadable, nothing hidden.
- HELM is the credibility floor, not the beauty bar. Its pages are
  visually plain, and that plainness is part of why David's verdict on
  our page stings: we currently sit closer to HELM's console look
  than to Artificial Analysis. The lesson is that completeness alone
  does not read as care.

### Hugging Face (huggingface.co)
Stack, verified: the Hub itself is a Svelte app (Svelte hydration
errors surface on huggingface.co settings pages), and chat-ui is
publicly a SvelteKit project. But the leaderboard products most
people know, including the Open LLM Leaderboard, ship as Gradio
Spaces. Patterns:
- Proof that SvelteKit works at very large scale, which keeps Svelte
  credible as a framework.
- A cautionary contrast for charting: the Gradio leaderboards feel
  generic and cramped despite excellent data, because the charting
  and layout layer was never really theirs. The framework was not
  their problem. The visualization layer was.

### Epoch AI (epoch.ai)
Stack, verified from served HTML: Astro, with React components
hydrated as islands (astro-island elements pointing at React
component bundles such as AIModelsViz). Patterns:
- Long-form research pages where most of the page is static text and
  only the few heavy interactive visualizations hydrate.
- Proof, from a research org with the same audience as ours, that the
  Astro plus React islands model works in production for data pages.
  It is the strongest counterexample to the Next.js consensus below,
  and the reason Astro is our runner-up rather than a footnote.

### METR (metr.org)
Stack, verified from served pages: largely static pages with Chart.js
widgets. The least app-like property in the set. Included as the low
end of the field: static plus a chart widget is where we already are,
and it is not where the bar sits.

Field summary: five of the eight properties run React, and four of
those (Artificial Analysis, LMArena, Scale SEAL, OpenRouter) run
Next.js specifically. The two non-React exceptions prove narrower
points: Epoch proves Astro islands for research pages, and Hugging
Face proves SvelteKit at platform scale while also proving that a
generic visualization layer sinks a leaderboard regardless of
framework. Nobody credible in this field hand-rolls a static HTML
renderer anymore, and nobody server-renders Python string templates.

## 2. Charting layer

Judged against our census: ranked dot plot with CI whiskers and tie
bands, labeled scatter, heatmap, calibration diagram, small
multiples, plus linked interaction with filtering, the compare tray,
and model cards. Bundle figures verified from bundlephobia on
2026-10-23.

### visx (Airbnb)
D3 primitives packaged as React components: scales, shapes, axis,
annotation, tooltip, brush. You compose the chart; nothing about the
final look is imposed. Bundle is a la carte and the smallest here by
a wide margin (verified: @visx/scale 17 KB gzip, @visx/shape 10 KB
gzip; a full set for this page lands roughly 45 to 75 KB gzip
including the d3 modules it wraps). Whiskers, tie bands, heatmap
cells, calibration curves are all direct compositions of primitives.
Label collision: nothing built in, and that is the honest weakness.
Our counter is structural, and it is strong: the dataset is frozen at
build time, so scatter label placement can be computed once during
the build (greedy or force relaxation in Node) and shipped as final
coordinates. Runtime collision solving is a feature for live data,
which we do not have. Accessibility is ours to add (SVG title and
desc, plus the data table we ship anyway). Design control: total.
This is the only candidate where the library cannot impose a look.

### Apache ECharts
The batteries-included option. Native heatmap, native boxplot (close
to our whiskers), custom series for anything else, and the only
mainstream library besides Vega with built-in label overlap handling:
labelLayout with hideOverlap and moveOverlap is present in the
shipped build (verified in the echarts 5 minified dist). Two
problems for us. First, hideOverlap resolves collisions by silently
dropping labels, and a dropped model label on a benchmark scatter is
a data honesty defect, not a layout choice; moveOverlap helps but
still cedes placement to a runtime heuristic we cannot screenshot-
review deterministically. Second, weight and defaults: 359 KB gzip
for the full package (verified), roughly 180 KB for a tree-shaken
subset with the SVG renderer, and a house aesthetic that reads as
enterprise dashboard unless fought chart by chart. Accessibility is
genuinely the best here (ARIA support plus decal patterns for
color-blind-safe fills). Verdict: the credible fallback if our own
label placement work fails its prototype round, not the first
choice.

### Vega and Vega-Lite
The declarative grammar option, and the owner of the single best
label feature in the field: Vega's label transform (docs, vega
5.16+) "positions text marks so that they do not overlap with each
other or with other marks in the chart" (verified, vega.github.io
label transform docs). Faceting for small multiples is native and
excellent, whiskers layer cleanly, heatmaps are trivial. Costs:
rendering needs Vega plus Vega-Lite together, roughly 266 KB gzip
combined (88 plus 178, verified); design control is exercised
through spec config, which fights pixel-level intent exactly where
our perfection bar lives (tie bands, flagged row treatment, wire
duplicates); and React integration is an embed of a spec renderer,
so linked interaction across charts (hover in the ranking lighting
the scatter) becomes signal plumbing instead of component state.
Verdict: steal the label transform idea, implemented at build time.
Do not adopt the runtime.

### Observable Plot
Grammar-of-graphics from the D3 team, 127 KB gzip (verified), the
fastest path from data to a competent chart, with native faceting
and good defaults for exploratory work. For this page it fails on
three counts: text label collision handling is the weakest of the
set (no dodging for text marks), bespoke constructions like tie
bands and flagged-row treatments fight the grammar, and its visual
signature reads as Observable notebook, which is the wrong register
for a flagship public artifact. It also renders to DOM outside
React, so linked state with the compare tray is manual. Verdict:
right tool for internal analysis notebooks. Not for the public
board.

### Recharts
The field's incumbent: Artificial Analysis and HELM both ship it,
146 KB gzip (verified), React-native, and quick to build standard
charts with. It is also, in our judgment, part of why benchmark
dashboards look alike. Label handling is the weakest of the serious
candidates (labels render where placed; overlap is the author's
problem, solved by hiding or rotating), heatmap is not a native
chart type, and the bespoke ranking construction we need (dot,
whisker, tie band, wire duplicate, flagged treatment on one row)
becomes a stack of custom shape hacks inside someone else's layout
engine. Its accessibility layer (keyboard-navigable charts) is real
and worth noting. Verdict: choosing Recharts would optimize for
building speed against the exact quality David rejected. Not
adopted.

### Hand-rolled SVG inside React components
Zero library weight, total control, and precisely the approach that
just failed, with one difference that matters: inside React, the
scales, ticks, and layout math still have to come from somewhere,
and hand-deriving them per chart is how the current page accumulated
its collisions. visx is the disciplined form of this option (the
same raw SVG output, with the math supplied by maintained
primitives). Verdict: hand-roll only where a chart is genuinely
simple (heatmap cells, malformed bars), and take the primitives for
everything else.

Charting verdict: visx as the primary layer, hand-rolled SVG inside
components where visx has no opinion worth taking, ECharts as the
named fallback for the scatter if build-time label placement misses
its prototype gate.

## 3. Framework and delivery

Constraints restated: one data-dense page plus possible per-model
detail views; data baked at build time from the existing payload
JSON; static assets only on Cloudflare Pages; builds run on a small
shared VM that is also running trial drivers; sharing meta matters
because LinkedIn traffic lands here; load performance on a heavy
page matters.

### Next.js with static export
output: "export" produces a fully static site. Official docs list
what export gives up (verified, Next.js static exports guide):
dynamic routes without generateStaticParams, route handlers that
rely on request state, rewrites, redirects, headers, ISR, image
optimization with the default loader, draft mode, server actions.
We need none of those. Per-model pages are generateStaticParams
over the payload. Sharing meta is the built-in metadata API,
including generated Open Graph images if wanted. Charts can be
server-rendered into the static HTML (the Artificial Analysis
pattern), so the page reads complete before hydration and
crawlers see every number. Costs: the heaviest build of the
candidates (acceptable; roughly 40 static pages is a small build,
and builds can be scheduled around trial checkpoints), framework
surface we will mostly not use, and version churn, managed by
pinning and by using only static features.

### React plus Vite, no framework
The lightest build and the fastest on the shared VM. But routing,
prerendering for sharing meta, and per-model pages become
hand-assembled or delegated to Vike or React Router framework mode,
at which point we have rebuilt a slice of Next.js with a smaller
community and fewer proven answers at 3 a.m. during a perfection
program. For a one-page site with a hard deadline, convention beats
assembly.

### Astro with React islands
Epoch AI proves this in production for research data pages, and its
performance story is the best here: prose and cards ship as zero-JS
static HTML, only charts hydrate. It is the strongest runner-up.
Where it loses for this page specifically: the page is one tightly
linked interactive surface, not a content site with widgets.
Ranking filters, scatter highlighting, the compare tray, and model
cards all share selection state, and across island boundaries that
state needs a separate store (nanostores) plus disciplined hydration
boundaries, with the seams multiplying when per-model pages reuse
the same linked charts. If this site grows into a multi-page
research publication (methodology essays, many mostly-static
pages), Astro wins and we should switch then. For the page we
actually have, one React tree is the simpler truth.

### Svelte and SvelteKit
Hugging Face proves SvelteKit at platform scale, its static adapter
is first-class, and bundles run small. The rejection is about the
charting ecosystem, not the framework: there is no visx peer for
Svelte (LayerChart is promising and younger), so our most bespoke
charts would be the most hand-rolled exactly where the perfection
bar is highest, and builder fluency plus component depth for this
design system is thinner. Wrong deadline to take ecosystem risk.

### Solid
Fine-grained reactivity is genuinely attractive for dense linked
charts, and SolidStart can prerender static pages. The charting and
component ecosystem is the thinnest of the set and the experienced
builder pool the smallest. Rejected on ecosystem risk, same as
Svelte but more so.

Delivery notes applying to any choice: Cloudflare Pages serves all
of these as static assets; the current deploy helper gets repointed
from a single rendered HTML file to the static output directory;
the current page stays live until the new build passes David's
review, with the new build iterated on a preview URL through the 40
rounds.

## 4. Recommendation

Adopt Next.js (App Router, static export) plus React, with visx as
the charting layer and hand-rolled SVG components where a chart is
simple, styled by a single design system (CSS custom properties
plus utility classes) defined in rounds 5 to 10 before build rounds
begin.

Reasoning, compressed: the field's credible benchmark properties
run this framework (four of eight studied, including the two whose
design we most want to approach). Static export satisfies the
static-only hosting contract with nothing we need given up. Charts
server-render into the static HTML, so LinkedIn arrivals and
crawlers see the finished page, not a spinner. visx is the only
charting layer that cannot impose a look, is the lightest by a wide
margin, and its one real weakness (no runtime label collision
solving) is neutralized by our frozen dataset: placement is
computed once at build time and reviewed in screenshots like
everything else.

Migration shape:
- Python pipeline: unchanged. It keeps emitting the identical
  payload JSON; no printed number changes, and the front end formats
  but never recomputes. A build-time check diffs every rendered
  number against the payload, turning the round 2 census into a
  standing gate.
- Front end: a new app in the repo (the dashpub tree is the natural
  home) that imports the payload at build time, computes derived
  layout (scatter label coordinates, tie band geometry) during the
  build, and prerenders the board plus one static page per model.
- Publish: the freeze pipeline writes the payload, runs the front
  end build, and deploys the static output directory to Cloudflare
  Pages in place of the current single-file deploy. Preview deploys
  on a branch URL for every review round; production swaps only on
  David's verdict.

Top three risks:
1. Scatter label placement is ours to build. Mitigation: it is
   prototyped and red teamed in round 9, before the build rounds
   commit to it, and ECharts is the named fallback if the prototype
   misses.
2. Build weight on the shared VM while trial drivers run.
   Mitigation: static export for roughly 40 pages is a small build;
   builds are bursty and scheduled around driver checkpoints, per
   the charter's box discipline.
3. Framework defaults making the result look like a generic
   dashboard template, the failure mode of the Recharts path.
   Mitigation: design system rounds precede build rounds, and visx
   plus hand-rolled SVG means no library aesthetic is inherited.

Deliberately NOT adopted: Recharts (design ceiling, weak label
handling, the generic dashboard look), Observable Plot (notebook
register, weakest bespoke control), Vega-Lite as a runtime (spec
indirection fights pixel-level design; its label transform is
adopted as a build-time idea instead), ECharts as primary (weight
plus opinionated defaults; retained as fallback), Svelte and Solid
(charting ecosystem risk on a deadline), any server runtime, ISR,
or API-driven rendering (the dataset is frozen; a server would
only add failure modes), and Gradio-style embedding of any kind.

Strongest runner-up: Astro with React islands carrying the same
visx chart components. It wins instead if either of two things
becomes true: the site grows well beyond one app-like page into a
publication with many mostly-static pages, or the JavaScript budget
becomes the binding constraint (for example if the board must
perform on low-end mobile over slow networks as a primary audience
rather than a supported one). The chart components port unchanged,
so this is a reversible decision at the framework layer.

## Sources

- artificialanalysis.ai/models, served HTML and page text fetched
  2026-10-23 (Next.js chunks; recharts-responsive-container and
  recharts-wrapper markup server-rendered; per-chart reading notes;
  Intelligence Index vs Cost per Task scatter with Pareto line).
- arena.ai/leaderboard, served HTML and payload fetched 2026-10-23
  (Next.js chunks; rankUpper and rankLower fields per model).
- labs.scale.com/leaderboard, fetched 2026-10-23 (Next.js chunks).
- openrouter.ai/rankings, fetched 2026-10-23 (Next.js chunks), plus
  OpenRouter's own LLM Rankings documentation ("How to read these
  rankings", Top Models chart grouping, Market Share by requests).
- crfm.stanford.edu/helm/classic/latest, fetched 2026-10-23
  (Recharts reference in served shell); PyPI crfm-helm package
  description (helm-frontend React front end in the repo layout).
- epoch.ai and epoch.ai/data/ai-models, served HTML fetched
  2026-10-23 (astro-island elements, React component bundles
  including AIModelsViz).
- huggingface.co, Svelte hydration error report on the Hugging Face
  forum, 2026-10-21; huggingface/chat-ui project structure
  (SvelteKit).
- metr.org, fetched 2026-10-23 (Chart.js present in served pages).
- bundlephobia.com size API, queried 2026-10-23: echarts 359 KB
  gzip, recharts 146 KB, @observablehq/plot 127 KB, vega 178 KB,
  vega-lite 88 KB, chart.js 68 KB, @visx/scale 17 KB, @visx/shape
  10 KB.
- Vega documentation, label transform (vega.github.io): "positions
  text marks so that they do not overlap with each other or with
  other marks in the chart".
- Apache ECharts 5 shipped build (cdn.jsdelivr.net/npm/echarts@5):
  labelLayout, hideOverlap, moveOverlap present in the dist.
- Next.js documentation, static exports guide (nextjs.org):
  unsupported features list for output export, quoted in section 3.
- UI perfection program charter, this goal's hidden_files
  (ui-perfection-program-2026-10-23.md): chart census, owner defect
  census, hard rules.
