# Noise Paraphrase Map: Per-Key Fuzz Checklist (F18)

Date: 2026-10-02 (round 3, NOISE-ROBUSTNESS FIX lane).
Status: the checklist below is the systematic sweep the round-3
red-team required (F18). Two earlier rounds fixed only reported
instances while same-class hazards survived; this pass enumerates,
per key, (1) the mapped meaning, (2) idioms and terms of art
containing the key, (3) part-of-speech ambiguities, and (4) the
guard conditions that resulted. Every row was fuzzed at rate=1.0
(guards are deterministic, so a hole reproduces on every seed);
what broke was fixed, and the sentences below are encoded as
regression tests in `tests/test_noise.py`.

Method: dictionary/thesaurus-style expansion per key — fixed
phrases (idiom dictionaries), domain terms of art (finance,
medicine, law, physics, chemistry, linguistics, computing,
publishing, sports), and POS alternations (verb/noun/adverb
senses, predicative vs attributive slots). The guard machinery
itself (single-pass, whole-word, hyphen-aware boundaries,
proper-noun runs, case preservation) is covered by the existing
suite; this checklist covers the *lexical* hazard surface.

Standing rule (from the round-3 red-team): any key with a verb
sense or more than ~4 guard clauses is a drop candidate, not a
guard candidate. "fast" and "consistent" were dropped under this
rule in this round.

## Per-key checklist

### strong -> solid / robust
1. Meaning: high intensity / power.
2. Idioms/terms: "strong suit" (idiom), "strong buy/sell" (finance
   ratings), "strong acid/base/electrolyte" (chemistry), "strong
   force/interaction" (physics), "strong verb/noun/declension"
   (linguistics), "strong arm of the law" (idiom), "strong
   language" (profanity), "strong-willed" (hyphen, boundary-safe),
   "strong password" (security — "robust password" is standard,
   fires).
3. POS: adjective only; no verb/noun senses.
4. Guards: veto next word in {suit, buy, sell, acid, base,
   electrolyte, force, interaction, verb, noun, declension, arm,
   language}.

### weak -> feeble
1. Meaning: low intensity / power.
2. Idioms/terms: "weak acid/base/electrolyte" (chemistry), "weak
   force/interaction" (physics), "weak verb/noun/declension"
   (linguistics), "weak link" (idiom), "weak hand" (poker),
   "weak sister" (finance slang), "weak password" (security).
3. POS: adjective only.
4. Guards: veto next word in {acid, base, electrolyte, force,
   interaction, verb, noun, declension, link, hand, sister,
   password}.

### quickly -> rapidly / swiftly
1. Meaning: at high speed.
2. Idioms/terms: none found.
3. POS: adverb only ("quick" is not a key).
4. Guards: none needed. Fuzz-clean.

### carefully -> cautiously
1. Meaning: with care.
2. Idioms/terms: none found.
3. POS: adverb only.
4. Guards: none needed. Fuzz-clean.

### large -> big / sizable
1. Meaning: great size.
2. Idioms/terms: "at large" (fugitive), "by and large", "loom
   large", "large cap(s)" (finance), "large language model",
   "large intestine" (anatomy), "large print" (publishing),
   "large fries" (menu size), "Large Hadron Collider" (proper
   noun, run-guarded).
3. POS: adjective only.
4. Guards: veto prev "at"; veto "by and" two-back; veto prev
   loom/looms/loomed/looming; veto next in {cap, caps,
   intestine, print, fries}; veto "language model(s)".

### small -> little
1. Meaning: little size.
2. Idioms/terms: "small talk", "small world", "small hours",
   "small wonder", "small potatoes" (idioms); "small business"
   (SBA), "small claims court", "small cap(s)" (finance),
   "small print" (publishing), "small molecule" (pharma), "small
   forward" (basketball); "think small" (adverbial slogan).
3. POS: adjective; adverb in "think small".
4. Guards: veto prev think/thinks/thought/thinking; veto next in
   {talk, world, business, claims, hours, wonder, potatoes,
   cap, caps, print, molecule, forward}.

### important -> significant / key
1. Meaning: of great significance.
2. Idioms/terms: none hazardous found ("all-important" is
   hyphen-safe).
3. POS: adjective only.
4. Guards: veto prev "an" (article clash — both alternatives
   start with a consonant). Fuzz-clean otherwise.

