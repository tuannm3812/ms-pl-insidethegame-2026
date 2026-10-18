"""Expected threat (xT), after Karun Singh's 2018 model.

The pitch is split into a 12 x 8 grid. For each cell we learn how often a
player there shoots, how often that shot scores, and where the ball tends to
move next. xT is then solved by value iteration:

    xT(cell) = P(shoot) * P(goal | shot) + P(move) * sum(T(cell -> z) * xT(z))

The grid is fitted on a batch of simulated matches and cached to disk.
"""

from __future__ import annotations

import json
from pathlib import Path

from .generator import PITCH_X, PITCH_Y, generate_match

NX, NY = 12, 8
CACHE = Path(__file__).resolve().parent.parent / "data" / "xt_grid.json"


def cell(x: float, y: float) -> tuple[int, int]:
    cx = min(NX - 1, max(0, int(x / PITCH_X * NX)))
    cy = min(NY - 1, max(0, int(y / PITCH_Y * NY)))
    return cx, cy


def fit_xt(matches: list[dict], iterations: int = 6) -> list[list[float]]:
    shots = [[0] * NY for _ in range(NX)]
    goals = [[0] * NY for _ in range(NX)]
    moves = [[0] * NY for _ in range(NX)]
    trans: dict[tuple[int, int], dict[tuple[int, int], int]] = {}
    for m in matches:
        for e in m["events"]:
            if e["type"] == "shot":
                cx, cy = cell(e["x"], e["y"])
                shots[cx][cy] += 1
                goals[cx][cy] += e["outcome"] == "goal"
            elif e["type"] == "pass":
                cx, cy = cell(e["x"], e["y"])
                moves[cx][cy] += 1
                if e["outcome"] == "complete":
                    dest = cell(e["end_x"], e["end_y"])
                    trans.setdefault((cx, cy), {}).setdefault(dest, 0)
                    trans[(cx, cy)][dest] += 1

    xt = [[0.0] * NY for _ in range(NX)]
    for _ in range(iterations):
        new = [[0.0] * NY for _ in range(NX)]
        for cx in range(NX):
            for cy in range(NY):
                total = shots[cx][cy] + moves[cx][cy]
                if not total:
                    continue
                p_shot = shots[cx][cy] / total
                p_goal = goals[cx][cy] / shots[cx][cy] if shots[cx][cy] else 0.0
                move_val = 0.0
                if moves[cx][cy]:
                    for (dx, dy), n in trans.get((cx, cy), {}).items():
                        move_val += n / moves[cx][cy] * xt[dx][dy]
                new[cx][cy] = p_shot * p_goal + (1 - p_shot) * move_val
        xt = new
    return [[round(v, 4) for v in col] for col in xt]


_GRID: list[list[float]] | None = None


def grid(n_matches: int = 40) -> list[list[float]]:
    """Return the cached xT grid, fitting it on simulated matches if needed."""
    global _GRID
    if _GRID is not None:
        return _GRID
    if CACHE.exists():
        _GRID = json.loads(CACHE.read_text())["grid"]
        return _GRID
    matches = [generate_match(seed=1000 + i) for i in range(n_matches)]
    _GRID = fit_xt(matches)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"nx": NX, "ny": NY, "fitted_on_matches": n_matches,
                                 "grid": _GRID}, indent=1))
    return _GRID


def value(x: float, y: float) -> float:
    cx, cy = cell(x, y)
    return grid()[cx][cy]


def pass_xt(e: dict) -> float:
    """Threat added by a completed pass (end cell minus start cell)."""
    if e["type"] != "pass" or e["outcome"] != "complete":
        return 0.0
    return round(value(e["end_x"], e["end_y"]) - value(e["x"], e["y"]), 4)
