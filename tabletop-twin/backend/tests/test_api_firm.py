"""The audit firm is only real once a table can ask it a question.

Three things are checked here that no other file can: that the HTTP paths answer with no chain
running and say plainly that that is why, that an engagement's figures come from the corpus
rather than from whatever a client posted, and that the agreements a review opens are exactly the
findings that bound somebody - both when there is no contract to write to and when there is.

The chain these tests use is a sidecar of their own, journalled in a temp directory, so no
agreement ever lands on the history a developer was reading yesterday.
"""

from __future__ import annotations

import dataclasses
import json
import os
import socket
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

from twin.api import main
from twin.api.main import EngagementIn
from twin.audit.agents import ROLES, Case, Priors
from twin.audit.chain import spawn_sidecar
from twin.audit.finetune import sweep
from twin.store import drop_schema, schema_name

PASSWORD = "tabletop-2026"
DEVICE = "a3" * 32
OTHER_DEVICE = "b9" * 32


def by_device(key: str) -> dict:
    return {"X-Twin-Device": key}


@pytest.fixture()
def client(monkeypatch):
    """A booted app with no chain named: the state this machine is in until somebody says otherwise."""
    name = schema_name()
    monkeypatch.setenv("TWIN_DB_SCHEMA", name)
    monkeypatch.delenv("TWIN_CHAIN_URL", raising=False)
    main.reset_state()
    try:
        yield TestClient(main.app)
    finally:
        main.reset_state()
        drop_schema(name)


@pytest.fixture(scope="module")
def sidecar():
    box = tempfile.mkdtemp(prefix="twin-firm-api-")
    with spawn_sidecar(journal=os.path.join(box, "firm-api.journal.jsonl"),
                       wait_sec=120.0) as chain:
        yield chain


@pytest.fixture()
def live(sidecar, monkeypatch):
    """The same app, booted for real with a chain it was told about before startup."""
    name = schema_name()
    monkeypatch.setenv("TWIN_DB_SCHEMA", name)
    monkeypatch.setenv("TWIN_CHAIN_URL", sidecar.url)
    main.reset_state()
    try:
        with TestClient(main.app) as running:
            yield running
    finally:
        main.reset_state()
        drop_schema(name)


@pytest.fixture()
def headers(client):
    return signup(client)


@pytest.fixture()
def live_headers(live):
    """A token for the app that has a chain.

    This is not the fixture above with a new name. `headers` depends on `client`, and `client`
    deliberately clears `TWIN_CHAIN_URL` and resets the service - so a test that asked for both
    would be handed a booted-with-a-chain app whose firm had just been told there is no chain.
    """
    return signup(live)


def signup(app: TestClient) -> dict:
    reply = app.post("/v1/signup", json={"email": "ada@acme.io", "name": "Ada",
                                         "password": PASSWORD})
    assert reply.status_code == 200, reply.text
    return {"Authorization": f"Bearer {reply.json()['token']}"}


# ------------------------------------------------------------------ with no chain

def test_a_brief_names_the_firm_and_says_why_it_has_no_chain(client):
    brief = client.get("/v1/firm").json()
    assert len(brief["roles"]) == len(ROLES), (
        "the roster is the firm; a panel that cannot see it sees nothing")
    assert len({role["role"] for role in brief["roles"]}) == len(ROLES)
    assert all(role["title"] and role["principal"] for role in brief["roles"])
    calibrated = [card for card in brief["thresholds"] if card["state"] == "calibrated"]
    assert calibrated, "the firm is calibrated on the corpus or it is not the firm in this repo"
    for card in calibrated:
        assert card["celex"] and card["article"], card
    names = {card["name"] for card in brief["thresholds"]}
    assert "non_audit_fee_cap_percent" in names
    assert "materiality_percent_of_turnover" in brief["uncalibrated"]
    assert brief["chain"]["on_chain"] is False
    assert "TWIN_CHAIN_URL" in brief["chain"]["why"]
    assert brief["engagements"] == len(sweep(Priors.load()))
    # This reply is served to a browser. Somebody's home directory is not a provenance fact.
    assert brief["provenance"]["corpus_dir"] == "backend/.corpus"
    assert "Users" not in json.dumps(brief["provenance"])


def test_the_brief_says_which_route_the_words_came_from(client):
    """No key is installed in this suite, so the honest answer is the rules - and it says so."""
    route = client.get("/v1/firm").json()["model_route"]
    assert route["route"] == "rules", route


