# Prototype version archive

Keep each version unchanged so the user can manually compare it later.
Never replace an archived HTML file, screenshot, fixture or manifest.
Corrections belong in a new version. The running preview is temporary;
the files here are the durable comparison artifacts.

**Compare side by side:** open [compare.html](compare.html) and pick a
version for each pane.

| Version | Purpose | Preview | Status |
| --- | --- | --- | --- |
| Codex v1 | Standalone coaching workflow concept | [Open HTML](codex-v1/index.html) | Archived; not selected as the base layout |
| Claude v1 | Claude's full interface before refinement | [Open HTML](claude-v1/index.html) · [notes](claude-v1/notes.md) | Archived (PR #9 at `2719d04`) |
| Claude v2 | Refine Claude v1 using the agreed coaching workflow ideas | [Open HTML](claude-v2/index.html) · [notes](claude-v2/notes.md) | Archived; built into the app at `f15e05e` |
| Claude v3 | The app after Codex pass 9 and the content audit (decision-aware follow-up, best-when per option, keyboard focus, one display rule, role-led player cards) | [Open HTML](claude-v3/index.html) · [notes](claude-v3/notes.md) | Awaiting manual review (app at `9332995`) |

Codex v1 images: [desktop](codex-v1/desktop.png),
[mobile](codex-v1/mobile.png), [follow-up](codex-v1/review.png),
[in-app review](codex-v1/browser-review.png).
Its original explanatory notes are preserved verbatim in `codex-v1/notes.md`;
relative links inside those copied notes refer to their original location
under `docs/prototypes/`. File hashes are in `codex-v1/manifest.json`.
Codex v1 was saved in Mike's local checkout; it is not yet committed.

Claude v1, v2 and v3 images, the same five views each (seed 27, Riverside,
1440 x 1000 and 390 x 844): `1-initial.png`, `2-priority-call.png`,
`3-selected.png`, `4-follow-up.png`, `5-mobile.png`. Each folder has
`notes.md` (change summary, what is simulated, known issues, checks run),
`manifest.json` (hashes, revision, seed, viewports, states),
`fixtures.js` and the `record_fixtures.py` and `capture.py` that made
them.

## Contract for Claude's snapshots

Before refining anything, archive the current Claude interface as
`claude-v1/`, recording its actual commit SHA and any uncommitted changes.
Then create the refined version in `claude-v2/`. Do not claim those versions
exist until their files are saved and checked. Continue with `claude-v3/`
and so on for subsequent iterations; do not overwrite earlier revisions.

Each version should include:

- A runnable snapshot: preferably self-contained HTML plus deterministic
  offline fixtures. If the backend is needed, include its exact revision,
  dependency/start instructions and the matching source snapshot. An HTML
  file that silently depends on a changing live API is not reproducible.
- Screenshots of the same views: initial analyst screen, expanded priority
  call, selected/adopted response, follow-up result, and mobile layout.
- Consistent seed 27, Riverside/home focus, scenario, scroll positions and
  viewport sizes (1440 × 1000 desktop and 390 × 844 mobile). Also check
  intermediate widths for overflow. Clearly label any different fixture.
- A short change summary: what changed from the previous version, why,
  what is simulated, what works, known issues, and checks actually run.
- A manifest with file hashes, source revision, capture date, seed, focus,
  viewport and state information. Do not include secrets or `.env`.

Update this index with relative links to every completed version and add
an append-only response in `../../5_agent_log.md`. Provide a single preview
index so the user can open versions side by side. New versions remain
pending the user's manual comparison; saving one does not approve it for
production or authorise deployment.
