# Peira board perfection vocabulary and criteria, 2026-10-23

Lane. Perfection vocabulary and criteria, part of the UI perfection
program (charter, ui-perfection-program-2026-10-23.md). David's
instruction was that the site be perfect in user interface, design,
data analytics and data visualization, and that we research more
words like those and hold the work to perfection in those words
too. This document does three things. It names the disciplines
that govern a public data product of this kind. It converts them
into a numbered checklist an auditor can pass or fail against
screenshots, the DOM, and the payload. It then scans the current
live page and the Ledger design system against that checklist and
lists the gaps neither one covers.

Companion documents. The census
(perfection-ui-review-cycle1-2026-10-23.md) holds defects F-01 to
F-17, V-02 to V-04, C-01 to C-07 and accessibility notes A-01 to
A-06 against the current page. The design system
(ui-design-system-2026-10-23.md) holds the Ledger direction for
the rebuild. This document cites both rather than repeating them.

Severity scale, shared with the census. BLOCKER means the defect
must be dead before a launch a researcher will judge in one
visit. SHOULD means a defect a careful reader will notice and
count against the work. POLISH means a defect that only shows
under deliberate inspection. A criterion marked as a gate applies
to the rebuilt page at the round named in the charter.

Method note. Definitions are grounded in the source named with
each term. Standards are cited by body and document, in the form
W3C for WCAG 2.2 and web.dev for Core Web Vitals. Page evidence
comes from the deployed file at
~/workspace/peira-dashpub/dist/index.html, re-read for this lane
on 2026-10-23, and from the payload
~/workspace/peira-trial/payload-publish26.json.

## Part 1. The vocabulary

Each entry gives the term, a one line definition with its source,
why the term binds this page, and the failure it names.

### Reading data

**Data visualization.** The encoding of data into visual channels
such as position, length, and color so that patterns can be seen
rather than computed by the reader (Munzner, Visualization
Analysis and Design, 2014). It binds because the board is four
charts and a table before it is anything else. The failure it
names is a chart that decorates a number instead of revealing a
comparison.

**Graphical perception.** The experimental ranking of how
accurately readers decode visual channels, with position on a
common scale first and color saturation and hue last (Cleveland
and McGill, Journal of the American Statistical Association,
1984). It binds because the headline comparison on this page,
attack success, must ride the most accurate channel available.
The failure it names is asking hue or area to carry a difference
the reader must judge to two significant figures.

**Visual analytics.** Analytical reasoning supported by
interactive visual interfaces, where the reader tests a question
against the data rather than receiving a fixed answer (Thomas and
Cook, Illuminating the Path, 2005). It binds because compare and
the expandable cards are the reader's own analysis tools. The
failure it names is interactivity that changes the view without
answering a question the reader actually brought.

**Statistical graphics integrity.** The rule that a graphic's
visual effects must be proportional to the data effects they
represent, and that scales must not mislead (Tufte, The Visual
Display of Quantitative Information, 1983, and Cairo, The
Truthful Art, 2016). It binds because every figure on the page
will be recomputed by at least one skeptical reader. The failure
it names is any chart that survives a screenshot but not a
recomputation.

**Data-ink ratio.** The share of a graphic's ink that encodes
data, to be maximized by erasing ink that encodes nothing
(Tufte, 1983). It binds because the current page spends ink on
hatching, boxes, and repeated numbers until the data is the
quietest thing on screen. The failure it names is chartjunk, the
next term.

**Chartjunk.** Visual material that encodes no information and
competes with the data for attention (Tufte, 1983). It binds
because the flagged rows on the current page are its loudest
object and they carry the least information per pixel. The
failure it names is decoration that a reader must spend
attention to ignore.

**Lie factor.** The size of the effect shown in the graphic
divided by the size of the effect in the data, which should stay
near one (Tufte, 1983). It binds directly to the accepted heat
ramp decision, since a power curve in a color scale is a
deliberate, disclosed departure that must be fenced by printed
values and an honest legend. The failure it names is a scale
that makes a 5 point gap look like a 20 point gap.

**Small multiples.** A set of small charts with identical
structure and scales, differing only in the data, so comparison
costs no relearning (Tufte, Envisioning Information, 1990). It
binds because the calibration section is 36 panels of exactly
this form. The failure it names is multiples whose scales drift
between panels, which turns comparison back into guesswork.

**Axis honesty.** Baselines, extents, and scale transforms must
be the ones the reader assumes, or must announce themselves
(Cairo, 2016, and Huff, How to Lie with Statistics, 1954). It
binds because the board uses a zero based ranking axis, a log
cost axis, and a transformed heat ramp on one page. The failure
it names is the axis that is technically labeled and practically
misread.

**Uncertainty communication.** Estimates must travel with their
precision, shown in the graphic and not only in the fine print
(Spiegelhalter, The Art of Statistics, 2019, and Padilla and
others on uncertainty visualization). It binds because a rank
without an interval is a claim this dataset cannot support, and
the board's tie bands exist to say so. The failure it names is
the confident point estimate standing alone.