def test_health_reports_the_boot_probe_without_reaching_the_network(client):
    audit = client.get("/v1/health").json()["audit"]
    assert audit["on_chain"] is False
    assert "TWIN_CHAIN_URL" in audit["why"], audit
    assert audit["hired"] == 0 and audit["refused"] == 0


def test_a_review_without_a_chain_still_answers_and_says_what_it_withdrew(client, headers):
    before = client.get("/v1/audit", headers=headers).json()["entries"]
    reply = client.post("/v1/firm/review", json={"engagement": 0}, headers=headers)
    assert reply.status_code == 200, reply.text
    summary = reply.json()
    assert len(summary["findings"]) == len(ROLES)
    assert summary["agreements"] == []
    assert summary["waiting_on_humans"] == []
    assert summary["chain"]["on_chain"] is False
    # An empty list is not a refusal. The reply has to carry the reason or a panel reads
    # "nothing was opened" as "nothing was binding", and those are different claims.
    assert "no contract" in summary["why_no_agreements"], summary["why_no_agreements"]
    assert all(f["route"].startswith("rules") for f in summary["findings"])
    after = client.get("/v1/audit", headers=headers).json()["entries"]
    assert len(after) == len(before), "a review that reached no chain must not write chain traffic"


def test_an_engagement_figure_moves_the_verdict_and_an_omitted_one_does_not(client, headers):
    """The only numbers a review may use are the engagement's; a caller can supply them, not choose them."""
    cases = sweep(Priors.load())
    clean = next((index for index, case in enumerate(cases)
                  if _verdict(client, headers, index, "non-audit-assessor") == "clear"), None)
    assert clean is not None, "no engagement in the corpus is within the non-audit cap"
    within = client.post("/v1/firm/review", json={"engagement": clean}, headers=headers).json()
    sent = dataclasses.replace(cases[clean], non_audit_fee_cents=10_000_000)
    past = client.post("/v1/firm/review",
                       json={"engagement": clean, "non_audit_fee_cents": 10_000_000},
                       headers=headers).json()
    assert _verdict_of(within, "non-audit-assessor") == "clear"
    assert _verdict_of(past, "non-audit-assessor") == "breach", "the posted figure was ignored"
    assert sent.non_audit_fee_cents == 10_000_000
    assert _finding(past, "non-audit-assessor")["numbers"]["non_audit_fee_cents"] == 10_000_000


def test_a_posted_list_of_services_arrives_as_the_engagement_declares_it(client, headers):
    """JSON has no tuple and the field is one; a posted list must review, not break the case.

    An empty list is the other half of the claim. A review that read `[]` as "nothing was
    asked" is right here, so it has to be the derived figure that says so rather than a
    field the client forgot to send.
    """
    cases = sweep(Priors.load())
    booked = next((index for index, case in enumerate(cases) if case.non_audit_services), None)
    assert booked is not None, "no engagement in the corpus asks for a non-audit service"
    named = cases[booked].non_audit_services
    summary = client.post("/v1/firm/review",
                          json={"engagement": booked, "non_audit_services": list(named)},
                          headers=headers).json()
    assert len(summary["findings"]) == len(ROLES)
    assert _finding(summary, "independence-monitor")["numbers"]["requested"] == list(named)
    withheld = client.post("/v1/firm/review", json={"engagement": booked}, headers=headers).json()
    assert _finding(withheld, "independence-monitor")["numbers"]["requested"] == list(named)
    cleared = client.post("/v1/firm/review", json={"engagement": booked, "non_audit_services": []},
                          headers=headers).json()
    assert _finding(cleared, "independence-monitor")["numbers"]["requested"] == []


def test_the_form_describes_the_engagement_and_nothing_else():
    """A field the model invented would be a threshold somebody typed; one missing is a case half-asked."""
    asked = set(EngagementIn.model_fields) - {"engagement"}
    # `client` is the one engagement field a caller may not send: naming a client is not a figure,
    # and a posted name would rename an engagement the corpus derived.
    assert asked == {field.name for field in dataclasses.fields(Case)} - {"client"}
    assert "non_audit_fee_cap_percent" not in asked, "a threshold is never an input"