### difficult -> challenging
1. Meaning: hard to do.
2. Idioms/terms: none found.
3. POS: adjective only.
4. Guards: none needed. Fuzz-clean.

### good -> solid
1. Meaning: of high quality.
2. Idioms/terms: greetings ("good morning/afternoon/evening/
   night/day", any position); "good on paper", "good on you";
   "in good faith/standing", "good cholesterol"; "good cop",
   "good old X", "good grief/heavens/god/lord", "good riddance",
   "good sport", "good egg", "good will" (benevolence), "good
   offices" (diplomacy), "in his good books/graces", "in good
   stead", "a good turn", "a good word", "good show", "a good
   deal/many" (quantifiers), "good and ready" (intensifier),
   "too good to be true"; "Good Friday", "Good Samaritan"
   (proper nouns, run-guarded).
3. POS: adjective; noun senses ("for good", "the common good",
   "good vs evil", "do good").
4. Guards: greeting veto with NO sentence-start condition
   (mid-sentence greetings break; cost: "a good day's work"
   stays unswapped); veto next in {on, cholesterol, cop, old,
   grief, heavens, god, lord, riddance, sport, egg, will,
   offices, books, graces, stead, turn, word, show, deal, many,
   and}; veto pw=="in" and nw in {faith, standing}; veto
   pw=="too" and nw=="to"; noun vetoes (for/common/vs); "do
   good" fires only before {work, job, jobs, deeds, thing,
   things}.

### bad -> poor
1. Meaning: of low quality.
2. Idioms/terms: "bad blood", "bad egg", "bad hair day", "bad
   trip", "in bad taste", "bad press", "bad look", "bad
   influence" (idioms); "bad faith" (legal), "bad debt/loan/
   bank" (accounting/finance), "bad actor" (security), "bad
   cholesterol" (medicine); "go bad", "too bad", "not bad"
   (litotes); "bad-mouth" (hyphen-safe), "badly" (no match).
3. POS: adjective only.
4. Guards: veto next in {blood, egg, hair, trip, taste, press,
   look, influence, faith, debt, loan, bank, actor,
   cholesterol, sport, cop, boy, girl}; veto prev in {go,
   goes, going, went, gone, too, not}.

### new -> recent
1. Meaning: recently made / current (not old).
2. Idioms/terms: "new moon" (astronomy), "new wave" (genre),
   "new math", "new normal", temporal "new year" (lowercase;
   "New Year" holiday is run-guarded); "new kid on the block",
   "new lease on life", "new blood", "brand new"; "something/
   nothing/anything new" (set phrases); "what is new" (greeting);
   "New Deal", "New York" (proper nouns, run-guarded).
3. POS: adjective only.
4. Guards: proper-noun run; veto next in {moon, wave, math,
   normal, year, kid, lease, blood}; veto prev in {brand,
   something, nothing, anything}; veto "what is/s new".

### low -> reduced
1. Meaning: small in amount/height.
2. Idioms/terms: "low blow(s)", "low point(s)", "low key(s)",
   "low tide(s)", "low ebb(s)" (singular and plural), "low
   profile", "low road", "low bar" (idioms); weather-noun "a
   low"; noun "low" ("a new low", "a record low", "all-time
   low"); "low-hanging" (hyphen-safe), "Low Countries"
   (capitalized, run-guarded).
3. POS: adjective; noun ("a new low", weather "low").
4. Guards: veto next in {blow, blows, point, points, key,
   keys, tide, tides, ebb, ebbs, profile, road, bar}; veto
   noun-"low" (prev in {new, record, time} with no following
   noun — "a new low price" still fires); weather-noun veto
   (determiner + non-adjective slot). P3 residual (red-team
   noted, not required): predicative "reduced" is awkward
   ("The bar was set low" -> "was set reduced").

### often -> frequently
1. Meaning: many times.
2. Idioms/terms: none found.
3. POS: adverb only.
4. Guards: none needed. Fuzz-clean.

### rarely -> seldom
1. Meaning: not often.
2. Idioms/terms: none found.
3. POS: adverb only.
4. Guards: none needed. Fuzz-clean.

### almost -> nearly
1. Meaning: very nearly.
2. Idioms/terms: none found.
3. POS: adverb only.
4. Guards: none needed. Fuzz-clean.

