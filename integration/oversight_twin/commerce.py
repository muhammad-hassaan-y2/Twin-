"""Client billing on PayPal: price an audited engagement, collect once, reconcile.

The firm sells a service. This module is the seller's side of that sale: an engagement that
survived the review is priced into an invoice, the invoice becomes a PayPal order, and money
only moves after the buyer approves and a named person asks for the capture. Two things are
deliberately separate from the agent-fee hub: here the merchant is the firm and the payer is
its client, and the guards that matter are invoice integrity and settlement integrity, not an
agent's spending limit.

The states exist because a payment API has more than two outcomes:

* `awaiting_buyer`  - the order exists, the payer has not approved it.
* `awaiting_capture`- the payer approved; nobody has captured it yet.
* `captured`        - the provider says COMPLETED. This is the only paid state.
* `unknown`         - the reply was lost. Read the known order; never create a second one.
* `failed`          - the provider refused the call.
* `conflict`        - this invoice id was opened before with different terms.

A replayed open returns the order already held for that invoice, and a capture of a captured
invoice returns the receipt it already has. Amounts are never taken from model output: the
price comes from the firm's reviewed case, and model text is only accepted when every number
in it can be traced to that invoice.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from twin.audit.agents import Case, Finding
from twin.payments.machine import AmbiguousResult, MoneyNotMoved
from twin.payments.paypal import ProviderNotFound, ProviderResult, to_amount

ERROR, WARNING = "error", "warning"

AWAITING_BUYER = "awaiting_buyer"
AWAITING_CAPTURE = "awaiting_capture"
CAPTURED = "captured"
UNKNOWN = "unknown"
FAILED = "failed"
CONFLICT = "conflict"

_PROVIDER_STATES = {
    "CREATED": AWAITING_BUYER,
    "APPROVED": AWAITING_CAPTURE,
    "COMPLETED": CAPTURED,
    "VOIDED": FAILED,
    "DECLINED": FAILED,
}


@dataclass(frozen=True)
class InvoiceIssue:
    """Why an engagement cannot be billed, or what a person should look at before it is."""

    code: str
    field: str
    severity: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "severity": self.severity,
                "message": self.message}


@dataclass(frozen=True)
class Invoice:
    """A bill for one engagement. The amount came from the firm's review, not from a model."""

    id: str
    engagement_id: str
    client: str
    amount_cents: int
    currency: str = "USD"
    description: str = ""
    due_in_days: int = 14

    def __post_init__(self) -> None:
        if not all(isinstance(value, str) and value.strip()
                   for value in (self.id, self.engagement_id, self.client)):
            raise ValueError("an invoice needs an id, an engagement and a client")
        if type(self.amount_cents) is not int or self.amount_cents <= 0:
            raise ValueError("an invoice amount must be positive integer minor units")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("currency must be a three-letter code")
        if self.due_in_days <= 0:
            raise ValueError("an invoice needs a positive payment term")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "engagement_id": self.engagement_id, "client": self.client,
            "amount_cents": self.amount_cents, "currency": self.currency,
            "description": self.description, "due_in_days": self.due_in_days,
            "amount": to_amount(self.amount_cents, self.currency),
        }


def price_engagement(external_id: str, case: Case, findings: list[Finding], *,
                     dataset_id: str, currency: str = "USD",
                     due_in_days: int = 14) -> tuple[Invoice | None, list[InvoiceIssue]]:
    """Turn a reviewed engagement into a bill, or into the reasons it may not be billed.

    A breach finding means a statute forbids the work, so there is nothing lawful to sell. An
    unreviewed engagement is not priced at all: the firm's own review is the thing being sold.
    A hold is a warning, not a refusal - a person may still bill, but the open question is on the
    invoice record where a reader will see it.
    """
    issues: list[InvoiceIssue] = []
    if not isinstance(external_id, str) or not external_id.strip():
        issues.append(InvoiceIssue("missing_engagement", "external_id", ERROR,
                                   "an invoice cannot be raised without an engagement id"))
    if not findings:
        issues.append(InvoiceIssue("not_reviewed", "findings", ERROR,
                                   "an engagement no desk reviewed cannot be priced"))
    if case.audit_fee_cents <= 0:
        issues.append(InvoiceIssue("zero_fee", "audit_fee_cents", ERROR,
                                   "there is no fee to bill"))
    breaches = sorted({finding.role for finding in findings if finding.verdict == "breach"})
    if breaches:
        issues.append(InvoiceIssue("engagement_forbidden", "findings", ERROR,
                                   "a statute forbids this work, so it cannot be sold ("
                                   + ", ".join(breaches) + ")"))
    holds = sorted({finding.role for finding in findings if finding.verdict == "hold"})
    if holds:
        issues.append(InvoiceIssue("open_questions", "findings", WARNING,
                                   "a person must resolve: " + ", ".join(holds)))
    if not case.client.strip():
        issues.append(InvoiceIssue("missing_client", "client", ERROR,
                                   "the client is not named on the file"))
    if any(issue.severity == ERROR for issue in issues):
        return None, issues
    invoice = Invoice(
        id=f"{dataset_id}:{external_id.strip()}:invoice",
        engagement_id=f"{dataset_id}:{external_id.strip()}",
        client=case.client,
        amount_cents=case.audit_fee_cents,
        currency=currency,
        description=f"Statutory audit - {case.client}",
        due_in_days=due_in_days,
    )
    return invoice, issues


