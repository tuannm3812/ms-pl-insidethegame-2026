# Coding standards: Half-time Briefing

The master standard (`~/Documents/GitHub/coding-standards/coding_standards.md`)
tailored to this repo. Section numbers in brackets point at the master. Where
this file and the master disagree, this file wins for this repo.

Last updated 2026-10-18.

## 1. Shape of the repo [§1, §2]

This is an app and hackathon repo, so it uses doc **shape B**:

| Path | Holds |
|---|---|
| `app.py` | FastAPI app: the page and the JSON API |
| `halftime/` | generator, metrics, xT model, agents, MCP server |
| `tests/` | pytest suite; every module change keeps it green |
| `static/index.html` | the single-page UI |
| `data/xt_grid.json` | fitted xT grid, a small committed cache |
| `docs/` | standards, agent log, screenshots |

Doc slots follow shape B: `0_coding_standards.md`, then `1_brief.md`,
`2_architecture.md`, `3_decisions.md`, `4_next_steps.md` when they are
written, and `5_agent_log.md`. Until the brief and architecture docs exist,
`README.md` covers both.

Not applicable here: notebooks (§4), feature leakage (§5), plot palette (§6)
and Kaggle submission (§11-12).

## 2. Python style [§3]

Enforced by Ruff from `pyproject.toml`; CI fails if either check fails.

- `ruff format` owns layout: 4-space indent, 79-character lines, double
  quotes. Do not hand-format around it.
- `ruff check` enforces pycodestyle, pyflakes, import order (standard
  library, third-party, then `halftime`), bugbear, pyupgrade to 3.12 idioms,
  PEP 8 naming, docstrings and type hints.
- Every public function, class and module has a docstring, Google style. A
  one-line summary is enough when the signature says the rest; add `Args:`
  and `Returns:` when it does not. Tests are exempt: their names say what
  they check.
- Every public function has argument and return type hints. Agent Framework
  types are imported under `TYPE_CHECKING`, because the package is imported
  lazily so the offline path never loads it.
- Long user-facing strings are split into implicit concatenations, one
  phrase per line. Prompts are triple-quoted constants at module level.
- Comments say why, not what.
- `snake_case` names, `UPPER_SNAKE_CASE` constants.

## 3. Rules specific to this app

These are the rules a reviewer should check hardest, because breaking them
breaks the demo or the pitch.

1. **Numbers come from code.** Every statistic in a briefing is computed in
   `halftime/metrics.py` (or `xt.py`) and passed to the agents. Model-backed
   agents explain and decide; they never compute or invent a number. Prompts
   must keep saying so.
2. **Same shape, model or not.** Each model-backed agent (tactics,
   explainer, coach, fan) has a rule-based `*_offline` fallback returning the
   same JSON shape. A model reply that cannot be parsed falls back to it and
   is recorded in the briefing's `trace`.
3. **Deterministic data.** The generator is seeded; the same seed gives the
   same events. Demo seed is 27. A change that alters seed 27's storyline
   (away side presses high from 25') must update the README and screenshots.
4. **Secrets stay out.** Configuration comes from the environment or a local
   `.env`. `.env` is git-ignored and Docker-ignored; `.env.example` lists
   the variables with placeholders only. No keys in code, tests, logs or
   docs.
5. **One container.** The app runs as one image from `Dockerfile`. CI builds
   it and smoke-tests `/api/health` and a fan briefing.

## 4. Git and pull requests [§8, §9, §10]

- Conventional Commits: `<type>(<scope>): <imperative summary>`. Scopes in
  use: `agents`, `metrics`, `generator`, `api`, `ui`, `mcp`, `ci`, `deploy`,
  `docs`.
- One coherent change per commit; put what was verified in the body.
- Before committing: `git status --short`, the two Ruff checks, `pytest`.
- Never commit `.env`, `.venv/`, caches or ad hoc output.
- Work on a branch and merge to `main` by pull request, CI green.

## 5. Agent log [§13]

`docs/5_agent_log.md` is the shared record for Claude, Codex and people.
Append an entry after meaningful work or a review pass: date, who, what
changed or was checked, what was verified (and how), what is still open.
Entries are append-only; correct an old one with a new entry. Record
findings that did not hold up as well as those that did.
