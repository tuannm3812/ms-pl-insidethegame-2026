# Claude v3: Codex pass 9 fixes and the content audit

Open `index.html` directly in a browser. Unlike v1 and v2, this is the
app's own page (`static/index.html` at `9332995`) plus the two fixture
scripts. Every field comes from the API, recorded offline by
`record_fixtures.py` (seed 27, rules agents, no model). Status:
**awaiting Mike's manual review**.

**What changed from v2, and why.**
- **Decisions drive the follow-up.** Only an adopted call counts as a
  chosen option. A call left open, deferred or rejected is monitoring
  only, with no option advice. Adopting needs an option. The "Next" line
  is written in code from the status and decision; the verifier's own
  wording is under details, labelled as wording only. (Codex pass 9,
  findings 2 and the switching note.)
- **"Best when" belongs to each option.** The coach writes it beside
  each option, with rules text as the fallback. It no longer comes from a
  table keyed by the type of call, so it cannot describe the other
  option. (Finding 3.)
- **Keyboard focus survives each redraw.** Enter on an option, then Tab,
  reaches Adopt. "Discuss first" moves focus to that call's heading.
  (Finding 4.)
- **A scoreline call naming the opponent no longer breaks the check.**
  (Finding 1; backend only, not visible on seed 27.)
- **One display rule per metric** everywhere: bars, team report,
  pre-match rows, evidence, player cards, follow-up, tooltips, feed and
  broadcast graphics. Counts are integers, percentages one decimal, xG
  two, xT three, rates two with their unit, PPDA and speed one, and
  simulated means one. Values round half up and keep full precision until
  shown (Haddad 35/44 = 79.5%).
- **Player cards** show tackles, interceptions and fouls separately. The
  insight leads with what matters for the role (e.g. Brennan, ST: shots
  first), in "recorded actions", using only the card's numbers. Chip
  order follows the role.
- **Phone width:** the pre-match values wrap under their row instead of
  widening the page.

**Simulated or editorial.** Decisions live in the page only. The
evidence floors, the 40% channel limit and the cost check are proposed
policy. The "or maybe" explanations and the rules coach's "best when"
are editorial rules text. The role-led ordering is a design choice, not
a player rating. The synthetic second half is fixed, so a check shows
whether a target is met, not what an option caused.

**How the offline check works.** The rules verifier treats each call on
its own. The check is recorded per call for every decision state
(option, status, in place), and `offline.js` puts each reply together
from the three parts. A state that was never recorded fails visibly.

**Checks run.** `capture.py` in headless Chromium (Playwright 1.64 with
a cached chromium-headless-shell; Google Fonts blocked), recorded in
`capture.json`:
- the five agreed views at 1440 x 1000 and 390 x 844;
- Adopt disabled before a draft, and the best-when text per option;
- keyboard: Enter drafts with focus kept, two Tabs reach Adopt, Enter
  adopts with focus kept, and focus is kept after checking "in place";
- adopted press: "Target not met", review with staff;
- threat not adopted: "Monitoring only";
- drafting B clears the check, and a delayed check is dropped;
- Brennan and Navarro chips and insight, and the headline bars;
- Away shows no stale check, and its press check reads "Too close to
  call";
- document width equals the viewport at 1440, 1024, 900, 861, 768, 390
  and 375 px, with no page errors.

**Known issues.** Decisions are not stored server-side. The target id
encodes finding, focus and version only. Evidence labels written by a
model may repeat a unit that the formatter also shows.
