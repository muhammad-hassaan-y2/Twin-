"""The Gemini surface: wire shape, grounded invoice copy, and an assistant under the same rules.

Every test talks to a localhost HTTP fake through the real client. Nothing here proves what a
live Gemini key will answer; it proves what this code sends, accepts and refuses.
"""
from __future__ import annotations

import pytest
from fake_gemini import answer, tool_calls

from oversight_twin.commerce import (BillingBook, SimulatedMerchant, invoice_from, invoice_line)
from oversight_twin.commerce_tools import CommerceTools, review_records
from oversight_twin.llm import (Assistant, GeminiClient, GeminiConfig, ModelUnavailable,
                                function_schemas)

INVOICE_ID = "crm-2026:A1:invoice"


def client_for(fake) -> GeminiClient:
    return GeminiClient(GeminiConfig(api_key=fake.api_key, model="gemini-test",
                                     test_server_url=fake.url))


def ledger(base_record):
    provider = SimulatedMerchant()
    book = BillingBook(provider, merchant="Ashgrove Audit LLP")
    engagements = review_records([base_record()], dataset_id="crm-2026")
    for entry in engagements.values():
        if entry["invoice"] is not None:
            book.prepare(invoice_from(entry["invoice"]))
    return provider, book, CommerceTools(book, engagements)


def sample_invoice():
    return invoice_from({"id": INVOICE_ID, "engagement_id": "crm-2026:A1", "client": "Acme GmbH",
                         "amount_cents": 20_000, "currency": "USD",
                         "description": "Statutory audit - Acme GmbH", "due_in_days": 14})


def test_the_key_is_a_bearer_token_and_never_part_of_the_body(gemini):
    gemini.replies.append(answer("ok"))
    reply = client_for(gemini).chat([{"role": "user", "content": "hello"}])
    assert reply.text == "ok"
    assert gemini.paths == ["/chat/completions"]
    assert gemini.headers[0]["authorization"] == f"Bearer {gemini.api_key}"
    assert gemini.api_key not in gemini.raw_bodies[0]
    assert gemini.bodies[0]["model"] == "gemini-test"
    assert gemini.bodies[0]["messages"] == [{"role": "user", "content": "hello"}]
    assert reply.in_tokens == 12 and reply.out_tokens == 4


def test_the_catalog_is_offered_in_the_openai_function_shape(base_record):
    _, _, tools = ledger(base_record)
    schemas = function_schemas(tools.catalog())
    assert [schema["function"]["name"] for schema in schemas] == [
        "billing_list", "billing_price", "billing_open", "billing_status",
        "billing_capture", "billing_summary"]
    assert all(schema["type"] == "function" for schema in schemas)
    capture = next(s for s in schemas if s["function"]["name"] == "billing_capture")
    assert capture["function"]["parameters"]["required"] == ["invoice_id", "approved_by"]
    assert capture["function"]["parameters"]["additionalProperties"] is False


def test_a_line_with_only_invoice_figures_is_used(gemini):
    gemini.replies.append(answer("Statutory audit for Acme GmbH, due in 14 days."))
    line, route = invoice_line(sample_invoice(), client_for(gemini).writer())
    assert route == "model"
    assert line == "Statutory audit for Acme GmbH, due in 14 days."


def test_a_line_with_an_invented_figure_falls_back(gemini):
    gemini.replies.append(answer("Statutory audit for Acme GmbH: 199.00 in 14 days."))
    line, route = invoice_line(sample_invoice(), client_for(gemini).writer())
    assert route == "rules (the model added a figure)"
    assert line == "Statutory audit - Acme GmbH"


def test_a_model_fault_falls_back_to_the_firms_own_sentence(gemini):
    line, route = invoice_line(sample_invoice(), client_for(gemini).writer())
    assert route == "rules (the model failed)"
    assert line == "Statutory audit - Acme GmbH"


