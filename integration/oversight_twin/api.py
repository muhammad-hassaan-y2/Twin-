"""The pipeline's HTTP edge: token-authenticated runs, lookups and named clearances.

It fails closed. With no token, no named payment destination, no rail or no aggregate bound the
routes answer 503 and health says which setting is missing; a run never falls back to a fake rail
without being labelled one.
"""
from __future__ import annotations

import os
import secrets
import threading
from typing import Any, Callable

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from swarm_oversight.monitor import Limits
from twin.payments.paypal import PayPalConfig, PayPalTransport, SandboxTransport

from .commerce import BillingBook, Invoice, SimulatedMerchant
from .commerce_tools import CommerceTools, review_records
from .pipeline import Pipeline

RAILS = {"paypal": "paypal-sandbox", "simulated": "simulated"}


class RunIn(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=120)
    records: list[dict[str, Any]] = Field(min_length=1, max_length=500)
    clearance: list[str] = Field(default_factory=list)
    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")


class ClearIn(BaseModel):
    agreements: list[str] = Field(min_length=1, max_length=500)


class BillingIn(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=120)
    records: list[dict[str, Any]] = Field(min_length=1, max_length=500)


class CaptureIn(BaseModel):
    approved_by: str = Field(min_length=1, max_length=120)


class ToolIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)


