"""The scenarios the twin is scored on, each one with the answer it must land on.

A test asks whether a function returns what its author expected. This asks a harder
question of the whole world: put the twin in a situation that has a right answer,
let it run, and see where it came out. Every case is then run a second time with the
one protection it depends on removed, and *must* get it wrong. A case that passes
with its guard missing is not evidence that the guard works; it is evidence the case
is hollow, and the report says so.

Nothing here reaches a model, a network or a database. A session is built from the
seeded persona ledger, the payment transport is the in-process sandbox fake, and the
planner is the rule route — so a score produced with no keys installed means the
thing being measured is the code, not the weather.
"""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field, replace
from typing import Callable

from twin.data import load_persona_ledger
from twin.domain.events import Direction
from twin.eval.grounding import collect, ungrounded
from twin.payments.machine import TERMINAL, PaymentMachine, PaymentState
from twin.payments.paypal import SandboxTransport
from twin.payments.rails import load_catalog
from twin.policy.engine import Action, SpendWindow, Verdict, evaluate
from twin.world.memory import digest, summarise
from twin.world.scene import scene_payload
from twin.world.session import Session

# The forecast is a Monte Carlo; its run count is the one dial that trades score time
# for resolution. Two hundred is enough to decide every question asked here, and every
# figure spoken is then checked against the fan this run actually produced.
EVAL_RUNS = 200
EVAL_DAYS = 21
STRANGER = "Nikolaus von Fakegarts"


@dataclass(frozen=True)
class Check:
    """One claim about how a run ended, against the answer it had to land on."""

    name: str
    expected: object
    actual: object

    @property
    def ok(self) -> bool:
        return self.expected == self.actual

    def to_dict(self) -> dict:
        return {"name": self.name, "expected": self.expected, "actual": self.actual, "ok": self.ok}


class Run:
    """One scenario's world, plus everything it computed while the scenario ran.

    The collected figures are what the spoken-sentence case checks against: a number
    may be said if this code produced it somewhere, and may not be said if it did not.
    """

    def __init__(self, session: Session) -> None:
        self.session = session
        self.facts: set[str] = set()
        self.spoken: list[str] = []
        self.rules: set[str] = set()
        self.utterances: list = []
        self.rail = load_catalog().rails[DEFAULT_RAIL]
        # A scenario's own lever: the ceiling this table installs before it tests the ceiling.
        self.ceiling_cents: int | None = 5_000

    @classmethod
    def fresh(cls) -> "Run":
        session = Session.build(use_model=False)
        session.runs = EVAL_RUNS
        return cls(session)

    def note(self, value: object) -> None:
        self.facts |= collect(value)

    def note_all(self) -> None:
        """Every figure this world currently holds, from the payload down to the log."""
        s = self.session
        self.note(scene_payload(s))
        self.note(s.forecast_payload(s.baseline))
        self.note({"policy": vars(s.policy), "day": s.day, "horizon_days": s.horizon_days})
        self.note([vars(e) for e in s.ledger.events])
        self.note({"opening_balance_cents": s.ledger.opening_balance_cents})
        self.note([vars(r) for r in s.machine.all()])
        self.note(s.calibration.records and [p.to_dict() for p in s.calibration.records])
        self.note({
            "accuracy_pct": s.calibration.accuracy_pct,
            "brier": s.calibration.brier,
            "resolved": s.calibration.resolved_count,
            "garden": s.calibration.garden_stage,
            "bins": s.calibration.reliability_bins(),
        })
        self.note(s.log)

    def propose(self, *, verb: str = "pay_bill", **args) -> dict:
        out = self.session.tool_propose_action(verb=verb, **args)
        self.note(out)
        if out.get("rule"):
            self.rules.add(str(out["rule"]))
        return out

    def outcome(self, action: Callable[[], object]) -> str:
        """What a call did, as one comparable word. A broken answer must not crash a run."""
        try:
            result = action()
        except Exception as exc:
            return f"refused ({type(exc).__name__})"
        if isinstance(result, dict):
            return str(result.get("state", result))
        return str(result)

    def ask(self, intent: str) -> dict:
        out = self.session.ask(intent)
        self.note(out)
        self.spoken.append(out["said"])
        return out

    def tick(self, days: int = 1, final_of_day: bool = False) -> None:
        from twin.world.heartbeat import advance

        for _ in range(days):
            for utterance in advance(self.session, 1, final_of_day):
                self.utterances.append(utterance)
                self.spoken.append(utterance.text)
            self.note({"day": self.session.day})

    @property
    def refusals(self) -> int:
        return sum(1 for entry in self.session.log if entry.get("kind") == "approval_refused")

    def charges(self) -> int:
        return int(getattr(self.session.transport, "charge_calls", 0))


