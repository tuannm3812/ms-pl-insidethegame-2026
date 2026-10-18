# ms-pl-insidethegame-2026

Half-time Briefing: a FastAPI app where a pipeline of agents turns a seeded
synthetic football match into an explained half-time briefing for analysts or
fans. Our entry for the Microsoft x Premier League *Inside the Game* hackathon
(submissions close 2026-10-27 23:59 PT). It is an app repo, not a modelling
repo: there is no training data, no notebook and no leaderboard.

## Standards

Follow the master standard at `~/Documents/GitHub/coding-standards/`.
Project-specific rules and deliberate overrides: @docs/0_coding_standards.md
If the master is not on disk (cloud review), `docs/0_coding_standards.md`
holds every rule this repo is reviewed against.

## Deltas from the master

- Doc shape B (app/hackathon), not the notebook-first shape A.
- Code lives in the `halftime/` package with `tests/` from day one; there
  are no notebooks, so §4 and §11-12 do not apply.
- `data/xt_grid.json` is committed on purpose: `halftime/xt.py` reads it as
  a cache and refits it if it is missing.

## Checks

```bash
ruff format --check . && ruff check .   # style, lint, docstrings, hints
python -m pytest -q                     # pipeline, API and MCP tests
```

CI runs both on every pull request, plus a Docker build and smoke test.

## Evidence locations

- `docs/5_agent_log.md` — append-only log of agent work and review passes.
- `README.md` — what was tested offline and live on Foundry, and its limits.

## Review passes (Codex)

Review the diff against `docs/0_coding_standards.md`. Append one entry to
`docs/5_agent_log.md` per pass: what you checked, each finding with
`file:line`, and which findings you verified versus inferred. Never edit an
earlier entry; correct it with a new one.

## Open risks

- Every number must come from code (`halftime/metrics.py`). A model-backed
  agent that states a statistic not in its input is a bug.
- Each model-backed agent needs a rule-based fallback with the same output
  shape, so the demo runs with no model and survives a bad model reply.
- Never commit `.env`; the Foundry key lives there and in Azure only.
