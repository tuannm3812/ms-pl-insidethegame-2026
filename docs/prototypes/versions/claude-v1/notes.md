# Claude v1: the interface before refinement

Open `index.html` directly in a browser. It is PR #9's page
(`static/index.html` at `2719d04`) unchanged apart from two script tags
that load `fixtures.js` (recorded API replies) and `offline.js` (serves
them in place of the API). No server, model or network is needed; Google
Fonts load if online and fall back to system fonts if not.

**What it shows.** Seed 27, Riverside FC (home) focus by default. Three
calls with Option A preselected and recommended, Watch line, clips, and a
Check at 60' that measures each Watch target and gives the verifier's
verdict. Pre-match vs now, team report, player cards, fan mode in five
languages, broadcast overlays and the first-half replay all work from the
fixtures.

**Simulated.** Every reply is a recording of the rule-based agents (no
model). Fan mode is recorded for each language with the default player
only; another player shows "not in this offline snapshot". Checks are
recorded for every A/B combination for both focus teams.

**Known issues, kept for comparison.** A missed target always says
"Consider option B"; Option A is chosen before the analyst picks; no
adopt or implementation record; no evidence-sufficiency rule (the 2-shot
xG check still gets a verdict).

**Checks run.** `capture.py` in Chromium: the five agreed views at
1440 x 1000 and 390 x 844, document width equals viewport at 1440, 1024,
900, 861, 768, 390 and 375 px, no page errors (`capture.json`).
Rebuild with `python docs/prototypes/versions/claude-v1/record_fixtures.py`
from the repository root at `2719d04`; trace timings (`ms`) differ between
recordings, nothing else.
