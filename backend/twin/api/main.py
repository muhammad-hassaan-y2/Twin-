"""The HTTP edge of the twin.

One visitor, one table, one world. The client sends gestures and scrub positions;
this answers with numbers it computed and sentences the persona is allowed to
say. Nothing here trusts a value that arrived over the network to decide whether
money moves.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from twin.payments.machine import IllegalTransition
from twin.payments.paypal import PayPalConfig, PayPalTransport
from twin.planner.tools import ToolError, parse_calls
from twin.world.heartbeat import advance, tick
from twin.world.scene import scene_payload
from twin.world.session import Session

_state: dict[str, Session] = {}


def session() -> Session:
    if "s" not in _state:
        _state["s"] = Session.build()
    return _state["s"]


app = FastAPI(title="Tabletop Twin", version="0.1.0")
# The immersive client is served from the IWSDK dev server on its own port.
_origins = [o for o in os.environ.get("TWIN_ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if o]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Ask(BaseModel):
    intent: str = Field(min_length=1, max_length=400)


class Calls(BaseModel):
    calls: list[dict]


class Gesture(BaseModel):
    action_id: str
    gesture: str


class Scrub(BaseModel):
    day: int = Field(ge=0, le=179)


class Pull(BaseModel):
    event_id: str


class Tick(BaseModel):
    days: int = Field(default=1, ge=0, le=30)
    final_of_day: bool = False


class ActionRef(BaseModel):
    action_id: str


@app.get("/v1/health")
def health() -> dict:
    s = session()
    return {
        "ok": True,
        "persona": s.persona.name,
        "planner": s.planner.name,
        "route": getattr(s.planner, "last_route", s.planner.name),
        "heartbeat_steps": [step.slug for step in s.persona.steps],
        "paypal_configured": PayPalConfig.from_env() is not None,
    }


@app.get("/v1/world")
def world() -> dict:
    return scene_payload(session())


@app.post("/v1/ask")
def ask(body: Ask) -> dict:
    s = session()
    answer = s.ask(body.intent)
    answer["scene"] = scene_payload(s)
    return answer


@app.post("/v1/tools")
def tools(body: Calls) -> dict:
    """Run tool calls the client already knows the names of — the same validator a model's reply goes through."""
    s = session()
    try:
        calls = parse_calls(body.calls)
    except ToolError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"results": [s.run(call) for call in calls], "scene": scene_payload(s)}


@app.post("/v1/scrub")
def scrub(body: Scrub) -> dict:
    s = session()
    s.day = min(body.day, s.horizon_days - 1)
    return {"day": s.day, "scene": scene_payload(s)}


@app.post("/v1/pull")
def pull(body: Pull) -> dict:
    """A pipe yanked out of the world. Returns the second miniature and its delta."""
    s = session()
    try:
        event = s.ledger.by_id(body.event_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="no such event") from exc
    if not event.is_cancellable():
        raise HTTPException(status_code=409, detail=f"{event.label} is not a pipe you can pull")
    result = s.tool_fork(f"cancel {event.label}", cancel_event_ids=[event.id])
    return {"fork": result, "scene": scene_payload(s)}


@app.post("/v1/tick")
def heartbeat(body: Tick) -> dict:
    s = session()
    utterances = advance(s, body.days, body.final_of_day)
    return {"day": s.day, "captions": [u.to_dict() for u in utterances], "scene": scene_payload(s)}


@app.post("/v1/approve")
def approve(body: Gesture) -> dict:
    s = session()
    try:
        return s.approve(body.action_id, body.gesture)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="nothing pending under that action id") from exc


@app.post("/v1/reconcile")
def reconcile(body: ActionRef) -> dict:
    s = session()
    try:
        return s.reconcile(body.action_id)
    except IllegalTransition as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/v1/blackout")
def blackout(body: ActionRef) -> dict:
    """Teach the unknown state on demand: the provider takes the money and the reply is lost."""
    s = session()
    key = s.pending.get(body.action_id)
    if key is None:
        raise HTTPException(status_code=404, detail="nothing pending under that action id")
    s.transport.blackout_keys.add(key)
    return {"action_id": body.action_id, "armed": True}


@app.post("/v1/transport")
def use_real_transport() -> dict:
    """Swap the sandbox fake for the live PayPal client. Needs env credentials; refuses without them."""
    config = PayPalConfig.from_env()
    if config is None:
        raise HTTPException(status_code=503, detail="PAYPAL_CLIENT_ID and PAYPAL_SECRET are not set")
    s = session()
    s.transport = PayPalTransport(config)
    return {"transport": "paypal", "environment": config.environment}


@app.get("/v1/persona")
def persona() -> dict:
    s = session()
    return {
        "name": s.persona.name,
        "voice": s.persona.voice_prompt,
        "prohibitions": list(s.persona.prohibitions),
        "heartbeat": [{"slug": step.slug, "index": step.index, "title": step.title} for step in s.persona.steps],
    }
