"""The HTTP edge of the twin.

One account, one table, one world. The client sends gestures and scrub positions;
this answers with numbers it computed and sentences the persona is allowed to
say. Nothing here trusts a value that arrived over the network to decide whether
money moves, and nothing is shared between accounts.

A table has no keyboard, so nobody is stopped at a door. The device id a browser
carries names its world, and the first request that carries one opens it. Signing
in later claims that same world rather than starting a second one beside it.
"""

from __future__ import annotations

import dataclasses
import json
import os
import queue
import threading
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.responses import StreamingResponse

from twin.audit import service as firm_service
from twin.domain.events import event_from_dict
from twin.payments.machine import IllegalTransition, TERMINAL
from twin.payments.paypal import PayPalConfig, PayPalTransport, SandboxTransport
from twin.planner.model import DETAIL_LIMIT, providers_configured, route_details
from twin.planner.tools import ToolError, parse_calls
from twin.payments.rails import SANDBOX_RAIL, load_catalog
from twin.store import Store
from twin.world import reconcile
from twin.world.heartbeat import advance, unwired
from twin.world.memory import WINDOWS, summarise
from twin.world.scene import scene_payload
from twin.world.session import Session

_cache: dict[str, Session] = {}
_store: Store | None = None
_demo: Session | None = None
_reconciler: reconcile.ReconciliationLoop | None = None
_store_opening = threading.Lock()


def store() -> Store:
    """The one connection every request writes through, opened by whoever asks first.

    A browser boots two systems at once, so two first requests can arrive before
    either has finished opening the connection. The second waits rather than standing
    up a second connection to a server that is mid-transaction.
    """
    global _store
    if _store is None:
        with _store_opening:
            if _store is None:
                _store = Store()
    return _store


def reset_state() -> None:
    """Drop every cached world. Tests and a restart both come through here."""
    global _store, _demo, _reconciler
    _cache.clear()
    if _reconciler is not None:
        _reconciler.stop()
        _reconciler = None
    if _store is not None:
        _store.close()
    _store = None
    _demo = None
    firm_service.reset()


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


DEVICE_HEADER = "X-Twin-Device"
# A device id has to be long enough that nobody could guess their way into another
# table. A short one is read as absent rather than trusted, because a headset with a
# six-character id is an invitation, not a credential.
DEVICE_MIN_LEN, DEVICE_MAX_LEN = 32, 128

# An executive figure reads deeper than the twin's own working memory: a session holds
# MEMORY_ROWS so a planner can be told what it just did, and a summary is asked about a
# quarter's worth of decisions. Two different questions, so two different windows.
SUMMARY_ROWS = 500


def device_key(request: Request) -> str:
    raw = request.headers.get(DEVICE_HEADER, "").strip().lower()
    if not DEVICE_MIN_LEN <= len(raw) <= DEVICE_MAX_LEN:
        return ""
    return raw if all(char in "0123456789abcdef" for char in raw) else ""


_world_opening = threading.Lock()


def ensure_world(user_id: str) -> None:
    """Give an account the fictional ledger, unless something already gave it one.

    Two first visits from one device race here. The loser must not seed the world the
    winner has just written: SQLite would refuse the duplicate row, and a table that
    cannot be read is a table that draws nothing.
    """
    with _world_opening:
        if store().world_row(user_id) is None:
            Session.seed_new_world(store(), user_id)


def current_user(request: Request) -> str:
    """Whose table this is: the signed-in account, else the account this device opened.

    Nothing here asks a person to sign up. A request that carries neither a token nor
    a device id still answers 401, though: without knowing whose world it is, the
    service would be guessing which ledger to move money in.
    """
    user_id = store().user_for_token(bearer_token(request))
    if user_id is None:
        device = device_key(request)
        if not device:
            raise HTTPException(status_code=401, detail="send an access token or a device key")
        user_id = store().user_for_device(device) or store().create_anonymous_user(device)
    # An account and its world are written in two steps, and a browser boots two
    # systems at once, so a request can name an account whose ledger has not landed
    # yet. It waits here rather than being handed an empty table.
    ensure_world(user_id)
    return user_id


