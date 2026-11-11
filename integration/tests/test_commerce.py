"""Billing an audited engagement on PayPal: one order, one capture, honest states.

The real transport talks to the localhost fake, so these tests exercise the two-step order
lifecycle rather than a stub: create, wait for buyer approval, capture, and reconcile a reply
that never arrived. No network, no credentials, no PostgreSQL.
"""
from __future__ import annotations

import pytest

from oversight_twin.commerce import (
    AWAITING_BUYER,
    AWAITING_CAPTURE,
    CAPTURED,
    CONFLICT,
    FAILED,
    UNKNOWN,
    BillingBook,
    Invoice,
    grounded,
    invoice_line,
    price_engagement,
)
from twin.audit.agents import Finding, Firm, Priors
from twin.payments.paypal import PayPalConfig, PayPalTransport

from oversight_twin.pipeline import parse_record

PRIORS = Priors.load()


def reviewed(base_record, **changes):
    _, case, issues = parse_record(base_record(**changes), priors=PRIORS)
    assert case is not None, issues
    return case, Firm(PRIORS).review(case)


def priced(base_record, **changes):
    case, findings = reviewed(base_record, **changes)
    invoice, issues = price_engagement("A1", case, findings, dataset_id="crm-2026")
    assert invoice is not None, issues
    return invoice, issues


def book_for(paypal, **changes):
    config = PayPalConfig(client_id=paypal.client_id, secret=paypal.secret,
                          test_server_url=paypal.url)
    return BillingBook(PayPalTransport(config), merchant="Ashgrove Audit LLP", **changes)


def make_invoice(**changes):
    row = {"id": "crm-2026:A1:invoice", "engagement_id": "crm-2026:A1",
           "client": "Acme GmbH", "amount_cents": 20_000, "currency": "USD",
           "description": "Statutory audit - Acme GmbH", "due_in_days": 14}
    row.update(changes)
    return Invoice(**row)


# ----------------------------------------------------------------------------- pricing


def test_a_reviewed_engagement_is_priced_at_its_own_fee(base_record):
    invoice, issues = priced(base_record)
    assert invoice.amount_cents == 20_000
    assert invoice.id == "crm-2026:A1:invoice"
    assert invoice.as_dict()["amount"] == "200.00"
    assert [issue.code for issue in issues] == ["open_questions"]
    assert issues[0].severity == "warning"


def test_a_breach_cannot_be_sold(base_record):
    case, findings = reviewed(base_record)
    findings = [f for f in findings if f.role != "engagement-partner"]
    findings.append(Finding("engagement-partner", "may this work be sold?", "breach", "forbidden"))
    invoice, issues = price_engagement("A1", case, findings, dataset_id="crm-2026")
    assert invoice is None
    assert "engagement_forbidden" in {issue.code for issue in issues}


def test_an_unreviewed_engagement_is_not_priced(base_record):
    case, _ = reviewed(base_record)
    invoice, issues = price_engagement("A1", case, [], dataset_id="crm-2026")
    assert invoice is None
    assert "not_reviewed" in {issue.code for issue in issues}


def test_a_zero_fee_engagement_is_not_priced(base_record):
    case, findings = reviewed(base_record, audit_fee_cents=0)
    invoice, issues = price_engagement("A1", case, findings, dataset_id="crm-2026")
    assert invoice is None
    assert "zero_fee" in {issue.code for issue in issues}


# -------------------------------------------------------------------------------- open


def test_opening_an_invoice_creates_one_order_and_replays_it(base_record, paypal):
    invoice, _ = priced(base_record)
    book = book_for(paypal)
    first = book.open(invoice)
    second = book.open(invoice)
    assert first["order_id"].startswith("MOCK")
    assert first["state"] == AWAITING_CAPTURE  # the fake auto-approves
    assert second["order_id"] == first["order_id"]
    assert paypal.create_calls == 1
    assert paypal.path_calls.count("POST /v2/checkout/orders") == 1
    assert paypal.replays == 0  # the book answered from its own record, not the provider


def test_changed_terms_under_one_invoice_id_are_a_conflict(base_record, paypal):
    invoice, _ = priced(base_record)
    book = book_for(paypal)
    book.open(invoice)
    changed = make_invoice(amount_cents=21_000)
    entry = book.open(changed)
    assert entry["state"] == CONFLICT
    assert paypal.create_calls == 1
    assert book.summary()["conflicts"] == 1


def test_two_invoice_ids_cannot_bill_the_same_engagement(base_record, paypal):
    invoice, _ = priced(base_record)
    book = book_for(paypal)
    book.open(invoice)
    duplicate = make_invoice(id="crm-2026:A1:second")
    entry = book.open(duplicate)
    assert entry["state"] == CONFLICT
    assert "already bills this engagement" in entry["note"]
    assert paypal.create_calls == 1


def test_one_book_keeps_one_currency(base_record, paypal):
    book = book_for(paypal)
    with pytest.raises(ValueError):
        book.open(make_invoice(currency="EUR"))
    with pytest.raises(ValueError):
        BillingBook(paypal, merchant=" ")


# ----------------------------------------------------------------------------- capture


