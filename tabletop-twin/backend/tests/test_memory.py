"""Memory is a window over logged rows, so every claim here is about an edge.

Two failures are worth guarding, and neither one raises an exception: a window that quietly
reaches further than its name, and an unknown window answered with the whole history instead
of a refusal. Both still produce a confident sentence, which is the only thing a person
standing at the table can see. Each test is therefore paired with the run it is standing
against — the same rows, folded the wrong way.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from twin.api import main
from twin.domain.events import Direction
from twin.payments.machine import TERMINAL
from twin.store import drop_schema, schema_name
from twin.world.memory import WINDOWS, digest, summarise, windowed
from twin.world.scene import scene_payload
from twin.world.session import MEMORY_ROWS, Session

PASSWORD = "tabletop-2026"

# Four rows on four days, so a window's edge is the only thing that can change what fits.
ROWS = [{"day": day, "kind": "intent", "intent": f"ask {day}"} for day in (0, 5, 14, 20)]


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
    reply = client.post("/v1/signup", json={"email": "ada@acme.io", "name": "Ada", "password": PASSWORD})
    assert reply.status_code == 200, reply.text
    return {"Authorization": f"Bearer {reply.json()['token']}"}


@pytest.fixture()
def table() -> Session:
    return Session.build(use_model=False)


def fits(window: str, day: int = 20) -> list[int]:
    return [row["day"] for row in windowed(ROWS, day=day, window=window)]


def test_each_window_reaches_back_exactly_as_far_as_it_says():
    assert sorted(WINDOWS) == ["all", "day", "week"]
    assert fits("day") == [20]
    assert fits("week") == [14, 20]
    # The control is the widest window: every row above also appears in it, and only in it.
    assert fits("all") == [0, 5, 14, 20]


def test_a_fold_does_not_care_which_end_of_the_trail_it_was_handed():
    """A session appends oldest first and the store reads newest first. Same week, same figures."""
    for trail in (ROWS, list(reversed(ROWS))):
        folded = summarise(trail, persona="Juno", day=20, open_payments=0, window="week")
        assert folded["entries_considered"] == 2
        assert folded["by_kind"]["intent"] == 2
        assert digest(trail, day=20, open_payments=0)["asks_this_week"] == 2


def test_the_week_edge_is_seven_days_and_not_eight():
    one_row = [{"day": 12, "kind": "intent", "intent": "a while ago"}]
    assert digest(one_row, day=20, open_payments=0)["asks_this_week"] == 0
    assert digest(one_row, day=19, open_payments=0)["asks_this_week"] == 0
    assert digest(one_row, day=18, open_payments=0)["asks_this_week"] == 1


def test_an_unknown_window_is_refused_rather_than_answered_with_everything():
    with pytest.raises(ValueError, match="not a window"):
        windowed(ROWS, day=20, window="fortnight")
    # What a silent fallback would have said: "today", answered with the whole history.
    assert len(windowed(ROWS, day=20, window="all")) == len(ROWS)


def test_the_endpoint_says_no_to_a_window_it_does_not_have(client, headers):
    assert client.post("/v1/ask", headers=headers, json={"intent": "what is coming"}).status_code == 200
    refused = client.get("/v1/summary?window=fortnight", headers=headers)
    assert refused.status_code == 422
    assert all(name in refused.json()["detail"] for name in WINDOWS), "the refusal names what would work"
    today = client.get("/v1/summary?window=day", headers=headers).json()
    history = client.get("/v1/summary?window=all", headers=headers).json()
    assert (today["window"], history["window"]) == ("day", "all")
    assert today["since_day"] == today["day"]
    assert history["entries_considered"] >= today["entries_considered"]
    assert "today" in today["said"] and "so far" in history["said"]


def test_a_row_that_cannot_be_placed_in_time_stays_visible():
    unplaced = [{"kind": "intent", "intent": "written by an older build"}]
    assert len(windowed(unplaced, day=20, window="day")) == 1
    folded = summarise(unplaced, persona="Juno", day=20, open_payments=0, window="day")
    assert folded["entries_considered"] == 1, "a row the reader cannot place is a writer bug, not a gap"


def test_the_trail_keeps_the_newest_rows_and_only_those(table):
    total = MEMORY_ROWS + 40
    for i in range(total):
        table.record("intent", {"intent": f"ask {i}"})
    kept = [entry["intent"] for entry in table.log]
    assert len(kept) == MEMORY_ROWS
    assert kept[-1] == f"ask {total - 1}"
    assert kept[0] == f"ask {total - MEMORY_ROWS}"


def test_the_digest_is_the_same_fold_as_the_summary():
    log = [
        {"day": 20, "kind": "intent", "intent": "what now"},
        {"day": 20, "kind": "policy", "verdict": "deny", "rule": "daily_cap"},
        {"day": 20, "kind": "policy", "verdict": "deny", "rule": "recipient_allowlist"},
        {"day": 20, "kind": "approval", "recipient": "Ashgrove Paper", "amount_cents": 1_200},
        {"day": 13, "kind": "intent", "intent": "last week"},
    ]
    seen = digest(log, day=20, open_payments=2)
    week = summarise(log, persona="", day=20, open_payments=2, window="week")
    assert seen["asks_this_week"] == week["by_kind"].get("intent", 0)
    assert seen["settled_cents_this_week"] == week["total_settled_cents"] == 1_200
    assert seen["refused_this_week"] == 2
    assert seen["top_denied_rule"] == "daily_cap", "the most frequent refusal, not the first seen"
    assert seen["unresolved_payments"] == 2
    assert seen["said"] == week["said"]


def test_the_planner_and_the_table_are_told_the_same_week(table):
    who = next(event.counterparty for event in table.ledger.events
               if event.direction is Direction.OUT and event.counterparty)
    table.tool_propose_action(verb="pay_bill", amount_cents=900, recipient=who)
    shown = table.planner_context()["memory"]
    painted = scene_payload(table)["memory"]
    assert shown == painted, "a panel and a prompt that disagree about the week are two memories"
    assert painted["unresolved_payments"] == sum(
        1 for record in table.machine.all() if record.state not in TERMINAL
    )
    assert painted["moves_this_week"] >= 1
