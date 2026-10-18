"""MCP server exposing the match tools, so any MCP client (GitHub Copilot agent
mode, a Foundry agent, Claude, VS Code) can query the same numbers the agents use.

Run:  python -m halftime.mcp_server            (stdio)
"""

from __future__ import annotations

import json
from functools import lru_cache

from mcp.server.fastmcp import FastMCP

from . import metrics
from .agents import half_time_briefing
from .generator import generate_match

mcp = FastMCP("halftime-briefing")


@lru_cache(maxsize=16)
def _match(seed: int) -> dict:
    return generate_match(seed)


@mcp.tool()
def match_info(seed: int = 27) -> str:
    """Teams, squads and final score of a synthetic match."""
    m = _match(seed)
    return json.dumps({"match_id": m["match_id"], "teams": m["teams"], "final_score": m["final_score"]})


@mcp.tool()
def first_half_facts(seed: int = 27) -> str:
    """All first-half stats: team summaries, 5-minute timeline, turning point, key moments."""
    facts = metrics.half_time_facts(_match(seed))
    facts.pop("players")
    return json.dumps(facts)


@mcp.tool()
def team_stats(seed: int = 27, team: str = "home", from_minute: int = 0, to_minute: int = 45) -> str:
    """Possession, xG, xT, PPDA and turnovers for one team ("home"/"away") between two minutes."""
    events = [e for e in metrics.window(_match(seed)["events"])
              if from_minute <= e["minute"] < (99 if to_minute >= 45 else to_minute)]
    return json.dumps(metrics.team_summary(events, team))


@mcp.tool()
def player_stats(seed: int = 27, player: str = "") -> str:
    """First-half stats for a player by surname (empty returns everyone)."""
    m = _match(seed)
    stats = metrics.player_stats(metrics.window(m["events"]), m)
    if player:
        stats = {k: v for k, v in stats.items() if v["name"].lower() == player.lower()}
    return json.dumps(list(stats.values()))


@mcp.tool()
async def briefing(seed: int = 27, mode: str = "analyst", focus: str = "home",
                   player: str = "", language: str = "en") -> str:
    """Run the full half-time agent pipeline (rule-based backend) and return its output."""
    out = await half_time_briefing(_match(seed), mode=mode, focus=focus, player=player or None,
                                   language=language)
    return json.dumps(out)


if __name__ == "__main__":
    mcp.run()
