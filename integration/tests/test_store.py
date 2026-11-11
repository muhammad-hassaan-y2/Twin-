"""Durable book state: a restart must not become a second charge.

The memory-store tests prove the book's logic; the Postgres tests run only when a database is
given through OVERSIGHT_TEST_DATABASE_URL and prove the same behaviour across two store objects
with a real server in between.
"""
from __future__ import annotations

import os
import uuid

import pytest

from oversight_twin.commerce import BillingBook, Invoice, SimulatedMerchant
from oversight_twin.store import MemoryStore, PostgresStore, store_from_env
from twin.payments.paypal import PayPalConfig, PayPalTransport

INVOICE_ID = "crm-2026:A1:invoice"
PG = os.environ.get("OVERSIGHT_TEST_DATABASE_URL", "")
needs_postgres = pytest.mark.skipif(
    not PG, reason="set OVERSIGHT_TEST_DATABASE_URL to run the Postgres store tests")


def invoice() -> Invoice:
    return Invoice(id=INVOICE_ID, engagement_id="crm-2026:A1", client="Acme GmbH",
                   amount_cents=20_000, description="Statutory audit - Acme GmbH")


def book(provider, store=None) -> BillingBook:
    return BillingBook(provider, merchant="Ashgrove Audit LLP", store=store)


def test_the_book_survives_a_restart_and_never_opens_a_second_order():
    provider = SimulatedMerchant()
    store = MemoryStore()
    first = book(provider, store)
    first.prepare(invoice())
    opened = first.open_prepared(INVOICE_ID)

    second = book(provider, store)
    assert second.status(INVOICE_ID)["order_id"] == opened["order_id"]
    again = second.open_prepared(INVOICE_ID)
    assert again["order_id"] == opened["order_id"]
    assert provider.create_calls == 1


def test_a_restart_without_a_store_would_charge_the_client_twice():
    # The negative control for the test above: remove the store and the second book forgets
    # the order it already raised, which is exactly the double charge the store prevents.
    provider = SimulatedMerchant()
    first = book(provider)
    first.prepare(invoice())
    first.open_prepared(INVOICE_ID)

    second = book(provider)
    second.prepare(invoice())
    second.open_prepared(INVOICE_ID)
    assert provider.create_calls == 2


def test_the_approver_and_the_capture_survive_a_restart():
    provider = SimulatedMerchant()
    store = MemoryStore()
    first = book(provider, store)
    first.prepare(invoice())
    first.open_prepared(INVOICE_ID)
    first.capture(INVOICE_ID, approved_by="H. Shaukat")

    second = book(provider, store)
    entry = second.status(INVOICE_ID)
    assert entry["state"] == "captured"
    assert entry["captured_by"] == "H. Shaukat"
    assert second.summary()["collected_cents"] == 20_000


def test_an_unknown_outcome_is_reconciled_after_a_restart(paypal):
    paypal.drop_keys.add(INVOICE_ID)
    transport = PayPalTransport(PayPalConfig(client_id=paypal.client_id, secret=paypal.secret,
                                             test_server_url=paypal.url))
    store = MemoryStore()
    first = book(transport, store)
    first.prepare(invoice())
    assert first.open_prepared(INVOICE_ID)["state"] == "unknown"

    # The reply was lost, but the order exists under this invoice's request id. A new process
    # re-opens the same key and the provider hands back the order it already has.
    second = book(transport, store)
    replayed = second.open_prepared(INVOICE_ID)
    assert replayed["state"] == "awaiting_capture"
    assert replayed["order_id"].startswith("MOCK")
    assert paypal.create_calls == 1
    assert paypal.replays == 1
    assert paypal.captured_cents == 0


def test_a_conflict_is_remembered_too():
    provider = SimulatedMerchant()
    store = MemoryStore()
    first = book(provider, store)
    first.prepare(invoice())
    first.open_prepared(INVOICE_ID)

    changed = Invoice(id=INVOICE_ID, engagement_id="crm-2026:A1", client="Acme GmbH",
                      amount_cents=99_000, description="Statutory audit - Acme GmbH")
    second = book(provider, store)
    second.prepare(changed)
    assert second.open_prepared(INVOICE_ID)["state"] == "conflict"
    assert book(provider, store).summary()["conflicts"] == 1
    assert provider.create_calls == 1


def test_a_new_export_replaces_the_datasets_engagements(base_record):
    from oversight_twin.api import BillingService

    store = MemoryStore()
    service = BillingService(SimulatedMerchant(), merchant="Ashgrove Audit LLP",
                             rail="simulated", store=store)
    service.prepare("crm-2026", [base_record()])
    service.prepare("crm-2026", [base_record(external_id="B2")])

    restarted = BillingService(SimulatedMerchant(), merchant="Ashgrove Audit LLP",
                               rail="simulated", store=store)
    listed = restarted.tool("billing_list", {})
    assert [row["external_id"] for row in listed["result"]] == ["B2"]


