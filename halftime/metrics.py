"""Deterministic match intelligence computed from the event stream.

Every number the agents talk about comes from here, so the explanations stay
grounded: the language model explains, it never invents a statistic.
"""

from __future__ import annotations

from collections import defaultdict

from .xt import pass_xt

DEFENSIVE_ACTIONS = {"tackle", "interception", "foul"}
SIDES = ("home", "away")


def other(side: str) -> str:
    return "away" if side == "home" else "home"


def window(events: list[dict], start: int = 0, end: int = 45) -> list[dict]:
    """Events with start <= minute < end (end=45 keeps first-half stoppage)."""
    if end == 45:
        return [e for e in events if e["half"] == 1 and e["minute"] >= start]
    return [e for e in events if start <= e["minute"] < end]


def pass_difficulty(e: dict) -> int:
    """0-100 rating: how hard the pass was, regardless of whether it worked."""
    p = 0.93 - 0.004 * max(0, e["length_m"] - 10) - (0.15 if e.get("under_pressure") else 0) \
        - 0.2 * max(0, (e["end_x"] - 70) / 35) - 0.05 * max(0, (e["end_x"] - e["x"]) / 20)
    return int(round(100 * min(1, max(0, 1 - p))))


def ppda(events: list[dict], pressing_side: str) -> float | None:
    """Opponent passes allowed per defensive action in the pressing zone.

    Lower means a more intense press. The zone is the opponent's first 60% of
    the pitch, measured in each team's own attacking frame.
    """
    opp = other(pressing_side)
    opp_passes = sum(1 for e in events if e["team"] == opp and e["type"] == "pass" and e["x"] < 63)
    actions = sum(1 for e in events if e["team"] == pressing_side
                  and e["type"] in DEFENSIVE_ACTIONS and e["x"] >= 42)
    return round(opp_passes / actions, 1) if actions else None


def team_summary(events: list[dict], side: str) -> dict:
    mine = [e for e in events if e["team"] == side]
    passes = [e for e in mine if e["type"] == "pass"]
    done = [e for e in passes if e["outcome"] == "complete"]
    shots = [e for e in mine if e["type"] == "shot"]
    all_passes = sum(1 for e in events if e["type"] == "pass")
    own_half_losses = sum(1 for e in events if e["team"] == other(side)
                          and e["type"] in ("tackle", "interception") and e["x"] >= 52.5)
    return {
        "goals": sum(1 for e in mine if e["type"] == "goal"),
        "shots": len(shots),
        "shots_on_target": sum(1 for e in shots if e["outcome"] in ("goal", "saved")),
        "xg": round(sum(e["xg"] for e in shots), 2),
        "big_chances": sum(1 for e in shots if e["xg"] >= 0.2),
        "passes": len(passes),
        "pass_accuracy": round(len(done) / len(passes), 3) if passes else None,
        "avg_pass_length_m": round(sum(e["length_m"] for e in passes) / len(passes), 1) if passes else None,
        "avg_pass_difficulty": round(sum(pass_difficulty(e) for e in passes) / len(passes)) if passes else None,
        "possession_pct": round(100 * len(passes) / all_passes, 1) if all_passes else None,
        "xt_created": round(sum(max(0, pass_xt(e)) for e in done), 3),
        "ppda": ppda(events, side),
        "pressures": sum(1 for e in mine if e["type"] == "pressure"),
        "turnovers_in_own_half": own_half_losses,
    }


def timeline(events: list[dict], end: int = 45, step: int = 5) -> list[dict]:
    """Five-minute windows: who had the ball, who created threat, how chaotic it was."""
    rows = []
    for start in range(0, end, step):
        stop = start + step
        evs = window(events, start, stop)
        changes = sum(1 for e in evs if e["type"] == "possession_change")
        row = {"from": start, "to": stop, "possession_changes_per_min": round(changes / step, 2)}
        for side in SIDES:
            s = team_summary(evs, side)
            row[side] = {k: s[k] for k in ("possession_pct", "xt_created", "xg", "ppda", "shots",
                                           "goals", "turnovers_in_own_half")}
        # Momentum: share of threat (xT + xG) in this window, -1 (all away) .. +1 (all home).
        h = row["home"]["xt_created"] + row["home"]["xg"]
        a = row["away"]["xt_created"] + row["away"]["xg"]
        row["momentum"] = round((h - a) / (h + a), 2) if h + a else 0.0
        rows.append(row)
    return rows


def press_rate(events: list[dict], side: str, minutes: float) -> float:
    """Pressures a team makes in the opponent's half, per minute."""
    n = sum(1 for e in events if e["team"] == side and e["type"] == "pressure" and e["x"] >= 52.5)
    return round(n / minutes, 2) if minutes else 0.0


def find_turning_point(events: list[dict], candidates=range(15, 40, 5)) -> dict:
    """Split the half where the balance of the game changed the most.

    Scores each candidate minute by the swing in possession plus the swing in
    how hard each side pressed high, both measured as rates so short and long
    spells compare fairly.
    """
    end = max(45, max((e["minute"] for e in events), default=45) + 1)
    best = None
    for t in candidates:
        before, after = window(events, 0, t), [e for e in window(events) if e["minute"] >= t]
        b, a = team_summary(before, "home"), team_summary(after, "home")
        if b["possession_pct"] is None or a["possession_pct"] is None:
            continue
        poss_shift = abs(b["possession_pct"] - a["possession_pct"])
        press_shift = max(abs(press_rate(before, s, t) - press_rate(after, s, end - t)) for s in SIDES)
        score = poss_shift + 4 * press_shift
        if best is None or score > best["score"]:
            best = {"minute": t, "score": round(score, 1)}
    t = best["minute"]
    before, after = window(events, 0, t), [e for e in window(events) if e["minute"] >= t]
    out = {"minute": t, "before": {}, "after": {}}
    for s in SIDES:
        out["before"][s] = team_summary(before, s) | {"high_presses_per_min": press_rate(before, s, t),
                                                      "minutes": t}
        out["after"][s] = team_summary(after, s) | {"high_presses_per_min": press_rate(after, s, end - t),
                                                    "minutes": end - t}
    return out


