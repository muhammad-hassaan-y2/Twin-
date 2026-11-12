"""PayPal failure paths on the billing book and the hub, against the localhost fake.

Covers what a naive client gets wrong: a rejected credential at the token call, a capture that
lands but whose reply is lost, a resend that must carry the same PayPal-Request-Id, and a
refused payment that must not make later, unrelated payments look suspicious.
"""
from __future__ import annotations

import pytest

from oversight_twin.commerce import (
    AWAITING_CAPTURE,
    CAPTURED,
    UNKNOWN,
    BillingBook,
    Invoice,
)
from oversight_twin.hub import Agreement, HumanGate, PayPalHub
from twin.payments.paypal import PayPalConfig, PayPalTransport

from test_hub import SPLIT, TIGHT


def invoice() -> Invoice:
    return Invoice(id="crm-2026:A1:invoice", engagement_id="crm-2026:A1", client="Acme GmbH",
                   amount_cents=20_000, description="Statutory audit - Acme GmbH")


def transport_for(paypal, secret=None) -> PayPalTransport:
    return PayPalTransport(PayPalConfig(client_id=paypal.client_id,
                                        secret=secret or paypal.secret,
                                        test_server_url=paypal.url))


def book_for(paypal, **kwargs) -> BillingBook:
    return BillingBook(transport_for(paypal), merchant="Ashgrove Audit LLP", **kwargs)


def test_the_token_call_sends_basic_credentials(paypal):
    book_for(paypal).open(invoice())
    assert paypal.token_calls == 1
    token_call = next(h for p, h in zip(paypal.path_calls, paypal.request_headers)
                      if p == "POST /v1/oauth2/token")
    assert token_call["authorization"].startswith("Basic ")


def test_the_capture_resend_after_a_lost_reply_carries_the_same_request_id(paypal):
    inv = invoice()
    book = book_for(paypal)
    book.open(inv)
    paypal.drop_capture_keys.add(inv.id)
    assert book.capture(inv.id, approved_by="H. Shaukat")["state"] == UNKNOWN

    entry = book.status(inv.id)
    assert entry["state"] == CAPTURED
    ids = [h.get("paypal-request-id") for p, h in zip(paypal.path_calls, paypal.request_headers)
           if p.endswith("/capture")]
    assert ids == [f"{inv.id}:capture"]
    assert paypal.captured_cents == 20_000


def test_a_refused_credential_at_capture_moves_nothing_and_does_not_condemn_the_invoice(paypal):
    inv = invoice()
    book = book_for(paypal)
    book.open(inv)
    # The credential is rotated after the order was raised; the next token call is refused.
    book.transport = transport_for(paypal, secret="rotated-away")
    book.capture(inv.id, approved_by="H. Shaukat")
    assert paypal.capture_calls == 0
    assert paypal.captured_cents == 0

    book.transport = transport_for(paypal)
    assert book.capture(inv.id, approved_by="H. Shaukat")["state"] == CAPTURED
    assert paypal.captured_cents == 20_000


def test_a_blocked_payment_makes_no_paypal_call_and_a_clean_payee_still_settles(paypal):
    ags = SPLIT + [Agreement("a3", "mandate-3", "cloud-host", 20_000)]
    hub = PayPalHub(transport_for(paypal), limits=TIGHT, freeze=False,
                    gate=HumanGate({a.id for a in ags}))
    rows = hub.settle_all(ags)
    assert [r.state for r in rows] == ["succeeded", "succeeded", "failed", "succeeded"]
    assert paypal.create_calls == paypal.capture_calls == 3
    assert paypal.captured_cents == 70_000
