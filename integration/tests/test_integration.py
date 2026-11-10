"""Negative controls for the integration. Each guard is shown to matter by
removing it and reproducing the failure: without the oversight layer the twin
settles the whole aggregate (the gap); with it the principal-wide bound holds.
The last two tests run the REAL PayPal transport against the twin's socket fake,
so the seam is proven on the production code path, not only on the sandbox.

Stdlib + pytest only: no PostgreSQL, no fastapi, no network beyond localhost.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from oversight_twin.bridge import SwarmOversight, record_action
from oversight_twin.demo import LIMITS, PAYMENTS, settle
from swarm_oversight.monitor import Limits
from twin.payments.machine import (
    IllegalTransition,
    PaymentMachine,
    PaymentState,
    idempotency_key,
)
from twin.payments.paypal import PayPalConfig, PayPalTransport, SandboxTransport

# fake_paypal is stdlib-only; load it by path so the test does not depend on the
# twin's pytest import mode.
_FAKE_PATH = (Path(__file__).resolve().parents[2]
              / "tabletop-twin" / "backend" / "tests" / "fake_paypal.py")
_spec = importlib.util.spec_from_file_location("fake_paypal", _FAKE_PATH)
_fake = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fake)
FakePayPal = _fake.FakePayPal

THREE = PAYMENTS[:3]  # the three mandates that split one payee


def _run(payments, oversight=None):
    machine = PaymentMachine(approval_floor_cents=5_000)
    transport = SandboxTransport()
    states = []
    for agent, amount, payee, tick in payments:
        rec = machine.open(f"{agent}:{payee}:{tick}", amount, payee, rail="sandbox")
        machine.propose(rec)
        machine.approve(rec, "pinch_hold_1s")
        if oversight is None:
            machine.submit(rec, transport)
        else:
            oversight.submit(machine, rec, transport, agent, tick)
        states.append(rec.state)
    return machine, transport, states


# --- the gap, and the guard that closes it ----------------------------------

def test_per_mandate_settles_the_whole_aggregate():
    """The twin as shipped: each payment is approved and under its own ceiling,
    so all three settle -- 75000c to one payee, over the 60000c bound."""
    settled, rows = settle(THREE)
    assert settled == 75_000
    assert all(state == "succeeded" for _, _, _, state in rows)


def test_oversight_freeze_holds_the_aggregate():
    ov = SwarmOversight(LIMITS, freeze=True)
    settled, rows = settle(THREE, ov)
    assert settled == 50_000
    assert rows[-1][3] == "failed"
    assert ov.frozen
    assert any("split_payment" in rules for _, _, _, rules in ov.refusals)


def test_removing_the_oversight_reproduces_the_gap():
    """Negative control: the ONLY difference between 75000c and 50000c is the
    oversight layer. Same machine, same transport, same approved payments."""
    plain, _, _ = _run(THREE, oversight=None)
    guarded, _, _ = _run(THREE, SwarmOversight(LIMITS, freeze=True))
    plain_out = sum(r.amount_cents for r in plain.all() if r.state is PaymentState.SUCCEEDED)
    guarded_out = sum(r.amount_cents for r in guarded.all() if r.state is PaymentState.SUCCEEDED)
    assert plain_out == 75_000
    assert guarded_out == 50_000


def test_hold_only_lets_a_legitimate_other_payee_through():
    ov = SwarmOversight(LIMITS, freeze=False)
    settled, rows = settle(PAYMENTS, ov)
    assert settled == 70_000          # 50000 to the split payee + 20000 legitimate
    assert not ov.frozen
    assert rows[2][3] == "failed"     # the breaching payment held
    assert rows[3][3] == "succeeded"  # the different payee still settles


def test_freeze_stops_the_legitimate_payment_too():
    ov = SwarmOversight(LIMITS, freeze=True)
    settled, rows = settle(PAYMENTS, ov)
    assert settled == 50_000
    assert ov.frozen
    assert rows[3][3] == "failed"     # frozen: even the legitimate fourth is stopped


def test_a_refused_payment_never_charges_the_transport():
    _, transport, states = _run(THREE, SwarmOversight(LIMITS, freeze=True))
    assert transport.charge_calls == 2          # the third never reached the provider
    assert states[-1] is PaymentState.FAILED    # MoneyNotMoved -> FAILED, not UNKNOWN


# --- the integration preserves the twin's own safety ------------------------

def test_unknown_payment_blind_retry_is_still_refused():
    """A charge whose reply is lost goes UNKNOWN; the oversight wrapper must not
    weaken the twin's rule that UNKNOWN cannot be retried blind."""
    action_id = "act-unknown"
    key = idempotency_key(action_id, 0)
    transport = SandboxTransport(blackout_keys={key})
    ov = SwarmOversight(LIMITS, freeze=True)
    machine = PaymentMachine(approval_floor_cents=5_000)
    rec = machine.open(action_id, 10_000, "cloud-host")
    machine.propose(rec)
    machine.approve(rec, "pinch_hold_1s")
    ov.submit(machine, rec, transport, "mandate-0", 0)
    assert rec.state is PaymentState.UNKNOWN
    with pytest.raises(IllegalTransition):
        machine.retry(rec)


def test_record_action_crosses_cents_and_payee_unchanged():
    machine = PaymentMachine()
    rec = machine.open("act-1", 12_345, "acme-ltd", currency="USD")
    action = record_action(rec, seq=7, agent="mandate-2", tick=3)
    assert (action.seq, action.agent, action.tick) == (7, "mandate-2", 3)
    assert action.amount == 12_345 and action.payee == "acme-ltd"
    assert action.kind == "spend"


def test_the_geography_rail_layer_is_preserved_under_oversight():
    """The aggregate bound sits ON TOP of the twin's rail geography, not in place
    of it: PayPal still cannot reach a country the catalog marks unavailable."""
    from twin.payments.rails import load_catalog
    paypal = load_catalog().rails["paypal"]
    assert paypal.blocks("PK") is not None
    assert paypal.blocks("US") is None


# --- end to end on the REAL PayPal transport --------------------------------

@pytest.fixture
def gateway():
    fake = FakePayPal()
    fake.start()
    try:
        yield fake
    finally:
        fake.stop()


def _paypal_config(fake) -> PayPalConfig:
    return PayPalConfig(client_id=fake.client_id, secret=fake.secret,
                        test_server_url=fake.url, timeout_sec=5.0)


def _paypal_run(fake, oversight):
    transport = PayPalTransport(_paypal_config(fake))
    machine = PaymentMachine(approval_floor_cents=5_000)
    settled = 0
    for agent, amount, payee, tick in THREE:
        rec = machine.open(f"{agent}:{tick}", amount, payee, currency="USD", rail="paypal")
        machine.propose(rec)
        machine.approve(rec, "pinch_hold_1s")
        if oversight is None:
            machine.submit(rec, transport)
        else:
            oversight.submit(machine, rec, transport, agent, tick)
        if rec.state is PaymentState.SUCCEEDED:
            settled += amount
    return settled


def test_oversight_guards_the_real_paypal_transport(gateway):
    settled = _paypal_run(gateway, SwarmOversight(LIMITS, freeze=True))
    assert settled == 50_000
    assert gateway.create_calls == 2        # the breaching order was never created
    assert gateway.captured_cents == 50_000


def test_without_oversight_the_real_paypal_transport_settles_the_gap(gateway):
    """Negative control on the production path: no wrapper, all three orders are
    created and captured at PayPal -- the aggregate leaves."""
    settled = _paypal_run(gateway, oversight=None)
    assert settled == 75_000
    assert gateway.create_calls == 3
    assert gateway.captured_cents == 75_000