**Calibration display.** A reliability diagram plots stated
confidence against observed frequency, with the diagonal as
perfect calibration and bin sizes visible (Murphy, 1973, and
Gneiting and others on probabilistic forecasting). It binds
because the calibration section argues that model confidences
can or cannot be trusted. The failure it names is a panel that
hides how few cases sit behind a dramatic point.

### Arranging the page

**Information design.** The design of information so that people
can find, understand, and use it efficiently (Horn, and the
International Institute for Information Design). It binds
because the page is an instrument before it is a document. The
failure it names is information that is present and still not
usable.

**Editorial design.** The newspaper and magazine craft of
hierarchy, rhythm, and entry points across a long page. It binds
because the rebuilt page is still a long scroll, and a scroll
without rhythm reads as a dump. The failure it names is 36 equal
sections at equal weight, which is the current page's F-12
disease.

**Data storytelling.** A narrative order in which the takeaway is
stated before the evidence and each view answers the question
the previous view raised (Knaflic, Storytelling with Data,
2015). It binds because the section order in the Ledger design
is a claim about what a skeptical reader asks first. The failure
it names is a page that can be read in any order because it
argues nothing.

**Information architecture.** The organization, labeling, and
navigation of information environments (Morville and Rosenfeld,
Information Architecture for the Web and Beyond, 2015). It binds
because a reader who cannot predict what a section holds will
not scroll to it. The failure it names is the label that names
the data instead of the question.

**Information scent.** The degree to which a label or link lets a
reader predict what lies behind it (Pirolli and Card,
information foraging theory, 1999). It binds because the nav and
the section titles are promises. The failure it names is the
click that surprises.

**Visual hierarchy.** The deliberate ordering of attention by
size, weight, position, and contrast, so the eye lands where the
designer intends first (gestalt tradition, surveyed by Nielsen
Norman Group). It binds because on the current page the loudest
element is a flagged bar, not the finding. The failure it names
is a page where everything shouts in the same register.

**Gestalt principles.** The perceptual grouping laws of
proximity, similarity, enclosure, and continuity (Wertheimer and
the Berlin school, 1923 onward). It binds because grouping is
how the ranking separates populations without a word of
explanation. The failure it names is grouping the eye performs
against the grouping the data intends, as when unranked rows sat
interleaved in ASR order and read as ranked.

**Cognitive load.** Working memory holds only a few chunks at
once, and extraneous load spent on decoding layout is load
stolen from the data (Sweller, 1988, and Cowan, 2001, on the
four chunk limit). It binds because every section asks the
reader to hold a scale, a population, and a caveat at the same
time. The failure it names is the caption wall of census F-10,
which spends the reader's memory on tie bookkeeping.

**Progressive disclosure.** Complexity stays hidden until the
reader asks for it, one level at a time (Nielsen Norman Group).
It binds because the card index is the page's depth mechanism.
The failure it names is disclosure that hides the existence of
the depth along with the depth itself.

### Type and color

**Typography and typesetting.** The craft of arranging type so
text is legible, readable, and hierarchically clear (Bringhurst,
The Elements of Typographic Style, 1992). It binds because the
design lane found the numerals themselves, set in mono, to be
the largest single cause of the debug console feel. The failure
it names is type that makes audited data look like a log file.

**Tabular figures.** Digit glyphs of equal width that align on
the decimal point in columns (a standard OpenType feature,
documented in Bringhurst and in font specifications). It binds
because a benchmark page is columns of numbers before it is
anything else. The failure it names is the column whose ones and
sevens wander, forcing the reader to compare digit by digit.

**Color theory for data.** Sequential schemes for ordered data,
diverging schemes for data with a meaningful midpoint, and
categorical schemes for unordered classes, matched to the data
type (Brewer, ColorBrewer, 1994 onward, and Munzner, 2014). It
binds because the heat ramp, the flag amber, and the strength
accent are three different data types sharing one screen. The
failure it names is a rainbow where an order was needed, or a
semantic color spent as decoration.

**Redundant encoding.** A distinction carried by two channels at
once, such as color plus text or color plus position, so no
reader depends on one channel alone (WCAG 1.4.1 Use of Color,
and standard visualization practice). It binds because flagged
status and slice status are load bearing facts on this board.
The failure it names is the distinction that vanishes for a
colorblind reader or in a grayscale print.

### The reader's terms

**Readability and plain language.** Writing that its intended
readers can find, understand, and use on first reading (the
United States Plain Writing Act of 2010, and the GOV.UK content
design guidance, which targets a reading age of nine for public
content). It binds because the method notes decide whether a
smart outsider trusts the numbers or walks away. The failure it
names is jargon that arrives before its definition, the census
C-07 pattern.

**Content design and microcopy.** The discipline of the words in
the interface itself, labels, captions, buttons, and empty
states, treated as functional components (Winters, Content
Design, 2017, and GOV.UK content design practice). It binds
because on this page a caption is where a chart's population and
base size live or die. The failure it names is the caption that
describes the chart's contents instead of stating its finding.

**Interaction design.** The design of how elements behave over
time in response to a person (Cooper, About Face, 1995 onward).
It binds because hover, focus, tap, and expansion are the
board's moving parts. The failure it names is information that
exists for the mouse and not for the finger or the keyboard.

