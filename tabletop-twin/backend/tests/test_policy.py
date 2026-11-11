"""Limits live in code. A model has no way to express "raise the limit"."""

from __future__ import annotations

import inspect
from dataclasses import FrozenInstanceError

import pytest

from twin.data import load_persona_ledger
from twin.policy.engine import Action, Policy, SpendWindow, Verdict, evaluate
from twin.world.session import Session


def policy() -> Policy:
    _, p, _ = load_persona_ledger()
    return p


def test_over_the_single_cap_is_denied_not_warned():
    decision = evaluate(Action(id="a", verb="pay_bill", amount_cents=26_000, recipient="Ashgrove Paper"), policy(), SpendWindow(), 0)
    assert decision.verdict is Verdict.DENY
    assert decision.rule == "max_single"


def test_rent_is_too_big_for_the_twin_to_pay():
    """The point of a cap is that it refuses the obvious, not only the absurd."""
    decision = evaluate(Action(id="a", verb="pay_bill", amount_cents=78_000, recipient="Ashgrove Studios"), policy(), SpendWindow(), 0)
    assert decision.verdict is Verdict.DENY


def test_at_or_above_the_approval_floor_needs_a_held_pinch():
    decision = evaluate(Action(id="a", verb="pay_bill", amount_cents=5_000, recipient="Ashgrove Paper"), policy(), SpendWindow(), 0)
    assert decision.verdict is Verdict.REQUIRE_APPROVAL
    assert decision.rule == "approval_floor"


def test_choosing_the_recipient_is_enforced():
    decision = evaluate(Action(id="a", verb="pay_bill", amount_cents=1_000, recipient="Some Unknown Vendor"), policy(), SpendWindow(), 0)
    assert decision.verdict is Verdict.DENY
    assert decision.rule == "recipient_allowlist"


def test_daily_cap_binds_after_enough_small_spending():
    p = policy()
    window = SpendWindow()
    day = 3
    used = 0
    while used + 4_000 <= p.daily_spend_cap_cents:
        action = Action(id=f"a{used}", verb="pay_bill", amount_cents=4_000, recipient="Ashgrove Paper")
        assert evaluate(action, p, window, day).verdict is not Verdict.DENY
        window.record(day, action)
        used = window.day_total(day)
    overflow = evaluate(Action(id="over", verb="pay_bill", amount_cents=4_000, recipient="Ashgrove Paper"), p, window, day)
    assert overflow.verdict is Verdict.DENY
    assert overflow.rule == "daily_cap"


def test_weekly_subscription_rate_is_a_cap_not_a_suggestion():
    p = policy()
    window = SpendWindow()
    for i in range(p.max_new_subscriptions_per_week):
        action = Action(id=f"s{i}", verb="start_subscription", amount_cents=900, recipient="Suite Works")
        assert evaluate(action, p, window, 10).verdict is not Verdict.DENY
        window.record(10, action)
    third = evaluate(Action(id="s99", verb="start_subscription", amount_cents=900, recipient="Suite Works"), p, window, 11)
    assert third.verdict is Verdict.DENY
    assert third.rule == "subscription_rate"


def test_blocked_actions_are_denied_even_at_zero_amount():
    for verb in ("unlink_account", "raise_limit", "export_credentials"):
        decision = evaluate(Action(id="a", verb=verb, amount_cents=0), policy(), SpendWindow(), 0)
        assert decision.verdict is Verdict.DENY


def test_a_chase_is_not_sized_like_a_payment():
    """An inbound invoice is large; nothing is leaving, so no cap applies to it."""
    decision = evaluate(Action(id="a", verb="chase_invoice", amount_cents=480_000, recipient="Northwind Roasters", direction="none"), policy(), SpendWindow(), 0)
    assert decision.rule != "max_single"


def test_policy_cannot_be_rewritten_at_runtime():
    assert policy().max_single_cents == 25_000
    session = Session.build(use_model=False)
    names = {n for n, _ in inspect.getmembers(session, predicate=callable)}
    assert not any("set_policy" in n or "raise" in n or "override" in n for n in names)
    with pytest.raises(FrozenInstanceError):
        session.policy.max_single_cents = 10**9


def test_decision_reports_the_limits_it_compared_against():
    decision = evaluate(Action(id="a", verb="pay_bill", amount_cents=26_000, recipient="Ashgrove Paper"), policy(), SpendWindow(), 0)
    assert decision.limits["max_single_cents"] == 25_000
    assert decision.limits["amount_cents"] == 26_000
