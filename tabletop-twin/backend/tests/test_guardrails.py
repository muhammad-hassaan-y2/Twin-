"""The guardrails, one rule at a time, and what the world does when that rule is gone.

These six checks sit in front of the policy engine. The person's caps say whether a
payment is *allowed*; these say whether the proposal is a thing this service can read at
all. Each rule here gets the same treatment the seeded failures in `test_regressions.py`
get: an answer with the rule in place, and the bad outcome with only that rule removed.
The last test notices if either half goes missing.

The rules and the harm each one stops:

| rule                   | what arrives without it                        |
|------------------------|------------------------------------------------|
| event_is_real          | a charge against a bill nobody owns, auto-paid |
| amount_is_a_number     | a payment at a figure the model never named    |
| charge_is_positive     | a zero-value charge that settles               |
| amount_matches_event   | a 240 dollar bill paid as 60 dollars           |
| payee_matches_event    | a hold requested for the wrong company         |
| figures_are_given      | a reason quoting a number nobody computed      |
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from twin.api import main
from twin.payments.machine import PaymentState
from twin.safety.guardrails import CHECKS, CLEAR, RULES, Guard, Proposal, parse_cents, review
from twin.store import drop_schema, schema_name
from twin.world.session import Session

PASSWORD = "tabletop-2026"

GUARDED = tuple(sorted(RULES))


@pytest.fixture()
def client(monkeypatch):
    name = schema_name()
    monkeypatch.setenv("TWIN_DB_SCHEMA", name)
    main.reset_state()
    try:
        yield TestClient(main.app)
    finally:
        main.reset_state()
        drop_schema(name)


@pytest.fixture()
def headers(client):
    reply = client.post(
        "/v1/signup", json={"email": "ada@acme.io", "name": "Ada", "password": PASSWORD}
    )
    assert reply.status_code == 200, reply.text
    return {"Authorization": f"Bearer {reply.json()['token']}"}


def review_without(*skipped: str):
    """The same ordered checks with one rule taken out.

    A control that switches off the whole guard proves only that the guard does
    something. This proves which rule was doing it.
    """

    def run(proposal: Proposal, *, event, given: set[str]) -> Guard:
        for name, check in CHECKS:
            if name in skipped:
                continue
            reason = check(proposal, event, given)
            if reason:
                return Guard(False, name, reason)
        return CLEAR

    return run


def propose(**args) -> tuple[Session, dict]:
    session = Session.build(use_model=False)
    return session, session.tool_propose_action(**args)


def propose_without(monkeypatch, rule: str, **args) -> tuple[Session, dict]:
    session = Session.build(use_model=False)
    monkeypatch.setattr("twin.world.session.review", review_without(rule))
    return session, session.tool_propose_action(**args)


def assert_stopped(session: Session, result: dict, rule: str) -> None:
    """Refused, written down, and never handed to the money machine."""
    assert result["verdict"] == "deny" and result["rule"] == rule, result
    assert result["state"] is None and result["idempotency_key"] is None
    assert result["blocked"] == result["reason"]
    assert session.machine.all() == [], "a stopped proposal never becomes a payment record"
    assert session.pending == {}
    assert session.log[-1]["kind"] == "guardrail" and session.log[-1]["rule"] == rule


# ------------------------------------------------------------- the checks themselves

def test_the_rules_are_ordered_and_each_one_is_named():
    assert [name for name, _ in CHECKS] == [
        "event_is_real", "amount_is_a_number", "charge_is_positive",
        "amount_matches_event", "payee_matches_event", "figures_are_given",
    ]


def test_a_proposal_that_lets_the_ledger_decide_clears_every_rule():
    session = Session.build(use_model=False)
    event = session.ledger.by_id("sub-adobe")
    guard = review(
        Proposal(verb="pay_bill", event_id=event.id, stated_amount_cents=None, stated_recipient="",
                 amount_cents=event.amount_cents, recipient=event.counterparty),
        event=event, given=session._given(event.amount_cents, 0, event),
    )
    assert guard == CLEAR


def test_cents_are_read_as_cents_and_nothing_else():
    assert parse_cents(6_100) == 6_100
    assert parse_cents("6,100") == 6_100
    assert parse_cents(6_100.0) == 6_100
    assert parse_cents(6_100.5) is None
    assert parse_cents("twelve dollars") is None
    assert parse_cents(True) is None
    assert parse_cents(None) is None


def test_a_reason_may_quote_the_persons_own_limits():
    """The policy this service loaded is a computed fact, so naming the floor is allowed."""
    session = Session.build(use_model=False)
    floor = session.policy.approval_floor_cents
    guard = review(
        Proposal(verb="pay_bill", event_id=None, stated_amount_cents=4_000, stated_recipient="The Lake",
                 amount_cents=4_000, recipient="The Lake",
                 justification=f"below the {floor} cent approval floor, so nobody has to hold"),
        event=None, given=session._given(4_000, 0, None),
    )
    assert guard == CLEAR


# ------------------------------------------------------------------- 1. event_is_real

BOGUS_BILL = {"verb": "pay_bill", "event_id": "bill-ghosts", "amount_cents": 4_000,
              "recipient": "The Lake"}


def test_event_is_real_known_answer():
    session, result = propose(**BOGUS_BILL)
    assert_stopped(session, result, "event_is_real")
    assert "bill-ghosts" in result["reason"]


def test_event_is_real_without_the_guard(monkeypatch):
    """A charge against a bill that does not exist, below the floor, pays itself."""
    session, result = propose_without(monkeypatch, "event_is_real", **BOGUS_BILL)
    assert result["verdict"] == "allow"
    record = session.machine.all()[0]
    assert (record.amount_cents, record.recipient) == (4_000, "The Lake")
    assert record.state is PaymentState.SUCCEEDED, "an invented bill paid itself, with no hand on it"


# --------------------------------------------------------------- 2. amount_is_a_number

UNREADABLE = {"verb": "pay_bill", "event_id": "sub-adobe", "amount_cents": "twelve dollars"}


def test_amount_is_a_number_known_answer():
    session, result = propose(**UNREADABLE)
    assert_stopped(session, result, "amount_is_a_number")
    assert "twelve dollars" in result["reason"]


def test_amount_is_a_number_without_the_guard(monkeypatch):
    """Unreadable does not mean refused: the event's number moves, and a hand is asked for it."""
    session, result = propose_without(monkeypatch, "amount_is_a_number", **UNREADABLE)
    event = session.ledger.by_id("sub-adobe")
    assert result["verdict"] == "require_approval"
    assert result["amount_cents"] == event.amount_cents, "a figure the model never named"
    assert session.machine.all()[0].amount_cents == event.amount_cents


