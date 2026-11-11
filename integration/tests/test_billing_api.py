"""The billing edge: price, open, read and capture, with the same token and fail-closed rules."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from oversight_twin.api import BillingService, create_app
from oversight_twin.commerce import SimulatedMerchant

TOKEN = "test-token-not-a-secret"


def build():
    merchant = SimulatedMerchant()
    billing = BillingService(merchant, merchant="Ashgrove Audit LLP", rail="simulated")
    client = TestClient(create_app(token=TOKEN, service=None, reason="runs are off",
                                   billing=billing))
    return client, billing


def auth():
    return {"Authorization": f"Bearer {TOKEN}"}


def prepare(client, base_record, **changes):
    return client.post("/v1/billing/prepare", headers=auth(), json={
        "dataset_id": "crm-2026", "records": [base_record(**changes)]})


def test_prepare_prices_without_billing_anything(base_record):
    client, billing = build()
    response = prepare(client, base_record)
    assert response.status_code == 200
    body = response.json()
    assert body["priced"] == 1 and body["refused"] == 0
    assert body["engagements"][0]["invoice"]["amount_cents"] == 20_000
    assert body["book"]["billed_cents"] == 0
    assert billing.book.transport.create_calls == 0


def test_billing_requires_the_token(base_record):
    client, _ = build()
    assert client.post("/v1/billing/prepare", json={
        "dataset_id": "crm-2026", "records": [base_record()]}).status_code == 401
    assert client.get("/v1/billing/summary").status_code == 401


def test_open_then_capture_settles_once(base_record):
    client, billing = build()
    prepare(client, base_record)
    invoice_id = "crm-2026:A1:invoice"

    opened = client.post(f"/v1/billing/invoices/{invoice_id}/open", headers=auth())
    assert opened.status_code == 200
    assert opened.json()["state"] == "awaiting_capture"
    assert opened.json()["approval_url"].startswith("simulated://")
    again = client.post(f"/v1/billing/invoices/{invoice_id}/open", headers=auth()).json()
    assert again["order_id"] == opened.json()["order_id"]
    assert billing.book.transport.create_calls == 1

    captured = client.post(f"/v1/billing/invoices/{invoice_id}/capture", headers=auth(),
                           json={"approved_by": "H. Shaukat"})
    assert captured.status_code == 200
    assert captured.json()["state"] == "captured"
    assert captured.json()["captured_by"] == "H. Shaukat"

    repeat = client.post(f"/v1/billing/invoices/{invoice_id}/capture", headers=auth(),
                         json={"approved_by": "H. Shaukat"}).json()
    assert repeat["state"] == "captured"
    assert billing.book.transport.capture_calls == 1

    summary = client.get("/v1/billing/summary", headers=auth()).json()
    assert summary["collected_cents"] == 20_000
    assert summary["outstanding_cents"] == 0


def test_capture_needs_a_name_in_the_body(base_record):
    client, billing = build()
    prepare(client, base_record)
    invoice_id = "crm-2026:A1:invoice"
    client.post(f"/v1/billing/invoices/{invoice_id}/open", headers=auth())
    assert client.post(f"/v1/billing/invoices/{invoice_id}/capture", headers=auth(),
                       json={}).status_code == 422
    assert client.post(f"/v1/billing/invoices/{invoice_id}/capture", headers=auth(),
                       json={"approved_by": "  "}).status_code == 422
    assert billing.book.transport.capture_calls == 0


def test_unknown_invoices_are_404(base_record):
    client, _ = build()
    assert client.get("/v1/billing/invoices/nope", headers=auth()).status_code == 404
    assert client.post("/v1/billing/invoices/nope/open", headers=auth()).status_code == 404
    assert client.post("/v1/billing/invoices/nope/capture", headers=auth(),
                       json={"approved_by": "H. Shaukat"}).status_code == 404


def test_an_unpriced_invoice_cannot_be_opened(base_record):
    client, _ = build()
    # The book exists but nothing was prepared in this process.
    response = client.post("/v1/billing/invoices/crm-2026:A1:invoice/open", headers=auth())
    assert response.status_code == 404


def test_a_blocked_engagement_is_reported_not_priced(base_record):
    client, _ = build()
    body = prepare(client, base_record, standard_vat_rate_percent=5.0,
                   reduced_vat_rate_percent=9.0).json()
    row = body["engagements"][0]
    assert row["quality"] == "blocked"
    assert row["invoice"] is None
    assert "vat_rate_order_invalid" in {issue["code"] for issue in row["issues"]}
    assert body["priced"] == 0 and body["refused"] == 1


def test_the_invoice_list_reports_prepared_and_billed(base_record):
    client, _ = build()
    prepare(client, base_record)
    listed = client.get("/v1/billing/invoices", headers=auth()).json()
    assert listed["invoices"] == []
    assert listed["book"]["invoices"] == 0
    client.post("/v1/billing/invoices/crm-2026:A1:invoice/open", headers=auth())
    listed = client.get("/v1/billing/invoices", headers=auth()).json()
    assert len(listed["invoices"]) == 1
    assert listed["invoices"][0]["state"] == "awaiting_capture"


def test_billing_without_a_service_is_503(base_record):
    client = TestClient(create_app(token=TOKEN, service=None, reason="off",
                                   billing=None, billing_reason="billing is off"))
    response = client.post("/v1/billing/prepare", headers=auth(),
                           json={"dataset_id": "crm-2026", "records": [base_record()]})
    assert response.status_code == 503
    assert response.json()["detail"] == "billing is off"


def test_the_tool_catalog_is_discoverable():
    client, _ = build()
    tools = client.get("/v1/billing/tools", headers=auth()).json()["tools"]
    names = [tool["name"] for tool in tools]
    assert names == ["billing_list", "billing_price", "billing_open", "billing_status",
                     "billing_capture", "billing_summary"]


def test_a_model_can_drive_billing_but_cannot_price_or_approve_it(base_record):
    client, billing = build()
    prepare(client, base_record)

    def tool(name, **arguments):
        return client.post("/v1/billing/tool", headers=auth(),
                           json={"name": name, "arguments": arguments}).json()

    listed = tool("billing_list")
    assert listed["ok"] is True
    assert listed["result"][0]["external_id"] == "A1"

    priced = tool("billing_price", external_id="A1", amount_cents=1)
    assert priced["result"]["amount_cents"] == 20_000
    assert priced["ignored_arguments"] == ["amount_cents"]

    assert tool("billing_capture", invoice_id="crm-2026:A1:invoice")["ok"] is False
    opened = tool("billing_open", invoice_id="crm-2026:A1:invoice")
    assert opened["result"]["state"] == "awaiting_capture"

    paid = tool("billing_capture", invoice_id="crm-2026:A1:invoice",
                approved_by="H. Shaukat")
    assert paid["result"]["state"] == "captured"
    assert billing.book.transport.capture_calls == 1
    assert tool("billing_summary")["result"]["collected_cents"] == 20_000


@pytest.mark.parametrize("payload", [
    {"dataset_id": "crm-2026", "records": []},
    {"dataset_id": "", "records": [{"client": "Acme"}]},
], ids=["no-records", "empty-dataset"])
def test_a_bad_billing_body_is_422(payload):
    client, _ = build()
    assert client.post("/v1/billing/prepare", headers=auth(),
                       json=payload).status_code == 422