**Web accessibility.** The W3C standard that content be
perceivable, operable, understandable, and robust for people
with disabilities, with WCAG 2.2 level AA as the floor (W3C
Recommendation, October 2023). It binds because a public
credibility artifact that excludes readers fails on its own
terms. The failure it names is any of the criteria in Part 2
under the AX group.

**Dashboard design.** A display of the important information
needed to achieve objectives, consolidated so it can be
monitored at a glance (Few, Information Dashboard Design, 2006).
It binds loosely here, and the looseness matters. This page is
not a monitoring dashboard, and applying dashboard habits to it
is how the KPI tile grid happened. The failure it names is the
at a glance grid forced onto an argument that needs reading.

### The artifact's terms

**Design systems and token discipline.** A shared set of named
design tokens and components that acts as the single source of
truth for visual decisions (Frost, Atomic Design, 2016, and the
GOV.UK and United States Web Design System documentation). It
binds because three builders across one night will drift unless
the tokens decide. The failure it names is the unlisted color,
which the Ledger calm rules already call a defect.

**Trust and credibility signals.** The visible evidence that a
claim can be checked, including authorship, dates, provenance,
and a path to the underlying data (Fogg and the Stanford Web
Credibility Project, 2003, and standard research artifact
practice). It binds because this page asks strangers to cite
its numbers in public. The failure it names is the claim with no
handle, no date, no source, and no way out to the evidence.

**Data provenance and reproducibility.** The recorded lineage of
a dataset and the ability of an outsider to regenerate the
result from stated inputs (the FAIR principles, Wilkinson and
others, Scientific Data, 2016, and W3C PROV). It binds because
the page's whole defense is that every number traces to a sealed
artifact. The failure it names is the number that traces to a
hardcoded constant in a renderer, which the census found in the
re run segment counts.

**Search and social presentation.** The metadata and preview
assets that decide how a page appears in search results and in
social feeds, governed by the Open Graph protocol and platform
card specifications (ogp.me, and schema.org structured data).
It binds because the launch channel is a LinkedIn post, and the
click lands on whatever the preview promised. The failure it
names is the share that renders with no image, no description,
and a title that says nothing.

**Perceived performance and performance budgets.** Numeric caps
on weight and timing that keep a page feeling instant, judged by
Core Web Vitals at the 75th percentile, with good thresholds of
2.5 seconds for largest contentful paint, 200 milliseconds for
interaction to next paint, and 0.1 for cumulative layout shift
(web.dev, Core Web Vitals). It binds because a page that feels
slow feels unfinished, whatever its numbers say. The failure it
names is the 806 kilobyte single file whose fonts travel inside
the HTML as base64.

**Print and screenshot fidelity.** The discipline that a page
survives being captured, cropped, printed, and pasted into decks,
with each fragment still identifying itself and its data
(practice across editorial and research publishing). It binds
because David will speak about this board tomorrow and the
audience will meet it as screenshots before they meet it as a
page. The failure it names is the cropped chart with no name, no
date, and no population, free to mean anything.

**Responsive design.** One document that adapts its layout to
the reader's viewport without forking content (Marcotte,
Responsive Web Design, 2010). It binds because half the launch
audience will open the link on a phone. The failure it names is
the phone page as a shrunken desktop, which at 51,000 pixels of
scroll is the current page's honest description.

## Part 2. The criteria

Sixty criteria in twelve groups. Each states the test an auditor
runs and the condition that fails it. Census IDs in parentheses
mean the criterion generalizes a census defect and the census
holds the original evidence. Round numbers refer to the charter.

### DV. Statistical graphics integrity

**DV-01 · BLOCKER · Bars and lengths start at zero**
Test. Inspect every bar, strip, and length encoded chart and read
its axis origin. Fail. Any length encoding whose axis starts
above zero, on any surface at any width.

**DV-02 · BLOCKER · No rank stands without its interval**
Test. Find every printed rank and every ranked value on every
surface. Each must carry its 95 percent interval on the same
surface, in the chart, on the card, and in compare. Fail. One
rank or ranked figure printed with no interval in reach.

**DV-03 · BLOCKER · Derived figures recompute from stated inputs (F-02)**
Test. Pick three printed derived figures, including one
robustness tax and one compare delta. Recompute each from the
benchmarks and inputs the page itself states. Fail. Any figure
that only reconciles against inputs the page does not name, or
that misses its stated inputs by more than rounding.

**DV-04 · SHOULD · Transformed scales announce themselves**
Test. Read the heatmap legend and the scatter axes. The legend
must name the ramp transform in plain words and state that
printed cell values are exact. The scatter cost axis must be
labeled as a log scale with currency decade ticks a lay reader
can price. Fail. A transformed scale that a reader can
reasonably take as linear, or a log axis with no plain label.

**DV-05 · SHOULD · Axis extents hug the data (V-04)**
Test. Measure empty axis range at both ends of every continuous
axis. Fail. More than one half decade of empty log range, or a
linear ceiling that is not the next round number above the data.

**DV-06 · SHOULD · Small multiples share one scale (calibration)**
Test. Compare axis ranges and bin geometry across all 36
calibration panels, and check each panel states its case base.
Fail. Any panel whose axes differ from the set, or whose base is
not printed on or with the panel.

