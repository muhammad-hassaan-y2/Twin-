"""The heartbeat: what the twin does when nobody asks it anything.

Steps run in the order ``heartbeat.md`` lists them. Each one is a question to the
code, never a request to a model, so the loop works with no key and no network.
"""

from __future__ import annotations

from twin.domain.events import CashEvent
from twin.domain.learning import Prediction
from twin.payments.machine import PaymentState
from twin.world.session import Session, Utterance, dollars

MATERIAL_CENTS = 1_000
LOOK_AHEAD_DAYS = 14


def tick(session: Session, final_of_day: bool = False) -> list[Utterance]:
    spoken: list[Utterance] = []
    for name, rule in (
        ("resolve", resolve_due),
        ("upstream", stuck_boats),
        ("thin-spot", thin_spot),
        ("test", one_test),
        ("money", unfinished_money),
    ):
        for utterance in rule(session)[:1]:
            if utterance.text in session.spoken_recently:
                continue
            session.spoken_recently.add(utterance.text)
            spoken.append(utterance)
        if spoken:
            break  # two observations in one tick is a wall of speech, not a person
    if final_of_day:
        spoken.extend(wind_down(session))
    session.log.append({"day": session.day, "heartbeat": [u.step for u in spoken]})
    return spoken


def advance(session: Session, days: int = 1, final_of_day: bool = False) -> list[Utterance]:
    session.day = max(0, min(session.day + days, session.horizon_days - 1))
    return tick(session, final_of_day)


# 1 ------------------------------------------------------------------ resolve
def resolve_due(session: Session) -> list[Utterance]:
    out = []
    for prediction in session.calibration.records:
        if not prediction.due_by(session.day):
            continue
        happened = evaluate_check(session, prediction.check)
        session.calibration.resolve(prediction.id, happened)
        if not happened:
            out.append(
                Utterance(
                    "resolve",
                    f"I said {int(prediction.probability * 100)} percent on '{prediction.statement}'. "
                    "That one didn't hold. The score takes it.",
                    target=f"event:{prediction.subject}",
                )
            )
        else:
            out.append(Utterance("resolve", "One of my calls came in.", target=f"event:{prediction.subject}"))
    return out


def evaluate_check(session: Session, check: dict) -> bool:
    """A prediction is worth nothing if nothing can falsify it."""
    kind = check.get("kind", "")
    baseline = session.baseline
    if kind == "balance_ge_zero_at_day":
        day = min(int(check["day"]), baseline.horizon_days - 1)
        return baseline.p50[day] >= 0
    if kind == "thinner_bank_lifts":
        day = min(int(check["day"]), baseline.horizon_days - 1)
        branch = session.branches.get(check.get("branch", ""))
        return branch is not None and branch.forecast.p10[day] > baseline.p10[day]
    if kind == "event_arrived_by_day":
        event = session.ledger.by_id(check["event_id"])
        worst = max(event.lateness_days, default=0)
        return event.due_day + worst <= int(check["day"])
    return False


# 2 ----------------------------------------------------------------- upstream

def late_probability(event: CashEvent) -> float:
    """How often this payer has actually been late. The fog's only input."""
    if not event.lateness_days:
        return 0.0
    return round(sum(1 for d in event.lateness_days if d > 0) / len(event.lateness_days), 2)


def stuck_boats(session: Session) -> list[Utterance]:
    out = []
    events = [e for e in session.ledger.events if e.is_chasable() and e.lateness_days]
    # Biggest first: if she only gets to mention one boat, it is the one worth chasing.
    events.sort(key=lambda e: e.amount_cents, reverse=True)
    for event in events:
        worst = max(event.lateness_days)
        if session.day > event.due_day + worst and late_probability(event) >= 0.5:
            out.append(
                Utterance(
                    "upstream",
                    f"{event.label} is past the latest it has ever come. "
                    f"{int(late_probability(event) * 100)} percent of its history says it was late at all.",
                    target=f"event:{event.id}",
                )
            )
    return out


# 3 ---------------------------------------------------------------- thin spot

def thin_spot(session: Session) -> list[Utterance]:
    baseline = session.baseline
    window = range(session.day, min(session.day + LOOK_AHEAD_DAYS, baseline.horizon_days))
    days = [(d, baseline.p10[d]) for d in window]
    below = [d for d, value in days if value < 0]
    if not below:
        return []  # no invented worry: if the bank holds, she says nothing
    day, value = min(days, key=lambda pair: pair[1])
    return [
        Utterance(
            "thin-spot",
            f"The P10 bank goes under at day {day}, about {abs(dollars(value))} dollars below the surface.",
            target=f"day:{day}",
        )
    ]


# 4 --------------------------------------------------------------------- test

def one_test(session: Session) -> list[Utterance]:
    if session.tested_on_day == session.day:
        return []
    session.tested_on_day = session.day
    candidate = cheapest_pipe(session)
    if candidate is None:
        return []
    result = session.tool_fork(f"cancel {candidate.label}", cancel_event_ids=[candidate.id])
    delta = result["delta"]
    material = abs(delta["min_balance_change_dollars"]) * 100 >= MATERIAL_CENTS
    if not material:
        return []
    session.calibration.add(
        Prediction(
            id=f"p-{session.day}-{candidate.id}",
            subject=candidate.id,
            statement=f"Dropping {candidate.label} lifts the thin bank this month.",
            probability=round(1.0 - min(1.0, abs(delta["dry_probability_change"])), 2),
            made_on_day=session.day,
            resolves_on_day=min(session.day + 7, session.horizon_days - 1),
            tool="fork",
            check={"kind": "thinner_bank_lifts", "branch": result["branch"], "day": result["forecast"]["pinch_day"]},
        )
    )
    return [
        Utterance(
            "test",
            f"I pulled {candidate.label} aside on the same seed. "
            f"It moves the floor by {delta['min_balance_change_dollars']} dollars and costs {delta['cost_change_dollars']} less. "
            f"That reads as {delta['verdict']} to me.",
            target=f"branch:{result['branch']}",
        )
    ]


def cheapest_pipe(session: Session) -> CashEvent | None:
    pipes = [e for e in session.ledger.events if e.is_cancellable()]
    return min(pipes, key=lambda e: e.amount_cents, default=None)


# 5 -------------------------------------------------------------------- money

def unfinished_money(session: Session) -> list[Utterance]:
    out = []
    for record in session.machine.all():
        if record.state is PaymentState.UNKNOWN:
            out.append(
                Utterance(
                    "money",
                    f"A payment of {dollars(record.amount_cents)} dollars to {record.recipient} went out and never "
                    "answered. I will not send it again; I'm asking the provider what happened.",
                    target=f"payment:{record.idempotency_key}",
                )
            )
        elif record.state is PaymentState.SUCCEEDED and record.verified_outcome is None:
            out.append(
                Utterance(
                    "money",
                    f"{record.recipient} took the money. I haven't seen the thing it was supposed to cause yet.",
                    target=f"payment:{record.idempotency_key}",
                )
            )
    return out


# 6 ---------------------------------------------------------------- wind-down

def wind_down(session: Session) -> list[Utterance]:
    baseline = session.baseline
    accuracy = session.calibration.accuracy_pct
    tomorrow = [
        Utterance(
            "wind-down",
            f"Day {session.day}: {dollars(baseline.p50[session.day])} dollars on the median path, "
            f"thin bank at day {baseline.p10.index(min(baseline.p10))}."
            + (f" I've been right {accuracy} percent of the time. " if accuracy is not None else " ")
            + f"Garden is at {session.calibration.garden_stage}.",
            target="",
        )
    ]
    return tomorrow
