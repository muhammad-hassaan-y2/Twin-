"""The HTTP edge is where a gesture becomes a decision, so it is where the refusals matter.

Every world belongs to an account, so the fixture signs one up rather than
reaching into a shared singleton.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from twin.api import main

PASSWORD = "tabletop-2026"


@pytest.fixture()
def client(monkeypatch):
    box = Path(tempfile.mkdtemp(prefix="twin-test-"))
    monkeypatch.setenv("TWIN_DB_PATH", str(box / "twin.db"))
    main.reset_state()
    try:
        yield TestClient(main.app)
    finally:
        main.reset_state()
        shutil.rmtree(box, ignore_errors=True)


def sign_up(client, email: str, name: str) -> dict:
    reply = client.post("/v1/signup", json={"email": email, "name": name, "password": PASSWORD})
    assert reply.status_code == 200, reply.text
    return {"Authorization": f"Bearer {reply.json()['token']}"}


@pytest.fixture()
def headers(client):
    return sign_up(client, "ada@acme.io", "Ada")


def test_anonymous_cannot_see_someone_elses_table(client):
    assert client.get("/v1/world").status_code == 401
    assert client.post("/v1/ask", json={"intent": "can I pay this"}).status_code == 401
    assert client.get("/v1/audit").status_code == 401


def test_signup_refuses_a_short_password_and_a_duplicate_email(client):
    assert client.post("/v1/signup", json={"email": "a@acme.io", "password": "short"}).status_code == 422
    sign_up(client, "dup@acme.io", "Dup")
    assert client.post("/v1/signup", json={"email": "dup@acme.io", "password": PASSWORD}).status_code == 409


def test_logout_invalidates_the_token(client):
    bearer = sign_up(client, "out@acme.io", "Out")
    assert client.get("/v1/me", headers=bearer).status_code == 200
    assert client.post("/v1/logout", headers=bearer).json() == {"signed_out": True}
    assert client.get("/v1/me", headers=bearer).status_code == 401


def test_health_says_which_planner_answered(client, monkeypatch):
    monkeypatch.delenv("META_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_COMPAT_BASE_URL", raising=False)
    body = client.get("/v1/health").json()
    assert body["ok"] and body["planner"] in {"rules", "model"}
    assert body["paypal_configured"] is False
    assert body["settlement_rail"] == "sandbox"
    assert body["reconciler"]["running"] is False
    assert "TWIN_RECONCILE_SEC" in body["reconciler"]["reason"]
    assert len(body["heartbeat_steps"]) == 6
    assert body["heartbeat_unwired"] == []
    # Which endpoints exist is reported by name; the keys themselves never leave the env.
    assert body["model_providers"] == []


def test_world_arrives_ready_to_draw(client, headers):
    world = client.get("/v1/world", headers=headers).json()
    assert len(world["river"]["p50_dollars"]) == world["meta"]["horizon_days"]
    assert world["boats"] and world["stones"] and world["palette"]
    assert world["meta"]["runs"] > 0 and world["meta"]["seed"]


def test_two_accounts_never_share_a_world(client, headers):
    client.post("/v1/tools", headers=headers, json={"calls": [{"name": "propose_action", "args": {"verb": "pay_bill", "amount_cents": 12_000, "recipient": "Ashgrove Paper"}}]})
    other = sign_up(client, "grace@acme.io", "Grace")
    entries = client.get("/v1/audit?limit=200", headers=other).json()["entries"]
    assert entries == []
    # Both start from the same fictional seed, but only Ada's table has her decisions.
    assert "bill-rent" in [e["id"] for e in client.get("/v1/ledger", headers=other).json()["events"]]
    assert client.get("/v1/audit?limit=200", headers=headers).json()["entries"]


def test_ask_returns_words_and_the_numbers_behind_them(client, headers):
    answer = client.post("/v1/ask", headers=headers, json={"intent": "what if I cancel the scanning subscription"}).json()
    assert "fork" in answer["calls"]
    assert answer["said"]
    assert answer["scene"]["branches"]


def test_an_empty_intent_is_not_forwarded_to_the_world(client, headers):
    assert client.post("/v1/ask", headers=headers, json={"intent": ""}).status_code == 422


def test_asking_about_a_rail_answers_with_prices(client, headers):
    answer = client.post(
        "/v1/ask", headers=headers, json={"intent": "which rail do I use for the print club box?"}
    ).json()
    assert "quote_rails" in answer["calls"]
    quote = next(result for result in answer["results"] if "quotes" in result)
    assert quote["country"] == "PK"
    assert [row["rail"] for row in quote["quotes"]][-1] == "paypal"
    assert answer["said"]


def test_a_pipe_is_pullable_and_a_bill_is_not(client, headers):
    assert client.post("/v1/pull", headers=headers, json={"event_id": "sub-scan"}).status_code == 200
    assert client.post("/v1/pull", headers=headers, json={"event_id": "bill-rent"}).status_code == 409
    assert client.post("/v1/pull", headers=headers, json={"event_id": "no-such-thing"}).status_code == 404


def test_scrubbing_the_wheel_moves_the_day_and_clamps(client, headers):
    assert client.post("/v1/scrub", headers=headers, json={"day": 44}).json()["day"] == 44
    # The wheel only spans the horizon, so a wild rotation is clamped, not trusted.
    assert client.post("/v1/scrub", headers=headers, json={"day": 179}).json()["day"] == 89
    assert client.post("/v1/scrub", headers=headers, json={"day": -5}).status_code == 422
    assert client.post("/v1/scrub", headers=headers, json={"day": 10_000}).status_code == 422


def test_a_tap_never_approves_money_that_needed_a_held_pinch(client, headers):
    proposal = client.post("/v1/tools", headers=headers, json={"calls": [{"name": "propose_action", "args": {"verb": "pay_bill", "amount_cents": 12_000, "recipient": "Ashgrove Paper"}}]}).json()["results"][0]
    rejected = client.post("/v1/approve", headers=headers, json={"action_id": proposal["action_id"], "gesture": "tap"}).json()
    assert "error" in rejected and rejected["state"] == "proposed"
    approved = client.post("/v1/approve", headers=headers, json={"action_id": proposal["action_id"], "gesture": "pinch_hold_1s"}).json()
    assert approved["state"] == "succeeded"


def test_a_human_rejection_is_counted_once_and_only_when_it_lands(client, headers):
    proposal = client.post("/v1/tools", headers=headers, json={"calls": [{"name": "propose_action", "args": {"verb": "pay_bill", "amount_cents": 12_000, "recipient": "Ashgrove Paper"}}]}).json()["results"][0]
    reply = client.post("/v1/reject", headers=headers, json={"action_id": proposal["action_id"], "reviewer": "Grace", "reason": "not this month"})
    assert reply.json()["state"] == "cancelled"
    rows = [e for e in client.get("/v1/audit?limit=200", headers=headers).json()["entries"] if e["kind"] == "rejection"]
    assert [r["applied"] for r in rows] == [True]
    assert client.get("/v1/summary", headers=headers).json()["human_rejections"] == 1
    # A cancelled record is finished business, so the second no has nothing to act on.
    assert client.post("/v1/reject", headers=headers, json={"action_id": proposal["action_id"], "reviewer": "Grace", "reason": "again"}).status_code == 404
    assert len([e for e in client.get("/v1/audit?limit=200", headers=headers).json()["entries"] if e["kind"] == "rejection"]) == 1


def test_a_policy_denial_leaves_nothing_for_a_human_to_reject(client, headers):
    denied = client.post("/v1/tools", headers=headers, json={"calls": [{"name": "propose_action", "args": {"verb": "pay_bill", "amount_cents": 3_000, "recipient": "Northwind Studio"}}]}).json()["results"][0]
    assert (denied["verdict"], denied["state"]) == ("deny", "cancelled")
    assert client.post("/v1/reject", headers=headers, json={"action_id": denied["action_id"], "reviewer": "Grace", "reason": "too late now"}).status_code == 404


def test_a_blackout_produces_unknown_and_only_reconcile_clears_it(client, headers):
    proposal = client.post("/v1/tools", headers=headers, json={"calls": [{"name": "propose_action", "args": {"verb": "pay_bill", "amount_cents": 9_000, "recipient": "Guild Mutual"}}]}).json()["results"][0]
    client.post("/v1/blackout", headers=headers, json={"action_id": proposal["action_id"]})
    approved = client.post("/v1/approve", headers=headers, json={"action_id": proposal["action_id"], "gesture": "pinch_hold_1s"}).json()
    assert approved["state"] == "unknown"
    # The blind retry is refused until the world has been asked what happened.
    assert client.post("/v1/retry", headers=headers, json={"action_id": proposal["action_id"]}).status_code == 409
    assert client.post("/v1/reconcile", headers=headers, json={"action_id": proposal["action_id"]}).json()["state"] == "succeeded"


def test_a_recipient_ceiling_binds_the_next_proposal(client, headers):
    client.put("/v1/limits/recipient", headers=headers, json={"recipient": "Ashgrove Paper", "cents": 20_000})
    first = client.post("/v1/tools", headers=headers, json={"calls": [{"name": "propose_action", "args": {"verb": "pay_bill", "amount_cents": 15_000, "recipient": "Ashgrove Paper"}}]}).json()["results"][0]
    assert first["rule"] == "approval_floor"  # inside the ceiling, so this is only a normal held-pinch ask
    client.post("/v1/approve", headers=headers, json={"action_id": first["action_id"], "gesture": "pinch_hold_1s"})
    second = client.post("/v1/tools", headers=headers, json={"calls": [{"name": "propose_action", "args": {"verb": "pay_bill", "amount_cents": 15_000, "recipient": "Ashgrove Paper"}}]}).json()["results"][0]
    # The ceiling counts what the recipient has already been paid, not just this bill.
    assert (second["verdict"], second["rule"]) == ("deny", "recipient_ceiling")


def test_the_client_cannot_smuggle_a_tool_past_the_validator(client, headers):
    assert client.post("/v1/tools", headers=headers, json={"calls": [{"name": "raise_limit", "args": {}}]}).status_code == 422
    assert client.post("/v1/tools", headers=headers, json={"calls": [{"name": "forecast", "args": {"seed": 1}}]}).status_code == 422


def test_an_unknown_action_has_nothing_to_approve(client, headers):
    assert client.post("/v1/approve", headers=headers, json={"action_id": "act-none", "gesture": "pinch_hold_1s"}).status_code == 404


def test_live_paypal_refuses_to_be_selected_without_credentials(client, headers, monkeypatch):
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_SECRET", raising=False)
    assert client.put("/v1/rail", headers=headers, json={"rail": "paypal"}).status_code == 503


def test_a_rail_with_no_adapter_here_is_refused_not_simulated(client, headers):
    response = client.put("/v1/rail", headers=headers, json={"rail": "local_transfer"})
    assert response.status_code == 501
    assert "adapter" in response.json()["detail"]


def test_an_unknown_rail_name_is_not_a_rail(client, headers):
    assert client.put("/v1/rail", headers=headers, json={"rail": "carrier_pigeon"}).status_code == 404


def test_an_open_payment_records_which_rail_was_asked_to_carry_it(client, headers):
    client.post("/v1/tools", headers=headers, json={
        "calls": [{"name": "propose_action", "args": {"verb": "pay_bill", "event_id": "sub-scan"}}]})
    record = next(r for r in client.get("/v1/payments", headers=headers).json()["records"]
                  if r["recipient"] == "Highres Club")
    assert record["country"] == "DE"
    assert record["currency"] == "USD" and record["rail"] == "sandbox"
    assert record["fee_cents"] == 0


def test_the_rail_question_is_answered_with_prices_and_a_border(client, headers):
    body = client.get("/v1/rails?country=PK&amount_cents=10000", headers=headers).json()
    assert body["settles_on"] == "sandbox"
    assert body["sender_country"] == "US" and body["sender_currency"] == "USD"
    assert "paypal" not in body["reachable"]
    assert "card_gateway" in body["reachable"]
    excluded = {row["rail"]: row["excluded"] for row in body["quotes"]}
    assert "no PayPal service" in excluded["paypal"]
    assert excluded["card_gateway"] is None


def test_a_rail_list_without_an_amount_prices_nothing(client, headers):
    body = client.get("/v1/rails", headers=headers).json()
    assert body["compiled_on"] and body["note"]
    assert "quotes" not in body and "country" not in body


def test_a_world_can_be_pointed_back_at_the_fake(client, headers, monkeypatch):
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_SECRET", raising=False)
    assert client.put("/v1/rail", headers=headers, json={"rail": "paypal"}).status_code == 503
    response = client.put("/v1/rail", headers=headers, json={"rail": "sandbox"})
    assert response.status_code == 200
    assert response.json()["rail"] == "sandbox"
    assert client.get("/v1/world", headers=headers).json()["meta"]["rail"] == "sandbox"


def test_tick_returns_captions_for_the_accessibility_track(client, headers):
    body = client.post("/v1/tick", headers=headers, json={"days": 30, "final_of_day": True}).json()
    assert body["captions"]
    assert all({"step", "text", "target"} <= set(c) for c in body["captions"])
    assert any("Day 30" in c["text"] for c in body["captions"])


def test_persona_exposes_the_heartbeat_as_addressable_steps(client, headers):
    persona = client.get("/v1/persona", headers=headers).json()
    assert persona["name"]
    assert [s["index"] for s in persona["heartbeat"]] == [1, 2, 3, 4, 5, 6]
    assert all(s["body"] for s in persona["heartbeat"])
    assert any("number" in line.lower() for line in persona["prohibitions"])


def test_a_keyed_connection_writes_one_accounts_ledger(client, headers):
    conn = client.post("/v1/connections", headers=headers, json={"name": "ledger-sync"}).json()
    event = {"id": "inc-client-9", "label": "Client 9 deposit", "kind": "income", "direction": "in", "amount_cents": 180_000, "due_day": 20}
    reply = client.post("/v1/ingest", json={"connection_id": conn["connection_id"], "key": conn["key"], "event": event})
    assert reply.status_code == 200 and reply.json()["added"]
    assert any(e["id"] == "inc-client-9" for e in client.get("/v1/ledger", headers=headers).json()["events"])
    other = sign_up(client, "grace@acme.io", "Grace")
    assert not any(e["id"] == "inc-client-9" for e in client.get("/v1/ledger", headers=other).json()["events"])


def test_a_wrong_connection_key_is_not_a_way_in(client, headers):
    conn = client.post("/v1/connections", headers=headers, json={"name": "ledger-sync"}).json()
    event = {"id": "x", "label": "X", "kind": "bill", "direction": "out", "amount_cents": 1, "due_day": 1}
    assert client.post("/v1/ingest", json={"connection_id": conn["connection_id"], "key": "guess", "event": event}).status_code == 401


def test_an_ingested_event_keeps_the_geography_it_arrived_with(client, headers):
    conn = client.post("/v1/connections", headers=headers, json={"name": "ledger-sync"}).json()
    event = {"id": "bill-hosting", "label": "Berlin hosting", "kind": "bill", "direction": "out",
             "amount_cents": 4_200, "due_day": 12, "counterparty": "Cumulus GmbH", "country": "de"}
    client.post("/v1/ingest", json={"connection_id": conn["connection_id"], "key": conn["key"], "event": event})
    stored = next(e for e in client.get("/v1/ledger", headers=headers).json()["events"] if e["id"] == "bill-hosting")
    assert stored["country"] == "DE"
    stone = next(s for s in client.get("/v1/world", headers=headers).json()["stones"] if s["event_id"] == "bill-hosting")
    assert stone["country"] == "DE"


def test_a_country_code_that_is_not_a_country_is_refused_at_the_edge(client, headers):
    reply = client.post("/v1/ledger/events", headers=headers, json={
        "id": "bill-lost", "label": "Somewhere", "kind": "bill", "direction": "out",
        "amount_cents": 1, "due_day": 1, "country": "deutschland"})
    assert reply.status_code == 422


def test_the_world_comes_back_after_a_restart(client, headers):
    client.post("/v1/tools", headers=headers, json={"calls": [{"name": "propose_action", "args": {"verb": "pay_bill", "amount_cents": 12_000, "recipient": "Ashgrove Paper"}}]})
    client.put("/v1/limits/recipient", headers=headers, json={"recipient": "Ashgrove Paper", "cents": 20_000})
    client.post("/v1/ledger/events", headers=headers, json={"id": "bill-cloud", "label": "Cloud invoice", "kind": "bill", "direction": "out", "amount_cents": 4_200, "due_day": 12, "counterparty": "Cumulus Host"})
    before = client.get("/v1/audit?limit=500", headers=headers).json()["entries"]

    # Same database file, no cached worlds — what a process restart looks like.
    main._cache.clear()

    assert client.get("/v1/audit?limit=500", headers=headers).json()["entries"] == before
    assert client.get("/v1/payments", headers=headers).json()["records"]
    ledger = client.get("/v1/ledger", headers=headers).json()
    assert "bill-cloud" in [e["id"] for e in ledger["events"]]
    assert ledger["policy"]["recipient_ceilings_cents"] == {"Ashgrove Paper": 20_000}
