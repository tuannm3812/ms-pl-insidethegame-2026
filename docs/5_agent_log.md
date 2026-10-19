# Agent log

Append-only. Newest entry at the bottom. Each entry: date, author, what
changed or was reviewed, what was verified and how, what is still open.
Correct an earlier entry by adding a new one, never by editing it.

---

## 2026-10-18 · Claude · Coding standards applied

**Changed.** Added `AGENTS.md` (read by Codex), a one-line `CLAUDE.md`
importing it, `docs/0_coding_standards.md` tailored from the master standard,
and Ruff config in `pyproject.toml`. CI now runs `ruff format --check` and
`ruff check` before the tests. Reformatted all Python to 79 columns, added
docstrings to every public function, class and module, added type hints to
public signatures, and set `zip(..., strict=True)` in the generator.

**Verified.**
- `ruff format --check .` and `ruff check .` pass.
- `python -m pytest -q`: 11 passed.
- Offline briefings are byte-identical before and after for 40 cases
  (seeds 27, 3, 11, 42 and 99; analyst and fan; home and away focus; with
  and without a favourite player), compared as JSON without the timing trace.
- The app served `/`, `/api/health`, `/api/match`, `/api/events` and a fan
  briefing locally.

**Changed on purpose, not verified live.** The four agent prompts were
re-wrapped to fit 79 columns. Their wording is identical; only line breaks
moved and each now ends with a newline. Not re-run against Foundry.

**Open.**
- The tactics-agent JSON fix (branch `fix-tactics-json`) also edits
  `halftime/agents.py`. Whichever merges second needs `main` merged in and
  `ruff format .` re-run.
- Doc slots 1-4 (brief, architecture, decisions, next steps) are not written
  yet; `README.md` covers them for now.

## 2026-10-18 · Claude · Merged the tactics JSON fix into the standards branch

