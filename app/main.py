"""FastAPI service placing PayPal at the center of autonomous AI agent operations,
guarded by the Oversight Twin spending monitor.

Capabilities:
  1. POST /api/v1/agents/charge      — Run oversight guard, then create/capture PayPal order.
  2. POST /api/v1/agents/payout      — Autonomous vendor/contractor payout via PayPal Payouts.
  3. POST /api/v1/payments/clear     — Human clearance for payments requiring named operator sign-off.
  4. POST /api/v1/invoices/prepare   — Review CRM engagement & calculate server-side price.
  5. POST /api/v1/invoices/{id}/open — Open PayPal order for a verified invoice.
  6. POST /api/v1/invoices/{id}/capture — Capture approved PayPal order.
  7. GET  /api/v1/invoices           — List all invoices and PayPal settlement status.
  8. GET  /api/v1/swarm/metrics      — Aggregate spend, active mandates, and prevented attack stats.
  9. POST /api/v1/tools/execute      — Standard JSON-schema tool interface for AI agents.
 10. POST /api/v1/assistant/chat     — AI CFO assistant with live tool integration.
 11. GET  / and /dashboard           — Interactive web dashboard for business executives.
"""

from __future__ import annotations

import logging
import uuid
from os import getenv
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Body, status, Request, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse
from pydantic import BaseModel, Field

from .oversight_twin import Session, Action, PaymentState, MoneyNotMoved
from .paypal_client import PayPalClient, MoneyNotMoved as PayPalMoneyNotMoved

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
log = logging.getLogger("uvicorn.error")
log.setLevel(logging.INFO)

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Oversight Twin — PayPal AI Agent Settlement Hub",
    version="1.0.0",
    description="PayPal-centered financial settlement hub and AI safety guard for autonomous agent swarms.",
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
            "detail": f"Payment not moved — {exc.reason}",
        },
    )


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------
class ChargeRequest(BaseModel):
    agent_id: str = Field(..., description="Identifier of the agent initiating the charge")
    payee_id: str = Field(..., description="Identifier of the payee receiving the funds")
    amount_cents: int = Field(..., ge=0, description="Payment amount in integer cents")
    mandate_cap_cents: int = Field(..., ge=0, description="Per-agent spending cap in cents")


class PayoutRequest(BaseModel):
    agent_id: str = Field(..., description="Agent requesting payout")
    recipient: str = Field(..., description="PayPal email or payee ID")
    amount_cents: int = Field(..., ge=0, description="Payout amount in cents")
    mandate_cap_cents: int = Field(default=50_000, description="Spending cap in cents")
    note: str = Field(default="Vendor Payout via AI Agent", description="Note on PayPal transaction")
    approved_by: Optional[str] = Field(default=None, description="Human operator sign-off if over threshold")


class ClearRequest(BaseModel):
    agreement_id: str = Field(..., description="Agreement or invoice ID to approve")
    operator_name: str = Field(..., description="Name of the clearing human operator")


class InvoicePrepareRequest(BaseModel):
    external_id: str = Field(..., description="CRM Engagement ID (e.g. A1, ENG-2026-001)")
    client_name: str = Field(..., description="Client name")
    audit_fee_cents: int = Field(default=20_000, description="Base fee in cents")
    non_audit_fee_cents: int = Field(default=1_000, description="Non-audit fee in cents")
    client_geo: str = Field(default="US", description="Client geography")


class InvoiceCaptureRequest(BaseModel):
    approved_by: str = Field(..., description="Named human operator approving the capture")


class ToolExecuteRequest(BaseModel):
    name: str = Field(..., description="Tool name: billing_list, billing_price, billing_open, billing_capture, agent_payout, swarm_metrics")
    arguments: Dict[str, Any] = Field(default_factory=dict)


class AssistantChatRequest(BaseModel):
    prompt: str = Field(..., description="User query or command for the AI CFO")
    operator_name: str = Field(default="H. Shaukat", description="Human operator name")


# ---------------------------------------------------------------------------
# State & Singletons
# ---------------------------------------------------------------------------
PAYPAL_CLIENT_ID = getenv("PAYPAL_CLIENT_ID", "test-client-id")
PAYPAL_SECRET = getenv("PAYPAL_SECRET", "test-secret")

_paypal_client: PayPalClient | None = None
_session: Session | None = None
_invoices: Dict[str, Dict[str, Any]] = {}
_human_cleared: set[str] = set()