def test_a_request_cannot_ask_for_an_engagement_that_is_not_there(client, headers):
    too_far = len(sweep(Priors.load()))
    assert client.post("/v1/firm/review", json={"engagement": too_far},
                       headers=headers).status_code == 422
    assert client.post("/v1/firm/review", json={"engagement": -1},
                       headers=headers).status_code == 422
    assert client.post("/v1/firm/review", json={"engagement": 0, "parent_holding_percent": 101},
                       headers=headers).status_code == 422
    assert client.post("/v1/firm/review",
                       json={"engagement": 0, "non_audit_services": [""]},
                       headers=headers).status_code == 422


def test_a_question_about_a_role_nobody_hired_is_refused(client):
    assert client.get("/v1/firm/inbox", params={"role": "man-in-the-middle"}).status_code == 422
    answer = client.get("/v1/firm/inbox", params={"role": "engagement-partner"}).json()
    assert answer["messages"] == [] and answer["chain"]["on_chain"] is False


def test_the_engagements_are_the_derived_ones(client):
    cards = client.get("/v1/firm/engagements").json()["engagements"]
    cases = sweep(Priors.load())
    assert [card["client"] for card in cards] == [case.client for case in cases]
    # Normalised through JSON because that is the only shape a tuple survives the wire in: a
    # panel is owed the derived figures, not a byte-for-byte copy of a Python container.
    wrong = [card["index"] for card, case in zip(cards, cases, strict=True)
             if card["facts"] != _json(dataclasses.asdict(case))]
    assert wrong == [], "a panel shown a figure the corpus did not derive is shown a fiction"


# ----------------------------------------------------------------- a chain that is not there

def test_a_named_chain_that_never_answers_costs_one_short_probe(client, monkeypatch):
    """The point of a boot probe is that it stops. A dead url must not be a frozen table."""
    closed = socket.socket()
    closed.bind(("127.0.0.1", 0))
    port = closed.getsockname()[1]
    closed.close()
    monkeypatch.setenv("TWIN_CHAIN_URL", f"http://127.0.0.1:{port}")
    main.reset_state()
    started = time.monotonic()
    with TestClient(main.app) as running:
        took = time.monotonic() - started
        audit = running.get("/v1/health").json()["audit"]
        assert audit["on_chain"] is False
        assert str(port) in audit["why"], audit
        assert took < 15, f"boot waited {took:.1f}s on a chain that refused the connection"
        world = running.get("/v1/world", headers=by_device(DEVICE))
        assert world.status_code == 200, "the payment twin does not stop because the firm has no chain"


# ---------------------------------------------------------------------- with a chain

def test_boot_hires_every_role_once(live):
    audit = live.get("/v1/health").json()["audit"]
    assert audit["on_chain"] is True, audit
    assert audit["hired"] == len(ROLES) and audit["refused"] == 0, audit
    brief = live.get("/v1/firm").json()
    assert len(brief["chain"]["roles_on_chain"]) == len(ROLES)
    assert brief["chain"]["chain"]["cap_basis_points"] == 7000, "the deployed cap is the derived one"
    # And it does it once: the second look must not re-hire the firm.
    again = live.get("/v1/firm").json()
    assert again["chain"]["registration"] == brief["chain"]["registration"]
    assert len([row for row in again["chain"]["registration"] if row["ok"]]) == len(ROLES)


