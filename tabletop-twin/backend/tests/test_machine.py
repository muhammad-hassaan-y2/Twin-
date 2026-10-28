"""The state machine's only interesting property is what it refuses to do."""

from __future__ import annotations

import pytest

from twin.payments.machine import IllegalTransition, PaymentState, PaymentMachine, idempotency_key
from twin.payments.paypal import SandboxTransport, TransportTimeout


def machine() -> PaymentMachine:
    return PaymentMachine(approval_floor_cents=5_000)


def open_proposed(m: PaymentMachine, amount: int = 12_000, who: str = "Ashgrove Paper"):
    record = m.open("act-1", amount, who)
    return m.propose(record)


def test_unknown_only_leads_to_reconciling():
    from twin.payments.machine import LEGAL

    assert LEGAL[PaymentState.UNKNOWN] == {PaymentState.RECONCILING}


def test_blind_retry_from_unknown_is_refused():
    m = machine()
    record = open_proposed(m)
    transport = SandboxTransport(blackout_keys={record.idempotency_key})
    m.approve(record, "pinch_hold_1s")
    m.submit(record, transport)
    assert record.state is PaymentState.UNKNOWN

    with pytest.raises(IllegalTransition, match="duplicate"):
        m.retry(record)

    assert transport.charge_calls == 1  # the refusal is not merely a message


def test_reconcile_recovers_the_charge_without_making_a_second_one():
    m = machine()
    record = open_proposed(m)
    transport = SandboxTransport(blackout_keys={record.idempotency_key})
    m.approve(record, "pinch_hold_1s")
    m.submit(record, transport)
    m.reconcile(record, transport)
    assert record.state is PaymentState.SUCCEEDED
    assert transport.charge_calls == 1
    assert transport.lookup_calls == 1
    assert record.provider_ref is not None


def test_reconcile_that_finds_nothing_marks_failed_and_allows_a_fresh_key():
    m = machine()
    record = open_proposed(m)
    transport = SandboxTransport(blackout_keys={record.idempotency_key})
    m.approve(record, "pinch_hold_1s")
    m.submit(record, transport)
    assert record.state is PaymentState.UNKNOWN
    transport.charged.clear()  # the provider insists it never saw it
    m.reconcile(record, transport)
    assert record.state is PaymentState.FAILED
    m.retry(record)
    assert record.state is PaymentState.PROPOSED
    assert record.attempt == 1
    assert record.idempotency_key != idempotency_key("act-1", 0)
    assert transport.charge_calls == 1  # nothing was charged while the first attempt was unresolved


def test_a_lost_reply_is_never_reported_as_a_clean_failure():
    m = machine()
    record = open_proposed(m)
    transport = SandboxTransport(blackout_keys={record.idempotency_key})
    m.approve(record, "pinch_hold_1s")
    with pytest.raises(TransportTimeout):
        transport.charge(record.idempotency_key, record.amount_cents, record.recipient)
    m.submit(record, transport)
    assert record.state is PaymentState.UNKNOWN


def test_approval_floor_rejects_the_wrong_gesture():
    m = machine()
    record = open_proposed(m, amount=12_000)
    with pytest.raises(Exception, match="held pinch"):
        m.approve(record, "tap")
    assert record.state is PaymentState.PROPOSED


def test_small_payment_needs_no_gesture_at_all():
    m = machine()
    record = open_proposed(m, amount=1_200)
    m.approve(record, "auto")
    assert record.state is PaymentState.APPROVED


def test_succeeded_is_terminal():
    m = machine()
    record = open_proposed(m, amount=1_200)
    m.approve(record, "auto")
    m.submit(record, SandboxTransport())
    assert record.state is PaymentState.SUCCEEDED
    with pytest.raises(IllegalTransition):
        m.retry(record)


def test_a_charge_is_not_finished_until_its_effect_is_seen():
    m = machine()
    record = open_proposed(m, amount=1_200)
    m.approve(record, "auto")
    m.submit(record, SandboxTransport())
    assert record.verified_outcome is None
    m.verify_outcome(record, "Ashgrove Paper settled")
    assert record.verified_outcome == "Ashgrove Paper settled"
    with pytest.raises(IllegalTransition):
        m.verify_outcome(m.propose(m.open("act-2", 500, "x")), "too early")


def test_history_records_every_move_with_its_reason():
    m = machine()
    record = open_proposed(m)
    states = [entry[1] for entry in record.history]
    assert states[0] == PaymentState.DRAFT.value
    assert states[1] == PaymentState.PROPOSED.value


def test_keys_are_stable_per_attempt_and_change_on_retry():
    first = idempotency_key("act-9", 0)
    assert first == idempotency_key("act-9", 0)
    assert first != idempotency_key("act-9", 1)
    assert first.startswith("tt-")