class SettlementService:
    """Per-dataset pipelines, all sharing one rail and one aggregate policy."""

    def __init__(self, factory: Callable[[str, str], Pipeline], *, rail: str) -> None:
        self._factory = factory
        self.rail = rail
        self._pipelines: dict[tuple[str, str], Pipeline] = {}
        self._runs: dict[str, Pipeline] = {}
        self._lock = threading.Lock()

    def pipeline(self, dataset_id: str, currency: str) -> Pipeline:
        key = (dataset_id, currency)
        with self._lock:
            if key not in self._pipelines:
                self._pipelines[key] = self._factory(dataset_id, currency)
            return self._pipelines[key]

    def run(self, dataset_id: str, currency: str, records: list[dict[str, Any]],
            clearance: list[str]) -> dict[str, Any]:
        pipeline = self.pipeline(dataset_id, currency)
        with self._lock:
            report = pipeline.run(records, clearance=clearance)
            self._runs[report["run_id"]] = pipeline
        return report

    def clear(self, run_id: str, agreement_ids: list[str]) -> dict[str, Any]:
        with self._lock:
            pipeline = self._runs.get(run_id)
            if pipeline is None:
                raise KeyError(run_id)
            return pipeline.clear(run_id, agreement_ids)

    def get(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            pipeline = self._runs.get(run_id)
            if pipeline is None:
                raise KeyError(run_id)
            return pipeline.get(run_id)

    def describe(self) -> dict[str, Any]:
        return {"rail": self.rail, "recovery": "in-memory", "payee_configured": True}


class BillingService:
    """Client invoices for one merchant: priced from the review, opened and captured on PayPal."""

    def __init__(self, transport: object, *, merchant: str, rail: str,
                 currency: str = "USD") -> None:
        self.book = BillingBook(transport, merchant=merchant, currency=currency)
        self.rail = rail
        self._engagements: dict[str, dict[str, Any]] = {}

    def prepare(self, dataset_id: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        engagements = review_records(records, dataset_id=dataset_id,
                                     currency=self.book.currency)
        self._engagements[dataset_id] = engagements
        for entry in engagements.values():
            priced = entry["invoice"]
            if priced is None:
                continue
            self.book.prepare(Invoice(
                id=priced["id"], engagement_id=priced["engagement_id"],
                client=priced["client"], amount_cents=priced["amount_cents"],
                currency=priced["currency"], description=priced["description"],
                due_in_days=priced["due_in_days"]))
        priced_count = sum(1 for entry in engagements.values() if entry["invoice"])
        return {
            "dataset_id": dataset_id,
            "rail": self.rail,
            "engagements": list(engagements.values()),
            "priced": priced_count,
            "refused": len(engagements) - priced_count,
            "book": self.book.summary(),
        }

    def open(self, invoice_id: str) -> dict[str, Any]:
        return self.book.open_prepared(invoice_id)

    def status(self, invoice_id: str) -> dict[str, Any]:
        return self.book.status(invoice_id)

    def capture(self, invoice_id: str, approved_by: str) -> dict[str, Any]:
        return self.book.capture(invoice_id, approved_by=approved_by)

    def invoices(self) -> dict[str, Any]:
        return {"invoices": self.book.invoices(), "book": self.book.summary()}

    def summary(self) -> dict[str, Any]:
        return self.book.summary()

    def _engagements_across_datasets(self) -> dict[str, dict[str, Any]]:
        return {key: entry for engagements in self._engagements.values()
                for key, entry in engagements.items()}

    def tools(self) -> list[dict[str, Any]]:
        return CommerceTools(self.book, self._engagements_across_datasets()).catalog()

    def tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return CommerceTools(self.book, self._engagements_across_datasets()).call(name, arguments)

    def describe(self) -> dict[str, Any]:
        return {"rail": self.rail, "merchant": self.book.merchant, "recovery": "in-memory"}


def limits_from_env() -> tuple[Limits | None, str]:
    try:
        per_agent = int(os.environ["OVERSIGHT_PER_AGENT_LIMIT_CENTS"])
        per_payee = int(os.environ["OVERSIGHT_PER_PAYEE_LIMIT_CENTS"])
        window = int(os.environ.get("OVERSIGHT_WINDOW", "10"))
        long_window = int(os.environ.get("OVERSIGHT_LONG_WINDOW", "60"))
    except (KeyError, ValueError):
        return None, ("set OVERSIGHT_PER_AGENT_LIMIT_CENTS and OVERSIGHT_PER_PAYEE_LIMIT_CENTS "
                      "so the aggregate bound is a number this service was given")
    if min(per_agent, per_payee, window, long_window) <= 0:
        return None, "aggregate limits and windows must be positive"
    return Limits(per_agent=per_agent, per_payee=per_payee, window=window,
                  long_window=long_window, merge="both"), ""


def transport_from_env() -> tuple[object | None, str, str]:
    rail = os.environ.get("OVERSIGHT_RAIL", "").strip().lower()
    if not rail:
        return None, "", "set OVERSIGHT_RAIL to paypal or simulated"
    if rail == "simulated":
        return SandboxTransport(), RAILS["simulated"], ""
    if rail == "paypal":
        config = PayPalConfig.from_env()
        if config is None:
            return None, "", "PAYPAL_CLIENT_ID and PAYPAL_SECRET are not in the environment"
        if config.environment != "sandbox":
            return None, "", "only the PayPal sandbox is allowed; live capture is refused"
        return PayPalTransport(config), RAILS["paypal"], ""
    return None, "", f"'{rail}' is not a rail this service offers"


def service_from_env() -> tuple[SettlementService | None, str]:
    transport, rail, why = transport_from_env()
    if transport is None:
        return None, why
    limits, why = limits_from_env()
    if limits is None:
        return None, why
    payee = os.environ.get("OVERSIGHT_PAYEE", "").strip()
    if not payee:
        return None, "set OVERSIGHT_PAYEE to the firm that receives these fees"

    def factory(dataset_id: str, currency: str) -> Pipeline:
        return Pipeline(transport, dataset_id=dataset_id, payee=payee, currency=currency,
                        rail=rail, limits=limits)

    return SettlementService(factory, rail=rail), ""


def billing_from_env() -> tuple[BillingService | None, str]:
    """A merchant book on the same rail the runs use. Simulated mode labels itself."""
    transport, rail, why = transport_from_env()
    if transport is None:
        return None, why
    merchant = os.environ.get("OVERSIGHT_PAYEE", "").strip()
    if not merchant:
        return None, "set OVERSIGHT_PAYEE to the merchant that receives these invoices"
    if rail == RAILS["simulated"]:
        transport = SimulatedMerchant()
    return BillingService(transport, merchant=merchant, rail=rail), ""


def create_app(*, token: str | None = None, service: SettlementService | None = None,
               reason: str = "", billing: BillingService | None = None,
               billing_reason: str = "") -> FastAPI:
    app = FastAPI(title="Oversight Twin Pipeline", version="0.2.0")
    app.state.token = token if token is not None else os.environ.get("OVERSIGHT_API_TOKEN", "")
    app.state.service = service
    app.state.reason = reason or ("the pipeline service is not configured"
                                  if service is None else "")
    app.state.billing = billing
    app.state.billing_reason = billing_reason or ("billing is not configured"
                                                  if billing is None else "")

    def auth(authorization: str = Header(default="")) -> None:
        expected = app.state.token
        if not expected:
            raise HTTPException(status_code=401, detail="no API token is configured")
        scheme, _, value = authorization.partition(" ")
        if scheme.lower() != "bearer" or not secrets.compare_digest(value, expected):
            raise HTTPException(status_code=401, detail="a valid bearer token is required")

    def require() -> SettlementService:
        if app.state.service is None:
            raise HTTPException(status_code=503, detail=app.state.reason)
        return app.state.service

    def require_billing() -> BillingService:
        if app.state.billing is None:
            raise HTTPException(status_code=503, detail=app.state.billing_reason)
        return app.state.billing

    @app.get("/health")
    def health() -> dict[str, Any]:
        service = app.state.service
        if service is None:
            return {"status": "unconfigured", "why": app.state.reason}
        return {"status": "ok", **service.describe(), "token_configured": bool(app.state.token),
                "billing": "ok" if app.state.billing else "unconfigured"}

    @app.post("/v1/runs")
    def run(body: RunIn, _: None = Depends(auth),
            service: SettlementService = Depends(require)) -> dict[str, Any]:
        try:
            return service.run(body.dataset_id, body.currency, body.records, body.clearance)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/runs/{run_id}")
    def get_run(run_id: str, _: None = Depends(auth),
                service: SettlementService = Depends(require)) -> dict[str, Any]:
        try:
            return service.get(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="no such run") from exc

    @app.post("/v1/runs/{run_id}/clear")
    def clear(run_id: str, body: ClearIn, _: None = Depends(auth),
              service: SettlementService = Depends(require)) -> dict[str, Any]:
        try:
            return service.clear(run_id, body.agreements)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="no such run") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    # ----------------------------------------------------------------- billing

    @app.post("/v1/billing/prepare")
    def billing_prepare(body: BillingIn, _: None = Depends(auth),
                        billing: BillingService = Depends(require_billing)) -> dict[str, Any]:
        try:
            return billing.prepare(body.dataset_id, body.records)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/billing/invoices")
    def billing_invoices(_: None = Depends(auth),
                         billing: BillingService = Depends(require_billing)) -> dict[str, Any]:
        return billing.invoices()

    @app.get("/v1/billing/invoices/{invoice_id}")
    def billing_status(invoice_id: str, _: None = Depends(auth),
                       billing: BillingService = Depends(require_billing)) -> dict[str, Any]:
        try:
            return billing.status(invoice_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="no such invoice") from exc

    @app.post("/v1/billing/invoices/{invoice_id}/open")
    def billing_open(invoice_id: str, _: None = Depends(auth),
                     billing: BillingService = Depends(require_billing)) -> dict[str, Any]:
        try:
            return billing.open(invoice_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="no such priced invoice") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/v1/billing/invoices/{invoice_id}/capture")
    def billing_capture(invoice_id: str, body: CaptureIn, _: None = Depends(auth),
                        billing: BillingService = Depends(require_billing)) -> dict[str, Any]:
        try:
            return billing.capture(invoice_id, body.approved_by)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="no such invoice") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/v1/billing/summary")
    def billing_summary(_: None = Depends(auth),
                        billing: BillingService = Depends(require_billing)) -> dict[str, Any]:
        return billing.summary()

    # ------------------------------------------------- the assistant's tool surface

    @app.get("/v1/billing/tools")
    def billing_tools(_: None = Depends(auth),
                      billing: BillingService = Depends(require_billing)) -> dict[str, Any]:
        return {"tools": billing.tools()}

    @app.post("/v1/billing/tool")
    def billing_tool(body: ToolIn, _: None = Depends(auth),
                     billing: BillingService = Depends(require_billing)) -> dict[str, Any]:
        return billing.tool(body.name, body.arguments)

    return app


_service_from_env, _why = service_from_env()
_billing_from_env, _billing_why = billing_from_env()
app = create_app(service=_service_from_env, reason=_why,
                 billing=_billing_from_env, billing_reason=_billing_why)
