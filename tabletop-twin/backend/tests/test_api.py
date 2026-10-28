"""The HTTP edge is where a gesture becomes a decision, so it is where the refusals matter."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from twin.api import main


@pytest.fixture()
def client():
    main._state.clear()
    return TestClient(main.app)


def test_health_says_which_planner_answered(client):
    body = client.get("/v1/health").json()
    assert body["ok"] and body["planner"] in {"rules", "model"}
    assert body["paypal_configured"] is False
    assert len(body["heartbeat_steps"]) == 6


def test_world_arrives_ready_to_draw(client):
    world = client.get("/v1/world").json()
    assert len(world["river"]["p50_dollars"]) == world["meta"]["horizon_days"]
    assert world["boats"] and world["stones"] and world["palette"]
    assert world["meta"]["runs"] > 0 and world["meta"]["seed"]


def test_ask_returns_words_and_the_numbers_behind_them(client):
    answer = client.post("/v1/ask", json={"intent": "what if I cancel the scanning subscription"}).json()
    assert "fork" in answer["calls"]
    assert answer["said"]
    assert answer["scene"]["branches"]


def test_an_empty_intent_is_not_forwarded_to_the_world(client):
    assert client.post("/v1/ask", json={"intent": ""}).status_code == 422


def test_a_pipe_is_pullable_and_a_bill_is_not(client):
    assert client.post("/v1/pull", json={"event_id": "sub-scan"}).status_code == 200
    assert client.post("/v1/pull", json={"event_id": "bill-rent"}).status_code == 409
    assert client.post("/v1/pull", json={"event_id": "no-such-thing"}).status_code == 404


def test_scrubbing_the_wheel_moves_the_day_and_clamps(client):
    assert client.post("/v1/scrub", json={"day": 44}).json()["day"] == 44
    # The wheel only spans the horizon, so a wild rotation is clamped, not trusted.
    assert client.post("/v1/scrub", json={"day": 179}).json()["day"] == 89
    assert client.post("/v1/scrub", json={"day": -5}).status_code == 422
    assert client.post("/v1/scrub", json={"day": 10_000}).status_code == 422


def test_a_tap_never_approves_money_that_needed_a_held_pinch(client):
    proposal = client.post("/v1/tools", json={"calls": [{"name": "propose_action", "args": {"verb": "pay_bill", "amount_cents": 12_000, "recipient": "Ashgrove Paper"}}]}).json()["results"][0]
    rejected = client.post("/v1/approve", json={"action_id": proposal["action_id"], "gesture": "tap"}).json()
    assert "error" in rejected and rejected["state"] == "proposed"
    approved = client.post("/v1/approve", json={"action_id": proposal["action_id"], "gesture": "pinch_hold_1s"}).json()
    assert approved["state"] == "succeeded"


def test_a_blackout_produces_unknown_and_only_reconcile_clears_it(client):
    proposal = client.post("/v1/tools", json={"calls": [{"name": "propose_action", "args": {"verb": "pay_bill", "amount_cents": 9_000, "recipient": "Guild Mutual"}}]}).json()["results"][0]
    client.post("/v1/blackout", json={"action_id": proposal["action_id"]})
    approved = client.post("/v1/approve", json={"action_id": proposal["action_id"], "gesture": "pinch_hold_1s"}).json()
    assert approved["state"] == "unknown"
    assert client.post("/v1/reconcile", json={"action_id": proposal["action_id"]}).json()["state"] == "succeeded"


def test_the_client_cannot_smuggle_a_tool_past_the_validator(client):
    assert client.post("/v1/tools", json={"calls": [{"name": "raise_limit", "args": {}}]}).status_code == 422
    assert client.post("/v1/tools", json={"calls": [{"name": "forecast", "args": {"seed": 1}}]}).status_code == 422


def test_an_unknown_action_has_nothing_to_approve(client):
    assert client.post("/v1/approve", json={"action_id": "act-none", "gesture": "pinch_hold_1s"}).status_code == 404


def test_live_paypal_refuses_to_be_selected_without_credentials(client, monkeypatch):
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_SECRET", raising=False)
    assert client.post("/v1/transport").status_code == 503


def test_tick_returns_captions_for_the_accessibility_track(client):
    body = client.post("/v1/tick", json={"days": 30, "final_of_day": True}).json()
    assert body["captions"]
    assert all({"step", "text", "target"} <= set(c) for c in body["captions"])
    assert any("Day 30" in c["text"] for c in body["captions"])


def test_persona_exposes_the_heartbeat_as_addressable_steps(client):
    persona = client.get("/v1/persona").json()
    assert persona["name"]
    assert [s["index"] for s in persona["heartbeat"]] == [1, 2, 3, 4, 5, 6]
    assert any("number" in line.lower() for line in persona["prohibitions"])
