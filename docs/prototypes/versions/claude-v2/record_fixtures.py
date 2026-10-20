"""Record the offline API replies and prototype data for Claude v2.

Run from the repository root at the recorded revision:
``python docs/prototypes/versions/claude-v2/record_fixtures.py``. It uses
the rule-based agents only (no model). The API replies are the same as
Claude v1's; ``proto:<focus>`` adds what the v2 page needs and the backend
does not produce yet: typed targets, the 46'-60' window with its counts,
an evidence status under a proposed policy, cost guardrails, and editorial
alternative explanations. Every number is computed here, in code.
"""

import itertools
import json
import pathlib
import sys
from urllib.parse import urlencode

sys.path.insert(0, str(pathlib.Path.cwd()))

from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
from halftime import metrics  # noqa: E402
from halftime.agents import (  # noqa: E402
    CHECK_MINUTE,
    other,
    second_half_events,
    tactics_offline,
    watch_targets,
)
from halftime.generator import generate_match  # noqa: E402
from halftime.xt import pass_xt  # noqa: E402

# Proposed evidence policy (Claude's reply in the agent log, 2026-10-20).
# A policy for discussion, not football fact.
MIN_RATE_EVENTS = 10
MIN_SHARE_PASSES = 20
MIN_SHOTS = 5

ALTERNATIVES = {
    ("press", "against"): (
        "Our build-up got worse on its own (tired legs, loose first "
        "touches), so the losses would have risen without their press.",
        "Whether our own-half losses come with a presser close by or not; "
        "the 25'-45' clips settle it.",
    ),
    ("press", "for"): (
        "They chose to go long and gave the ball away, rather than our "
        "press forcing errors.",
        "Whether their losses come from pressured passes; the clips of "
        "their losses settle it.",
    ),
    ("threat", "against"): (
        "They had few attacks, so a handful of passes down one channel "
        "looks like a pattern.",
        "How many of their threatening passes went down that channel, and "
        "the clips.",
    ),
    ("threat", "for"): (
        "Their shape leaves that channel open by design and may close it "
        "after the break.",
        "Whether our threat there holds once they make their next change.",
    ),
    ("scoreline", "any"): (
        "The gap is a few chances either way, not a pattern of play.",
        "The shot list and the clips of the big chances.",
    ),
}
BEST_WHEN = {
    ("press", "against"): (
        "our quick forward can run behind a back line that pushes up",
        "the keeper and centre-backs are calm on the ball under pressure",
    ),
    ("press", "for"): (
        "the front line still has the legs to keep pressing",
        "after the hour, or when the lead needs protecting",
    ),
    ("threat", "against"): (
        "their threat really does come from that one channel",
        "they switch play often, so a winger cannot keep tracking back",
    ),
    ("threat", "for"): (
        "the channel stays open after the break",
        "they shift their cover to that side",
    ),
    ("scoreline", "any"): (
        "the first-half pattern holds after the break",
        "they change shape or personnel at the break",
    ),
}

OUT = pathlib.Path(__file__).with_name("fixtures.js")
LANGUAGES = ("en", "es", "vi", "fr", "ar")


def _rate_status(n: int, minutes: int, value: float, w: dict) -> str:
    """Met, not met or too close: within one Poisson standard error."""
    if n < MIN_RATE_EVENTS:
        return "insufficient"
    se = n**0.5 / minutes
    if abs(value - w["target"]) < se:
        return "too_close"
    met = (
        value < w["target"]
        if w["direction"] == "below"
        else (value >= w["target"])
    )
    return "met" if met else "not_met"