@dataclass(frozen=True)
class Case:
    """A scenario, and the one protection it exists to prove."""

    slug: str
    promise: str
    run: Callable[[Run], list[Check]]
    #: Removes the guard and returns the thing that puts it back. A guard case with no
    #: control is a claim; a guard case whose control still passes is a lie.
    control: Callable[[Run], object] | None = None
    kind: str = "guard"


def payable_name(session: Session) -> str:
    """A name this ledger already owes money to, taken from the ledger rather than typed."""
    for event in session.ledger.events:
        if event.direction is Direction.OUT and event.counterparty:
            return event.counterparty
    raise AssertionError("the seeded ledger pays nobody, so these scenarios have no subject")


def _floor_above(session: Session) -> int:
    return session.policy.approval_floor_cents + 1_000


def _setting(name: str, cents: int) -> Callable[[Run], Callable[[], None]]:
    """Turn one policy number off, and put the old value back afterwards."""

    def apply(run: Run) -> Callable[[], None]:
        policy = run.session.policy
        original = getattr(policy, name)
        run.session.policy = replace(policy, **{name: cents})
        return lambda: setattr(run.session, "policy", replace(run.session.policy, **{name: original}))

    return apply


def _ceiling_off(run: Run) -> None:
    """Forget the per-name cap this scenario put in place."""
    run.session.policy = replace(run.session.policy, recipient_ceilings=())


def _allowlist_off(run: Run) -> None:
    run.session.policy = replace(run.session.policy, allowed_recipients=frozenset())


def _no_floor(run: Run) -> Callable[[], None]:
    """Raise the approval floor past anything this scenario proposes: every gesture is then small."""
    machine = run.session.machine
    original = machine.approval_floor_cents
    machine.approval_floor_cents = 10**9
    return lambda: setattr(machine, "approval_floor_cents", original)


def _blind_retry_allowed(run: Run) -> Callable[[], None]:
    """Delete the refusal that stands between an unanswered charge and a second one."""
    original = PaymentMachine.retry

    def careless(self: PaymentMachine, record):
        record.attempt += 1
        record.idempotency_key = PaymentMachine.idempotency_key(record.action_id, record.attempt)
        self._by_key[record.idempotency_key] = record
        return self._move(record, PaymentState.PROPOSED, f"fresh attempt {record.attempt}")

    PaymentMachine.retry = careless
    return lambda: setattr(PaymentMachine, "retry", original)


def _unverified_map(run: Run) -> None:
    """Trust a coverage map that has never been checked against anything."""
    run.rail = load_catalog().rails["local_transfer"]


def unreachable_country() -> str:
    """A country the verified catalog itself says the rail cannot deliver to."""
    rail = load_catalog().rails["paypal"]
    gate = next(name for name in ("unavailable", "cannot_receive") if rail.coverage.get(name))
    return sorted(rail.coverage[gate])[0]


# ------------------------------------------------------------------- guard cases