**DV-07 · SHOULD · Headline comparisons ride the strongest channel**
Test. Identify the channel carrying the headline comparison in
each chart. Attack success must ride position or length on a
common scale everywhere it is compared. Fail. Any surface where
the headline quantity is carried by area, angle, or hue alone.

### TY. Typography and information design

**TY-01 · SHOULD · Numerals align on the decimal**
Test. Measure the right edges and decimal positions of one
column of figures in the ranking, the index, and one card grid
by DOM geometry. Tabular figures must be engaged on every data
numeral. Fail. Any column whose decimals wander, or any data
numeral set in a proportional or mono face outside the
identifier register.

**TY-02 · SHOULD · One type scale, no strays**
Test. Census every computed font size and weight on the page at
1440 and at 390. Fail. Any size or weight outside the token
scale in the design system, or more than three sizes inside one
chart.

**TY-03 · POLISH · Measure and line breaks stay civilized (F-17)**
Test. Measure prose line lengths and read every heading at the
three widths. Fail. Prose wider than 75 characters, a heading
line that opens with a separator, or a heading that ends in a
single orphaned word at any width.

**TY-04 · SHOULD · The same quantity prints the same way everywhere**
Test. Sample five quantities that appear on three or more
surfaces, including one true zero and one count over a thousand.
Fail. Any surface that prints a different string for the same
value, a measured zero as a bare 0 percent, or a count without
its thousands separator.

**TY-05 · POLISH · Reading order and document order agree**
Test. Extract the heading outline and compare it with the visual
scan order at 1440. Fail. A heading sequence a screen reader
user would meet in an order the sighted reader does not.

### CO. Color

**CO-01 · BLOCKER · No distinction rides on color alone (WCAG 1.4.1)**
Test. Print or desaturate screenshots of the ranking, the
heatmap, and one card. Flagged status, slice status, and the
worst family must each still be identifiable from a tag, a word,
a position, or a shape. Fail. Any load bearing distinction that
exists only as a hue difference.

**CO-02 · SHOULD · The palette survives color vision simulation**
Test. Run the ranking, scatter, and heatmap through deuteranopia,
protanopia, and tritanopia simulation. Amber, accent green, and
extreme red must stay separable, and the heat ramp must stay
ordered. Fail. Two semantic colors that merge under any of the
three simulations. This criterion is the test method behind
CO-01 and its result is evidence there.

**CO-03 · BLOCKER · Contrast floors hold on every surface (WCAG 1.4.3 and 1.4.11)**
Test. Compute contrast for every text token on every ground it
sits on, and for data marks and focus indicators against their
backgrounds. Floors are 4.5 to 1 for text, 3 to 1 for large text
and for non text marks. Fail. One text token under its floor, or
one caption token carrying a number a reader needs at under 4.5
to 1.

**CO-04 · SHOULD · Every hue on screen has one named meaning**
Test. Sample the distinct hues in screenshots of each section
and map each to the token table. Fail. A hue with no token, a
token used for two meanings, or a semantic color spent as
decoration anywhere, including hover states.

**CO-05 · SHOULD · The heat ramp is perceptually ordered**
Test. Sample the ramp at ten points and check lightness rises or
falls monotonically with value, on one hue family. Fail. A ramp
step that reverses lightness, or a second hue entering the ramp.

### IA. Information architecture

**IA-01 · BLOCKER · The first viewport answers the three opening questions (C-01)**
Test. At 1440 and at 390, read only the first viewport. It must
say what was measured, on how many cases, and what the headline
finding is. Fail. Any of the three answers absent, or reachable
only by scrolling or by opening the method notes.

**IA-02 · SHOULD · Every section has a stable address**
Test. Check each section for a fragment identifier, load the
page at three fragments, and confirm the view lands on the named
section. Compare selections must also live in the address. Fail.
A section with no working fragment, or a compare state that a
link cannot reproduce.

**IA-03 · SHOULD · The reader always knows where they are**
Test. Scroll to the middle of three long sections and read the
stuck navigation. Fail. No current section indication, or an
indication that names the wrong section.

**IA-04 · SHOULD · One fact has one home**
Test. Scan each section for numbers repeated inside the same
section in a second costume, and for facts repeated across
sections without a pointer to the owning section. Fail. A number
printed twice in one section, or a definition restated in
different words in two places.

**IA-05 · SHOULD · Labels predict their contents**
Test. Give a fresh reader the nav labels and section titles
alone and ask what each holds, then compare with the contents.
Fail. A label whose contents surprise the reader, or a title
that names a data type where the section argues a finding.

### IX. Interaction and cognitive load

**IX-01 · BLOCKER · Mouse, finger, and keyboard learn the same facts**
Test. Pick five data marks across the charts. Reach each by
hover, by tap at 390, and by keyboard focus. The information
returned must be identical in content. Fail. One mark whose facts
exist for only one input kind.

**IX-02 · SHOULD · Nothing essential hides behind hover alone**
Test. Disable hover by working at touch widths and by keyboard
only. Every tooltip fact must have a visible or focusable
equivalent. Fail. A fact, including full model identity behind a
shortened name, that no touch or keyboard path can reach (F-05).

