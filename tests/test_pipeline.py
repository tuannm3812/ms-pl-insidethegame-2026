import asyncio
import json
import os

import pytest
from agent_framework import BaseChatClient, ChatResponse, Message
from fastapi.testclient import TestClient

from halftime import metrics
from halftime.agents import (
    check_changes,
    check_findings,
    check_grounded,
    check_verdicts,
    coach_offline,
    explain_offline,
    fan_offline,
    grounded_numbers,
    half_time_briefing,
    parse_json_reply,
    second_half_check,
    tactics_offline,
    watch_targets,
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
    for c in out["changes"]:
        assert c["action"] != c["alternative"]
        assert c["tradeoff"] and c["alternative_tradeoff"]
    for f in out["findings"]:
        assert len(f["moments"]) <= metrics.MOMENTS_PER_FINDING
        assert f["moments"] == sorted(
            f["moments"], key=lambda m: (m["minute"], m["second"])
        )
    press = out["findings"][0]
    assert all(m["minute"] >= press["minute"] for m in press["moments"])
    assert [t["agent"] for t in out["trace"]] == [
        "stats",
        "tactics",
        "explainer",
        "coach",
        "overlay",
    ]


def test_team_report_rows_match_the_summary(match):
    facts = metrics.half_time_facts(match)
    for focus in metrics.SIDES:
        r = metrics.team_report(facts, focus)
        opp = metrics.other(focus)
        rows = {x["key"]: x for x in r["attack"] + r["defence"]}
        assert rows["xg"]["us"] == facts["summary"][focus]["xg"]
        assert rows["xg_conceded"]["us"] == facts["summary"][opp]["xg"]
        assert rows["ppda"]["better"] == "lower"
        tp = facts["turning_point"]
        mins = tp["before"][focus]["minutes"]
        assert rows["shots"]["us_before"] == round(
            10 * tp["before"][focus]["shots"] / mins, 2
        )
        assert rows["possession_pct"]["split_unit"] == ""


def test_player_cards_cover_the_squad_and_add_up(match):
    ev = metrics.window(match["events"])
    for side in metrics.SIDES:
        cards = metrics.player_cards(ev, match, side)
        squad = match["teams"][side]["players"]
        assert [c["id"] for c in cards] == [p["id"] for p in squad]
        assert sorted(c["xt_rank"] for c in cards) == list(
            range(1, len(squad) + 1)
        )
        for c in cards:
            hm = c["heatmap"]
            assert len(hm["grid"]) == metrics.HEAT_ROWS
            assert all(len(r) == metrics.HEAT_COLS for r in hm["grid"])
            assert sum(map(sum, hm["grid"])) == hm["actions"]
            assert c["name"] in c["insight"]
        gk = cards[0]
        assert gk["position"] == "GK"
        assert gk["heatmap"]["thirds_pct"]["final"] == 0
    received = sum(
        1
        for e in ev
        if e["type"] == "pass"
        and e["outcome"] == "complete"
        and e["receiver"] == "Silva"
        and e["team"] == "home"
    )
    silva = next(
        c
        for c in metrics.player_cards(ev, match, "home")
        if c["name"] == "Silva"
    )
    own = sum(
        1
        for e in ev
        if e.get("player") == "Silva"
        and e["team"] == "home"
        and e["type"] in metrics.ACTION_TYPES
    )
    assert silva["heatmap"]["actions"] == own + received


def test_prematch_flags_the_away_press(match):
    from halftime import prematch

    out = prematch.compare(match, "home")
    rows = {(r["side"], r["key"]): r for r in out["rows"]}
    press = rows[("away", "high_presses")]
    # Seed 27's storyline: the away side was not expected to press high.
    assert press["verdict"] == "above" and press["actual"] > press["high"]
    assert press["good_for_focus"] is False
    assert out["changes"][0]["key"] == "high_presses"
    assert sum(out["prematch_win_pct"].values()) == pytest.approx(100)
    for r in out["rows"]:
        assert r["low"] <= r["expected"] <= r["high"]
        inside = r["low"] <= r["actual"] <= r["high"]
        assert (r["verdict"] == "as_expected") is inside
    other_fixture = dict(match, teams={**match["teams"]})
    other_fixture["teams"]["home"] = {
        **match["teams"]["home"],
        "name": "Elsewhere FC",
    }
    assert prematch.compare(other_fixture, "home") is None


def test_press_resistance_counts_pressured_passes(match):
    ev = metrics.window(match["events"])
    for side in metrics.SIDES:
        s = metrics.team_summary(ev, side)
        pressured = [
            e
            for e in ev
            if e["type"] == "pass"
            and e["team"] == side
            and e.get("under_pressure")
        ]
        assert s["passes_under_pressure"] == len(pressured)
        assert 0 <= s["pass_accuracy_under_pressure"] <= 1
    assert metrics.press_resistance([]) == {
        "passes_under_pressure": 0,
        "pass_accuracy_under_pressure": None,
    }


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
        {
            "finding": f["id"],
            "action": f"do {i}",
            "tradeoff": "costs",
            "alternative": f"or {i}",
            "alternative_tradeoff": "costs more",
            "watch": "x",
        }
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


@pytest.mark.parametrize("focus", ["home", "away"])
def test_second_half_check_offline(match, focus):
    briefing = asyncio.run(half_time_briefing(match, focus=focus))
    out = asyncio.run(
        second_half_check(
            match,
            findings=briefing["findings"],
            changes=briefing["changes"],
            focus=focus,
            choices={"threat": "b"},
        )
    )
    assert [c["finding"] for c in out["checks"]] == [
        "press",
        "threat",
        "scoreline",
    ]
    for c in out["checks"]:
        assert c["minutes"] == 15 and c["window"] == "46'-60'"
        assert c["status"] in metrics.EVIDENCE_STATUSES
        assert c["on_track"] is (c["status"] == "met")
        assert c["target_id"] == f"{c['finding']}.{focus}.v1"
    assert out["choices"] == {"press": "a", "threat": "b", "scoreline": "a"}
    by_id = {v["finding"]: v for v in out["verdicts"]}
    changes = {c["finding"]: c for c in briefing["changes"]}
    for c in out["checks"]:
        v = by_id[c["finding"]]
        assert v["next"] == ("keep" if c["status"] == "met" else "review")
        assert str(c["n"]) in v["verdict"]
        # The verifier never points the coach at the other option.
        other = changes[c["finding"]][
            "action" if c["finding"] == "threat" else "alternative"
        ]
        assert other not in v["verdict"]
        assert "switch" not in v["verdict"].lower()
        assert "consider option" not in v["verdict"].lower()
    assert [t["agent"] for t in out["trace"]] == ["stats", "verifier"]
    with pytest.raises(ValueError, match="a or b"):
        asyncio.run(
            second_half_check(
                match,
                findings=briefing["findings"],
                changes=briefing["changes"],
                choices={"press": "c"},
            )
        )


def test_verifier_model_reply_is_checked_and_grounded(match):
    briefing = asyncio.run(half_time_briefing(match))
    good = [
        {
            "finding": f,
            "verdict": "Look again with the staff.",
            "next": "review",
        }
        for f in ("press", "threat", "scoreline")
    ]
    assert check_verdicts(good) == good
    with pytest.raises(ValueError, match="keep or review"):
        check_verdicts([dict(v, next="change") for v in good])
    # "keep" is only allowed for a target that is met.
    missed = [
        {"finding": f, "status": "not_met"}
        for f in ("press", "threat", "scoreline")
    ]
    with pytest.raises(ValueError, match="keep only when"):
        check_verdicts([dict(v, next="keep") for v in good], missed)
    invented = [dict(v, verdict="We lost it 77 times.") for v in good]
    client = ScriptedClient([json.dumps(invented)])
    out = asyncio.run(
        second_half_check(
            match,
            findings=briefing["findings"],
            changes=briefing["changes"],
            client=client,
        )
    )
    assert out["trace"][1]["backend"] == "offline-rules"
    assert "77" not in json.dumps(out["verdicts"])
    client = ScriptedClient([json.dumps(good)])
    out = asyncio.run(
        second_half_check(
            match,
            findings=briefing["findings"],
            changes=briefing["changes"],
            client=client,
        )
    )
    assert out["trace"][1]["backend"] == "ScriptedClient"
    assert out["verdicts"] == good


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
    b = c.get("/api/briefing", params={"focus": "home"}).json()
    r = c.post(
        "/api/check",
        json={
            "focus": "home",
            "choices": {"press": "b"},
            "findings": b["findings"],
            "changes": b["changes"],
        },
    )
    assert r.status_code == 200 and r.json()["until"] == 60
    assert r.json()["choices"]["press"] == "b"
    bad = c.post(
        "/api/check",
        json={"findings": b["findings"], "changes": b["changes"][:2]},
    )
    assert bad.status_code == 422 and "three" in bad.json()["detail"]


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
        {
            "finding": f,
            "action": "Press higher.",
            "tradeoff": "Tired legs.",
            "alternative": "Sit deeper.",
            "alternative_tradeoff": "Less of the ball.",
            "watch": "Win it back.",
        }
        for f in ("press", "threat", "scoreline")
    ]
    assert check_changes(good) == good
    one_order = [
        {k: v for k, v in c.items() if k != "alternative"} for c in good
    ]
    with pytest.raises(ValueError, match="alternative"):
        check_changes(one_order)
    titled = [dict(c, finding="Away side presses high") for c in good]
    with pytest.raises(ValueError, match="finding must be one of"):
        check_changes(titled)
    target = [dict(c, watch={"metric": "xg", "below": 1}) for c in good]
    with pytest.raises(ValueError, match="watch must be"):
        check_changes(target)


