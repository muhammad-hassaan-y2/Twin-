"""A fork differs from the world only by the decision that made it."""

from __future__ import annotations

from twin.domain.interventions import Branch, compare, fork
from twin.world.session import Session


def test_no_intervention_forks_to_an_identical_world():
    session = Session.build(use_model=False)
    result = session.tool_fork("do nothing")
    delta = result["delta"]
    assert delta["min_balance_change_dollars"] == 0.0
    assert delta["cost_change_dollars"] == 0.0
    assert delta["dry_probability_change"] == 0.0
    assert delta["verdict"] == "no material change"


def test_forking_the_same_decision_twice_gives_the_same_forecast():
    session = Session.build(use_model=False)
    first = session.tool_fork("cancel the print club", cancel_event_ids=["sub-plates"])
    second = session.tool_fork("cancel the print club", cancel_event_ids=["sub-plates"])
    assert first["forecast"] == second["forecast"]
    assert first["delta"] == second["delta"]


def test_branches_are_reforecasts_not_rescalings():
    """A branch must come from its own simulation, so it can differ on any day."""
    session = Session.build(use_model=False)
    baseline = session.branches["baseline"]
    branch = Branch(
        key="shift-tax",
        label="pay the tax a week early",
        forecast=baseline.forecast,
        shifted=(("bill-tax", -7),),
    )
    worlds = fork(session.ledger, baseline, [branch], runs=600)
    assert worlds["shift-tax"].forecast.p50 != baseline.forecast.p50


def test_delta_signs_describe_the_candidate_relative_to_baseline():
    session = Session.build(use_model=False)
    baseline = session.branches["baseline"]
    cancel = session.tool_fork("cancel the print club", cancel_event_ids=["sub-plates"])
    branch = session.branches[cancel["branch"]]
    delta = compare(baseline, branch)
    assert delta.min_balance_change_cents >= 0
    assert delta.key == branch.key