**IX-03 · SHOULD · State changes are announced and focus behaves**
Test. Expand three cards and change both compare pickers by
keyboard. Check aria-expanded, visible state, and where focus
lands after each change. Fail. An expansion a screen reader does
not announce, or focus lost to the top of the page.

**IX-04 · SHOULD · The ten second and thirty second tests pass**
Test. With a fresh reader, show the top of the page for ten
seconds and ask for the headline finding. Then ask why one named
model carries no rank, allowing thirty seconds of search. Fail.
Either answer unreachable in its budget. This is the charter
round 29 test, stated here so build rounds can rehearse it.

**IX-05 · POLISH · One idea owns each viewport**
Test. Take screenshots at ten scroll stops at 1440. Fail. A
viewport where two section ideas compete at equal weight, or
where furniture is louder than the section's data (calm rule 5).

**IX-06 · SHOULD · Motion stays disciplined (WCAG 2.3.1)**
Test. Load the page with reduced motion on and off. Nothing
animates on load, nothing flashes, and the reduced motion
setting removes any transition the default setting allows. Fail.
One load animation, one flashing element, or a transition that
ignores the setting.

### AX. Accessibility, WCAG 2.2 AA as the floor

**AX-01 · BLOCKER · Focus is never hidden by stuck chrome (WCAG 2.4.11)**
Test. Tab through every interactive element at 1440 and at 390
with the sticky nav in its stuck state. Fail. One focused
element wholly covered by the nav, a sticky group header, or
any other author placed layer. This criterion is new in WCAG 2.2
and postdates the checks the old program ran.

**AX-02 · BLOCKER · Targets meet the size floor (WCAG 2.5.8)**
Test. Measure every pointer target in the DOM. Fail. A target
under 24 by 24 CSS pixels that no spacing exception covers, or a
primary target under the design system's 44 pixel rule.

**AX-03 · BLOCKER · The page reflows at small widths and high zoom (WCAG 1.4.10)**
Test. Render at 320 CSS pixels and at 200 percent zoom. Fail.
Two dimensional scrolling anywhere except inside the signposted
heatmap panel and the nav chip row, or content lost off either
edge.

**AX-04 · SHOULD · Text spacing overrides break nothing (WCAG 1.4.12)**
Test. Apply the standard text spacing overrides, line height
1.5, paragraph spacing 2em, letter spacing 0.12em, word spacing
0.16em. Fail. Clipped, overlapped, or truncated text anywhere,
with chart labels included.

**AX-05 · SHOULD · Forced colors mode stays legible**
Test. Render in a forced colors environment and read the
ranking, one heatmap region, and the flags. Fail. Data marks
that vanish against the canvas, flags indistinguishable, or
chart structure lost because backgrounds the design relied on
were stripped.

**AX-06 · BLOCKER · Every chart has a complete text equivalent**
Test. For each chart, read its text alternative end to end and
check it against the payload. It must convey the ranking or
pattern, the extremes, and every row's values, and a data list
or table must be reachable for the chart's full contents. Fail.
An alternative that summarizes without the values, or values
that disagree with the payload in any row.

**AX-07 · SHOULD · Landmarks, headings, and a skip link frame the page (WCAG 2.4.1)**
Test. Inspect the document outline and tab order. One h1,
labeled landmarks, and a skip link as the first focusable
element that lands past the nav. Fail. A missing landmark label,
a second h1, or no skip link.

### DS. Design system discipline

**DS-01 · SHOULD · Nothing ships off token**
Test. Census the built stylesheets for color, spacing, radius,
and type values, and diff against the token table in the design
system. Fail. One production value with no token behind it.

**DS-02 · SHOULD · Edge states are designed and absence fails loudly**
Test. Render fixtures with no flagged rows, with a model missing
cost, with a family unmeasured, and with provenance missing its
case count. The first three must render their designed empty
states. The fourth must fail the build rather than drop the
furniture silently, which is the defect behind census C-01.
Fail. An improvised empty state, a silent omission, or a build
that passes on missing provenance.

**DS-03 · SHOULD · The page survives its font failing**
Test. Block the webfonts and reload at the three widths. The
named fallback stack must hold the layout, with no label
collisions, no truncated names appearing, and no chart geometry
shifted. Fail. Any collision or overlap that the loaded font
does not produce, since screenshots taken on a machine where the
font failed must still be honest.

### CT. Content design and microcopy

**CT-01 · SHOULD · Every statistic is glossed at or before first use (C-07)**
Test. List every statistic and coined term the page prints, in
reading order, and mark the position of its gloss. Fail. One
term, ECE and Brier are the standing risks, that appears in a
card or chart before the page has said what it measures.

**CT-02 · SHOULD · One concept keeps one name (C-05)**
Test. Census the strings used for flagged status, slice status,
and the robustness tax across all surfaces. Fail. A second name
for any of the three anywhere, including screen reader text and
chart keys.

**CT-03 · SHOULD · Captions state findings, not contents (F-10)**
Test. Read every section caption. Each must state the finding or
the rule the reader needs, inside one line at desktop width and
two at phone width. Fail. A caption that inventories the chart,
enumerates tie bands, or runs past its line budget.

