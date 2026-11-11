"""The billing actions an AI assistant is allowed to take, and the ones it is not.

The model can look, price, open and read. It cannot supply an amount: `billing_price` takes an
engagement id and prices it from the firm's own review, so a model that asks for a different
number is ignored and told so. It cannot capture without the name of the person who approved
the payment, because an assistant that can approve its own spending is not a control.

The schemas are plain JSON Schema so any agent framework - including PayPal's Agent Toolkit -
can expose them as tools. The dispatcher is the authority, not the schema: every argument is
checked here, because a schema is advice a model can ignore.
"""
from __future__ import annotations

from typing import Any, Callable

from twin.audit.agents import Firm, Priors

from .commerce import BillingBook, Invoice, price_engagement
from .pipeline import ERROR, WARNING, parse_record, quality_issues

TOOLS: tuple[dict[str, Any], ...] = (
    {
        "name": "billing_list",
        "description": "List the engagements this book can bill, with quality and review summary.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "billing_price",
        "description": ("Price one reviewed engagement into an invoice. The server sets the amount "
                        "from the firm's review; an assistant cannot supply or change it."),
        "input_schema": {
            "type": "object",
            "properties": {"external_id": {"type": "string"}},
            "required": ["external_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "billing_open",
        "description": "Create the PayPal order for an invoice this book priced.",
        "input_schema": {
            "type": "object",
            "properties": {"invoice_id": {"type": "string"}},
            "required": ["invoice_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "billing_status",
        "description": "Read the provider's current state for an opened invoice.",
        "input_schema": {
            "type": "object",
            "properties": {"invoice_id": {"type": "string"}},
            "required": ["invoice_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "billing_capture",
        "description": ("Capture a buyer-approved payment. Requires the name of the person who "
                        "approved it; an assistant may not approve on its own."),
        "input_schema": {
            "type": "object",
            "properties": {
                "invoice_id": {"type": "string"},
                "approved_by": {"type": "string"},
            },
            "required": ["invoice_id", "approved_by"],
            "additionalProperties": False,
        },
    },
    {
        "name": "billing_summary",
        "description": "Billed, collected, outstanding and what still needs a person.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
)

_ARGUMENTS = {
    "billing_list": (),
    "billing_price": ("external_id",),
    "billing_open": ("invoice_id",),
    "billing_status": ("invoice_id",),
    "billing_capture": ("invoice_id", "approved_by"),
    "billing_summary": (),
}


def review_records(records: list[dict[str, Any]], *, dataset_id: str,
                   priors: Priors | None = None, firm: Firm | None = None,
                   currency: str = "USD",
                   due_in_days: int = 14) -> dict[str, dict[str, Any]]:
    """Parse, check and review each row, and price it when the firm has something to sell."""
    priors = priors or Priors.load()
    firm = firm or Firm(priors)
    engagements: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(records, start=1):
        external_id, case, issues = parse_record(row, priors=priors)
        key = external_id or f"(unnamed {index})"
        entry: dict[str, Any] = {
            "external_id": key,
            "client": getattr(case, "client", "") if case is not None else "",
            "fee_cents": getattr(case, "audit_fee_cents", 0) if case is not None else 0,
            "quality": "blocked",
            "issues": [issue.as_dict() for issue in issues],
            "verdicts": {},
            "invoice": None,
        }
        if key in engagements:
            entry["issues"].append({"code": "duplicate_external_id", "field": "external_id",
                                    "severity": ERROR, "message": "this id appears twice"})
            engagements[key] = entry
            continue
        if case is None:
            engagements[key] = entry
            continue
        issues.extend(quality_issues(case, priors))
        entry["issues"] = [issue.as_dict() for issue in issues]
        if any(issue.severity == ERROR for issue in issues):
            engagements[key] = entry
            continue
        findings = firm.review(case)
        entry["verdicts"] = {verdict: sum(1 for f in findings if f.verdict == verdict)
                             for verdict in ("clear", "hold", "breach", "silent")}
        invoice, invoice_issues = price_engagement(external_id, case, findings,
                                                   dataset_id=dataset_id, currency=currency,
                                                   due_in_days=due_in_days)
        entry["issues"] = [issue.as_dict() for issue in issues + invoice_issues]
        entry["quality"] = ("review" if any(issue.severity == WARNING
                                            for issue in issues + invoice_issues) else "verified")
        entry["invoice"] = invoice.as_dict() if invoice is not None else None
        engagements[key] = entry
    return engagements


class CommerceTools:
    """A dispatcher over one book, for an assistant that must not be trusted with figures."""

    def __init__(self, book: BillingBook, engagements: dict[str, dict[str, Any]]) -> None:
        self.book = book
        self.engagements = engagements

    def catalog(self) -> list[dict[str, Any]]:
        return [dict(tool) for tool in TOOLS]

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = dict(arguments or {})
        if name not in _ARGUMENTS:
            return {"ok": False, "refused": f"{name!r} is not a billing tool"}
        ignored = sorted(set(arguments) - set(_ARGUMENTS[name]))
        try:
            result = getattr(self, f"_{name.removeprefix('billing_')}")(arguments)
        except KeyError as error:
            return {"ok": False, "refused": f"nothing was priced under {error.args[0]!r}"}
        except ValueError as error:
            return {"ok": False, "refused": str(error)}
        if not result.get("ok"):
            return result
        result["ignored_arguments"] = ignored
        return result

    # ------------------------------------------------------------------ tools

    def _list(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "result": list(self.engagements.values())}

    def _price(self, arguments: dict[str, Any]) -> dict[str, Any]:
        external_id = str(arguments.get("external_id", "")).strip()
        entry = self.engagements.get(external_id)
        if entry is None:
            return {"ok": False, "refused": f"no engagement {external_id!r} in this batch"}
        if entry["invoice"] is None:
            return {"ok": False, "refused": "this engagement cannot be billed",
                    "issues": entry["issues"]}
        invoice = Invoice(
            id=entry["invoice"]["id"], engagement_id=entry["invoice"]["engagement_id"],
            client=entry["invoice"]["client"], amount_cents=entry["invoice"]["amount_cents"],
            currency=entry["invoice"]["currency"],
            description=entry["invoice"]["description"],
            due_in_days=entry["invoice"]["due_in_days"],
        )
        self.book.prepare(invoice)
        return {"ok": True, "result": dict(entry["invoice"]), "issues": entry["issues"]}

    def _open(self, arguments: dict[str, Any]) -> dict[str, Any]:
        invoice_id = str(arguments.get("invoice_id", "")).strip()
        entry = self.book.open_prepared(invoice_id)
        return {"ok": True, "result": entry}

    def _status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        invoice_id = str(arguments.get("invoice_id", "")).strip()
        return {"ok": True, "result": self.book.status(invoice_id)}

    def _capture(self, arguments: dict[str, Any]) -> dict[str, Any]:
        approved_by = str(arguments.get("approved_by", "")).strip()
        if not approved_by:
            return {"ok": False,
                    "refused": ("a named person must approve the capture; an assistant cannot "
                                "approve its own spending")}
        invoice_id = str(arguments.get("invoice_id", "")).strip()
        return {"ok": True, "result": self.book.capture(invoice_id, approved_by=approved_by)}

    def _summary(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "result": self.book.summary()}