def prototype(focus: str) -> dict:
    """The v2 page's extra data for one focus team, computed in code."""
    match = generate_match(app_module.DEFAULT_SEED)
    facts = metrics.half_time_facts(match)
    findings = tactics_offline(facts, match, focus)
    watch = watch_targets(facts, findings, focus)
    by_id = {f["id"]: f for f in findings}
    opp = other(focus)
    minutes = CHECK_MINUTE - 45
    ev = second_half_events(match["events"], CHECK_MINUTE)
    late = facts["turning_point"]["after"]
    names = facts["teams"]

    def positive_passes(side: str, events: list[dict]) -> list[dict]:
        return [
            e
            for e in events
            if e["team"] == side
            and e["type"] == "pass"
            and e["outcome"] == "complete"
            and pass_xt(e) > 0
        ]

    def xt_per_10(side: str, events: list[dict], mins: float) -> float:
        # Same measure as the backend's check: team_summary's xt_created.
        xt = metrics.team_summary(events, side)["xt_created"]
        return round(10 * xt / mins, 2)

    out = {}
    for fid in ("press", "threat", "scoreline"):
        f, w = by_id[fid], watch[fid]
        situation = (
            "any"
            if fid == "scoreline"
            else "against"
            if f["team"] == opp
            else "for"
        )
        check: dict = {"window": "46'-60'", "minutes": minutes}
        guard = None
        policy = "from the first half"
        if fid == "press":
            side = focus if situation == "against" else opp
            n = metrics.team_summary(ev, side)["turnovers_in_own_half"]
            value = round(n / minutes, 2)
            baseline = round(
                late[side]["turnovers_in_own_half"] / late[side]["minutes"],
                2,
            )
            check |= {
                "value": value,
                "target": w["target"],
                "n": n,
                "unit": "balls lost in own half",
                "baseline": baseline,
                "status": _rate_status(n, minutes, value, w),
                "se": round(n**0.5 / minutes, 2),
                "rule": (
                    f"at least {MIN_RATE_EVENTS} events; too close to call "
                    "within one standard error (square root of the count, "
                    "per minute)"
                ),
            }
        elif fid == "threat" and situation == "against":
            passes = positive_passes(opp, ev)
            n = len(passes)
            share = metrics.threat_channels(ev, opp)[f["channel"]]
            late_ev = [
                e
                for e in metrics.window(match["events"])
                if e["minute"] >= facts["turning_point"]["minute"]
            ]
            check |= {
                "value": share,
                "target": w["target"],
                "n": n,
                "unit": "threatening passes by " + names[opp],
                "baseline": metrics.threat_channels(late_ev, opp)[
                    f["channel"]
                ],
                "status": (
                    "insufficient"
                    if n < MIN_SHARE_PASSES
                    else "met"
                    if share < w["target"]
                    else "not_met"
                ),
                "rule": (
                    f"at least {MIN_SHARE_PASSES} threatening passes; no "
                    "too-close rule for a share yet"
                ),
            }
            policy = "proposed limit, not validated"
        elif fid == "threat":
            passes = positive_passes(focus, ev)
            n = len(passes)
            value = xt_per_10(focus, ev, minutes)
            check |= {
                "value": value,
                "target": w["target"],
                "n": n,
                "unit": "threatening passes",
                "baseline": round(
                    10 * late[focus]["xt_created"] / late[focus]["minutes"], 2
                ),
                "status": (
                    "insufficient"
                    if n < MIN_SHARE_PASSES
                    else "met"
                    if value >= w["target"]
                    else "not_met"
                ),
                "rule": (
                    f"at least {MIN_SHARE_PASSES} threatening passes; no "
                    "too-close rule for xT yet"
                ),
            }
        else:
            summary = metrics.team_summary(ev, opp)
            paced = round(w["target"] * minutes / 45, 2)
            n = summary["shots"]
            check |= {
                "value": summary["xg"],
                "target": paced,
                "n": n,
                "unit": "shots by " + names[opp],
                "baseline": None,
                "status": (
                    "insufficient"
                    if n < MIN_SHOTS
                    else "met"
                    if summary["xg"] < paced
                    else "not_met"
                ),
                "rule": (
                    f"at least {MIN_SHOTS} shots; the whole-half target "
                    f"{w['target']} is paced to {minutes} minutes"
                ),
            }
            policy = "half the first-half xG, at least 0.3"
        if situation == "against":
            n = len(positive_passes(focus, ev))
            guard = {
                "label": f"{names[focus]} threat (xT) per 10 min",
                "value": xt_per_10(focus, ev, minutes),
                "reference": round(
                    10 * late[focus]["xt_created"] / late[focus]["minutes"], 2
                ),
                "reference_label": "25' to half-time",
                "n": n,
                "enough": n >= MIN_SHARE_PASSES,
                "why": (
                    "Both options give something up in attack, so watch "
                    "that our threat does not collapse."
                ),
            }
        alt, tell = ALTERNATIVES[(fid, situation)]
        best_a, best_b = BEST_WHEN[(fid, situation)]
        out[fid] = {
            "target": {
                "id": f"{fid}.{focus}.v1",
                "label": w["label"],
                "direction": w["direction"],
                "threshold": w["target"],
                "text": w["text"],
                "policy": policy,
            },
            "check": check,
            "guardrail": guard,
            "alternative": alt,
            "tell_apart": tell,
            "best_when": {"a": best_a, "b": best_b},
        }
    return out


def main() -> None:
    """Write fixtures.js: every GET and check reply the page can ask for."""
    app_module.client = None
    c = TestClient(app_module.app)
    meta = c.get("/api/match").json()
    fx: dict[str, object] = {
        "api/match": meta,
        "api/health": c.get("/api/health").json(),
        "api/events?half=1": c.get("/api/events?half=1").json(),
    }
    for focus in ("home", "away"):
        q = urlencode({"mode": "analyst", "focus": focus, "language": "en"})
        brief = c.get("/api/briefing?" + q).json()
        fx["api/briefing?" + q] = brief
        for picks in itertools.product("ab", repeat=3):
            choices = dict(
                zip(("press", "threat", "scoreline"), picks, strict=True)
            )
            r = c.post(
                "/api/check",
                json={
                    "focus": focus,
                    "choices": choices,
                    "findings": brief["findings"],
                    "changes": brief["changes"],
                },
            )
            fx[f"api/check:{focus}:{''.join(picks)}"] = r.json()
        # The page defaults a fan to the tenth player of the focus squad.
        player = meta["teams"][focus]["players"][9]["name"]
        for lang in LANGUAGES:
            q = urlencode(
                {
                    "mode": "fan",
                    "focus": focus,
                    "language": lang,
                    "player": player,
                }
            )
            fx["api/briefing?" + q] = c.get("/api/briefing?" + q).json()
    for focus in ("home", "away"):
        fx[f"proto:{focus}"] = prototype(focus)
    OUT.write_text(
        "// Recorded offline API replies, seed 27. Generated by "
        "record_fixtures.py (Claude v2); do not edit.\n"
        "window.FIXTURES = " + json.dumps(fx, separators=(",", ":")) + ";\n"
    )
    print(f"{len(fx)} replies -> {OUT}")


if __name__ == "__main__":
    main()