def test_model_watch_is_replaced_by_the_checked_target(match):
    findings, explanations, changes = _rules(match)
    canonical = [c["watch"] for c in changes]
    # A grounded but different target: the after-press rate, not the before.
    lost = findings[0]["evidence"][1]["after"]
    changes[0]["watch"] = f"Own-half losses below {lost} per minute."
    client = ScriptedClient(
        [json.dumps(findings), json.dumps(explanations), json.dumps(changes)]
    )
    out = asyncio.run(half_time_briefing(match, client=client))
    coach = next(t for t in out["trace"] if t["agent"] == "coach")
    assert coach["backend"] == "ScriptedClient"
    assert "watch lines set from code" in coach["note"]
    assert [c["watch"] for c in out["changes"]] == canonical
    check = asyncio.run(
        second_half_check(
            match, findings=out["findings"], changes=out["changes"]
        )
    )
    for c, change in zip(check["checks"], out["changes"], strict=True):
        if c["finding"] != "scoreline":
            assert str(c["target"]) in change["watch"]


@pytest.mark.parametrize("focus", ["home", "away"])
def test_watch_targets_match_coach_and_check(match, focus):
    facts = metrics.half_time_facts(match)
    findings = tactics_offline(facts, match, focus)
    watch = watch_targets(facts, findings, focus)
    changes = coach_offline(findings, facts, match, focus)
    assert {c["finding"]: c["watch"] for c in changes} == {
        f: w["text"] for f, w in watch.items()
    }
    check = asyncio.run(
        second_half_check(
            match, findings=findings, changes=changes, focus=focus
        )
    )
    for c in check["checks"]:
        assert c["direction"] == watch[c["finding"]]["direction"]
        assert (
            str(watch[c["finding"]]["target"]) in watch[c["finding"]]["text"]
        )
        if c["finding"] != "scoreline":
            assert c["target"] == watch[c["finding"]]["target"]


