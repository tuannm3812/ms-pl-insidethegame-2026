"""The half-time agents.

Five roles, run in order:

  1. Stats agent      computes every number (deterministic code, also
                      served over MCP)
  2. Tactics agent    finds the three patterns that decided the half
  3. Explainer agent  says why each pattern matters (control vs chaos,
                      pressure, rhythm)
  4. Coach agent      offers two options per finding, each with its
                      trade-off (analyst mode)
     Verifier agent   at 60', checks the chosen option against its target
                      (analyst mode, on request)
     Fan agent        turns them into a story about your team/player
                      (fan mode)
  5. Overlay agent    renders timed, machine-readable graphics cards

Steps 2-4 run on Microsoft Agent Framework when a model is configured
(Microsoft Foundry, or any OpenAI-compatible endpoint). Without one they fall
back to rule-based versions, so the demo always works and the output shape is
identical either way.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated, Any

from . import metrics, prematch
from .metrics import SIDES, other

if TYPE_CHECKING:
    from agent_framework import BaseChatClient, FunctionTool

# ---------------------------------------------------------------------------
# Model client
# ---------------------------------------------------------------------------


def load_env_file(path: str = ".env") -> None:
    """Read KEY=VALUE lines from a local .env file into the environment.

    Keeps keys out of the code and out of shell history. Values already set
    in the environment win, and a missing file is fine.
    """
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.removeprefix("export ").split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def azure_resource_endpoint(url: str) -> str:
    """Return the resource root of any Foundry/Azure OpenAI portal URL."""
    m = re.match(r"(https://[^/]+)", url.strip())
    return m.group(1) + "/" if m else url


def make_client() -> BaseChatClient | None:
    """Pick a chat client from the environment, or None for offline mode."""
    load_env_file()
    if os.getenv("FOUNDRY_PROJECT_ENDPOINT") and os.getenv("FOUNDRY_MODEL"):
        from agent_framework.foundry import FoundryChatClient
        from azure.identity import DefaultAzureCredential

        return FoundryChatClient(credential=DefaultAzureCredential())
    if os.getenv("AZURE_OPENAI_ENDPOINT") and os.getenv(
        "AZURE_OPENAI_API_KEY"
    ):
        # Key-based access to a model deployed in Foundry (Azure OpenAI v1).
        from agent_framework.openai import OpenAIChatClient

        return OpenAIChatClient(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT")
            or os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            azure_endpoint=azure_resource_endpoint(
                os.environ["AZURE_OPENAI_ENDPOINT"]
            ),
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
        )
    if os.getenv("OPENAI_API_KEY"):
        from agent_framework.openai import OpenAIChatClient

        return OpenAIChatClient(
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            api_key=os.environ["OPENAI_API_KEY"],
        )
    return None


def backend_name(client: BaseChatClient | None) -> str:
    """Short label for the active backend, shown in the page header."""
    return "offline-rules" if client is None else type(client).__name__


# ---------------------------------------------------------------------------
# Tools the LLM agents may call (thin wrappers over metrics)
# ---------------------------------------------------------------------------


def build_tools(
    match: dict, seen: list[str] | None = None
) -> list[FunctionTool]:
    """Wrap the metric functions as Agent Framework tools for one match.

    Args:
        match: The generated match.
        seen: If given, every tool result is appended to it, so the numbers a
            model looked up count as grounded.

    Returns:
        The tools, ready to hand to an agent.
    """
    from agent_framework import tool

    def _out(value: Any) -> str:
        text = json.dumps(value)
        if seen is not None:
            seen.append(text)
        return text

    events = metrics.window(match["events"])
    names = {s: match["teams"][s]["name"] for s in SIDES}

    def _side(team: str) -> str:
        t = team.lower()
        for s in SIDES:
            if t in (s, names[s].lower(), match["teams"][s]["short"].lower()):
                return s
        raise ValueError(
            f"unknown team {team!r}; use one of {list(names.values())}"
        )

    @tool(
        description=(
            "Team stats (possession, xG, xT, PPDA, turnovers) between two "
            "minutes of the first half."
        )
    )
    def team_stats(
        team: Annotated[str, "team name, short code, or home/away"],
        from_minute: Annotated[int, "start minute, inclusive"] = 0,
        to_minute: Annotated[
            int, "end minute, exclusive; 45 includes stoppage time"
        ] = 45,
    ) -> str:
        evs = [
            e
            for e in events
            if from_minute
            <= e["minute"]
            < (99 if to_minute >= 45 else to_minute)
        ]
        return _out(metrics.team_summary(evs, _side(team)))

    @tool(description="First-half stats for one player by surname.")
    def player_stats(player: Annotated[str, "player surname"]) -> str:
        for p in metrics.player_stats(events, match).values():
            if p["name"].lower() == player.lower():
                return _out(p)
        return _out({"error": f"no player called {player}"})

    @tool(
        description=(
            "Where a team's threat (xT) came from by channel, optionally "
            "only after a minute."
        )
    )
    def threat_channels(
        team: Annotated[str, "team name or home/away"],
        from_minute: Annotated[int, "only count passes from this minute"] = 0,
    ) -> str:
        evs = [e for e in events if e["minute"] >= from_minute]
        return _out(metrics.threat_channels(evs, _side(team)))

    return [team_stats, player_stats, threat_channels]


async def _run_agent(
    client: BaseChatClient,
    name: str,
    instructions: str,
    payload: dict,
    tools: list[FunctionTool] | None = None,
) -> Any:
    """Run one Agent Framework agent and parse the JSON it returns."""
    from agent_framework import Agent

    agent = Agent(
        client,
        instructions=instructions
        + "\n\nReply with JSON only, no prose around it.",
        name=name,
        tools=tools,
    )
    message = json.dumps(payload, default=str)
    try:
        return parse_json_reply((await agent.run(message)).text)
    # One retry: models sometimes wrap the JSON in prose.
    except ValueError:
        return parse_json_reply((await agent.run(message)).text)


def parse_json_reply(text: str) -> Any:
    """Return the first JSON object, or array of objects, in a model reply.

    Code fences and surrounding prose are ignored, and so is incidental JSON
    such as "[3]" in the prose.
    """
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    decoder = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch in "[{":
            try:
                value = decoder.raw_decode(text, i)[0]
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict) or (
                isinstance(value, list)
                and value
                and all(isinstance(v, dict) for v in value)
            ):
                return value
    raise ValueError(f"no JSON in model reply: {text[:80]!r}")


# ---------------------------------------------------------------------------
# Checks on model replies. A reply that fails one is treated like a reply
# that could not be parsed: the step falls back to its rule-based version.
# ---------------------------------------------------------------------------

FINDING_IDS = ("press", "threat", "scoreline")
CHANNELS = ("left", "centre", "right")
# Numbers a model may use without them appearing in its input: small counts
# such as "three changes", and "45" for a half. Kept short on purpose; any
# other number has to come from the input.
FREE_NUMBERS = {0, 1, 2, 3, 45}
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def _require(ok: bool, what: str) -> None:
    if not ok:
        raise ValueError(f"model reply rejected: {what}")


def _is_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _same_text(a: str, b: str) -> bool:
    """Two texts that differ only in case, spacing or end punctuation."""

    def norm(t: str) -> str:
        return " ".join(t.casefold().split()).rstrip(".!")

    return norm(a) == norm(b)


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _evidence_value_ok(item: dict) -> bool:
    """Evidence is {before, after} numbers, or a value the page can show."""
    if "before" in item or "after" in item:
        # A window with nothing to measure (no pressured passes, say) is None
        # in the facts; the page shows it as n/a.
        pair = (item.get("before"), item.get("after"))
        return any(_is_number(v) for v in pair) and all(
            v is None or _is_number(v) for v in pair
        )
    value = item.get("value")
    if isinstance(value, dict):
        return bool(value) and all(_is_number(v) for v in value.values())
    return _is_number(value) or _is_text(value)


def check_findings(findings: Any) -> list[dict]:
    """Reject tactics output the explainer, coach and page cannot use."""
    _require(isinstance(findings, list), "findings must be a list")
    _require(
        all(
            isinstance(f, dict) and f.get("id") in FINDING_IDS
            for f in findings
        )
        and sorted(f["id"] for f in findings) == sorted(FINDING_IDS),
        f"findings need exactly the ids {FINDING_IDS}",
    )
    for f in findings:
        _require(f.get("team") in SIDES, f"{f['id']}: team must be home/away")
        _require(_is_text(f.get("title")), f"{f['id']}: title missing")
        _require(_is_text(f.get("concept")), f"{f['id']}: concept missing")
        _require(
            isinstance(f.get("evidence"), list)
            and f["evidence"]
            and all(
                isinstance(e, dict)
                and _is_text(e.get("label"))
                and _evidence_value_ok(e)
                for e in f["evidence"]
            ),
            f"{f['id']}: evidence must list labelled values",
        )
        _require(
            isinstance(f.get("minute"), int | float), f"{f['id']}: minute"
        )
        if f["id"] == "threat":
            _require(f.get("channel") in CHANNELS, "threat: channel")
            _require(
                isinstance(f.get("creators"), list)
                and f["creators"]
                and all(_is_text(c) for c in f["creators"]),
                "threat: creators must name at least one player",
            )
        if f["id"] == "scoreline":
            _require(
                isinstance(f.get("goals_minus_xg"), int | float),
                "scoreline: goals_minus_xg must be a number",
            )
            _require(
                f.get("weak_link") is None or _is_text(f["weak_link"]),
                "scoreline: weak_link must be a name or null",
            )
    return findings


def check_explanations(explanations: Any) -> list[dict]:
    """Reject explainer output that does not cover every finding."""
    _require(isinstance(explanations, list), "explanations must be a list")
    _require(
        all(
            isinstance(x, dict)
            and x.get("id") in FINDING_IDS
            and _is_text(x.get("concept"))
            and _is_text(x.get("why_it_matters"))
            for x in explanations
        ),
        "each explanation needs id, concept and why_it_matters",
    )
    _require(
        {x["id"] for x in explanations} == set(FINDING_IDS),
        "explanations must cover every finding",
    )
    return explanations


CHANGE_TEXT_FIELDS = (
    "action",
    "tradeoff",
    "alternative",
    "alternative_tradeoff",
    "watch",
)


def check_changes(changes: Any) -> list[dict]:
    """Reject coach output that is not three changes, one per finding.

    Each change carries two options, each with its trade-off, so the coach
    is offered a choice rather than an order.
    """
    _require(isinstance(changes, list), "changes must be a list")
    _require(len(changes) == 3, "changes must be three items")
    for c in changes:
        _require(isinstance(c, dict), "each change must be an object")
        # Name the bad field so a live fallback in the trace is diagnosable.
        _require(
            c.get("finding") in FINDING_IDS,
            f"change finding must be one of {FINDING_IDS}",
        )
        _require(
            all(_is_text(c.get(k)) for k in CHANGE_TEXT_FIELDS),
            "change action, tradeoff, alternative, alternative_tradeoff "
            "and watch must be non-empty text",
        )
        _require(
            not _same_text(c["action"], c["alternative"]),
            f"{c['finding']}: alternative repeats the recommended option",
        )
    _require(
        {c["finding"] for c in changes} == set(FINDING_IDS),
        "changes must cover each finding once",
    )
    return changes


def check_fan(fan: Any) -> dict:
    """Reject fan output the page cannot render."""
    _require(isinstance(fan, dict), "fan story must be an object")
    _require(_is_text(fan.get("headline")), "fan: headline missing")
    _require(
        isinstance(fan.get("story"), list)
        and fan["story"]
        and all(_is_text(p) for p in fan["story"]),
        "fan: story must be a list of paragraphs",
    )
    spot = fan.get("spotlight")
    _require(
        spot is None
        or (
            isinstance(spot, dict)
            and _is_text(spot.get("player"))
            and _is_text(spot.get("line"))
        ),
        "fan: spotlight must be {player, line} or null",
    )
    _require(_is_text(fan.get("watch_for")), "fan: watch_for missing")
    return fan


def _numbers_in(value: Any, skip: tuple[str, ...] = ()) -> list[float]:
    """Every number in a reply, from numeric values and from inside text."""
    if isinstance(value, bool):
        return []
    if isinstance(value, int | float):
        return [abs(float(value))]
    if isinstance(value, str):
        return [float(n) for n in _NUMBER.findall(value)]
    if isinstance(value, dict):
        return [
            n
            for k, v in value.items()
            if k not in skip
            for n in _numbers_in(v, skip)
        ]
    if isinstance(value, list):
        return [n for v in value for n in _numbers_in(v, skip)]
    return []


def grounded_numbers(*sources: Any) -> set[float]:
    """Numbers a reply may quote: those in its inputs, in any usual rounding.

    A share such as 0.834 may also appear as a percentage (83 or 83.4).
    """
    allowed = {float(n) for n in FREE_NUMBERS}
    for source in sources:
        for n in _numbers_in(source):
            forms = {n, round(n), round(n, 1), round(n, 2)}
            if n <= 1:
                forms |= {round(100 * n), round(100 * n, 1)}
            allowed |= {float(f) for f in forms}
    return allowed


def check_grounded(
    reply: Any, allowed: set[float], skip: tuple[str, ...] = ()
) -> Any:
    """Reject a reply that states a number its inputs do not contain.

    This is a number filter, not a full proof: it checks that each number
    exists somewhere in the input, not that it describes the right team,
    metric or window. Keys in ``skip`` are not checked.
    """
    invented = sorted(
        {n for n in _numbers_in(reply, skip) if round(n, 2) not in allowed}
    )
    _require(not invented, f"numbers not in the input: {invented[:5]}")
    return reply


# ---------------------------------------------------------------------------
# Rule-based versions (offline mode, and the fallback if a model reply breaks)
# ---------------------------------------------------------------------------


def _per_min(n: float, minutes: float) -> float:
    return round(n / minutes, 2) if minutes else 0.0


def _per_10(n: float, minutes: float) -> float:
    return round(10 * n / minutes, 2) if minutes else 0.0


def _own_half_losses(facts: dict, side: str) -> dict[str, float]:
    """Own-half losses per minute, before and after the turning point.

    Read from the facts rather than a finding's evidence labels, which a model
    may word differently.
    """
    tp = facts["turning_point"]
    return {
        when: _per_min(
            tp[when][side]["turnovers_in_own_half"], tp[when][side]["minutes"]
        )
        for when in ("before", "after")
    }


def _possession_changes(facts: dict) -> dict[str, float]:
    """Possession changes per minute, before and after the turning point."""
    tl = facts["timeline"]
    t = facts["turning_point"]["minute"]
    return {
        "before": round(
            sum(w["possession_changes_per_min"] for w in tl if w["to"] <= t)
            / max(1, t // 5),
            2,
        ),
        "after": round(
            sum(w["possession_changes_per_min"] for w in tl if w["from"] >= t)
            / max(1, (45 - t) // 5),
            2,
        ),
    }


# Minutes of timeline the coach looks back over to judge momentum.
MOMENTUM_WINDOW_MIN = 15


def coach_targets(facts: dict, focus: str) -> dict:
    """Second-half targets the coach may set, computed in code."""
    opp = other(focus)
    return {
        "opponent_threat_share_in_channel_pct_below": 40,
        "opponent_second_half_xg_below": max(
            0.3, round(facts["summary"][opp]["xg"] / 2, 1)
        ),
        "own_half_losses_per_min": {
            side: _own_half_losses(facts, side) for side in SIDES
        },
        "momentum_window_minutes": MOMENTUM_WINDOW_MIN,
    }


def watch_targets(facts: dict, findings: list[dict], focus: str) -> dict:
    """The one measurable target per finding, worded and valued in code.

    The coach's Watch line and the 60' check both read from here, so the
    target the analyst sees is exactly the target that gets checked.

    Returns:
        Finding id mapped to {label, target, direction, text}; direction is
        "below" or "at_least".
    """
    names = facts["teams"]
    opp = other(focus)
    by_id = {f["id"]: f for f in findings}
    targets = coach_targets(facts, focus)
    watch = {}

    if by_id["press"]["team"] == opp:
        lost = _own_half_losses(facts, focus)
        watch["press"] = {
            "label": f"{names[focus]} balls lost in own half per min",
            "target": lost["before"],
            "direction": "below",
            "text": (
                f"Balls lost in our half back under {lost['before']} a "
                f"minute (now {lost['after']})."
            ),
        }
    else:
        lost = _own_half_losses(facts, opp)
        watch["press"] = {
            "label": f"{names[opp]} balls lost in own half per min",
            "target": lost["after"],
            "direction": "at_least",
            "text": (
                f"Keep {names[opp]} losing the ball in their half at "
                f"least {lost['after']} times a minute."
            ),
        }

    threat = by_id["threat"]
    if threat["team"] == opp:
        limit = targets["opponent_threat_share_in_channel_pct_below"]
        watch["threat"] = {
            "label": (
                f"{names[opp]} share of threat down the {threat['channel']} %"
            ),
            "target": limit,
            "direction": "below",
            "text": (
                f"Their share of threat down the {threat['channel']} "
                f"below {limit}%."
            ),
        }
    else:
        level = _per_10(facts["summary"][focus]["xt_created"], 45)
        watch["threat"] = {
            "label": f"{names[focus]} threat (xT) per 10 min",
            "target": level,
            "direction": "at_least",
            "text": (
                f"Our threat (xT) per 10 minutes stays at least {level}, "
                "our first-half level."
            ),
        }

    xg = targets["opponent_second_half_xg_below"]
    watch["scoreline"] = {
        "label": f"{names[opp]} xG since the break",
        "target": xg,
        "direction": "below",
        "text": f"Their xG for the second half under {xg}.",
    }
    return watch


def tactics_offline(facts: dict, match: dict, focus: str) -> list[dict]:
    """Rule-based tactics agent: the three findings that decided the half."""
    tp = facts["turning_point"]
    t = tp["minute"]
    b, a = tp["before"], tp["after"]
    names = facts["teams"]
    after_events = [
        e for e in metrics.window(match["events"]) if e["minute"] >= t
    ]
    findings = []

    # 1. Pressing shift.
    presser = max(
        SIDES,
        key=lambda s: (
            a[s]["high_presses_per_min"] - b[s]["high_presses_per_min"]
        ),
    )
    victim = other(presser)
    findings.append(
        {
            "id": "press",
            "concept": "pressure",
            "team": presser,
            "title": f"{names[presser]} switched to a high press around {t}'",
            "evidence": [
                {
                    "label": f"{names[presser]} high presses per min",
                    "before": b[presser]["high_presses_per_min"],
                    "after": a[presser]["high_presses_per_min"],
                },
                {
                    "label": f"{names[victim]} balls lost in own half per min",
                    **_own_half_losses(facts, victim),
                },
                {
                    "label": f"{names[victim]} passes made under pressure",
                    "before": b[victim]["passes_under_pressure"],
                    "after": a[victim]["passes_under_pressure"],
                },
                {
                    "label": f"{names[victim]} pass accuracy under pressure",
                    "before": b[victim]["pass_accuracy_under_pressure"],
                    "after": a[victim]["pass_accuracy_under_pressure"],
                },
                {
                    "label": f"{names[victim]} possession %",
                    "before": b[victim]["possession_pct"],
                    "after": a[victim]["possession_pct"],
                },
                {
                    "label": f"{names[victim]} threat (xT) per 10 min",
                    "before": _per_10(
                        b[victim]["xt_created"], b[victim]["minutes"]
                    ),
                    "after": _per_10(
                        a[victim]["xt_created"], a[victim]["minutes"]
                    ),
                },
            ],
            "minute": t,
        }
    )

    # 2. Where the dominant team's threat comes from since the turning point.
    dominant = max(SIDES, key=lambda s: a[s]["xt_created"] + a[s]["xg"])
    channels = metrics.threat_channels(after_events, dominant)
    channel = max(channels, key=channels.get)
    after_players = metrics.player_stats(after_events, match)
    creators = sorted(
        (p for p in after_players.values() if p["team"] == dominant),
        key=lambda p: -p["xt_created"],
    )[:2]
    findings.append(
        {
            "id": "threat",
            "concept": "rhythm",
            "team": dominant,
            "title": (
                f"{names[dominant]} are getting in down the {channel} "
                f"({channels[channel]:.0f}% of their threat since {t}')"
            ),
            "evidence": [
                {
                    "label": (
                        f"{names[dominant]} xT share by channel since {t}'"
                    ),
                    "value": channels,
                },
                {
                    "label": "Main creators (xT since turning point)",
                    "value": {p["name"]: p["xt_created"] for p in creators},
                },
                {
                    "label": f"{names[dominant]} xT before vs after",
                    "before": b[dominant]["xt_created"],
                    "after": a[dominant]["xt_created"],
                },
            ],
            "channel": channel,
            "creators": [p["name"] for p in creators],
            "minute": t,
        }
    )

    # 3. Scoreline vs chance quality, and the focus team's weak link under
    # pressure.
    s = facts["summary"]
    losers = sorted(
        (p for p in after_players.values() if p["team"] == focus),
        key=lambda p: -p["lost_ball_in_own_half"],
    )
    weak = losers[0] if losers and losers[0]["lost_ball_in_own_half"] else None
    gap = round(s[focus]["goals"] - s[focus]["xg"], 2)
    opp_gap = round(s[other(focus)]["goals"] - s[other(focus)]["xg"], 2)
    verdict = (
        "ahead of their chances"
        if gap >= 0.4
        else "behind their chances"
        if gap <= -0.4
        else "about level with their chances"
    )
    findings.append(
        {
            "id": "scoreline",
            "concept": "chance_quality",
            "team": focus,
            "title": (
                f"{names[focus]} are {verdict} ({s[focus]['goals']} "
                f"goal{'' if s[focus]['goals'] == 1 else 's'} "
                f"from {s[focus]['xg']} xG)"
            ),
            "evidence": [
                {
                    "label": f"{names[focus]}",
                    "value": (
                        f"{s[focus]['goals']} scored from {s[focus]['xg']} xG"
                    ),
                },
                {
                    "label": f"{names[other(focus)]}",
                    "value": (
                        f"{s[other(focus)]['goals']} scored from "
                        f"{s[other(focus)]['xg']} xG"
                    ),
                },
            ]
            + (
                [
                    {
                        "label": (
                            f"{weak['name']} balls lost in own half since {t}'"
                        ),
                        "value": weak["lost_ball_in_own_half"],
                    }
                ]
                if weak
                else []
            ),
            "goals_minus_xg": gap,
            "opp_goals_minus_xg": opp_gap,
            "weak_link": weak["name"] if weak else None,
            "minute": t,
        }
    )
    return findings


def explain_offline(
    findings: list[dict], facts: dict, focus: str
) -> list[dict]:
    """Rule-based explainer agent: why each finding matters."""
    names = facts["teams"]
    t = facts["turning_point"]["minute"]
    chaos = _possession_changes(facts)
    chaos_before, chaos_after = chaos["before"], chaos["after"]
    out = []
    for f in findings:
        if f["id"] == "press":
            p, v = f["team"], other(f["team"])
            lost = _own_half_losses(facts, v)
            tempo = (
                "the game got scrappier"
                if chaos_after > chaos_before + 0.3
                else "the game settled down"
                if chaos_after < chaos_before - 0.3
                else "the overall tempo stayed about the same"
            )
            why = (
                f"{names[p]} started hunting the ball in {names[v]}'s half. "
                f"{names[v]} went from losing it there {lost['before']} to "
                f"{lost['after']} times a minute. "
                f"Possession changed hands {chaos_before} times a minute "
                f"before {t}' and {chaos_after} after, "
                f"so {tempo}, but the losses moved closer to {names[v]}'s "
                "goal. That is why the press "
                f"turns into chances rather than just pressure."
            )
            concept = "Control vs chaos"
        elif f["id"] == "threat":
            why = (
                "Expected threat (xT) measures how much each pass moves the "
                "ball into places goals come from. "
                f"Since {t}', most of {names[f['team']]}'s came down the "
                f"{f['channel']}, mainly through "
                f"{' and '.join(f['creators'])}. A repeated route like that "
                "is something the other side can "
                f"defend against at half-time."
            )
            concept = "Game rhythm"
        else:
            gap = f["goals_minus_xg"]
            how = (
                "more than"
                if gap >= 0.4
                else "fewer than"
                if gap <= -0.4
                else "about what"
            )
            why = (
                f"xG adds up the quality of every shot. {names[focus]} have "
                f"scored {how} their chances "
                f"deserved (goals minus xG: {gap:+.2f}). "
            )
            if gap >= 0.4:
                why += (
                    "That lead rests partly on finishing that rarely lasts "
                    "a whole match. "
                )
            elif gap <= -0.4:
                why += "The chances are there; the finishing has not been. "
            if f.get("weak_link"):
                why += (
                    f"{f['weak_link']} is where the ball has been lost most "
                    f"often since {t}', "
                    f"so that is where the opponent will keep aiming."
                )
            concept = "Chance quality"
        out.append({"id": f["id"], "concept": concept, "why_it_matters": why})
    return out


def coach_offline(
    findings: list[dict], facts: dict, match: dict, focus: str
) -> list[dict]:
    """Rule-based coach agent: three second-half changes."""
    opp = other(focus)
    squad = {p["position"]: p for p in match["teams"][focus]["players"]}
    fastest = max(
        (
            p
            for p in match["teams"][focus]["players"]
            if p["position"] in ("RW", "LW", "ST")
        ),
        key=lambda p: p["top_speed_kmh"],
    )
    by_id = {f["id"]: f for f in findings}
    changes = []

    press = by_id["press"]
    if press["team"] == opp:
        changes.append(
            {
                "finding": "press",
                "action": (
                    f"Beat the press: drop {squad['DM']['name']} between the "
                    "centre-backs to make a back three in build-up, and go "
                    f"longer earlier towards {fastest['name']} "
                    f"(top speed {fastest['top_speed_kmh']} km/h) to turn "
                    "their press into space behind."
                ),
                "tradeoff": (
                    "Going longer gives up some possession, so expect fewer "
                    "spells of control."
                ),
                "alternative": (
                    f"Play through it: {squad['GK']['name']} waits for "
                    f"{squad['CM']['name']} to drop in and we play short "
                    "to draw their press on before releasing the full-backs."
                ),
                "alternative_tradeoff": (
                    "Keeps the ball but one loose pass near our box is a "
                    "big chance for them."
                ),
            }
        )
    else:
        changes.append(
            {
                "finding": "press",
                "action": (
                    "Keep the high press, it is working, but hold "
                    f"{squad['DM']['name']} deeper so one long ball "
                    f"does not get them past our front line."
                ),
                "tradeoff": (
                    "Pressing for another 45 minutes costs legs; the front "
                    "three may need changing before the end."
                ),
                "alternative": (
                    "Drop into a mid-block after the hour and keep the "
                    "front line fresh for counters."
                ),
                "alternative_tradeoff": (
                    "Gives them more of the ball and time to build."
                ),
            }
        )

    threat = by_id["threat"]
    if threat["team"] == opp:
        wide = {"right": "LW", "left": "RW", "centre": "CM"}[threat["channel"]]
        helper = squad[wide]["name"]
        changes.append(
            {
                "finding": "threat",
                "action": (
                    f"Close their {threat['channel']} channel: {helper} "
                    "tracks back and we double up on "
                    f"{threat['creators'][0]}"
                    + (
                        f" and {threat['creators'][1]}"
                        if len(threat["creators"]) > 1
                        else ""
                    )
                    + "."
                ),
                "tradeoff": (
                    f"Pulling {helper} back costs us an outlet on that side "
                    "when we win the ball."
                ),
                "alternative": (
                    f"Stay compact instead: {squad['DM']['name']} sits in "
                    f"front of the back four so the {threat['channel']} "
                    "channel is screened without pulling a winger back."
                ),
                "alternative_tradeoff": (
                    "Leaves the full-backs one-on-one if they switch play."
                ),
            }
        )
    else:
        changes.append(
            {
                "finding": "threat",
                "action": (
                    f"Keep overloading the {threat['channel']}: it is where "
                    "our threat comes from, through "
                    f"{' and '.join(threat['creators'])}. Expect them to "
                    "shift cover there, so have the far side ready."
                ),
                "tradeoff": (
                    "If they double up there, our threat drops until we "
                    "switch sides."
                ),
                "alternative": (
                    "Switch the point of attack early and often so their "
                    "cover never settles on one side."
                ),
                "alternative_tradeoff": (
                    "Longer switches are harder passes and some will be lost."
                ),
            }
        )

    score = by_id["scoreline"]
    s = facts["score"]
    leading = s[focus] > s[opp]
    momentum = [
        w["momentum"] if focus == "home" else -w["momentum"]
        for w in facts["timeline"][-(MOMENTUM_WINDOW_MIN // 5) :]
    ]
    if score.get("weak_link") and score["weak_link"] not in (
        squad["DM"]["name"],
    ):
        action = (
            f"Protect {score['weak_link']}: give them a short option on every "
            "touch so they are never isolated under pressure."
        )
        tradeoff = "Ties a second player to them and thins our midfield."
        alternative = (
            f"Replace {score['weak_link']} at the break if they keep being "
            "targeted."
        )
        alternative_tradeoff = (
            "Uses a substitution early and unsettles the back line."
        )
    else:
        action = (
            "Get one more runner into the box: our best chances came from "
            "close range."
        )
        tradeoff = "One fewer body behind the ball on the counter."
        alternative = (
            "Keep the shape and work the ball to the byline for cut-backs."
        )
        alternative_tradeoff = "Slower, and fewer shots if they sit deep."
    if leading and sum(momentum) < 0:
        action += (
            f" We lead but lost the last {MOMENTUM_WINDOW_MIN} minutes, so "
            "slow the restarts and keep the ball for longer spells."
        )
    changes.append(
        {
            "finding": "scoreline",
            "action": action,
            "tradeoff": tradeoff,
            "alternative": alternative,
            "alternative_tradeoff": alternative_tradeoff,
        }
    )
    watch = watch_targets(facts, findings, focus)
    for c in changes:
        c["watch"] = watch[c["finding"]]["text"]
    return changes


def fan_offline(
    findings: list[dict], facts: dict, focus: str, player: str | None
) -> dict:
    """Rule-based fan agent: an English half-time story, plain words."""
    names = facts["teams"]
    s = facts["score"]
    opp = other(focus)
    t = facts["turning_point"]["minute"]
    goals = [m for m in facts["key_moments"] if m["kind"] == "goal"]
    lead = s[focus] - s[opp]
    mood = "lead" if lead > 0 else "trail" if lead < 0 else "are level with"
    headline = (
        f"{names[focus]} {mood} {names[opp]} "
        if lead
        else f"{names[focus]} level with {names[opp]} "
    ) + f"{s[focus]}-{s[opp]} at the break"
    if lead < 0:
        headline = (
            f"{names[focus]} trail {names[opp]} {s[focus]}-{s[opp]} "
            "at the break"
        )
    goal_lines = [
        f"{m['minute']}' {m['player']} ({names[m['team']]})" for m in goals
    ]
    press = next(f for f in findings if f["id"] == "press")
    story = [
        f"Goals: {', '.join(goal_lines)}."
        if goal_lines
        else "No goals yet, but plenty happening.",
        (
            f"The game changed around the {t}th minute. "
            f"{names[press['team']]} started pressing high and "
            f"{'your team' if press['team'] != focus else 'the other side'} "
            "kept losing the ball near "
            f"{'your' if press['team'] != focus else 'their'} own goal."
        ),
    ]
    threat = next(f for f in findings if f["id"] == "threat")
    story.append(
        "Most of the danger since then has come down the "
        f"{threat['channel']}, through "
        f"{' and '.join(threat['creators'])}."
    )
    spotlight = None
    if player:
        p = next(
            (
                p
                for p in facts["players"].values()
                if p["name"].lower() == player.lower()
            ),
            None,
        )
        if p:
            bits = [
                f"{p['passes']} passes "
                f"({round(100 * (p['pass_accuracy'] or 0))}% accurate)"
            ]
            if p["goals"]:
                bits.append(
                    f"{p['goals']} goal{'s' if p['goals'] > 1 else ''}"
                )
            if p["shots"]:
                bits.append(
                    f"{p['shots']} shot{'s' if p['shots'] > 1 else ''} worth "
                    f"{p['xg']} xG"
                )
            if p["xt_created"] >= 0.1:
                bits.append("one of the most dangerous passers on the pitch")
            if p["defensive_actions"]:
                bits.append(
                    f"{p['defensive_actions']} tackles and interceptions"
                )
            if p["top_sprint_kmh"]:
                bits.append(f"top sprint {p['top_sprint_kmh']} km/h")
            spotlight = {
                "player": p["name"],
                "line": f"{p['name']}: " + ", ".join(bits) + ".",
            }
    watch = (
        f"Watch whether {names[focus]} can play through the press after "
        "the break."
        if press["team"] != focus
        else f"Watch whether {names[focus]} can keep the press going for "
        "45 more minutes."
    )
    return {
        "headline": headline,
        "story": story,
        "spotlight": spotlight,
        "watch_for": watch,
        "language": "en",
    }


def overlays(
    findings: list[dict], facts: dict, focus: str, mode: str
) -> list[dict]:
    """Timed graphics cards for a half-time show segment.

    Card times are seconds from the start of the segment.
    """
    names = facts["teams"]
    s = facts["summary"]
    cards = [
        {
            "at_s": 0,
            "duration_s": 6,
            "type": "scorebug",
            "home": names["home"],
            "away": names["away"],
            "score": f"{facts['score']['home']}-{facts['score']['away']}",
            "label": "Half-time",
        },
        {
            "at_s": 6,
            "duration_s": 8,
            "type": "stat_bars",
            "title": "First half",
            "rows": [
                {
                    "label": "Possession %",
                    "home": s["home"]["possession_pct"],
                    "away": s["away"]["possession_pct"],
                },
                {
                    "label": "xG",
                    "home": s["home"]["xg"],
                    "away": s["away"]["xg"],
                },
                {
                    "label": "Threat (xT)",
                    "home": s["home"]["xt_created"],
                    "away": s["away"]["xt_created"],
                },
                {
                    "label": "Shots",
                    "home": s["home"]["shots"],
                    "away": s["away"]["shots"],
                },
            ],
        },
        {
            "at_s": 14,
            "duration_s": 8,
            "type": "momentum",
            "title": "Who had the upper hand",
            "series": [
                {"from": w["from"], "to": w["to"], "value": w["momentum"]}
                for w in facts["timeline"]
            ],
            "marker": {
                "minute": facts["turning_point"]["minute"],
                "label": "Turning point",
            },
        },
    ]
    at = 22
    for f in findings:
        cards.append(
            {
                "at_s": at,
                "duration_s": 7,
                "type": "lower_third",
                "concept": f["concept"],
                "team": names[f["team"]],
                "title": f["title"]
                if mode == "analyst"
                else f["title"].split(" (")[0],
            }
        )
        at += 7
    return cards


# ---------------------------------------------------------------------------
# Instructions for the model-backed agents
# ---------------------------------------------------------------------------

TACTICS_INSTRUCTIONS = """\
You are the tactics analyst for a football club. You get first-half facts as
JSON, already computed from the event data, including measured evidence for
each finding under "measurements", and tools to look up more. Find exactly
three findings, using these ids: "press" (a change in pressing and what it
did), "threat" (where the dominant side's attacking threat comes from),
"scoreline" (the focus team's goals versus their chance quality, and their
weakest link under pressure). Quote numbers exactly as the facts,
measurements or tools give them; never calculate or invent one. A reply with
any other number is discarded. Return a JSON list; each item needs id,
concept, team ("home" or "away"), title (one sentence), evidence (list of
{label, before, after} or {label, value}), minute, and for "threat" also
channel ("left", "centre" or "right") and creators, for "scoreline" also
goals_minus_xg and weak_link (a player name or null).
"""

EXPLAINER_INSTRUCTIONS = """\
You explain football analysis to people who did not see the numbers. For each
finding, say in two or three plain sentences why it matters to the result,
using one lens: "Control vs chaos", "Game rhythm", "Pressure" or "Chance
quality". Return a JSON list of {id, concept, why_it_matters}. Quote numbers
only as they appear in the findings or "measurements"; a reply with any other
number is discarded.
"""

COACH_INSTRUCTIONS = """\
You are the assistant coach writing the half-time briefing for the focus team.
Turn the findings into exactly three changes for the second half, one per
finding. You advise, the head coach decides, so each change offers two
options with their trade-off rather than one order. Each option names real
players from the squad list and is something a coach can say in the dressing
room. Return a JSON list of {finding, action, tradeoff, alternative,
alternative_tradeoff, watch}, all strings. finding is the id of the finding
the change answers ("press", "threat" or "scoreline"), not its title. action
is the option you recommend and tradeoff its cost; alternative is the other
option and alternative_tradeoff its cost. alternative must be a genuinely
different option from action. watch is copied exactly from "watch" for that
finding, because it is the target the second-half check measures. Quote
numbers only as they appear in the input; never calculate or invent one. A
reply with any other number is discarded.
"""

FAN_INSTRUCTIONS = """\
You are a match-day presenter writing a half-time story for a fan of the focus
team, in the requested language. Be warm and clear, no jargon unless explained.
If a favourite player is given, include a spotlight on them using their real
stats. Return JSON {headline, story (list of 3 short paragraphs), spotlight
({player, line} or null), watch_for, language}. Quote numbers only as they
appear in the input; never calculate or invent one. A reply with any other
number is discarded.
"""


# ---------------------------------------------------------------------------
# The 60' check: did the chosen option do what the coach asked to watch?
# ---------------------------------------------------------------------------

CHECK_MINUTE = 60
OPTIONS = ("a", "b")


def second_half_events(events: list[dict], until: int) -> list[dict]:
    """Second-half events before `until`, dropping first-half stoppage time."""
    return [e for e in events if e["half"] == 2 and e["minute"] < until]


def check_targets(
    facts: dict,
    match: dict,
    findings: list[dict],
    focus: str,
    until: int = CHECK_MINUTE,
) -> list[dict]:
    """Measure each Watch target on the second half so far, in code.

    Targets come from `watch_targets`, the same place the coach's Watch line
    is written from, so the check measures exactly what the analyst was shown.
    """
    ev = second_half_events(match["events"], until)
    minutes = until - 45
    opp = other(focus)
    by_id = {f["id"]: f for f in findings}
    summary = {s: metrics.team_summary(ev, s) for s in SIDES}
    watch = watch_targets(facts, findings, focus)

    side = focus if by_id["press"]["team"] == opp else opp
    threat = by_id["threat"]
    values = {
        "press": _per_min(summary[side]["turnovers_in_own_half"], minutes),
        "threat": (
            metrics.threat_channels(ev, opp)[threat["channel"]]
            if threat["team"] == opp
            else _per_10(summary[focus]["xt_created"], minutes)
        ),
        "scoreline": summary[opp]["xg"],
    }
    checks = []
    for fid in FINDING_IDS:
        w = watch[fid]
        label, target = w["label"], w["target"]
        if fid == "scoreline":
            # The xG target covers the whole half, so pace it to the minutes.
            target = round(target * minutes / 45, 2)
            label = f"{label} (target paced to {until}')"
        value = values[fid]
        checks.append(
            {
                "finding": fid,
                "label": label,
                "value": value,
                "target": target,
                "direction": w["direction"],
                "on_track": (
                    value < target
                    if w["direction"] == "below"
                    else value >= target
                ),
                "minutes": minutes,
            }
        )
    return checks


def check_verdicts(verdicts: Any) -> list[dict]:
    """Reject verifier output that is not one verdict per finding."""
    _require(isinstance(verdicts, list), "verdicts must be a list")
    _require(len(verdicts) == 3, "verdicts must be three items")
    for v in verdicts:
        _require(isinstance(v, dict), "each verdict must be an object")
        _require(
            v.get("finding") in FINDING_IDS,
            f"verdict finding must be one of {FINDING_IDS}",
        )
        _require(
            _is_text(v.get("verdict")) and v.get("next") in ("keep", "change"),
            "verdict needs text and next of keep or change",
        )
    _require(
        {v["finding"] for v in verdicts} == set(FINDING_IDS),
        "verdicts must cover each finding once",
    )
    return verdicts


def verify_offline(
    checks: list[dict], changes: list[dict], choices: dict[str, str]
) -> list[dict]:
    """Rule-based verifier: one verdict per check, read from the numbers."""
    by_id = {c["finding"]: c for c in changes}
    verdicts = []
    for c in checks:
        chosen = choices.get(c["finding"], "a")
        option = by_id[c["finding"]]
        picked = option["action"] if chosen == "a" else option["alternative"]
        other_option = (
            option["alternative"] if chosen == "a" else option["action"]
        )
        goal = "under" if c["direction"] == "below" else "at least"
        if c["on_track"]:
            text = (
                f"On track after {c['minutes']} minutes: {c['label']} is "
                f"{c['value']}, {goal} the {c['target']} target. Keep "
                f"option {chosen.upper()}: {picked}"
            )
            nxt = "keep"
        else:
            text = (
                f"Not there yet after {c['minutes']} minutes: {c['label']} "
                f"is {c['value']} against a target of {goal} "
                f"{c['target']}. Consider option "
                f"{'B' if chosen == 'a' else 'A'}: {other_option}"
            )
            nxt = "change"
        verdicts.append(
            {"finding": c["finding"], "verdict": text, "next": nxt}
        )
    return verdicts


VERIFY_INSTRUCTIONS = """\
You are the analyst checking in with the head coach at the given minute of the
second half. For each finding you get the option the coach chose at half-time,
the measurable target they were told to watch, and the value measured so far
("checks", computed from the events). Say in one or two plain sentences
whether the chosen option is doing its job, and whether to keep it or switch
to the other option. Return a JSON list of {finding, verdict, next}, where
next is "keep" or "change". Quote numbers only as they appear in "checks";
never calculate or invent one. A reply with any other number is discarded.
"""


async def second_half_check(
    match: dict,
    *,
    findings: list[dict],
    changes: list[dict],
    focus: str = "home",
    choices: dict[str, str] | None = None,
    until: int = CHECK_MINUTE,
    client: BaseChatClient | None = None,
) -> dict:
    """Check the half-time calls against the second half so far.

    The numbers come from code; the verifier agent only words the verdict
    and falls back to rules like every other agent.
    """
    choices = {f: (choices or {}).get(f, "a") for f in FINDING_IDS}
    _require(
        all(c in OPTIONS for c in choices.values()),
        "each choice must be a or b",
    )
    trace: list[dict] = []
    started = time.perf_counter()
    facts = metrics.half_time_facts(match)
    checks = check_targets(facts, match, findings, focus, until)
    _step(
        trace,
        "stats",
        "deterministic",
        started,
        f"{len(second_half_events(match['events'], until))} events "
        f"to {until}'",
    )
    by_id = {c["finding"]: c for c in changes}
    chosen = {
        f: by_id[f]["action"] if choices[f] == "a" else by_id[f]["alternative"]
        for f in FINDING_IDS
    }
    verdicts = await _model_or_rules(
        client,
        match,
        trace,
        "verifier",
        VERIFY_INSTRUCTIONS,
        {
            "focus_team": facts["teams"][focus],
            "minute": until,
            "chosen_options": chosen,
            "watch": {
                f: w["text"]
                for f, w in watch_targets(facts, findings, focus).items()
            },
            "checks": checks,
        },
        lambda: verify_offline(checks, changes, choices),
        check_verdicts,
    )
    return {
        "match_id": facts["match_id"],
        "focus": focus,
        "focus_team": facts["teams"][focus],
        "until": until,
        "score": {
            s: facts["score"][s]
            + sum(
                1
                for e in second_half_events(match["events"], until)
                if e["type"] == "goal" and e["team"] == s
            )
            for s in SIDES
        },
        "choices": choices,
        "checks": checks,
        "verdicts": verdicts,
        "trace": trace,
    }


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


def _step(
    trace: list[dict], agent: str, backend: str, started: float, note: str = ""
) -> None:
    """Append one agent step to the briefing trace."""
    trace.append(
        {
            "agent": agent,
            "backend": backend,
            "ms": round(1000 * (time.perf_counter() - started)),
            "note": note,
        }
    )


async def _model_or_rules(
    client: BaseChatClient | None,
    match: dict,
    trace: list[dict],
    agent: str,
    instructions: str,
    payload: dict,
    fallback: Callable[[], Any],
    check: Callable[[Any], Any],
    use_tools: bool = False,
    skip: tuple[str, ...] = (),
) -> Any:
    """Run a model-backed agent, or its rules when there is no client.

    A reply that fails its shape or grounding check also falls back, and the
    trace records why, so the output shape never changes.
    """
    started = time.perf_counter()
    if client is not None:
        try:
            seen: list[str] = []
            tools = build_tools(match, seen) if use_tools else None
            out = await _run_agent(client, agent, instructions, payload, tools)
            check(out)
            allowed = grounded_numbers(payload, *(json.loads(t) for t in seen))
            check_grounded(out, allowed, skip)
            _step(trace, agent, backend_name(client), started)
            return out
        # A broken reply should not break the show.
        except Exception as exc:
            _step(
                trace,
                agent,
                "offline-rules",
                started,
                f"model step failed ({type(exc).__name__}: "
                f"{str(exc)[:120]}), used rules",
            )
            return fallback()
    out = fallback()
    _step(trace, agent, "offline-rules", started)
    return out


async def half_time_briefing(
    match: dict,
    *,
    mode: str = "analyst",
    focus: str = "home",
    player: str | None = None,
    language: str = "en",
    client: BaseChatClient | None = None,
) -> dict:
    """Run all five agents and return the briefing for one audience.

    Model-backed steps fall back to their rule-based versions when no client
    is configured or a reply cannot be parsed, so the output shape never
    changes.
    """
    trace: list[dict] = []

    def step(agent: str, backend: str, started: float, note: str = "") -> None:
        _step(trace, agent, backend, started, note)

    async def model_or_rules(*args: Any, **kwargs: Any) -> Any:
        return await _model_or_rules(client, match, trace, *args, **kwargs)

    started = time.perf_counter()
    facts = metrics.half_time_facts(match)
    step(
        "stats",
        "deterministic",
        started,
        f"{len(metrics.window(match['events']))} first-half events",
    )

    focus_name = facts["teams"][focus]
    slim = {
        k: facts[k]
        for k in (
            "teams",
            "score",
            "summary",
            "turning_point",
            "threat_channels",
            "key_moments",
        )
    }
    slim["focus_team"] = focus
    # Code-computed evidence for each finding, so the model can quote
    # measured rates and shares instead of working them out.
    rules_findings = tactics_offline(facts, match, focus)
    slim["measurements"] = {
        f["id"]: {k: v for k, v in f.items() if k not in ("title", "concept")}
        for f in rules_findings
    }

    findings = await model_or_rules(
        "tactics",
        TACTICS_INSTRUCTIONS,
        slim,
        lambda: rules_findings,
        check_findings,
        use_tools=True,
    )
    # Moments to watch are picked in code for whichever findings came back,
    # so the clip list never depends on the model.
    for f in findings:
        f["moments"] = metrics.moments_for_finding(f, facts["key_moments"])

    explanations = await model_or_rules(
        "explainer",
        EXPLAINER_INSTRUCTIONS,
        {
            "findings": findings,
            "focus_team": focus_name,
            "measurements": {
                "possession_changes_per_min": _possession_changes(facts),
                "own_half_losses_per_min": {
                    side: _own_half_losses(facts, side) for side in SIDES
                },
            },
        },
        lambda: explain_offline(findings, facts, focus),
        check_explanations,
    )

    result: dict[str, Any] = {
        "match_id": facts["match_id"],
        "mode": mode,
        "focus": focus,
        "focus_team": focus_name,
        "teams": facts["teams"],
        "score": facts["score"],
        "summary": facts["summary"],
        "timeline": facts["timeline"],
        "turning_point_minute": facts["turning_point"]["minute"],
        "key_moments": facts["key_moments"],
        "shots": facts["shots"],
        "findings": findings,
        "explanations": explanations,
        "team_report": metrics.team_report(facts, focus),
        "prematch": prematch.compare(match, focus),
        "player_cards": metrics.player_cards(
            metrics.window(match["events"]), match, focus
        ),
    }
    if mode == "analyst":
        squad = [
            {
                "name": p["name"],
                "position": p["position"],
                "top_speed_kmh": p["top_speed_kmh"],
            }
            for p in match["teams"][focus]["players"]
        ]
        watch = {
            f: w["text"]
            for f, w in watch_targets(facts, findings, focus).items()
        }
        changes = await model_or_rules(
            "coach",
            COACH_INSTRUCTIONS,
            {
                "focus_team": focus_name,
                "findings": findings,
                "explanations": explanations,
                "squad": squad,
                "watch": watch,
                "momentum_window_minutes": MOMENTUM_WINDOW_MIN,
            },
            lambda: coach_offline(findings, facts, match, focus),
            check_changes,
        )
        # The 60' check measures the code's target, so the Watch line shown
        # with each call is the code's wording, whatever the model wrote.
        if any(c["watch"] != watch[c["finding"]] for c in changes):
            coach = next(t for t in trace if t["agent"] == "coach")
            coach["note"] = (
                coach["note"] + "; " if coach["note"] else ""
            ) + "watch lines set from code"
        for c in changes:
            c["watch"] = watch[c["finding"]]
        result["changes"] = changes
    else:
        players = {p["name"]: p for p in facts["players"].values()}
        result["fan"] = await model_or_rules(
            "fan",
            FAN_INSTRUCTIONS,
            {
                "focus_team": focus_name,
                "language": language,
                "score": facts["score"],
                "teams": facts["teams"],
                "summary": facts["summary"],
                "findings": findings,
                "favourite_player": players.get(player) if player else None,
                "goals": [
                    m for m in facts["key_moments"] if m["kind"] == "goal"
                ],
            },
            lambda: fan_offline(findings, facts, focus, player),
            check_fan,
        )
        if client is None and language != "en":
            result["fan"]["note"] = (
                "Offline mode writes English only; connect a model for other "
                "languages."
            )

    started = time.perf_counter()
    result["overlays"] = overlays(findings, facts, focus, mode)
    step(
        "overlay", "deterministic", started, f"{len(result['overlays'])} cards"
    )
    result["trace"] = trace
    return result
