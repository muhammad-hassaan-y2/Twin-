"""Forking the world: pull a ribbon, get a second miniature beside the first."""

from __future__ import annotations

from dataclasses import dataclass

from .events import Ledger
from .forecast import Forecast, forecast_ledger


@dataclass(frozen=True)
class Branch:
    """One possible future, named by the decision that created it."""

    key: str
    label: str
    forecast: Forecast
    cancelled_ids: frozenset[str] = frozenset()
    chase_ids: frozenset[str] = frozenset()
    shifted: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class BranchDelta:
    key: str
    label: str
    min_balance_change_cents: int
    shortfall_day_change: int | None
    cost_change_cents: int
    dry_probability_change: float
    band_narrowing_cents: int
    verdict: str


def fork(
    ledger: Ledger,
    baseline: Branch,
    alternatives: list[Branch],
    horizon_days: int = 90,
    runs: int = 4000,
    seed: int = 20261028,
) -> dict[str, Branch]:
    """Re-forecast each branch from the same seed.

    Same seed is the whole point: two worlds that differ only in the decision,
    so a judge can trust that the delta came from the intervention.
    """
    out = {baseline.key: baseline}
    for branch in alternatives:
        forecast = forecast_ledger(
            ledger,
            horizon_days=horizon_days,
            runs=runs,
            seed=seed,
            cancelled_ids=branch.cancelled_ids,
            chase_ids=branch.chase_ids,
            shifted=dict(branch.shifted),
        )
        out[branch.key] = Branch(
            key=branch.key,
            label=branch.label,
            forecast=forecast,
            cancelled_ids=branch.cancelled_ids,
            chase_ids=branch.chase_ids,
            shifted=branch.shifted,
        )
    return out


def compare(baseline: Branch, candidate: Branch, pinch_day: int | None = None) -> BranchDelta:
    a, b = baseline.forecast, candidate.forecast
    horizon = min(a.horizon_days, b.horizon_days)
    day = pinch_day if pinch_day is not None else _worst_day(a)

    def shortfall_ordinal(forecast: Forecast) -> int:
        return forecast.shortfall_day if forecast.shortfall_day is not None else forecast.horizon_days

    change_shortfall = shortfall_ordinal(b) - shortfall_ordinal(a)
    dry_change = (b.dry_prob[day] if day < len(b.dry_prob) else 0.0) - (
        a.dry_prob[day] if day < len(a.dry_prob) else 0.0
    )
    min_change = b.min_balance_cents - a.min_balance_cents
    cost_change = b.expected_cost_cents - a.expected_cost_cents

    if min_change > 0 and cost_change <= 0:
        verdict = "strictly better"
    elif min_change > 0:
        verdict = "safer floor, costlier"
    elif cost_change < 0:
        verdict = "cheaper, thinner cushion"
    else:
        verdict = "no material change"

    return BranchDelta(
        key=candidate.key,
        label=candidate.label,
        min_balance_change_cents=min_change,
        shortfall_day_change=change_shortfall if a.shortfall_day is not None or b.shortfall_day is not None else None,
        cost_change_cents=cost_change,
        dry_probability_change=round(dry_change, 4),
        band_narrowing_cents=b.width_cents - a.width_cents,
        verdict=verdict,
    )


def _worst_day(forecast: Forecast) -> int:
    if not forecast.dry_prob:
        return 0
    return max(range(len(forecast.dry_prob)), key=lambda d: forecast.dry_prob[d])
