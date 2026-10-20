"""Deterministic match intelligence computed from the event stream.

Every number the agents talk about comes from here, so the explanations stay
grounded: the language model explains, it never invents a statistic.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from .xt import pass_xt

DEFENSIVE_ACTIONS = {"tackle", "interception", "foul"}
SIDES = ("home", "away")


# One display rule per kind of metric: (decimals, scale, unit). Values keep
# their calculation precision; these apply only when a number is shown, in
# Python text and, through the briefing's "formats", on the page.
FORMAT_KINDS = {
    "count": (0, 1, ""),
    "fraction_pct": (1, 100, "%"),
    "pct": (1, 1, "%"),
    "xg": (2, 1, ""),
    "xt": (3, 1, ""),
    "rate_min": (2, 1, "/min"),
    "rate_10": (2, 1, " per 10 min"),
    # A rate whose unit is stated beside it (a table column or footnote).
    "rate": (2, 1, ""),
    "ppda": (1, 1, ""),
    "speed": (1, 1, " km/h"),
    "mean": (1, 1, ""),
}
METRIC_FORMATS = {
    **dict.fromkeys(
        (
            "goals",
            "shots",
            "shots_on_target",
            "big_chances",
            "passes",
            "passes_complete",
            "passes_under_pressure",
            "pressures",
            "high_presses",
            "turnovers_in_own_half",
            "lost_ball_in_own_half",
            "defensive_actions",
            "tackles",
            "interceptions",
            "fouls",
            "actions",
        ),
        "count",
    ),
    "pass_accuracy": "fraction_pct",
    "pass_accuracy_under_pressure": "fraction_pct",
    "possession_pct": "pct",
    "share_pct": "pct",
    "xg": "xg",
    "xg_conceded": "xg",
    "xt_created": "xt",
    "ppda": "ppda",
    "top_sprint_kmh": "speed",
    "top_speed_kmh": "speed",
}


def display(key: str, value: float | None, kind: str | None = None) -> str:
    """Format a metric for display: one rule per kind, rounding half up.

    Args:
        key: Metric key, looked up in `METRIC_FORMATS`.
        value: The value; None shows as "n/a", a measured zero as 0.
        kind: A `FORMAT_KINDS` entry that overrides the key's own, e.g.
            "rate_10" for a per-10-minute split or "mean" for a simulated
            average of a count.

    Returns:
        The value with fixed decimals and its unit, or the plain value for
        a key without a rule.
    """
    if value is None:
        return "n/a"
    # A key without its own rule may name a kind directly ("rate_min").
    spec = FORMAT_KINDS.get(kind or METRIC_FORMATS.get(key, key))
    if spec is None:
        return str(value)
    decimals, scale, unit = spec
    step = Decimal(1).scaleb(-decimals)
    exact = Decimal(str(value)) * scale
    q = exact.quantize(step, rounding=ROUND_HALF_UP)
    if exact > 0 and q == 0:
        # A small positive value must not look like a measured zero.
        return f"<{step}{unit}"
    return f"{q}{unit}"


def formats() -> dict:
    """The display rules for the page, so it formats exactly as Python does."""
    return {"kinds": FORMAT_KINDS, "keys": METRIC_FORMATS}


def other(side: str) -> str:
    """Return the opposing side."""
    return "away" if side == "home" else "home"


def window(events: list[dict], start: int = 0, end: int = 45) -> list[dict]:
    """Events with start <= minute < end (end=45 keeps first-half stoppage)."""
    if end == 45:
        return [e for e in events if e["half"] == 1 and e["minute"] >= start]
    return [e for e in events if start <= e["minute"] < end]


def pass_difficulty(e: dict) -> int:
    """0-100 rating: how hard the pass was, regardless of whether it worked."""
    p = (
        0.93
        - 0.004 * max(0, e["length_m"] - 10)
        - (0.15 if e.get("under_pressure") else 0)
        - 0.2 * max(0, (e["end_x"] - 70) / 35)
        - 0.05 * max(0, (e["end_x"] - e["x"]) / 20)
    )
    return int(round(100 * min(1, max(0, 1 - p))))


def ppda(events: list[dict], pressing_side: str) -> float | None:
    """Opponent passes allowed per defensive action in the pressing zone.

    Lower means a more intense press. The zone is the opponent's first 60% of
    the pitch, measured in each team's own attacking frame.
    """
    opp = other(pressing_side)
    opp_passes = sum(
        1
        for e in events
        if e["team"] == opp and e["type"] == "pass" and e["x"] < 63
    )
    actions = sum(
        1
        for e in events
        if e["team"] == pressing_side
        and e["type"] in DEFENSIVE_ACTIONS
        and e["x"] >= 42
    )
    return round(opp_passes / actions, 1) if actions else None


def press_resistance(passes: list[dict]) -> dict:
    """How a team's passing holds up when the passer is under pressure.

    Returns the number of pressured passes and the share completed, so a
    press can be judged by what it does to the ball, not only by its volume.
    """
    pressured = [e for e in passes if e.get("under_pressure")]
    done = [e for e in pressured if e["outcome"] == "complete"]
    return {
        "passes_under_pressure": len(pressured),
        "pass_accuracy_under_pressure": (
            round(len(done) / len(pressured), 6) if pressured else None
        ),
    }


def team_summary(events: list[dict], side: str) -> dict:
    """Headline team stats (goals, xG, passing, xT, PPDA) for one side."""
    mine = [e for e in events if e["team"] == side]
    passes = [e for e in mine if e["type"] == "pass"]
    done = [e for e in passes if e["outcome"] == "complete"]
    shots = [e for e in mine if e["type"] == "shot"]
    all_passes = sum(1 for e in events if e["type"] == "pass")
    own_half_losses = sum(
        1
        for e in events
        if e["team"] == other(side)
        and e["type"] in ("tackle", "interception")
        and e["x"] >= 52.5
    )
    return {
        "goals": sum(1 for e in mine if e["type"] == "goal"),
        "shots": len(shots),
        "shots_on_target": sum(
            1 for e in shots if e["outcome"] in ("goal", "saved")
        ),
        "xg": round(sum(e["xg"] for e in shots), 2),
        "big_chances": sum(1 for e in shots if e["xg"] >= 0.2),
        "passes": len(passes),
        "pass_accuracy": round(len(done) / len(passes), 6) if passes else None,
        "avg_pass_length_m": round(
            sum(e["length_m"] for e in passes) / len(passes), 1
        )
        if passes
        else None,
        "avg_pass_difficulty": round(
            sum(pass_difficulty(e) for e in passes) / len(passes)
        )
        if passes
        else None,
        "possession_pct": round(100 * len(passes) / all_passes, 1)
        if all_passes
        else None,
        "xt_created": round(sum(max(0, pass_xt(e)) for e in done), 3),
        **press_resistance(passes),
        "ppda": ppda(events, side),
        "pressures": sum(1 for e in mine if e["type"] == "pressure"),
        "high_presses": sum(
            1 for e in mine if e["type"] == "pressure" and e["x"] >= 52.5
        ),
        "turnovers_in_own_half": own_half_losses,
    }


def timeline(events: list[dict], end: int = 45, step: int = 5) -> list[dict]:
    """Five-minute windows of possession, threat and chaos."""
    rows = []
    for start in range(0, end, step):
        stop = start + step
        evs = window(events, start, stop)
        changes = sum(1 for e in evs if e["type"] == "possession_change")
        row = {
            "from": start,
            "to": stop,
            "possession_changes_per_min": round(changes / step, 2),
        }
        for side in SIDES:
            s = team_summary(evs, side)
            row[side] = {
                k: s[k]
                for k in (
                    "possession_pct",
                    "xt_created",
                    "xg",
                    "ppda",
                    "shots",
                    "goals",
                    "turnovers_in_own_half",
                )
            }
        # Momentum: share of threat (xT + xG) in this window,
        # from -1 (all away) to +1 (all home).
        h = row["home"]["xt_created"] + row["home"]["xg"]
        a = row["away"]["xt_created"] + row["away"]["xg"]
        row["momentum"] = round((h - a) / (h + a), 2) if h + a else 0.0
        rows.append(row)
    return rows


def press_rate(events: list[dict], side: str, minutes: float) -> float:
    """Pressures a team makes in the opponent's half, per minute."""
    n = sum(
        1
        for e in events
        if e["team"] == side and e["type"] == "pressure" and e["x"] >= 52.5
    )
    return round(n / minutes, 2) if minutes else 0.0


