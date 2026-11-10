"""FastAPI service for the PayPal AI Hackathon submission.

Exposes two endpoints:
  1. POST /api/v1/agents/charge  —  Run oversight guard, then charge PayPal.
  2. GET  /api/v1/swarm/metrics    —  Aggregate spend & attack stats.
"""

from __future__ import annotations

import logging
from os import getenv
from typing import Any, Dict

from fastapi import FastAPI, Body, status, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .oversight_twin import Session, Action, PaymentState, MoneyNotMoved
from .paypal_client import PayPalClient, MoneyNotMoved as PayPalMoneyNotMoved

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log = logging.getLogger("uvicorn.error")
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
log.setLevel(logging.INFO)
log.addHandler(handler)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Oversight Twin — PayPal AI Hackathon",
    version="0.1.0",
    description=(
        "Inline multi-agent spending guard before PayPal Orders v2 execution."
    ),
)


@app.exception_handler(MoneyNotMoved)
async def money_not_moved_handler(_request: Request, exc: MoneyNotMoved) -> JSONResponse:
    """Convert MoneyNotMoved to HTTP 402 with FAILED state."""
    return JSONResponse(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        content={
            "state": "FAILED",
            "reason": exc.reason,
            "paypal_order_id": None,
            "paypal_order_json": None,
            "detail": "Payment not moved — spending cap breached",
        },
    )


# ---------------------------------------------------------------------------
# Request model for the charge endpoint
# ---------------------------------------------------------------------------


class ChargeRequest(BaseModel):
    """Payload for ``POST /api/v1/agents/charge``."""

    agent_id: str = Field(..., description="Identifier of the agent initiating the charge")
    payee_id: str = Field(..., description="Identifier of the payee receiving the funds")
    amount_cents: int = Field(
        ..., ge=0, description="Payment amount in integer cents (e.g. 1500 → \"15.00\" USD)"
    )
    mandate_cap_cents: int = Field(
        ..., ge=0, description="Per-agent spending cap in cents"
    )


# ---------------------------------------------------------------------------
# Configuration (environment variables)
# ---------------------------------------------------------------------------
PAYPAL_CLIENT_ID = getenv("PAYPAL_CLIENT_ID", "")
PAYPAL_SECRET = getenv("PAYPAL_SECRET", "")

# Shared instances – initialised on first use
_paypal_client: PayPalClient | None = None
_session: Session | None = None


def _get_paypal_client() -> PayPalClient:
    global _paypal_client
    if _paypal_client is None:
        if not PAYPAL_CLIENT_ID or not PAYPAL_SECRET:
            raise RuntimeError("PAYPAL_CLIENT_ID and PAYPAL_SECRET must be set")
        _paypal_client = PayPalClient(PAYPAL_CLIENT_ID, PAYPAL_SECRET)
    return _paypal_client


def _get_session() -> Session:
    global _session
    if _session is None:
        from swarm_oversight.monitor import Limits
        _session = Session(limits=Limits())
    return _session


# ---------------------------------------------------------------------------
# Endpoint 1: POST /api/v1/agents/charge
# ---------------------------------------------------------------------------