def player_stats(events: list[dict], match: dict) -> dict:
    stats: dict[str, dict] = {}
    roster = {p["id"]: (side, p) for side in SIDES for p in match["teams"][side]["players"]}
    for pid, (side, p) in roster.items():
        stats[pid] = {"name": p["name"], "team": side, "position": p["position"], "passes": 0,
                      "passes_complete": 0, "xt_created": 0.0, "shots": 0, "xg": 0.0, "goals": 0,
                      "defensive_actions": 0, "pressures": 0, "top_sprint_kmh": None,
                      "lost_ball_in_own_half": 0}
    for e in events:
        pid = e.get("player_id")
        if pid not in stats:
            continue
        s = stats[pid]
        t = e["type"]
        if t == "pass":
            s["passes"] += 1
            if e["outcome"] == "complete":
                s["passes_complete"] += 1
                s["xt_created"] += max(0, pass_xt(e))
        elif t == "shot":
            s["shots"] += 1
            s["xg"] += e["xg"]
        elif t == "goal":
            s["goals"] += 1
        elif t in DEFENSIVE_ACTIONS:
            s["defensive_actions"] += 1
        elif t == "pressure":
            s["pressures"] += 1
        elif t == "sprint":
            s["top_sprint_kmh"] = max(s["top_sprint_kmh"] or 0, e["speed_kmh"])
    # Who gave the ball away deep in their own half.
    by_name = {(v["team"], v["name"]): v for v in stats.values()}
    for e in events:
        if e["type"] in ("tackle", "interception") and e.get("from_player") and e["x"] >= 52.5:
            victim = by_name.get((other(e["team"]), e["from_player"]))
            if victim:
                victim["lost_ball_in_own_half"] += 1
    for s in stats.values():
        s["xt_created"] = round(s["xt_created"], 3)
        s["xg"] = round(s["xg"], 2)
        s["pass_accuracy"] = round(s["passes_complete"] / s["passes"], 2) if s["passes"] else None
    return stats


def key_moments(events: list[dict], limit: int = 8) -> list[dict]:
    moments = []
    for e in events:
        if e["type"] == "goal":
            moments.append({"minute": e["minute"], "second": e["second"], "kind": "goal", "team": e["team"],
                            "player": e["player"], "score": e["score"], "weight": 10})
        elif e["type"] == "shot" and e["xg"] >= 0.2 and e["outcome"] != "goal":
            moments.append({"minute": e["minute"], "second": e["second"], "kind": "big_chance_missed",
                            "team": e["team"], "player": e["player"], "xg": e["xg"],
                            "outcome": e["outcome"], "weight": 5 + 10 * e["xg"]})
    passes = sorted((e for e in events if e["type"] == "pass" and e["outcome"] == "complete"),
                    key=pass_xt, reverse=True)[:3]
    for e in passes:
        moments.append({"minute": e["minute"], "second": e["second"], "kind": "threat_pass", "team": e["team"],
                        "player": e["player"], "receiver": e["receiver"], "xt_added": pass_xt(e),
                        "length_m": e["length_m"], "difficulty": pass_difficulty(e),
                        "weight": 3 + 50 * pass_xt(e)})
    moments.sort(key=lambda m: -m["weight"])
    top = sorted(moments[:limit], key=lambda m: (m["minute"], m["second"]))
    for m in top:
        m.pop("weight")
    return top


def threat_channels(events: list[dict], side: str) -> dict:
    """Share of a team's xT by the channel the ball was moved into.

    In the attacking frame y = 0 is the team's right touchline.
    """
    totals = {"right": 0.0, "centre": 0.0, "left": 0.0}
    for e in events:
        if e["team"] == side and e["type"] == "pass" and e["outcome"] == "complete":
            gain = max(0, pass_xt(e))
            ch = "right" if e["end_y"] < 68 / 3 else "left" if e["end_y"] > 2 * 68 / 3 else "centre"
            totals[ch] += gain
    total = sum(totals.values())
    return {k: round(100 * v / total, 1) if total else 0.0 for k, v in totals.items()}


def shot_map(events: list[dict]) -> list[dict]:
    return [{"minute": e["minute"], "team": e["team"], "player": e["player"], "x": e["x"], "y": e["y"],
             "xg": e["xg"], "outcome": e["outcome"]} for e in events if e["type"] == "shot"]


def half_time_facts(match: dict) -> dict:
    """Everything the agents need about the first half, as plain JSON."""
    ev = window(match["events"])
    score = {s: sum(1 for e in ev if e["type"] == "goal" and e["team"] == s) for s in SIDES}
    players = player_stats(ev, match)
    return {
        "match_id": match["match_id"],
        "teams": {s: match["teams"][s]["name"] for s in SIDES},
        "score": score,
        "summary": {s: team_summary(ev, s) for s in SIDES},
        "timeline": timeline(ev),
        "turning_point": find_turning_point(ev),
        "threat_channels": {s: threat_channels(ev, s) for s in SIDES},
        "key_moments": key_moments(ev),
        "shots": shot_map(ev),
        "players": players,
    }
