"""The running world one visitor owns.

Everything the orb says is assembled from a value produced here. The planner
picks which tool to run; this module is the only thing that can compute, spend,
or remember.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from twin.data import load_persona_ledger
from twin.domain.events import CashEvent, Direction, Ledger
from twin.domain.forecast import Forecast, forecast_ledger
from twin.domain.interventions import Branch, compare, fork
from twin.domain.learning import Calibration, Outcome, Prediction
from twin.payments.machine import ApprovalRequired, PaymentMachine, PaymentState
from twin.payments.paypal import SandboxTransport
from twin.persona.persona import Persona, load_persona
from twin.planner.model import ModelPlanner
from twin.planner.rules import RulePlanner
from twin.planner.tools import ToolCall, handler_map, parse_calls
from twin.policy.engine import Action, Policy, SpendWindow, evaluate

DEFAULT_HORIZON = 90
DEFAULT_RUNS = 2000
SEED = 20261028
# Only these verbs actually take money out the door, so only these may enter the
# payment machine. A chase or a cancellation is a change to the ledger, not a charge.
CHARGE_VERBS = frozenset({"pay_bill", "start_subscription", "shift_payment"})


def dollars(cents: int) -> float:
    return round(cents / 100, 2)


@dataclass
class Utterance:
    step: str
    text: str
    target: str = ""

    def to_dict(self) -> dict:
        return {"step": self.step, "text": self.text, "target": self.target}


@dataclass
class Session:
    ledger: Ledger
    policy: Policy
    persona: Persona
    planner: RulePlanner | ModelPlanner
    horizon_days: int = DEFAULT_HORIZON
    runs: int = DEFAULT_RUNS
    day: int = 0
    transport: SandboxTransport = field(default_factory=SandboxTransport)
    machine: PaymentMachine = field(default_factory=lambda: PaymentMachine(approval_floor_cents=5_000))
    calibration: Calibration = field(default_factory=Calibration)
    window: SpendWindow = field(default_factory=SpendWindow)
    branches: dict[str, Branch] = field(default_factory=dict)
    focus: str = ""
    last_speech: str = ""
    log: list[dict] = field(default_factory=list)
    pending: dict[str, str] = field(default_factory=dict)
    actions: dict[str, Action] = field(default_factory=dict)
    spoken_recently: set[str] = field(default_factory=set)
    tested_on_day: int = -1
    _baseline: Forecast | None = None

    @classmethod
    def build(cls, path: Path | None = None, use_model: bool = True) -> "Session":
        ledger, policy, history = load_persona_ledger(path)
        persona = load_persona(persona_id=ledger.persona_id)
        planner: RulePlanner | ModelPlanner = ModelPlanner.from_env() or RulePlanner()
        if isinstance(planner, ModelPlanner):
            planner.voice_prompt = persona.voice_prompt
        session = cls(ledger=ledger, policy=policy, persona=persona, planner=planner)
        session.machine = PaymentMachine(approval_floor_cents=policy.approval_floor_cents)
        session.calibration = Calibration([_prediction(raw) for raw in history])
        session.branches["baseline"] = Branch(key="baseline", label="As things stand", forecast=session.baseline)
        return session

    # ---------------------------------------------------------------- numbers

    @property
    def baseline(self) -> Forecast:
        if self._baseline is None:
            self._baseline = forecast_ledger(
                self.ledger, horizon_days=self.horizon_days, runs=self.runs, seed=SEED
            )
        return self._baseline

    def planner_context(self) -> dict:
        return {
            "horizon_days": self.horizon_days,
            "day": self.day,
            "balance_cents": self.baseline.p50[self.day],
            "events": [self._event_brief(e) for e in self.ledger.events],
            "chasable": [
                self._event_brief(e) for e in self.ledger.events if e.is_chasable()
            ],
            "cancellable": [
                self._event_brief(e) for e in self.ledger.events if e.is_cancellable()
            ],
            "voice_prompt": self.persona.voice_prompt,
            "branches": sorted(self.branches),
        }

    @staticmethod
    def _event_brief(event: CashEvent) -> dict:
        return {"id": event.id, "label": event.label, "kind": event.kind.value}

    def forecast_payload(self, forecast: Forecast) -> dict:
        pinch = min(range(forecast.horizon_days), key=lambda d: forecast.p10[d])
        median_low = min(forecast.p50)
        today = min(self.day, forecast.horizon_days - 1)
        return {
            "horizon_days": forecast.horizon_days,
            "runs": forecast.runs,
            "seed": forecast.seed,
            "pinch_day": pinch,
            "shortfall_day": forecast.shortfall_day,
            "min_balance_cents": forecast.min_balance_cents,
            "min_balance_dollars": dollars(forecast.min_balance_cents),
            "median_low_dollars": dollars(median_low),
            "dry_run_percent": round(forecast.dry_run_share * 100),
            "balance_today_cents": forecast.p50[today],
            "balance_today_dollars": dollars(forecast.p50[today]),
            "expected_late_fees_cents": forecast.expected_late_fees_cents,
            "uncertainty_dollars": dollars(forecast.width_cents),
            "dry_prob_today": forecast.dry_prob[today],
        }

    def delta_payload(self, delta) -> dict:
        return {
            "key": delta.key,
            "label": delta.label,
            "min_balance_change_dollars": dollars(delta.min_balance_change_cents),
            "cost_change_dollars": dollars(delta.cost_change_cents),
            "dry_probability_change": delta.dry_probability_change,
            "shortfall_day_change": delta.shortfall_day_change,
            "verdict": delta.verdict,
        }

    # ------------------------------------------------------------------ tools

    def tool_forecast(self, horizon_days: int | None = None, runs: int | None = None) -> dict:
        if horizon_days or runs:
            self.horizon_days = int(horizon_days or self.horizon_days)
            self.runs = int(runs or self.runs)
            self._baseline = None
        return {"forecast": self.forecast_payload(self.baseline)}

    def tool_fork(
        self,
        label: str,
        cancel_event_ids: list[str] | None = None,
        chase_event_ids: list[str] | None = None,
        shift: dict[str, int] | None = None,
    ) -> dict:
        cancelled = frozenset(self._known(cancel_event_ids or []))
        chased = frozenset(self._known(chase_event_ids or []))
        moves = {str(k): int(v) for k, v in (shift or {}).items() if k in self.ledger.ids()}
        key = _slug(label) or f"branch-{len(self.branches)}"
        branch = Branch(
            key=key,
            label=label,
            forecast=self.baseline,
            cancelled_ids=cancelled,
            chase_ids=chased,
            shifted=tuple(sorted(moves.items())),
        )
        worlds = fork(
            self.ledger,
            self.branches["baseline"],
            [branch],
            horizon_days=self.horizon_days,
            runs=self.runs,
            seed=SEED,
        )
        world = worlds[key]
        delta = compare(self.branches["baseline"], world)
        self.branches[key] = world
        return {"branch": key, "label": label, "forecast": self.forecast_payload(world.forecast), "delta": self.delta_payload(delta)}

    def tool_highlight(self, target: str, id: str | None = None, note: str = "") -> dict:
        if target == "driest":
            day = self.baseline.p10.index(min(self.baseline.p10))
            self.focus = f"day:{day}"
            return {"highlight": self.focus, "day": day, "note": note}
        if target == "day" and id is not None:
            day = max(0, min(int(id), self.horizon_days - 1))
            self.focus = f"day:{day}"
            return {"highlight": self.focus, "day": day, "p10_cents": self.baseline.p10[day], "p90_cents": self.baseline.p90[day], "note": note}
        if target == "event" and id:
            event = self.ledger.by_id(id)
            self.focus = f"event:{event.id}"
            return {"highlight": self.focus, "label": event.label, "due_day": event.due_day, "note": note}
        if target == "branch" and id and id in self.branches:
            self.focus = f"branch:{id}"
            return {"highlight": self.focus, "label": self.branches[id].label, "note": note}
        self.focus = ""
        return {"highlight": None, "note": note}

    def tool_propose_action(
        self,
        verb: str,
        event_id: str | None = None,
        amount_cents: int = 0,
        recipient: str = "",
        justification: str = "",
    ) -> dict:
        event = self.ledger.by_id(event_id) if event_id else None
        amount = int(amount_cents or (event.amount_cents if event else 0))
        who = recipient or (event.counterparty if event else "")
        is_charge = verb in CHARGE_VERBS
        action = Action(
            id=f"act-{uuid.uuid4().hex[:8]}",
            verb=verb,
            amount_cents=amount,
            recipient=who,
            justification=justification,
            direction=("in" if event and event.direction is Direction.IN else "out") if is_charge else "none",
        )
        decision = evaluate(action, self.policy, self.window, self.day)
        self.log.append({"day": self.day, "tool": "propose_action", "verb": verb, "verdict": decision.verdict.value, "rule": decision.rule})
        payload = {
            "action_id": action.id,
            "verb": verb,
            "amount_cents": amount,
            "recipient": who,
            "verdict": decision.verdict.value,
            "reason": decision.reason,
            "rule": decision.rule,
            "state": None,
            "idempotency_key": None,
        }

        if not is_charge:
            # Chasing or cancelling moves nothing today, so it never enters the machine.
            # A refused verb is not even simulated: the twin does not get to rehearse a
            # thing it is not allowed to do.
            if decision.verdict.value == "deny":
                payload["blocked"] = decision.reason
            else:
                payload["effect"] = self._fork_for(verb, event)
            return payload

        record = self.machine.open(action.id, amount, who)
        self.machine.propose(record)
        payload["state"] = record.state.value
        payload["idempotency_key"] = record.idempotency_key
        self.pending[action.id] = record.idempotency_key
        self.actions[action.id] = action
        if decision.verdict.value == "deny":
            payload["state"] = self.machine.cancel(record, f"policy: {decision.rule}").state.value
        elif decision.verdict.value == "allow":
            # Below the floor the policy itself is the approval; there is no gesture to wait for.
            self.machine.approve(record, "auto")
            payload["state"] = self._settle(record).value
        return payload

    def _fork_for(self, verb: str, event: CashEvent | None) -> dict:
        if event is None:
            return {"skipped": f"{verb} names no ledger event"}
        if verb == "chase_invoice" and event.is_chasable():
            return self.tool_fork(f"chase {event.label}", chase_event_ids=[event.id])
        if verb == "cancel_subscription" and event.is_cancellable():
            return self.tool_fork(f"cancel {event.label}", cancel_event_ids=[event.id])
        return {"skipped": f"{verb} is not available for {event.label}"}

    # ------------------------------------------------------------- gestures

    def approve(self, action_id: str, gesture: str) -> dict:
        key = self.pending.get(action_id)
        if key is None:
            raise KeyError(f"nothing pending for {action_id}")
        record = self.machine.get(key)
        try:
            self.machine.approve(record, gesture)
        except ApprovalRequired as exc:
            return {"action_id": action_id, "state": record.state.value, "error": str(exc)}
        state = self._settle(record)
        return {"action_id": action_id, "state": state.value, "idempotency_key": record.idempotency_key}

    def reconcile(self, action_id: str) -> dict:
        record = self.machine.get(self.pending[action_id])
        state = self.machine.reconcile(record, self.transport).state
        if state is PaymentState.SUCCEEDED:
            self.machine.verify_outcome(record, f"{record.recipient} settled")
        return {"action_id": action_id, "state": state.value}

    def _settle(self, record) -> PaymentState:
        """Submit a record that is already APPROVED, then look for its effect."""
        self.machine.submit(record, self.transport)
        if record.state is PaymentState.SUCCEEDED:
            self.machine.verify_outcome(record, f"{record.recipient} settled")
            action = self.actions.get(record.action_id)
            self.window.record(self.day, action or Action(id=record.action_id, verb="pay_bill", amount_cents=record.amount_cents))
        return record.state

    def _known(self, ids: list[str]) -> list[str]:
        valid = self.ledger.ids()
        return [i for i in ids if i in valid]

    # ------------------------------------------------------------- dispatch

    def run(self, call: ToolCall) -> dict:
        handlers = handler_map(self)
        return handlers[call.tool](**call.args)

    def ask(self, intent: str) -> dict:
        context = self.planner_context()
        calls = self.planner.plan(intent, context)
        results = []
        for call in calls:
            try:
                results.append(self.run(call))
            except KeyError as exc:
                results.append({"error": f"unknown event '{exc.args[0]}'"})
        narration = self.planner.narrate(intent, results, context)
        self.last_speech = narration
        self.log.append({"day": self.day, "intent": intent, "route": getattr(self.planner, "last_route", self.planner.name)})
        return {"intent": intent, "calls": [c.tool for c in calls], "results": results, "said": narration, "focus": self.focus}


def _slug(text: str) -> str:
    out = "".join(c.lower() if c.isalnum() else "-" for c in text)
    return "-".join(part for part in out.split("-") if part)[:32]


def _prediction(raw: dict) -> Prediction:
    return Prediction(
        id=raw["id"],
        subject=raw["subject"],
        statement=raw["statement"],
        probability=float(raw["probability"]),
        made_on_day=int(raw["made_on_day"]),
        resolves_on_day=int(raw["resolves_on_day"]),
        outcome=Outcome(raw.get("outcome", "open")),
        tool=raw.get("tool", "forecast"),
    )