# -------------------------------------------------------------- 3. charge_is_positive

EMPTY_CHARGE = {"verb": "pay_bill", "amount_cents": 0, "recipient": "The Lake"}


def test_charge_is_positive_known_answer():
    session, result = propose(**EMPTY_CHARGE)
    assert_stopped(session, result, "charge_is_positive")


def test_charge_is_positive_without_the_guard(monkeypatch):
    """Zero is under every cap, so the policy waves it through and it settles."""
    session, result = propose_without(monkeypatch, "charge_is_positive", **EMPTY_CHARGE)
    assert result["verdict"] == "allow"
    assert result["amount_dollars"] == 0
    assert session.machine.all()[0].state is PaymentState.SUCCEEDED


# ------------------------------------------------------------- 4. amount_matches_event

SHORTED_BILL = {"verb": "pay_bill", "event_id": "sub-scan", "amount_cents": 6_000}


def test_amount_matches_event_known_answer():
    session, result = propose(**SHORTED_BILL)
    assert_stopped(session, result, "amount_matches_event")
    assert "24000" in result["reason"] and "not 6000" in result["reason"]


def test_amount_matches_event_without_the_guard(monkeypatch):
    """The bill is 240 dollars; a human is asked to hold a payment of 60."""
    session, result = propose_without(monkeypatch, "amount_matches_event", **SHORTED_BILL)
    assert result["verdict"] == "require_approval"
    assert result["amount_dollars"] == 60.0
    assert result["recipient"] == session.ledger.by_id("sub-scan").counterparty