# --------------------------------------------------------------------- the invoice line


def _numbers(text: str) -> list[str]:
    return [token.replace(",", "") for token in re.findall(r"\d+(?:[.,]\d+)?", text)]


def grounded(text: str, invoice: Invoice) -> bool:
    """Whether every number in the text came from the invoice itself.

    Ids and the client name are removed first, because "A1" and "GmbH 24" are names rather than
    amounts. What survives must be the amount in minor or major units, or the payment term.
    """
    if not text.strip():
        return False
    stripped = text
    for token in (invoice.id, invoice.engagement_id, invoice.client):
        stripped = stripped.replace(token, " ")
    allowed = {
        str(invoice.amount_cents),
        to_amount(invoice.amount_cents, invoice.currency).replace(",", ""),
        to_amount(invoice.amount_cents, invoice.currency).split(".")[0].replace(",", ""),
        str(invoice.due_in_days),
    }
    return all(number in allowed for number in _numbers(stripped))


Writer = Callable[[str, dict[str, Any]], str]


def invoice_line(invoice: Invoice, writer: Writer | None = None) -> tuple[str, str]:
    """The line a client reads, and which route wrote it.

    With no writer the sentence is the firm's own. With one, the model may reword it but may not
    add a figure: a reply carrying a number that is not on the invoice is dropped, and the route
    says so rather than hiding the fallback.
    """
    if writer is None:
        return invoice.description, "rules"
    prompt = ("Write one client-facing line for this professional-services invoice. Use only the "
              "facts given; add no amount, rate, date or discount. Facts: " + repr(invoice.as_dict()))
    try:
        text = writer(prompt, invoice.as_dict())
    except Exception:  # noqa: BLE001 - a model fault is a fallback, not a billing failure
        return invoice.description, "rules (the model failed)"
    if not grounded(text, invoice):
        return invoice.description, "rules (the model added a figure)"
    return text.strip(), "model"


# ------------------------------------------------------------------------ the collections book