def test_the_assistant_cannot_supply_a_price(gemini, base_record):
    _, book, tools = ledger(base_record)
    gemini.replies.extend([
        tool_calls(("billing_price", {"external_id": "A1", "amount_cents": 1})),
        answer("Priced A1 at the firm's fee."),
    ])
    result = Assistant(client_for(gemini), tools).ask("price A1")
    step = result["steps"][0]
    assert step["allowed"] is True
    assert step["result"]["result"]["amount_cents"] == 20_000
    assert step["result"]["ignored_arguments"] == ["amount_cents"]
    assert book.prepared()[0]["amount_cents"] == 20_000


def test_a_capture_without_an_approver_is_refused_and_moves_nothing(gemini, base_record):
    provider, book, tools = ledger(base_record)
    book.open_prepared(INVOICE_ID)
    gemini.replies.extend([
        tool_calls(("billing_capture", {"invoice_id": INVOICE_ID, "approved_by": "Gemini"})),
        answer("I cannot approve that."),
    ])
    result = Assistant(client_for(gemini), tools).ask("capture it")
    assert result["steps"][0]["allowed"] is False
    assert result["steps"][0]["result"]["ok"] is False
    assert provider.capture_calls == 0
    assert book.status(INVOICE_ID)["state"] == "awaiting_capture"


def test_the_operators_approver_overrides_the_name_the_model_wrote(gemini, base_record):
    provider, book, tools = ledger(base_record)
    book.open_prepared(INVOICE_ID)
    gemini.replies.extend([
        tool_calls(("billing_capture", {"invoice_id": INVOICE_ID, "approved_by": "Gemini"})),
        answer("Captured."),
    ])
    result = Assistant(client_for(gemini), tools,
                       approved_invoices=[INVOICE_ID]).ask("capture it",
                                                           approved_by="H. Shaukat")
    assert result["steps"][0]["allowed"] is True
    assert provider.capture_calls == 1
    assert book.status(INVOICE_ID)["captured_by"] == "H. Shaukat"


def test_a_capture_outside_the_operators_list_is_refused(gemini, base_record):
    # The failing-first control for the allowlist: same approver, same invoice, only the
    # operator's clearance removed. Without the list check this call captures money.
    provider, book, tools = ledger(base_record)
    book.open_prepared(INVOICE_ID)
    gemini.replies.extend([
        tool_calls(("billing_capture", {"invoice_id": INVOICE_ID})),
        answer("I was not cleared to capture that."),
    ])
    result = Assistant(client_for(gemini), tools).ask("capture it", approved_by="H. Shaukat")
    assert result["steps"][0]["allowed"] is False
    assert provider.capture_calls == 0
    assert book.status(INVOICE_ID)["state"] == "awaiting_capture"


def test_a_model_that_never_answers_is_stopped(gemini, base_record):
    _, _, tools = ledger(base_record)
    gemini.replies.extend([tool_calls(("billing_summary", {}))] * 3)
    result = Assistant(client_for(gemini), tools, max_steps=2).ask("loop")
    assert "2 steps" in result["stopped"]
    assert len(result["steps"]) == 2


def test_a_tool_the_book_does_not_have_is_refused(gemini, base_record):
    _, _, tools = ledger(base_record)
    gemini.replies.extend([
        tool_calls(("billing_refund", {"invoice_id": INVOICE_ID})),
        answer("That is not something I can do."),
    ])
    result = Assistant(client_for(gemini), tools).ask("refund it")
    assert result["steps"][0]["result"]["ok"] is False
    assert "not a billing tool" in result["steps"][0]["result"]["refused"]


def test_an_endpoint_failure_is_model_unavailable(gemini):
    with pytest.raises(ModelUnavailable):
        client_for(gemini).chat([{"role": "user", "content": "hi"}])


def test_no_key_means_no_configuration_and_a_repr_without_the_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert GeminiConfig.from_env() is None
    monkeypatch.setenv("GEMINI_API_KEY", "super-secret-key")
    config = GeminiConfig.from_env()
    assert config.model == "gemini-3.5-flash-lite"
    assert "super-secret-key" not in repr(config)