@pytest.mark.parametrize(
    "bad_id", [None, ["press"], {"id": "press"}, 7, "missing"]
)
def test_malformed_finding_ids_are_rejected(match, bad_id, monkeypatch):
    import app as app_module

    findings, _, changes = _rules(match)
    if bad_id == "missing":
        del findings[0]["id"]
    else:
        findings[0]["id"] = bad_id
    with pytest.raises(ValueError, match="ids"):
        check_findings(findings)
    monkeypatch.setattr(app_module, "client", None)
    r = TestClient(app_module.app).post(
        "/api/check", json={"findings": findings, "changes": changes}
    )
    assert r.status_code == 422


def test_identical_options_are_rejected(match):
    findings, explanations, changes = _rules(match)
    copies = [
        dict(c, alternative=c["action"] + " ", alternative_tradeoff="Same.")
        for c in changes
    ]
    with pytest.raises(ValueError, match="repeats the recommended"):
        check_changes(copies)
    client = ScriptedClient(
        [json.dumps(findings), json.dumps(explanations), json.dumps(copies)]
    )
    out = asyncio.run(half_time_briefing(match, client=client))
    assert _backends(out)["coach"] == "offline-rules"
    assert all(c["alternative"] != c["action"] for c in out["changes"])


def test_unmeasured_window_is_accepted_as_null(match):
    findings, explanations, changes = _rules(match)
    accuracy = findings[0]["evidence"][3]
    assert "accuracy under pressure" in accuracy["label"]
    accuracy["before"] = None
    assert check_findings(findings) == findings
    client = ScriptedClient(
        [json.dumps(findings), json.dumps(explanations), json.dumps(changes)]
    )
    out = asyncio.run(half_time_briefing(match, client=client))
    assert _backends(out)["tactics"] == "ScriptedClient"
    accuracy["after"] = None
    with pytest.raises(ValueError, match="evidence"):
        check_findings(findings)


@pytest.mark.parametrize("seed", [2, 5, 27, 41])
def test_clips_belong_to_their_finding(seed):
    m = generate_match(seed)
    for focus in ("home", "away"):
        facts = metrics.half_time_facts(m)
        for f in tactics_offline(facts, m, focus):
            moments = metrics.moments_for_finding(f, facts["key_moments"])
            assert len(moments) <= metrics.MOMENTS_PER_FINDING
            for c in moments:
                if f["id"] in ("press", "threat"):
                    assert c["minute"] >= f["minute"]
                if f["id"] == "threat":
                    assert c["team"] == f["team"]
                if f["id"] == "scoreline":
                    assert c["kind"] in ("goal", "big_chance_missed")