def find_turning_point(
    events: list[dict], candidates: range = range(15, 40, 5)
) -> dict:
    """Split the half where the balance of the game changed the most.

    Scores each candidate minute by the swing in possession plus the swing in
    how hard each side pressed high, both measured as rates so short and long
    spells compare fairly.
    """
    end = max(45, max((e["minute"] for e in events), default=45) + 1)
    best = None
    for t in candidates:
        before, after = (
            window(events, 0, t),
            [e for e in window(events) if e["minute"] >= t],
        )
        b, a = team_summary(before, "home"), team_summary(after, "home")
        if b["possession_pct"] is None or a["possession_pct"] is None:
            continue
        poss_shift = abs(b["possession_pct"] - a["possession_pct"])
        press_shift = max(
            abs(press_rate(before, s, t) - press_rate(after, s, end - t))
            for s in SIDES
        )
        score = poss_shift + 4 * press_shift
        if best is None or score > best["score"]:
            best = {"minute": t, "score": round(score, 1)}
    t = best["minute"]
    before, after = (
        window(events, 0, t),
        [e for e in window(events) if e["minute"] >= t],
    )
    out = {"minute": t, "before": {}, "after": {}}
    for s in SIDES:
        out["before"][s] = team_summary(before, s) | {
            "high_presses_per_min": press_rate(before, s, t),
            "minutes": t,
        }
        out["after"][s] = team_summary(after, s) | {
            "high_presses_per_min": press_rate(after, s, end - t),
            "minutes": end - t,
        }
    return out