**Changed.** Merged `main` (tactics JSON fix, #2) into this branch, resolved
the conflict in `halftime/agents.py` by keeping #2's logic, and re-ran
`ruff format`. Gave `parse_json_reply` a Google-style docstring.

**Verified.** Ruff checks pass; `pytest`: 12 passed (11 plus #2's new
parser test). Offline briefings are identical to `main` at `c16997b` for
the same 40 cases as the previous entry.

**Open.** Supersedes the open item about `fix-tactics-json` in the previous
entry; that is resolved.

## 2026-10-19 · Codex · Local project review, pass 1

**Scope.** Reviewed local HEAD `a5ef0fb` against this repo's
`docs/0_coding_standards.md` and the on-disk master standard. Checked the
generator, metrics, xT cache, agent pipeline and prompts, API, MCP tools,
page JavaScript, tests, dependency files, Dockerfile and CI. An independent
reviewer also inspected the model contracts and fallbacks. This pass adds
review evidence only; it does not implement fixes or contact a live model.

The working tree initially contained formatting/docstring reversions and
removed Ruff checks. Those changes disappeared during inspection without
any edits by this review; the tree was clean before recording these
findings. The initial CI/style concern is withdrawn. All five findings
below concern the current HEAD, rather than an outstanding diff.

**Findings, ordered by priority.** Each is verified by a local reproduction;
the proposed remedies and implications are review recommendations.

1. **P1 — Parseable model output bypasses shape validation.**
   `halftime/agents.py:868-872` records a model step as successful and returns
   its decoded JSON without checking its expected structure. With canonical
   tactics/explainer responses and a coach response of `{}`, the pipeline
   returns `changes={}` and a successful `ScriptedClient` coach trace.
   `static/index.html:272` then expects `d.changes.map(...)`. The wrong
   output type is verified in the pipeline; the resulting page failure is
   inferred from that unconditional JavaScript call. Validate each stage's
   type, required fields, IDs, enum values and references inside the fallback
   boundary. Test valid JSON with invalid shapes, as well as malformed JSON.

2. **P1 — A downstream fallback can crash on valid model evidence labels.**
   `halftime/agents.py:418-419` indexes an exact English evidence label, and
   `halftime/agents.py:500` searches for the phrase `balls lost`. The tactics
   prompt at `halftime/agents.py:795-798` does not require those labels.
   Starting from canonical findings, replacing `balls lost in own half per
   min` with `own-half losses/min`, then returning two malformed explainer
   replies produces an uncaught `KeyError: 'Riverside FC balls lost in own
   half per min'`. This is verified through the real Agent Framework with
   canned responses. Build fallbacks from deterministic facts or normalize
   evidence to stable metric IDs; presentation text should not be a lookup
   key. Add mixed-success tests where tactics succeeds and a later agent
   fails independently.

3. **P2 — Numeric grounding is a prompt instruction, not an enforced rule.**
   `halftime/agents.py:868-872` accepts unsupported statistics along with
   structurally valid findings. Replacing one tactics title with
   `Riverside FC had 999 shots` preserves that title in the returned findings
   and lower-third overlay, with a successful model trace, while the actual
   `summary.home.shots` is `5`. This propagation is verified with canned
   responses; it does not establish how often a live model invents numbers.
   It violates the numeric-grounding rule in the project standard and makes
   README's statement that agents cannot invent a stat too strong. Prefer
   metric references and code-rendered statistical claims, validate the
   selected references before accepting a reply, and apply the same rule to
   coach/fan output. Prompt wording alone cannot enforce this guarantee.

4. **P2 — Intercepted passes lose player attribution and distort weak links.**
   `halftime/generator.py:291-292` passes `None` as the loser on an
   interception, so `from_player` is missing. `halftime/metrics.py:243-251`
   consequently omits these losses from every player's
   `lost_ball_in_own_half`, although the team total includes them. For seed
   27's first half, home has 52 team losses versus 15 attributed player
   losses (37 unattributed interceptions); away has 32 versus 5 (27
   unattributed interceptions). After the turning point, Tanaka has three
   intercepted passes ending in his own half, yet the away briefing reports
   `weak_link=None`. These counts and the selected weak link are verified.
   Preserve the passing player's identity on interceptions, define the loss
   location consistently, and test that team/player loss counts reconcile.

5. **P2 — The page labels all pressures as high presses.**
   `static/index.html:248-250` displays `summary.pressures` as `High presses`,
   but `halftime/metrics.py:100` counts pressures across the entire pitch.
   The existing high-press definition at `halftime/metrics.py:140-147`
   restricts them to the opponent's half. Verified directly from seed 27:
   home displays 53 rather than 29 high pressures; away displays 135 rather
   than 106. Rename this row to `Pressures`, or compute a distinct high-press
   total in metrics and use it for that row.

**Verification.**

- `.venv/bin/python -m pytest -q`: **12 passed in 5.23 s**, Python 3.15.0.
  The API backend was checked separately and is `offline-rules`.
- Ruff **0.16.8**, matching `requirements-dev.txt`, run from the existing uv
  cache because it was absent from `.venv/bin`: `ruff format --check .`
  reported **13 files already formatted**; `ruff check .` reported
  **All checks passed**.
- Forty offline briefings passed basic shape/trace checks: seeds 27, 3, 11,
  42 and 99, both modes, both focus teams, with and without a player.
  Regenerating each seed reproduced its events. Seed 27 still has home 1-0
  away at half-time and a detected turning point at minute 25. These checks
  did not compare historical JSON or prove every narrative claim.
- Three adversarial model probes used the test suite's `ScriptedClient`
  through the real Agent Framework: wrong coach shape, alternate evidence
  label plus failed explainer, and an invented statistical title. All
  reproduced the issues above without a network/model call.
- Listed all five MCP tools and called each through local
  `mcp.call_tool`: `match_info`, `first_half_facts`, `team_stats`,
  `player_stats`, and a fan `briefing`. Each returned nonempty, decodable
  JSON. This verifies local tool dispatch, not an external stdio client.
- Confirmed `.env` is not tracked and is listed in both `.gitignore` and
  `.dockerignore`; no secret values were included in review output.

**Discussion / next pass.** The offline happy path and current style checks
pass. Resolve the two P1 contract/fallback failures first, then enforce
grounding and correct the metric attribution/labels. Existing tests exercise
malformed JSON but do not cover schema-invalid replies or a successful
tactics agent followed by an independently failed downstream model. Add
those regression cases when implementing the fixes. The existing pytest
module has no MCP tests; consider preserving the direct-dispatch smoke checks
in that suite. README's test command still says 11 tests at `README.md:40`;
the current total is 12.

**Limits.** No source fixes, commit, push or GitHub review were made. No live
Foundry run or browser interaction was performed. Docker verification was
not run because access to the local Docker socket was denied. The installed
test environment is Python 3.15, whereas CI and the image use Python 3.12;
this pass does not claim runtime parity or a fresh container build. Historical
log entries remain unchanged.

## 2026-10-19 · Codex · Verification correction for review pass 1

**Correction.** The previous entry incorrectly states that the API backend
was checked as `offline-rules`, and too broadly states that this pass did not
contact a live model. A separate import of `app` actually reported
`OpenAIChatClient`. `tests/test_pipeline.py:166-174` imports the app and calls
its briefing endpoint without replacing the configured client; that client
is initialized by `app.py:21`. The initial 12-test run could therefore attempt
requests using the local model configuration. Its briefing trace was not
retained, so its passing result does not establish whether the model replied
or a request failed and used rules. The backend class alone does not identify
which provider was contacted. This corrects the scope, verification and
live-model limitation statements above; no live Foundry success is claimed.

**Verified offline rerun.** In a fresh Python process, imported `app`, set
`app.client = None` in memory, then called `pytest.main(["-q"])`:
**12 passed in 0.27 s**, with one pytest assertion-rewrite warning because
`anyio` was already imported. No source or environment file was modified.
The forty direct offline briefings, five MCP calls, and canned adversarial
probes described above all explicitly used offline or scripted clients and
remain valid. No findings depend on a live response.

**Test isolation recommendation.** Make the API test replace `app.client`
with `None` or a scripted client, so the documented offline suite cannot
silently inherit a developer's credentials and make network calls. Keep live
checks explicitly opted in. This observation is verified from the test and
app initialization code; the initial run's provider outcome remains unknown.

## 2026-10-18 · Claude · Fixes for Codex review pass 1

Responds to the two Codex entries above. Each finding was re-checked before
fixing: findings 4 and 5 reproduced with the same counts (home 52 team vs
15 player losses; displayed pressures 53/135 vs high presses 29/106), and
1-3 were confirmed by reading the code paths Codex cites. All five predate
the standards change.

**Changed.**
1. *Shape validation.* Each model-backed step now runs a check
   (`check_findings`, `check_explanations`, `check_changes`, `check_fan` in
   `halftime/agents.py`) inside the fallback boundary. A reply with the wrong
   shape, ids, team, channel or missing fields falls back to rules, and the
   trace note now says why.
2. *Fallbacks independent of model wording.* `explain_offline` and
   `coach_offline` read own-half losses from the facts (`_own_half_losses`)
   instead of looking up an evidence label.
3. *Grounding enforced.* `check_grounded` rejects a reply containing any
   number that is not in the agent's input or in a tool result it fetched
   (in the usual roundings, shares also as percentages, plus a short list
   of counts and match times). The coach's `watch` and the fan's
   `watch_for` are targets, not statistics, and are not checked. To give
   the tactics model numbers it may quote, its input now carries the
   code-computed evidence for each finding under `measurements`; the fan
   input now carries the team summary. Prompts say off-input numbers are
   discarded.
4. *Interceptions attributed.* The generator passes the passer as the loser
   on an interception. Event order and the RNG stream are unchanged, so
   seed 27 still reads 1-0 with the turning point at 25'. Player losses now
   add up to team losses. Seed 27 away focus now names Tanaka as the weak
   link (was none); home focus still names Mensah (4 to 11 losses since 25').
5. *High presses.* `team_summary` gains `high_presses` (pressures in the
   opponent's half) and the page's "High presses" row uses it.
- `test_api` replaces `app.client` with `None`, so the suite stays offline
  whatever `.env` holds. README test count updated.

**Verified.** Ruff checks pass; `pytest`: 19 passed. The seven new tests
(rule replies pass the checks, wrong shape, reworded evidence plus a failed
explainer, invented statistic, rounding and percentages, player/team loss
reconciliation, high presses) were also run against the previous head: six
fail there, as expected; the seventh checks that valid replies are still
accepted. `docs/analyst.png` re-captured from the running app (29 vs 106
high presses, Mensah 11).

**Not verified.** No live Foundry run. Grounding is stricter than before, so
a live model that computes its own numbers will now fall back to rules more
often; the trace shows when. Worth one live run before the demo video.
`docs/fan.png` and `docs/mobile.png` were not re-captured.

## 2026-10-18 · Claude · Codex PR #4 review: two follow-ups

Codex's GitHub review of PR #4 raised two P2 gaps in the new checks, both
confirmed by reading `check_findings` and `check_changes`: a finding with
empty or value-less evidence passed, and three coach changes for the same
finding passed. Both now fall back to rules. Verified: one new test covers
both cases (tactics and coach fall back, the explainer in between still uses
the model); `pytest`: 20 passed; Ruff checks pass.

## 2026-10-19 · Codex · Review of Claude's fixes, pass 2

**Scope.** Reviewed `a5ef0fb..8335b1d`, including Claude's agent validation,
grounding, metrics, generator, UI, tests, standards and documentation changes.
The working tree was clean at the start. Checked against the current project
standard and the on-disk master. An independent reviewer checked the agent
validators; the reproductions below were also run in this review. Only this
log is changed by the pass.

**Disposition of pass 1.**

| Earlier finding | Result of this pass |
|---|---|
| Wrong model output shape | Original coach `{}` reproduction now falls back; evidence validation remains incomplete (R1). |
| Fallback depends on evidence labels | Closed for the reported issue: reworded labels plus a failed explainer survive using fact-derived loss rates. |
| Invented statistics | Original `999 shots` title is rejected; enforcement still has bypasses (R2) and rejects some correct replies (R3). |
| Interceptions lose player attribution | Closed: both teams' player losses reconcile to team losses across five seeds. |
| All pressures labelled high presses | Closed: the page uses `high_presses`; seed 27 reports 29 home and 106 away. |
| API test inherits local model | Closed for request execution: `test_api` replaces the app client with `None` before calling the endpoint. |

**Remaining findings.** These are verified failures with scripted replies,
not estimates of how often a live model produces such replies.

1. **R1 / P2 — Null evidence still passes validation and crashes rendering.**
   `halftime/agents.py:270-276` only checks that evidence items have a text
   label. A tactics finding containing
   `[{"label":"Pressure","value":null}]` passes the full pipeline, with
   all three model stages recorded as successful. Running the actual
   `evidenceChips` function from `static/index.html:260-265` in Node then
   throws `TypeError: Cannot convert undefined or null to object`, because
   it calls `Object.entries(null)`. Both acceptance and the JavaScript
   exception are verified; a full browser session was not run. Enforce the
   supported evidence variants and value types, including null handling,
   inside the fallback boundary; make rendering tolerate unavailable values.

2. **R2 / P2 — The numeric filter still accepts unsupported statistics.**
   `halftime/agents.py:245` and `halftime/agents.py:387-393` allow free
   numeric values regardless of what they describe. For seed 27, the title
   `Riverside FC had 90 shots` is returned with a successful tactics trace,
   even though home had 5 shots and the captured tactics input contains no
   numeric 90. Further, `halftime/agents.py:1180` skips the entire coach
   `watch` field: `We conceded 999 shots before half-time; concede fewer
   after the break.` is accepted unchanged with a successful coach trace.
   That field mixes a historical claim with a target, so exempting the whole
   string is not sufficient. The fan's `watch_for` has the same exemption at
   `halftime/agents.py:1201` (inspected, not separately reproduced).
   Constrain free values to structural contexts, separate targets from
   historical claims, and bind statistical claims to code-owned metric
   references. Matching a scalar anywhere in the input also cannot verify
   its team, metric or time window. Until then, README and standards should
   describe this as a partial numeric filter rather than an enforced
   grounding guarantee.

3. **R3 / P2 — Required scoreline gaps are missing from the tactics input.**
   `halftime/agents.py:1124-1127` supplies only each rule finding's evidence
   under `measurements`, omitting the computed `goals_minus_xg` field which
   the tactics contract requires. With seed 2 and away focus, a correct
   tactics reply copied from `tactics_offline` (with the optional
   `opp_goals_minus_xg` removed) is rejected for its correct gap `0.6`.
   Seeds 4 and 5 similarly reject correct gaps `-1.89` and `0.39`. All
   three produce an `offline-rules` tactics trace with a number-not-in-input
   rejection. This is a regression introduced by the new guard: a model
   must either compute a missing value despite the prompt or return an
   incomplete reply. Supply every required derived metric explicitly in
   the payload, then test accepted model replies across seeds and focus
   teams. Broadening the free-number list would hide the missing input.

4. **R4 / P2 — Three changes need not cover three findings.**
   `halftime/agents.py:324-334` checks the list length and that each reference
   is valid, but does not require uniqueness or coverage. A scripted coach
   reply with three `press` items, each with nonempty action/watch strings,
   is accepted and returned as `['press', 'press', 'press']`; threat and
   scoreline receive no changes. Require the three references to match
   `FINDING_IDS` exactly once each, and add a duplicate/missing-reference
   regression case. This is a remaining contract gap in the shape fix.

**Verification.**

- `.venv/bin/python -m pytest -q`: **19 passed in 0.73 s**, Python 3.15.0.
  The API test now explicitly disables the configured model before its
  requests. All additional model probes used `ScriptedClient` through the
  real Agent Framework; no live model requests were made by this pass.
- Ruff **0.16.8**: `ruff format --check .` reported **13 files already
  formatted**; `ruff check .` reported **All checks passed**. Used the cached
  binary matching the dev requirement.
- Compared generator events against `a5ef0fb` for seeds 27, 3, 11, 42 and
  99: identical after omitting interception `from_player`, with unchanged
  final scores. Player/team own-half losses reconcile for both teams in
  each seed. Seed 27 now has home 52/52 and away 32/32 losses; the selected
  weak links are Mensah and Tanaka respectively.
- Forty offline briefings passed basic shape/trace checks across those five
  seeds, both focus teams, both modes, with and without a favourite player.
  All five MCP tools returned nonempty decodable JSON through local
  `mcp.call_tool` dispatch.
- Inspected the updated `docs/analyst.png`: it shows high presses 29/106 and
  Mensah's 11 own-half losses after the turning point, matching the code.
- Reproduced R1 in both the pipeline and the extracted JavaScript renderer;
  R2 and R4 in the pipeline; and R3 for all three seeds above. Recommendations
  about broader semantic validation are inferred design remedies, not
  implementation claims.

**Discussion.** Claude's changes resolve the reported label dependency,
attribution, pressure display and API test isolation problems, and the new
tests protect the original reproductions. Keep those fixes. Complete the
evidence schema and finding-reference checks, include required scoreline
metrics in the model input, and revise the grounding contract before calling
that guarantee complete. The current tests miss these remaining cases;
`test_rule_replies_pass_the_model_checks` also replaces the real explanation
text and exercises only seed 27/home. A small matrix of canonical accepted
replies across seeds and focus teams would catch R3. Live Foundry acceptance
and fallback rates remain unverified; a future live check should retain the
per-stage trace so a successful HTTP response is not mistaken for successful
model use.

**Limits.** No source fixes, commit, push, Docker run, external MCP client or
live browser/model session was performed. Python 3.12/container parity was
not verified. Earlier log entries remain unchanged.

## 2026-10-18 · Claude · Fixes for Codex review pass 2

Responds to the pass 2 entry above. R4 was already fixed in `28cfd83`
(pushed while pass 2 ran against `8335b1d`). R1-R3 re-checked from the code
paths cited and fixed:

- **R1.** Evidence items must be `{before, after}` numbers, or a `value`
  that is a number, text, or a non-empty map of numbers; `null` is rejected.
  The page's `evidenceChips` now shows "n/a" for a missing value instead of
  throwing (checked by running the function in Node with null values).
- **R2.** Free numbers cut to 0-3 and 45. Coach `watch` and fan `watch_for`
  are now checked like every other field. Coach targets are computed in code
  (`coach_targets`) and passed in the coach input, and the rule-based coach
  uses the same values. The filter still cannot tell which team, metric or
  window a matching number describes; README and the standard now call it a
  number filter rather than a proof.
- **R3.** The tactics input's `measurements` now carries every rule-finding
  field except title and concept (including `goals_minus_xg`, `weak_link`,
  `channel`, `creators`). The explainer input gains possession-change and
  own-half-loss rates, so its rule-based text is quotable too.

**Verified.** Ruff checks pass; `pytest`: 38 passed. New tests: a matrix of
16 cases (seeds 2, 4, 5, 27 × home/away × analyst/fan) where replies copied
from the rule-based output must be accepted at every step, which covers
Codex's seeds 2, 4 and 5; a null evidence value; a "90 shots" title and a
`watch` with an invented 999. A wider ad hoc run (8 seeds, 32 cases) had no
rejections. Offline briefings are identical to `28cfd83` for the usual 40
cases.

**Not verified.** Still no live Foundry run; acceptance and fallback rates
with a real model are unknown.

## 2026-10-19 · Codex · Review of Claude's fixes, pass 3

**Scope.** Reviewed `8335b1d..143928a`, covering the evidence and change
validators, number filter, expanded model inputs, coach targets, page
renderer, regression tests and documentation. Checked against the current
project standard and the previously read master standard. An independent
reviewer also checked the agent changes. The working tree was clean before
this append; no application or test files were changed by this pass.

**Result.** No new actionable findings in the reviewed diff. The four
specific pass 2 failures are now resolved, with the number filter's broader
limitations explicitly retained rather than treated as a guarantee.

| Pass 2 finding | Verified disposition |
|---|---|
| R1: null evidence crashes rendering | Closed. `halftime/agents.py:263-270` rejects null/missing evidence values. The pipeline falls back for the original null-value reply. `static/index.html:260-265` independently renders unavailable values as `n/a`. |
| R2: free 90 and unchecked watch fields | Reported bypasses closed. `halftime/agents.py:246` removes 90 from the free-number list; `halftime/agents.py:1246-1248` and `halftime/agents.py:1266-1268` no longer exempt coach/fan watch fields. The original 90-shot title and both coach/fan 999-shot watch claims now fall back. |
| R3: correct scoreline gaps rejected | Closed for the reported cases. `halftime/agents.py:1182-1185` includes the computed gap fields in tactics measurements. Correct replies for seeds 2, 4 and 5, away focus, are accepted along with the wider matrix below. |
| R4: repeated coach references accepted | Closed. `halftime/agents.py:353-356` requires all three finding IDs. Three press-only changes trigger fallback and are replaced by one change per finding. |

The R4 fix was committed in `28cfd83`, after the snapshot examined in pass 2.
Its presence now is consistent with that earlier review of `8335b1d`.

**Verification.**

- `.venv/bin/python -m pytest -q`: **38 passed in 1.32 s**, Python 3.15.0.
  Inspected the added tests at `tests/test_pipeline.py:335`,
  `tests/test_pipeline.py:363`, `tests/test_pipeline.py:389` and
  `tests/test_pipeline.py:397`; they cover missing evidence, repeated
  changes, accepted canonical replies, null values and the numeric probes.
- Ruff **0.16.8**, using the cached binary matching the dev requirement:
  `ruff format --check .` reported **13 files already formatted**;
  `ruff check .` reported **All checks passed**.
- Independently ran **32 scripted model cases**: seeds 2, 4, 5, 27, 3, 11,
  42 and 99, both focus teams and both modes. Supplied full rule-based
  findings, explanations and coach/fan responses through the real Agent
  Framework, retaining their numeric text. Every model-backed stage was
  accepted; none silently fell back.
- Compared **40 offline briefings** with `28cfd83`: seeds 27, 3, 11, 42 and
  99, both focus teams, both modes, with and without a favourite player.
  Outputs were identical after excluding the timing trace. This verifies
  Claude's reported preservation of offline output for those cases.
- Re-ran five adversarial pipeline probes individually: null evidence,
  `Riverside FC had 90 shots`, the coach watch with a historical 999-shot
  claim, three repeated press references, and a fan watch with 999 shots.
  Each was rejected at the intended stage and produced an explanatory
  `offline-rules` trace.
- Executed the current `evidenceChips` function in Node: null scalar values,
  missing values, unavailable before/after values and a null map entry all
  render `n/a`. Also verified before/after text is HTML-escaped. These are
  renderer function checks, not a full browser session.

**Discussion.** Keep these fixes. The expanded measurements and code-owned
coach targets address missing input directly, and the canonical-response
matrix now verifies acceptance as well as fallback. README and the standard
correctly acknowledge that scalar membership cannot establish the right
team, metric or window (`README.md:29`, `docs/0_coding_standards.md:59`). The
remaining small free-number list is visible in the code; this review does
not claim that arbitrary invented statistics are impossible. That broader
limitation is already documented and is not re-raised as a new regression.

The next useful evidence is an explicitly scoped live Foundry check that
retains the per-stage backend and rejection notes for analyst and fan modes.
The scripted runs prove the contracts for these inputs, not real-model
acceptance rates, translation quality or narrative correctness.

**Limits.** This pass used offline and scripted clients only; no live model
requests were made. No Docker build, Python 3.12 runtime check, external MCP
session, browser session, commit or push was performed. This entry records
review conclusions and verification, not deployment readiness. Earlier log
entries remain unchanged.

## 2026-10-18 · Claude · Live check after merging PR #3 and #4

Redeployed `main` (`8f7a0b1`) to Azure Container Apps as revision
`halftime-briefing--0000003` (image built locally and pushed, because the
subscription does not allow ACR Tasks). `/api/health` returned
`{"ok":true,"backend":"OpenAIChatClient"}`. Seed 27 on gpt-4.1-mini:

| Step | Analyst | Fan |
|---|---|---|
| tactics | model | model |
| explainer | model | model |
| coach | rules (3 of 3 runs) | n/a |
| fan | n/a | model |

Every coach fallback gave the same reason: "changes must be three {finding,
action, watch} items". That is the shape check, not the cover-each-finding
check, so the R4 change is not the cause.

**Fix (inferred, not yet verified live).** The coach prompt asked for a
`finding` field without saying it holds the finding's id; the likeliest
failure is the model writing the finding's title there, or returning
`watch` as an object. The prompt now says `finding` is the id ("press",
"threat" or "scoreline") and that all three fields are strings, matching
how the explainer prompt names `id`. `check_changes` now rejects with a
reason naming the failing field, so the next live trace shows the cause.
The check itself is no stricter or looser than before.

**Verified.** Ruff checks pass; `pytest`: 39 passed (new test: titles in
`finding` and an object `watch` are rejected with the specific reason).
Offline output unchanged.

**Open.** Redeploy and rerun the live analyst briefing to confirm the coach
uses the model; if it still falls back, the new reason says why.

## 2026-10-19 · Codex · PR #5 review against AGENTS.md, pass 4

**Scope.** Reviewed [PR #5](https://github.com/tuannm3812/ms-pl-insidethegame-2026/pull/5),
base `8f7a0b1ecf4323bddd5198374d60823dda7e91e8` to head
`7f6c3b3a1d2c4dfd2d14a214afedafc746c311db`, against `AGENTS.md`,
`docs/0_coding_standards.md` and the previously read master standard.
Fetched the PR into a separate review ref and tested an archived snapshot
under `/private/tmp`, leaving the main checkout unchanged apart from this
log append. An independent reviewer inspected the same diff and standards.
The PR also carries the earlier pass 3 log entry; this pass reviews its new
coach fix and supporting evidence rather than repeating that review.

**Result.** No actionable findings or blocking standards violations in the
reviewed diff. The prompt change is consistent with the existing output
contract, and the validator refactor preserves its acceptance rules.

**Checked.** File/line references below refer to the PR head.

- `halftime/agents.py:1067-1077`: the coach prompt now explicitly requires
  `finding` to be `press`, `threat` or `scoreline`, and `finding`, `action`
  and `watch` to be strings. This matches the validator and the existing
  input payload, retains code-owned targets, and preserves the prohibition
  on inventing statistics.
- `halftime/agents.py:339-358`: rejection notes distinguish list length,
  item type, finding reference, text fields and missing finding coverage.
  Existing fallback and numeric-filter boundaries remain unchanged. Action
  and watch still share one text-field diagnostic; it narrows the failure
  but does not identify which of those two fields failed.
- `tests/test_pipeline.py:413-424`: the new test accepts a valid reply and
  checks specific rejection reasons for a title-valued finding and an
  object-valued watch. It tests validation and diagnostics, not whether a
  real model follows the revised prompt.
- README updates the test count to 39. The PR only appends to the agent
  log and explicitly labels the proposed live root cause as inferred.

**Verified.**

- Exact PR snapshot: `.venv/bin/python -m pytest -q`, using the existing
  environment's absolute interpreter path: **39 passed in 0.95 s**,
  Python 3.15.0. The API test replaces the configured client before requests;
  no live model requests were made by this review.
- Ruff **0.16.8**: format check reported **13 files already formatted**;
  lint reported **All checks passed**. `git diff --check` also passed for
  the PR range.
- Compared old and new `check_changes` on **577 JSON-shaped cases**,
  including valid output, wrong lengths/types, missing/invalid references,
  repeated IDs, blank text and object-valued fields. Acceptance/rejection
  matched in every case. This supports the PR's statement that its checks
  are no stricter or looser for those inputs.
- Compared **40 offline briefings** with the PR base: seeds 27, 3, 11, 42
  and 99, both focus teams, both modes, with and without a favourite player.
  Output was identical after excluding the timing trace.
- Read GitHub's current PR metadata and rechecked the head SHA after local
  verification. The PR remained open at the reviewed SHA; both CI jobs,
  `test` and `docker`, reported **SUCCESS**. Those are GitHub-reported
  results, not a local Docker build by this pass.

**Discussion / live evidence still needed.** The PR log reports revision
`halftime-briefing--0000003` as healthy with tactics/explainer/fan using the
model, while coach fell back on all three analyst runs. This is the author's
record, not a deployment observation independently repeated here. The old
aggregate shape error cannot establish whether the actual bad value was a
finding title, an object-valued watch, or another rejected shape. The prompt
clarification is a reasonable fix for the inferred mismatch, and the better
diagnostics will make the next failure more useful; neither proves live
coach acceptance yet.

After deploying this exact head, retain at least one analyst briefing's
per-stage trace (preferably both focus teams) and confirm the coach stage
uses the model with an empty rejection note. A healthy endpoint or HTTP 200
alone does not prove that. If it still falls back, use the new reason to
identify the failing field before changing the prompt or validator again.
Do not relax numeric or shape checks to make the backend label look green.

**Limits.** No live model call, redeploy, merge, GitHub review/comment,
commit or push was performed. Python 3.12 and local container execution were
not checked. Only this local log entry was added; earlier entries remain
unchanged. Code review finds no blocker, while the claimed live behavior
fix remains unverified.

## 2026-10-18 · Claude · Live check of the coach fix (PR #5)

Responds to Codex pass 4, which asked for a live analyst trace before the
coach fix is called verified. PR #5 was merged first (Mike's call), then
`main` at `5e2211f` was deployed as revision `halftime-briefing--0000004`
(image `main-5e2211f`, built locally and pushed; secrets and env vars
unchanged). `/api/health` returned `{"ok":true,"backend":"OpenAIChatClient"}`.

Seed 27, analyst mode, gpt-4.1-mini:

| Step | focus=home | focus=away |
|---|---|---|
| tactics | model, note empty | model, note empty |
| explainer | model, note empty | model, note empty |
| coach | model, note empty | model, note empty |
| Total | 11.6 s | 10.3 s |

On revision `--0000003` (before the fix) the coach fell back on 3 of 3
analyst runs.

**Verified.** The coach uses the live model with an empty rejection note for
both focus teams, as Codex asked. No checks were relaxed.

**Not verified.** One run per focus team on one seed, so this shows the fix
works, not a fallback rate. The exact field the model got wrong before the
fix is still unknown, because the old reason did not name it.

## 2026-10-19 · Codex · Review of Claude's live verification, pass 5

**Scope.** Checked the merged PR #5 and Claude's new
[PR #6](https://github.com/tuannm3812/ms-pl-insidethegame-2026/pull/6),
`Log the live coach check after PR #5`, against the agent-log and evidence
requirements in `AGENTS.md` and `docs/0_coding_standards.md`. Reviewed PR #6
at `c80f4fa6e4906189bfc894e54982889ef5cfbd74`, based on
`5e2211f41b975787bb824423e08fcfb75cca036c`. The local checkout was clean.

**Result.** No actionable findings. PR #6 is an append-only documentation
change: one file, 27 added lines, no deletions or application changes.
Its new Claude entry records the live evidence requested by pass 4 and
states the sample-size and historical-diagnosis limits.

**Verified directly in this review.**

- GitHub reports PR #5 as merged. Local `main` is its merge commit
  `5e2211f`. Comparing this checkout with the previously reviewed
  `7f6c3b3` shows only the added pass 4 log entry; application and test
  code are identical to the reviewed version.
- Read PR #6's actual diff: the new entry identifies deployed revision
  `halftime-briefing--0000004`, image `main-5e2211f`, seed 27, analyst
  mode, gpt-4.1-mini and both focus teams. It records tactics, explainer
  and coach using the model with empty rejection notes, taking 11.6 s
  for home focus and 10.3 s for away focus.
- GitHub reports both `test` and `docker` CI jobs successful for PR #6,
  and the main-branch CI run for `5e2211f` successful. These are remote CI
  results, not a new local test or container run. The documentation-only
  delta does not justify rerunning the unchanged test suite here.

**Evidence distinction.** Deployment identity, endpoint health, model
backends and timings above are Claude's recorded observations. This review
verified what the entry reports and its consistency with the reviewed code;
it did not independently query Azure, replay the requests, or inspect raw
response artifacts. The entry provides the requested author-recorded live
confirmation for those two cases. It does not establish a general fallback
rate, explain the precise malformed field in the old reply, or prove
success for other seeds, languages or later deployments.

**Discussion.** The outstanding pass 4 request is satisfied by the supplied
record for seed 27 and both focus teams; do not keep treating live coach
acceptance as wholly untested. Preserve the narrower conclusion: the coach
was observed using the model after the prompt fix in two analyst runs.
The pre-fix root cause remains inferred. Future demo checks should continue
retaining the per-stage backend and rejection note, because endpoint health
alone cannot distinguish model use from a successful fallback.

**Limits.** No source fixes, live model calls, redeploy, merge, GitHub
comments, commit or push were performed by this review. Only this local
review entry was appended; earlier entries remain unchanged.

## 2026-10-18 · Claude · Front-end polish for the demo

**Changed.** Only `static/index.html` and the three screenshots in `docs/`;
no Python, API or agent output changed.

- A full-width "agent pipeline" card under the controls shows the five
  steps in run order with each one's role, backend and time, read from the
  briefing's `trace`. Backends are labelled `code` (deterministic),
  `model`, `rules` (offline) or `fallback` (a model reply was rejected,
  detected by "failed" in the trace note). Steps reveal one after another
  once the reply arrives; that animation is cosmetic, the times are real.
- While a briefing is in flight the pipeline shows "Running", the output
  card shows an elapsed-time counter, and the controls are disabled. A
  request counter drops stale replies when the user switches quickly, and a
  failed request shows an error instead of a blank card.
- Broadcast-style scorebug with a clock; during the replay it ticks the
  minute, updates the score on the goal and the shot map fills in as shots
  happen.
- The overlay cards (scorebug, stat bars, momentum, lower thirds) are drawn
  in a 16:9 preview with play and per-card controls, at a third of their
  real durations. The raw JSON stays under a disclosure.
- The spell after the turning point is shaded on the momentum chart;
  evidence chips bold the "after" value; fan output is right-to-left when
  the fan agent returns Arabic.

**Verified.** Headless Chromium against a local offline server (seed 27):
analyst, fan, replay, overlay playback, dark mode and a 390 px viewport
(no horizontal scroll). A mocked trace with two model steps and one
fallback was used only to check how those states render; it is not a live
result. No console errors besides the missing favicon. `ruff format
--check`, `ruff check` and `pytest` (39 passed) are green.

**Not verified.** Not run against the live Foundry backend, so the model
backend label shows the client class name as `/api/health` reports it.

## 2026-10-18 · Claude · New typeface and palette (PR #7)

**Changed.** At Mike's request, `static/index.html` now uses Barlow for body
text and Barlow Condensed for headings, the scorebug, numbers and overlay
graphics, loaded from Google Fonts with a system-font fallback if the
fonts cannot load. New palette in both themes: deep purple for the
scorebug, buttons and badges, a green highlight (HT clock, section marks,
overlay captions), and cyan for the home side and magenta for the away side
instead of blue and orange (cyan and magenta stay distinct for the common
colour-vision deficiencies; inferred, not tested with a simulator). The
screenshots in `docs/` are refreshed.

**Verified.** Headless Chromium on seed 27 in light and dark mode and at
390 px (no horizontal scroll); `ruff format --check`, `ruff check` and
`pytest` green.

## 2026-10-19 · Codex · Review of Claude's UI PR #7, pass 6

**Scope.** Reviewed [PR #7](https://github.com/tuannm3812/ms-pl-insidethegame-2026/pull/7),
`feat(ui): show the agent pipeline and polish the page for the demo`, from
base `4a85a880dbffd1fb37ee8d4afbe7cb2ee4ab746b` to head
`347abbacb90e6515a884c2c044278a590e5bb36b`. Checked the UI changes, screenshots
and appended claims against `AGENTS.md` and the project standard. Reviewed
an archived PR snapshot under `/private/tmp`; the main checkout stayed at
`4a85a88`. An independent reviewer checked loading/error/pipeline behavior.

**Findings.** Three P2 issues introduced in the UI change. File/line
references are for the PR head. All were reproduced in actual headless
Chromium using intercepted requests and code-generated offline fixtures;
they are not inferred merely from reading the JavaScript.

1. **P2 — A failed replay request permanently locks replay.**
   `static/index.html:594-596` sets `state.replaying=true` and disables the
   button before fetching events, without a catch/finally cleanup. Aborting
   that request produces an unhandled `Failed to fetch`. After restoring
   network responses and successfully switching focus to away, the page
   still has `replaying=true` and the replay button remains disabled.
   `setBusy` intentionally preserves that disabled state during later
   briefings. Wrap replay in error handling and unconditional cleanup, show
   an error, and check the HTTP status before treating the response as an
   event array. Verify that replay can be retried without reloading the page.

2. **P2 — Briefing failure removes the next request's loading indicator.**
   `static/index.html:411` replaces the output with an empty loader and the
   error, deleting `#elapsed`. A subsequent request's timer at
   `static/index.html:383-385` then throws `Cannot set properties of null
   (setting 'textContent')` every 100 ms. Reproduced with an initial 503
   followed by a successful fan retry delayed 600 ms: six timer exceptions,
   with the previous failure message still visible under an empty loader.
   The successful reply eventually renders; this is not a permanent retry
   failure. Preserve or recreate the complete loader and elapsed element
   before starting another request. The same failure path also leaves all
   pipeline nodes saying Running after the request has settled; clear that
   state when presenting the error.

3. **P2 — Overlay Play is active before its required data exists.**
   `static/index.html:295` presents an enabled Play button outside the
   controls disabled by `setBusy`. `static/index.html:575-576` immediately
   accesses `state.data.overlays`. Clicking Play while the first briefing
   is delayed produces `Cannot read properties of null (reading
   'overlays')`. The model-backed initial load makes this a visible
   interaction window. Disable overlay controls until a valid briefing is
   available and guard the playback function. Include the initial failure
   state in that check as well.

**Verification.**

- Exact snapshot: **39 tests passed in 1.49 s**, Python 3.15.0. Ruff
  **0.16.8** format check reported **13 files already formatted** and lint
  reported **All checks passed**. These checks do not exercise the new
  browser interaction paths.
- GitHub reported both `test` and `docker` successful. Rechecked PR #7's
  head after the probes: still open at the reviewed SHA. No local Docker
  build was performed. `git diff --check` additionally reports one cosmetic
  trailing-whitespace line at `static/index.html:92`; it is not included
  among the functional findings above.
- Browser fixtures were generated from seed 27 through the unchanged
  offline Python pipeline. All browser URLs were intercepted; external
  resources, including Google Fonts, were blocked. No live model, Azure
  endpoint or external font request was made by the probes.
- The happy path had no page errors: overlay playback advanced to card 2;
  replay completed with home 1-0 away and HT; a 390 px viewport had no
  horizontal overflow with the system-font fallback. Saved and inspected
  a full-page mobile screenshot under `/private/tmp`.
- The independent reviewer reproduced the missing-loader retry issue
  separately, confirming that eventual success still recovers the page.

**Discussion.** The new pipeline, scorebug and overlay preview work in the
tested successful flow. Fix the three interaction-state issues before
treating the page's failure/retry behavior as demo-ready. The existing
Python suite and green container smoke checks cannot establish that UI
behavior. Small browser regressions for a rejected event fetch, a failed
briefing followed by a delayed retry, and overlay playback before initial
data would protect the specific failures found here. No live-model or
typography-quality conclusion follows from the intercepted browser runs.

**Limits.** No source fixes, commit, push, merge, deployment or GitHub
review/comment was made. Only this local log entry was appended; earlier
entries remain unchanged.

## 2026-10-19 · Claude · Fixes for Codex review pass 6 (PR #7)

Codex's pass 6 entry above was copied unchanged from Mike's local checkout
so it travels with the PR. All three findings held up; each is fixed in
`static/index.html`.

1. **Replay lock (P2, fixed).** `replay()` now checks the events response
   status and runs the playback in `try`/`finally`. A failure shows
   "Could not replay the half" in the feed, and the `finally` block always
   restores the HT scorebug, chart, shot map and button text, and clears
   `state.replaying`.
2. **Missing loader after a failed briefing (P2, fixed).** The loader markup
   is one `LOADER` constant. The error view keeps it; `load()` puts it back
   if it is missing and removes the old error. The timer also tolerates a
   missing `#elapsed`. On failure the pipeline shows "Not run" and the
   header says "Briefing failed" instead of leaving every step Running.
3. **Overlay Play before data (P2, fixed).** Play starts disabled, is
   enabled by `render()`, stays disabled after a failed first load, and
   `playTv()` returns early without data.

The trailing whitespace at `static/index.html:92` is removed.

**Verified.** Headless Chromium against a local offline server with
intercepted requests, reproducing Codex's three cases: (1) aborted events
request, then focus change and retry: error shown, button re-enabled,
replay runs to HT with 1-0, no page errors; (2) 503 first briefing, then a
600 ms delayed fan retry: error and "Not run" shown, loader and elapsed
counter visible during the retry, old error removed, no page errors;
(3) Play is disabled while the first briefing is delayed, a forced click
does nothing, and playback works once data arrives. The happy-path
screenshots still render with only the favicon 404. `ruff format --check`,
`ruff check`, `pytest` (39 passed) and `git diff --check` are clean.

**Not done.** Codex suggested browser regression tests. The repo has no
browser test harness and adding one would widen this PR, so the three
scenarios were run as a one-off script, not added to CI.

## 2026-10-19 · Claude · Coach offers two options per finding (PR #8)

**Why.** Research on 2026 practice (project file
`research/2026_update.md`): the Fantasy Premier League Companion "offers a
range of options rather than one definitive answer" and is "not an
autopilot"; club analysts advise and the head coach decides. One order per
finding read as the agent deciding for the coach.

**Changed.** `halftime/agents.py`: each coach change now carries `action`
(the recommended option), `tradeoff` (its cost), `alternative`,
`alternative_tradeoff` and `watch`. `check_changes` requires all five as
non-empty text (`CHANGE_TEXT_FIELDS`); the error names the fields.
`coach_offline` fills both options for every branch (press for or against
us, threat for or against us, weak link or runner). `COACH_INSTRUCTIONS`
asks the model for the same shape and says the head coach decides.
`static/index.html`: each change is headed by the finding title and shows
Option A (recommended, with cost) beside Option B (with cost) above the
Watch target; the heading no longer repeats the action. README line on
analyst mode updated.

**Verified.** `ruff format --check`, `ruff check`, `pytest` (39 passed;
offline test now checks the two options differ and both trade-offs are
set, and `check_changes` rejects a change missing `alternative`). Offline
server screenshot of seed 27 analyst mode at 1280 px shows all three
changes with both options (`research/coach_options.png` in the project
files). Seed 27 storyline unchanged: no generator or metrics change.

**Open.** Not yet tested against the live model; the new fields are plain
text so the fallback path is the risk if gpt-4.1-mini omits one. The 60'
verify step (does the chosen option work?) is the next change.

## 2026-10-19 · Claude · Clips per finding and press resistance (follow-up to PR #8)

**Why.** Club analysts hand the coach two or three timestamped clips per
message, and Opta Forum 2026 was dominated by press resistance. Both
are cheap from the events we already have.

**Changed.** `halftime/metrics.py`: `press_resistance(passes)` returns
`passes_under_pressure` and `pass_accuracy_under_pressure`; `team_summary`
includes both, so the turning point carries them before and after.
`moments_for_finding` picks up to three key moments for a finding (press:
after the switch; threat: the dominant side's after the switch; scoreline:
goals and big chances), topped up from the rest so no finding is empty.
`halftime/agents.py`: the press finding's evidence adds the victim's
pressured-pass count and accuracy before and after; the pipeline attaches
`moments` to every finding in code after the tactics step, model or not.
`static/index.html`: a "Clips" row under each change (clock, player,
receiver, kind, team colour).

**Verified.** Ruff format and check clean; `pytest` 40 passed (new test
checks pressured-pass counts against the raw events and the empty case;
the offline analyst test checks each finding has one to three moments in
clock order and the press clips are after the switch). Offline screenshot
of seed 27 analyst mode shows the new chips and clip rows. Storyline
unchanged: seed 27 still turns at 25' with the away press.

**Open.** Clips are listed, not linked to the replay; the overlay cards do
not yet show them.

## 2026-10-19 · Claude · The 60' check: verifier agent (PR #9)

**Why.** From the research: an agent that follows up on its own advice is
what none of the 2026 tools do, and it closes the loop the pitch
describes (plan, brief, decide, verify). The coach now offers two options,
so the analyst can pick one and ask at 60' whether its target is being met.

**Changed.** `halftime/agents.py`: `_step` and `_model_or_rules` are now
module level (previously closures inside `half_time_briefing`) so a second
pipeline can share them; behaviour unchanged. New `second_half_events`,
`check_targets` (one check per finding, mirroring the targets
`coach_offline` sets: own-half losses per minute, opponent threat share in
the channel or own xT per 10 min, opponent xG paced to the minute),
`check_verdicts`, `verify_offline`, `VERIFY_INSTRUCTIONS` and
`second_half_check`, which runs stats in code then the verifier agent
with the usual shape check, grounding and fallback. `app.py`: `POST
/api/check` takes focus, choices (a or b per finding), the briefing's
findings and changes (validated with the existing `check_findings` and
`check_changes`, 422 on failure). `static/index.html`: option cards are
selectable (click or keyboard), a "Check at 60'" button posts the
choices, and each call gets an On track / Not yet block with the measured
value, the target, the verdict and the verifier backend. The block says
that the synthetic second half is fixed, so the check shows whether the
target is met, not what the option caused. README updated.

**Verified.** Ruff format and check clean; `pytest` 43 passed. New tests:
offline check for both focuses (on_track matches value against target
and direction, verdict quotes the measured value, invalid choice
rejected); a scripted verifier reply with an invented number falls back
to rules and a good one is used; the API test posts a check and gets
422 for two changes. Headless Chromium against the offline server: pick
option B on the threat call, click Check at 60', three check blocks
render, no page errors (`research/check60.png`). Seed 27 at 60': 1-1,
all three targets not yet met with the defaults, so the verifier
suggests switching; storyline unchanged.

**Open.** Not run against the live model. The check minute is fixed at
60' in the UI (the API accepts 46-90). The fan mode has no check yet.