def world_of(user_id: str = Depends(current_user)) -> Session:
    return session_for(user_id)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Background reconciliation is opt-in: it needs a transport that can answer a lookup.

    The audit firm is opened the same way. A sidecar named by `TWIN_CHAIN_URL` is probed once
    here and every role of the firm is put on it, so the first review writes agreements
    instead of racing a registration. No url, or no answer, costs one short timeout at boot and
    is then said by every endpoint that needs a chain - because a firm that cannot reach its
    contract still has an opinion, and hiding that is worse than reporting it.
    """
    global _reconciler
    _reconciler = reconcile.start(store())
    firm_service.service().chain()
    try:
        yield
    finally:
        if _reconciler is not None:
            _reconciler.stop()
            _reconciler = None


app = FastAPI(title="Tabletop Twin", version="0.3.0", lifespan=lifespan)
# The immersive client is served by the IWSDK dev server: https on 8081, with a
# self-signed certificate — not Vite's default port. `TWIN_ALLOW_ORIGINS` replaces
# this list rather than adding to it, because a served deployment has no reason to
# keep a developer's laptop origin in it.
_origins = [o for o in os.environ.get(
    "TWIN_ALLOW_ORIGINS", "https://localhost:8081,https://127.0.0.1:8081").split(",") if o]
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
    country: str = Field(default="", max_length=2, pattern="^[A-Za-z]{0,2}$")
    currency: str = Field(default="", max_length=3, pattern="^[A-Za-z]{0,3}$")
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


class RailIn(BaseModel):
    rail: str = Field(min_length=1, max_length=32)


# The engagement fields the firm's own case type declares as tuples, so a posted list has to
# become one before the frozen dataclass is built.
TUPLE_FIELDS = ("non_audit_services", "prior_audit_fees_cents", "prior_non_audit_fees_cents",
                "register_particulars")


class EngagementIn(BaseModel):
    """One engagement to put in front of the firm: an index into the derived cases, plus the
    figures this client's file says differently.

    The bounds are on the shape of a figure, never on what it means. The thresholds belong to the
    corpus, so a caller that sends 70.0001 % of an audit fee is not told it is under the cap —
    and a caller cannot send a threshold at all.
    """

    engagement: int = Field(ge=0)
    audit_fee_cents: int | None = Field(default=None, ge=0, le=100_000_000_000)
    non_audit_fee_cents: int | None = Field(default=None, ge=0, le=100_000_000_000)
    non_audit_services: list[Annotated[str, Field(min_length=1, max_length=120)]] | None = Field(
        default=None, max_length=8)
    firm_fee_from_client_cents: int | None = Field(default=None, ge=0, le=100_000_000_000)
    firm_total_fees_cents: int | None = Field(default=None, ge=0, le=100_000_000_000)
    is_pie: bool | None = None
    is_group: bool | None = None
    turnover_eur: float | None = Field(default=None, ge=0, le=1e14)
    balance_sheet_eur: float | None = Field(default=None, ge=0, le=1e14)
    employees: float | None = Field(default=None, ge=0, le=1e8)
    parent_holding_percent: float | None = Field(default=None, ge=0, le=100)
    years_auditing: int | None = Field(default=None, ge=0, le=99)
    partner_years: int | None = Field(default=None, ge=0, le=99)
    previously_audited: bool | None = None
    years_since_previous: int | None = Field(default=None, ge=0, le=99)
    tender_held: bool | None = None
    kyc_checked_years_ago: int | None = Field(default=None, ge=0, le=99)
    file_retention_years: int | None = Field(default=None, ge=0, le=99)
    fee_arrangement: Annotated[str, Field(min_length=1, max_length=120)] | None = None
    non_audit_years: int | None = Field(default=None, ge=0, le=99)
    prior_audit_fees_cents: list[Annotated[int, Field(ge=0, le=100_000_000_000)]] | None = Field(
        default=None, max_length=8)
    prior_non_audit_fees_cents: list[Annotated[int, Field(ge=0, le=100_000_000_000)]] | None = Field(
        default=None, max_length=8)
    months_since_year_end: int | None = Field(default=None, ge=0, le=24)
    transparency_published: bool | None = None
    transparency_kept_years: int | None = Field(default=None, ge=0, le=99)
    audit_report_issued: bool | None = None
    committee_report_issued: bool | None = None
    register_status: Annotated[str, Field(min_length=1, max_length=60)] | None = None
    register_particulars: list[Annotated[str, Field(min_length=1, max_length=4)]] | None = Field(
        default=None, max_length=8)
    sustainability_assurance: bool | None = None

    def changes(self) -> dict:
        """Only the figures somebody actually sent, so an untouched one stays the derived one."""
        changes = self.model_dump(exclude_unset=True, exclude={"engagement"})
        # JSON has no tuple. Left as a list it would sit in a field the engagement declares as
        # one, and a frozen dataclass holding a list cannot be hashed.
        for name in TUPLE_FIELDS:
            if name in changes:
                changes[name] = tuple(changes[name] or ())
        return changes


# ------------------------------------------------------------------- accounts


@app.post("/v1/signup")
def signup(body: SignUp, request: Request) -> dict:
    """Claim an email for this device's world, or open a new one if it has none.

    Signing up after the fact is not a second table. The anonymous account that the
    device already owns gains an email and a password, so everything that was on the
    world before — payments, forks, the audit trail — is still there afterwards. It
    happens once: after that the credentials belong to the account, not to the device.
    """
    device = device_key(request)
    user_id = store().user_for_device(device) if device else None
    if user_id is not None and store().has_password(user_id):
        # One world is claimed once. Rewriting the email and the password of an
        # account that already has both is signing in, and signup refuses to do it.
        raise HTTPException(status_code=409, detail="this table already has an account — sign in to it")
    if user_id is not None:
        try:
            store().claim_account(user_id, body.email, body.name, body.password)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        ensure_world(user_id)
    else:
        try:
            user_id = store().create_user(body.email, body.name, body.password)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        Session.seed_new_world(store(), user_id)
        if device:
            store().bind_device(user_id, device)
    return {"token": store().issue_token(user_id), "user_id": user_id, "name": store().user_name(user_id)}


@app.post("/v1/login")
def login(body: SignIn, request: Request) -> dict:
    user_id = store().verify_password(body.email, body.password)
    if user_id is None:
        raise HTTPException(status_code=401, detail="that email and password do not match")
    # A device that has no world of its own joins the one it signed into. A device
    # that already owns one is left alone: its anonymous table keeps existing, and
    # the token decides which world this browser looks at from now on.
    device = device_key(request)
    if device and store().user_for_device(device) is None:
        store().bind_device(user_id, device)
    return {"token": store().issue_token(user_id), "user_id": user_id, "name": store().user_name(user_id)}


@app.post("/v1/logout")
def logout(request: Request) -> dict:
    """Forget this token. The device behind it still opens the same world.

    A headset has no keyboard to sign back in with, so revoking the credential that
    was handed out must not also revoke the table itself.
    """
    store().revoke_token(bearer_token(request))
    return {"signed_out": True}


@app.get("/v1/me")
def me(user_id: str = Depends(current_user)) -> dict:
    s = session_for(user_id)
    return {
        "user_id": user_id,
        "name": store().user_name(user_id),
        "signed_in": store().has_password(user_id),
        "persona": s.persona.name,
        "day": s.day,
        "horizon_days": s.horizon_days,
        "events": len(s.ledger.events),
    }


@app.get("/v1/health")
def health() -> dict:
    s = demo_session()
    spoken = getattr(s.planner, "last_route", "")
    return {
        "ok": True,
        "persona": s.persona.name,
        "planner": s.planner.name,
        "route": spoken or getattr(s.planner, "route", s.planner.name),
        # An unspoken route is an intention read out of the environment, not a
        # measurement: nobody has been asked anything yet, so nothing proves the
        # endpoint answers.
        "route_is_measured": bool(spoken),
        "model_providers": providers_configured(),
        "model_routes": route_details(),
        "heartbeat_steps": [step.slug for step in s.persona.steps],
        "heartbeat_unwired": unwired(s),
        "paypal_configured": PayPalConfig.from_env() is not None,
        "settlement_rail": s.rail,
        "rails_compiled_on": load_catalog().compiled_on,
        "reconciler": _reconciler.status() if _reconciler else {"running": False, "reason": reconciler_refusal()},
        "accounts": True,
        "audit": firm_service.service().health(),
    }


def reconciler_refusal() -> str:
    """Why nobody is sweeping overnight, said plainly instead of left blank."""
    if reconcile.interval_sec() <= 0:
        return "TWIN_RECONCILE_SEC is not set"
    if PayPalConfig.from_env() is None:
        return "settlement is on the sandbox fake, which forgets what it charged when it restarts"
    return "the loop has not started yet"


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


@app.post("/v1/ask/stream")
def ask_stream(body: Ask, s: Session = Depends(world_of)) -> StreamingResponse:
    """The same ask, spoken a sentence at a time while it is being phrased.

    A `delta` frame is never a raw token: the planner releases only a finished
    sentence whose numbers it has already checked against the forecast. The `done`
    frame carries the whole answer and is the one the table writes down, so a
    narration that got frozen mid-sentence is replaced by a verified sentence
    rather than left half-spoken on the panel.
    """
    out: queue.Queue = queue.Queue()

    def speak() -> None:
        try:
            answer = s.ask(body.intent, on_delta=lambda piece: out.put(("delta", {"text": piece})))
            answer["scene"] = scene_payload(s)
            s.persist()
            out.put(("done", answer))
        except Exception as error:  # a world that cannot finish must still say so on the wire
            out.put(("failed", {"error": " ".join(str(error).split())[:DETAIL_LIMIT]}))
        finally:
            out.put(None)

    def frames():
        worker = threading.Thread(target=speak, daemon=True, name="twin-narration")
        worker.start()
        while True:
            item = out.get()
            if item is None:
                return
            name, payload = item
            yield f"event: {name}\ndata: {json.dumps(payload, sort_keys=True)}\n\n"

    return StreamingResponse(frames(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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
def reconcile_payment(body: ActionRef, s: Session = Depends(world_of)) -> dict:
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


@app.put("/v1/rail")
def choose_rail(body: RailIn, s: Session = Depends(world_of)) -> dict:
    """Point this world at the rail money leaves by.

    A rail the deployment has no transport for is refused rather than pretended:
    the twin can still quote its prices, because a quote is arithmetic.
    """
    rail = load_catalog().rails.get(body.rail)
    if rail is None and body.rail != SANDBOX_RAIL:
        raise HTTPException(status_code=404, detail=f"'{body.rail}' is not a rail this twin knows")
    if rail is None:
        s.set_rail(SANDBOX_RAIL, SandboxTransport())
    elif rail.transport == "paypal":
        config = PayPalConfig.from_env()
        if config is None:
            raise HTTPException(status_code=503, detail="PAYPAL_CLIENT_ID and PAYPAL_SECRET are not set")
        s.set_rail(rail.name, PayPalTransport(config))
    else:
        raise HTTPException(
            status_code=501,
            detail=f"{rail.label} has no transport adapter here; the twin can price it but not settle on it",
        )
    s.persist()
    return {"rail": s.rail, "transport": type(s.transport).__name__, **({"settlement_note": rail.settlement_note} if rail else {})}


@app.get("/v1/rails")
def rails(country: str = "", amount_cents: int = 0, s: Session = Depends(world_of)) -> dict:
    """What this world's rails cost for one payment, and which of them cannot reach at all."""
    catalog = load_catalog()
    payload = {
        "settles_on": s.rail,
        "sender_country": s.ledger.country,
        "sender_currency": s.ledger.currency,
        "compiled_on": catalog.compiled_on,
        "note": catalog.note,
    }
    if country:
        payload["country"] = country.upper()
        payload["reachable"] = catalog.reachable(country.upper(), s.ledger.country, s.ledger.currency)
    if amount_cents > 0:
        payload["quotes"] = catalog.quote(
            amount_cents,
            sender_country=s.ledger.country,
            recipient_country=country.upper(),
            sender_currency=s.ledger.currency,
        )
    return payload


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
        "currency": s.ledger.currency,
        "country": s.ledger.country,
        "events": [
            {
                "id": e.id,
                "label": e.label,
                "kind": e.kind.value,
                "direction": e.direction.value,
                "amount_cents": e.amount_cents,
                "due_day": e.due_day,
                "counterparty": e.counterparty,
                "country": e.country,
                "currency": e.currency,
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
def summary(window: str = "all", s: Session = Depends(world_of), user_id: str = Depends(current_user)) -> dict:
    """What the trail says, over the whole history or only over the days being asked about.

    A bad window name is a 422 rather than a silent fall back to *all*: an executive
    figure that quietly stopped being about today is the kind of number nobody notices.
    """
    if window not in WINDOWS:
        raise HTTPException(status_code=422, detail=f"'{window}' is not one of {sorted(WINDOWS)}")
    unresolved = sum(1 for r in s.machine.all() if r.state not in TERMINAL)
    return summarise(
        store().read_log(user_id, limit=SUMMARY_ROWS),
        persona=s.persona.name,
        day=s.day,
        open_payments=unresolved,
        window=window,
    )


@app.get("/v1/payments")
def payments(s: Session = Depends(world_of)) -> dict:
    return {
        "records": [
            {
                "action_id": record.action_id,
                "amount_cents": record.amount_cents,
                "currency": record.currency,
                "rail": record.rail,
                "fee_cents": record.fee_cents,
                "recipient": record.recipient,
                "country": record.country,
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


# ------------------------------------------------------------ the audit firm
#
# These routes are the only place the firm is reachable from a table. They are deliberately
# shaped like the rest of the service: a reply that cannot do a thing says why rather than
# returning an empty list, because an empty agreement list is indistinguishable from a firm
# that opened none.


@app.get("/v1/firm")
def firm() -> dict:
    """Who is hired, on what numbers, standing on what. No world, no writes, no key needed."""
    return firm_service.brief()


@app.get("/v1/firm/engagements")
def firm_engagements() -> dict:
    """The engagements the derived thresholds make interesting, with every figure they hold."""
    return {"engagements": [firm_service.engagement_card(index, case)
                            for index, case in enumerate(firm_service.engagements())]}


@app.post("/v1/firm/review")
def firm_review(body: EngagementIn, user_id: str = Depends(current_user),
                s: Session = Depends(world_of)) -> dict:
    """Every agent answers one engagement, and what they bind each other to is written down."""
    cases = firm_service.engagements()
    if body.engagement >= len(cases):
        raise HTTPException(status_code=422,
                            detail=f"engagement {body.engagement} is past the end of a corpus "
                                   f"with {len(cases)} cases")
    case = dataclasses.replace(cases[body.engagement], **body.changes())
    return firm_service.service().review(case, store(), user_id, s.day)


@app.get("/v1/firm/agreements")
def firm_agreements() -> dict:
    """What the contract holds, and which of it is waiting on a human signature."""
    return firm_service.service().agreements()


@app.get("/v1/firm/transcript")
def firm_transcript(limit: int = 60, role: str = "", user_id: str = Depends(current_user),
                    s: Session = Depends(world_of)) -> dict:
    """Every message this world's agents sent, including the attempts the contract refused."""
    bus = firm_service.service().bus(store(), user_id, s.day)
    if bus is None:
        return {"messages": [], "chain": firm_service.service().health()}
    rows = bus.transcript(limit=min(max(limit, 1), 500), role=role or None)
    return {"messages": rows, "count": len(rows)}


@app.get("/v1/firm/inbox")
def firm_inbox(role: str, after: int = 0) -> dict:
    """One agent's mail, as the chain emitted it, from a transaction cursor onwards."""
    hired = {agent["role"] for agent in firm_service.roster().get("agents") or []}
    if role not in hired:
        raise HTTPException(status_code=422, detail=f"'{role}' is not a role on the roster")
    return firm_service.service().inbox(role, max(after, 0))