def player_stats(events: list[dict], match: dict) -> dict:
    """Per-player passing, shooting, defending and running stats by id."""
    stats: dict[str, dict] = {}
    roster = {
        p["id"]: (side, p)
        for side in SIDES
        for p in match["teams"][side]["players"]
    }
    for pid, (side, p) in roster.items():
        stats[pid] = {
            "name": p["name"],
            "team": side,
            "position": p["position"],
            "passes": 0,
            "passes_complete": 0,
            "xt_created": 0.0,
            "shots": 0,
            "xg": 0.0,
            "goals": 0,
            "defensive_actions": 0,
            "tackles": 0,
            "interceptions": 0,
            "fouls": 0,
            "pressures": 0,
            "top_sprint_kmh": None,
            "lost_ball_in_own_half": 0,
        }
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
            # The broad count (fouls included, as PPDA uses) plus each kind,
            # so a card can say "tackles" without counting fouls.
            s["defensive_actions"] += 1
            s[
                {"tackle": "tackles", "interception": "interceptions"}.get(
                    t, "fouls"
                )
            ] += 1
        elif t == "pressure":
            s["pressures"] += 1
        elif t == "sprint":
            s["top_sprint_kmh"] = max(s["top_sprint_kmh"] or 0, e["speed_kmh"])
    # Who gave the ball away deep in their own half.
    by_name = {(v["team"], v["name"]): v for v in stats.values()}
    for e in events:
        if (
            e["type"] in ("tackle", "interception")
            and e.get("from_player")
            and e["x"] >= 52.5
        ):
            victim = by_name.get((other(e["team"]), e["from_player"]))
            if victim:
                victim["lost_ball_in_own_half"] += 1
    for s in stats.values():
        s["xt_created"] = round(s["xt_created"], 3)
        s["xg"] = round(s["xg"], 2)
        # Kept precise: 35 of 44 is 79.5%, which a value stored as 0.80
        # would show as 80.0%.
        s["pass_accuracy"] = (
            round(s["passes_complete"] / s["passes"], 6)
            if s["passes"]
            else None
        )
    return stats