@dataclass
class BillingBook:
    """One merchant's invoices: one PayPal order per invoice, one capture per order."""

    transport: object
    merchant: str
    currency: str = "USD"
    due_in_days: int = 14
    _entries: dict[str, dict[str, Any]] = field(init=False, default_factory=dict)
    _invoices: dict[str, Invoice] = field(init=False, default_factory=dict)
    _conflicts: dict[str, dict[str, Any]] = field(init=False, default_factory=dict)
    _prepared: dict[str, Invoice] = field(init=False, default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.merchant, str) or not self.merchant.strip():
            raise ValueError("a bill needs a named merchant, never a guess")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("currency must be a three-letter code")
        self.merchant = self.merchant.strip()

    def prepare(self, invoice: Invoice) -> dict[str, Any]:
        """Hold a priced invoice without touching the provider. Opening is a separate act."""
        if invoice.currency != self.currency:
            raise ValueError("one book keeps one currency for its settlements")
        self._prepared[invoice.id] = invoice
        return invoice.as_dict()

    def prepared(self) -> list[dict[str, Any]]:
        return [invoice.as_dict() for invoice in self._prepared.values()]

    def open_prepared(self, invoice_id: str, *, writer: Writer | None = None) -> dict[str, Any]:
        """Open an invoice this book priced. An id it never priced is refused, not guessed."""
        invoice = self._prepared.get(invoice_id)
        if invoice is None:
            raise KeyError(invoice_id)
        return self.open(invoice, writer=writer)

    def open(self, invoice: Invoice, *, writer: Writer | None = None) -> dict[str, Any]:
        """Create the order once for this invoice, and remember it before anything else."""
        if invoice.currency != self.currency:
            raise ValueError("one book keeps one currency for its settlements")
        known = self._invoices.get(invoice.id)
        if known is not None and known != invoice:
            return self._conflict(invoice, "terms changed under an invoice id this book already priced")
        if invoice.engagement_id in {inv.engagement_id for inv in self._invoices.values()} \
                and invoice.id not in self._invoices:
            return self._conflict(invoice, "another invoice already bills this engagement")
        entry = self._entries.get(invoice.id)
        if entry is not None and entry["state"] != UNKNOWN:
            return dict(entry)

        line, route = invoice_line(invoice, writer)
        try:
            order = self.transport.create_order(invoice.id, invoice.amount_cents, self.merchant,
                                                invoice.currency)
        except AmbiguousResult as error:
            return self._store(invoice, line, route, state=UNKNOWN, order_id="",
                               note=f"order creation outcome unknown: {error}; retry open, "
                                    "never raise a second order")
        except MoneyNotMoved as error:
            return self._store(invoice, line, route, state=FAILED, order_id="",
                               note=f"the provider refused the order: {error}")
        order_id = str(order.get("id") or "")
        if not order_id:
            return self._store(invoice, line, route, state=FAILED, order_id="",
                               note="the provider returned no order id")
        state = _PROVIDER_STATES.get(str(order.get("status", "")).upper(), AWAITING_BUYER)
        return self._store(invoice, line, route, state=state, order_id=order_id,
                           approval_url=_approval_url(order),
                           note="created; waiting for the buyer" if state == AWAITING_BUYER else "")

    def capture(self, invoice_id: str, *, approved_by: str) -> dict[str, Any]:
        """Capture a buyer-approved order, once, on a named person's instruction."""
        if not isinstance(approved_by, str) or not approved_by.strip():
            raise ValueError("a capture needs the name of the person who approved it")
        entry = self._entries.get(invoice_id)
        if entry is None:
            raise KeyError(invoice_id)
        if entry["state"] == CAPTURED:
            return dict(entry)
        if entry["state"] in (FAILED, CONFLICT):
            return dict(entry)

        read = self.transport.lookup(invoice_id)
        provider = str((read.raw or {}).get("status", "")).upper()
        if provider == "COMPLETED":
            return self._finish(entry, CAPTURED, read.reference or entry["order_id"], approved_by)
        if provider not in _PROVIDER_STATES:
            entry["note"] = ("the provider did not report a state this book recognises; reconcile"
                             " from the provider, never by charging again")
            return dict(entry)
        if provider != "APPROVED":
            entry.update(state=AWAITING_BUYER,
                         note="the buyer has not approved this order yet")
            return dict(entry)

        try:
            result = self.transport.capture_order(entry["order_id"], invoice_id)
        except AmbiguousResult as error:
            return self._finish(entry, UNKNOWN, None, approved_by,
                                note=f"capture outcome unknown: {error}; reconcile, do not retry")
        except MoneyNotMoved as error:
            # A 409 can mean "already captured" and a 422 "not approved". Read the truth once.
            again = self.transport.lookup(invoice_id)
            if str((again.raw or {}).get("status", "")).upper() == "COMPLETED":
                return self._finish(entry, CAPTURED, again.reference or entry["order_id"],
                                    approved_by)
            return self._finish(entry, FAILED, None, approved_by, note=f"capture refused: {error}")

        if result.status == "completed":
            return self._finish(entry, CAPTURED, result.reference or entry["order_id"],
                                approved_by)
        if result.status in (AWAITING_BUYER, AWAITING_CAPTURE, "pending"):
            entry.update(state=AWAITING_CAPTURE, note="the provider has not completed the capture")
        elif result.status == UNKNOWN:
            return self._finish(entry, UNKNOWN, None, approved_by,
                                note="the provider returned an unknown outcome; reconcile")
        else:
            return self._finish(entry, FAILED, None, approved_by,
                                note=f"the provider refused the capture ({result.status})")
        return dict(entry)

    def status(self, invoice_id: str) -> dict[str, Any]:
        """Read the provider's view of a known order without moving anything."""
        entry = self._entries.get(invoice_id)
        if entry is None:
            raise KeyError(invoice_id)
        if entry["state"] in (CAPTURED, FAILED, CONFLICT) or not entry["order_id"]:
            return dict(entry)
        read = self.transport.lookup(invoice_id)
        provider = str((read.raw or {}).get("status", "")).upper()
        state = _PROVIDER_STATES.get(provider)
        if state is None:
            entry["note"] = "the provider did not report a state this book recognises"
        elif state != entry["state"]:
            entry["state"] = state
            if state == CAPTURED:
                entry["provider_ref"] = read.reference or entry["order_id"]
                entry["note"] = "captured"
        return dict(entry)

    def summary(self) -> dict[str, Any]:
        """What the book says: billed, collected, still owed, and what needs a person."""
        rows = [dict(entry) for entry in self._entries.values()]
        captured = [row for row in rows if row["state"] == CAPTURED]
        billed = sum(row["invoice"]["amount_cents"] for row in rows)
        collected = sum(row["invoice"]["amount_cents"] for row in captured)
        return {
            "merchant": self.merchant,
            "currency": self.currency,
            "invoices": len(rows),
            "billed_cents": billed,
            "collected_cents": collected,
            "outstanding_cents": billed - collected,
            "captured": len(captured),
            "awaiting_buyer": sum(1 for row in rows if row["state"] == AWAITING_BUYER),
            "awaiting_capture": sum(1 for row in rows if row["state"] == AWAITING_CAPTURE),
            "unknown": sum(1 for row in rows if row["state"] == UNKNOWN),
            "failed": sum(1 for row in rows if row["state"] == FAILED),
            "conflicts": len(self._conflicts),
            "clients": sorted({row["invoice"]["client"] for row in rows}),
        }

    def invoices(self) -> list[dict[str, Any]]:
        return ([dict(entry) for entry in self._entries.values()]
                + [dict(entry) for entry in self._conflicts.values()])

    def _store(self, invoice: Invoice, line: str, route: str, *, state: str, order_id: str,
               note: str = "", approval_url: str = "") -> dict[str, Any]:
        entry = {
            "invoice": dict(invoice.as_dict(), description=line),
            "line_route": route,
            "order_id": order_id,
            "approval_url": approval_url,
            "state": state,
            "provider_ref": None,
            "captured_by": "",
            "note": note,
        }
        self._entries[invoice.id] = entry
        self._invoices[invoice.id] = invoice
        return dict(entry)

    def _finish(self, entry: dict[str, Any], state: str, reference: str | None,
                approved_by: str, *, note: str = "") -> dict[str, Any]:
        entry["state"] = state
        entry["provider_ref"] = reference
        entry["captured_by"] = approved_by.strip() if state == CAPTURED else ""
        entry["note"] = note or ("captured" if state == CAPTURED else entry.get("note", ""))
        return dict(entry)

    def _conflict(self, invoice: Invoice, note: str) -> dict[str, Any]:
        entry = {
            "invoice": invoice.as_dict(),
            "line_route": "rules",
            "order_id": "",
            "approval_url": "",
            "state": CONFLICT,
            "provider_ref": None,
            "captured_by": "",
            "note": note,
        }
        self._conflicts[invoice.id] = entry
        return dict(entry)