**CT-04 · SHOULD · Method prose reads plain**
Test. Take the method and notes prose. Sentences should run
under 25 words at the median, every acronym must be expanded at
first use, and no sentence may require a second reading to parse
its claim. Fail. A median over the budget, an unexpanded
acronym, or a claim a fresh reader must read twice.

**CT-05 · POLISH · The copy bar scan stays clean**
Test. Run the Python codepoint scan over all visible text. Fail.
One em dash, one semicolon in prose, or a colon doing prose work
outside labels, times, and values.

### TR. Trust and provenance

**TR-01 · BLOCKER · The page dates and versions itself at the top**
Test. Read the masthead and findings area for the dataset
version, the suite version, the board or publish version, and a
last updated date. Fail. Any of the four absent from the top of
the page, or a date that disagrees with the publish record. The
current page prints no updated stamp anywhere, and a page
without one reads as unfinished whatever else it does.

**TR-02 · BLOCKER · The evidence is two clicks away**
Test. From the page, reach the sealed payload and the code that
generated the page in at most two clicks each, following links
on the page itself. Fail. Either target unreachable, or reached
only through an address the reader must already know. The
current page carries no external link of any kind.

**TR-03 · BLOCKER · Quoted extremes name their population**
Test. Find every range, maximum, and best or worst claim in
prose and tiles. Each must name its population, full suite,
ranked, or slices, in the same breath. Fail. One extreme quoted
bare, which is the prose half of census F-02 generalized to
every claim on the page.

**TR-04 · SHOULD · A reader can cite the board**
Test. Find the how to cite block. It must give a stable citation
string naming the artifact, its version, its date, and its
address. Fail. No citation block, or one the reader must
assemble from scattered provenance fields.

**TR-05 · SHOULD · Changes between versions are stated**
Test. Find the change note or corrections statement, on the page
or one click from it. It must say what changed since the
previous board version and how errors get corrected. Fail. A
board that silently differs from its predecessor, with the
difference discoverable only by diffing payloads.

### SO. Search and social presentation

**SO-01 · BLOCKER · The social preview is complete and purpose built**
Test. Inspect the document head for Open Graph and Twitter card
tags, and open the referenced preview image. The image must be
1200 by 630, generated from the same payload as the page, and
must carry the headline finding rather than a bare logo. Fail.
A missing tag, a missing or generic image, or an image whose
numbers differ from the page. The current head carries no social
tags at all.

**SO-02 · BLOCKER · The search description exists and says the thing**
Test. Read the meta description. It must run under 160
characters and state what was measured and on how many cases.
Fail. No description, which is the current state, or one that
reads as a slogan with no measurement in it.

**SO-03 · SHOULD · The title names the artifact and its subject**
Test. Read the title tag. It must name the board, the subject,
and the suite, in words a stranger can repeat. Fail. A title at
the level of the current one, which is the two words peira
leaderboard and nothing else.

**SO-04 · SHOULD · Machines can identify the dataset**
Test. Check for a canonical address, a favicon set, and
schema.org Dataset structured data that parses without errors
and whose figures match the payload. Fail. Any of the three
missing, or structured data that disagrees with the page.

### PF. Performance and perceived performance

**PF-01 · SHOULD · Lab vitals meet the good thresholds**
Test. Run a lab pass on a mid tier mobile profile against the
built page. Largest contentful paint at or under 2.5 seconds,
cumulative layout shift at or under 0.1, and total blocking time
at or under 200 milliseconds as the interaction proxy (web.dev
thresholds, judged at the 75th percentile in the field once
field data exists). Fail. Any of the three over budget.

**PF-02 · SHOULD · The weight budget is stated and met**
Test. Measure the initial transfer of the built page. The budget
must be written in the build record before the dress rehearsal,
fonts must be subset and travel as font files at or under 120
kilobytes in total, and no font may ride inside the HTML as
base64. Fail. An unstated budget, a missed budget, or the
current page's pattern of fonts inlined into an 806 kilobyte
document.

**PF-03 · SHOULD · Font loading moves nothing**
Test. Record layout during font swap with throttled loading.
Fallback metrics must be size adjusted so text blocks move by no
more than a few pixels, and the shift must count inside the
PF-01 layout shift budget. Fail. Visible reflow of any chart or
table when the real face arrives.

**PF-04 · SHOULD · The page reads with JavaScript off**
Test. Disable JavaScript and read the page end to end. Every
chart, card, and note must be present, and the one interactive
exception, the compare picker, must degrade to a stated fallback
rather than an empty frame. Fail. Content that exists only
after hydration.

### SF. Screenshot and print fidelity

**SF-01 · BLOCKER · A cropped section still identifies itself**
Test. Crop three chart sections out of full page screenshots,
including one calibration panel and one heatmap region. Each
crop must show the board name, the section's question or title,
the population and base it rests on, and the board date or
version. Fail. A crop that could be pasted into a deck and
misread, which is the use David has announced for tomorrow.