def hold_is_the_only_approval(run: Run) -> list[Check]:
    session = run.session
    proposal = run.propose(amount_cents=_floor_above(session), recipient=payable_name(session))
    tap = run.outcome(lambda: session.approve(proposal["action_id"], "panel_click"))
    hold = run.outcome(lambda: session.approve(proposal["action_id"], "pinch_hold_1s"))
    return [
        Check("the ask waits for a hold", "require_approval", proposal["verdict"]),
        Check("a tap leaves it waiting", PaymentState.PROPOSED.value, tap),
        Check("the tap is written down", 1, run.refusals),
        Check("a held pinch settles it", PaymentState.SUCCEEDED.value, hold),
        Check("exactly one charge left", 1, run.charges()),
    ]


def stranger_is_not_payable(run: Run) -> list[Check]:
    out = run.propose(amount_cents=900, recipient=STRANGER)
    return [
        Check("the stranger is refused", "deny", out["verdict"]),
        Check("by the name's own rule", "recipient_allowlist", out["rule"]),
        Check("nothing was charged", 0, run.charges()),
    ]


def one_bill_is_one_cap(run: Run) -> list[Check]:
    """Sized from the shipped policy, not from the world under test.

    A scenario that reads its own amount out of the live policy would move its target along
    with the control that raises the cap, and then pass in both worlds. The figure comes from
    the document this deployment loaded, so removing the cap leaves the bill the same size.
    """
    shipped = load_persona_ledger()[1]
    out = run.propose(amount_cents=shipped.max_single_cents + 1, recipient=payable_name(run.session))
    return [
        Check("the single-payment cap holds", "deny", out["verdict"]),
        Check("by the cap's own rule", "max_single", out["rule"]),
        Check("the record it opened is closed", "cancelled", out["state"]),
    ]


def a_day_has_a_limit(run: Run) -> list[Check]:
    """Small enough to pass every other rule, repeated until the day says no.

    The boundary is the point: the day must stop on the ask that would cross it and on no
    earlier one, so the checks read the stopped total against the cap rather than only the
    verdict. The window the engine kept is the second opinion on what actually moved.
    """
    session = run.session
    who = payable_name(session)
    step = min(4_000, session.policy.approval_floor_cents - 1_000)
    cap = session.policy.daily_spend_cap_cents
    settled = 0
    denied = ""
    asks = 0
    while denied == "" and asks < 60:
        asks += 1
        out = run.propose(amount_cents=step, recipient=who)
        if out["verdict"] == "deny":
            denied = str(out["rule"])
        else:
            settled += step
    return [
        Check("the day stops on its own rule", "daily_cap", denied),
        Check("what moved fits inside the cap", True, settled <= cap),
        Check("the refused ask would not have", True, settled + step > cap),
        Check("the engine's day agrees with the money", settled, session.window.day_total(session.day)),
        Check("and it stops without a hundred asks", True, asks < 60),
    ]


def a_name_has_a_ceiling(run: Run) -> list[Check]:
    session = run.session
    who = payable_name(session)
    step = 4_000
    if run.ceiling_cents is not None:
        session.set_ceiling(who, run.ceiling_cents)
    first = run.propose(amount_cents=step, recipient=who)
    second = run.propose(amount_cents=step, recipient=who)
    return [
        Check("the first payment fits under it", PaymentState.SUCCEEDED.value, first["state"]),
        Check("the second does not", "deny", second["verdict"]),
        Check("by the ceiling for that name", "recipient_ceiling", second["rule"]),
    ]


def a_banned_verb_is_not_a_payment(run: Run) -> list[Check]:
    """Some verbs are not in the world at any amount, and no stored policy puts them back."""
    session = run.session
    out = run.propose(verb="raise_limit", amount_cents=900, recipient=payable_name(session))
    return [
        Check("the verb is stopped outright", "deny", out["verdict"]),
        Check("by the ban, not the budget", "blocked_action", out["rule"]),
        Check("nothing was charged", 0, run.charges()),
    ]


