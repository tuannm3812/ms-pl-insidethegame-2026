"""Web app: serves the half-time briefing page and its JSON API.

Run:  uvicorn app:app --reload      then open http://localhost:8000
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse

from halftime.agents import backend_name, half_time_briefing, make_client
from halftime.generator import generate_match

DEFAULT_SEED = 27
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Half-time Briefing")
client = make_client()


@lru_cache(maxsize=32)
def match(seed: int) -> dict:
    return generate_match(seed)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "backend": backend_name(client)}


@app.get("/api/match")
def match_meta(seed: int = DEFAULT_SEED):
    m = match(seed)
    return {"match_id": m["match_id"], "teams": m["teams"], "final_score": m["final_score"]}


@app.get("/api/events")
def events(seed: int = DEFAULT_SEED, half: int = 1, since_t: float = 0.0, limit: int = 5000):
    """Raw event stream, so a client can replay the half as if it were live."""
    evs = [e for e in match(seed)["events"] if e["half"] == half and e["t"] >= since_t]
    return evs[:limit]


@app.get("/api/briefing")
async def briefing(seed: int = DEFAULT_SEED,
                   mode: str = Query("analyst", pattern="^(analyst|fan)$"),
                   focus: str = Query("home", pattern="^(home|away)$"),
                   player: str | None = None,
                   language: str = "en"):
    return await half_time_briefing(match(seed), mode=mode, focus=focus, player=player,
                                    language=language, client=client)
