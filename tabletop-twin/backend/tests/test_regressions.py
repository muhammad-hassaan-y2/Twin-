"""Seeded failures with known answers, each one run twice: guarded, and not.

Every other file in this suite asks whether a guard works. This one asks a sharper
question, because an agent that writes its own test can always make a test pass: is
there something to guard? Each row of CORPUS seeds a failure that has happened here
or could plausibly happen, states the answer the world must land on, and then runs the
same seed with that one protection removed and requires the *bad* outcome to appear.
A row whose negative control stops failing has stopped proving anything, and the last
test in this file notices.

The six seeds:

| failure                        | the thing that stops it                  | known answer                    |
|--------------------------------|------------------------------------------|---------------------------------|
| a payment stuck in unknown     | the transition table, and retry's refusal| one charge, recovered by asking   |
| a rail that cannot reach there | a verified coverage map                  | deny, rule rail_unavailable       |
| a stream that invents a figure | numbers checked before any sentence shows| the rule sentence is what is kept |
| a click offered as approval    | the approval floor                       | refused, and written down         |
| a ledger that has not landed   | every request seeds before it reads      | the table arrives populated       |
| a server that dropped its socket| the store notices a closed connection   | one open, then the world is there |
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fake_muse import FakeMuse
from twin.api import main
from twin.data import load_persona_ledger
from twin.payments.machine import (
    IllegalTransition,
    PaymentMachine,
    PaymentState,
    idempotency_key,
)
from twin.payments.paypal import SandboxTransport
from twin.payments.rails import load_catalog
from twin.planner.model import ModelPlanner
from twin.policy.engine import Action, SpendWindow, Verdict, evaluate
from twin.store import Store, drop_schema, schema_name

PASSWORD = "tabletop-2026"
DEVICE = "b3" * 32
FRESH_DEVICE = "5c" * 32

CORPUS = (
    ("stuck_unknown", "a payment whose provider never answered"),
    ("rail_unreachable", "a rail that cannot deliver to the recipient's country"),
    ("invented_figure", "a streamed sentence with a number nobody computed"),
    ("click_as_approval", "a click offered in place of a hold"),
    ("ledger_not_landed", "a request naming an account whose ledger has not landed"),
    ("dropped_connection", "a database socket that the server closed mid-session"),
)


def by_device(key: str) -> dict:
    return {"X-Twin-Device": key}


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


@pytest.fixture()
def muse(monkeypatch):
    """One live gateway on localhost, and exactly one endpoint pointed at it."""
    for name in ("META_MODEL_BASE_URL", "META_MODEL_API_KEY", "META_MODEL_NAME", "MODEL_API_KEY",
                 "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL",
                 "OPENAI_COMPAT_BASE_URL", "OPENAI_COMPAT_API_KEY", "OPENAI_COMPAT_MODEL"):
        monkeypatch.delenv(name, raising=False)
    fake = FakeMuse()
    monkeypatch.setenv("MODEL_API_KEY", "muse-key")
    monkeypatch.setenv("META_MODEL_BASE_URL", fake.start())
    try:
        yield fake
    finally:
        fake.stop()


# The only figures a model may speak in these rows: everything else is invented.
FACTS = [{"forecast": {"pinch_day": 77, "shortfall_day": None, "median_low_dollars": 255.0,
                       "dry_run_percent": 12, "runs": 2000}}]


def blackout_payment() -> tuple[PaymentMachine, SandboxTransport]:
    """A charge that left the machine and got no answer: the record is in unknown."""
    machine = PaymentMachine(approval_floor_cents=5_000)
    record = machine.open("act-1", 12_000, "Ashgrove Paper")
    machine.propose(record)
    transport = SandboxTransport(blackout_keys={record.idempotency_key})
    machine.approve(record, "pinch_hold_1s")
    machine.submit(record, transport)
    assert record.state is PaymentState.UNKNOWN
    return machine, transport


# ------------------------------------------------------------------ 1. stuck unknown

def test_stuck_unknown_known_answer():
    machine, transport = blackout_payment()
    record = machine.all()[0]
    with pytest.raises(IllegalTransition, match="unresolved"):
        machine.retry(record)
    machine.reconcile(record, transport)
    assert record.state is PaymentState.SUCCEEDED
    assert transport.charge_calls == 1, "recovering a charge must not make a second one"
    assert transport.lookup_calls == 1


def test_stuck_unknown_without_the_guard(monkeypatch):
    """Take the transition table away and the retry the machine refused charges twice."""

    def any_transition(self, record, target, note):
        record.state = target
        return record

    monkeypatch.setattr(PaymentMachine, "_move", any_transition)
    machine, transport = blackout_payment()
    record = machine.all()[0]
    record.attempt += 1
    record.idempotency_key = idempotency_key(record.action_id, record.attempt)
    machine._by_key[record.idempotency_key] = record
    machine.submit(record, transport)
    assert transport.charge_calls == 2, "the refusal is the only thing between these two charges"


# --------------------------------------------------------------- 2. unreachable rail

def unreachable_pair() -> tuple[Action, object]:
    """A country the catalog itself says the rail cannot reach, derived not typed."""
    catalog = load_catalog()
    rail = catalog.rails["paypal"]
    gate = next(g for g in ("unavailable", "cannot_receive") if rail.coverage.get(g))
    country = sorted(rail.coverage[gate])[0]
    return Action(id="a", verb="pay_bill", amount_cents=3_000, recipient="Ashgrove Paper",
                  country=country), rail


def test_rail_unreachable_known_answer():
    action, rail = unreachable_pair()
    _, policy, _ = load_persona_ledger()
    decision = evaluate(action, policy, SpendWindow(), 0, rail=rail, sender_country="US")
    assert (decision.verdict, decision.rule) == (Verdict.DENY, "rail_unavailable")
    assert rail.verified


def test_rail_unreachable_without_the_guard():
    """The same country through a rail whose map verifies nothing: no refusal."""
    action, _ = unreachable_pair()
    _, policy, _ = load_persona_ledger()
    unverified = next(rail for rail in load_catalog().rails.values()
                      if not rail.verified and rail.blocks(action.country, "US") is None)
    decision = evaluate(action, policy, SpendWindow(), 0, rail=unverified, sender_country="US")
    assert decision.rule != "rail_unavailable", "a map that verifies nothing denies nothing"


# --------------------------------------------------------------- 3. invented figure

def test_invented_figure_known_answer(muse):
    muse.stream("The floor is 255 dollars.", " You need 9,000 more by Friday.")
    shown: list[str] = []
    planner = ModelPlanner.from_env()
    said = planner.narrate("what now", FACTS, on_delta=shown.append)
    assert shown == ["The floor is 255 dollars."], "the panel never sees the second sentence"
    assert "9,000" not in said and "9000" not in said
    assert planner.last_route.startswith("rules (narration fell back")


def test_invented_figure_without_the_guard(muse, monkeypatch):
    """Release every sentence unchecked and the invented figure reaches the panel."""
    monkeypatch.setattr("twin.planner.model.safe_release", lambda text, given: (text, True))
    muse.stream("The floor is 255 dollars.", " You need 9,000 more by Friday.")
    shown: list[str] = []
    ModelPlanner.from_env().narrate("what now", FACTS, on_delta=shown.append)
    assert "9,000" in "".join(shown), "the control only has teeth if the figure gets spoken"


# ----------------------------------------------------------- 4. a click as approval

def test_click_as_approval_known_answer(client, headers):
    proposal = client.post("/v1/tools", headers=headers, json={"calls": [{
        "name": "propose_action",
        "args": {"verb": "pay_bill", "amount_cents": 12_000, "recipient": "Ashgrove Paper"},
    }]}).json()["results"][0]
    refused = client.post("/v1/approve", headers=headers,
                          json={"action_id": proposal["action_id"], "gesture": "panel_click"}).json()
    assert "error" in refused and refused["state"] == "proposed"
    entries = client.get("/v1/audit?limit=200", headers=headers).json()["entries"]
    kept = [e for e in entries if e["kind"] == "approval_refused"]
    assert [e["gesture"] for e in kept] == ["panel_click"], "the attempt is kept, not swallowed"
    assert client.get("/v1/world", headers=headers).json()["payments"], "still waiting for a hold"


def test_click_as_approval_without_the_guard():
    """Put the floor above the amount and the same click settles it: the floor is the guard."""
    machine = PaymentMachine(approval_floor_cents=20_000)
    record = machine.open("act-2", 12_000, "Ashgrove Paper")
    machine.propose(record)
    machine.approve(record, "panel_click")
    assert record.state is PaymentState.APPROVED


# --------------------------------------------------------- 5. a ledger not yet landed

def test_ledger_not_landed_known_answer(client):
    user_id = main.store().create_anonymous_user(DEVICE)
    assert main.store().world_row(user_id) is None, "the account exists a moment before its ledger"
    assert client.get("/v1/world", headers=by_device(DEVICE)).status_code == 200
    assert main.store().world_row(user_id) is not None


def test_ledger_not_landed_without_the_guard(client, monkeypatch):
    """Remove the seed-before-read and the same request is a dead one, not an error."""
    monkeypatch.setattr(main, "ensure_world", lambda user_id: None)
    main.store().create_anonymous_user(FRESH_DEVICE)
    blunt = TestClient(main.app, raise_server_exceptions=False)
    assert blunt.get("/v1/world", headers=by_device(FRESH_DEVICE)).status_code == 500


# --------------------------------------------------- 6. a socket the server dropped

def visit(client: TestClient) -> int:
    return client.get("/v1/world", headers=by_device(DEVICE)).status_code


def kill_the_socket() -> None:
    """Do to this process the thing a restarting Postgres does to its end of the link."""
    main.store()._conn.close()


def test_dropped_connection_known_answer(client):
    assert visit(client) == 200
    before = main.store()._conn
    kill_the_socket()
    assert visit(client) == 200, "a closed socket is noticed and another one is opened"
    assert main.store()._conn is not before
    body = client.get("/v1/world", headers=by_device(DEVICE)).json()
    assert body["stones"], "the world came back with its table still on it"


def test_dropped_connection_without_the_guard(client, monkeypatch):
    """Skip the reopen and one dropped socket ends the run: every later call is a 500."""

    def without_reopen(self, work):
        with self._lock:
            if self._conn is None:
                self._open()
            return work(self._conn)

    monkeypatch.setattr(Store, "_do", without_reopen)
    blunt = TestClient(main.app, raise_server_exceptions=False)
    assert visit(blunt) == 200
    kill_the_socket()
    assert visit(blunt) == 500
    assert visit(blunt) == 500, "a store that never reopens stays dead for the rest of the run"


# ---------------------------------------------------------------------- the discipline

def test_the_corpus_runs_every_seed_both_ways():
    """A row that lost its negative control is no longer evidence of anything."""
    names = {name for name in globals() if name.startswith("test_")}
    for slug, _ in CORPUS:
        assert f"test_{slug}_known_answer" in names, slug
        assert f"test_{slug}_without_the_guard" in names, slug
