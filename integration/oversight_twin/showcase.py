"""The whole system in one command: the gap, the price, the refusal, and the restart.

    python -m oversight_twin.showcase

Every figure below is measured during the run. Nothing here needs a key, a network or a
database, so the transcript is the same on a laptop and in CI; the live rails and the model
are configured separately and are labelled when they are not simulated.
"""
from __future__ import annotations

from .commerce import BillingBook, SimulatedMerchant
from .commerce_tools import CommerceTools, review_records
from .demo import LIMITS, PAYMENTS, settle
from .store import MemoryStore
from swarm_oversight.monitor import Limits
from .bridge import SwarmOversight

MERCHANT = "Ashgrove Audit LLP"
DATASET = "crm-2026"

RECORD = {
    "external_id": "A1", "client": "Acme GmbH", "audit_fee_cents": 20_000,
    "non_audit_fee_cents": 1_000, "is_pie": True, "years_auditing": 3,
    "partner_years": 2, "tender_held": True, "firm_fee_from_client_cents": 1_000,
    "firm_total_fees_cents": 100_000, "kyc_checked_years_ago": 1,
    "non_audit_services": ["tax"], "client_geo": "DE",
    "standard_vat_rate_percent": 19.0, "reduced_vat_rate_percent": 7.0,
    "supply_in_reduced_category": False,
}


def _money(cents: int) -> str:
    return f"{cents / 100:,.2f}"


def act_one() -> None:
    attempted = sum(amount for _, amount, _, _ in PAYMENTS)
    print("1. The gap a per-mandate ceiling cannot see")
    print(f"   {len(PAYMENTS)} mandates, each approved and under its own ceiling, "
          f"{_money(attempted)} in total.")
    print(f"   The principal's bound is {_money(LIMITS.per_payee)} per payee.")
    alone, _ = settle(PAYMENTS)
    guarded, _ = settle(PAYMENTS, SwarmOversight(Limits(
        per_agent=LIMITS.per_agent, per_payee=LIMITS.per_payee, window=LIMITS.window,
        long_window=LIMITS.long_window, merge=LIMITS.merge), freeze=True))
    print(f"   without oversight: {_money(alone)} settles; with it: {_money(guarded)}. "
          f"The {_money(alone - guarded)} difference is the gap.")


def act_two(book: BillingBook, engagements: dict) -> dict:
    print("\n2. Price an engagement from the firm's own review")
    entry = engagements["A1"]
    findings = sum(entry["verdicts"].values())
    print(f"   {findings} findings across the desks: {entry['verdicts']}.")
    invoice = entry["invoice"]
    print(f"   priced at {_money(invoice['amount_cents'])} {invoice['currency']} "
          f"({invoice['id']}), billed from the case file, not from a model.")
    book.prepare(_invoice(invoice))
    return invoice


def act_three(book: BillingBook, engagements: dict, invoice: dict) -> None:
    print("\n3. A model may ask; the dispatcher decides")
    tools = CommerceTools(book, engagements, actor="H. Shaukat", request_id="showcase-run")
    priced = tools.call("billing_price", {"external_id": "A1", "amount_cents": 1})
    print(f"   a model asks to bill 0.01; the server prices "
          f"{_money(priced['result']['amount_cents'])} for the engagement it reviewed "
          f"(ignored arguments: {priced['ignored_arguments']}).")
    opened = tools.call("billing_open", {"invoice_id": invoice["id"]})
    print(f"   order {opened['result']['order_id']} opened: {opened['result']['state']}.")
    refused = tools.call("billing_capture", {"invoice_id": invoice["id"]})
    print(f"   a capture with no approver: refused - {refused['refused']}")
    captured = tools.call("billing_capture", {"invoice_id": invoice["id"],
                                              "approved_by": "H. Shaukat"})
    print(f"   a capture signed by a person: {captured['result']['state']}, "
          f"by {captured['result']['captured_by']}, reference "
          f"{captured['result']['provider_ref']}.")


def act_four(store: MemoryStore, invoice: dict) -> None:
    print("\n4. A restart reads the same book")
    restarted = BillingBook(SimulatedMerchant(), merchant=MERCHANT, store=store)
    again = restarted.open_prepared(invoice["id"], actor="night shift")
    print(f"   new process, same invoice: {again['state']}, order {again['order_id']} "
          "- no second order, no second charge.")
    for event in restarted.events(invoice["id"]):
        actor = event.get("actor") or "system"
        print(f"   {event['at']}  {event['kind']:<18} {actor} "
              f"[{event.get('request_id') or '-'}]")
    summary = restarted.summary()
    print(f"   billed {_money(summary['billed_cents'])}, collected "
          f"{_money(summary['collected_cents'])}, outstanding "
          f"{_money(summary['outstanding_cents'])}.")


def _invoice(data: dict):
    from .commerce import Invoice
    return Invoice(id=data["id"], engagement_id=data["engagement_id"], client=data["client"],
                   amount_cents=data["amount_cents"], currency=data["currency"],
                   description=data["description"], due_in_days=data["due_in_days"])


def main() -> None:
    print("=" * 78)
    print("Oversight Twin - an audited engagement, billed once, under a human's name")
    print("=" * 78 + "\n")
    act_one()
    engagements = review_records([RECORD], dataset_id=DATASET)
    store = MemoryStore()
    book = BillingBook(SimulatedMerchant(), merchant=MERCHANT, store=store)
    invoice = act_two(book, engagements)
    act_three(book, engagements, invoice)
    act_four(store, invoice)
    print("\nServe it:  uvicorn oversight_twin.api:app  ->  http://127.0.0.1:8000/")
    print("Prove it:  python -m pytest -q")


if __name__ == "__main__":
    main()