HEAT_COLS, HEAT_ROWS = 12, 8
ACTION_TYPES = {"pass", "shot", "pressure", "tackle", "interception", "foul"}


def _channel(y: float) -> str:
    """Channel in the attacking frame, matching `threat_channels`."""
    if y < 68 / 3:
        return "right"
    if y > 2 * 68 / 3:
        return "left"
    return "centre"


def player_heatmaps(events: list[dict], match: dict) -> dict:
    """Where each player acted, as a coarse grid in their attacking frame.

    Counts the player's own actions (passes, shots, pressures, tackles,
    interceptions, fouls) at their start point, plus completed passes they
    received at the end point. This is event data, not tracking: it shows
    where a player touched the game, not where they stood.

    Returns, by player id, the grid (``HEAT_ROWS`` rows by ``HEAT_COLS``
    columns, row 0 at y = 0), the action count, the shares of actions in
    each third and channel, and the average x.
    """
    names = {
        (side, p["name"]): p["id"]
        for side in SIDES
        for p in match["teams"][side]["players"]
    }
    points: dict[str, list[tuple[float, float]]] = {
        pid: [] for pid in names.values()
    }
    for e in events:
        if e["type"] in ACTION_TYPES and e.get("player_id") in points:
            points[e["player_id"]].append((e["x"], e["y"]))
        if (
            e["type"] == "pass"
            and e["outcome"] == "complete"
            and (e["team"], e.get("receiver")) in names
        ):
            pid = names[(e["team"], e["receiver"])]
            points[pid].append((e["end_x"], e["end_y"]))
    out = {}
    for pid, pts in points.items():
        grid = [[0] * HEAT_COLS for _ in range(HEAT_ROWS)]
        thirds = {"defensive": 0, "middle": 0, "final": 0}
        channels = {"right": 0, "centre": 0, "left": 0}
        for x, y in pts:
            col = min(HEAT_COLS - 1, max(0, int(x / 105 * HEAT_COLS)))
            row = min(HEAT_ROWS - 1, max(0, int(y / 68 * HEAT_ROWS)))
            grid[row][col] += 1
            third = "defensive" if x < 35 else "final" if x >= 70 else "middle"
            thirds[third] += 1
            channels[_channel(y)] += 1
        n = len(pts)
        out[pid] = {
            "grid": grid,
            "actions": n,
            "avg_x": round(sum(x for x, _ in pts) / n, 1) if n else None,
            "thirds_pct": {
                k: round(100 * v / n, 1) if n else 0.0
                for k, v in thirds.items()
            },
            "channels_pct": {
                k: round(100 * v / n, 1) if n else 0.0
                for k, v in channels.items()
            },
        }
    return out


def player_cards(events: list[dict], match: dict, side: str) -> list[dict]:
    """One card per player of a side: stats, heatmap and a computed insight.

    The insight is written in code from the numbers on the card, so it can
    sit next to model output without being checked.
    """
    stats = player_stats(events, match)
    heat = player_heatmaps(events, match)
    squad = [p for p in match["teams"][side]["players"]]
    xt_rank = sorted(
        (p["id"] for p in squad),
        key=lambda pid: -stats[pid]["xt_created"],
    )
    cards = []
    for p in squad:
        st, hm = stats[p["id"]], heat[p["id"]]
        cards.append(
            {
                "id": p["id"],
                "name": p["name"],
                "position": p["position"],
                "number": p["number"],
                "stats": st,
                "heatmap": hm,
                "xt_rank": xt_rank.index(p["id"]) + 1,
                "insight": _player_insight(p, st, hm),
            }
        )
    return cards


