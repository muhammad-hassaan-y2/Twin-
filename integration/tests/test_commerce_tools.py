"""The assistant surface: it may look and price, it may not invent an amount or approve itself."""
from __future__ import annotations

import pytest

from oversight_twin.commerce import BillingBook
from oversight_twin.commerce_tools import CommerceTools, review_records
from twin.payments.paypal import PayPalConfig, PayPalTransport


def tools_for(paypal, records):
    config = PayPalConfig(client_id=paypal.client_id, secret=paypal.secret,
                          test_server_url=paypal.url)
    book = BillingBook(PayPalTransport(config), merchant="Ashgrove Audit LLP")
    return CommerceTools(book, review_records(records, dataset_id="crm-2026"))


def test_the_catalog_exposes_only_billing_actions(paypal, base_record):
    toolset = tools_for(paypal, [base_record()])
    names = [tool["name"] for tool in toolset.catalog()]
    assert names == ["billing_list", "billing_price", "billing_open", "billing_status",
                     "billing_capture", "billing_summary"]
    assert all(tool["input_schema"]["type"] == "object" for tool in toolset.catalog())


def test_list_shows_what_can_be_billed(paypal, base_record):
    toolset = tools_for(paypal, [base_record()])
    result = toolset.call("billing_list")
    assert result["ok"] is True
    row = result["result"][0]
    assert row["external_id"] == "A1"
    assert row["quality"] == "review"  # a hold desk needs a person
    assert row["invoice"]["amount_cents"] == 20_000


def test_the_assistant_cannot_supply_or_change_the_amount(paypal, base_record):
    toolset = tools_for(paypal, [base_record()])
    result = toolset.call("billing_price", {"external_id": "A1", "amount_cents": 1})
    assert result["ok"] is True
    assert result["result"]["amount_cents"] == 20_000
    assert result["ignored_arguments"] == ["amount_cents"]


def test_an_invoice_must_be_priced_before_it_can_be_opened(paypal, base_record):
    toolset = tools_for(paypal, [base_record()])
    refused = toolset.call("billing_open", {"invoice_id": "crm-2026:A1:invoice"})
    assert refused["ok"] is False
    assert "priced" in refused["refused"]
    assert paypal.create_calls == 0


def test_the_assistant_cannot_approve_its_own_capture(paypal, base_record):
    toolset = tools_for(paypal, [base_record()])
    toolset.call("billing_price", {"external_id": "A1"})
    opened = toolset.call("billing_open", {"invoice_id": "crm-2026:A1:invoice"})
    assert opened["result"]["state"] == "awaiting_capture"

    refused = toolset.call("billing_capture", {"invoice_id": "crm-2026:A1:invoice"})
    assert refused["ok"] is False
    assert "named person" in refused["refused"]
    assert paypal.capture_calls == 0


def test_a_named_person_can_capture_what_the_assistant_opened(paypal, base_record):
    toolset = tools_for(paypal, [base_record()])
    toolset.call("billing_price", {"external_id": "A1"})
    toolset.call("billing_open", {"invoice_id": "crm-2026:A1:invoice"})

    captured = toolset.call("billing_capture", {
        "invoice_id": "crm-2026:A1:invoice", "approved_by": "H. Shaukat"})
    assert captured["ok"] is True
    assert captured["result"]["state"] == "captured"
    assert captured["result"]["captured_by"] == "H. Shaukat"
    assert paypal.captured_cents == 20_000

    summary = toolset.call("billing_summary")["result"]
    assert summary["collected_cents"] == 20_000
    assert summary["outstanding_cents"] == 0


def test_a_blocked_engagement_is_refused_with_its_reasons(paypal, base_record):
    toolset = tools_for(paypal, [base_record(standard_vat_rate_percent=5.0,
                                             reduced_vat_rate_percent=9.0)])
    listed = toolset.call("billing_list")["result"][0]
    assert listed["quality"] == "blocked"
    assert "vat_rate_order_invalid" in {issue["code"] for issue in listed["issues"]}

    refused = toolset.call("billing_price", {"external_id": "A1"})
    assert refused["ok"] is False
    assert refused["issues"]


def test_unknown_tools_and_engagements_are_refusals(paypal, base_record):
    toolset = tools_for(paypal, [base_record()])
    assert toolset.call("billing_refund")["ok"] is False
    assert toolset.call("billing_price", {"external_id": "Z9"})["ok"] is False
    assert toolset.call("billing_status", {"invoice_id": "nope"})["ok"] is False
