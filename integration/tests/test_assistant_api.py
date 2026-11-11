"""The assistant at the HTTP edge: fail-closed without a key, a real tool loop with one."""
from __future__ import annotations

from fastapi.testclient import TestClient
from fake_gemini import answer, tool_calls

from oversight_twin.api import BillingService, SettlementService, create_app
from oversight_twin.commerce import SimulatedMerchant
from oversight_twin.llm import GeminiClient, GeminiConfig

TOKEN = "test-token-not-a-secret"
INVOICE_ID = "crm-2026:A1:invoice"


def auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {TOKEN}"}


def build(gemini=None):
    provider = SimulatedMerchant()
    client = GeminiClient(GeminiConfig(api_key=gemini.api_key, model="gemini-test",
                                       test_server_url=gemini.url)) if gemini else None
    billing = BillingService(provider, merchant="Ashgrove Audit LLP", rail="simulated",
                             client=client)
    service = SettlementService(lambda dataset, currency: None, rail="simulated")
    edge = TestClient(create_app(token=TOKEN, service=service, billing=billing))
    return edge, billing, provider


def prepare(edge, base_record):
    response = edge.post("/v1/billing/prepare", headers=auth(), json={
        "dataset_id": "crm-2026", "records": [base_record()]})
    assert response.status_code == 200
    return response.json()


def test_without_a_model_the_assistant_is_503(base_record):
    edge, _, _ = build()
    prepare(edge, base_record)
    response = edge.post("/v1/billing/ask", headers=auth(), json={"question": "what is due?"})
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]


def test_the_assistant_reads_the_book_through_the_tools(gemini, base_record):
    edge, _, _ = build(gemini)
    prepare(edge, base_record)
    gemini.replies.extend([tool_calls(("billing_list", {})),
                           answer("One engagement can be billed.")])
    response = edge.post("/v1/billing/ask", headers=auth(),
                         json={"question": "what can I bill?"})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "One engagement can be billed."
    assert body["steps"][0]["tool"] == "billing_list"
    assert body["steps"][0]["result"]["result"][0]["external_id"] == "A1"
    assert body["model"] == "gemini-test"


def test_a_model_fault_is_a_502(base_record):
    edge, _, _ = build()
    edge.app.state.billing.client = GeminiClient(GeminiConfig(api_key="k", model="gemini-test",
                                                              test_server_url="http://127.0.0.1:1"))
    prepare(edge, base_record)
    response = edge.post("/v1/billing/ask", headers=auth(), json={"question": "what is due?"})
    assert response.status_code == 502
    assert "could not be reached" in response.json()["detail"]


def test_capture_over_http_needs_the_named_approver(gemini, base_record):
    edge, billing, provider = build(gemini)
    prepare(edge, base_record)
    assert edge.post(f"/v1/billing/invoices/{INVOICE_ID}/open",
                     headers=auth()).status_code == 200

    gemini.replies.extend([
        tool_calls(("billing_capture", {"invoice_id": INVOICE_ID, "approved_by": "Gemini"})),
        answer("I cannot approve that.")])
    refused = edge.post("/v1/billing/ask", headers=auth(), json={"question": "capture it"})
    assert refused.status_code == 200
    assert refused.json()["steps"][0]["allowed"] is False
    assert provider.capture_calls == 0

    gemini.replies.extend([
        tool_calls(("billing_capture", {"invoice_id": INVOICE_ID})),
        answer("Captured.")])
    allowed = edge.post("/v1/billing/ask", headers=auth(),
                        json={"question": "capture it", "approved_by": "H. Shaukat"})
    assert allowed.status_code == 200
    assert allowed.json()["steps"][0]["allowed"] is True
    assert provider.capture_calls == 1
    assert edge.get("/v1/billing/summary", headers=auth()).json()["collected_cents"] == 20_000
    assert billing.book.status(INVOICE_ID)["captured_by"] == "H. Shaukat"


def test_health_names_the_store_and_the_model(gemini):
    edge, _, _ = build(gemini)
    billing = edge.get("/health").json()["billing"]
    assert billing["store"] == {"kind": "memory", "durable": False}
    assert billing["model"] == "gemini-test"
    assert billing["rail"] == "simulated"


def test_an_empty_question_is_422(gemini):
    edge, _, _ = build(gemini)
    response = edge.post("/v1/billing/ask", headers=auth(), json={"question": ""})
    assert response.status_code == 422


def test_an_unreachable_database_is_503_not_a_silent_fall_back_to_memory():
    from oversight_twin.store import PostgresStore

    billing = BillingService(SimulatedMerchant(), merchant="Ashgrove Audit LLP",
                             rail="simulated",
                             store=PostgresStore("postgresql://x:y@127.0.0.1:1/none",
                                                 connect_timeout=1))
    edge = TestClient(create_app(token=TOKEN, service=None, reason="runs are off",
                                 billing=billing))
    response = edge.get("/v1/billing/summary", headers=auth())
    assert response.status_code == 503
    assert "unreachable" in response.json()["detail"]
