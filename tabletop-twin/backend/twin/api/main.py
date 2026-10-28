"""The HTTP edge of the twin.

One account, one table, one world. The client sends gestures and scrub positions;
this answers with numbers it computed and sentences the persona is allowed to
say. Nothing here trusts a value that arrived over the network to decide whether
money moves, and nothing is shared between accounts.
"""

from __future__ import annotations

import os

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from twin.domain.events import event_from_dict
from twin.payments.machine import IllegalTransition, TERMINAL
from twin.payments.paypal import PayPalConfig, PayPalTransport
from twin.planner.model import providers_configured
from twin.planner.tools import ToolError, parse_calls
from twin.store import Store
from twin.world.heartbeat import advance, unwired
from twin.world.memory import summarise
from twin.world.scene import scene_payload
from twin.world.session import Session

_cache: dict[str, Session] = {}
_store: Store | None = None
_demo: Session | None = None


def store() -> Store:
    global _store
    if _store is None:
        _store = Store(os.environ.get("TWIN_DB_PATH", "twin.db"))
    return _store


def reset_state() -> None:
    """Drop every cached world. Tests and a restart both come through here."""
    global _store, _demo
    _cache.clear()
    if _store is not None:
        _store.close()
    _store = None
    _demo = None


def demo_session() -> Session:
    """The seed table, used only to answer an unauthenticated health check."""
    global _demo
    if _demo is None:
        _demo = Session.build()
    return _demo


def session_for(user_id: str) -> Session:
    if user_id not in _cache:
        _cache[user_id] = Session.restore(store(), user_id)
    return _cache[user_id]


def bearer_token(request: Request) -> str:
    header = request.headers.get("Authorization", "")
    return header[7:].strip() if header[:7].lower() == "bearer " else ""


def current_user(request: Request) -> str:
    user_id = store().user_for_token(bearer_token(request))
    if not user_id:
        raise HTTPException(status_code=401, detail="sign in with an access token")
    return user_id


def world_of(user_id: str = Depends(current_user)) -> Session:
    return session_for(user_id)