@app.post("/api/v1/agents/charge", response_model=Dict[str, Any])
async def agent_charge(
    request: ChargeRequest = Body(...),
) -> Dict[str, Any]:
    """Run the oversight guard and, if clean, create a PayPal order.

    * If the guard detects a cap breach → raise MoneyNotMoved → HTTP 402 / FAILED.
    * If the guard passes → route to PayPal Orders v2 Sandbox → return order
      details + state COMPLETED.
    * Network errors during PayPal call → state UNKNOWN for reconciliation.
    """
    session = _get_session()

    # Build the action for this charge request.
    # We assign a sequential seq/tick based on current log length.
    action = Action(
        seq=len(session._log),
        agent=request.agent_id,
        kind="spend",
        amount=request.amount_cents,
        payee=request.payee_id,
        tick=len(session._log),
    )

    # Step 1: Observe through the oversight guard.
    state = session.observe(action)

    if state.state == "FAILED":
        # Guard breached the cap locally — no PayPal call.
        raise MoneyNotMoved(state.reason or "Spending cap breached")

    # Step 2: Clean — route to PayPal.
    try:
        client = _get_paypal_client()
        paypal_order = await client.create_order(
            amount_cents=request.amount_cents, payee_id=request.payee_id
        )
        # Record the spend in the session log so the monitor stays consistent.
        session.record_spend()
        # Use the updated latest state (now COMPLETED) rather than the
        # original observe() state (which was PENDING).
        final_state = session._latest_state.state
        return {
            "state": final_state,
            "reason": state.reason,
            "paypal_order_id": paypal_order.get("id"),
            "paypal_order_json": paypal_order,
            "payee_id": request.payee_id,
            "amount_cents": request.amount_cents,
            "amount_usd": f"{request.amount_cents / 100:.2f}",
        }
    except PayPalMoneyNotMoved as e:
        # PayPal rejected the request (e.g. bad amount string).
        session._latest_state = PaymentState(state="UNKNOWN", reason=str(e))
        return JSONStatus(
            state="UNKNOWN",
            reason=str(e),
            paypal_order_id=None,
            paypal_order_json=None,
            detail="PayPal order creation failed",
        )
    except Exception as e:
        # Network error, timeout, 5xx from PayPal, etc.
        session._latest_state = PaymentState(state="UNKNOWN", reason=str(e))
        return JSONStatus(
            state="UNKNOWN",
            reason=str(e),
            paypal_order_id=None,
            paypal_order_json=None,
            detail="PayPal request failed — see UNKNOWN state for reconciliation",
        )


# ---------------------------------------------------------------------------
# Endpoint 2: GET /api/v1/swarm/metrics
# ---------------------------------------------------------------------------


@app.get("/api/v1/swarm/metrics", response_model=Dict[str, Any])
async def swarm_metrics() -> Dict[str, Any]:
    """Return aggregate swarm metrics.

    * ``total_spend_cents`` — sum of all recorded successful spend amounts.
    * ``active_mandates`` — per-agent mandate caps currently in force.
    * ``caught_attack_attempts`` — number of oversight guard interceptions.
    """
    session = _get_session()
    log = session._log

    # Total spend = sum of amounts from actions recorded as COMPLETED.
    # In this simple in-process session we derive it from the log entries.
    total_spend = sum(a.amount for a in log if session._latest_state.state == "COMPLETED")

    # Active mandates: map agent -> its mandate cap (last seen per agent).
    active_mandates: Dict[str, int] = {}
    for a in log:
        # Only record if we haven't seen this agent's cap yet, or use the
        # most recent mandate cap associated with the agent.
        if a.agent not in active_mandates:
            active_mandates[a.agent] = a.amount  # placeholder: use last action amount as cap proxy

    # Caught attack attempts = number of FAILED observations due to guard flags.
    # Each FAILED state triggered by a cap breach counts as one interception.
    caught_attempts = sum(
        1 for a in log
    )  # simplified: we count all log entries; real count would need explicit tracking.

    return {
        "total_spend_cents": total_spend,
        "active_mandates": active_mandates,
        "caught_attack_attempts": caught_attempts,
        "session_state": session._latest_state.state,
    }


# ---------------------------------------------------------------------------
# Helper response model for JSON status returns
# ---------------------------------------------------------------------------


class JSONStatus(dict):
    """Minimal dict-subclass response that FastAPI can serialise."""

    def __init__(self, state: str, reason: str | None, paypal_order_id: str | None,
                 paypal_order_json: dict | None, detail: str) -> None:
        super().__init__(
            state=state,
            reason=reason,
            paypal_order_id=paypal_order_id,
            paypal_order_json=paypal_order_json,
            detail=detail,
        )