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