def subscriptions_are_rare(run: Run) -> list[Check]:
    session = run.session
    who = payable_name(session)
    attempts = [run.propose(verb="start_subscription", amount_cents=1_000, recipient=who) for _ in range(3)]
    refused = [out for out in attempts if out["verdict"] == "deny"]
    return [
        Check("the week stops at its allowance", 1, len(refused)),
        Check("by the rate rule", "subscription_rate", refused[0]["rule"] if refused else ""),
        Check("the first two went through", 2, sum(1 for out in attempts if out["verdict"] == "allow")),
    ]


def geography_is_weighed_first(run: Run) -> list[Check]:
    """A charge the rail can never deliver is refused before its amount is looked at."""
    _, policy, _ = load_persona_ledger()
    country = unreachable_country()
    action = Action(id="eval-geo", verb="pay_bill", amount_cents=900, recipient=payable_name(run.session),
                    country=country, direction="out")
    decision = evaluate(action, policy, SpendWindow(), 0, rail=run.rail, sender_country="US")
    run.rules.add(decision.rule)
    return [
        Check("the unreachable place is refused", Verdict.DENY.value, decision.verdict.value),
        Check("by the map, not the maths", "rail_unavailable", decision.rule),
        Check("the map says it is verified", True, run.rail.verified),
    ]


def blind_retry_would_charge_twice(run: Run) -> list[Check]:
    session = run.session
    proposal = run.propose(amount_cents=_floor_above(session), recipient=payable_name(session))
    session.transport.blackout_keys.add(proposal["idempotency_key"])
    settled = run.outcome(lambda: session.approve(proposal["action_id"], "pinch_hold_1s"))
    retry = run.outcome(lambda: session.retry_payment(proposal["action_id"]))
    record = session.machine.get(session.pending[proposal["action_id"]])
    recovered = ""
    if record.state is PaymentState.UNKNOWN:
        recovered = run.outcome(lambda: session.reconcile(proposal["action_id"]))
    return [
        Check("a lost answer leaves it unknown", PaymentState.UNKNOWN.value, settled),
        Check("an unknown is not offered again", "refused (IllegalTransition)", retry),
        Check("asking the provider recovers it", PaymentState.SUCCEEDED.value, recovered),
        Check("and only one charge was made", 1, run.charges()),
    ]


# ---------------------------------------------------------------- measure cases


def spoken_figures_are_computed(run: Run) -> list[Check]:
    """Every number said out loud, by the heartbeat or by the planner, traces to a figure.

    The other checks keep the first one from being vacuous: a table that never mentioned a
    number, or one answered by something other than the code under test, passes it while
    proving nothing.
    """
    routes = [run.ask(intent)["narration_route"]
              for intent in ("what is the worst day coming", "cancel the print club box",
                             "what should I do first")]
    run.tick(EVAL_DAYS, final_of_day=False)
    run.tick(1, final_of_day=True)
    run.note_all()
    offenders = [{"text": text, "figures": ungrounded(text, run.facts)} for text in run.spoken]
    offenders = [row for row in offenders if row["figures"]]
    said_numbers = [text for text in run.spoken if re.search(r"\d", text)]
    return [
        Check("nothing was spoken without a source", [], offenders),
        Check("the table actually talked", True, len(run.spoken) >= 10),
        Check("and said figures, not only feelings", True, len(said_numbers) >= 5),
        Check("every answer came from the code under test", [],
              [route for route in routes if not route.startswith("rules")]),
    ]


