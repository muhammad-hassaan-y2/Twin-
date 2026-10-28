"""The loop makes one observation at a time, and goes quiet rather than inventing one."""

from __future__ import annotations

from twin.domain.learning import Outcome, Prediction
from twin.world import heartbeat
from twin.world.session import Session


def fresh() -> Session:
    return Session.build(use_model=False)


def test_a_tick_speaks_at_most_once():
    session = fresh()
    for day in range(0, 40, 3):
        session.day = day
        spoken = heartbeat.tick(session)
        assert len(spoken) <= 1 + 1  # one observation, plus the wind-down when it is asked for
        assert len({u.step for u in spoken}) <= 2


def test_the_closing_line_follows_an_observation():
    """Step 6 is the day's summary, so an observation earlier in the loop must not silence it."""
    session = fresh()
    session.day = 30
    spoken = heartbeat.tick(session, final_of_day=True)
    assert spoken[-1].step == "wind-down"
    assert len([u for u in spoken if u.step != "wind-down"]) <= 1


def test_she_does_not_repeat_herself():
    session = fresh()
    session.day = 30
    first = heartbeat.tick(session)
    second = heartbeat.tick(session)
    assert not {u.text for u in first} & {u.text for u in second}


def test_silence_when_the_bank_holds():
    """A thin-spot report requires the computed P10 to actually go under."""
    session = fresh()
    session.day = 80
    window = list(range(80, min(80 + heartbeat.LOOK_AHEAD_DAYS, session.horizon_days)))
    expected = any(session.baseline.p10[d] < 0 for d in window)
    assert bool(heartbeat.thin_spot(session)) is expected


def test_a_stuck_boat_is_named_by_its_own_history_not_a_calendar():
    session = fresh()
    session.day = 0
    assert heartbeat.stuck_boats(session) == []
    session.day = 89
    stuck = heartbeat.stuck_boats(session)
    assert stuck and "Northwind" in stuck[0].text  # largest and lateliest comes first


def test_late_probability_is_a_share_of_observed_attempts():
    session = fresh()
    event = session.ledger.by_id("inv-northwind")
    assert heartbeat.late_probability(event) == 0.8
    assert heartbeat.late_probability(session.ledger.by_id("bill-rent")) == 0.0


def test_a_test_only_speaks_when_the_delta_is_material():
    session = fresh()
    session.day = 12
    before = len(session.calibration.records)
    spoken = heartbeat.one_test(session)
    assert session.tested_on_day == 12
    if spoken:
        assert len(session.calibration.records) == before + 1
        assert "$" not in spoken[0].text  # she speaks plain numbers, not formatted currency
    else:
        assert len(session.calibration.records) == before


def test_the_same_day_is_never_tested_twice():
    session = fresh()
    session.day = 5
    heartbeat.one_test(session)
    assert heartbeat.one_test(session) == []


def test_an_unanswered_payment_surfaces_here_and_nowhere_else():
    session = fresh()
    proposal = session.tool_propose_action(verb="pay_bill", amount_cents=9_000, recipient="Ashgrove Paper")
    session.transport.blackout_keys.add(session.pending[proposal["action_id"]])
    session.approve(proposal["action_id"], "pinch_hold_1s")
    spoken = heartbeat.unfinished_money(session)
    assert len(spoken) == 1
    assert "I will not send it again" in spoken[0].text


def test_a_prediction_is_only_checked_by_something_that_can_falsify_it():
    session = fresh()
    session.day = 10
    guess = Prediction(id="g", subject="bill-rent", statement="the river holds", probability=0.9,
                       made_on_day=0, resolves_on_day=9, check={"kind": "balance_ge_zero_at_day", "day": 9})
    session.calibration.add(guess)
    spoken = heartbeat.resolve_due(session)
    assert len(spoken) == 1
    assert session.calibration.records[-1].outcome is not Outcome.OPEN


def test_an_unnamed_check_is_a_miss_not_a_pass():
    session = fresh()
    assert heartbeat.evaluate_check(session, {"kind": "vibes"}) is False


def test_wind_down_carries_the_real_score_and_garden():
    session = fresh()
    calibration = session.calibration
    # Step 6 belongs to the last tick of a day, so it stays quiet before then.
    assert heartbeat.wind_down(session) == []
    line = heartbeat.wind_down(session, final_of_day=True)[0].text
    assert f"{calibration.garden_stage}" in line
    if calibration.accuracy_pct is not None:
        assert f"{calibration.accuracy_pct} percent" in line


def test_advancing_clamps_to_the_horizon():
    session = fresh()
    heartbeat.advance(session, days=500)
    assert session.day == session.horizon_days - 1
