"""CRM records in, audited instructions out, and every payment through the PayPal hub.

A record is only audited when it survives parsing and the structural checks below; a record
that contradicts itself is reported and never priced. Every binding desk that clears or asks
for review becomes an instruction, but nothing moves until a person clears it by name. The
hub then applies the principal-wide bound and PayPal is the only rail.
"""
from __future__ import annotations

import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from twin.audit.agents import CLEAR, HOLD, Case, Firm, Priors

from .hub import Agreement, HumanGate, PayPalHub

ERROR = "error"
WARNING = "warning"

_INT_FIELDS = {
    "audit_fee_cents", "non_audit_fee_cents", "years_auditing", "partner_years",
    "firm_fee_from_client_cents", "firm_total_fees_cents", "kyc_checked_years_ago",
    "file_retention_years", "non_audit_years", "months_since_year_end",
    "transparency_kept_years", "years_since_previous",
}
_MONEY_FIELDS = {
    "turnover_eur", "balance_sheet_eur", "employees", "parent_holding_percent",
}
_RATE_FIELDS = {"standard_vat_rate_percent", "reduced_vat_rate_percent"}
_BOOL_FIELDS = {
    "is_pie", "is_group", "tender_held", "previously_audited", "supply_in_reduced_category",
    "transparency_published", "audit_report_issued", "committee_report_issued",
    "sustainability_assurance", "claims_small_undertaking",
}
_STR_FIELDS = {"client", "fee_arrangement", "register_status", "client_geo"}
_INT_LIST_FIELDS = {"prior_audit_fees_cents", "prior_non_audit_fees_cents"}
_STR_LIST_FIELDS = {"non_audit_services", "register_particulars"}
_CASE_FIELDS = set(Case.__dataclass_fields__)

# A CRM export that omits any of these has not given the firm enough to price an engagement.
REQUIRED = (
    "external_id", "client", "audit_fee_cents", "non_audit_fee_cents", "is_pie",
    "years_auditing", "partner_years", "tender_held", "firm_fee_from_client_cents",
    "firm_total_fees_cents", "kyc_checked_years_ago", "non_audit_services",
)


@dataclass(frozen=True)
class Issue:
    code: str
    field: str
    severity: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "field": self.field, "severity": self.severity,
                "message": self.message}


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _to_int(value: Any, *, nonnegative: bool = True) -> int:
    if isinstance(value, bool):
        raise ValueError("must be an integer, not a boolean")
    if isinstance(value, int):
        out = value
    elif isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
        out = int(value.strip())
    else:
        raise ValueError("must be an integer")
    if nonnegative and out < 0:
        raise ValueError("must not be negative")
    return out


def _to_number(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("must be a number, not a boolean")
    if isinstance(value, (int, float)):
        out = float(value)
    elif isinstance(value, str):
        try:
            out = float(value.strip())
        except ValueError as exc:
            raise ValueError("must be a number") from exc
    else:
        raise ValueError("must be a number")
    if out != out or out in (float("inf"), float("-inf")):
        raise ValueError("must be finite")
    if out < 0:
        raise ValueError("must not be negative")
    return out


def _to_rate(value: Any) -> float:
    out = _to_number(value)
    if out > 100:
        raise ValueError("must be between 0 and 100")
    return out


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str) and value.strip().lower() in {"true", "false", "yes", "no", "1", "0"}:
        return value.strip().lower() in {"true", "yes", "1"}
    raise ValueError("must be a boolean")


