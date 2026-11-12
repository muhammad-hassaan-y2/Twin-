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
from datetime import datetime, timezone
from threading import RLock
from typing import Any, Callable
from uuid import uuid4

from twin.audit.agents import Case, Finding
from twin.payments.machine import AmbiguousResult, MoneyNotMoved
from twin.payments.paypal import ProviderNotFound, ProviderResult, to_amount

from .store import MemoryStore, Store

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


def invoice_from(data: dict[str, Any]) -> Invoice:
    """Rebuild an invoice from stored JSON. Validation runs again, so bad state cannot slip in."""
    return Invoice(
        id=data["id"], engagement_id=data["engagement_id"], client=data["client"],
        amount_cents=int(data["amount_cents"]), currency=data["currency"],
        description=str(data.get("description", "")), due_in_days=int(data["due_in_days"]),
    )


def price_engagement(external_id: str, case: Case, findings: list[Finding], *,
                     dataset_id: str, currency: str = "USD",
                     due_in_days: int = 14,
                     max_fee_cents: int | None = None) -> tuple[Invoice | None, list[InvoiceIssue]]:
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
    if max_fee_cents is not None and case.audit_fee_cents > max_fee_cents:
        issues.append(InvoiceIssue(
            "fee_above_ceiling", "audit_fee_cents", ERROR,
            f"the fee is above this book's ceiling of {max_fee_cents} minor units"))
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


class InvoiceConflict(ValueError):
    """This invoice id, or this engagement, is already billed on terms that differ."""


