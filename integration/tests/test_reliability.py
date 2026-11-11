"""What a restart, a second worker or an untrusted caller must not be able to do.

Each test names the failure it excludes. Where a guard can be removed in one line, the test
removes it and shows the failure that follows, so a passing suite is evidence and not a ritual.
"""
from __future__ import annotations

import threading

import pytest
from fastapi.testclient import TestClient

from oversight_twin.api import BillingService, create_app, edge_from_env
from oversight_twin.commerce import BillingBook, Invoice, InvoiceConflict, SimulatedMerchant
from oversight_twin.store import MemoryStore, StoreUnavailable
from twin.payments.paypal import PayPalConfig, PayPalTransport

INVOICE_ID = "crm-2026:A1:invoice"
TOKEN = "test-token-not-a-secret"
AUTH = {"Authorization": f"Bearer {TOKEN}"}


def invoice(amount_cents: int = 20_000, invoice_id: str = INVOICE_ID,
            engagement_id: str = "crm-2026:A1") -> Invoice:
    return Invoice(id=invoice_id, engagement_id=engagement_id, client="Acme GmbH",
                   amount_cents=amount_cents, description="Statutory audit - Acme GmbH")


def book(provider, store) -> BillingBook:
    return BillingBook(provider, merchant="Ashgrove Audit LLP", store=store)


def opened_book():
    provider = SimulatedMerchant()
    store = MemoryStore()
    first = book(provider, store)
    first.prepare(invoice())
    first.open_prepared(INVOICE_ID, actor="H. Shaukat", request_id="r-1")
    return provider, store, first


def prepare(client, record) -> dict:
    response = client.post("/v1/billing/prepare", headers=AUTH,
                           json={"dataset_id": "crm-2026", "records": [record()]})
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------ a restart

def test_a_capture_after_a_restart_reads_the_stored_order(paypal):
    # The idempotency-key map lives in the transport's process. A restarted transport has an
    # empty map, so a key lookup says "unknown" even though the provider holds an APPROVED
    # order. The capture must be driven by the order id the book stored, not by that map.
    config = PayPalConfig(client_id=paypal.client_id, secret=paypal.secret,
                          test_server_url=paypal.url)
    store = MemoryStore()
    first = BillingBook(PayPalTransport(config), merchant="Ashgrove Audit LLP", store=store)
    first.prepare(invoice())
    opened = first.open_prepared(INVOICE_ID)
    assert opened["state"] == "awaiting_capture"

    restarted = PayPalTransport(config)
    assert restarted.lookup(INVOICE_ID).status == "unknown"  # the map really is gone
    second = BillingBook(restarted, merchant="Ashgrove Audit LLP", store=store)
    captured = second.capture(INVOICE_ID, approved_by="H. Shaukat")
    assert captured["state"] == "captured"
    assert captured["captured_by"] == "H. Shaukat"
    assert paypal.capture_calls == 1
    assert paypal.captured_cents == 20_000


def test_a_stale_worker_cannot_erase_who_captured_the_payment():
    provider, store, first = opened_book()
    stale = book(provider, store)
    assert stale.status(INVOICE_ID)["state"] == "awaiting_capture"  # it holds its own copy

    first.capture(INVOICE_ID, approved_by="H. Shaukat")
    again = stale.capture(INVOICE_ID, approved_by="Someone Else")
    assert again["state"] == "captured"
    assert again["captured_by"] == "H. Shaukat"
    assert provider.capture_calls == 1
    assert book(provider, store).status(INVOICE_ID)["captured_by"] == "H. Shaukat"


def test_two_captures_at_once_capture_once():
    provider, store, _ = opened_book()
    handles = {name: book(provider, store) for name in ("A. Person", "B. Person")}
    results: dict[str, dict] = {}
    start = threading.Barrier(len(handles))

    def capture(name: str, handle: BillingBook) -> None:
        start.wait(timeout=10)
        results[name] = handle.capture(INVOICE_ID, approved_by=name)

    threads = [threading.Thread(target=capture, args=(name, handle))
               for name, handle in handles.items()]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert provider.capture_calls == 1
    assert set(results) == set(handles)
    assert {row["state"] for row in results.values()} == {"captured"}
    # Both callers are shown the approver who actually captured, never their own guess.
    assert len({row["captured_by"] for row in results.values()}) == 1
    assert book(provider, store).status(INVOICE_ID)["captured_by"] in handles


