"""Monte Carlo cash-flow forecast.

Every number the world draws comes from here. The model is never asked to
arithmetic; it is only asked which question to pose.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .events import CashEvent, Ledger


@dataclass(frozen=True)
class Forecast:
    horizon_days: int
    runs: int
    seed: int
    p10: tuple[int, ...]
    p50: tuple[int, ...]
    p90: tuple[int, ...]
    dry_prob: tuple[float, ...]
    min_balance_cents: int
    shortfall_day: int | None
    dry_run_share: float
    expected_late_fees_cents: int
    expected_cost_cents: int

    def band(self, day: int) -> tuple[int, int, int]:
        return self.p10[day], self.p50[day], self.p90[day]

    @property
    def width_cents(self) -> int:
        """Mean P90-P10 spread: how uncertain the twin claims to be."""
        spreads = [self.p90[d] - self.p10[d] for d in range(self.horizon_days)]
        return round(sum(spreads) / len(spreads)) if spreads else 0


def _sample_lag(event: CashEvent, rng: random.Random, chase_multiplier: float) -> int:
    """Draw a lateness in days from what this counterparty actually did before."""
    if not event.lateness_days:
        base = 0
    else:
        base = rng.choice(event.lateness_days)
    # Jitter so the same history does not produce a lattice of identical paths.
    jitter = max(0, int(rng.gauss(0, 1.5)))
    lag = base + jitter
    if chase_multiplier < 1.0:
        lag = int(round(lag * chase_multiplier))
    return max(0, lag)


def forecast_ledger(
    ledger: Ledger,
    horizon_days: int = 90,
    runs: int = 4000,
    seed: int = 20261028,
    cancelled_ids: frozenset[str] = frozenset(),
    chase_ids: frozenset[str] = frozenset(),
    chase_multiplier: float = 0.35,
    shifted: dict[str, int] | None = None,
) -> Forecast:
    """Simulate the ledger and return per-day percentiles.

    ``cancelled_ids`` drop events entirely (a pulled subscription pipe).
    ``chase_ids`` compress observed lateness (the twin sends the reminder).
    ``shifted`` moves an event by a day offset (pay the bill early).
    """
    rng = random.Random(seed)
    shifted = shifted or {}
    plan = [
        (day, event)
        for day, event in ledger.expand(horizon_days)
        if event.id not in cancelled_ids
    ]

    paths: list[list[int]] = []
    fee_hits: list[int] = []
    for _ in range(runs):
        balance = ledger.opening_balance_cents
        series = [0] * horizon_days
        fees = 0
        pending: dict[int, list[tuple[CashEvent, int]]] = {}
        for day, event in plan:
            moved = day + shifted.get(event.id, 0)
            lag = 0
            if event.is_chasable():
                lag = _sample_lag(event, rng, chase_multiplier if event.id in chase_ids else 1.0)
                if lag > 0 and event.late_fee_cents:
                    fees += event.late_fee_cents
            arrival = min(horizon_days - 1, max(0, moved + lag))
            pending.setdefault(arrival, []).append((event, moved))
        for day in range(horizon_days):
            for event, _moved in pending.get(day, ()):
                balance += event.signed_cents
            series[day] = balance
        paths.append(series)
        fee_hits.append(fees)

    p10: list[int] = []
    p50: list[int] = []
    p90: list[int] = []
    dry: list[float] = []
    for day in range(horizon_days):
        column = sorted(path[day] for path in paths)
        p10.append(_percentile(column, 0.10))
        p50.append(_percentile(column, 0.50))
        p90.append(_percentile(column, 0.90))
        below = sum(1 for value in column if value < 0)
        dry.append(below / len(column))

    min_balance = min(min(path) for path in paths)
    shortfall_day = next((d for d in range(horizon_days) if dry[d] >= 0.5), None)
    under = sum(1 for path in paths if min(path) < 0)
    expected_fees = round(sum(fee_hits) / len(fee_hits)) if fee_hits else 0

    return Forecast(
        horizon_days=horizon_days,
        runs=runs,
        seed=seed,
        p10=tuple(p10),
        p50=tuple(p50),
        p90=tuple(p90),
        dry_prob=tuple(round(d, 4) for d in dry),
        min_balance_cents=min_balance,
        shortfall_day=shortfall_day,
        dry_run_share=round(under / len(paths), 4) if paths else 0.0,
        expected_late_fees_cents=expected_fees,
        expected_cost_cents=expected_fees,
    )


def _percentile(sorted_column: list[int], q: float) -> int:
    if not sorted_column:
        return 0
    index = q * (len(sorted_column) - 1)
    low = int(index)
    high = min(low + 1, len(sorted_column) - 1)
    frac = index - low
    return round(sorted_column[low] * (1 - frac) + sorted_column[high] * frac)