def test_no_dsn_means_memory_and_says_so(monkeypatch):
    monkeypatch.delenv("OVERSIGHT_DATABASE_URL", raising=False)
    store, why = store_from_env()
    assert why == ""
    assert store.describe() == {"kind": "memory", "durable": False}


def test_a_dsn_that_is_not_postgres_is_refused(monkeypatch):
    monkeypatch.setenv("OVERSIGHT_DATABASE_URL", "mysql://user:pw@host/db")
    store, why = store_from_env()
    assert store is None
    assert "postgresql://" in why


def test_a_schema_name_must_be_a_plain_identifier():
    with pytest.raises(ValueError):
        PostgresStore("postgresql://u:p@127.0.0.1/db", schema="oversight; DROP SCHEMA public")


def test_an_unreachable_database_fails_the_operation_rather_than_falling_back():
    store = PostgresStore("postgresql://nobody:nothing@127.0.0.1:1/none",
                          schema="oversight", connect_timeout=1)
    with pytest.raises(Exception) as raised:
        store.load("Ashgrove Audit LLP")
    assert "unreachable" in str(raised.value)


# ------------------------------------------------------------------- real PostgreSQL


def _drop(schema: str) -> None:
    import psycopg
    from psycopg import sql
    with psycopg.connect(PG, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
            sql.Identifier(schema)))


@needs_postgres
def test_postgres_keeps_the_book_across_two_store_instances():
    schema = f"t_{uuid.uuid4().hex[:12]}"
    provider = SimulatedMerchant()
    try:
        first = book(provider, PostgresStore(PG, schema=schema))
        first.prepare(invoice())
        opened = first.open_prepared(INVOICE_ID)

        second = book(provider, PostgresStore(PG, schema=schema))
        assert second.status(INVOICE_ID)["order_id"] == opened["order_id"]
        second.capture(INVOICE_ID, approved_by="H. Shaukat")

        third = book(provider, PostgresStore(PG, schema=schema))
        assert third.status(INVOICE_ID)["captured_by"] == "H. Shaukat"
        assert third.summary()["collected_cents"] == 20_000
        assert provider.create_calls == 1
    finally:
        _drop(schema)


@needs_postgres
def test_postgres_refuses_a_state_the_book_does_not_define():
    import psycopg
    from psycopg import sql

    schema = f"t_{uuid.uuid4().hex[:12]}"
    try:
        PostgresStore(PG, schema=schema).load("Ashgrove Audit LLP")
        with psycopg.connect(PG, autocommit=True) as conn:
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute(
                    sql.SQL("INSERT INTO {}.book_entries (merchant, invoice_id, state, entry) "
                            "VALUES (%s, %s, %s, %s)").format(sql.Identifier(schema)),
                    ("merchant", "inv", "paid-ish", '{"invoice": {"id": "inv"}}'))
    finally:
        _drop(schema)


@needs_postgres
def test_postgres_isolates_merchants():
    schema = f"t_{uuid.uuid4().hex[:12]}"
    provider = SimulatedMerchant()
    try:
        store = PostgresStore(PG, schema=schema)
        other = BillingBook(provider, merchant="Another Firm", store=store)
        mine = book(provider, store)
        mine.prepare(invoice())
        mine.open_prepared(INVOICE_ID)
        assert other.summary()["invoices"] == 0
        assert other.invoices() == []
    finally:
        _drop(schema)


@needs_postgres
def test_postgres_engagements_come_back_for_the_assistant(base_record):
    from oversight_twin.api import BillingService

    schema = f"t_{uuid.uuid4().hex[:12]}"
    provider = SimulatedMerchant()
    try:
        service = BillingService(provider, merchant="Ashgrove Audit LLP", rail="simulated",
                                 store=PostgresStore(PG, schema=schema))
        service.prepare("crm-2026", [base_record()])

        restarted = BillingService(provider, merchant="Ashgrove Audit LLP", rail="simulated",
                                   store=PostgresStore(PG, schema=schema))
        listed = restarted.tool("billing_list", {})
        assert [row["external_id"] for row in listed["result"]] == ["A1"]
        priced = restarted.tool("billing_price", {"external_id": "A1"})
        assert priced["result"]["amount_cents"] == 20_000

        service.prepare("crm-2026", [base_record(external_id="B2")])
        replaced = BillingService(provider, merchant="Ashgrove Audit LLP", rail="simulated",
                                  store=PostgresStore(PG, schema=schema))
        assert [row["external_id"] for row in replaced.tool("billing_list", {})["result"]] == ["B2"]
    finally:
        _drop(schema)