# ------------------------------------------------------------- the store guards

def test_the_store_never_downgrades_a_captured_row():
    store = MemoryStore()
    captured = {"invoice": {"id": "inv-1", "amount_cents": 1, "client": "Acme"},
                "state": "captured", "captured_by": "H. Shaukat"}
    store.save_entry("m", captured)
    store.save_entry("m", dict(captured, state="awaiting_buyer", captured_by=""))
    assert store.load_entry("m", "inv-1")["state"] == "captured"
    assert store.load_entry("m", "inv-1")["captured_by"] == "H. Shaukat"
    assert store.update_entry("m", dict(captured, state="failed"),
                              expected=("awaiting_buyer",)) is False
    assert store.load_entry("m", "inv-1")["state"] == "captured"


def test_the_ledger_keeps_every_fact_in_order():
    provider, store, first = opened_book()
    first.capture(INVOICE_ID, approved_by="H. Shaukat", actor="H. Shaukat", request_id="r-1")
    kinds = [event["kind"] for event in store.events("Ashgrove Audit LLP", INVOICE_ID)]
    assert kinds == ["order_opened", "capture_attempted", "captured"]
    first_event = store.events("Ashgrove Audit LLP", INVOICE_ID)[0]
    assert first_event["actor"] == "H. Shaukat"
    assert first_event["request_id"] == "r-1"
    assert first_event["at"].endswith("+00:00")
    assert store.events("Ashgrove Audit LLP", "no-such-invoice") == []


# -------------------------------------------------------------- pricing rules

def test_an_engagement_cannot_be_billed_twice():
    provider = SimulatedMerchant()
    store = MemoryStore()
    ledger = book(provider, store)
    ledger.prepare(invoice())
    with pytest.raises(InvoiceConflict):
        ledger.prepare(invoice(invoice_id="crm-2026:A1:second", engagement_id="crm-2026:A1"))
    assert ledger.summary()["invoices"] == 0
    assert provider.create_calls == 0


def test_a_fee_above_the_ceiling_is_refused_not_clamped(base_record):
    billing = BillingService(SimulatedMerchant(), merchant="Ashgrove Audit LLP",
                             rail="simulated", max_invoice_cents=15_000)
    client = TestClient(create_app(token=TOKEN, service=None, reason="runs are off",
                                   billing=billing))
    body = prepare(client, base_record)  # the fixture fee is 200.00
    assert body["priced"] == 0 and body["refused"] == 1
    assert body["engagements"][0]["invoice"] is None
    assert any(issue["code"] == "fee_above_ceiling"
               for issue in body["engagements"][0]["issues"])
    assert client.get("/v1/billing/summary", headers=AUTH).json()["invoices"] == 0


# ---------------------------------------------------------------- the HTTP edge

def test_a_named_operator_cannot_capture_as_somebody_else(base_record):
    billing = BillingService(SimulatedMerchant(), merchant="Ashgrove Audit LLP", rail="simulated")
    client = TestClient(create_app(tokens={"tok-hs": "H. Shaukat", "tok-ro": "R. Ozan"},
                                   service=None, reason="runs are off", billing=billing))
    shaukat = {"Authorization": "Bearer tok-hs"}
    assert client.post("/v1/billing/prepare", headers=shaukat, json={
        "dataset_id": "crm-2026", "records": [base_record()]}).status_code == 200
    assert client.post(f"/v1/billing/invoices/{INVOICE_ID}/open",
                       headers=shaukat).status_code == 200

    refused = client.post(f"/v1/billing/invoices/{INVOICE_ID}/capture", headers=shaukat,
                          json={"approved_by": "R. Ozan"})
    assert refused.status_code == 403
    assert billing.book.transport.capture_calls == 0

    signed = client.post(f"/v1/billing/invoices/{INVOICE_ID}/capture", headers=shaukat, json={})
    assert signed.status_code == 200
    assert signed.json()["captured_by"] == "H. Shaukat"

    events = client.get(f"/v1/billing/invoices/{INVOICE_ID}/events", headers=shaukat).json()
    assert [event["kind"] for event in events["events"]] == [
        "order_opened", "capture_attempted", "captured"]
    assert events["events"][0]["actor"] == "H. Shaukat"
    assert events["events"][0]["request_id"]