@dataclass
class BillingBook:
    """One merchant's invoices: one PayPal order per invoice, one capture per order.

    Every write is a compare-and-set against the store, so two workers can hold the same
    invoice without either silently overwriting what the other already did: a stale worker's
    capture finds the row already captured and returns the row that captured it, approver and
    all. A provider read is always by the stored order id, because an idempotency-key map in
    process memory is exactly what a restart loses.
    """

    transport: object
    merchant: str
    currency: str = "USD"
    due_in_days: int = 14
    store: Store | None = None
    max_invoice_cents: int | None = None
    _entries: dict[str, dict[str, Any]] = field(init=False, default_factory=dict)
    _invoices: dict[str, Invoice] = field(init=False, default_factory=dict)
    _conflicts: dict[str, dict[str, Any]] = field(init=False, default_factory=dict)
    _prepared: dict[str, Invoice] = field(init=False, default_factory=dict)
    _lock: object = field(init=False, default_factory=RLock)

    def __post_init__(self) -> None:
        if not isinstance(self.merchant, str) or not self.merchant.strip():
            raise ValueError("a bill needs a named merchant, never a guess")
        if not re.fullmatch(r"[A-Z]{3}", self.currency):
            raise ValueError("currency must be a three-letter code")
        if self.max_invoice_cents is not None and self.max_invoice_cents <= 0:
            raise ValueError("an invoice ceiling must be a positive number of minor units")
        self.merchant = self.merchant.strip()
        self.store = self.store or MemoryStore()

    def prepare(self, invoice: Invoice) -> dict[str, Any]:
        """Hold a priced invoice without touching the provider. Opening is a separate act.

        Re-preparing the same terms is a no-op. Re-preparing an id with *different* terms, or
        pricing a second invoice for an engagement this book already bills, is refused: an
        invoice that changes after it was priced is how a client pays a number nobody approved.
        """
        with self._lock:
            self._reload()
            if invoice.currency != self.currency:
                raise ValueError("one book keeps one currency for its settlements")
            if self.max_invoice_cents is not None \
                    and invoice.amount_cents > self.max_invoice_cents:
                raise ValueError(f"this book will not bill more than {self.max_invoice_cents} "
                                 "minor units on one invoice")
            known = self._invoices.get(invoice.id)
            if known is not None and known != invoice:
                note = "terms changed under an invoice id this book already priced"
                self._conflict(invoice, note)
                raise InvoiceConflict(note)
            holder = next((other.id for other in self._invoices.values()
                           if other.engagement_id == invoice.engagement_id
                           and other.id != invoice.id), None)
            if holder is not None:
                note = f"another invoice ({holder}) already bills this engagement"
                self._conflict(invoice, note)
                raise InvoiceConflict(note)
            self._prepared[invoice.id] = invoice
            self._invoices[invoice.id] = invoice
            self.store.save_invoice(self.merchant, invoice.as_dict())
            return invoice.as_dict()

    def prepared(self) -> list[dict[str, Any]]:
        with self._lock:
            self._reload()
            return [invoice.as_dict() for invoice in self._prepared.values()]

    def open_prepared(self, invoice_id: str, *, writer: Writer | None = None,
                      actor: str = "", request_id: str = "") -> dict[str, Any]:
        """Open an invoice this book priced. An id it never priced is refused, not guessed."""
        with self._lock:
            self._reload()
            invoice = self._prepared.get(invoice_id)
            if invoice is None:
                raise KeyError(invoice_id)
            return self._open(invoice, writer, actor=actor, request_id=request_id)

    def open(self, invoice: Invoice, *, writer: Writer | None = None,
             actor: str = "", request_id: str = "") -> dict[str, Any]:
        """Create the order once for this invoice, and remember it before anything else."""
        with self._lock:
            return self._open(invoice, writer, actor=actor, request_id=request_id)

    def _open(self, invoice: Invoice, writer: Writer | None, *,
              actor: str = "", request_id: str = "") -> dict[str, Any]:
        self._reload()
        if invoice.currency != self.currency:
            raise ValueError("one book keeps one currency for its settlements")
        known = self._invoices.get(invoice.id)
        if known is not None and known != invoice:
            return self._conflict(invoice, "terms changed under an invoice id this book already priced")
        if any(other.engagement_id == invoice.engagement_id and other.id != invoice.id
               for other in self._invoices.values()):
            return self._conflict(invoice, "another invoice already bills this engagement")
        entry = self._refresh(invoice.id)
        if entry is not None:
            if entry["state"] != UNKNOWN:
                return dict(entry)
            # The last attempt's outcome was lost. Read the order we stored, if we stored one;
            # with no order id the create itself is ambiguous and PayPal's request id makes a
            # retry safe, but a second order is never raised for an order we already have.
            reconciled = self._reconcile(entry, actor=actor, request_id=request_id)
            if reconciled is not None:
                return reconciled
            if entry.get("order_id"):
                return dict(entry)

        line, route = invoice_line(invoice, writer)
        try:
            order = self.transport.create_order(invoice.id, invoice.amount_cents, self.merchant,
                                                invoice.currency)
        except AmbiguousResult as error:
            return self._store(invoice, line, route, state=UNKNOWN, order_id="",
                               note=f"order creation outcome unknown: {error}; retry open, "
                                    "never raise a second order",
                               actor=actor, request_id=request_id, event="order_unknown")
        except MoneyNotMoved as error:
            return self._store(invoice, line, route, state=FAILED, order_id="",
                               note=f"the provider refused the order: {error}",
                               actor=actor, request_id=request_id, event="order_failed")
        order_id = str(order.get("id") or "")
        if not order_id:
            return self._store(invoice, line, route, state=FAILED, order_id="",
                               note="the provider returned no order id",
                               actor=actor, request_id=request_id, event="order_failed")
        state = _PROVIDER_STATES.get(str(order.get("status", "")).upper(), AWAITING_BUYER)
        return self._store(invoice, line, route, state=state, order_id=order_id,
                           approval_url=_approval_url(order),
                           note="created; waiting for the buyer" if state == AWAITING_BUYER else "",
                           actor=actor, request_id=request_id, event="order_opened")

    def capture(self, invoice_id: str, *, approved_by: str,
                actor: str = "", request_id: str = "") -> dict[str, Any]:
        """Capture a buyer-approved order, once, on a named person's instruction."""
        with self._lock:
            return self._capture(invoice_id, approved_by, actor=actor, request_id=request_id)

    def _capture(self, invoice_id: str, approved_by: str, *,
                 actor: str = "", request_id: str = "") -> dict[str, Any]:
        if not isinstance(approved_by, str) or not approved_by.strip():
            raise ValueError("a capture needs the name of the person who approved it")
        self._reload()
        conflict = self._conflicts.get(invoice_id)
        if conflict is not None:
            return dict(conflict)
        entry = self._refresh(invoice_id)
        if entry is None:
            raise KeyError(invoice_id)
        if entry["state"] in (CAPTURED, FAILED):
            return dict(entry)
        if not entry.get("order_id"):
            raise ValueError("this invoice has no order yet; open it before capturing")

        try:
            read = self._lookup(entry)
        except MoneyNotMoved as error:
            # The read itself was refused (a rejected credential, say). Nothing moved and
            # nothing is known; leave the invoice as it is so a later capture can proceed.
            return self._advance(entry, entry["state"], actor=actor, request_id=request_id,
                                 event="capture_unknown",
                                 note=f"the provider refused the status read: {error}")
        provider = str((read.raw or {}).get("status", "")).upper()
        if provider == "COMPLETED":
            return self._finish(entry, CAPTURED, read.reference or entry["order_id"], approved_by,
                                actor=actor, request_id=request_id, event="captured",
                                note="the provider already reports COMPLETED; no second charge")
        if provider not in _PROVIDER_STATES:
            return self._advance(entry, entry["state"], actor=actor, request_id=request_id,
                                 event="capture_unknown",
                                 note="the provider did not report a state this book recognises; "
                                      "reconcile from the provider, never by charging again")
        if provider != "APPROVED":
            return self._advance(entry, entry["state"], actor=actor, request_id=request_id,
                                 event="capture_refused", state=AWAITING_BUYER,
                                 note="the buyer has not approved this order yet")

        self._record("capture_attempted", invoice_id, actor=actor, request_id=request_id,
                     approved_by=approved_by.strip(), order_id=entry["order_id"])
        try:
            result = self.transport.capture_order(entry["order_id"], invoice_id)
        except AmbiguousResult as error:
            return self._finish(entry, UNKNOWN, None, approved_by,
                                actor=actor, request_id=request_id, event="capture_unknown",
                                note=f"capture outcome unknown: {error}; reconcile, do not retry")
        except MoneyNotMoved as error:
            # A 409 can mean "already captured" and a 422 "not approved". Read the truth once.
            again = self._lookup(entry)
            if str((again.raw or {}).get("status", "")).upper() == "COMPLETED":
                return self._finish(entry, CAPTURED, again.reference or entry["order_id"],
                                    approved_by, actor=actor, request_id=request_id,
                                    event="captured",
                                    note="the provider reports COMPLETED; no second charge")
            return self._finish(entry, FAILED, None, approved_by,
                                actor=actor, request_id=request_id, event="capture_refused",
                                note=f"capture refused: {error}")

        if result.status == "completed":
            return self._finish(entry, CAPTURED, result.reference or entry["order_id"],
                                approved_by, actor=actor, request_id=request_id, event="captured")
        if result.status in (AWAITING_BUYER, AWAITING_CAPTURE, "pending"):
            return self._advance(entry, entry["state"], actor=actor, request_id=request_id,
                                 event="capture_pending", state=AWAITING_CAPTURE,
                                 note="the provider has not completed the capture")
        if result.status == UNKNOWN:
            return self._finish(entry, UNKNOWN, None, approved_by,
                                actor=actor, request_id=request_id, event="capture_unknown",
                                note="the provider returned an unknown outcome; reconcile")
        return self._finish(entry, FAILED, None, approved_by,
                            actor=actor, request_id=request_id, event="capture_refused",
                            note=f"the provider refused the capture ({result.status})")

    def status(self, invoice_id: str, *, actor: str = "", request_id: str = "") -> dict[str, Any]:
        """Read the provider's view of a known order without moving anything."""
        with self._lock:
            return self._read(invoice_id, actor=actor, request_id=request_id)

    def _read(self, invoice_id: str, *, actor: str = "", request_id: str = "") -> dict[str, Any]:
        self._reload()
        conflict = self._conflicts.get(invoice_id)
        if conflict is not None:
            return dict(conflict)
        entry = self._refresh(invoice_id)
        if entry is None:
            raise KeyError(invoice_id)
        if entry["state"] in (CAPTURED, FAILED) or not entry["order_id"]:
            return dict(entry)
        read = self._lookup(entry)
        provider = str((read.raw or {}).get("status", "")).upper()
        state = _PROVIDER_STATES.get(provider)
        if state is None:
            return self._advance(entry, entry["state"], actor=actor, request_id=request_id,
                                 event="reconcile_failed",
                                 note="the provider did not report a state this book recognises")
        if state == entry["state"]:
            return dict(entry)
        fields: dict[str, Any] = {"state": state}
        if state == CAPTURED:
            fields["provider_ref"] = read.reference or entry["order_id"]
            fields["note"] = ("captured" if entry.get("captured_by")
                              else "the provider reports COMPLETED; this book has no record of "
                                   "who approved it")
        return self._advance(entry, entry["state"], actor=actor, request_id=request_id,
                             event="reconciled", **fields)

    def events(self, invoice_id: str | None = None) -> list[dict[str, Any]]:
        """The invoice's ledger, in the order the facts happened."""
        with self._lock:
            return self.store.events(self.merchant, invoice_id)

    def summary(self) -> dict[str, Any]:
        """What the book says: billed, collected, still owed, and what needs a person."""
        with self._lock:
            self._reload()
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
        with self._lock:
            self._reload()
            return ([dict(entry) for entry in self._entries.values()]
                    + [dict(entry) for entry in self._conflicts.values()])

    def _store(self, invoice: Invoice, line: str, route: str, *, state: str, order_id: str,
               note: str = "", approval_url: str = "", actor: str = "", request_id: str = "",
               event: str = "") -> dict[str, Any]:
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
        self.store.save_entry(self.merchant, entry)
        # The store refuses to overwrite a row the provider has finished with, so what comes
        # back is the truth, not necessarily what this worker tried to write.
        authoritative = self.store.load_entry(self.merchant, invoice.id) or entry
        self._entries[invoice.id] = authoritative
        self._invoices.setdefault(invoice.id, invoice)
        if authoritative == entry and event:
            self._record(event, invoice.id, actor=actor, request_id=request_id,
                         state=state, order_id=order_id, note=note)
        return dict(authoritative)

    def _finish(self, entry: dict[str, Any], state: str, reference: str | None,
                approved_by: str, *, note: str = "", actor: str = "", request_id: str = "",
                event: str = "") -> dict[str, Any]:
        prior = entry["state"]
        fields: dict[str, Any] = {
            "state": state,
            "provider_ref": reference,
            "captured_by": approved_by.strip() if state == CAPTURED else "",
            "note": note or ("captured" if state == CAPTURED else entry.get("note", "")),
        }
        return self._advance(entry, prior, actor=actor, request_id=request_id, event=event,
                             **fields)

    def _advance(self, entry: dict[str, Any], prior: str, *, actor: str = "",
                 request_id: str = "", event: str = "", **fields: Any) -> dict[str, Any]:
        """Write the next state only if the row still holds `prior`; else report what won."""
        entry.update(fields)
        invoice_id = entry["invoice"]["id"]
        if not self.store.update_entry(self.merchant, entry, expected=(prior,)):
            stored = self.store.load_entry(self.merchant, invoice_id)
            if stored is None:
                raise KeyError(invoice_id)
            self._entries[invoice_id] = stored
            return dict(stored)
        self._entries[invoice_id] = entry
        if event:
            self._record(event, invoice_id, actor=actor, request_id=request_id,
                         state=entry["state"], order_id=entry.get("order_id", ""),
                         note=entry.get("note", ""))
        return dict(entry)

    def _lookup(self, entry: dict[str, Any]):
        """Read the provider by the order id we stored; a key map dies with the process."""
        order_id = str(entry.get("order_id") or "")
        read_order = getattr(self.transport, "lookup_order", None)
        if order_id and callable(read_order):
            return read_order(order_id)
        return self.transport.lookup(entry["invoice"]["id"])

    def _reconcile(self, entry: dict[str, Any], *, actor: str = "",
                   request_id: str = "") -> dict[str, Any] | None:
        read = self._lookup(entry)
        state = _PROVIDER_STATES.get(str((read.raw or {}).get("status", "")).upper())
        if state is None or state == entry["state"]:
            return None
        fields: dict[str, Any] = {"state": state}
        if read.reference:
            fields["provider_ref"] = read.reference
        if state == CAPTURED:
            fields["note"] = ("the provider reports COMPLETED; this book has no record of who "
                              "approved it" if not entry.get("captured_by") else "captured")
        else:
            fields["note"] = "reconciled from the provider"
        return self._advance(entry, entry["state"], actor=actor, request_id=request_id,
                             event="reconciled", **fields)

    def _record(self, kind: str, invoice_id: str, *, actor: str = "", request_id: str = "",
                **details: Any) -> None:
        self.store.append_event(self.merchant, {
            "event_id": uuid4().hex,
            "invoice_id": invoice_id,
            "kind": kind,
            "at": datetime.now(timezone.utc).isoformat(timespec="microseconds"),
            "actor": actor,
            "request_id": request_id,
            **details,
        })

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
        self.store.save_conflict(self.merchant, entry)
        self._record("conflict", invoice.id, note=note)
        return dict(entry)

    def _refresh(self, invoice_id: str) -> dict[str, Any] | None:
        """Read one invoice's authoritative row, so a stale cache cannot overwrite a payment."""
        stored = self.store.load_entry(self.merchant, invoice_id)
        if stored is not None:
            self._entries[invoice_id] = stored
        return stored

    def _reload(self) -> None:
        """Rebuild from the store. Reads are cheap; believing a stale payment state is not."""
        snapshot = self.store.load(self.merchant)
        self._prepared = {row["id"]: invoice_from(row) for row in snapshot.invoices}
        self._entries = {}
        # The entry carries the client-facing line as its description; the priced invoice
        # record keeps the terms, and a replay must compare against those.
        self._invoices = dict(self._prepared)
        self._conflicts = {}
        for stored in snapshot.entries:
            invoice_id = stored["invoice"]["id"]
            self._entries[invoice_id] = stored
            self._invoices.setdefault(invoice_id, invoice_from(stored["invoice"]))
        for stored in snapshot.conflicts:
            self._conflicts[stored["invoice"]["id"]] = stored


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
        return _provider_view(order)

    def lookup_order(self, order_id: str) -> ProviderResult:
        """The restart path: find the order by the id the book stored, not by a key map."""
        for order in self.orders.values():
            if order["id"] == order_id:
                return _provider_view(order)
        return ProviderResult(status="unknown", raw={})


def _provider_view(order: dict[str, Any]) -> ProviderResult:
    status = "completed" if order["status"] == "COMPLETED" else "pending"
    return ProviderResult(status=status, reference=order["id"], raw=dict(order))
