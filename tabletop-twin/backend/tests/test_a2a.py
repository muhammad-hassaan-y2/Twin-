"""Agent-to-agent messages, against a chain that is really running and a database of its own.

Every test here is about the difference between two things that look the same from the
outside: the chain said no, and the chain did not answer. A refusal is an answer an agent
acts on, so it is mirrored and logged. A dead sidecar is not an answer, so nothing is
recorded at all - a world where an unsent message looks like a refused one is a world where
the panel can show an agreement nobody proposed.

Each guard is paired with the run that satisfies it, because a guard that only ever refuses
is indistinguishable from a broken client.
"""

from __future__ import annotations

import os
import tempfile

import pytest

from twin.audit.a2a import STATES, Bus
from twin.audit.agents import ROLES
from twin.audit.chain import Chain, ChainDown, ChainError, spawn_sidecar
from twin.store import Store

# The cap the corpus derived, in cents on a 2000.00 EUR audit fee. 1400.00 is exactly 70%,
# so one cent more is the smallest possible breach and the only honest test of the number.
AUDIT_CENTS = 200_000
CAP_CENTS = 140_000
USER = "test-user"


@pytest.fixture(scope="module")
def chain():
    box = tempfile.mkdtemp(prefix="twin-a2a-")
    with spawn_sidecar(journal=os.path.join(box, "a2a.journal.jsonl"), wait_sec=120.0) as running:
        assert running.status()["cap_basis_points"] == 7000, "the deployed cap must be the derived one"
        assert len(running.register_roles()) == len(ROLES), \
            "the firm cannot speak for an agent it never hired"
        yield running


@pytest.fixture()
def store():
    box = Store.temporary()
    try:
        yield box
    finally:
        box.close()


@pytest.fixture()
def bus(chain, store):
    return Bus(chain, store=store, user_id=USER, day=3)


def propose(over_cap: bool = False):
    return {
        "from_role": "non-audit-assessor",
        "to_role": "engagement-partner",
        "subject": "tax work during the audit",
        "terms": "prepare the returns and audit the same year",
        "amount_cents": AUDIT_CENTS,
        "non_audit_cents": CAP_CENTS + (1 if over_cap else 0),
    }


def test_a_refusal_is_an_answer_and_is_kept(bus, store):
    refused = bus.send("propose", **propose(over_cap=True))
    assert not refused.ok
    assert refused.refusal is not None and refused.refusal.name == "FeeCapBreached"
    assert refused.refusal.args == (str(CAP_CENTS + 1), str(CAP_CENTS)), "the receipt names both numbers"
    assert refused.gas_used > 0, "a refusal still costs what it cost"
    assert refused.receipt.seq > 0, "a refusal takes a place in the log like any other write"

    rows = store.agent_messages(USER)
    assert len(rows) == 1 and rows[0]["state"] == "refused" and rows[0]["refusal"].startswith("FeeCapBreached")
    assert rows[0]["agreement"] == "", "a proposal the contract refused is not an agreement"
    assert rows[0]["seq"] == refused.receipt.seq, "the mirror sorts by the chain, not by the wall clock"
    logged = [entry for entry in store.read_log(USER) if entry["kind"] == "agent_refusal"]
    assert logged and logged[0]["refused"].startswith("FeeCapBreached")

    # Control: the identical message at the cap. Only the number changed, so the number is
    # what the contract was refusing.
    accepted = bus.send("propose", **propose(over_cap=False))
    assert accepted.ok and accepted.state == "Proposed" and accepted.agreement
    assert accepted.receipt.seq == refused.receipt.seq + 1
    assert store.agent_messages(USER)[0]["state"] == "Proposed"


def test_a_role_the_registry_withdrew_cannot_open_an_agreement(bus, store):
    """The contract's guard: hired once, then no longer allowed to speak."""
    gone = "group-audit-coordinator"
    assert bus.chain.write("withdraw", role=gone).ok
    listed = {agent["role"]: agent["known"] for agent in bus.chain.roles()["agents"]}
    assert listed[gone] is False and listed["engagement-partner"] is True

    silent = bus.send("propose", **{**propose(), "from_role": gone})
    assert not silent.ok and silent.refusal is not None
    assert silent.refusal.name == "require" and "unknown proposer" in " ".join(silent.refusal.args)
    assert silent.gas_used > 0, "the registry check costs what any other check costs"
    row = store.agent_messages(USER)[0]
    assert (row["state"], row["from_role"], row["refusal"]) == ("refused", gone, "require(unknown proposer)")
    assert [entry for entry in store.read_log(USER) if entry["kind"] == "agent_refusal"]

    # Control: the same offer from a role the registry still lists. Only the sender changed.
    assert bus.send("propose", **propose()).ok


def test_an_agent_the_chain_never_funded_is_not_heard_at_all(bus, store):
    """The EVM's guard, which is not a refusal and must not be mirrored as one."""
    with pytest.raises(ChainError, match="enough funds"):
        bus.send("propose", **{**propose(), "from_role": "partner-that-was-never-hired"})
    assert store.agent_messages(USER) == [], "no transaction, so no message"
    assert list(store.read_log(USER)) == []