# Role families for player insights. Position alone decides which measured
# numbers lead; no claim goes beyond the card's own stats.
ROLE_FAMILIES = {
    "GK": "gk",
    "CB": "cb",
    "RB": "fb",
    "LB": "fb",
    "DM": "dm",
    "CM": "cm",
    "RW": "winger",
    "LW": "winger",
    "ST": "st",
}


def _player_insight(p: dict, st: dict, hm: dict) -> str:
    """Two or three plain sentences, led by what matters for the position.

    Uses only the card's stats and heatmap, formatted with `display`. Event
    locations are recorded actions, not time spent or distance covered.
    """
    name, pos = p["name"], p["position"]
    if not hm["actions"]:
        return f"{name} ({pos}) had no recorded actions in the first half."

    def n(key: str) -> str:
        return display(key, st[key])

    passing = (
        f"completed {n('passes_complete')} of {n('passes')} passes "
        f"({n('pass_accuracy')})"
        if st["passes"]
        else "made no passes"
    )
    losses = st["lost_ball_in_own_half"]
    lost = (
        f"{losses} own-half loss{'es' if losses != 1 else ''} "
        f"{'were' if losses != 1 else 'was'} attributed to {name}"
    )
    defending = (
        f"{n('tackles')} tackle{'s' if st['tackles'] != 1 else ''} and "
        f"{n('interceptions')} interception"
        f"{'s' if st['interceptions'] != 1 else ''}"
    )
    shooting = (
        f"{n('shots')} shot{'s' if st['shots'] != 1 else ''} worth "
        f"{n('xg')} xG and {n('goals')} goal{'s' if st['goals'] != 1 else ''}"
        if st["shots"]
        else "no shots"
    )
    threat = f"created {n('xt_created')} xT"
    role = ROLE_FAMILIES.get(pos, "other")
    lead = {
        "gk": f"{name} ({pos}) {passing}; {lost}.",
        "cb": f"{name} ({pos}) made {defending}; {lost}. In build-up, "
        f"{passing}.",
        "fb": f"{name} ({pos}) {threat} and made {defending}; {passing}.",
        "dm": f"{name} ({pos}) {passing}; {lost}. Without the ball: "
        f"{defending}.",
        "cm": f"{name} ({pos}) {threat} and {passing}; "
        f"{n('pressures')} pressures.",
        "winger": f"{name} ({pos}) {threat} and had {shooting}.",
        "st": f"{name} ({pos}) recorded {shooting}. In link play, {passing}; "
        f"{n('pressures')} pressures.",
        "other": f"{name} ({pos}) {passing}; {threat}.",
    }[role]
    third = max(hm["thirds_pct"], key=hm["thirds_pct"].get)
    where = (
        f"{display('actions', hm['actions'])} recorded actions, "
        f"{display('share_pct', hm['thirds_pct'][third])} in the {third} "
        "third."
    )
    return f"{lead} {where}"


def key_moments(events: list[dict], limit: int = 8) -> list[dict]:
    """Goals, big chances and other standout events, most important first."""
    moments = []
    for e in events:
        if e["type"] == "goal":
            moments.append(
                {
                    "minute": e["minute"],
                    "second": e["second"],
                    "kind": "goal",
                    "team": e["team"],
                    "player": e["player"],
                    "score": e["score"],
                    "weight": 10,
                }
            )
        elif e["type"] == "shot" and e["xg"] >= 0.2 and e["outcome"] != "goal":
            moments.append(
                {
                    "minute": e["minute"],
                    "second": e["second"],
                    "kind": "big_chance_missed",
                    "team": e["team"],
                    "player": e["player"],
                    "xg": e["xg"],
                    "outcome": e["outcome"],
                    "weight": 5 + 10 * e["xg"],
                }
            )
    passes = sorted(
        (
            e
            for e in events
            if e["type"] == "pass" and e["outcome"] == "complete"
        ),
        key=pass_xt,
        reverse=True,
    )[:3]
    for e in passes:
        moments.append(
            {
                "minute": e["minute"],
                "second": e["second"],
                "kind": "threat_pass",
                "team": e["team"],
                "player": e["player"],
                "receiver": e["receiver"],
                "xt_added": pass_xt(e),
                "length_m": e["length_m"],
                "difficulty": pass_difficulty(e),
                "weight": 3 + 50 * pass_xt(e),
            }
        )
    moments.sort(key=lambda m: -m["weight"])
    top = sorted(moments[:limit], key=lambda m: (m["minute"], m["second"]))
    for m in top:
        m.pop("weight")
    return top


