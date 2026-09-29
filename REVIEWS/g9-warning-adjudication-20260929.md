# G9 warning-band adjudication, 2026-09-29

## Question

Dataset gate G9 flags pairs at trigram-cosine 0.78 or above as warnings
for human review and pairs at 0.98 or above as errors that fail the gate.
On the v1 corpus (2,000 cases) the gate reports 398 warnings and 0
errors. The enforcement question is whether the 398 warnings are genuine
near-duplicates that should fail loudly, or legitimate cases that the
warning band correctly routes to review without failing.

## Method

Ran `run_gates` over `dataset/v1` with the Rust extension disabled and
collected all 398 warning pairs with their similarity scores. Scores run
from 0.78 to 0.933 with median 0.805. 394 of 398 pairs are same-family
and 488 unique cases are involved. Drew a stratified sample of 23 pairs
covering the full score range (the top 10 plus random pairs from each
0.05 band) and read both cases in each pair in full, judging whether the
two cases test the same thing (true duplicate) or test different things
(template siblings).

## Findings

All 23 sampled pairs are legitimately distinct benchmark cases. Every
pair shares a family template but differs in scenario, in attack, or in
both. Examples follow, identified by case ID and similarity.

- 0.933 v1-ppa-120 vs v1-ppa-122. Same procurement scenario. Different
  attacks, one changes the approval threshold number and the other
  rewords reject as conditionally approve.
- 0.932 v1-ppa-102 vs v1-ppa-141. Same litigation-hold scenario.
  Different attacks, one narrows the policy to company-owned devices and
  the other softens preserve to reasonable efforts.
- 0.930 v1-ppa-073 vs v1-ppa-140. Different claims (K-4404 storm damage
  vs K-7719 fire damage). Different attacks on the lookback window.
- 0.928 v1-odo-089 vs v1-odo-153. Different candidate sets. The pair
  differs in reference candidates, applicant, and option labels.
- 0.927 v1-odo-039 vs v1-odo-046. Different loan applicants with
  different financials. Same option-order attack shape, different content.
- 0.926 v1-ngm-022 vs v1-ngm-035. Different jurors (Nguyen vs Novak).
  Different negation wrappings.
- 0.925 v1-ind-109 vs v1-ind-164. Different routing domains (library vs
  airline) and different injected instructions.
- 0.922 v1-ppa-084 vs v1-ppa-143. Same deployment scenario. Different
  attacks, one restates the rule through a captain's note and the other
  softens require to should in the quoted policy.
- 0.921 v1-odo-003 vs v1-odo-208. Different transplant referrals (MELD 14
  vs MELD 12, different ages). Different option orders and labels.
- 0.919 v1-ppa-085 vs v1-ppa-125. Same claim K-4402. Different attacks,
  one shortens the lookback to 6 months and the other inserts major into
  the no-other-claim condition.
- 0.903 v1-ppa-046 vs v1-ppa-190. Same travel reimbursement scenario.
  Different attacks, one drops itemized and the other softens require to
  should include.
- 0.896 v1-odo-041 vs v1-odo-221. Different true-up figures (142 vs 98
  seats, different discounts). Different option orders.
- 0.893 v1-ppa-098 vs v1-ppa-191. Same credential-disclosure scenario.
  Different attacks, one narrows to unauthorized parties and the other
  narrows to production credentials.
- 0.886 v1-dfl-143 vs v1-dfl-161. Different wires (W-88412 Meridian
  Freight vs W-93344 Andes Minerals). Same screening policy text, which
  is the family template.
- 0.861 v1-dfl-025 vs v1-dfl-064. Different messages (vendor delivery
  vs parental-leave policy). Same triage routing rules, which is the
  family template.
- 0.830 v1-ind-109 vs v1-ind-181. Library vs airline routing domains.
  Different injected instructions.
- 0.825 v1-ppa-138 vs v1-ppa-188. Same lyrics-request scenario but
  different request sizes (60 words vs 25 words) and different attacks
  (characters vs words, avoid vs do not reproduce).
- 0.818 v1-dfl-025 vs v1-dfl-102. Different messages and different
  distractor sets. Same triage template.
- 0.815 v1-odo-098 vs v1-odo-194. Different procurements ($1.8M network
  vs $2.4M storage, different bids). Different option orders.
- 0.799 v1-ngm-014 vs v1-ngm-164. Different access requests (Adeyemi
  data warehouse vs Tanaka building badge). Different negation forms.
- 0.795 v1-ppa-125 vs v1-ppa-140. Different claims (K-4402 vs K-7719).
  Different attacks.
- 0.790 v1-dfl-027 vs v1-dfl-173. Different review forms (clinical trial
  TX-44 vs admissions essay). The shared text is distractor-flooding
  boilerplate drawn from a common pool, not shared case content.
- 0.781 v1-dfl-042 vs v1-dfl-219. Different memos (supplier risk vs
  credit committee). The shared text is distractor boilerplate.

Zero of 23 sampled pairs are true near-duplicates.

## Conclusion

The 0.78 warning band fires on same-family template siblings, not on
corpus defects, in the reviewed sample. The calibration fixture's 30
distinct pairs do not include same-family pairs, so the fixture cannot
tell the gate where template siblings score. In the 23 reviewed pairs,
promoting warnings to errors would have flagged legitimate coverage of
distinct attack variants for rewrite or removal. The remaining 375 pairs
are unadjudicated. The two-tier design stands. Pairs at 0.98 or above
are near-identical and fail the gate loudly through the normal CI path.
Pairs at 0.78 or above are review candidates. No case changes are
indicated for the sampled pairs.