def test_the_human_hold_is_a_queue_and_it_drains(bus, store):
    opened = bus.send("propose", **{
        "from_role": "engagement-partner", "to_role": "quality-review-partner",
        "subject": "quality management review", "terms": "review the file before the opinion is signed",
        "amount_cents": 60_000, "non_audit_cents": 12_000, "horizon_sec": 7200,
    })
    assert opened.ok
    agreement = opened.agreement

    early = bus.send("settle", from_role="quality-review-partner", agreement=agreement)
    assert not early.ok and early.refusal.name == "WrongState"

    assert bus.send("accept", from_role="quality-review-partner", agreement=agreement).ok
    assert bus.send("attest", from_role="engagement-partner", agreement=agreement,
                    evidence="audit file section 4").ok

    waiting = bus.waiting_on_humans()
    assert [row["agreement"] for row in waiting] == [agreement]
    # The one move that cannot be made from here: the reviewer's own agent key closes the file.
    held = bus.send("settle", from_role="quality-review-partner", agreement=agreement)
    assert not held.ok and held.refusal.name == "HumanRequired"
    impostor = bus.send("countersign", from_role="engagement-partner", agreement=agreement)
    assert not impostor.ok and impostor.refusal.name == "HumanRequired"

    signed = bus.send("countersign", from_role="quality-review-partner", agreement=agreement)
    assert signed.ok, signed.refusal
    settled = bus.send("settle", from_role="quality-review-partner", agreement=agreement)
    assert settled.ok and settled.state == "Settled"
    assert bus.waiting_on_humans() == [], "the queue drains by signing, not by waiting"

    rows = [row for row in store.agent_messages(USER, limit=80) if row["agreement"] == agreement]
    assert len(rows) == 8, "every attempt is a row, including the three that were held"
    assert {(row["verb"], row["state"]) for row in rows} == {
        ("propose", "Proposed"), ("accept", "Accepted"), ("attest", "Attested"),
        ("countersign", "Attested"), ("settle", "Settled"), ("settle", "refused"),
        ("countersign", "refused"),
    }
    assert sorted(row["refusal"].split("(")[0] for row in rows if row["refusal"]) == [
        "HumanRequired", "HumanRequired", "WrongState",
    ]


def test_the_mirror_records_each_message_not_what_followed_it(bus, store):
    opened = bus.send("propose", **{
        "from_role": "tender-administrator", "to_role": "rotation-tracker",
        "subject": "ten-year rotation check", "terms": "confirm the firm may tender again in 2036",
        "amount_cents": 30_000, "non_audit_cents": 0,
    })
    assert opened.ok
    agreement = opened.agreement

    def mirrored():
        return {row["seq"]: row for row in store.agent_messages(USER, limit=80) if row["agreement"] == agreement}

    before = mirrored()
    assert [row["state"] for row in before.values()] == ["Proposed"]

    assert bus.send("accept", from_role="rotation-tracker", agreement=agreement).ok
    after = mirrored()
    assert len(after) == 2, "the second message is a new row, not an edit of the first"
    assert after[opened.receipt.seq]["state"] == "Proposed", "an accepted agreement was still a proposal once"
    # The current state is a question for the chain, which is the only thing that can answer it.
    assert store.agent_messages(USER, limit=80)[0]["state"] == "Accepted"
    assert bus.chain.agreement(agreement)["state"] == "Accepted"


def test_a_rejection_is_a_message_not_a_refusal(bus, store):
    opened = bus.send("propose", **{
        "from_role": "fraud-risk-assessor", "to_role": "materiality-reviewer",
        "subject": "fraud risk assessment", "terms": "set the performance materiality for the file",
        "amount_cents": 45_000, "non_audit_cents": 0,
    })
    assert opened.ok
    said_no = bus.send("reject", from_role="materiality-reviewer", agreement=opened.agreement,
                       reason="the assessment is scoped before the ledger is closed")
    assert said_no.ok and said_no.state == "Rejected"
    assert said_no.refusal is None, "an agent declining is traffic; the bytecode declining is a refusal"

    row = store.agent_messages(USER, limit=80)[0]
    assert (row["verb"], row["state"], row["refusal"]) == ("reject", "Rejected", "")
    assert row["reason"].startswith("the assessment is scoped")
    assert bus.chain.agreement(opened.agreement)["state"] == "Rejected"
    assert not [entry for entry in store.read_log(USER) if entry["kind"] == "agent_refusal"]

    # Control: the same verb on an agreement that does not exist is refused by the contract.
    missing = bus.send("reject", from_role="materiality-reviewer", agreement="0x" + "11" * 32, reason="")
    assert not missing.ok and missing.refusal.name == "UnknownAgreement"


def test_an_inbox_names_the_roles_and_a_cursor_advances(bus, chain):
    items, cursor = bus.receive("quality-review-partner")
    assert items, "the reviewer has an inbox"
    assert all("quality-review-partner" in item["roles"] for item in items)
    assert {item["name"] for item in items} >= {"Registered", "Proposed", "Accepted", "Countersigned", "Settled"}
    assert cursor >= max(item["seq"] for item in items)
    again, _ = bus.receive("quality-review-partner", after=cursor)
    assert again == [], "a cursor that rereads everything is not a cursor"
    # The same log read whole is bigger than one role's share of it.
    everything, _ = bus.receive("*")
    assert len(everything) > len(items)


def test_a_dead_chain_records_nothing(store):
    dead = Bus(Chain(url="http://127.0.0.1:1", timeout_sec=2.0), store=store, user_id=USER, day=1)
    with pytest.raises(ChainDown):
        dead.send("propose", **propose())
    assert store.agent_messages(USER) == []
    assert list(store.read_log(USER)) == [], "no answer is not a refusal"
    assert dead.status()["on_chain"] is False


def test_only_the_verbs_the_contract_understands_are_ours(bus):
    with pytest.raises(ValueError):
        bus.send("invoice", from_role="engagement-partner", agreement="0x" + "00" * 32)
    assert set(STATES) == {"propose", "accept", "attest", "countersign", "settle", "reject", "dispute"}
