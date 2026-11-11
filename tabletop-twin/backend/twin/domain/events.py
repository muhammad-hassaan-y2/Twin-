"""Money in minor units, ledger events, and the fictional persona's history.

Every amount here is an integer count of one currency's minor units, so
``amount_cents`` is 1/100 of a dollar, 1 yen, or 1/1000 of a dinar depending on
the currency a ledger is denominated in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class Direction(str, Enum):
    IN = "in"
    OUT = "out"


class Kind(str, Enum):
    INCOME = "income"
    BILL = "bill"
    SUBSCRIPTION = "subscription"
    TAX = "tax"


@dataclass(frozen=True)
class CashEvent:
    """One expected movement of money on the timeline.

    ``lateness_days`` is the observed history for this counterparty. It is the
    only learning signal the twin gets about a payer, and it is what turns a
    fixed due date into a distribution.

    ``late_fee_cents`` is what an inbound costs her when it slips — the bill it
    leaves stranded behind it, not a penalty the payer owes.

    ``country`` is the counterparty's ISO-3166 alpha-2 code, which is what makes
    a rail question answerable at all. ``currency`` is the counterparty's own
    currency when it differs from the ledger's; empty means it does not.
    """

    id: str
    label: str
    kind: Kind
    direction: Direction
    amount_cents: int
    due_day: int
    counterparty: str = ""
    country: str = ""
    currency: str = ""
    recurring_every_days: int | None = None
    occurrences: int = 1
    late_fee_cents: int = 0
    lateness_days: tuple[int, ...] = ()

    @property
    def signed_cents(self) -> int:
        return self.amount_cents if self.direction is Direction.IN else -self.amount_cents

    def is_chasable(self) -> bool:
        return self.direction is Direction.IN and self.kind is Kind.INCOME

    def is_cancellable(self) -> bool:
        return self.kind is Kind.SUBSCRIPTION


@dataclass(frozen=True)
class Ledger:
    opening_balance_cents: int
    events: tuple[CashEvent, ...]
    persona_id: str = "juno-reyes"
    currency: str = "USD"
    country: str = ""

    def currency_of(self, event: CashEvent) -> str:
        return event.currency or self.currency

    def by_id(self, event_id: str) -> CashEvent:
        for event in self.events:
            if event.id == event_id:
                return event
        raise KeyError(event_id)

    def ids(self) -> tuple[str, ...]:
        return tuple(event.id for event in self.events)

    def expand(self, horizon_days: int) -> list[tuple[int, CashEvent]]:
        """Flatten recurring events into (day, event) pairs inside the horizon."""
        out: list[tuple[int, CashEvent]] = []
        for event in self.events:
            for n in range(event.occurrences):
                day = event.due_day + n * (event.recurring_every_days or 0)
                if day < horizon_days:
                    out.append((day, event))
        return sorted(out, key=lambda pair: (pair[0], pair[1].id))


@dataclass
class Snapshot:
    day: int
    p10_cents: int
    p50_cents: int
    p90_cents: int
    dry_prob: float = 0.0


@dataclass(frozen=True)
class Intervention:
    """A decision the twin can fork the world over."""

    id: str
    label: str
    verb: str
    event_ids: tuple[str, ...] = field(default_factory=tuple)
    params: dict[str, float] = field(default_factory=dict)


def event_from_dict(item: dict) -> CashEvent:
    return CashEvent(
        id=str(item["id"]),
        label=str(item["label"]),
        kind=Kind(item["kind"]),
        direction=Direction(item["direction"]),
        amount_cents=int(item["amount_cents"]),
        due_day=int(item["due_day"]),
        counterparty=item.get("counterparty", ""),
        country=str(item.get("country", "")).upper(),
        currency=str(item.get("currency", "")).upper(),
        recurring_every_days=item.get("recurring_every_days"),
        occurrences=int(item.get("occurrences", 1)),
        late_fee_cents=int(item.get("late_fee_cents", 0)),
        lateness_days=tuple(int(d) for d in item.get("lateness_days", ())),
    )


def ledger_from_dict(raw: dict) -> Ledger:
    events = [event_from_dict(item) for item in raw["events"]]
    return Ledger(
        opening_balance_cents=int(raw["opening_balance_cents"]),
        events=tuple(events),
        persona_id=raw.get("persona_id", "unknown"),
        currency=str(raw.get("currency", "USD")).upper(),
        country=str(raw.get("country", "")).upper(),
    )


def iter_days(events: Iterable[tuple[int, CashEvent]]) -> int:
    return max((day for day, _ in events), default=0)
