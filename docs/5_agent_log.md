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
