"""The transport is the one part of the twin that can move real money.

These tests run ``PayPalTransport`` against a gateway that answers on a socket,
so what is being proved is the transport's own behaviour: client-credentials,
the created-then-captured two-step, ``PayPal-Request-Id`` replay, and the state
the machine lands in when a reply is lost after the money moved.
"""

from __future__ import annotations

import pytest
from fake_paypal import FakePayPal

from twin.payments.machine import (
    IllegalTransition,
    MoneyNotMoved,
    PaymentMachine,
    PaymentState,
)
from twin.payments.paypal import PayPalConfig, PayPalTransport, TransportTimeout

AMOUNT = 12_345


@pytest.fixture()
def gateway():
    fake = FakePayPal()
    fake.start()
    try:
        yield fake
    finally:
        fake.stop()


def config(gateway: FakePayPal, **overrides) -> PayPalConfig:
    fields = {"client_id": "test-client", "secret": "test-secret",
              "test_server_url": gateway.url, "timeout_sec": 5.0}
    fields.update(overrides)
    return PayPalConfig(**fields)


def settle(gateway: FakePayPal, action_id: str = "act-1", **overrides) -> tuple[PaymentMachine, PaymentState]:
    """Open a record, approve it, and hand it to the transport."""
    machine = PaymentMachine(approval_floor_cents=5_000)
    record = machine.open(action_id=action_id, amount_cents=AMOUNT, recipient="Ashgrove Paper")
    machine.propose(record)
    machine.approve(record, "pinch_hold_1s")
    machine.submit(record, PayPalTransport(config(gateway, **overrides)))
    return machine, record.state


# -------------------------------------------------------------------- the happy path


def test_a_charge_creates_an_order_then_captures_it(gateway):
    transport = PayPalTransport(config(gateway))
    result = transport.charge("tt-key-one", AMOUNT, "Ashgrove Paper")
    assert result.status == "completed"
    assert result.reference and result.reference.startswith("MOCK")
    assert gateway.token_calls == 1 and gateway.create_calls == 1 and gateway.capture_calls == 1
    assert gateway.captured_cents == AMOUNT


def test_the_token_is_reused_until_it_expires(gateway):
    transport = PayPalTransport(config(gateway))
    transport.charge("tt-key-a", 1_000, "Ashgrove Paper")
    transport.charge("tt-key-b", 2_000, "Ashgrove Paper")
    assert gateway.token_calls == 1


def test_a_denied_provider_lands_failed_not_mysterious(gateway):
    gateway.decline_recipients.add("Ashgrove Paper")
    _, state = settle(gateway)
    assert state is PaymentState.FAILED
    assert gateway.captured_cents == 0


def test_a_refused_payment_can_be_tried_again_under_a_fresh_key(gateway):
    gateway.decline_recipients.add("Ashgrove Paper")
    transport = PayPalTransport(config(gateway))
    machine = PaymentMachine(approval_floor_cents=5_000)
    record = machine.open(action_id="act-retry", amount_cents=AMOUNT, recipient="Ashgrove Paper")
    machine.propose(record)
    machine.approve(record, "pinch_hold_1s")
    machine.submit(record, transport)
    first_key = record.idempotency_key
    gateway.decline_recipients.clear()
    machine.retry(record)
    machine.approve(record, "pinch_hold_1s")
    machine.submit(record, transport)
    assert record.state is PaymentState.SUCCEEDED
    assert record.idempotency_key != first_key
    # The refused attempt never became an order, so only the retry one did.
    assert gateway.create_calls == 1 and len(gateway.orders) == 1
    assert gateway.captured_cents == AMOUNT


# --------------------------------------------------------------------- credentials


def test_bad_credentials_are_a_refusal_and_never_an_order(gateway):
    transport = PayPalTransport(config(gateway, client_id="someone-else"))
    with pytest.raises(MoneyNotMoved):
        transport.charge("tt-key-nope", AMOUNT, "Ashgrove Paper")
    assert gateway.token_calls == 1
    assert gateway.orders == {}