def _to_str(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("must be text")
    return value.strip()


def _items(value: Any, *, text: bool) -> list:
    if isinstance(value, str):
        parts = [part.strip() for part in re.split(r"[;,]", value) if part.strip()]
    elif isinstance(value, (list, tuple)):
        parts = list(value)
    else:
        raise ValueError("must be a list")
    if text:
        if not all(isinstance(part, str) for part in parts):
            raise ValueError("must contain text")
        return [part.strip() for part in parts]
    return [_to_int(part) for part in parts]


def parse_record(raw: dict[str, Any], *, priors: Priors) -> tuple[str, Case | None, list[Issue]]:
    """Turn one CRM row into a case, or into the reasons it cannot become one."""
    issues: list[Issue] = []
    external_id = raw.get("external_id")
    if not isinstance(external_id, str) or not external_id.strip():
        issues.append(Issue("missing_field", "external_id", ERROR,
                            "external_id must be a non-empty string"))
        external_id = ""
    else:
        external_id = external_id.strip()

    for name in REQUIRED:
        if name == "external_id":
            continue
        if name not in raw or _missing(raw[name]):
            issues.append(Issue("missing_field", name, ERROR, f"{name} is required"))

    values: dict[str, Any] = {}
    for name, value in raw.items():
        if name == "external_id":
            continue
        if name not in _CASE_FIELDS:
            issues.append(Issue("unknown_field", name, WARNING,
                                f"{name} is not a field this firm audits and was ignored"))
            continue
        if _missing(value):
            continue
        try:
            if name in _INT_FIELDS:
                values[name] = _to_int(value)
            elif name in _MONEY_FIELDS:
                values[name] = _to_number(value)
            elif name in _RATE_FIELDS:
                values[name] = _to_rate(value)
            elif name in _BOOL_FIELDS:
                values[name] = _to_bool(value)
            elif name in _STR_FIELDS:
                values[name] = _to_str(value)
            elif name in _INT_LIST_FIELDS:
                values[name] = tuple(_items(value, text=False))
            elif name in _STR_LIST_FIELDS:
                values[name] = tuple(_items(value, text=True))
        except ValueError as exc:
            code = "negative_number" if "negative" in str(exc) else "invalid_type"
            if name in _RATE_FIELDS and "between 0 and 100" in str(exc):
                code = "number_out_of_range"
            issues.append(Issue(code, name, ERROR, f"{name}: {exc}"))

    case = None if any(issue.severity == ERROR for issue in issues) else Case(**values)
    return external_id, case, issues


def quality_issues(case: Case, priors: Priors) -> list[Issue]:
    """Structural contradictions and missing facts a tax audit would have to resolve."""
    issues: list[Issue] = []
    if case.firm_fee_from_client_cents > case.firm_total_fees_cents:
        issues.append(Issue("fees_exceed_firm_total", "firm_fee_from_client_cents", ERROR,
                            "the fee attributed to this client exceeds the firm's total fees"))
    if case.non_audit_fee_cents and not case.non_audit_services:
        issues.append(Issue("non_audit_services_missing", "non_audit_services", WARNING,
                            "a non-audit fee is stated but no service is named"))
    standard, reduced = case.standard_vat_rate_percent, case.reduced_vat_rate_percent
    if standard is not None and reduced is not None and standard < reduced:
        issues.append(Issue("vat_rate_order_invalid", "standard_vat_rate_percent", ERROR,
                            "the standard VAT rate is below the reduced rate"))
    if case.claims_small_undertaking and not any(
            (case.turnover_eur, case.balance_sheet_eur, case.employees)):
        issues.append(Issue("small_undertaking_unsupported", "claims_small_undertaking", WARNING,
                            "a small-undertaking claim has no balance-sheet, turnover or headcount"))
    if not case.client_geo:
        issues.append(Issue("jurisdiction_missing", "client_geo", WARNING,
                            "no jurisdiction, so the VAT and finance desks cannot observe it"))
    elif not any(priors.finance(name, case.client_geo) for name in (
            "hicp_inflation_percent", "gdp_per_capita_eur", "economic_sentiment_index")):
        issues.append(Issue("finance_reference_missing", "client_geo", WARNING,
                            "no harvested finance series names this jurisdiction"))
    if case.audit_fee_cents == 0:
        issues.append(Issue("zero_audit_fee", "audit_fee_cents", WARNING,
                            "no fee is stated, so no instruction can be priced"))
    lookback = priors.value("non_audit_lookback_years")
    if lookback and case.non_audit_years >= int(lookback):
        need = int(lookback)
        if len(case.prior_audit_fees_cents) < need or len(case.prior_non_audit_fees_cents) < need:
            issues.append(Issue("fee_history_incomplete", "prior_audit_fees_cents", WARNING,
                                f"the ceiling averages {need} years and the file carries fewer"))
    return issues


def _record_state(agreements: list[dict[str, Any]]) -> str:
    if not agreements:
        return "no_payment"
    states = [a["state"] for a in agreements]
    if any(state == "conflict" for state in states):
        return "conflict"
    if all(state == "succeeded" for state in states):
        return "settled"
    if any(state == "succeeded" for state in states):
        return "partial"
    if any(state == "unknown" for state in states):
        return "unresolved"
    if all(state == "awaiting_human" for state in states):
        return "awaiting_human"
    return "failed"


@dataclass
class Run:
    run_id: str
    dataset_id: str
    currency: str
    rail: str
    created_at: str
    results: dict[str, dict[str, Any]]
    agreements: dict[str, Agreement]

    def summarise(self) -> dict[str, Any]:
        records = [self.results[key] for key in sorted(self.results)]
        for record in records:
            record["state"] = _record_state(record["agreements"])
            record["settled_cents"] = sum(
                a["amount_cents"] for a in record["agreements"] if a["state"] == "succeeded")
        quality = Counter(record["quality"] for record in records)
        codes = Counter(issue["code"] for record in records for issue in record["issues"])
        verdicts = Counter()
        silent_roles: set[str] = set()
        payable = 0
        for record in records:
            verdicts.update(record["verdicts"])
            silent_roles.update(record["silent_roles"])
            payable += record["payable"]
        entries = [a for record in records for a in record["agreements"]]
        settlement = Counter(a["state"] for a in entries)
        return {
            "run_id": self.run_id,
            "dataset_id": self.dataset_id,
            "currency": self.currency,
            "rail": self.rail,
            "created_at": self.created_at,
            "quality": {
                "records": len(records),
                "verified": quality.get("verified", 0),
                "review": quality.get("review", 0),
                "blocked": quality.get("blocked", 0),
                "issue_codes": dict(sorted(codes.items())),
            },
            "desks": {
                "findings": sum(verdicts.values()),
                "clear": verdicts.get(CLEAR, 0),
                "hold": verdicts.get(HOLD, 0),
                "breach": verdicts.get("breach", 0),
                "silent": verdicts.get("silent", 0),
                "payable": payable,
                "silent_roles": sorted(silent_roles),
            },
            "settlement": {
                "agreements": len(entries),
                "settled": settlement.get("succeeded", 0),
                "awaiting_human": settlement.get("awaiting_human", 0),
                "failed": settlement.get("failed", 0),
                "unresolved": settlement.get("unknown", 0),
                "conflicts": sum(1 for record in records if record["state"] == "conflict"),
                "settled_cents": sum(a["amount_cents"] for a in entries
                                     if a["state"] == "succeeded"),
                "settled_now_cents": sum(record["settled_now_cents"] for record in records),
            },
            "records": records,
        }


class Pipeline:
    """One principal's dataset: one gate, one hub, one aggregate bound."""

    def __init__(self, transport: object, *, dataset_id: str, payee: str, limits: Any,
                 currency: str = "USD", rail: str = "paypal", freeze: bool = True,
                 firm: Firm | None = None, priors: Priors | None = None,
                 chain: Any = None, quality: Callable[[Case, Priors], list[Issue]] | None = None):
        if not dataset_id.strip():
            raise ValueError("a dataset needs a name")
        if not payee.strip():
            raise ValueError("a payment destination must be named, never guessed")
        if not re.fullmatch(r"[A-Z]{3}", currency):
            raise ValueError("currency must be a three-letter code")
        if limits is None:
            raise ValueError("an aggregate bound must be given, not left to a library default")
        self.dataset_id = dataset_id.strip()
        self.payee = payee.strip()
        self.currency = currency
        self.rail = rail
        self.priors = priors or Priors.load()
        self.firm = firm or Firm(self.priors)
        self.quality = quality or quality_issues
        self.gate = HumanGate()
        self.hub = PayPalHub(transport, limits=limits, freeze=freeze, gate=self.gate,
                             currency=currency, chain=chain)
        self._runs: dict[str, Run] = {}
        self._agreements: dict[str, Agreement] = {}
        self._next_tick = 0

    def run(self, records: list[dict[str, Any]], *, clearance: list[str] | None = None,
            tick: int | None = None) -> dict[str, Any]:
        """Audit every record, price the binding ones, and pay only what was cleared."""
        start = self._next_tick if tick is None else tick
        for key in clearance or ():
            self.gate.clear(key)
        run = Run(uuid.uuid4().hex, self.dataset_id, self.currency, self.rail,
                  datetime.now(timezone.utc).isoformat(timespec="seconds"), {}, {})
        duplicates = Counter(
            row.get("external_id") for row in records
            if isinstance(row.get("external_id"), str) and row.get("external_id").strip())
        duplicate_ids = {key for key, count in duplicates.items() if count > 1}
        for row in records:
            external_id = row.get("external_id")
            key = external_id if isinstance(external_id, str) and external_id.strip() else uuid.uuid4().hex
            result = self._audit_row(row, run, start, duplicate=key in duplicate_ids)
            if key in run.results:
                key = f"{key}#{len(run.results)}"
            run.results[key] = result
            start += len(result["agreements"]) or 1
        self._next_tick = start
        self._runs[run.run_id] = run
        return run.summarise()

    def _audit_row(self, row: dict[str, Any], run: Run, tick: int, *,
                   duplicate: bool) -> dict[str, Any]:
        external_id, case, issues = parse_record(row, priors=self.priors)
        if duplicate:
            issues.append(Issue("duplicate_external_id", "external_id", ERROR,
                                "another record in this batch names the same engagement"))
        result: dict[str, Any] = {
            "external_id": external_id or "(unnamed)",
            "quality": "blocked" if any(issue.severity == ERROR for issue in issues) else "verified",
            "issues": [issue.as_dict() for issue in issues],
            "verdicts": {}, "silent_roles": [], "payable": 0, "agreements": [],
            "state": "blocked", "settled_cents": 0, "settled_now_cents": 0,
        }
        if result["quality"] == "blocked":
            return result
        issues.extend(self.quality(case, self.priors))
        if any(issue.severity == ERROR for issue in issues):
            result["quality"] = "blocked"
            result["issues"] = [issue.as_dict() for issue in issues]
            return result
        if any(issue.severity == WARNING for issue in issues):
            result["quality"] = "review"
        result["issues"] = [issue.as_dict() for issue in issues]

        findings = self.firm.review(case)
        result["verdicts"] = dict(Counter(finding.verdict for finding in findings))
        result["silent_roles"] = [finding.role for finding in findings if finding.verdict == "silent"]

        payable = [finding for finding in findings if finding.binding and case.audit_fee_cents > 0]
        result["payable"] = len(payable)
        for finding in payable:
            agreement = Agreement(f"{self.dataset_id}:{external_id}:{finding.role}",
                                  finding.role, self.payee, case.audit_fee_cents,
                                  self.currency)
            entry = {"id": agreement.id, "role": finding.role,
                     "amount_cents": agreement.amount_cents,
                     "review_required": finding.verdict == HOLD,
                     "state": "conflict", "provider_ref": None, "note": ""}
            result["agreements"].append(entry)
            known = self._agreements.get(agreement.id)
            if known is not None and known != agreement:
                entry["note"] = "terms changed under an agreement id this dataset already priced"
                issues.append(Issue("agreement_terms_changed", finding.role, ERROR,
                                    f"{agreement.id}: payment terms changed since it was priced"))
                continue
            self._agreements[agreement.id] = agreement
            run.agreements[agreement.id] = agreement
            before = self.hub.state_of(agreement.id)
            try:
                settlement = self.hub.settle(agreement, tick + len(result["agreements"]) - 1)
            except ValueError as exc:
                entry["note"] = str(exc)
                issues.append(Issue("agreement_terms_changed", finding.role, ERROR,
                                    f"{agreement.id}: {exc}"))
                continue
            entry.update(state=settlement.state, provider_ref=settlement.provider_ref,
                         note=settlement.note)
            if settlement.state == "succeeded" and before != "succeeded":
                result["settled_now_cents"] += agreement.amount_cents
        result["issues"] = [issue.as_dict() for issue in issues]
        result["state"] = _record_state(result["agreements"])
        return result

    def clear(self, run_id: str, agreement_ids: list[str], *, tick: int | None = None) -> dict[str, Any]:
        """Record a person's clearance by name, then settle exactly those instructions."""
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        unknown = [key for key in agreement_ids if key not in run.agreements]
        if unknown:
            raise ValueError(f"unknown agreement(s) in this run: {', '.join(unknown)}")
        start = self._next_tick if tick is None else tick
        # `settled_now_cents` answers for this reply, not for the run's whole history, so a
        # second clearance of the same instruction reports zero rather than the first one again.
        for record in run.results.values():
            record["settled_now_cents"] = 0
        for key in agreement_ids:
            agreement = run.agreements[key]
            self.gate.clear(key)
            entry = next(a for record in run.results.values() for a in record["agreements"]
                         if a["id"] == key)
            before = self.hub.state_of(key)
            try:
                settlement = self.hub.settle(agreement, start)
            except ValueError as exc:
                entry.update(state="conflict", note=str(exc))
                continue
            entry.update(state=settlement.state, provider_ref=settlement.provider_ref,
                         note=settlement.note)
            if settlement.state == "succeeded" and before != "succeeded":
                owner = next(record for record in run.results.values()
                             if any(a["id"] == key for a in record["agreements"]))
                owner["settled_now_cents"] += agreement.amount_cents
            start += 1
        self._next_tick = start
        return run.summarise()

    def get(self, run_id: str) -> dict[str, Any]:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        return run.summarise()