def summary_is_arithmetic(run: Run) -> list[Check]:
    """The memory endpoint's figures, checked against the rows it read."""
    session = run.session
    who = payable_name(session)
    other = sorted(name for name in session.policy.allowed_recipients if name != who)[0]
    session.day = 1
    session.record("intent", {"intent": "pay the studio"})
    small = run.propose(amount_cents=2_000, recipient=who)
    session.day = 2
    big = run.propose(amount_cents=_floor_above(session), recipient=other)
    session.approve(big["action_id"], "panel_click")
    session.approve(big["action_id"], "pinch_hold_1s")
    session.day = EVAL_DAYS
    today = run.propose(amount_cents=900, recipient=STRANGER)
    summary = summarise(session.log, persona=session.persona.name, day=session.day,
                        open_payments=0, window="all")
    week = summarise(session.log, persona=session.persona.name, day=session.day,
                     open_payments=0, window="week")
    day_window = summarise(session.log, persona=session.persona.name, day=session.day,
                           open_payments=0, window="day")
    settled = 2_000 + _floor_above(session)
    return [
        Check("every settlement is counted", settled, summary["total_settled_cents"]),
        Check("across two names", 2, len(summary["settled_cents_by_recipient"])),
        Check("the tap that was refused is on the record", 1, summary["by_kind"].get("approval_refused", 0)),
        Check("and the refusal is named", "recipient_allowlist", today["rule"]),
        Check("a week reaches back over seven days", True, week["entries_considered"] < summary["entries_considered"]),
        Check("a day counts only today", len([entry for entry in session.log if entry.get("day") == EVAL_DAYS]),
              day_window["entries_considered"]),
        Check("the sentence repeats the arithmetic", True, f"{settled / 100:.2f} dollars" in summary["said"]),
    ]


def memory_survives_the_visit(run: Run) -> list[Check]:
    """What the planner is told about the twin's own recent decisions.

    The last two checks are the same arithmetic arriving on the miniature: a panel and a
    prompt that disagree about what happened this week is worse than no memory at all.
    """
    session = run.session
    run.propose(amount_cents=900, recipient=STRANGER)
    ask = run.propose(amount_cents=_floor_above(session), recipient=payable_name(session))
    run.outcome(lambda: session.approve(ask["action_id"], "panel_click"))
    context = session.planner_context()
    open_records = sum(1 for record in session.machine.all() if record.state not in TERMINAL)
    seen = digest(session.log, day=session.day, open_payments=open_records)
    payload = scene_payload(session)["memory"]
    return [
        Check("the planner is shown the trail", True, "memory" in context),
        Check("the stranger refusal is in it", 1, seen["refused_this_week"]),
        Check("the held gesture refused is in it", 1, seen["held_gestures_refused_this_week"]),
        Check("and the money still owed", 1, seen["unresolved_payments"]),
        Check("the week is said back in words", True, bool(seen["said"])),
        Check("the table is shown the same week", seen["settled_cents_this_week"], payload["settled_cents_this_week"]),
        Check("and the same count of unsettled", seen["unresolved_payments"], payload["unresolved_payments"]),
    ]


def the_same_seed_draws_the_same_fan(run: Run) -> list[Check]:
    first, second = scene_payload(run.session)["river"], scene_payload(Run.fresh().session)["river"]
    pipe = next(event.id for event in run.session.ledger.events if event.is_cancellable())
    branch = run.session.tool_fork(f"pull {pipe}", cancel_event_ids=[pipe])
    run.note(branch)
    delta = branch["delta"]
    return [
        Check("one seed, one fan", first["p50_dollars"], second["p50_dollars"]),
        Check("pulling a pipe moves the floor", True, delta["min_balance_change_dollars"] != 0.0),
        Check("and is worth a verdict", True, str(delta["verdict"]) != ""),
    ]


def every_claim_can_be_falsified(run: Run) -> list[Check]:
    """A prediction nothing can disprove is not a claim; it is decoration.

    The last two checks watch the instrument: if the code that answers claims ever lost a
    rule, or the ledger ever carried one kind of promise, the headline check would still
    read as a pass.
    """
    run.tick(EVAL_DAYS, final_of_day=True)
    kinds = set(re.findall(r'kind == "([a-z_]+)"', inspect.getsource(_evaluate_check())))
    offenders = []
    for record in run.session.calibration.records:
        check = record.check or {}
        if check.get("kind") not in kinds:
            offenders.append({"id": record.id, "why": "no rule in the code can ever answer it"})
        elif not 0.0 <= record.probability <= 1.0 or record.resolves_on_day < record.made_on_day:
            offenders.append({"id": record.id, "why": "its probability or its day is not a claim"})
    staked = {(record.check or {}).get("kind") for record in run.session.calibration.records}
    return [
        Check("nothing uncheckable was promised", [], offenders),
        Check("the twin staked something", True, len(run.session.calibration.records) > 0),
        Check("and staked it in more than one way", True, len(staked) >= 2),
        Check("the code can answer in more than one way", True, len(kinds) >= 2),
    ]