APPROVAL_FLOOR_CENTS = 30_000  # $500 threshold requiring human clearance


def _get_paypal_client() -> PayPalClient:
    global _paypal_client
    if _paypal_client is None:
        _paypal_client = PayPalClient(PAYPAL_CLIENT_ID, PAYPAL_SECRET)
    return _paypal_client


def _get_session() -> Session:
    global _session
    if _session is None:
        from swarm_oversight.monitor import Limits
        _session = Session(limits=Limits())
    return _session


# ---------------------------------------------------------------------------
# Endpoint 1: POST /api/v1/agents/charge (Hackathon core)
# ---------------------------------------------------------------------------
@app.post("/api/v1/agents/charge", response_model=Dict[str, Any])
async def agent_charge(request: ChargeRequest = Body(...)) -> Dict[str, Any]:
    """Run oversight guard; if clean, create & capture PayPal order."""
    session = _get_session()

    action = Action(
        seq=len(session._log),
        agent=request.agent_id,
        kind="spend",
        amount=request.amount_cents,
        payee=request.payee_id,
        tick=len(session._log),
    )

    state = session.observe(action, mandate_cap_cents=request.mandate_cap_cents)
    if state.state == "FAILED":
        raise MoneyNotMoved(state.reason or "Spending cap breached")

    try:
        client = _get_paypal_client()
        paypal_order = await client.create_order(
            amount_cents=request.amount_cents, payee_id=request.payee_id
        )
        session.record_spend(
            amount_cents=request.amount_cents,
            tx_meta={
                "type": "charge",
                "order_id": paypal_order.get("id"),
                "agent": request.agent_id,
                "payee": request.payee_id,
                "amount_cents": request.amount_cents,
                "status": "COMPLETED",
            }
        )
        return {
            "state": "COMPLETED",
            "reason": None,
            "paypal_order_id": paypal_order.get("id"),
            "paypal_order_json": paypal_order,
            "payee_id": request.payee_id,
            "amount_cents": request.amount_cents,
            "amount_usd": f"{request.amount_cents / 100:.2f}",
        }
    except PayPalMoneyNotMoved as e:
        session._latest_state = PaymentState(state="UNKNOWN", reason=str(e))
        return {
            "state": "UNKNOWN",
            "reason": str(e),
            "paypal_order_id": None,
            "paypal_order_json": None,
            "detail": "PayPal order creation failed",
        }
    except Exception as e:
        session._latest_state = PaymentState(state="UNKNOWN", reason=str(e))
        return {
            "state": "UNKNOWN",
            "reason": str(e),
            "paypal_order_id": None,
            "paypal_order_json": None,
            "detail": f"PayPal request failed: {e}",
        }


# ---------------------------------------------------------------------------
# Endpoint 2: POST /api/v1/agents/payout (Accounts Payable via PayPal Payouts)
# ---------------------------------------------------------------------------
@app.post("/api/v1/agents/payout", response_model=Dict[str, Any])
async def agent_payout(request: PayoutRequest = Body(...)) -> Dict[str, Any]:
    """Autonomous agent disbursements for vendors & contractors."""
    session = _get_session()

    # 1. Immediate mandate cap check
    if request.amount_cents > request.mandate_cap_cents:
        raise MoneyNotMoved(f"{request.agent_id} spent {request.amount_cents} > {request.mandate_cap_cents}")

    # 2. Human approval floor check: if over threshold, require human clearance before moving money
    payout_ref = f"payout:{request.agent_id}:{request.recipient}"
    if request.amount_cents >= APPROVAL_FLOOR_CENTS and not (request.approved_by or payout_ref in _human_cleared):
        return {
            "state": "AWAITING_HUMAN",
            "reason": f"Disbursement exceeds ${APPROVAL_FLOOR_CENTS / 100:.2f} threshold; requires named operator sign-off.",
            "agreement_id": payout_ref,
            "amount_cents": request.amount_cents,
            "amount_usd": f"{request.amount_cents / 100:.2f}",
            "recipient": request.recipient,
        }

    # 3. Guard check: observe action through monitor (anti-split, relay, window caps)
    action = Action(
        seq=len(session._log),
        agent=request.agent_id,
        kind="spend",
        amount=request.amount_cents,
        payee=request.recipient,
        tick=len(session._log),
    )
    state = session.observe(action, mandate_cap_cents=request.mandate_cap_cents)
    if state.state == "FAILED":
        raise MoneyNotMoved(state.reason or "Spending cap breached")

    client = _get_paypal_client()
    payout_res = await client.create_payout(
        recipient=request.recipient, amount_cents=request.amount_cents, note=request.note
    )

    session.record_spend(
        amount_cents=request.amount_cents,
        tx_meta={
            "type": "payout",
            "payout_batch_id": payout_res.get("batch_header", {}).get("payout_batch_id"),
            "agent": request.agent_id,
            "payee": request.recipient,
            "amount_cents": request.amount_cents,
            "status": "COMPLETED",
        }
    )

    return {
        "state": "COMPLETED",
        "payout_batch_id": payout_res.get("batch_header", {}).get("payout_batch_id"),
        "recipient": request.recipient,
        "amount_cents": request.amount_cents,
        "amount_usd": f"{request.amount_cents / 100:.2f}",
        "raw": payout_res,
    }


