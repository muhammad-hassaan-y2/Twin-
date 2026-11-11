"""Code computes every number, and the same question asked twice gets the same answer."""

from __future__ import annotations

from twin.data import load_persona_ledger
from twin.domain.forecast import forecast_ledger
from twin.world.session import Session


def test_same_seed_reproduces_every_percentile():
    ledger, _, _ = load_persona_ledger()
    a = forecast_ledger(ledger, runs=800)
    b = forecast_ledger(ledger, runs=800)
    assert a.p10 == b.p10 and a.p50 == b.p50 and a.p90 == b.p90
    assert a.dry_prob == b.dry_prob


def test_a_different_seed_moves_the_answer():
    """If a different seed agreed exactly, the simulation would be doing nothing."""
    ledger, _, _ = load_persona_ledger()
    a = forecast_ledger(ledger, runs=800, seed=1)
    b = forecast_ledger(ledger, runs=800, seed=2)
    assert a.p50 != b.p50


def test_banks_are_ordered_every_day():
    ledger, _, _ = load_persona_ledger()
    f = forecast_ledger(ledger, runs=600)
    assert all(lo <= mid <= hi for lo, mid, hi in zip(f.p10, f.p50, f.p90))


def test_cancelling_a_pipe_cannot_make_the_river_worse():
    ledger, _, _ = load_persona_ledger()
    baseline = forecast_ledger(ledger, runs=800)
    cancelled = forecast_ledger(ledger, runs=800, cancelled_ids={"sub-plates"})
    assert cancelled.min_balance_cents >= baseline.min_balance_cents


def test_chasing_pulls_the_inbound_earlier():
    ledger, _, _ = load_persona_ledger()
    alone = forecast_ledger(ledger, runs=800)
    chased = forecast_ledger(ledger, runs=800, chase_ids={"inv-northwind"})
    assert chased.min_balance_cents >= alone.min_balance_cents
    assert max(chased.dry_prob) <= max(alone.dry_prob)


def test_dry_run_share_is_a_count_of_real_paths():
    session = Session.build(use_model=False)
    f = session.baseline
    assert 0.0 <= f.dry_run_share <= 1.0
    if f.shortfall_day is None:
        assert min(f.p50) >= 0