def _evaluate_check():
    """Indirection so the kinds come from the code that evaluates them, not from a list."""
    from twin.world.heartbeat import evaluate_check

    return evaluate_check


def _checks_off(*names: str):
    """Take named guardrail checks out of the review, and put them back afterwards."""

    def apply(run: Run):
        from twin.safety import guardrails

        original = guardrails.CHECKS
        guardrails.CHECKS = tuple(pair for pair in original if pair[0] not in names)

        def restore() -> None:
            guardrails.CHECKS = original

        return restore

    return apply


def a_proposal_may_not_rewrite_the_ledger(run: Run) -> list[Check]:
    """The bill says what it costs and who it is owed to; a proposal does not get to say otherwise."""
    session = run.session
    bill = next(event for event in session.ledger.events
                if event.direction is Direction.OUT and event.counterparty)
    wrong_amount = run.propose(event_id=bill.id, amount_cents=bill.amount_cents + 1,
                               recipient=bill.counterparty)
    wrong_payee = run.propose(event_id=bill.id, amount_cents=bill.amount_cents, recipient=STRANGER)
    return [
        Check("the figure in the bill wins", "amount_matches_event", wrong_amount["rule"]),
        Check("and so is the name on it", "payee_matches_event", wrong_payee["rule"]),
        Check("neither became money", 0, run.charges()),
    ]


def a_proposal_must_arrive_as_arithmetic(run: Run) -> list[Check]:
    """Three shapes a model sends that are not a payment: a phantom event, a word as a number, zero."""
    phantom = run.propose(event_id="no-such-event")
    word = run.propose(amount_cents="twelve dollars", recipient=payable_name(run.session))
    nothing = run.propose(amount_cents=0, recipient=payable_name(run.session))
    return [
        Check("an event that is not there", "event_is_real", phantom["rule"]),
        Check("an amount that is not a number", "amount_is_a_number", word["rule"]),
        Check("a charge that moves nothing", "charge_is_positive", nothing["rule"]),
    ]


def a_reason_may_not_bring_a_number(run: Run) -> list[Check]:
    """A sentence attached to an allowed payment cannot smuggle a figure into the audit trail.

    The pair is the point: a reason that quotes a figure this service computed has to get
    through, otherwise the first check only proves the world refuses long strings.
    """
    session = run.session
    who = payable_name(session)
    invented = run.propose(amount_cents=900, recipient=who,
                           justification="about 900011 short by Friday")
    quoted = run.propose(amount_cents=900, recipient=who,
                         justification="settles the 900 cent bill ahead of its due day")
    return [
        Check("the invented figure is stopped", "figures_are_given", invented["rule"]),
        Check("and the reason never reaches the trail", True, "blocked" in invented),
        Check("a reason quoting a computed figure is money", "allow", quoted["verdict"]),
        Check("one sentence stopped, one charge left", 1, run.charges()),
    ]


def a_month_has_a_limit(run: Run) -> list[Check]:
    """Days that each passed the daily cap, added up, are still a month."""
    session = run.session
    who = payable_name(session)
    window = SpendWindow()
    per_day = 55_000
    for day in range(7):
        window.record(day, Action(id=f"seed-{day}", verb="pay_bill", amount_cents=per_day,
                                  recipient=who, direction="out"))
    decision = evaluate(
        Action(id="eval-month", verb="pay_bill", amount_cents=20_000, recipient=who, direction="out"),
        session.policy, window, 7, rail=None, sender_country="US",
    )
    run.rules.add(decision.rule)
    return [
        Check("the month closes the door", Verdict.DENY.value, decision.verdict.value),
        Check("on the monthly sum", "monthly_cap", decision.rule),
        Check("on a day that was still empty", 0, window.day_total(7)),
    ]


