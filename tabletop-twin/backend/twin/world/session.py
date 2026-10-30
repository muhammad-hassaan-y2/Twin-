"""The running world one visitor owns.

Everything the orb says is assembled from a value produced here. The planner
picks which tool to run; this module is the only thing that can compute, spend,
or remember.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path

from twin.data import load_persona_ledger
from twin.domain.events import CashEvent, Direction, Ledger
from twin.domain.forecast import Forecast, forecast_ledger
from twin.domain.interventions import Branch, compare, fork
from twin.domain.learning import Calibration, Outcome, Prediction
from twin.payments.machine import (
    TERMINAL,
    ApprovalRequired,
    IllegalTransition,
    PaymentMachine,
    PaymentRecord,
    PaymentState,
)
from twin.payments.paypal import PayPalConfig, PayPalTransport, SandboxTransport
from twin.payments.rails import SANDBOX_RAIL, Rail, load_catalog
from twin.persona.persona import Persona, load_persona
from twin.planner.model import ModelPlanner
from twin.planner.rules import RulePlanner
from twin.planner.tools import ToolCall, handler_map, parse_calls
from twin.policy.engine import Action, Policy, SpendWindow, evaluate
from twin.store import Store

DEFAULT_HORIZON = 90
DEFAULT_RUNS = 2000
SEED = 20261028
# Only these verbs actually take money out the door, so only these may enter the
# payment machine. A chase or a cancellation is a change to the ledger, not a charge.
CHARGE_VERBS = frozenset({"pay_bill", "start_subscription", "shift_payment"})


def dollars(cents: int) -> float:
    """Minor units as a number the client can print.

    Every money field in the payload is called "dollars" even when the ledger is
    denominated in yen: the shape of the scene does not change with the currency,
    and `meta.currency` says what the numbers are actually in.
    """
    return round(cents / 100, 2)


def transport_for(rail_name: str):
    """The transport that can walk this rail, or None if this deployment cannot.

    A rail is a promise about how money leaves. Without the credentials behind it
    the honest answer is that nothing settles here, so the caller is told to fall
    back rather than being handed a fake that matches the name.
    """
    rail = load_catalog().rails.get(rail_name)
    if rail is None:
        return SandboxTransport()
    if rail.transport == "paypal":
        config = PayPalConfig.from_env()
        return None if config is None else PayPalTransport(config)
    return None


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
    rail: str = SANDBOX_RAIL
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
    settled_days: dict[str, int] = field(default_factory=dict)
    store: Store | None = None
    user_id: str = ""
    _baseline: Forecast | None = None

    @classmethod
    def build(cls, path: Path | None = None, use_model: bool = True) -> "Session":
        ledger, policy, history = load_persona_ledger(path)
        persona = load_persona(persona_id=ledger.persona_id)
        planner: RulePlanner | ModelPlanner = (ModelPlanner.from_env() if use_model else None) or RulePlanner()
        if isinstance(planner, ModelPlanner):
            planner.voice_prompt = persona.voice_prompt
        session = cls(ledger=ledger, policy=policy, persona=persona, planner=planner)
        session.machine = PaymentMachine(approval_floor_cents=policy.approval_floor_cents)
        session.calibration = Calibration([_prediction(raw) for raw in history])
        session.branches["baseline"] = Branch(key="baseline", label="As things stand", forecast=session.baseline)
        return session

    @classmethod
    def restore(cls, store: Store, user_id: str) -> "Session":
        """Rebuild a visitor's world from the database, exactly as they left it."""
        row = store.world_row(user_id)
        if row is None:
            raise KeyError("that account has no world yet")
        ledger = store.ledger_for(
            user_id, row["persona_id"], int(row["opening_balance_cents"]),
            currency=row.get("currency") or "USD", country=row.get("country") or "",
        )
        policy = store.policy_for(user_id, ledger)
        persona = load_persona(persona_id=ledger.persona_id)
        planner: RulePlanner | ModelPlanner = ModelPlanner.from_env() or RulePlanner()
        if isinstance(planner, ModelPlanner):
            planner.voice_prompt = persona.voice_prompt
        session = cls(ledger=ledger, policy=policy, persona=persona, planner=planner, store=store, user_id=user_id)
        session.machine = PaymentMachine(approval_floor_cents=policy.approval_floor_cents)
        session.day = int(row["day"])
        session.horizon_days = int(row["horizon_days"])
        session.runs = int(row["runs"])
        rail = row.get("rail") or SANDBOX_RAIL
        transport = transport_for(rail)
        if transport is None:
            session.record(
                "rail_reverted",
                {"from": rail, "to": SANDBOX_RAIL, "because": "no transport for that rail in this deployment"},
            )
            rail = SANDBOX_RAIL
            transport = SandboxTransport()
        session.rail = rail
        session.transport = transport
        session.focus = row["focus"]
        session.last_speech = row["last_speech"]
        session.tested_on_day = int(row["tested_on_day"])
        session.calibration = Calibration(store.load_predictions(user_id))
        session._adopt_payments(store.load_payments(user_id))
        session.branches["baseline"] = Branch(key="baseline", label="As things stand", forecast=session.baseline)
        session._refork_saved_branches(store.load_branches(user_id))
        return session

    @classmethod
    def seed_new_world(cls, store: Store, user_id: str) -> "Session":
        """Copy the fictional ledger into a fresh account so the table is alive immediately."""
        ledger, policy, history = load_persona_ledger()
        store.create_world(user_id, ledger, policy)
        session = cls.restore(store, user_id)
        session.calibration = Calibration([_prediction(raw) for raw in history])
        store.save_predictions(user_id, session.calibration.records)
        return session

    def _adopt_payments(self, rows: list[dict]) -> None:
        for row in rows:
            record = PaymentRecord(
                action_id=row["action_id"],
                amount_cents=int(row["amount_cents"]),
                recipient=row["recipient"],
                state=PaymentState(row["state"]),
                attempt=int(row["attempt"]),
                idempotency_key=row["idempotency_key"],
                provider_ref=row["provider_ref"],
                history=[tuple(entry) for entry in json.loads(row["history_json"])],
                verified_outcome=row["verified_outcome"],
                currency=row.get("currency") or "USD",
                rail=row.get("rail") or SANDBOX_RAIL,
                country=row.get("country") or "",
                fee_cents=int(row.get("fee_cents") or 0),
            )
            self.machine.adopt(record)
            action = Action(
                id=record.action_id,
                verb=row["verb"],
                amount_cents=record.amount_cents,
                recipient=record.recipient,
                direction=row["direction"],
                country=record.country,
                currency=record.currency,
            )
            self.actions[record.action_id] = action
            if record.state not in TERMINAL:
                self.pending[record.action_id] = record.idempotency_key
            if record.state is PaymentState.SUCCEEDED:
                settled_day = int(row["settled_day"] or 0)
                self.settled_days[record.idempotency_key] = settled_day
                self.window.record(settled_day, action)

    def _refork_saved_branches(self, definitions: list[dict]) -> None:
        if not definitions:
            return
        worlds = fork(
            self.ledger,
            self.branches["baseline"],
            [
                Branch(
                    key=each["key"],
                    label=each["label"],
                    forecast=self.baseline,
                    cancelled_ids=each["cancelled"],
                    chase_ids=each["chase"],
                    shifted=each["shifted"],
                )
                for each in definitions
            ],
            horizon_days=self.horizon_days,
            runs=self.runs,
            seed=SEED,
        )
        for key, world in worlds.items():
            if key != "baseline":
                self.branches[key] = world

    def persist(self) -> None:
        """Write what this turn changed. A twin that forgets is a toy."""
        if self.store is None or not self.user_id:
            return
        self.store.save_world(
            self.user_id,
            day=self.day,
            horizon_days=self.horizon_days,
            runs=self.runs,
            rail=self.rail,
            focus=self.focus,
            last_speech=self.last_speech,
            tested_on_day=self.tested_on_day,
        )
        self.store.save_predictions(self.user_id, self.calibration.records)
        for record in self.machine.all():
            action = self.actions.get(record.action_id)
            self.store.save_payment(
                self.user_id,
                record,
                verb=action.verb if action else "pay_bill",
                direction=action.direction if action else "out",
                settled_day=self.settled_days.get(record.idempotency_key),
            )
        for key, branch in self.branches.items():
            if key == "baseline":
                continue
            self.store.save_branch(
                self.user_id, key, branch.label, branch.cancelled_ids, branch.chase_ids, branch.shifted
            )

    def record(self, kind: str, payload: dict) -> None:
        """One line in the trail. Everything the twin decided is written, not just said."""
        entry = {"day": self.day, "kind": kind, **payload}
        self.log.append(entry)
        if self.store is not None and self.user_id:
            self.store.append_log(self.user_id, self.day, kind, payload)

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
        country = (event.country if event else "") or self._country_of(who)
        currency = self.ledger.currency
        is_charge = verb in CHARGE_VERBS
        rail = self.active_rail() if is_charge else None
        action = Action(
            id=f"act-{uuid.uuid4().hex[:8]}",
            verb=verb,
            amount_cents=amount,
            recipient=who,
            justification=justification,
            direction=("in" if event and event.direction is Direction.IN else "out") if is_charge else "none",
            country=country,
            currency=currency,
        )
        decision = evaluate(
            action, self.policy, self.window, self.day, rail=rail, sender_country=self.ledger.country
        )
        fee = self._fee_estimate(rail, amount, country, event)
        reason = decision.reason
        if decision.rule == "rail_unavailable":
            alternatives = [
                name
                for name in load_catalog().reachable(country, self.ledger.country, currency)
                if name != self.rail
            ]
            reason = f"{reason}. Rails that could reach it here: {', '.join(alternatives) or 'none the twin knows'}"
        self.record(
            "policy",
            {"tool": "propose_action", "verb": verb, "verdict": decision.verdict.value, "rule": decision.rule,
             "amount_cents": amount, "recipient": who, "country": country, "currency": currency,
             "rail": self.rail, "fee_cents": fee, "reason": reason},
        )
        payload = {
            "action_id": action.id,
            "verb": verb,
            "amount_cents": amount,
            "amount_dollars": dollars(amount),
            "recipient": who,
            "country": country,
            "currency": currency,
            "rail": self.rail,
            "fee_cents": fee,
            "fee_dollars": dollars(fee),
            "verdict": decision.verdict.value,
            "reason": reason,
            "rule": decision.rule,
            "state": None,
            "idempotency_key": None,
        }

        if not is_charge:
            # Chasing or cancelling moves nothing today, so it never enters the machine.
            # A refused verb is not even simulated: the twin does not get to rehearse a
            # thing it is not allowed to do.
            if decision.verdict.value == "deny":
                payload["blocked"] = reason
            else:
                payload["effect"] = self._fork_for(verb, event)
            return payload

        record = self.machine.open(action.id, amount, who, currency=currency, rail=self.rail, country=country)
        record.fee_cents = fee
        self.machine.propose(record)
        payload["state"] = record.state.value
        payload["idempotency_key"] = record.idempotency_key
        self.pending[action.id] = record.idempotency_key
        self.actions[action.id] = action
        if decision.verdict.value == "deny":
            payload["state"] = self.machine.cancel(record, f"policy: {decision.rule}").state.value
            # A policy denial is finished business. Leaving it "pending" would invite a
            # human to reject something that already cannot move.
            self.pending.pop(action.id, None)
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
            self.record("approval_refused", {"action_id": action_id, "gesture": gesture, "reason": str(exc)})
            return {"action_id": action_id, "state": record.state.value, "error": str(exc)}
        self.record("approval", {"action_id": action_id, "gesture": gesture, "recipient": record.recipient,
                                 "amount_cents": record.amount_cents})
        state = self._settle(record)
        return {"action_id": action_id, "state": state.value, "idempotency_key": record.idempotency_key}

    def reject(self, action_id: str, reviewer: str, reason: str) -> dict:
        """A human saying no, out of band. The UI closing a panel is not a decision."""
        key = self.pending.get(action_id)
        if key is None:
            raise KeyError(f"nothing pending for {action_id}")
        record = self.machine.get(key)
        refusal = None
        if record.state in {PaymentState.SUBMITTED, PaymentState.UNKNOWN, PaymentState.RECONCILING}:
            refusal = f"{record.state.value} — the money has already left, so this needs a recall, not a rejection"
        elif record.state in TERMINAL:
            refusal = f"{record.state.value} is already settled"
        # Logged whether or not it lands, so an auditor sees the ask that could not be withdrawn.
        self.record(
            "rejection",
            {"action_id": action_id, "reviewer": reviewer, "reason": reason,
             "state": record.state.value, "applied": refusal is None},
        )
        if refusal is not None:
            raise IllegalTransition(refusal)
        self.machine.cancel(record, f"rejected by {reviewer}: {reason}")
        self.pending.pop(action_id, None)
        return {"action_id": action_id, "state": record.state.value, "rejected": True}

    def retry_payment(self, action_id: str) -> dict:
        """Reachable from a route now: a failed payment can be offered again, an unknown one cannot."""
        key = self.pending.get(action_id)
        if key is None:
            raise KeyError(f"nothing pending for {action_id}")
        record = self.machine.retry(self.machine.get(key))
        self.pending[action_id] = record.idempotency_key
        self.record("retry", {"action_id": action_id, "attempt": record.attempt, "state": record.state.value})
        return {
            "action_id": action_id,
            "state": record.state.value,
            "attempt": record.attempt,
            "idempotency_key": record.idempotency_key,
        }

    def reconcile(self, action_id: str) -> dict:
        key = self.pending.get(action_id)
        if key is None:
            raise KeyError(f"nothing pending for {action_id}")
        record = self.machine.reconcile(self.machine.get(key), self.transport)
        state = record.state
        if state is PaymentState.SUCCEEDED:
            self.machine.verify_outcome(record, f"{record.recipient} settled")
            self.settled_days[record.idempotency_key] = self.day
        self.record("reconcile", {"action_id": action_id, "state": state.value, "recipient": record.recipient})
        return {"action_id": action_id, "state": state.value}

    def _settle(self, record) -> PaymentState:
        """Submit a record that is already APPROVED, then look for its effect."""
        self.machine.submit(record, self.transport)
        if record.state is PaymentState.SUCCEEDED:
            self.machine.verify_outcome(record, f"{record.recipient} settled")
            self.settled_days[record.idempotency_key] = self.day
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
        self.record("intent", {"intent": intent, "route": getattr(self.planner, "last_route", self.planner.name),
                               "calls": [c.tool for c in calls]})
        return {"intent": intent, "calls": [c.tool for c in calls], "results": results, "said": narration, "focus": self.focus}

    # ------------------------------------------------------------------ ledger

    def add_event(self, event: CashEvent, source: str = "manual") -> dict:
        """Connect a workflow: a new bill, income or subscription enters the world."""
        if event.id in self.ledger.ids():
            raise ValueError(f"'{event.id}' is already on the ledger")
        self.ledger = replace(self.ledger, events=(*self.ledger.events, event))
        if event.counterparty and event.counterparty not in self.policy.allowed_recipients:
            self.policy = replace(
                self.policy, allowed_recipients=self.policy.allowed_recipients | {event.counterparty}
            )
            if self.store is not None and self.user_id:
                self.store.put_policy(self.user_id, self.policy)
        self._baseline = None
        if self.store is not None and self.user_id:
            self.store.put_event(self.user_id, event, source)
        self.record("event_added", {"event_id": event.id, "label": event.label, "source": source,
                                    "amount_cents": event.amount_cents})
        return {"event": self._event_brief(event), "added": True}

    def remove_event(self, event_id: str) -> dict:
        event = self.ledger.by_id(event_id)
        open_to = [r for r in self.machine.all() if r.state not in TERMINAL and r.recipient == event.counterparty]
        if open_to:
            raise ValueError(f"{event.label} still has {len(open_to)} open payment(s)")
        dropped = [
            key
            for key, branch in self.branches.items()
            if key != "baseline"
            and (event_id in branch.cancelled_ids or event_id in branch.chase_ids or event_id in dict(branch.shifted))
        ]
        for key in dropped:
            self.branches.pop(key)
        self.ledger = replace(self.ledger, events=tuple(e for e in self.ledger.events if e.id != event_id))
        self._baseline = None
        if self.store is not None and self.user_id:
            self.store.delete_event(self.user_id, event_id)
            for key in dropped:
                self.store.delete_branch(self.user_id, key)
        self.record("event_removed", {"event_id": event_id, "label": event.label, "branches_dropped": dropped})
        return {"removed": event_id, "branches_dropped": dropped}

    def set_opening_balance(self, cents: int) -> dict:
        self.ledger = replace(self.ledger, opening_balance_cents=int(cents))
        self._baseline = None
        if self.store is not None and self.user_id:
            self.store.set_opening_balance(self.user_id, int(cents))
        self.record("opening_balance_set", {"cents": int(cents)})
        return {"opening_balance_cents": int(cents)}

    def set_ceiling(self, recipient: str, cents: int | None) -> dict:
        """A human, not the twin, sets how much one name may take."""
        ceilings = {name: value for name, value in self.policy.recipient_ceilings if name != recipient}
        if cents is not None:
            ceilings[recipient] = int(cents)
        self.policy = replace(self.policy, recipient_ceilings=tuple(sorted(ceilings.items())))
        if self.store is not None and self.user_id:
            self.store.set_recipient_ceiling(self.user_id, recipient, cents)
        self.record("ceiling_set", {"recipient": recipient, "cents": cents})
        return {"recipient": recipient, "ceiling_cents": cents}

    # --------------------------------------------------------------- settlement

    def active_rail(self) -> Rail | None:
        """The rail money leaves by, or None while the transport is the sandbox fake."""
        return load_catalog().rails.get(self.rail)

    def set_rail(self, name: str, transport=None) -> dict:
        """Choose the rail by which this world pays out, and the transport that walks it.

        Both move together: a world that claims to settle on PayPal while holding a
        sandbox fake would be describing a settlement path it does not have.
        """
        catalog = load_catalog()
        if name != SANDBOX_RAIL and name not in catalog.rails:
            raise ValueError(f"'{name}' is not a rail this twin knows")
        self.rail = name
        if transport is not None:
            self.transport = transport
        rail = catalog.rails.get(name)
        self.record("rail_set", {"rail": name, "label": rail.label if rail else name})
        return {
            "rail": name,
            "label": rail.label if rail else "sandbox fake",
            "settlement_note": rail.settlement_note if rail else "Nothing leaves this machine.",
        }

    def _country_of(self, recipient: str) -> str:
        for event in self.ledger.events:
            if event.counterparty == recipient and event.country:
                return event.country
        return ""

    def _fee_estimate(self, rail: Rail | None, amount_cents: int, country: str,
                      event: CashEvent | None) -> int:
        """What the chosen rail charges to move this, derived from the catalog's rates."""
        if rail is None or not amount_cents:
            return 0
        return rail.fee_cents(
            amount_cents,
            sender_country=self.ledger.country,
            recipient_country=country,
            sender_currency=self.ledger.currency,
            recipient_currency=event.currency if event else "",
        )

    def tool_quote_rails(self, event_id: str | None = None, recipient: str = "",
                         amount_cents: int | None = None) -> dict:
        """Every rail, cheapest first, with the reason any of them cannot deliver this."""
        event = self.ledger.by_id(event_id) if event_id else None
        who = recipient or (event.counterparty if event else "")
        country = (event.country if event else "") or self._country_of(who)
        amount = int(amount_cents or (event.amount_cents if event else 0))
        if not amount:
            return {"skipped": "quote_rails names neither a ledger event nor an amount"}
        quotes = load_catalog().quote(
            amount,
            sender_country=self.ledger.country,
            recipient_country=country,
            sender_currency=self.ledger.currency,
            recipient_currency=event.currency if event else "",
        )
        best = next((row for row in quotes if not row["excluded"]), None)
        self.record("rails_quoted", {"recipient": who, "country": country, "amount_cents": amount,
                                     "settles_on": self.rail, "cheapest": best["rail"] if best else None})
        return {
            "recipient": who,
            "country": country,
            "amount_cents": amount,
            "amount_dollars": dollars(amount),
            "settles_on": self.rail,
            "quotes": quotes,
        }


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