def _approval_url(order: dict[str, Any]) -> str:
    for link in order.get("links") or ():
        if str(link.get("rel", "")).lower() in {"approve", "payer-action"}:
            return str(link.get("href", ""))
    return ""


class SimulatedMerchant:
    """A local merchant stand-in for demos with no credentials.

    Orders auto-approve and captures complete at once. Nothing here contacts PayPal, moves
    money or proves the live integration; the rail label says so wherever it is used.
    """

    def __init__(self) -> None:
        self.orders: dict[str, dict[str, Any]] = {}
        self.create_calls = 0
        self.capture_calls = 0

    def create_order(self, key: str, amount_cents: int, recipient: str,
                     currency: str = "USD") -> dict[str, Any]:
        self.create_calls += 1
        order = self.orders.get(key)
        if order is None:
            order = {
                "id": f"SIM-{len(self.orders) + 1:06d}", "status": "APPROVED",
                "amount_cents": amount_cents, "currency": currency,
                "links": [{"rel": "approve", "href": f"simulated://pay/{key}"}],
            }
            self.orders[key] = order
        return dict(order)

    def capture_order(self, order_id: str, key: str) -> ProviderResult:
        order = self.orders.get(key)
        if order is None:
            raise ProviderNotFound(order_id)
        if order["status"] == "COMPLETED":
            raise MoneyNotMoved("ORDER_ALREADY_CAPTURED")
        if order["status"] != "APPROVED":
            raise MoneyNotMoved("ORDER_NOT_APPROVED")
        self.capture_calls += 1
        order["status"] = "COMPLETED"
        return ProviderResult(status="completed", reference=order_id, raw=dict(order))

    def lookup(self, key: str) -> ProviderResult:
        order = self.orders.get(key)
        if order is None:
            return ProviderResult(status="unknown", raw={})
        status = "completed" if order["status"] == "COMPLETED" else "pending"
        return ProviderResult(status=status, reference=order["id"], raw=dict(order))