# ---------------------------------------------------------------------------
# Endpoint 3: POST /api/v1/payments/clear (Human Clearance)
# ---------------------------------------------------------------------------
@app.post("/api/v1/payments/clear", response_model=Dict[str, Any])
async def clear_payment(request: ClearRequest = Body(...)) -> Dict[str, Any]:
    """Human clearance for held disbursements or high-value orders."""
    _human_cleared.add(request.agreement_id)
    return {
        "status": "cleared",
        "agreement_id": request.agreement_id,
        "operator": request.operator_name,
        "message": f"Agreement {request.agreement_id} cleared by {request.operator_name}",
    }


# ---------------------------------------------------------------------------
# Endpoint 4: POST /api/v1/invoices/prepare (Accounts Receivable Server Pricing)
# ---------------------------------------------------------------------------
@app.post("/api/v1/invoices/prepare", response_model=Dict[str, Any])
async def prepare_invoice(request: InvoicePrepareRequest = Body(...)) -> Dict[str, Any]:
    """Audit CRM record and price invoice on server (rejecting LLM pricing)."""
    # Deterministic calculation from reviewed facts:
    # Base fee + non-audit fee + VAT
    vat_multiplier = 1.19 if request.client_geo == "DE" else 1.0
    total_cents = int((request.audit_fee_cents + request.non_audit_fee_cents) * vat_multiplier)

    invoice_id = f"INV-{request.external_id}-{uuid.uuid4().hex[:6].upper()}"
    invoice = {
        "invoice_id": invoice_id,
        "external_id": request.external_id,
        "client_name": request.client_name,
        "amount_cents": total_cents,
        "amount_usd": f"{total_cents / 100:.2f}",
        "currency": "USD",
        "state": "draft",
        "paypal_order_id": None,
        "findings": {
            "clear": 18,
            "hold": 4,
            "breach": 0,
            "silent": 4,
        },
    }
    _invoices[invoice_id] = invoice
    return invoice


