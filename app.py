"""Web app: serves the half-time briefing page and its JSON API.

Run:  uvicorn app:app --reload      then open http://localhost:8000
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from halftime.agents import (
    CHECK_MINUTE,
    backend_name,
    check_changes,
    check_findings,
    half_time_briefing,
    make_client,
    second_half_check,
)
from halftime.generator import generate_match

DEFAULT_SEED = 27
STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Half-time Briefing")
client = make_client()


@lru_cache(maxsize=32)
def match(seed: int) -> dict:
    """Generate (and cache) the synthetic match for a seed."""
    return generate_match(seed)


@app.get("/")
def index() -> FileResponse:
    """Serve the single-page UI."""
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    """Report liveness and which agent backend is active."""
    return {"ok": True, "backend": backend_name(client)}


@app.get("/api/match")
def match_meta(seed: int = DEFAULT_SEED) -> dict:
    """Teams and final score for a match, without the events."""
    m = match(seed)
    return {
        "match_id": m["match_id"],
        "teams": m["teams"],
        "final_score": m["final_score"],
    }


@app.get("/api/events")
def events(
    seed: int = DEFAULT_SEED,
    half: int = 1,
    since_t: float = 0.0,
    limit: int = 5000,
) -> list[dict]:
    """Raw event stream, so a client can replay the half as if it were live."""
    evs = [
        e
        for e in match(seed)["events"]
        if e["half"] == half and e["t"] >= since_t
    ]
    return evs[:limit]


@app.get("/api/briefing")
async def briefing(
    seed: int = DEFAULT_SEED,
    mode: str = Query("analyst", pattern="^(analyst|fan)$"),
    focus: str = Query("home", pattern="^(home|away)$"),
    player: str | None = None,
    language: str = "en",
) -> dict:
    """Run the agent pipeline and return the half-time briefing."""
    return await half_time_briefing(
        match(seed),
        mode=mode,
        focus=focus,
        player=player,
        language=language,
        client=client,
    )


class Decision(BaseModel):
    """The analyst's record for one call.

    The drafted option, the decision, and whether the change was confirmed
    in place at the restart.
    """

    option: Literal["a", "b"] | None = None
    status: Literal["open", "adopted", "deferred", "rejected"] = "open"
    implemented: bool = False
    target_id: str | None = None


class CheckRequest(BaseModel):
    """The half-time calls to check, plus which option the coach chose.

    `decisions` supersedes `choices` where it names an option; each adopted
    `target_id` must match the target the check measures, or the request is
    rejected with 422.
    """

    seed: int = DEFAULT_SEED
    focus: str = Field("home", pattern="^(home|away)$")
    until: int = Field(CHECK_MINUTE, ge=46, le=90)
    choices: dict[str, str] = Field(default_factory=dict)
    decisions: (
        dict[Literal["press", "threat", "scoreline"], Decision] | None
    ) = None
    findings: list[dict]
    changes: list[dict]


@app.post("/api/check")
async def check(req: CheckRequest) -> dict:
    """Check the chosen options against the second half so far."""
    try:
        findings = check_findings(req.findings)
        changes = check_changes(req.changes)
        return await second_half_check(
            match(req.seed),
            findings=findings,
            changes=changes,
            focus=req.focus,
            choices=req.choices,
            decisions=(
                {f: d.model_dump() for f, d in req.decisions.items()}
                if req.decisions
                else None
            ),
            until=req.until,
            client=client,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
