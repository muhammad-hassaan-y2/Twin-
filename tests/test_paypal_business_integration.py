"""Tests for the PayPal-centered business and AI agent settlement operations:
- Accounts Payable (Vendor disbursements via PayPal Payouts)
- Accounts Receivable (Server-priced client billing & PayPal Order capture)
- Anti-structuring swarm spend guards
- Human-in-the-loop threshold escalations
- AI Agent Tool dispatch & AI CFO Assistant
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app, _get_session, Session
from swarm_oversight.monitor import Limits

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_state():
    import app.main as m
    m._session = Session(limits=Limits(per_agent=100_000, per_payee=150_000))
    m._invoices.clear()
    m._human_cleared.clear()
    yield


def test_dashboard_renders_html():
    """GET / renders the interactive executive dashboard."""
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Oversight Twin Settlement Hub" in resp.text
    assert "PayPal" in resp.text


def test_vendor_payout_under_threshold_auto_completes():
    """Agent vendor payout under $500 floor executes through PayPal Payouts."""
    payload = {
        "agent_id": "procure-ai",
        "recipient": "contractor@example.com",
        "amount_cents": 15_000,  # $150.00
        "mandate_cap_cents": 50_000,
        "note": "Software module delivery",
    }
    resp = client.post("/api/v1/agents/payout", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "COMPLETED"
    assert data["amount_usd"] == "150.00"
    assert data["payout_batch_id"] is not None


def test_vendor_payout_over_threshold_escalates_to_human():
    """Payout >= $500 holds in AWAITING_HUMAN until explicitly cleared."""
    payload = {
        "agent_id": "procure-ai",
        "recipient": "supplier-corp",
        "amount_cents": 75_000,  # $750.00 (>= $500 threshold)
        "mandate_cap_cents": 100_000,
        "note": "Bulk cloud infrastructure",
    }
    resp = client.post("/api/v1/agents/payout", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "AWAITING_HUMAN"
    assert "requires named operator" in data["reason"]

    # Now clear it with human operator
    agreement_id = data["agreement_id"]
    clear_resp = client.post("/api/v1/payments/clear", json={
        "agreement_id": agreement_id,
        "operator_name": "H. Shaukat (CFO)"
    })
    assert clear_resp.status_code == 200
    assert clear_resp.json()["status"] == "cleared"

    # Retry payout after clearance -> completes successfully
    resp2 = client.post("/api/v1/agents/payout", json=payload)
    assert resp2.status_code == 200
    assert resp2.json()["state"] == "COMPLETED"


def test_payout_blocked_when_swarm_cap_breached():
    """If an agent tries to disburse past its mandate, guard halts transaction."""
    payload = {
        "agent_id": "rogue-agent",
        "recipient": "sketchy-payee",
        "amount_cents": 60_000,  # $600 exceeds per_agent limit of $500
        "mandate_cap_cents": 50_000,
    }
    resp = client.post("/api/v1/agents/payout", json=payload)
    assert resp.status_code == 402
    assert resp.json()["state"] == "FAILED"


def test_b2b_client_invoicing_and_paypal_capture_flow():
    """Full Accounts Receivable flow:
    1. Server prices engagement from facts (rejecting LLM pricing)
    2. Opens PayPal order v2
    3. Requires human approval before capture
    4. Captures on PayPal and records in treasury
    """
    # Step 1: Prepare server-priced invoice
    prep_resp = client.post("/api/v1/invoices/prepare", json={
        "external_id": "ENG-401",
        "client_name": "Acme Global",
        "audit_fee_cents": 30_000,
        "non_audit_fee_cents": 5_000,
        "client_geo": "US",
    })
    assert prep_resp.status_code == 200
    inv = prep_resp.json()
    assert inv["amount_cents"] == 35_000
    assert inv["amount_usd"] == "350.00"
    invoice_id = inv["invoice_id"]

    # Step 2: Open PayPal order
    open_resp = client.post(f"/api/v1/invoices/{invoice_id}/open")
    assert open_resp.status_code == 200
    opened = open_resp.json()
    assert opened["state"] == "awaiting_capture"
    assert opened["paypal_order_id"] is not None

    # Step 3: Capture fails without human approver name
    fail_cap = client.post(f"/api/v1/invoices/{invoice_id}/capture", json={"approved_by": ""})
    assert fail_cap.status_code == 400

    # Step 4: Capture succeeds with named operator
    cap_resp = client.post(f"/api/v1/invoices/{invoice_id}/capture", json={
        "approved_by": "M. Hassaan"
    })
    assert cap_resp.status_code == 200
    captured = cap_resp.json()
    assert captured["state"] == "captured"
    assert captured["approved_by"] == "M. Hassaan"


def test_ai_agent_tool_dispatcher():
    """Verify standard JSON-Schema AI tools execute against PayPal services."""
    # Tool 1: swarm_metrics
    tool_resp = client.post("/api/v1/tools/execute", json={
        "name": "swarm_metrics",
        "arguments": {}
    })
    assert tool_resp.status_code == 200
    assert "total_spend_cents" in tool_resp.json()

    # Tool 2: billing_price
    price_resp = client.post("/api/v1/tools/execute", json={
        "name": "billing_price",
        "arguments": {"external_id": "ENG-TOOL-01"}
    })
    assert price_resp.status_code == 200
    assert "invoice_id" in price_resp.json()


def test_ai_cfo_assistant_chat():
    """Verify AI assistant natural language query routes to PayPal tools."""
    resp = client.post("/api/v1/assistant/chat", json={
        "prompt": "What is our current PayPal treasury spend and attack metrics?",
        "operator_name": "Finance Director"
    })
    assert resp.status_code == 200
    data = resp.json()
    assert "PayPal Settlement Hub Overview" in data["reply"]
    assert data["tool_called"] == "swarm_metrics"