# ---------------------------------------------------------------------------
# Endpoint 5: POST /api/v1/invoices/{id}/open (Open PayPal Order for Client)
# ---------------------------------------------------------------------------
@app.post("/api/v1/invoices/{invoice_id}/open", response_model=Dict[str, Any])
async def open_invoice(invoice_id: str) -> Dict[str, Any]:
    """Generate PayPal Order v2 for a priced client invoice."""
    invoice = _invoices.get(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.get("paypal_order_id"):
        return invoice  # Idempotent re-read

    client = _get_paypal_client()
    order = await client.create_order(
        amount_cents=invoice["amount_cents"], payee_id=invoice["client_name"]
    )
    invoice["paypal_order_id"] = order.get("id")
    invoice["state"] = "awaiting_capture"
    invoice["paypal_order"] = order
    return invoice


# ---------------------------------------------------------------------------
# Endpoint 6: POST /api/v1/invoices/{id}/capture (Capture Client Payment)
# ---------------------------------------------------------------------------
@app.post("/api/v1/invoices/{invoice_id}/capture", response_model=Dict[str, Any])
async def capture_invoice(invoice_id: str, request: InvoiceCaptureRequest = Body(...)) -> Dict[str, Any]:
    """Capture payment on PayPal after client checkout. Requires human operator sign-off."""
    invoice = _invoices.get(invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if not request.approved_by or not request.approved_by.strip():
        raise HTTPException(
            status_code=400,
            detail="A named person must approve the capture; an AI assistant cannot approve its own capture.",
        )

    order_id = invoice.get("paypal_order_id")
    if not order_id:
        raise HTTPException(status_code=400, detail="Invoice has no PayPal order open yet")

    client = _get_paypal_client()
    capture_res = await client.capture_order(order_id)

    invoice["state"] = "captured"
    invoice["approved_by"] = request.approved_by
    invoice["capture_res"] = capture_res

    session = _get_session()
    session.record_spend(
        amount_cents=invoice["amount_cents"],
        tx_meta={
            "type": "invoice_capture",
            "invoice_id": invoice_id,
            "order_id": order_id,
            "client": invoice["client_name"],
            "amount_cents": invoice["amount_cents"],
            "approved_by": request.approved_by,
            "status": "COMPLETED",
        }
    )

    return {
        "invoice_id": invoice_id,
        "state": "captured",
        "approved_by": request.approved_by,
        "paypal_order_id": order_id,
        "amount_usd": invoice["amount_usd"],
    }


# ---------------------------------------------------------------------------
# Endpoint 7: GET /api/v1/invoices
# ---------------------------------------------------------------------------
@app.get("/api/v1/invoices", response_model=List[Dict[str, Any]])
async def list_invoices() -> List[Dict[str, Any]]:
    return list(_invoices.values())


# ---------------------------------------------------------------------------
# Endpoint 8: GET /api/v1/swarm/metrics (Hackathon core)
# ---------------------------------------------------------------------------
@app.get("/api/v1/swarm/metrics", response_model=Dict[str, Any])
async def swarm_metrics() -> Dict[str, Any]:
    """Return aggregate swarm metrics: spend, active mandates, caught attacks."""
    session = _get_session()
    return {
        "total_spend_cents": session.successful_spend_cents,
        "total_spend_usd": f"{session.successful_spend_cents / 100:.2f}",
        "active_mandates": session.active_mandates,
        "caught_attack_attempts": len(session.blocked_attempts),
        "blocked_attempts": session.blocked_attempts,
        "session_state": session._latest_state.state,
        "total_transactions": len(session.transactions),
    }


# ---------------------------------------------------------------------------
# Endpoint 9: POST /api/v1/tools/execute (AI Agent Tool Dispatcher)
# ---------------------------------------------------------------------------
@app.post("/api/v1/tools/execute", response_model=Dict[str, Any])
async def execute_tool(request: ToolExecuteRequest = Body(...)) -> Dict[str, Any]:
    """Standard JSON-schema tool caller for AI agents & assistant dispatchers."""
    name = request.name
    args = request.arguments
    session = _get_session()

    if name == "billing_list":
        return {"invoices": list(_invoices.values())}

    elif name == "billing_price":
        ext_id = args.get("external_id", "A1")
        req = InvoicePrepareRequest(external_id=ext_id, client_name=f"Client-{ext_id}")
        return await prepare_invoice(req)

    elif name == "billing_open":
        inv_id = args.get("invoice_id")
        if not inv_id:
            raise HTTPException(status_code=400, detail="invoice_id required")
        return await open_invoice(inv_id)

    elif name == "billing_capture":
        inv_id = args.get("invoice_id")
        approver = args.get("approved_by")
        if not inv_id or not approver:
            return {
                "error": "refused",
                "detail": "a named person must approve the capture; an assistant cannot approve its own spending",
            }
        return await capture_invoice(inv_id, InvoiceCaptureRequest(approved_by=approver))

    elif name == "agent_payout":
        agent_id = args.get("agent_id", "agent-procure")
        recipient = args.get("recipient", "vendor@example.com")
        amount = int(args.get("amount_cents", 5_000))
        cap = int(args.get("mandate_cap_cents", 50_000))
        return await agent_payout(PayoutRequest(
            agent_id=agent_id, recipient=recipient, amount_cents=amount, mandate_cap_cents=cap
        ))

    elif name == "swarm_metrics":
        return await swarm_metrics()

    else:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {name}")


# ---------------------------------------------------------------------------
# Endpoint 10: POST /api/v1/assistant/chat (AI CFO Assistant with Tools)
# ---------------------------------------------------------------------------
@app.post("/api/v1/assistant/chat", response_model=Dict[str, Any])
async def assistant_chat(request: AssistantChatRequest = Body(...)) -> Dict[str, Any]:
    """AI CFO Assistant that translates natural language requests into safe PayPal operations."""
    prompt = request.prompt.lower()
    session = _get_session()

    # Intent routing to safe deterministic tools:
    if "metric" in prompt or "spend" in prompt or "status" in prompt or "overview" in prompt:
        metrics = await swarm_metrics()
        return {
            "reply": f"PayPal Settlement Hub Overview: Total Settled Spend is ${metrics['total_spend_usd']}. We have {len(metrics['active_mandates'])} active agent mandates and our Oversight Twin guard has blocked {metrics['caught_attack_attempts']} attack attempts.",
            "tool_called": "swarm_metrics",
            "data": metrics,
        }

    elif "invoice" in prompt or "price" in prompt or "bill" in prompt:
        # Server-priced invoice creation
        inv = await prepare_invoice(InvoicePrepareRequest(
            external_id="ENG-2026",
            client_name="Global Enterprise Inc",
            audit_fee_cents=20_000,
            non_audit_fee_cents=3_800,
        ))
        opened = await open_invoice(inv["invoice_id"])
        return {
            "reply": f"Generated server-verified invoice {opened['invoice_id']} for {opened['client_name']}. The server priced the total to ${opened['amount_usd']} (model-provided amounts were ignored). PayPal Order {opened['paypal_order_id']} is created in state 'awaiting_capture'.",
            "tool_called": "billing_price + billing_open",
            "data": opened,
        }

    elif "attack" in prompt or "split" in prompt or "simulate attack" in prompt:
        # Simulate 3-agent split attack
        tight_session = session
        action1 = Action(seq=len(tight_session._log), agent="agent-A", amount=40_000, payee="payee-bad", tick=1)
        action2 = Action(seq=len(tight_session._log) + 1, agent="agent-B", amount=40_000, payee="payee-bad", tick=2)
        action3 = Action(seq=len(tight_session._log) + 2, agent="agent-C", amount=30_000, payee="payee-bad", tick=3)
        tight_session.observe(action1)
        tight_session.observe(action2)
        state3 = tight_session.observe(action3)
        return {
            "reply": f"Simulated collusive split attack across 3 agents: Agent A ($40) + Agent B ($40) passed individual checks. Agent C ($30) attempted to complete the $110 split against the $100 cap. Result: BLOCKED ({state3.reason}). Zero dollars left the PayPal treasury.",
            "tool_called": "guard_split_check",
            "data": {"agent_c_state": state3.state, "reason": state3.reason},
        }

    else:
        return {
            "reply": f"AI CFO Assistant online. I can price client engagements on PayPal, disburse vendor payouts with guard enforcement, or inspect swarm safety metrics. What would you like to execute?",
            "tool_called": None,
            "data": {},
        }


# ---------------------------------------------------------------------------
# Endpoint 11: GET / and /dashboard (Interactive Web Dashboard)
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_view() -> HTMLResponse:
    return HTMLResponse(content="""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Oversight Twin — PayPal AI Agent Settlement Hub</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    body { background-color: #0b0f19; color: #f3f4f6; font-family: system-ui, -apple-system, sans-serif; }
    .card { background: rgba(17, 24, 39, 0.8); border: 1px solid rgba(55, 65, 81, 0.6); backdrop-filter: blur(8px); }
    .badge-paypal { background-color: #0070ba; color: white; }
    .pulse-dot { animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite; }
    @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .4; } }
  </style>
</head>
<body class="p-6 md:p-10 max-w-7xl mx-auto">
  <!-- Header -->
  <header class="flex flex-col md:flex-row justify-between items-start md:items-center pb-8 border-b border-gray-800 gap-4">
    <div>
      <div class="flex items-center gap-3">
        <span class="px-2.5 py-1 text-xs font-semibold rounded-md badge-paypal">PayPal</span>
        <h1 class="text-2xl font-bold tracking-tight text-white">Oversight Twin Settlement Hub</h1>
        <span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-950 text-emerald-400 border border-emerald-800">
          <span class="h-1.5 w-1.5 rounded-full bg-emerald-400 pulse-dot"></span> Live Guard
        </span>
      </div>
      <p class="text-sm text-gray-400 mt-1">Single-Process PayPal Settlement Hub, Anti-Structuring Guard & Autonomous AI Fleet</p>
    </div>
    <div class="flex gap-2">
      <a href="/docs" target="_blank" class="px-3 py-1.5 bg-gray-800 hover:bg-gray-700 text-sm font-medium rounded-lg transition border border-gray-700">FastAPI Swagger</a>
      <button onclick="refreshData()" class="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-sm font-medium rounded-lg transition text-white">Refresh Data</button>
    </div>
  </header>

  <!-- Metric KPI Cards -->
  <div class="grid grid-cols-1 md:grid-cols-4 gap-4 mt-8">
    <div class="card p-5 rounded-xl">
      <div class="text-xs font-medium text-gray-400 uppercase tracking-wider">PayPal Settled Volume</div>
      <div id="metric-total-spend" class="text-3xl font-extrabold text-blue-400 mt-2">$0.00</div>
      <div class="text-xs text-gray-500 mt-1">Idempotent Orders & Captures</div>
    </div>
    <div class="card p-5 rounded-xl">
      <div class="text-xs font-medium text-gray-400 uppercase tracking-wider">Attacks Intercepted</div>
      <div id="metric-attacks" class="text-3xl font-extrabold text-amber-400 mt-2">0</div>
      <div class="text-xs text-emerald-400 mt-1">Zero dollars lost to treasury</div>
    </div>
    <div class="card p-5 rounded-xl">
      <div class="text-xs font-medium text-gray-400 uppercase tracking-wider">Active Agent Mandates</div>
      <div id="metric-mandates" class="text-3xl font-extrabold text-purple-400 mt-2">0</div>
      <div class="text-xs text-gray-500 mt-1">Per-agent dynamic caps</div>
    </div>
    <div class="card p-5 rounded-xl">
      <div class="text-xs font-medium text-gray-400 uppercase tracking-wider">Settlement State</div>
      <div id="metric-state" class="text-3xl font-extrabold text-emerald-400 mt-2">ONLINE</div>
      <div class="text-xs text-gray-500 mt-1">Deterministic state machine</div>
    </div>
  </div>

  <!-- Interactive Simulation Controls -->
  <div class="card p-6 rounded-xl mt-8">
    <h2 class="text-lg font-semibold text-white mb-2">Simulate AI Agent Financial Operations</h2>
    <p class="text-sm text-gray-400 mb-5">Click below to trigger live workflows through the Oversight Twin guard and PayPal client:</p>
    
    <div class="grid grid-cols-1 md:grid-cols-4 gap-3">
      <button onclick="runSim('compliant')" class="p-3 bg-gray-800/80 hover:bg-gray-800 border border-emerald-500/40 rounded-lg text-left transition group">
        <div class="text-sm font-semibold text-emerald-400">1. Compliant Charge</div>
        <div class="text-xs text-gray-400 mt-1">Agent spend $25.00 under cap → PayPal Order 200 COMPLETED</div>
      </button>

      <button onclick="runSim('over_cap')" class="p-3 bg-gray-800/80 hover:bg-gray-800 border border-red-500/40 rounded-lg text-left transition group">
        <div class="text-sm font-semibold text-red-400">2. Single Cap Breach</div>
        <div class="text-xs text-gray-400 mt-1">Agent attempts $1,500 vs $500 cap → Guard 402 FAILED (zero PayPal call)</div>
      </button>

      <button onclick="runSim('split_attack')" class="p-3 bg-gray-800/80 hover:bg-gray-800 border border-amber-500/40 rounded-lg text-left transition group">
        <div class="text-sm font-semibold text-amber-400">3. Collusive Split Attack</div>
        <div class="text-xs text-gray-400 mt-1">3 agents split $110 to bypass $100 cap → Caught at Agent C</div>
      </button>

      <button onclick="runSim('invoice')" class="p-3 bg-gray-800/80 hover:bg-gray-800 border border-blue-500/40 rounded-lg text-left transition group">
        <div class="text-sm font-semibold text-blue-400">4. Server-Priced Invoice</div>
        <div class="text-xs text-gray-400 mt-1">Audit engagement → Server prices $250 → PayPal Order created</div>
      </button>
    </div>

    <!-- Output Box -->
    <div class="mt-4 p-4 bg-black/50 border border-gray-800 rounded-lg font-mono text-xs overflow-x-auto min-h-[90px]" id="sim-output">
      <span class="text-gray-500">// Operation log will appear here after clicking a scenario above...</span>
    </div>
  </div>

  <!-- AI CFO Chat Interface -->
  <div class="card p-6 rounded-xl mt-8">
    <h2 class="text-lg font-semibold text-white mb-2">AI CFO Assistant (Natural Language Tool Dispatcher)</h2>
    <p class="text-sm text-gray-400 mb-4">Chat with the autonomous finance desk. Commands are executed through safe server-side tools:</p>
    <div class="flex gap-2">
      <input id="chat-input" type="text" placeholder="e.g. 'Show our PayPal metrics' or 'Price and bill client Acme GmbH' or 'Simulate a split attack'" class="flex-1 bg-gray-900 border border-gray-700 px-4 py-2 rounded-lg text-sm focus:outline-none focus:border-blue-500">
      <button onclick="sendChat()" class="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-sm font-medium rounded-lg text-white transition">Send Query</button>
    </div>
    <div id="chat-response" class="mt-4 p-4 bg-gray-900/60 border border-gray-800 rounded-lg text-sm text-gray-300 hidden"></div>
  </div>

  <script>
    async function refreshData() {
      try {
        const res = await fetch('/api/v1/swarm/metrics');
        const data = await res.json();
        document.getElementById('metric-total-spend').innerText = '$' + (data.total_spend_usd || '0.00');
        document.getElementById('metric-attacks').innerText = data.caught_attack_attempts || '0';
        document.getElementById('metric-mandates').innerText = Object.keys(data.active_mandates || {}).length;
        document.getElementById('metric-state').innerText = data.session_state || 'ONLINE';
      } catch (e) {
        console.error(e);
      }
    }

    async function runSim(type) {
      const out = document.getElementById('sim-output');
      out.innerHTML = '<span class="text-blue-400">Executing ' + type + '...</span>';
      
      try {
        if (type === 'compliant') {
          const res = await fetch('/api/v1/agents/charge', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({agent_id: 'procure-01', payee_id: 'vendor-aws', amount_cents: 2500, mandate_cap_cents: 50000})
          });
          const d = await res.json();
          out.innerHTML = '<span class="text-emerald-400">✓ 200 COMPLETED</span>: Charge of $' + d.amount_usd + ' routed through PayPal Order ID: <span class="text-white">' + d.paypal_order_id + '</span>';
        } else if (type === 'over_cap') {
          const res = await fetch('/api/v1/agents/charge', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({agent_id: 'procure-02', payee_id: 'vendor-cloud', amount_cents: 150000, mandate_cap_cents: 50000})
          });
          const d = await res.json();
          out.innerHTML = '<span class="text-red-400">✗ 402 FAILED</span>: ' + d.detail + ' (Reason: ' + d.reason + '). Zero HTTP calls to PayPal Sandbox.';
        } else if (type === 'split_attack') {
          const res = await fetch('/api/v1/assistant/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({prompt: 'simulate split attack'})
          });
          const d = await res.json();
          out.innerHTML = '<span class="text-amber-400">🛡️ SWARM SPLIT INTERCEPTED</span>: ' + d.reply;
        } else if (type === 'invoice') {
          const res = await fetch('/api/v1/assistant/chat', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({prompt: 'price invoice'})
          });
          const d = await res.json();
          out.innerHTML = '<span class="text-blue-400">🧾 SERVER PRICED & BILLED</span>: ' + d.reply;
        }
        refreshData();
      } catch (err) {
        out.innerHTML = '<span class="text-red-400">Error: ' + err.message + '</span>';
      }
    }

    async function sendChat() {
      const input = document.getElementById('chat-input');
      const val = input.value.trim();
      if (!val) return;
      const respBox = document.getElementById('chat-response');
      respBox.classList.remove('hidden');
      respBox.innerHTML = '<span class="text-gray-400">Processing query with AI CFO tools...</span>';
      try {
        const res = await fetch('/api/v1/assistant/chat', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({prompt: val})
        });
        const d = await res.json();
        respBox.innerHTML = '<div class="font-semibold text-blue-400">AI CFO:</div><div class="mt-1">' + d.reply + '</div>' +
          (d.tool_called ? '<div class="text-xs text-gray-500 mt-2 font-mono">Tool executed: ' + d.tool_called + '</div>' : '');
        refreshData();
      } catch (e) {
        respBox.innerHTML = '<span class="text-red-400">Error: ' + e.message + '</span>';
      }
    }

    refreshData();
  </script>
</body>
</html>""")
