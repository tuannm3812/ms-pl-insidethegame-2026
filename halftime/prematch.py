"""Pre-match expectation: what a normal first half looks like for these teams.

Before kick-off we only know each side's style (passing skill, pressing,
directness): the scouting report. Simulating many matches with those
pre-match styles, and no mid-match changes, gives the expected first-half
numbers and a typical range, plus a pre-match win, draw and loss estimate.
Comparing the real half with that range shows what changed from the plan.
"""

from __future__ import annotations

from dataclasses import replace
from functools import lru_cache
from statistics import mean

from . import metrics
from .generator import default_teams, generate_match
from .metrics import SIDES, other

SIMULATIONS = 60
FIRST_SEED = 10_000

# (key, label, better for the side it describes)
ROWS = (
    ("possession_pct", "Possession %", "higher"),
    ("xg", "Expected goals (xG)", "higher"),
    ("shots", "Shots", "higher"),
    ("xt_created", "Threat created (xT)", "higher"),
    ("pass_accuracy", "Pass accuracy", "higher"),
    ("high_presses", "High presses", "higher"),
    ("ppda", "PPDA", "lower"),
    ("turnovers_in_own_half", "Balls lost in own half", "lower"),
)


def _percentile(values: list[float], q: float) -> float:
    """Nearest-rank percentile of a non-empty list."""
    ordered = sorted(values)
    i = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return ordered[i]


@lru_cache(maxsize=1)
def expectation(simulations: int = SIMULATIONS) -> dict:
    """Simulate the default fixture with pre-match styles only.

    Returns, per side and metric, the mean and the 10th to 90th percentile
    of the first-half value, and the share of full matches each side won.
    Cached, because it is the same for every request.
    """
    samples: dict[str, dict[str, list[float]]] = {
        s: {k: [] for k, _, _ in ROWS} for s in SIDES
    }
    results = {"home": 0, "draw": 0, "away": 0}
    for i in range(simulations):
        home, away = default_teams()
        home = replace(home, style_changes={})
        away = replace(away, style_changes={})
        m = generate_match(FIRST_SEED + i, home, away)
        ev = metrics.window(m["events"])
        for s in SIDES:
            summary = metrics.team_summary(ev, s)
            for k, _, _ in ROWS:
                if summary[k] is not None:
                    samples[s][k].append(summary[k])
        h, a = m["final_score"]["home"], m["final_score"]["away"]
        results["home" if h > a else "away" if a > h else "draw"] += 1
    return {
        "simulations": simulations,
        "win_pct": {
            k: round(100 * v / simulations, 1) for k, v in results.items()
        },
        "metrics": {
            s: {
                k: {
                    "mean": round(mean(v), 2),
                    "low": round(_percentile(v, 0.1), 2),
                    "high": round(_percentile(v, 0.9), 2),
                }
                for k, v in samples[s].items()
                if v
            }
            for s in SIDES
        },
    }


def compare(match: dict, focus: str) -> dict | None:
    """The real first half against the pre-match expectation.

    Each row says whether the actual value sits inside the typical range
    (10th to 90th percentile of the simulations), above it or below it, and
    whether that is good or bad for the focus team. ``changes`` lists the
    rows outside the range, furthest outside first. Returns None for a
    fixture other than the default one, which has no scouting report here.
    """
    teams = default_teams()
    if [match["teams"][s]["name"] for s in SIDES] != [t.name for t in teams]:
        return None
    exp = expectation()
    ev = metrics.window(match["events"])
    actual = {s: metrics.team_summary(ev, s) for s in SIDES}
    rows = []
    for side in (focus, other(focus)):
        for key, label, better in ROWS:
            e = exp["metrics"][side].get(key)
            value = actual[side][key]
            if e is None or value is None:
                continue
            verdict = (
                "above"
                if value > e["high"]
                else "below"
                if value < e["low"]
                else "as_expected"
            )
            good_for_side = (
                None
                if verdict == "as_expected"
                else (verdict == "above") == (better == "higher")
            )
            rows.append(
                {
                    "side": side,
                    "key": key,
                    "label": label,
                    "expected": e["mean"],
                    "low": e["low"],
                    "high": e["high"],
                    "actual": value,
                    "verdict": verdict,
                    "good_for_focus": (
                        None
                        if good_for_side is None
                        else good_for_side == (side == focus)
                    ),
                }
            )

    def distance(r: dict) -> float:
        width = (r["high"] - r["low"]) or 1
        edge = r["high"] if r["verdict"] == "above" else r["low"]
        return abs(r["actual"] - edge) / width

    changes = sorted(
        (r for r in rows if r["verdict"] != "as_expected"),
        key=distance,
        reverse=True,
    )
    return {
        "focus": focus,
        "simulations": exp["simulations"],
        "changes": [
            {k: r[k] for k in ("side", "key", "label", "verdict")}
            for r in changes
        ],
        "prematch_win_pct": exp["win_pct"],
        "rows": rows,
        "styles": {
            s: vars(t.style) for s, t in zip(SIDES, teams, strict=True)
        },
    }
