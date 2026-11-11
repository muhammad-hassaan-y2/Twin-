"""Guards cover one process and one currency; no durable recovery or production custody."""
from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from oversight_twin.hub import Agreement, HumanGate, PayPalHub
from oversight_twin import live_smoke
from twin.audit.agents import ROLES
from twin.audit.chain import AmbiguousWrite
from twin.payments.paypal import PayPalConfig, PayPalTransport, ProviderResult, SandboxTransport
from test_hub import FakePayPal, OPEN


@pytest.mark.parametrize("role", ROLES)
def test_each_roster_role_settles_via_real_transport(role):
    fake = FakePayPal()
    fake.start()
    try:
        transport = PayPalTransport(PayPalConfig(fake.client_id, fake.secret, test_server_url=fake.url))
        agreement = Agreement(role, role, "shared-payee", 100)
        hub = PayPalHub(transport, limits=OPEN, gate=HumanGate({role}))
        assert hub.settle(agreement).settled
        assert fake.create_calls == fake.capture_calls == 1
        assert fake.captured_cents == 100
    finally:
        fake.stop()


def test_repeat_and_concurrent_calls_do_not_recharge_or_recount():
    agreement = Agreement("same", "agent", "payee", 100)
    transport = SandboxTransport()
    hub = PayPalHub(transport, limits=OPEN, gate=HumanGate({agreement.id}))
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda _: hub.settle(agreement), range(8)))
    assert all(r.settled for r in rows)
    assert transport.charge_calls == 1
    assert hub.settled_cents == 100


def test_unknown_repeat_looks_up_without_new_charge():
    class Pending(SandboxTransport):
        def charge(self, *args, **kwargs):
            self.charge_calls += 1
            return ProviderResult("pending")

        def lookup(self, key):
            self.lookup_calls += 1
            return ProviderResult("unknown")

    transport = Pending()
    agreement = Agreement("pending", "agent", "payee", 100)
    hub = PayPalHub(transport, limits=OPEN, gate=HumanGate({agreement.id}))
    assert hub.settle(agreement).state == "unknown"
    assert hub.settle(agreement).state == "unknown"
    assert transport.charge_calls == 1
    assert transport.lookup_calls == 2
    assert hub.settled_cents == 0


def test_id_reuse_with_changed_terms_is_rejected_before_charge():
    agreement = Agreement("fixed", "agent", "payee", 100)
    transport = SandboxTransport()
    hub = PayPalHub(transport, limits=OPEN, gate=HumanGate({agreement.id}))
    hub.settle(agreement)
    with pytest.raises(ValueError, match="different payment terms"):
        hub.settle(replace(agreement, amount_cents=101))
    assert transport.charge_calls == 1


@pytest.mark.parametrize("amount", [0, -1, 1.1, True])
def test_invalid_amount_cannot_reduce_aggregate(amount):
    with pytest.raises(ValueError):
        Agreement("invalid", "agent", "payee", amount)


def test_different_currencies_are_not_summed_as_one():
    transport = SandboxTransport()
    hub = PayPalHub(transport, gate=HumanGate({"euros"}))
    with pytest.raises(ValueError, match="currency"):
        hub.settle(Agreement("euros", "agent", "payee", 100, "EUR"))
    assert transport.charge_calls == 0


class ChainRecord:
    def __init__(self):
        self.row = {"id": "chain-id", "state": "Attested", "signedBy": "0x0",
                    "from_role": "agent", "to_role": "payee", "amountCents": "100"}
        self.writes = 0
        self.lose_reply = False

    def agreement(self, _):
        return dict(self.row)

    def write(self, op, **payload):
        assert op == "settle" and payload == {"id": "chain-id", "by_role": "payee"}
        self.writes += 1
        self.row["state"] = "Settled"
        if self.lose_reply:
            raise AmbiguousWrite("reply lost")
        return SimpleNamespace(ok=True)


def test_chain_signature_and_payment_must_precede_chain_settlement():
    chain = ChainRecord()
    transport = SandboxTransport()
    agreement = Agreement("chain-id", "agent", "payee", 100)
    hub = PayPalHub(transport, limits=OPEN, gate=HumanGate({agreement.id}), chain=chain)
    assert hub.settle(agreement).state == "awaiting_human"
    assert transport.charge_calls == chain.writes == 0
    chain.row["signedBy"] = "0x1"
    result = hub.settle(agreement)
    assert result.settled and result.chain_state == "Settled"
    assert transport.charge_calls == chain.writes == 1


def test_lost_chain_write_reply_does_not_repay():
    chain = ChainRecord()
    chain.row["signedBy"] = "0x1"
    chain.lose_reply = True
    transport = SandboxTransport()
    agreement = Agreement("chain-id", "agent", "payee", 100)
    hub = PayPalHub(transport, limits=OPEN, gate=HumanGate({agreement.id}), chain=chain)
    first = hub.settle(agreement)
    assert first.settled and first.chain_state == "record_pending"
    assert hub.settle(agreement).chain_state == "Settled"
    assert transport.charge_calls == chain.writes == 1
    assert hub.settled_cents == 100


def test_provider_refusal_never_marks_chain_settled():
    chain = ChainRecord()
    chain.row["signedBy"] = "0x1"
    transport = SandboxTransport(decline_recipients={"payee"})
    agreement = Agreement("chain-id", "agent", "payee", 100)
    hub = PayPalHub(transport, limits=OPEN, gate=HumanGate({agreement.id}), chain=chain)
    assert hub.settle(agreement).state == "failed"
    assert chain.row["state"] == "Attested" and chain.writes == 0


@pytest.fixture
def smoke_environment(monkeypatch):
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "dummy-client")
    monkeypatch.setenv("PAYPAL_SECRET", "dummy-secret")
    monkeypatch.setenv("PAYPAL_ENVIRONMENT", "sandbox")
    monkeypatch.setenv("PAYPAL_SANDBOX_SMOKE", "1")


def test_smoke_skips_without_keys(monkeypatch, capsys):
    monkeypatch.delenv("PAYPAL_CLIENT_ID", raising=False)
    monkeypatch.delenv("PAYPAL_SECRET", raising=False)
    assert live_smoke.main([]) == 0
    assert "SKIPPED" in capsys.readouterr().out


def test_smoke_requires_opt_in(smoke_environment, monkeypatch):
    monkeypatch.delenv("PAYPAL_SANDBOX_SMOKE", raising=False)
    monkeypatch.setattr(live_smoke, "PayPalTransport", lambda _: pytest.fail("network opened"))
    assert live_smoke.main([]) == 0


@pytest.mark.parametrize("environment", ["live", "production", "sandobox"])
def test_smoke_rejects_live_and_misspelled_environments(smoke_environment, monkeypatch, environment):
    monkeypatch.setenv("PAYPAL_ENVIRONMENT", environment)
    monkeypatch.setattr(live_smoke, "PayPalTransport", lambda _: pytest.fail("network opened"))
    assert live_smoke.main([]) == 2


@pytest.mark.parametrize("status,code", [("completed", 0), ("denied", 1), ("pending", 3)])
def test_smoke_only_passes_confirmed_capture(smoke_environment, monkeypatch, capsys, status, code):
    class Result:
        def charge(self, *args, **kwargs):
            return ProviderResult(status)

        def lookup(self, key):
            return ProviderResult(status)

    monkeypatch.setattr(live_smoke, "PayPalTransport", lambda _: Result())
    assert live_smoke.main([]) == code
    output = capsys.readouterr().out
    assert "dummy-secret" not in output and "dummy-client" not in output
    assert ("PASS:" in output) == (status == "completed")
