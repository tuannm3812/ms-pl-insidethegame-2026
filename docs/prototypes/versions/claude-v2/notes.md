# Claude v2: decide and follow up inside each call

Open `index.html` directly in a browser. Built from Claude v1 with the
coaching-workflow ideas agreed in the agent log (Codex's request and
Claude's reply, 2026-10-20). Same seed 27 fixtures plus `proto:<focus>`
data computed in `record_fixtures.py`. Status: **awaiting Mike's manual
review**; not in the live app.

**What changed from v1, and why.**
- A compact priority summary of the three calls. The analyst picks which
  one to "Discuss first"; that call is open, the others are one click
  away. Labelled unranked, because no ranking rule has been evaluated.
- Each call separates **What we saw** (measured, with its window) from
  **Why** (the explainer agent's leading explanation) and **Or maybe**
  (one alternative explanation and what would tell them apart).
- No option is chosen for the analyst. Each option shows its cost and
  **Best when**. Draft, then **Adopt**, **Defer** or **Reject**; whether
  the change was in place at 46' is recorded separately. Labels come from
  the decision state, so "drafted" and "adopted" never contradict.
  Drafting another option clears the adoption, implementation and check.
- The follow-up stays in the call: the exact Watch target (with a target
  reference and where its threshold comes from), the 46'-60' value with
  its count and minutes, the move from the end of the first half, a
  status of met, not met, too close to call or not enough evidence, and
  "review with staff" instead of an automatic switch. The verifier's own
  wording is kept under details.
- A cost check where the option names a measurable cost (our xT per 10
  minutes against 25' to half-time), shown as a comparison, not a verdict.
- Links from each call to the pre-match, team and player reports. On a
  narrow screen the calls come first and the pipeline starts folded.

**Simulated or editorial.** Alternative explanations, "what would tell
them apart" and "best when" are prototype text written by rules, not
model output, and are labelled so. The evidence rule is a proposal:
at least 10 events for a rate (too close to call within one Poisson
standard error), 20 threatening passes for a share or xT, 5 shots for xG.
The 40% channel limit is shown as a proposed limit. Decisions live in
the page only. The synthetic second half is fixed, so a check shows
whether a target is met, not what an option caused.

**Seed 27 results.** Home: own-half losses 1.33 from 20 against under
0.84, not met (1.48 at the end of the first half, better); centre share
61% from 41 passes against under 40%, not met; Northgate xG 0.27 from 2
shots, not enough evidence. Away: Riverside losses 1.33 against at least
1.48, too close to call.

**Known issues.** The page uses recorded checks; the backend still
returns the v1 verdict wording and does not store the adopted target.
Turning these into product needs backend work: a typed decision record,
the evidence policy in `halftime/metrics.py`, and `threat_channels`
returning None when a team has no threat (today it returns 0%, which
would pass a "below 40%" target).

**Checks run.** `capture.py` in Chromium (`capture.json`): the five
agreed views at 1440 x 1000 and 390 x 844; Adopt disabled until an
option is drafted; label after adopting; switching to B clears the
adoption and check; a check reply held 1.5 s and overtaken by a draft
change is dropped; switching to Away shows no stale check and Away's
press check reads too close to call; document width equals viewport at
1440, 1024, 900, 861, 768, 390 and 375 px with a check open; no page
errors.