# ------------------------------------------------------------- 5. payee_matches_event

WRONG_PAYEE = {"verb": "pay_bill", "event_id": "sub-adobe", "recipient": "Guild Mutual"}


def test_payee_matches_event_known_answer():
    session, result = propose(**WRONG_PAYEE)
    assert_stopped(session, result, "payee_matches_event")
    assert "Suite Works" in result["reason"] and "Guild Mutual" in result["reason"]


def test_payee_matches_event_without_the_guard(monkeypatch):
    """Both names are on the allowlist, so only the ledger knows they are not the same bill."""
    session, result = propose_without(monkeypatch, "payee_matches_event", **WRONG_PAYEE)
    assert result["verdict"] == "require_approval"
    assert result["recipient"] == "Guild Mutual"
    assert session.machine.all()[0].recipient == "Guild Mutual"
    assert session.ledger.by_id("sub-adobe").counterparty == "Suite Works"


# --------------------------------------------------------------- 6. figures_are_given

INVENTED_REASON = {"verb": "pay_bill", "event_id": "sub-adobe",
                   "justification": "the club usually bills 4,200 for this"}


def test_figures_are_given_known_answer():
    session, result = propose(**INVENTED_REASON)
    assert_stopped(session, result, "figures_are_given")
    assert "4200" in result["reason"]
    assert session.log[-1]["justification"] == INVENTED_REASON["justification"]


def test_figures_are_given_without_the_guard(monkeypatch):
    """The proposal proceeds and nothing in the trail says the number was made up."""
    session, result = propose_without(monkeypatch, "figures_are_given", **INVENTED_REASON)
    assert result["verdict"] == "require_approval"
    assert [entry["kind"] for entry in session.log] == ["policy"]


def test_a_reason_may_restate_the_amount_that_moves():
    session, result = propose(verb="pay_bill", event_id="sub-adobe",
                              justification=f"Suite Works takes {6_100} cents, or 61 dollars, on the 6th")
    assert result["verdict"] == "require_approval", result["reason"]


# ------------------------------------------------------------------ through the API

def test_the_http_surface_refuses_a_bogus_event_instead_of_crashing(client, headers):
    """Before these checks, a mistyped event id was a 500 on the whole tool call."""
    reply = client.post("/v1/tools", headers=headers, json={"calls": [{
        "name": "propose_action",
        "args": {"verb": "pay_bill", "event_id": "bill-ghosts", "amount_cents": 4_000,
                 "recipient": "The Lake"},
    }]})
    assert reply.status_code == 200, reply.text
    result = reply.json()["results"][0]
    assert (result["verdict"], result["rule"]) == ("deny", "event_is_real")
    assert reply.json()["scene"]["payments"] == []
    kinds = [entry["kind"] for entry in client.get("/v1/audit?limit=50", headers=headers).json()["entries"]]
    assert "guardrail" in kinds and "policy" not in kinds


def test_a_quote_rails_call_names_a_bill_that_is_not_there(client, headers):
    reply = client.post("/v1/tools", headers=headers, json={"calls": [{
        "name": "quote_rails", "args": {"event_id": "bill-ghosts", "amount_cents": 6_000},
    }]}).json()["results"][0]
    assert reply == {"skipped": "'bill-ghosts' is not an event in this ledger"}


# ---------------------------------------------------------------------- the discipline

def test_the_guardrails_run_every_rule_both_ways():
    """A rule that lost its negative control no longer proves it stops anything."""
    names = {name for name in globals() if name.startswith("test_")}
    for rule in GUARDED:
        assert f"test_{rule}_known_answer" in names, rule
        assert f"test_{rule}_without_the_guard" in names, rule