def test_capture_needs_a_named_person(base_record, paypal):
    invoice, _ = priced(base_record)
    book = book_for(paypal)
    book.open(invoice)
    with pytest.raises(ValueError, match="name"):
        book.capture(invoice.id, approved_by="   ")
    assert paypal.capture_calls == 0


def test_capture_before_buyer_approval_moves_nothing(base_record, paypal):
    paypal.auto_approve = False
    invoice, _ = priced(base_record)
    book = book_for(paypal)
    opened = book.open(invoice)
    assert opened["state"] == AWAITING_BUYER
    entry = book.capture(invoice.id, approved_by="H. Shaukat")
    assert entry["state"] == AWAITING_BUYER
    assert paypal.capture_calls == 0
    assert paypal.captured_cents == 0


def test_an_approved_order_is_captured_once(base_record, paypal):
    invoice, _ = priced(base_record)
    book = book_for(paypal)
    opened = book.open(invoice)
    entry = book.capture(invoice.id, approved_by="H. Shaukat")
    assert entry["state"] == CAPTURED
    assert entry["provider_ref"] == opened["order_id"]
    assert entry["captured_by"] == "H. Shaukat"
    assert paypal.captured_cents == 20_000

    again = book.capture(invoice.id, approved_by="H. Shaukat")
    assert again["state"] == CAPTURED
    assert paypal.capture_calls == 1
    assert paypal.captured_cents == 20_000


def test_a_lost_capture_reply_is_reconciled_not_retried(base_record, paypal):
    invoice, _ = priced(base_record)
    book = book_for(paypal)
    book.open(invoice)
    paypal.drop_capture_keys.add(invoice.id)

    entry = book.capture(invoice.id, approved_by="H. Shaukat")
    assert entry["state"] == UNKNOWN
    assert paypal.capture_calls == 1

    reconciled = book.status(invoice.id)
    assert reconciled["state"] == CAPTURED
    assert reconciled["provider_ref"]
    assert paypal.capture_calls == 1
    assert paypal.captured_cents == 20_000


def test_a_lost_create_reply_is_reopened_under_the_same_key(base_record, paypal):
    invoice, _ = priced(base_record)
    book = book_for(paypal)
    paypal.drop_keys.add(invoice.id)

    first = book.open(invoice)
    assert first["state"] == UNKNOWN
    assert paypal.create_calls == 1

    second = book.open(invoice)
    assert second["state"] == AWAITING_CAPTURE
    assert second["order_id"] == first["order_id"] or second["order_id"].startswith("MOCK")
    assert paypal.create_calls == 1
    assert paypal.replays == 1


def test_a_refused_order_is_a_failed_state_not_a_crash(base_record, paypal):
    paypal.decline_recipients.add("Ashgrove Audit LLP")
    invoice, _ = priced(base_record)
    book = book_for(paypal)
    entry = book.open(invoice)
    assert entry["state"] == FAILED
    assert "refused" in entry["note"]
    assert book.capture(invoice.id, approved_by="H. Shaukat")["state"] == FAILED
    assert paypal.capture_calls == 0


# ---------------------------------------------------------------------------- the line


def test_the_firm_writes_the_line_by_default(base_record):
    invoice, _ = priced(base_record)
    line, route = invoice_line(invoice)
    assert line == "Statutory audit - Acme GmbH"
    assert route == "rules"


def test_a_model_may_reword_but_not_add_a_figure(base_record):
    invoice, _ = priced(base_record)

    def good(prompt, facts):
        return f"Statutory audit of {facts['client']} - {facts['amount']} {facts['currency']}"

    def invented(prompt, facts):
        return f"Statutory audit of {facts['client']} at a 19% discount, only 15,000 due"

    assert invoice_line(invoice, good) == (good("", invoice.as_dict()), "model")
    line, route = invoice_line(invoice, invented)
    assert line == invoice.description
    assert route == "rules (the model added a figure)"


def test_grounding_accepts_major_minor_and_term_only(base_record):
    invoice, _ = priced(base_record)
    assert grounded("200.00 USD due in 14 days", invoice)
    assert grounded("200 USD due in 14 days", invoice)
    assert grounded("20000 cents due in 14 days", invoice)
    assert not grounded("250.00 USD due in 14 days", invoice)
    assert not grounded("", invoice)


# -------------------------------------------------------------------------------- book


def test_the_book_reports_billed_collected_and_outstanding(base_record, paypal):
    first, _ = priced(base_record)
    book = book_for(paypal)
    book.open(first)
    book.capture(first.id, approved_by="H. Shaukat")

    second = make_invoice(id="crm-2026:A2:invoice", engagement_id="crm-2026:A2",
                          client="Beta AG", amount_cents=30_000)
    book.open(second)

    summary = book.summary()
    assert summary["invoices"] == 2
    assert summary["billed_cents"] == 50_000
    assert summary["collected_cents"] == 20_000
    assert summary["outstanding_cents"] == 30_000
    assert summary["captured"] == 1
    assert summary["awaiting_capture"] == 1
    assert summary["clients"] == ["Acme GmbH", "Beta AG"]
    assert summary["currency"] == "USD"
    assert summary["merchant"] == "Ashgrove Audit LLP"