app = FastAPI(title="Tabletop Twin", version="0.2.0")
# The immersive client is served from the IWSDK dev server on its own port.
_origins = [o for o in os.environ.get("TWIN_ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SignUp(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    name: str = Field(default="", max_length=80)
    password: str = Field(min_length=8, max_length=200)


class SignIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class Ask(BaseModel):
    intent: str = Field(min_length=1, max_length=400)


class Calls(BaseModel):
    calls: list[dict]


class Gesture(BaseModel):
    action_id: str
    gesture: str


class Rejection(BaseModel):
    action_id: str
    reviewer: str = Field(min_length=1, max_length=80)
    reason: str = Field(min_length=3, max_length=400)


class Scrub(BaseModel):
    day: int = Field(ge=0, le=179)


class Pull(BaseModel):
    event_id: str


class Tick(BaseModel):
    days: int = Field(default=1, ge=0, le=30)
    final_of_day: bool = False


class ActionRef(BaseModel):
    action_id: str


class EventIn(BaseModel):
    id: str = Field(min_length=1, max_length=48)
    label: str = Field(min_length=1, max_length=120)
    kind: str = Field(pattern="^(income|bill|subscription|tax)$")
    direction: str = Field(pattern="^(in|out)$")
    amount_cents: int = Field(ge=0, le=100_000_000)
    due_day: int = Field(ge=0, le=364)
    counterparty: str = Field(default="", max_length=120)
    recurring_every_days: int | None = Field(default=None, ge=1, le=365)
    occurrences: int = Field(default=1, ge=1, le=104)
    late_fee_cents: int = Field(default=0, ge=0, le=10_000_000)
    lateness_days: list[int] = Field(default_factory=list, max_length=52)


class ConnectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class Ingest(BaseModel):
    connection_id: str
    key: str
    event: EventIn


class CeilingIn(BaseModel):
    recipient: str = Field(min_length=1, max_length=120)
    cents: int | None = Field(default=None, ge=0, le=100_000_000)


class OpeningIn(BaseModel):
    cents: int = Field(ge=-100_000_000, le=1_000_000_000)


# ------------------------------------------------------------------- accounts


@app.post("/v1/signup")
def signup(body: SignUp) -> dict:
    try:
        user_id = store().create_user(body.email, body.name, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    Session.seed_new_world(store(), user_id)
    return {"token": store().issue_token(user_id), "user_id": user_id, "name": store().user_name(user_id)}


@app.post("/v1/login")
def login(body: SignIn) -> dict:
    user_id = store().verify_password(body.email, body.password)
    if user_id is None:
        raise HTTPException(status_code=401, detail="that email and password do not match")
    return {"token": store().issue_token(user_id), "user_id": user_id, "name": store().user_name(user_id)}


@app.post("/v1/logout")
def logout(request: Request) -> dict:
    store().revoke_token(bearer_token(request))
    return {"signed_out": True}


@app.get("/v1/me")
def me(user_id: str = Depends(current_user)) -> dict:
    s = session_for(user_id)
    return {
        "user_id": user_id,
        "name": store().user_name(user_id),
        "persona": s.persona.name,
        "day": s.day,
        "horizon_days": s.horizon_days,
        "events": len(s.ledger.events),
    }


@app.get("/v1/health")
def health() -> dict:
    s = demo_session()
    return {
        "ok": True,
        "persona": s.persona.name,
        "planner": s.planner.name,
        "route": getattr(s.planner, "last_route", s.planner.name),
        "model_providers": providers_configured(),
        "heartbeat_steps": [step.slug for step in s.persona.steps],
        "heartbeat_unwired": unwired(s),
        "paypal_configured": PayPalConfig.from_env() is not None,
        "accounts": True,
    }


# ---------------------------------------------------------------------- world


@app.get("/v1/world")
def world(s: Session = Depends(world_of)) -> dict:
    return scene_payload(s)


@app.post("/v1/ask")
def ask(body: Ask, s: Session = Depends(world_of)) -> dict:
    answer = s.ask(body.intent)
    answer["scene"] = scene_payload(s)
    s.persist()
    return answer


@app.post("/v1/tools")
def tools(body: Calls, s: Session = Depends(world_of)) -> dict:
    """Run tool calls the client already knows the names of — the same validator a model's reply goes through."""
    try:
        calls = parse_calls(body.calls)
    except ToolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    results = [s.run(call) for call in calls]
    s.persist()
    return {"results": results, "scene": scene_payload(s)}


@app.post("/v1/scrub")
def scrub(body: Scrub, s: Session = Depends(world_of)) -> dict:
    s.day = min(body.day, s.horizon_days - 1)
    s.persist()
    return {"day": s.day, "scene": scene_payload(s)}


@app.post("/v1/pull")
def pull(body: Pull, s: Session = Depends(world_of)) -> dict:
    """A pipe yanked out of the world. Returns the second miniature and its delta."""
    try:
        event = s.ledger.by_id(body.event_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="no such event") from exc
    if not event.is_cancellable():
        raise HTTPException(status_code=409, detail=f"{event.label} is not a pipe you can pull")
    result = s.tool_fork(f"cancel {event.label}", cancel_event_ids=[event.id])
    s.persist()
    return {"fork": result, "scene": scene_payload(s)}


@app.post("/v1/tick")
def heartbeat(body: Tick, s: Session = Depends(world_of)) -> dict:
    utterances = advance(s, body.days, body.final_of_day)
    s.persist()
    return {"day": s.day, "captions": [u.to_dict() for u in utterances], "scene": scene_payload(s)}


# -------------------------------------------------------------------- money


@app.post("/v1/approve")
def approve(body: Gesture, s: Session = Depends(world_of)) -> dict:
    try:
        result = s.approve(body.action_id, body.gesture)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="nothing pending under that action id") from exc
    s.persist()
    return result


@app.post("/v1/reject")
def reject(body: Rejection, s: Session = Depends(world_of)) -> dict:
    """A human saying no, with a name and a reason attached."""
    try:
        result = s.reject(body.action_id, body.reviewer, body.reason)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="nothing pending under that action id") from exc
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    s.persist()
    return result


@app.post("/v1/retry")
def retry(body: ActionRef, s: Session = Depends(world_of)) -> dict:
    try:
        result = s.retry_payment(body.action_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="nothing pending under that action id") from exc
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    s.persist()
    return result


@app.post("/v1/reconcile")
def reconcile(body: ActionRef, s: Session = Depends(world_of)) -> dict:
    try:
        result = s.reconcile(body.action_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="nothing pending under that action id") from exc
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    s.persist()
    return result


@app.post("/v1/blackout")
def blackout(body: ActionRef, s: Session = Depends(world_of)) -> dict:
    """Teach the unknown state on demand: the provider takes the money and the reply is lost."""
    key = s.pending.get(body.action_id)
    if key is None:
        raise HTTPException(status_code=404, detail="nothing pending under that action id")
    if not hasattr(s.transport, "blackout_keys"):
        raise HTTPException(status_code=409, detail="the live transport cannot be made to lose a reply on purpose")
    s.transport.blackout_keys.add(key)
    return {"action_id": body.action_id, "armed": True}


@app.post("/v1/transport")
def use_real_transport(s: Session = Depends(world_of)) -> dict:
    """Swap the sandbox fake for the live PayPal client. Needs env credentials; refuses without them."""
    config = PayPalConfig.from_env()
    if config is None:
        raise HTTPException(status_code=503, detail="PAYPAL_CLIENT_ID and PAYPAL_SECRET are not set")
    s.transport = PayPalTransport(config)
    return {"transport": "paypal", "environment": config.environment}


@app.put("/v1/limits/recipient")
def set_ceiling(body: CeilingIn, s: Session = Depends(world_of)) -> dict:
    result = s.set_ceiling(body.recipient, body.cents)
    s.persist()
    return result


@app.put("/v1/limits/opening")
def set_opening(body: OpeningIn, s: Session = Depends(world_of)) -> dict:
    result = s.set_opening_balance(body.cents)
    s.persist()
    return {**result, "scene": scene_payload(s)}


# --------------------------------------------------------------------- ledger


@app.get("/v1/ledger")
def ledger(s: Session = Depends(world_of)) -> dict:
    return {
        "opening_balance_cents": s.ledger.opening_balance_cents,
        "events": [
            {
                "id": e.id,
                "label": e.label,
                "kind": e.kind.value,
                "direction": e.direction.value,
                "amount_cents": e.amount_cents,
                "due_day": e.due_day,
                "counterparty": e.counterparty,
                "chasable": e.is_chasable(),
                "cancellable": e.is_cancellable(),
            }
            for e in s.ledger.events
        ],
        "policy": {
            "max_single_cents": s.policy.max_single_cents,
            "daily_spend_cap_cents": s.policy.daily_spend_cap_cents,
            "monthly_spend_cap_cents": s.policy.monthly_spend_cap_cents,
            "approval_floor_cents": s.policy.approval_floor_cents,
            "allowed_recipients": sorted(s.policy.allowed_recipients),
            "blocked_actions": sorted(s.policy.blocked_actions),
            "recipient_ceilings_cents": dict(s.policy.recipient_ceilings),
        },
    }


@app.post("/v1/ledger/events")
def add_event(body: EventIn, s: Session = Depends(world_of)) -> dict:
    try:
        result = s.add_event(event_from_dict(body.model_dump()), "manual")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    result["scene"] = scene_payload(s)
    s.persist()
    return result


@app.delete("/v1/ledger/events/{event_id}")
def remove_event(event_id: str, s: Session = Depends(world_of)) -> dict:
    try:
        event = s.ledger.by_id(event_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="no such event") from exc
    try:
        result = s.remove_event(event.id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    result["scene"] = scene_payload(s)
    s.persist()
    return result


# ---------------------------------------------------------------- connections


@app.post("/v1/connections")
def create_connection(body: ConnectionIn, user_id: str = Depends(current_user)) -> dict:
    connection_id, key = store().create_connection(user_id, body.name)
    return {"connection_id": connection_id, "key": key, "posts_to": "/v1/ingest"}


@app.get("/v1/connections")
def list_connections(user_id: str = Depends(current_user)) -> dict:
    return {"connections": store().connections_for(user_id)}


@app.post("/v1/ingest")
def ingest(body: Ingest) -> dict:
    """An outside workflow hands an event to one account. The key says whose."""
    user_id = store().owner_of_connection(body.connection_id, body.key)
    if user_id is None:
        raise HTTPException(status_code=401, detail="that connection key is not recognised")
    s = session_for(user_id)
    try:
        result = s.add_event(event_from_dict(body.event.model_dump()), f"connection:{body.connection_id}")
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    s.persist()
    return result


# ------------------------------------------------------------- memory / audit


@app.get("/v1/audit")
def audit(limit: int = 50, user_id: str = Depends(current_user)) -> dict:
    return {"entries": store().read_log(user_id, limit=min(max(limit, 1), 500))}


@app.get("/v1/summary")
def summary(s: Session = Depends(world_of), user_id: str = Depends(current_user)) -> dict:
    unresolved = sum(1 for r in s.machine.all() if r.state not in TERMINAL)
    return summarise(
        store().read_log(user_id, limit=500),
        persona=s.persona.name,
        day=s.day,
        open_payments=unresolved,
    )


@app.get("/v1/payments")
def payments(s: Session = Depends(world_of)) -> dict:
    return {
        "records": [
            {
                "action_id": record.action_id,
                "amount_cents": record.amount_cents,
                "recipient": record.recipient,
                "state": record.state.value,
                "attempt": record.attempt,
                "idempotency_key": record.idempotency_key,
                "provider_ref": record.provider_ref,
                "verified_outcome": record.verified_outcome,
                "history": record.history,
            }
            for record in s.machine.all()
        ]
    }


@app.get("/v1/persona")
def persona(s: Session = Depends(world_of)) -> dict:
    return {
        "name": s.persona.name,
        "voice": s.persona.voice_prompt,
        "prohibitions": list(s.persona.prohibitions),
        "loop": s.persona.heartbeat,
        "heartbeat": [
            {"slug": step.slug, "index": step.index, "title": step.title, "body": step.body}
            for step in s.persona.steps
        ],
    }