**SF-02 · SHOULD · Print produces a legible document**
Test. Print to paper and to PDF. The output must be legible on
a light ground, must not cut rows in half, and must show link
addresses where a link carried meaning. Fail. Dark ground
printing, severed rows, or links that become dead text. A print
rule exists in the current page and is untested, which is not
the same as passing.

**SF-03 · SHOULD · The page holds across engines**
Test. Render the built page in Chromium, Firefox, and WebKit at
the three widths. Fail. An overlap, a missing glyph shown as a
placeholder box, or a chart that differs in geometry between
engines.

**SF-04 · SHOULD · Every representation of the data agrees**
Test. Compare the figures in the social preview image, the
structured data, and any printed summary against the page
itself. Fail. A number that differs between representations,
since each representation is generated separately and can drift
separately.

## Part 3. Gap scan

The checklist applied to two subjects. The current live page, as
the census measured it and as this lane re-read its head and
structure on 2026-10-23. The Ledger design system, as specified,
noting that a specification is a promise and not a pass. Coverage
classes are Covered by census, Covered by Ledger, Partial in one
or the other, and Net-new, meaning neither document tests it or
specifies it.

### Coverage by group

| Group | Census | Ledger | Net-new weight |
| --- | --- | --- | --- |
| DV integrity | Strong. Values verified, F-02 and V-04 found | Strong. Specs carry the rules | Low. DV-04 log label wording is the residue |
| TY typography | Partial. A-06 notes the size floor | Strong. Scale, faces, formats all specified | Low |
| CO color | Partial. Contrast computed, A-02 and A-03 | Strong. Budget and semantic rules | Medium. Simulation and forced viewing untested |
| IA architecture | Strong. C-01 to C-07 | Strong. Order, grouping, one home rule | Low. Current section indication unspecified |
| IX interaction | Partial. Round 3 read, it did not time or tab | Partial. Parity stated as a common rule | Medium. Timed tests and focus behavior after change |
| AX accessibility | Partial. A-01 to A-06 pass the 2.1 era checks | Partial. Keyboard and focus named in chart rules | High. The WCAG 2.2 additions are untested |
| DS system | Not its subject | Strong on tokens, partial on states | Medium. Font failure and loud absence |
| CT content | Strong. Copy audit clean, C-05 and C-07 found | Strong. Copy rules in section 2.4 | Low |
| TR trust | Partial. Provenance verified where printed | Partial. Per run provenance fully specified | High. Page level trust furniture missing |
| SO social | Silent | Silent | Total. The whole group is net-new |
| PF performance | Silent | Silent | Total. The whole group is net-new |
| SF screenshot and print | Partial. Captures exist as evidence | Partial. Titles and bases in chart specs | High. Self identification and print untested |

### What the current page already satisfies

Recorded so the rebuild does not regress it, drawn from census
passes. Every plotted value on the page reconciles with the
payload, including all 36 ranking bars and whiskers, both
heatmaps cell by cell, the calibration bins, and every card field
(DV-01, DV-02, DV-06, AX-06 in substance). Contrast clears AA on
every text token the census computed (CO-03, with the A-03
borderline token barred from text). Heading order, focus
treatment, and chart text alternatives pass (AX-07 in substance,
TY-05). The copy scan is clean (CT-05). These are the floor the
rebuild inherits, and round 32 should test them by these IDs as
well as by the census IDs.

### What Ledger answers that the census could only flag

The grouped ranking with population headers answers IA-01's
placement half and V-03. The findings strip replaces the debug
tiles behind F-09. Bracket drawn ties end the F-10 enumeration.
The no-cost rail answers V-02 and C-03. The name policy and the
cut marker rule answer F-05 and TY-04. The color budget, the
hatching ban, and the middot state for unmeasured values answer
F-08, F-11, and CO-04. The card index answers F-12's scroll
weight, with a stated target of 10,500 pixels against the
current 20,566. The tax benchmark rule, design section 4.5 rule
6, answers F-02 once the data audit confirms the setter rows.

### The net-new gaps, in the order the build rounds will meet them

**G-1 · The social and search layer does not exist (SO-01 to SO-04)**
Evidence from the deployed head, read for this lane. The head
carries a charset, a viewport, and a title, and nothing else. No
meta description. No Open Graph tag. No Twitter card. No
canonical address. No structured data. No favicon. The title is
the two words peira leaderboard. The design system never
mentions the head at all. This is the page whose launch vehicle
is a LinkedIn post, and today the post's preview would be
assembled by the platform from a bare title and whatever text it
scrapes first. Every other discipline in this document can pass
and the launch still lands as an unformatted link. Build rounds
must add the head as a named work item, with the preview image
generated from the payload at build time so SF-04 can hold.

**G-2 · The page has no exits and no trust furniture at page level (TR-01, TR-02, TR-04, TR-05)**
Evidence. The deployed file contains no external link of any
kind, counted for this lane at zero. There is no path from the
page to the sealed payload, to the generating code, to a
citation, or to a change note. There is no last updated date
anywhere on the page, counted at zero occurrences of any updated
stamp. The design system specifies per run provenance in full,
and the register is genuinely good, but provenance inside a
collapsed card is not page level trust furniture. A researcher
landing from a post tomorrow needs four things in the first
screen or the last, the date this board was published, the
version of the board itself, a cite this string, and a door to
the evidence. None exists. David's instruction that the site
address sit prominent in the GitHub repo has a mirror here, and
the mirror is empty today.