def test_evidence_status_boundaries():
    floor = metrics.MIN_RATE_EVENTS
    status = metrics.evidence_status
    assert status(1.0, 2.0, "below", floor - 1, floor) == "insufficient"
    assert status(None, 2.0, "below", 50, floor) == "insufficient"
    assert status(1.0, 2.0, "below", floor, floor) == "met"
    assert status(2.0, 2.0, "below", floor, floor) == "not_met"
    assert status(2.0, 2.0, "at_least", floor, floor) == "met"
    # Within one standard error of the target is too close to call.
    assert status(1.9, 2.0, "below", floor, floor, se=0.2) == "too_close"
    assert status(1.7, 2.0, "below", floor, floor, se=0.2) == "met"
    assert status(2.3, 2.0, "below", floor, floor, se=0.2) == "not_met"
    assert metrics.rate_se(20, 15) == pytest.approx(20**0.5 / 15)


def test_threat_channels_without_threat_is_none(match):
    assert metrics.threat_channels([], "home") == {
        "left": None,
        "centre": None,
        "right": None,
    }
    assert metrics.threat_passes([], "home") == 0
    # No evidence can never pass a "share below 40%" target.
    assert (
        metrics.evidence_status(None, 40, "below", 0, metrics.MIN_SHARE_PASSES)
        == "insufficient"
    )
    findings, _, _ = _rules(match)
    findings[1]["evidence"][0]["value"] = {
        "left": None,
        "centre": None,
        "right": None,
    }
    assert check_findings(findings) == findings


def _check(match, focus, **kwargs):
    briefing = asyncio.run(half_time_briefing(match, focus=focus))
    out = asyncio.run(
        second_half_check(
            match,
            findings=briefing["findings"],
            changes=briefing["changes"],
            focus=focus,
            **kwargs,
        )
    )
    return briefing, {c["finding"]: c for c in out["checks"]}, out


def test_seed_27_check_statuses(match):
    _, home, _ = _check(match, "home")
    # 20 own-half losses in 15 minutes: 1.33 against under 0.84, clear miss.
    assert (home["press"]["n"], home["press"]["value"]) == (20, 1.33)
    assert home["press"]["status"] == "not_met"
    assert home["press"]["baseline"] == 1.48
    # Two Northgate shots cannot judge an xG target either way.
    assert home["scoreline"]["n"] == 2
    assert home["scoreline"]["status"] == "insufficient"
    assert home["threat"]["policy"] == "proposed limit, not validated"
    # Calls against the focus team carry a cost check, not a verdict.
    guard = home["press"]["guardrail"]
    assert guard and "status" not in guard and guard["enough"]
    assert home["scoreline"]["guardrail"] is None
    _, away, _ = _check(match, "away")
    # The same 1.33 against "at least 1.48" sits inside one standard error.
    assert away["press"]["value"] == 1.33 and away["press"]["target"] == 1.48
    assert away["press"]["status"] == "too_close"


def test_briefing_changes_carry_target_and_rules_text(match):
    out = asyncio.run(half_time_briefing(match, focus="away"))
    for c in out["changes"]:
        assert c["target"]["id"] == f"{c['finding']}.away.v1"
        assert c["target"]["text"] == c["watch"]
        assert c["rules"]["source"] == "rules"
        assert set(c["rules"]["best_when"]) == {"a", "b"}
        assert c["rules"]["alternative"] and c["rules"]["tell_apart"]


def test_check_decisions(monkeypatch):
    import app as app_module

    monkeypatch.setattr(app_module, "client", None)
    c = TestClient(app_module.app)
    b = c.get("/api/briefing", params={"focus": "home"}).json()
    body = {
        "focus": "home",
        "findings": b["findings"],
        "changes": b["changes"],
    }
    decisions = {
        "press": {
            "option": "b",
            "status": "adopted",
            "implemented": True,
            "target_id": "press.home.v1",
        },
        "threat": {"option": None, "status": "deferred"},
    }
    r = c.post("/api/check", json=body | {"decisions": decisions})
    assert r.status_code == 200
    out = r.json()
    assert out["choices"] == {"press": "b", "threat": "a", "scoreline": "a"}
    assert out["decisions"]["press"]["implemented"] is True
    assert out["decisions"]["threat"]["target_id"] == "threat.home.v1"
    # A target adopted for another focus is not the one this check measures.
    stale = {"press": dict(decisions["press"], target_id="press.away.v1")}
    r = c.post("/api/check", json=body | {"decisions": stale})
    assert r.status_code == 422 and "reload" in r.json()["detail"]
    unadopted = {"press": {"option": "a", "implemented": True}}
    r = c.post("/api/check", json=body | {"decisions": unadopted})
    assert r.status_code == 422
    r = c.post(
        "/api/check", json=body | {"decisions": {"press": {"status": "done"}}}
    )
    assert r.status_code == 422