def test_a_review_opens_exactly_the_findings_that_bind(live, live_headers):
    """The claim the whole subsystem is built on, asked through the door a client uses.

    The contract is not a mirror of the firm's rules. Every proposal carries the engagement's
    fee figures, and the bytecode was given the derived cap, so on an engagement whose non-audit
    work sits one cent past it the chain records nothing however binding the rules called the
    finding. Both halves are asserted here: a refused attempt has to say which rule refused it,
    and a system that quietly dropped that name would look like a firm that opened an agreement
    it never did.
    """
    attested = []
    refused = 0
    blocked = []
    summaries = {}
    for index in range(len(sweep(Priors.load()))):
        summary = live.post("/v1/firm/review", json={"engagement": index},
                            headers=live_headers).json()
        summaries[index] = summary
        binding = [f for f in summary["findings"] if f["binding"]]
        assert len(summary["agreements"]) == len(binding), (summary["client"], len(binding))
        assert summary["chain"]["on_chain"] is True
        refused_here = [row for row in summary["agreements"] if row["state"] == "refused"]
        attested_here = [row for row in summary["agreements"] if row["state"] == "Attested"]
        assert len(attested_here) + len(refused_here) == len(summary["agreements"]), \
            "an agreement left mid-flight is a chain a panel cannot read"
        assert all(row["verdict"] in ("clear", "hold") for row in summary["agreements"])
        # Nothing settles: no agent holds a key that could mean anything to the registry.
        assert all(row["state"] != "Settled" for row in summary["agreements"])
        attested.extend(row["agreement"] for row in attested_here)
        refused += len(refused_here)
        for row in refused_here:
            # A refusal the reply cannot explain is a missing agreement with no reason.
            assert all(step["refused"] for step in row["steps"] if not step["ok"]), row
            assert any("FeeCapBreached" in step["refused"] for step in row["steps"]), row
        if summary["agreements"] and not attested_here:
            blocked.append(index)
    assert attested and refused, "the chain must both record and refuse, or it is only a mirror"
    # The interesting case is the whole engagement, not one row of it: the bytecode says no to
    # every agreement offered on terms it was given a ceiling for, whichever role offered them.
    assert blocked, "an engagement one cent past the cap opened something"
    for index in blocked:
        assert _verdict_of(summaries[index], "non-audit-assessor") == "breach", (
            f"engagement {index} was refused by the contract but cleared by the firm")
    on_chain = {row["id"] for row in live.get("/v1/firm/agreements").json()["agreements"]}
    assert set(attested) <= on_chain, "an agreement the review says it attested is not on the chain"


def test_the_agreements_are_readable_off_the_chain(live, live_headers):
    live.post("/v1/firm/review", json={"engagement": 0}, headers=live_headers)
    answer = live.get("/v1/firm/agreements").json()
    assert answer["chain"]["on_chain"] is True
    assert answer["agreements"], "a review that wrote agreements must be able to show them"
    assert all(row["state"] for row in answer["agreements"])
    waiting = answer["waiting_on_humans"]
    assert waiting, "an attested agreement that needs no human signature is a hold nobody decided"
    for row in waiting:
        assert row["agreement"] and row["from_role"] and row["to_role"], row
        assert row["from_role"] != row["to_role"], row


def test_the_transcript_is_this_world_s_only(live, live_headers):
    """Two tables, one chain: the mirror rows are the account's, the agreements are the contract's."""
    summary = live.post("/v1/firm/review", json={"engagement": 0}, headers=live_headers).json()
    mine = live.get("/v1/firm/transcript", headers=live_headers).json()
    assert mine["messages"], "a review that wrote traffic should leave a trail"
    assert len(mine["messages"]) == len(summary["agreements"]) * 3
    assert all(row["verb"] in ("propose", "accept", "attest") for row in mine["messages"])
    assert {row["state"] for row in mine["messages"]} == {"Proposed", "Accepted", "Attested"}
    theirs = live.get("/v1/firm/transcript", headers=by_device(OTHER_DEVICE)).json()
    assert theirs["messages"] == [], "another device read this world's mirror rows"
    # The chain, though, is shared truth: the agreements are the same either way.
    assert len(live.get("/v1/firm/agreements").json()["agreements"]) >= len(mine["messages"]) // 3


def test_a_role_can_read_what_it_was_told(live, live_headers):
    summary = live.post("/v1/firm/review", json={"engagement": 0}, headers=live_headers).json()
    if not summary["agreements"]:
        pytest.skip("engagement 0 opens nothing, so there is no mail to read")
    to_role = summary["agreements"][0]["to_role"]
    answer = live.get("/v1/firm/inbox", params={"role": to_role}).json()
    assert answer["chain"]["on_chain"] is True
    assert answer["messages"], f"{to_role} was sent nothing, though an agreement names it"
    assert answer["cursor"] >= 1
    later = live.get("/v1/firm/inbox", params={"role": to_role, "after": answer["cursor"]}).json()
    assert later["messages"] == [], "the cursor replayed mail the role had already read"


def _json(value):
    return json.loads(json.dumps(value))


def _verdict(client: TestClient, headers: dict, index: int, role: str) -> str:
    return _verdict_of(client.post("/v1/firm/review", json={"engagement": index},
                                   headers=headers).json(), role)


def _verdict_of(summary: dict, role: str) -> str:
    return _finding(summary, role)["verdict"]


def _finding(summary: dict, role: str) -> dict:
    return next(finding for finding in summary["findings"] if finding["role"] == role)