### main -> primary
1. Meaning: most important.
2. Idioms/terms: "main course/event", "main drag", "main
   squeeze", "main character" (slang), "in the main" (= mostly);
   "main memory" (computing), "main sequence" (astronomy),
   "main clause" (grammar), "main line" (railway), "the main
   thing" (set phrase); "water/gas main" (noun); "Main Street"
   (proper noun, run-guarded).
3. POS: adjective; noun ("water main", "in the main").
4. Guards: proper-noun run; veto prev water/gas; veto "in the
   main"; veto next in {course, event, drag, squeeze, memory,
   sequence, clause, line, character, thing}.

### recent -> latest
1. Meaning: not long ago.
2. Idioms/terms: "recent graduate", "in recent memory", "the
   recent past" (fixed terms); "a recent study", "most recent"
   (article/stacking clashes); "in recent years" (time spans).
3. POS: adjective only.
4. Guards: veto prev in {a, an, most}; veto next in {years,
   months, weeks, days, hours, minutes, decades, centuries,
   times, graduate, graduates, memory, past}.

### significant -> notable
1. Meaning: important / meaningful.
2. Idioms/terms: "significant other", "significant
   figures/digits" (incl. singular "digit"); "statistically
   significant", "significant difference", "significant level"
   (statistics).
3. POS: adjective only.
4. Guards: veto next in {other, figure, figures, digit,
   digits, difference, level}; veto prev "statistically".

### excellent -> outstanding
1. Meaning: very good.
2. Idioms/terms: none found.
3. POS: adjective only.
4. Guards: none needed. Fuzz-clean.

### poor -> subpar
1. Meaning: low quality.
2. Idioms/terms: poverty sense ("the poor family" — people
   nouns incl. baby/babies, soul/souls); pity construction
   ("the poor old/dear/young/little man"); "poor sport"
   (idiom); "poor man's X" (covered via people-noun "man").
3. POS: adjective only.
4. Guards: veto next in _POOR_PEOPLE_NOUNS; veto next in
   {old, young, little, dear} (pity adjectives); veto next
   "sport".

### steady -> stable
1. Meaning: firmly fixed / regular.
2. Idioms/terms: "steady state" (physics), "steady hand(s)"
   (craft idiom), "steady gaze", "steady stream", "steady
   boyfriend/girlfriend/partner/date" (relationship senses),
   "going steady" (dating idiom), "steady as she goes".
3. POS: adjective AND verb ("Steady the ladder", "Steady your
   nerves", "to steady").
4. Guards: veto verb uses (next word in _FOLLOW_STOPS —
   imperative "steady" takes a determiner, attributive
   "steady" takes a noun); veto next in {hand, hands, gaze,
   state, stream, boyfriend, girlfriend, partner, date};
   veto bare "going steady".

### thorough -> comprehensive
1. Meaning: complete / detailed.
2. Idioms/terms: none ("thoroughbred", "thoroughfare" have no
   word boundary — never match).
3. POS: adjective only.
4. Guards: none needed. Fuzz-clean.

### detailed -> thorough
1. Meaning: having many details.
2. Idioms/terms: "detailed balance" (physics).
3. POS: adjective AND verb participle ("She detailed the
   costs", "detailed in the appendix").
4. Guards: veto verb uses (next word in _FOLLOW_STOPS);
   veto next "balance".

### brief -> short (restored this round)
1. Meaning: of short duration.
2. Idioms/terms: legal-noun "filed a brief", "amicus brief",
   "the brief argues"; adverbial "in brief".
3. POS: adjective; noun (legal); verb ("brief the team").
4. Guards: restored 2026-10-02 after the round-3 red-team
   flagged the round-2 drop as a mild over-drop. The adjective
   fires only before a whitelisted noun (_BRIEF_NOUNS:
   meeting/overview/summary/note/pause/break/moment/visit/
   statement/remarks/introduction/history/silence/look/
   glimpse/chat/call/spell/stint/respite/interlude/recap/
   primer/rundown/bio/sketch/synopsis and plurals) or in the
   predicative copula slot ("the meeting was brief"); noun
   and verb senses are vetoed by exclusion.

## Residual risk (documented, not assumed away)

- Unlisted idioms and lone capitalized words can still slip
  through; the #52 human validation sample is the backstop.
- "What is new"-style greetings beyond the covered patterns,
  and predicative "reduced" ("The bar was set low"), are known
  P3 residuals.
- Guard sets are flat next/prev-word vetoes by design: cheap,
  deterministic, no POS tagging. A key that needs more than
  this shape gets dropped (the "fast"/"consistent" rule).