def test_bad_credentials_do_not_leave_the_record_asking(gateway):
    _, state = settle(gateway, client_id="someone-else")
    assert state is PaymentState.FAILED


# --------------------------------------------------------- the reply that never came


def test_a_lost_reply_after_the_capture_is_recovered_by_reconcile(gateway):
    transport = PayPalTransport(config(gateway))
    machine = PaymentMachine(approval_floor_cents=5_000)
    record = machine.open(action_id="act-drop", amount_cents=AMOUNT, recipient="Ashgrove Paper")
    gateway.drop_capture_keys.add(record.idempotency_key)
    machine.propose(record)
    machine.approve(record, "pinch_hold_1s")
    machine.submit(record, transport)
    assert record.state is PaymentState.UNKNOWN
    # The provider did take the money, even though the transport never heard back.
    assert gateway.captured_cents == AMOUNT

    machine.reconcile(record, transport)
    assert record.state is PaymentState.SUCCEEDED
    assert record.provider_ref and record.provider_ref.startswith("MOCK")
    # Reconciling looks, it does not pay: no second order, no second capture.
    assert gateway.create_calls == 1 and gateway.capture_calls == 1


def test_a_retried_charge_after_a_lost_reply_would_have_duplicated_nothing(gateway):
    transport = PayPalTransport(config(gateway))
    machine = PaymentMachine(approval_floor_cents=5_000)
    record = machine.open(action_id="act-blk", amount_cents=AMOUNT, recipient="Ashgrove Paper")
    gateway.drop_keys.add(record.idempotency_key)
    machine.propose(record)
    machine.approve(record, "pinch_hold_1s")
    machine.submit(record, transport)
    assert record.state is PaymentState.UNKNOWN
    with pytest.raises(IllegalTransition):
        machine.retry(record)
    assert gateway.create_calls == 1


def test_an_order_created_but_never_captured_stays_unknown(gateway):
    transport = PayPalTransport(config(gateway))
    machine = PaymentMachine(approval_floor_cents=5_000)
    record = machine.open(action_id="act-pend", amount_cents=AMOUNT, recipient="Ashgrove Paper")
    gateway.drop_keys.add(record.idempotency_key)
    machine.propose(record)
    machine.approve(record, "pinch_hold_1s")
    machine.submit(record, transport)
    assert record.state is PaymentState.UNKNOWN
    machine.reconcile(record, transport)
    # CREATED is not paid. The twin would rather keep asking than guess.
    assert record.state is PaymentState.UNKNOWN
    assert gateway.create_calls == 1 and gateway.capture_calls == 0
    assert gateway.captured_cents == 0


def test_a_lost_reply_can_be_resent_because_the_key_already_bought_an_order(gateway):
    transport = PayPalTransport(config(gateway))
    key = "tt-key-lost"
    gateway.drop_keys.add(key)
    with pytest.raises(TransportTimeout):
        transport.charge(key, AMOUNT, "Ashgrove Paper")
    assert gateway.orders and gateway.capture_calls == 0
    # The retry is safe: the provider replays the order it made instead of making another.
    again = transport.charge(key, AMOUNT, "Ashgrove Paper")
    assert again.status == "completed"
    assert len(gateway.orders) == 1 and gateway.create_calls == 1
    assert gateway.captured_cents == AMOUNT


def test_replaying_the_same_key_returns_the_same_order(gateway):
    transport = PayPalTransport(config(gateway))
    first = transport.charge("tt-key-replay", AMOUNT, "Ashgrove Paper")
    again = transport.charge("tt-key-replay", AMOUNT, "Ashgrove Paper")
    assert first.reference == again.reference
    assert gateway.replays == 1
    assert len(gateway.orders) == 1 and gateway.capture_calls == 1


# ------------------------------------------------------------------------- lookups


def test_lookup_of_a_key_the_provider_has_never_seen_says_not_found(gateway):
    transport = PayPalTransport(config(gateway))
    assert transport.lookup("tt-never-sent").status == "not_found"