**G-3 · No performance budget exists anywhere (PF-01 to PF-04)**
Evidence. The deployed document is 806,037 bytes as a single
file, with both webfonts inlined as base64 data, a pattern that
inflates font weight by roughly a third and puts the fonts on
the critical path of the HTML itself. Neither the census nor
the design system sets a number for weight, paint, or shift. The
stack decision helps by accident, since a static export with
real font files is the Next.js default, but an accident is not a
budget and the first heavy dependency will spend it. The
rebuild's JavaScript runs the compare view and the expansions,
and nothing anywhere caps it. Build rounds must state the budget
in the build record before the dress rehearsal and measure
against it at round 24 and round 39.

**G-4 · Perception edge environments are untested (CO-02, AX-05, AX-04)**
Evidence. The census computed contrast ratios for the page's own
palette and stopped there. Nobody has rendered this board under
deuteranopia or protanopia simulation, on a page whose three
semantic colors are green, amber, and red, the exact trio the
common color vision deficiencies merge. Nobody has rendered it
in forced colors mode, where the dark grounds the design relies
on are stripped by the operating system. Nobody has applied the
WCAG text spacing overrides. The Ledger rules make these passes
likely, since redundant encoding is specified for flags and the
ramp is single hue, but likely is not tested, and the failures
here are silent, since the page looks fine on the builder's own
screen. Rounds 23 and 31 should run these by ID.

**G-5 · WCAG 2.2 moved and the checks did not (AX-01, AX-02)**
Evidence. The old program's accessibility passes predate WCAG
2.2, which became the W3C recommendation in October 2023 and
added criteria this page is exposed to. Focus not obscured,
2.4.11, binds directly because the rebuild keeps a sticky nav on
desktop and adds a sticky chip row on mobile, and a focused
ranking row or nav chip can slide under either. Target size
minimum, 2.5.8, binds because the rebuilt page is dense with
small tap surfaces, heatmap cells excluded by their nature but
chips, tags, and index controls not. The census found 44 pixel
targets on the old nav and passed them under the older framing.
The new framing must be measured, not inherited.

**G-6 · Screenshots do not yet have to identify themselves (SF-01)**
Evidence. The census captures prove the failure mode. A crop of
the current calibration section shows a model name, an ECE
figure, and a curve, with no board name, no date, no population,
and no base in frame. The design system puts a question title
and base sizes on charts, which covers part of the criterion,
but board identity and the board date inside or beside each
chart frame are specified nowhere. David will present this board
to a person tomorrow and the board will travel as crops in posts
and decks afterward. A crop that cannot say what it is, what it
rests on, and when it was made is a rumor with axes. The fix is
cheap at build time and impossible later, a small running
identification in each chart's frame furniture.

**G-7 · The page cannot be taken away (extends TR-02)**
Evidence. There is no download on the page, no CSV, no link to
the payload JSON, counted at zero for this lane. The readers
most likely to cite the board are the readers most likely to
want its numbers in a table of their own. The design system's
content inventory lists what the page must present and does not
list the data itself as a presentable artifact. One link in the
provenance area closes it.

**G-8 · Absence must fail loudly, and only half of that is specified (DS-02)**
Evidence. Census C-01's cause was a renderer that silently
dropped a tile and a caption clause when provenance lacked a
case count. The design system specifies empty states for rows
and components with care. It does not state the build rule that
missing provenance is a build failure rather than a quieter
page. Without the rule, the next absent field will also pass
silently, and the failure will again be discovered by an audit
instead of by the build.

**G-9 · The font is a single point of failure (DS-03, PF-03)**
Evidence. The design rests its numeral argument on Archivo with
tabular figures, self hosted and, today, inlined. No fallback
stack is named in either document, and no test blocks the fonts
to see what survives. If the face fails or arrives late on a
reader's machine or in a screenshot pipeline, the alignment
argument in TY-01 fails with it and nobody will know which
screenshots were taken in the fallback. A named metric adjusted
fallback and one blocked font test close it.

**G-10 · Two representations are about to be born and can drift (SF-04)**
Evidence. The freeze will add representations of this data that
the census never had to check, the social preview image under
G-1 and the structured data under SO-04, plus the LinkedIn post
itself. Each is generated by a different path from the page.
The census discipline of recompute everything from the payload
must extend to them at the dress rehearsal, or the launch will
ship a preview image whose headline number the page itself does
not print.

### Standing risks the criteria create on purpose

Three criteria will be argued with, and the argument is recorded
here so the rounds can settle them once. DV-04 asks the heat
legend to name its transform, which costs the legend a clause of
plain words and buys honesty about the power 0.65 decision. IX-04
asks for timed fresh reader tests, which are the only criteria
in this list that need a person who has not seen the page, and
they should be run at rounds 8, 9, and 29 rather than once at
the end. SF-01 asks every chart frame to carry identification
furniture, which spends a little of the calm the Ledger rules
buy, and the trade is worth it for a board whose afterlife is
screenshots.
