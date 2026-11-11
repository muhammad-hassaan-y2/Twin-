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
from twin.payments.paypal import PayPalConfig, PayPalTransport, ProviderResult, TransportTimeout

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


@pytest.mark.parametrize("auto_approve", [False, True])
def test_create_order_returns_and_remembers_the_order_without_capturing(gateway, auto_approve):
    gateway.auto_approve = auto_approve
    transport = PayPalTransport(config(gateway))
    key = "tt-create-only"
    order = transport.create_order(key=key, amount=AMOUNT, recipient="Ashgrove Paper")
    assert isinstance(order, dict)
    assert order["status"] == ("APPROVED" if auto_approve else "CREATED")
    assert order["custom_id"] == key
    assert gateway.request_headers[-1]["paypal-request-id"] == key
    assert gateway.create_calls == 1 and gateway.capture_calls == 0
    assert gateway.captured_cents == 0
    assert transport.lookup(key).reference == order["id"]
    assert gateway.path_calls[-1] == f"GET /v2/checkout/orders/{order['id']}"
    assert gateway.capture_calls == 0


def test_charge_does_not_capture_before_buyer_approval(gateway):
    gateway.auto_approve = False
    transport = PayPalTransport(config(gateway))
    result = transport.charge("tt-needs-buyer", AMOUNT, "Ashgrove Paper")
    assert result.status == "pending"
    assert result.reference and result.raw["status"] == "CREATED"
    assert gateway.create_calls == 1 and gateway.capture_calls == 0
    assert gateway.captured_cents == 0


def test_public_capture_order_after_explicit_buyer_approval(gateway):
    gateway.auto_approve = False
    transport = PayPalTransport(config(gateway))
    key = "tt-buyer-approved"
    order = transport.create_order(key, AMOUNT, "Ashgrove Paper")
    # The buyer approves at PayPal, not by approving the local payment record.
    gateway.orders[order["id"]]["status"] = "APPROVED"
    result = transport.capture_order(order_id=order["id"], key=key)
    assert isinstance(result, ProviderResult)
    assert result.status == "completed" and result.reference == order["id"]
    assert result.raw["status"] == "COMPLETED"
    assert gateway.request_headers[-1]["paypal-request-id"] == f"{key}:capture"
    assert gateway.capture_calls == 1 and gateway.captured_cents == AMOUNT


def test_fake_rejects_capture_of_an_unapproved_order(gateway):
    gateway.auto_approve = False
    transport = PayPalTransport(config(gateway))
    key = "tt-unapproved"
    order = transport.create_order(key, AMOUNT, "Ashgrove Paper")
    with pytest.raises(MoneyNotMoved, match="ORDER_NOT_APPROVED"):
        transport.capture_order(order["id"], key)
    assert gateway.orders[order["id"]]["status"] == "CREATED"
    assert gateway.captured_cents == 0


def test_local_approval_does_not_replace_buyer_approval(gateway):
    gateway.auto_approve = False
    _, state = settle(gateway)
    assert state is PaymentState.UNKNOWN
    assert gateway.create_calls == 1 and gateway.capture_calls == 0
    assert gateway.captured_cents == 0


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
    assert gateway.path_calls[-1] == f"GET /v2/checkout/orders/{record.provider_ref}"


def test_public_capture_remembers_the_reference_even_when_its_reply_is_lost(gateway):
    key = "tt-follow-up-drop"
    order = PayPalTransport(config(gateway)).create_order(key, AMOUNT, "Ashgrove Paper")
    # A separate follow-up process only knows the order ID and the original key.
    follow_up = PayPalTransport(config(gateway))
    gateway.drop_capture_keys.add(key)
    with pytest.raises(TransportTimeout):
        follow_up.capture_order(order["id"], key)
    assert gateway.captured_cents == AMOUNT
    result = follow_up.lookup(key)
    assert result.status == "completed" and result.reference == order["id"]
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


