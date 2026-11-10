"""Local EVM records agreements; the socket PayPal fake alone moves test money."""
import os
from pathlib import Path
import shutil
import tempfile

import pytest

from oversight_twin.hub import HumanGate, PayPalHub, firm_agreements
from twin.audit.a2a import Bus
from twin.audit.agents import ROLES, Firm
from twin.audit.chain import spawn_sidecar
from twin.payments.paypal import PayPalConfig, PayPalTransport
from test_hub import FakePayPal, OPEN, _expanded_case


@pytest.mark.skipif(not (shutil.which("node") or os.environ.get("TWIN_NODE")), reason="Node required for local EVM")
def test_firm_chain_signatures_paypal_capture_then_chain_record():
    with tempfile.TemporaryDirectory(prefix="twin-hub-chain-") as directory:
        with spawn_sidecar(journal=Path(directory) / "test.journal.jsonl") as chain:
            receipts = chain.register_roles()
            assert len(receipts) == len(ROLES) and all(r.ok for r in receipts)
            bus = Bus(chain)
            agreements = firm_agreements(_expanded_case(), Firm(), bus=bus)
            assert agreements and all(a.id.startswith("0x") for a in agreements)
            fake = FakePayPal()
            fake.start()
            try:
                transport = PayPalTransport(PayPalConfig(fake.client_id, fake.secret, test_server_url=fake.url))
                gate = HumanGate({a.id for a in agreements})
                hub = PayPalHub(transport, limits=OPEN, gate=gate, chain=chain)
                assert all(r.state == "awaiting_human" for r in hub.settle_all(agreements))
                assert fake.create_calls == 0
                for agreement in agreements:
                    receipt = chain.write("countersign", id=agreement.id, role=agreement.payee)
                    assert receipt.ok
                results = hub.settle_all(agreements)
                assert all(r.settled and r.chain_state == "Settled" for r in results)
                assert fake.create_calls == len(agreements)
                assert fake.captured_cents == sum(a.amount_cents for a in agreements)
                assert {r.provider_ref for r in results} == set(fake.orders)
                hub.settle_all(agreements)
                assert fake.create_calls == len(agreements)
                assert hub.settled_cents == fake.captured_cents
            finally:
                fake.stop()
