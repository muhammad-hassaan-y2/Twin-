"""Turn computed facts into the shape the miniature world draws.

The client never does arithmetic and never receives an opinion. It gets arrays
indexed by day and one entry per object in the scene, so a stone's height and a
boat's fog are the same numbers the narration is allowed to speak.
"""

from __future__ import annotations

from twin.domain.forecast import Forecast
from twin.domain.interventions import compare
from twin.payments.machine import TERMINAL
from twin.world.heartbeat import late_probability
from twin.world.session import Session, dollars

PALETTE = {
    "river": "#2E7DD1",
    "bank_low": "#7FB3D5",
    "stone": "#F2E8C9",
    "boat": "#00B3A4",
    "lake": "#5BC8AF",
    "fog": "#9AA5B1",
    "twin": "#FFD166",
    "danger": "#E4572E",
}
# Blue-to-teal-to-amber only. Nothing in this set is distinguished by red versus
# green, so the world reads the same for deuteranopia and protanopia.


def scene_payload(session: Session) -> dict:
    baseline = session.baseline
    return {
        "meta": {
            "persona": session.persona.name,
            "day": session.day,
            "horizon_days": session.horizon_days,
            "runs": baseline.runs,
            "seed": baseline.seed,
            "currency": "USD",
            "generated_by": "code, not the model",
        },
        "palette": PALETTE,
        "river": river(baseline),
        "stones": stones(session, baseline),
        "boats": boats(session),
        "lake": lake(session),
        "garden": garden(session),
        "branches": branches(session),
        "payments": payments(session),
        "focus": session.focus,
        "twin": {"look_at": session.focus, "speak": session.last_speech},
    }


def river(forecast: Forecast) -> dict:
    """The water: a median line and the P10-P90 banks, one value per day."""
    return {
        "p10_dollars": [dollars(v) for v in forecast.p10],
        "p50_dollars": [dollars(v) for v in forecast.p50],
        "p90_dollars": [dollars(v) for v in forecast.p90],
        "dry_probability": list(forecast.dry_prob),
        "pinch_day": forecast.p10.index(min(forecast.p10)),
    }


def stones(session: Session, forecast: Forecast) -> list[dict]:
    """Bills, tax and subscriptions become stepping stones at their own dates."""
    out = []
    for day, event in session.ledger.expand(session.horizon_days):
        if event.direction.value != "out":
            continue
        out.append(
            {
                "id": f"{event.id}@{day}",
                "event_id": event.id,
                "label": event.label,
                "kind": event.kind.value,
                "day": day,
                "amount_dollars": dollars(event.amount_cents),
                "height": round(event.amount_cents / max(1, max(e.amount_cents for e in session.ledger.events)) * 0.14, 4),
                "below_surface": forecast.p50[day] < 0,
                "cancellable": event.is_cancellable(),
            }
        )
    return out


def boats(session: Session) -> list[dict]:
    """Late inbounds are boats stuck upstream. Fog thickness is their own history."""
    out = []
    for event in session.ledger.events:
        if not event.is_chasable():
            continue
        late = late_probability(event)
        worst = max(event.lateness_days, default=0)
        out.append(
            {
                "id": event.id,
                "label": event.label,
                "day": event.due_day,
                "amount_dollars": dollars(event.amount_cents),
                "fog": late,
                "worst_lag_days": worst,
                "stuck": session.day > event.due_day + worst,
            }
        )
    return out


def lake(session: Session) -> dict:
    """Savings is the one place money is allowed to sit still."""
    moves = [e for e in session.ledger.events if e.label.lower().startswith("move to savings")]
    total = sum(e.amount_cents * e.occurrences for e in moves)
    return {"feed_event_ids": [e.id for e in moves], "depth_dollars": dollars(total)}


def garden(session: Session) -> dict:
    calibration = session.calibration
    return {
        "stage": calibration.garden_stage,
        "accuracy_pct": calibration.accuracy_pct,
        "brier": None if calibration.brier is None else round(calibration.brier, 4),
        "resolved": calibration.resolved_count,
        "open": len(calibration.records) - calibration.resolved_count,
        "reliability": calibration.reliability_bins(),
    }


def payments(session: Session) -> list[dict]:
    """Money that has not landed yet. An UNKNOWN record is drawn, not hidden."""
    return [
        {
            "action_id": record.action_id,
            "state": record.state.value,
            "recipient": record.recipient,
            "amount_dollars": dollars(record.amount_cents),
            "attempt": record.attempt,
            "idempotency_key": record.idempotency_key,
            "verified": record.verified_outcome is not None,
        }
        for record in session.machine.all()
        if record.state not in TERMINAL
    ]


def branches(session: Session) -> list[dict]:
    out = []
    baseline = session.branches["baseline"]
    for key, branch in session.branches.items():
        if key == "baseline":
            continue
        delta = session.delta_payload(compare(baseline, branch))
        out.append({"key": key, "label": branch.label, "min_balance_dollars": dollars(branch.forecast.min_balance_cents), **delta})
    return out