MOMENTS_PER_FINDING = 3


def moments_for_finding(finding: dict, key_moments: list[dict]) -> list[dict]:
    """The key moments an analyst would clip for one finding.

    A press finding takes moments after the switch; a threat finding takes
    the dominant side's moments after it; the scoreline finding takes goals
    and big chances. A list may be short or empty: a moment from another
    team or time would show the analyst evidence for a different story.
    """
    t = finding.get("minute", 0)
    team = finding.get("team")
    if finding["id"] == "press":
        picked = [m for m in key_moments if m["minute"] >= t]
    elif finding["id"] == "threat":
        picked = [
            m for m in key_moments if m["minute"] >= t and m["team"] == team
        ]
    else:
        picked = [
            m
            for m in key_moments
            if m["kind"] in ("goal", "big_chance_missed")
        ]
    picked.sort(key=lambda m: (m["minute"], m["second"]))
    return [
        {k: m[k] for k in ("minute", "second", "kind", "team", "player")}
        | ({"receiver": m["receiver"]} if "receiver" in m else {})
        for m in picked[:MOMENTS_PER_FINDING]
    ]


def threat_channels(events: list[dict], side: str) -> dict:
    """Share of a team's xT by the channel the ball was moved into.

    In the attacking frame y = 0 is the team's right touchline. A team with
    no threatening pass has no shares (None), not 0% in every channel, so a
    "share below N%" target cannot pass on no evidence.
    """
    totals = {"right": 0.0, "centre": 0.0, "left": 0.0}
    for e in events:
        if (
            e["team"] == side
            and e["type"] == "pass"
            and e["outcome"] == "complete"
        ):
            gain = max(0, pass_xt(e))
            ch = (
                "right"
                if e["end_y"] < 68 / 3
                else "left"
                if e["end_y"] > 2 * 68 / 3
                else "centre"
            )
            totals[ch] += gain
    total = sum(totals.values())
    return {
        k: round(100 * v / total, 1) if total else None
        for k, v in totals.items()
    }


def threat_passes(events: list[dict], side: str) -> int:
    """Completed passes by a team that moved the ball to higher xT."""
    return sum(
        1
        for e in events
        if e["team"] == side
        and e["type"] == "pass"
        and e["outcome"] == "complete"
        and pass_xt(e) > 0
    )


# Proposed evidence policy for the second-half check (agent log, 2026-10-20).
# These are policy defaults for discussion, not football facts: below a
# floor the check reports "insufficient" instead of a verdict.
MIN_RATE_EVENTS = 10  # events behind a per-minute rate
MIN_SHARE_PASSES = 20  # threatening passes behind a share or an xT rate
MIN_SHOTS = 5  # shots behind an xG total
EVIDENCE_STATUSES = ("met", "not_met", "too_close", "insufficient")


def rate_se(n: int, minutes: float) -> float:
    """Rough standard error of a per-minute rate from a count (Poisson)."""
    return n**0.5 / minutes if minutes else 0.0


