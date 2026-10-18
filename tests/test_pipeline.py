import asyncio
import json
import os

import pytest
from agent_framework import BaseChatClient, ChatResponse, Message
from fastapi.testclient import TestClient

from halftime import metrics
from halftime.agents import half_time_briefing, parse_json_reply
from halftime.generator import generate_match, shot_xg
from halftime.xt import grid

SEED = 27


@pytest.fixture(scope="module")
def match():
    return generate_match(SEED)


def test_generator_is_deterministic(match):
    again = generate_match(SEED)
    assert again["events"] == match["events"]
    types = {e["type"] for e in match["events"]}
    assert {"pass", "shot", "tackle", "interception", "pressure", "possession_change"} <= types


def test_xg_is_higher_close_to_goal():
    assert shot_xg(99, 34) > shot_xg(94, 34) > shot_xg(80, 34) > shot_xg(80, 10)


def test_xt_grid_increases_towards_goal():
    g = grid()
    assert g[11][3] > g[8][3] > g[4][3]


def test_half_time_facts_add_up(match):
    facts = metrics.half_time_facts(match)
    s = facts["summary"]
    assert abs(s["home"]["possession_pct"] + s["away"]["possession_pct"] - 100) < 0.2
    assert sum(1 for m in facts["key_moments"] if m["kind"] == "goal") == sum(facts["score"].values())
    assert 15 <= facts["turning_point"]["minute"] <= 35
    assert len(facts["timeline"]) == 9


@pytest.mark.parametrize("focus", ["home", "away"])
def test_analyst_briefing_offline(match, focus):
    out = asyncio.run(half_time_briefing(match, mode="analyst", focus=focus))
    assert [f["id"] for f in out["findings"]] == ["press", "threat", "scoreline"]
    assert len(out["changes"]) == 3
    squad = {p["name"] for p in match["teams"][focus]["players"]}
    assert any(name in out["changes"][0]["action"] for name in squad)
    assert [t["agent"] for t in out["trace"]] == ["stats", "tactics", "explainer", "coach", "overlay"]


def test_fan_briefing_spotlights_player(match):
    out = asyncio.run(half_time_briefing(match, mode="fan", player="Silva", language="es"))
    assert out["fan"]["spotlight"]["player"] == "Silva"
    assert "note" in out["fan"]  # offline mode is English only


class ScriptedClient(BaseChatClient):
    """Stands in for Foundry: replies with canned JSON per agent, to test the Agent Framework wiring."""

    def __init__(self, replies):
        super().__init__()
        self.replies = replies
        self.calls = 0

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        reply = self.replies[self.calls]
        self.calls += 1
        return ChatResponse(messages=Message("assistant", [reply]))


def test_agent_framework_path_uses_model_replies(match):
    findings = [{"id": "press", "concept": "pressure", "team": "away", "title": "T1", "evidence": [], "minute": 25},
                {"id": "threat", "concept": "rhythm", "team": "away", "title": "T2", "evidence": [], "minute": 25,
                 "channel": "left", "creators": ["Duarte"]},
                {"id": "scoreline", "concept": "chance_quality", "team": "home", "title": "T3", "evidence": [],
                 "minute": 25, "goals_minus_xg": 0.3, "weak_link": "Mensah"}]
    explanations = [{"id": f["id"], "concept": "Pressure", "why_it_matters": "because"} for f in findings]
    changes = [{"finding": f["id"], "action": f"do {i}", "watch": "x"} for i, f in enumerate(findings)]
    client = ScriptedClient(["```json\n" + json.dumps(findings) + "\n```", json.dumps(explanations),
                             json.dumps(changes)])
    out = asyncio.run(half_time_briefing(match, client=client))
    assert out["changes"][1]["action"] == "do 1"
    assert {t["backend"] for t in out["trace"][1:4]} == {"ScriptedClient"}


def test_broken_model_reply_falls_back_to_rules(match):
    client = ScriptedClient(["not json", "still not json", "nope"])
    out = asyncio.run(half_time_briefing(match, client=client))
    assert len(out["changes"]) == 3
    assert "used rules" in out["trace"][1]["note"]


def test_api():
    from app import app
    c = TestClient(app)
    assert c.get("/api/health").json()["ok"]
    r = c.get("/api/briefing", params={"mode": "fan", "focus": "away", "player": "Novak"})
    assert r.status_code == 200 and r.json()["fan"]["spotlight"]["player"] == "Novak"
    assert c.get("/").status_code == 200
    assert len(c.get("/api/events").json()) > 500


def test_key_based_foundry_client_from_env_file(tmp_path, monkeypatch):
    from halftime.agents import azure_resource_endpoint, make_client

    assert azure_resource_endpoint("https://res.services.ai.azure.com/api/projects/p1") == \
        "https://res.services.ai.azure.com/"
    for k in ("FOUNDRY_PROJECT_ENDPOINT", "FOUNDRY_MODEL", "AZURE_OPENAI_ENDPOINT",
              "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT", "OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / ".env").write_text("AZURE_OPENAI_ENDPOINT=https://res.openai.azure.com/openai/v1/\n"
                                   "export AZURE_OPENAI_API_KEY='abc'\nAZURE_OPENAI_DEPLOYMENT=my-gpt\n")
    monkeypatch.chdir(tmp_path)
    try:
        client = make_client()
        assert type(client).__name__ == "OpenAIChatClient"
        assert str(client.client.base_url) == "https://res.openai.azure.com/openai/v1/"
    finally:
        for k in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT"):
            os.environ.pop(k, None)


def test_parse_json_reply_ignores_prose_and_fences():
    assert parse_json_reply('Here are the findings:\n[{"a": 1}]\nHope this helps.') == [{"a": 1}]
    assert parse_json_reply('```json\n{"b": [2, 3]}\n```') == {"b": [2, 3]}
    assert parse_json_reply('Score [1-0] then {"c": true}') == {"c": True}
    assert parse_json_reply('I found [3] key patterns.\n[{"id": "press"}]') == [{"id": "press"}]
    with pytest.raises(ValueError):
        parse_json_reply("no json here")
