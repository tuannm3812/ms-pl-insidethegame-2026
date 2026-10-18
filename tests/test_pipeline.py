import asyncio
import json
import os

import pytest
from agent_framework import BaseChatClient, ChatResponse, Message
from fastapi.testclient import TestClient

from halftime import metrics
from halftime.agents import (
    check_changes,
    check_grounded,
    coach_offline,
    explain_offline,
    fan_offline,
    grounded_numbers,
    half_time_briefing,
    parse_json_reply,
    tactics_offline,
)
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
    assert {
        "pass",
        "shot",
        "tackle",
        "interception",
        "pressure",
        "possession_change",
    } <= types


def test_xg_is_higher_close_to_goal():
    assert (
        shot_xg(99, 34) > shot_xg(94, 34) > shot_xg(80, 34) > shot_xg(80, 10)
    )


def test_xt_grid_increases_towards_goal():
    g = grid()
    assert g[11][3] > g[8][3] > g[4][3]


def test_half_time_facts_add_up(match):
    facts = metrics.half_time_facts(match)
    s = facts["summary"]
    assert (
        abs(s["home"]["possession_pct"] + s["away"]["possession_pct"] - 100)
        < 0.2
    )
    assert sum(1 for m in facts["key_moments"] if m["kind"] == "goal") == sum(
        facts["score"].values()
    )
    assert 15 <= facts["turning_point"]["minute"] <= 35
    assert len(facts["timeline"]) == 9


@pytest.mark.parametrize("focus", ["home", "away"])
def test_analyst_briefing_offline(match, focus):
    out = asyncio.run(half_time_briefing(match, mode="analyst", focus=focus))
    assert [f["id"] for f in out["findings"]] == [
        "press",
        "threat",
        "scoreline",
    ]
    assert len(out["changes"]) == 3
    squad = {p["name"] for p in match["teams"][focus]["players"]}
    assert any(name in out["changes"][0]["action"] for name in squad)
    assert [t["agent"] for t in out["trace"]] == [
        "stats",
        "tactics",
        "explainer",
        "coach",
        "overlay",
    ]


def test_fan_briefing_spotlights_player(match):
    out = asyncio.run(
        half_time_briefing(match, mode="fan", player="Silva", language="es")
    )
    assert out["fan"]["spotlight"]["player"] == "Silva"
    assert "note" in out["fan"]  # offline mode is English only


class ScriptedClient(BaseChatClient):
    """Stands in for Foundry to test the Agent Framework wiring.

    Replies with canned JSON per agent.
    """

    def __init__(self, replies):
        super().__init__()
        self.replies = replies
        self.calls = 0

    async def _inner_get_response(
        self, *, messages, stream, options, **kwargs
    ):
        reply = self.replies[self.calls]
        self.calls += 1
        return ChatResponse(messages=Message("assistant", [reply]))


def test_agent_framework_path_uses_model_replies(match):
    findings = [
        {
            "id": "press",
            "concept": "pressure",
            "team": "away",
            "title": "T1",
            "evidence": [{"label": "L", "value": 1}],
            "minute": 25,
        },
        {
            "id": "threat",
            "concept": "rhythm",
            "team": "away",
            "title": "T2",
            "evidence": [{"label": "L", "value": 1}],
            "minute": 25,
            "channel": "left",
            "creators": ["Duarte"],
        },
        {
            "id": "scoreline",
            "concept": "chance_quality",
            "team": "home",
            "title": "T3",
            "evidence": [{"label": "L", "value": 1}],
            "minute": 25,
            "goals_minus_xg": 0.3,
            "weak_link": "Mensah",
        },
    ]
    explanations = [
        {"id": f["id"], "concept": "Pressure", "why_it_matters": "because"}
        for f in findings
    ]
    changes = [
        {"finding": f["id"], "action": f"do {i}", "watch": "x"}
        for i, f in enumerate(findings)
    ]
    client = ScriptedClient(
        [
            "```json\n" + json.dumps(findings) + "\n```",
            json.dumps(explanations),
            json.dumps(changes),
        ]
    )
    out = asyncio.run(half_time_briefing(match, client=client))
    assert out["changes"][1]["action"] == "do 1"
    assert {t["backend"] for t in out["trace"][1:4]} == {"ScriptedClient"}


def test_broken_model_reply_falls_back_to_rules(match):
    client = ScriptedClient(["not json", "still not json", "nope"])
    out = asyncio.run(half_time_briefing(match, client=client))
    assert len(out["changes"]) == 3
    assert "used rules" in out["trace"][1]["note"]