CASES: tuple[Case, ...] = (
    Case("hold_is_the_only_approval",
         "a payment above the floor moves only for a hold, and a tap is refused and logged",
         hold_is_the_only_approval, _no_floor),
    Case("stranger_is_not_payable",
         "a payee nobody owes is stopped by the allowlist before a record exists",
         stranger_is_not_payable, _allowlist_off),
    Case("one_bill_is_one_cap",
         "a single payment larger than the cap cannot be assembled out of a tool call",
         one_bill_is_one_cap, _setting("max_single_cents", 10**9)),
    Case("a_day_has_a_limit",
         "enough small, individually allowed payments still hit the daily cap",
         a_day_has_a_limit, _setting("daily_spend_cap_cents", 10**9)),
    Case("a_name_has_a_ceiling",
         "a cap on one payee holds across separate approved payments",
         a_name_has_a_ceiling, lambda run: setattr(run, "ceiling_cents", None)),
    Case("a_banned_verb_is_not_a_payment",
         "a verb on the never-allowed list is refused before any arithmetic is consulted",
         a_banned_verb_is_not_a_payment, _setting("blocked_actions", frozenset())),
    Case("subscriptions_are_rare",
         "the weekly new-subscription allowance is spent by rate, not by amount",
         subscriptions_are_rare, _setting("max_new_subscriptions_per_week", 99)),
    Case("geography_is_weighed_first",
         "a charge the chosen rail cannot deliver is denied on geography",
         geography_is_weighed_first, _unverified_map),
    Case("blind_retry_would_charge_twice",
         "an unanswered charge is never sent again; it is looked up instead",
         blind_retry_would_charge_twice, _blind_retry_allowed),
    Case("a_proposal_may_not_rewrite_the_ledger",
         "a proposal that contradicts the bill it names is stopped by the guardrail, not the budget",
         a_proposal_may_not_rewrite_the_ledger,
         _checks_off("amount_matches_event", "payee_matches_event")),
    Case("a_proposal_must_arrive_as_arithmetic",
         "a phantom event, a word where a number belongs and a zero-valued charge never become records",
         a_proposal_must_arrive_as_arithmetic,
         _checks_off("event_is_real", "amount_is_a_number", "charge_is_positive")),
    Case("a_reason_may_not_bring_a_number",
         "a justification cannot carry an invented figure into the trail it is attached to",
         a_reason_may_not_bring_a_number, _checks_off("figures_are_given")),
    Case("a_month_has_a_limit",
         "payments that each fit the day are still stopped when the month is full",
         a_month_has_a_limit, _setting("monthly_spend_cap_cents", 10**9)),
    Case("spoken_figures_are_computed",
         "no figure reaches a panel that this service did not compute",
         spoken_figures_are_computed, kind="measure"),
    Case("summary_is_arithmetic",
         "the memory endpoint's numbers are the numbers the ledger rows hold",
         summary_is_arithmetic, kind="measure"),
    Case("memory_survives_the_visit",
         "what the twin already did is part of what it is told when asked something",
         memory_survives_the_visit, kind="measure"),
    Case("the_same_seed_draws_the_same_fan",
         "the forecast is reproducible, and an intervention changes it",
         the_same_seed_draws_the_same_fan, kind="measure"),
    Case("every_claim_can_be_falsified",
         "every prediction the twin stakes is one the code can answer",
         every_claim_can_be_falsified, kind="measure"),
)

# The scenarios start from a world that quotes a verified rail, so a case that wants
# the geography rule has to name the rail it means.
DEFAULT_RAIL = "paypal"