def evidence_status(
    value: float | None,
    target: float,
    direction: str,
    n: int,
    minimum: int,
    se: float | None = None,
) -> str:
    """Judge a measured value against its target under the evidence policy.

    Args:
        value: The measured value, or None when nothing could be measured.
        target: The threshold.
        direction: "below" or "at_least".
        n: How many events the value rests on.
        minimum: The policy floor for `n`.
        se: For rates, a standard error; within one of the target the result
            is "too_close". Shares and xG pass None and get no such band.

    Returns:
        One of `EVIDENCE_STATUSES`.
    """
    if value is None or n < minimum:
        return "insufficient"
    if se is not None and abs(value - target) < se:
        return "too_close"
    met = value < target if direction == "below" else value >= target
    return "met" if met else "not_met"


def shot_map(events: list[dict]) -> list[dict]:
    """Every shot with its location, xG and outcome."""
    return [
        {
            "minute": e["minute"],
            "team": e["team"],
            "player": e["player"],
            "x": e["x"],
            "y": e["y"],
            "xg": e["xg"],
            "outcome": e["outcome"],
        }
        for e in events
        if e["type"] == "shot"
    ]


# (key, label, better) per section. "better" says which way is good for the
# team the row describes, so the page can colour a change without guessing.
ATTACK_ROWS = (
    ("goals", "Goals", "higher"),
    ("xg", "Expected goals (xG)", "higher"),
    ("shots", "Shots", "higher"),
    ("big_chances", "Big chances", "higher"),
    ("xt_created", "Threat created (xT)", "higher"),
    ("possession_pct", "Possession %", "higher"),
    ("pass_accuracy", "Pass accuracy", "higher"),
    ("pass_accuracy_under_pressure", "Pass accuracy under pressure", "higher"),
)
DEFENCE_ROWS = (
    ("ppda", "PPDA", "lower"),
    ("high_presses", "High presses", "higher"),
    ("pressures", "Pressures", "higher"),
    ("xg_conceded", "xG conceded", "lower"),
    ("turnovers_in_own_half", "Balls lost in own half", "lower"),
)


def team_report(facts: dict, focus: str) -> dict:
    """Attacking and defending rows for both teams, split at the turning point.

    Each row carries the focus team's and the opponent's value for the half,
    plus the focus team's value before and after the turning point as a
    per-minute rate where the raw count would depend on the window length.
    """
    opp = other(focus)
    tp = facts["turning_point"]
    rate_keys = {
        "goals",
        "shots",
        "big_chances",
        "xt_created",
        "high_presses",
        "pressures",
        "turnovers_in_own_half",
        "xg",
        "xg_conceded",
    }

    def value(summary: dict, side: str, key: str) -> float | None:
        if key == "xg_conceded":
            return summary[other(side)]["xg"]
        return summary[side][key]

    def per_10(v: float | None, minutes: float) -> float | None:
        return None if v is None or not minutes else round(10 * v / minutes, 2)

    def rows(spec: tuple) -> list[dict]:
        out = []
        for key, label, better in spec:
            before = value(tp["before"], focus, key)
            after = value(tp["after"], focus, key)
            rated = key in rate_keys
            if rated:
                before = per_10(before, tp["before"][focus]["minutes"])
                after = per_10(after, tp["after"][focus]["minutes"])
            out.append(
                {
                    "key": key,
                    "label": label,
                    "better": better,
                    "us": value(facts["summary"], focus, key),
                    "them": value(facts["summary"], opp, key),
                    "us_before": before,
                    "us_after": after,
                    "split_unit": "per 10 min" if rated else "",
                }
            )
        return out

    return {
        "focus": focus,
        "turning_point": tp["minute"],
        "attack": rows(ATTACK_ROWS),
        "defence": rows(DEFENCE_ROWS),
        "threat_channels": facts["threat_channels"],
    }


def half_time_facts(match: dict) -> dict:
    """Everything the agents need about the first half, as plain JSON."""
    ev = window(match["events"])
    score = {
        s: sum(1 for e in ev if e["type"] == "goal" and e["team"] == s)
        for s in SIDES
    }
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