@pytest.mark.parametrize("failure_keys", ["drop_keys", "timeout_keys"])
def test_an_order_created_but_never_captured_stays_unknown(gateway, failure_keys):
    transport = PayPalTransport(config(gateway))
    machine = PaymentMachine(approval_floor_cents=5_000)
    record = machine.open(action_id="act-pend", amount_cents=AMOUNT, recipient="Ashgrove Paper")
    getattr(gateway, failure_keys).add(record.idempotency_key)
    machine.propose(record)
    machine.approve(record, "pinch_hold_1s")
    machine.submit(record, transport)
    assert record.state is PaymentState.UNKNOWN
    calls = list(gateway.path_calls)
    assert transport.lookup(record.idempotency_key).status == "unknown"
    machine.reconcile(record, transport)
    # The lost create reply leaves no ID to query, not evidence of no payment.
    assert record.state is PaymentState.UNKNOWN
    assert gateway.path_calls == calls
    with pytest.raises(IllegalTransition):
        machine.retry(record)
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


def test_lookup_without_a_known_reference_stays_unknown_without_any_request(gateway):
    transport = PayPalTransport(config(gateway))
    result = transport.lookup("tt-never-sent")
    assert result.status == "unknown" and result.reference is None
    assert gateway.path_calls == []
    assert gateway.orders == {}


@pytest.mark.parametrize("status", ["CREATED", "APPROVED", "COMPLETED"])
def test_lookup_is_a_read_only_get_of_the_known_order(gateway, status):
    gateway.auto_approve = status != "CREATED"
    transport = PayPalTransport(config(gateway))
    key = "tt-read-only"
    order = transport.create_order(key, AMOUNT, "Ashgrove Paper")
    if status == "COMPLETED":
        transport.capture_order(order["id"], key)
    before = len(gateway.path_calls)
    captures = gateway.capture_calls
    result = transport.lookup(key)
    assert result.status == ("completed" if status == "COMPLETED" else "pending")
    assert result.reference == order["id"] and result.raw["status"] == status
    assert gateway.path_calls[before:] == [f"GET /v2/checkout/orders/{order['id']}"]
    assert "paypal-request-id" not in gateway.request_headers[-1]
    assert gateway.create_calls == 1 and gateway.capture_calls == captures
    assert gateway.orders[order["id"]]["status"] == status


def test_lookup_after_restart_cannot_infer_an_order_is_missing(gateway):
    transport = PayPalTransport(config(gateway))
    key = "tt-restarted"
    transport.charge(key, AMOUNT, "Ashgrove Paper")
    calls = list(gateway.path_calls)
    restarted = PayPalTransport(config(gateway))
    result = restarted.lookup(key)
    assert result.status == "unknown" and result.reference is None
    assert gateway.path_calls == calls
    assert gateway.captured_cents == AMOUNT


def test_get_404_after_a_lost_capture_stays_unknown_and_blocks_fresh_retry(gateway):
    transport = PayPalTransport(config(gateway))
    machine = PaymentMachine(approval_floor_cents=5_000)
    record = machine.open(action_id="act-missing", amount_cents=AMOUNT, recipient="Ashgrove Paper")
    gateway.drop_capture_keys.add(record.idempotency_key)
    machine.propose(record)
    machine.approve(record, "pinch_hold_1s")
    machine.submit(record, transport)
    assert record.state is PaymentState.UNKNOWN
    assert gateway.captured_cents == AMOUNT
    order_id = gateway.by_request_id[record.idempotency_key]
    # The provider temporarily cannot serve an order that already took payment.
    order = gateway.orders.pop(order_id)
    before = len(gateway.path_calls)
    result = transport.lookup(record.idempotency_key)
    assert result.status == "unknown" and result.reference == order_id
    machine.reconcile(record, transport)
    assert record.state is PaymentState.UNKNOWN
    with pytest.raises(IllegalTransition):
        machine.retry(record)
    assert gateway.path_calls[before:] == [f"GET /v2/checkout/orders/{order_id}"] * 2
    assert gateway.create_calls == 1 and gateway.capture_calls == 1
    # A 404 must not forget the reference: a later GET can still recover it.
    gateway.orders[order_id] = order
    machine.reconcile(record, transport)
    assert record.state is PaymentState.SUCCEEDED
    assert record.provider_ref == order_id
    assert gateway.create_calls == 1 and gateway.capture_calls == 1
    assert gateway.captured_cents == AMOUNT


def test_fake_does_not_support_the_invented_lookup_post(gateway):
    transport = PayPalTransport(config(gateway))
    with pytest.raises(MoneyNotMoved, match="INVALID_REQUEST"):
        transport._post("/v2/checkout/orders", {"idempotency_id": "tt-not-a-real-lookup"})
    assert gateway.create_calls == 0 and gateway.capture_calls == 0
    assert gateway.orders == {}