def test_a_shared_token_must_still_name_the_approver(base_record):
    # The negative control for the test above: with one token there is no identity to sign
    # with, so an unnamed capture is refused instead of being attributed to "operator".
    billing = BillingService(SimulatedMerchant(), merchant="Ashgrove Audit LLP", rail="simulated")
    client = TestClient(create_app(token=TOKEN, service=None, reason="runs are off",
                                   billing=billing))
    prepare(client, base_record)
    client.post(f"/v1/billing/invoices/{INVOICE_ID}/open", headers=AUTH)
    assert client.post(f"/v1/billing/invoices/{INVOICE_ID}/capture", headers=AUTH,
                       json={}).status_code == 422
    assert billing.book.transport.capture_calls == 0


def test_a_caller_past_its_rate_is_refused(base_record):
    billing = BillingService(SimulatedMerchant(), merchant="Ashgrove Audit LLP", rail="simulated")
    client = TestClient(create_app(token=TOKEN, service=None, reason="runs are off",
                                   billing=billing, rate_limit_per_min=3))
    for _ in range(3):
        assert client.get("/v1/billing/summary", headers=AUTH).status_code == 200
    throttled = client.get("/v1/billing/summary", headers=AUTH)
    assert throttled.status_code == 429
    assert "too many requests" in throttled.json()["detail"]


def test_an_oversized_body_is_refused_before_the_book(base_record):
    billing = BillingService(SimulatedMerchant(), merchant="Ashgrove Audit LLP", rail="simulated")
    client = TestClient(create_app(token=TOKEN, service=None, reason="runs are off",
                                   billing=billing, max_body_bytes=200))
    response = client.post("/v1/billing/prepare", headers=AUTH, json={
        "dataset_id": "crm-2026", "records": [base_record()]})
    assert response.status_code == 413
    assert response.headers["x-request-id"]
    assert billing.book.summary()["invoices"] == 0


def test_every_response_carries_the_callers_request_id(base_record):
    billing = BillingService(SimulatedMerchant(), merchant="Ashgrove Audit LLP", rail="simulated")
    client = TestClient(create_app(token=TOKEN, service=None, reason="runs are off",
                                   billing=billing))
    generated = client.get("/health")
    assert generated.headers["x-request-id"]
    echoed = client.get("/health", headers={"X-Request-ID": "trace-42"})
    assert echoed.headers["x-request-id"] == "trace-42"


def test_the_showcase_page_is_served_without_a_token():
    billing = BillingService(SimulatedMerchant(), merchant="Ashgrove Audit LLP", rail="simulated")
    client = TestClient(create_app(token=TOKEN, service=None, reason="runs are off",
                                   billing=billing))
    page = client.get("/")
    assert page.status_code == 200
    assert "text/html" in page.headers["content-type"]
    assert "Oversight Twin" in page.text
    assert "Price the sample engagement" in page.text
    assert "demo-2026" in page.text
    assert TOKEN not in page.text


def test_the_edges_limits_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("OVERSIGHT_RATE_LIMIT_PER_MIN", "7")
    monkeypatch.setenv("OVERSIGHT_MAX_BODY_BYTES", "4096")
    assert edge_from_env() == (7, 4096)


def test_an_edge_limit_of_zero_stops_the_service_instead_of_guessing(monkeypatch):
    monkeypatch.setenv("OVERSIGHT_RATE_LIMIT_PER_MIN", "0")
    with pytest.raises(RuntimeError, match="unusable"):
        edge_from_env()


def test_the_served_app_carries_the_configured_edge_limits(monkeypatch):
    import importlib
    from oversight_twin import api
    monkeypatch.setenv("OVERSIGHT_RATE_LIMIT_PER_MIN", "9")
    monkeypatch.setenv("OVERSIGHT_MAX_BODY_BYTES", "12345")
    try:
        reloaded = importlib.reload(api)
        assert reloaded.app.state.meter.per_minute == 9
        assert reloaded.app.state.max_body_bytes == 12345
    finally:
        monkeypatch.undo()
        importlib.reload(api)