def test_api(monkeypatch):
    import app as app_module

    # Stay offline even when a developer's .env configures a model.
    monkeypatch.setattr(app_module, "client", None)
    c = TestClient(app_module.app)
    assert c.get("/api/health").json()["ok"]
    r = c.get(
        "/api/briefing",
        params={"mode": "fan", "focus": "away", "player": "Novak"},
    )
    assert (
        r.status_code == 200
        and r.json()["fan"]["spotlight"]["player"] == "Novak"
    )
    assert c.get("/").status_code == 200
    assert len(c.get("/api/events").json()) > 500


def test_key_based_foundry_client_from_env_file(tmp_path, monkeypatch):
    from halftime.agents import azure_resource_endpoint, make_client

    assert (
        azure_resource_endpoint(
            "https://res.services.ai.azure.com/api/projects/p1"
        )
        == "https://res.services.ai.azure.com/"
    )
    for k in (
        "FOUNDRY_PROJECT_ENDPOINT",
        "FOUNDRY_MODEL",
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_DEPLOYMENT",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(k, raising=False)
    (tmp_path / ".env").write_text(
        "AZURE_OPENAI_ENDPOINT=https://res.openai.azure.com/openai/v1/\n"
        "export AZURE_OPENAI_API_KEY='abc'\nAZURE_OPENAI_DEPLOYMENT=my-gpt\n"
    )
    monkeypatch.chdir(tmp_path)
    try:
        client = make_client()
        assert type(client).__name__ == "OpenAIChatClient"
        assert (
            str(client.client.base_url)
            == "https://res.openai.azure.com/openai/v1/"
        )
    finally:
        for k in (
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_API_KEY",
            "AZURE_OPENAI_DEPLOYMENT",
        ):
            os.environ.pop(k, None)


def test_parse_json_reply_ignores_prose_and_fences():
    assert parse_json_reply(
        'Here are the findings:\n[{"a": 1}]\nHope this helps.'
    ) == [{"a": 1}]
    assert parse_json_reply('```json\n{"b": [2, 3]}\n```') == {"b": [2, 3]}
    assert parse_json_reply('Score [1-0] then {"c": true}') == {"c": True}
    assert parse_json_reply(
        'I found [3] key patterns.\n[{"id": "press"}]'
    ) == [{"id": "press"}]
    with pytest.raises(ValueError):
        parse_json_reply("no json here")


def _rules(match, focus="home"):
    facts = metrics.half_time_facts(match)
    findings = tactics_offline(facts, match, focus)
    return (
        findings,
        explain_offline(findings, facts, focus),
        coach_offline(findings, facts, match, focus),
    )


def _backends(out):
    return {t["agent"]: t["backend"] for t in out["trace"]}


def test_rule_replies_pass_the_model_checks(match):
    findings, explanations, changes = _rules(match)
    explanations = [
        {**x, "why_it_matters": "It shifted the half."} for x in explanations
    ]
    client = ScriptedClient(
        [json.dumps(findings), json.dumps(explanations), json.dumps(changes)]
    )
    out = asyncio.run(half_time_briefing(match, client=client))
    assert set(_backends(out).values()) >= {"ScriptedClient"}
    assert _backends(out)["tactics"] == "ScriptedClient"
    assert _backends(out)["coach"] == "ScriptedClient"


def test_wrong_shape_reply_falls_back(match):
    findings, explanations, _ = _rules(match)
    explanations = [
        {**x, "why_it_matters": "It shifted the half."} for x in explanations
    ]
    client = ScriptedClient(
        [json.dumps(findings), json.dumps(explanations), "{}", "{}"]
    )
    out = asyncio.run(half_time_briefing(match, client=client))
    assert isinstance(out["changes"], list) and len(out["changes"]) == 3
    assert _backends(out)["coach"] == "offline-rules"


def test_fallback_survives_reworded_model_evidence(match):
    findings, _, _ = _rules(match)
    for e in findings[0]["evidence"]:
        e["label"] = e["label"].replace(
            "balls lost in own half per min", "own-half losses/min"
        )
    client = ScriptedClient(
        [json.dumps(findings), "not json", "still not json", "nope", "no"]
    )
    out = asyncio.run(half_time_briefing(match, client=client))
    assert _backends(out)["tactics"] == "ScriptedClient"
    assert _backends(out)["explainer"] == "offline-rules"
    assert len(out["explanations"]) == 3


def test_invented_statistic_is_rejected(match):
    findings, _, _ = _rules(match)
    findings[0]["title"] = "Riverside FC had 999 shots"
    client = ScriptedClient([json.dumps(findings)] * 2 + ["no"] * 6)
    out = asyncio.run(half_time_briefing(match, client=client))
    assert _backends(out)["tactics"] == "offline-rules"
    assert "999" not in json.dumps(out["findings"])


def test_grounding_accepts_roundings_and_percentages():
    allowed = grounded_numbers({"pass_accuracy": 0.834, "xg": 1.237})
    check_grounded("83% of passes, 83.4%, xG 1.24 or 1.2", allowed)
    with pytest.raises(ValueError):
        check_grounded("xG 2.7", allowed)


def test_player_losses_add_up_to_team_losses(match):
    events = metrics.window(match["events"])
    players = metrics.player_stats(events, match).values()
    for side in ("home", "away"):
        team = metrics.team_summary(events, side)["turnovers_in_own_half"]
        assert team == sum(
            p["lost_ball_in_own_half"] for p in players if p["team"] == side
        )


def test_high_presses_are_pressures_in_the_opponent_half(match):
    events = metrics.window(match["events"])
    for side in ("home", "away"):
        s = metrics.team_summary(events, side)
        assert 0 < s["high_presses"] < s["pressures"]


def test_reply_without_evidence_or_with_repeated_changes_falls_back(match):
    findings, explanations, changes = _rules(match)
    explanations = [
        {**x, "why_it_matters": "It shifted the half."} for x in explanations
    ]
    no_evidence = [{**f, "evidence": []} for f in findings]
    same_finding = [{**c, "finding": "press"} for c in changes]
    client = ScriptedClient(
        [
            json.dumps(no_evidence),
            json.dumps(explanations),
            json.dumps(same_finding),
        ]
    )
    out = asyncio.run(half_time_briefing(match, client=client))
    assert _backends(out)["tactics"] == "offline-rules"
    assert _backends(out)["explainer"] == "ScriptedClient"
    assert "each finding once" in out["trace"][3]["note"]
    assert {c["finding"] for c in out["changes"]} == {
        "press",
        "threat",
        "scoreline",
    }


@pytest.mark.parametrize("seed", [2, 4, 5, 27])
@pytest.mark.parametrize("focus", ["home", "away"])
@pytest.mark.parametrize("mode", ["analyst", "fan"])
def test_correct_replies_are_accepted(seed, focus, mode):
    """A reply that copies the rule-based output, numbers and all, is valid
    model output, so no step may reject it."""
    m = generate_match(seed)
    facts = metrics.half_time_facts(m)
    findings = tactics_offline(facts, m, focus)
    last = (
        coach_offline(findings, facts, m, focus)
        if mode == "analyst"
        else fan_offline(findings, facts, focus, "Silva")
    )
    replies = [
        findings,
        explain_offline(findings, facts, focus),
        last,
    ]
    client = ScriptedClient([json.dumps(r) for r in replies])
    out = asyncio.run(
        half_time_briefing(
            m, mode=mode, focus=focus, player="Silva", client=client
        )
    )
    rejected = [t for t in out["trace"] if t["backend"] == "offline-rules"]
    assert not rejected


def test_null_evidence_value_is_rejected(match):
    findings, _, _ = _rules(match)
    findings[0]["evidence"] = [{"label": "Pressure", "value": None}]
    client = ScriptedClient([json.dumps(findings)] + ["no"] * 6)
    out = asyncio.run(half_time_briefing(match, client=client))
    assert _backends(out)["tactics"] == "offline-rules"


def test_free_numbers_and_watch_targets_are_checked(match):
    findings, explanations, changes = _rules(match)
    findings[0]["title"] = "Riverside FC had 90 shots"
    changes[0]["watch"] = (
        "We conceded 999 shots; concede fewer after the break."
    )
    client = ScriptedClient(
        [json.dumps(findings), json.dumps(explanations), json.dumps(changes)]
    )
    out = asyncio.run(half_time_briefing(match, client=client))
    assert _backends(out)["tactics"] == "offline-rules"
    assert _backends(out)["coach"] == "offline-rules"
    assert "999" not in json.dumps(out["changes"])


def test_coach_reply_rejection_names_the_bad_field():
    good = [
        {"finding": f, "action": "Press higher.", "watch": "Win it back."}
        for f in ("press", "threat", "scoreline")
    ]
    assert check_changes(good) == good
    titled = [dict(c, finding="Away side presses high") for c in good]
    with pytest.raises(ValueError, match="finding must be one of"):
        check_changes(titled)
    target = [dict(c, watch={"metric": "xg", "below": 1}) for c in good]
    with pytest.raises(ValueError, match="action and watch must be"):
        check_changes(target)
