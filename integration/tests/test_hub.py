"""Hub guards and agent fees through PayPalTransport against a localhost HTTP fake."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from oversight_twin.hub import Agreement, HumanGate, PayPalHub, firm_agreements
from swarm_oversight.monitor import Limits
from twin.audit.agents import Case, Firm
from twin.payments.machine import idempotency_key
from twin.payments.paypal import PayPalConfig, PayPalTransport, SandboxTransport

_FAKE_PATH = (Path(__file__).resolve().parents[2]
              / "tabletop-twin" / "backend" / "tests" / "fake_paypal.py")
_spec = importlib.util.spec_from_file_location("fake_paypal", _FAKE_PATH)
_fake = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fake)
FakePayPal = _fake.FakePayPal

# Three mandates each pay 25000 to one payee: 75000 against a 60000 bound.
SPLIT = [Agreement(f"a{i}", f"mandate-{i}", "offshore-consulting", 25_000) for i in range(3)]
TIGHT = Limits(per_agent=50_000, per_payee=60_000, window=10, long_window=60, merge="both")
OPEN = Limits(per_agent=10**9, per_payee=10**9, window=10, long_window=60, merge="both")


def _cleared(agreements):
    return HumanGate({a.id for a in agreements})


# --- the human gate ---------------------------------------------------------

def test_no_human_clearance_settles_nothing():
    transport = SandboxTransport()
    hub = PayPalHub(transport, limits=TIGHT, gate=HumanGate())
    rows = hub.settle_all(SPLIT)
    assert [r.state for r in rows] == ["awaiting_human"] * 3
    assert hub.settled_cents == 0
    assert transport.charge_calls == 0  # the provider was never called


def test_clearing_one_agreement_settles_only_that_one():
    transport = SandboxTransport()
    hub = PayPalHub(transport, limits=TIGHT, gate=HumanGate({"a0"}))
    rows = hub.settle_all(SPLIT)
    assert [r.state for r in rows] == ["succeeded", "awaiting_human", "awaiting_human"]
    assert hub.settled_cents == 25_000
    assert transport.charge_calls == 1


# --- the swarm aggregate guard ---------------------------------------------

def test_freeze_holds_the_aggregate_at_the_bound():
    transport = SandboxTransport()
    hub = PayPalHub(transport, limits=TIGHT, freeze=True, gate=_cleared(SPLIT))
    rows = hub.settle_all(SPLIT)
    assert [r.state for r in rows] == ["succeeded", "succeeded", "failed"]
    assert hub.settled_cents == 50_000
    assert hub.frozen
    assert transport.charge_calls == 2  # the refused payment never reached PayPal
    assert "swarm oversight refused" in rows[-1].note
    assert hub.refusals[0][0] == "mandate-2"


def test_negative_control_removing_the_bound_settles_the_whole_aggregate():
    """Removing the aggregate bound permits the previously blocked payment."""
    transport = SandboxTransport()
    hub = PayPalHub(transport, limits=OPEN, freeze=True, gate=_cleared(SPLIT))
    rows = hub.settle_all(SPLIT)
    assert all(r.state == "succeeded" for r in rows)
    assert hub.settled_cents == 75_000
    assert not hub.frozen
    assert transport.charge_calls == 3


def test_hold_only_lets_a_legitimate_other_payee_through():
    ags = SPLIT + [Agreement("a3", "mandate-3", "cloud-host", 20_000)]
    transport = SandboxTransport()
    hub = PayPalHub(transport, limits=TIGHT, freeze=False, gate=_cleared(ags))
    rows = hub.settle_all(ags)
    assert [r.state for r in rows] == ["succeeded", "succeeded", "failed", "succeeded"]
    assert hub.settled_cents == 70_000
    assert not hub.frozen  # hold-only never freezes the principal


# --- the twin's own safety survives the hub --------------------------------

def test_ambiguous_charge_is_reconciled_not_retried():
    key = idempotency_key("a0", 0)
    transport = SandboxTransport(blackout_keys={key})
    hub = PayPalHub(transport, limits=OPEN, gate=HumanGate({"a0"}))
    row = hub.settle(SPLIT[0])
    assert row.state == "succeeded"  # UNKNOWN -> lookup recovered it
    assert transport.charge_calls == 1  # charged once, never blindly retried
    assert transport.lookup_calls == 1


def test_amount_crosses_in_cents_unchanged():
    transport = SandboxTransport()
    hub = PayPalHub(transport, limits=OPEN, gate=HumanGate({"a0"}))
    hub.settle(SPLIT[0])
    assert transport.charged[idempotency_key("a0", 0)].status == "completed"
    assert hub.settled_cents == 25_000


# --- the firm feeds the hub -------------------------------------------------

def _case(**kw):
    base = dict(client="Acme GmbH", audit_fee_cents=20_000, non_audit_fee_cents=1_000,
                is_pie=True, years_auditing=3, partner_years=2, tender_held=True,
                firm_fee_from_client_cents=1_000, firm_total_fees_cents=100_000,
                kyc_checked_years_ago=1, non_audit_services=())
    base.update(kw)
    return Case(**base)


def test_firm_binding_findings_become_agreements():
    ags = firm_agreements(_case(), Firm())
    assert ags and all(a.amount_cents == 20_000 for a in ags)
    assert all(a.agent and a.payee for a in ags)


def test_firm_breach_opens_no_agreement():
    # Past the outer rotation bound: engagement-partner returns breach, which binds nobody.
    ags = firm_agreements(_case(years_auditing=99), Firm())
    assert all(a.agent != "engagement-partner" for a in ags)


def test_firm_agreements_settle_through_the_hub():
    ags = firm_agreements(_case(), Firm())
    transport = SandboxTransport()
    hub = PayPalHub(transport, limits=OPEN, gate=_cleared(ags))
    rows = hub.settle_all(ags)
    assert all(r.state == "succeeded" for r in rows)
    assert hub.settled_cents == 20_000 * len(ags)


# --- the new tax, finance and audit desks feed the hub too ------------------

NEW_DESKS = ("vat-standard-rate-officer", "vat-reduced-rate-officer", "vat-rate-band-reviewer",
             "delegation-standards-reviewer", "size-ceiling-reviewer", "macro-inflation-reporter",
             "gdp-per-capita-reporter", "economic-sentiment-monitor")


def _expanded_case(**kw):
    base = dict(client_geo="DE", standard_vat_rate_percent=19.0, reduced_vat_rate_percent=7.0,
                supply_in_reduced_category=True, claims_small_undertaking=True,
                balance_sheet_eur=1_000_000.0, turnover_eur=2_000_000.0)
    base.update(kw)
    return _case(**base)


def test_every_new_desk_binds_and_settles_through_paypal():
    ags = firm_agreements(_expanded_case(), Firm())
    bound = {a.agent for a in ags}
    assert set(NEW_DESKS) <= bound, f"new desks that did not bind: {set(NEW_DESKS) - bound}"
    transport = SandboxTransport()
    hub = PayPalHub(transport, limits=OPEN, gate=_cleared(ags))
    rows = hub.settle_all(ags)
    assert all(r.state == "succeeded" for r in rows)
    assert hub.settled_cents == 20_000 * len(ags)
    assert transport.charge_calls == len(ags)


def test_new_desks_settle_on_the_real_paypal_transport():
    ags = [a for a in firm_agreements(_expanded_case(), Firm()) if a.agent in NEW_DESKS]
    assert len(ags) == len(NEW_DESKS)
    fake = FakePayPal()
    fake.start()
    try:
        config = PayPalConfig(client_id=fake.client_id, secret=fake.secret,
                              test_server_url=fake.url)
        hub = PayPalHub(PayPalTransport(config), limits=OPEN, gate=_cleared(ags))
        rows = hub.settle_all(ags)
        assert all(r.state == "succeeded" for r in rows)
        assert fake.create_calls == len(NEW_DESKS)
        assert fake.captured_cents == 20_000 * len(NEW_DESKS)
    finally:
        fake.stop()


def test_below_snapshot_vat_floor_requires_human_review():
    floor = Firm().priors.value("vat_standard_rate_min_percent")
    case = _expanded_case(standard_vat_rate_percent=floor - 1.0)
    findings = {f.role: f for f in Firm().review(case)}
    assert findings["vat-standard-rate-officer"].verdict == "hold"
    ags = firm_agreements(case, Firm())
    transport = SandboxTransport()
    hub = PayPalHub(transport, limits=OPEN)
    assert all(r.state == "awaiting_human" for r in hub.settle_all(ags))
    assert transport.charge_calls == 0


def test_negative_control_no_jurisdiction_settles_no_treasury_agreement():
    """An aggregate observation cannot stand in for an unnamed jurisdiction."""
    ags = firm_agreements(_expanded_case(client_geo=""), Firm())
    treasury = {"macro-inflation-reporter", "gdp-per-capita-reporter", "economic-sentiment-monitor"}
    assert not (treasury & {a.agent for a in ags})


# --- the REAL PayPal transport against the socket fake ----------------------

def _paypal_hub(fake, limits):
    config = PayPalConfig(client_id=fake.client_id, secret=fake.secret,
                          test_server_url=fake.url)
    return PayPalHub(PayPalTransport(config), limits=limits, gate=_cleared(SPLIT))


def test_real_paypal_transport_oversight_holds_the_aggregate():
    fake = FakePayPal()
    fake.start()
    try:
        hub = _paypal_hub(fake, TIGHT)
        rows = hub.settle_all(SPLIT)
        assert [r.state for r in rows] == ["succeeded", "succeeded", "failed"]
        assert fake.create_calls == 2
        assert fake.captured_cents == 50_000
    finally:
        fake.stop()


def test_real_paypal_transport_negative_control_settles_the_gap():
    fake = FakePayPal()
    fake.start()
    try:
        hub = _paypal_hub(fake, OPEN)
        rows = hub.settle_all(SPLIT)
        assert all(r.state == "succeeded" for r in rows)
        assert fake.create_calls == 3
        assert fake.captured_cents == 75_000
    finally:
        fake.stop()