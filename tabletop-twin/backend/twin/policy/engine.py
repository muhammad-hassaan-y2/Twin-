"""The policy engine. Spending rules live here, in code.

The model proposes. This module decides. A model can never widen a limit, and
the reason a request was refused is always a fact about the ledger, never an
opinion about the prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Verdict(str, Enum):
    ALLOW = "allow"
    REQUIRE_APPROVAL = "require_approval"
    DENY = "deny"


@dataclass(frozen=True)
class Policy:
    """Hard limits. Loaded from config, never from a model response."""

    max_single_cents: int = 25_000
    daily_spend_cap_cents: int = 60_000
    monthly_spend_cap_cents: int = 400_000
    approval_floor_cents: int = 5_000
    allowed_recipients: frozenset[str] = frozenset()
    blocked_actions: frozenset[str] = frozenset({"unlink_account", "raise_limit", "export_credentials"})
    max_new_subscriptions_per_week: int = 2


@dataclass(frozen=True)
class Action:
    id: str
    verb: str
    amount_cents: int = 0
    recipient: str = ""
    cadence_days: int | None = None
    justification: str = ""
    source: str = "twin"
    direction: str = "out"

    @property
    def is_recurring(self) -> bool:
        return self.cadence_days is not None

    @property
    def direction_out(self) -> bool:
        return self.direction == "out"


@dataclass(frozen=True)
class Decision:
    verdict: Verdict
    reason: str
    action_id: str
    rule: str
    limits: dict[str, int] = field(default_factory=dict)


class SpendWindow:
    """Rolling spend, so a cap means something across a session."""

    def __init__(self) -> None:
        self._daily: dict[int, int] = {}
        self._monthly: dict[int, int] = {}
        self._new_subs: dict[int, int] = {}

    def record(self, day: int, action: Action) -> None:
        if action.direction_out:
            self._daily[day] = self._daily.get(day, 0) + action.amount_cents
            month = day // 30
            self._monthly[month] = self._monthly.get(month, 0) + action.amount_cents
        if action.verb == "start_subscription":
            week = day // 7
            self._new_subs[week] = self._new_subs.get(week, 0) + 1

    def day_total(self, day: int) -> int:
        return self._daily.get(day, 0)

    def month_total(self, day: int) -> int:
        return self._monthly.get(day // 30, 0)

    def new_subscriptions(self, day: int) -> int:
        return self._new_subs.get(day // 7, 0)


def evaluate(action: Action, policy: Policy, window: SpendWindow, day: int) -> Decision:
    limits = {
        "amount_cents": action.amount_cents,
        "max_single_cents": policy.max_single_cents,
        "daily_used_cents": window.day_total(day),
        "daily_cap_cents": policy.daily_spend_cap_cents,
    }

    if action.verb in policy.blocked_actions:
        return Decision(Verdict.DENY, f"'{action.verb}' is not a permitted action", action.id, "blocked_action", limits)

    if action.recipient and policy.allowed_recipients and action.recipient not in policy.allowed_recipients:
        return Decision(Verdict.DENY, f"unknown recipient '{action.recipient}'", action.id, "recipient_allowlist", limits)

    # Caps are about money leaving. A chase or a cancellation names an amount for
    # context, not a charge, so sizing it against a payment cap would be nonsense.
    if action.direction_out and action.amount_cents > policy.max_single_cents:
        return Decision(
            Verdict.DENY,
            f"single payment exceeds the {policy.max_single_cents} cent cap",
            action.id,
            "max_single",
            limits,
        )

    if action.verb == "start_subscription" and window.new_subscriptions(day) >= policy.max_new_subscriptions_per_week:
        return Decision(
            Verdict.DENY,
            "weekly new-subscription allowance already used",
            action.id,
            "subscription_rate",
            limits,
        )

    if action.direction_out and window.day_total(day) + action.amount_cents > policy.daily_spend_cap_cents:
        return Decision(Verdict.DENY, "daily spend cap would be exceeded", action.id, "daily_cap", limits)

    if action.direction_out and window.month_total(day) + action.amount_cents > policy.monthly_spend_cap_cents:
        return Decision(Verdict.DENY, "monthly spend cap would be exceeded", action.id, "monthly_cap", limits)

    if action.direction_out and action.amount_cents >= policy.approval_floor_cents:
        return Decision(
            Verdict.REQUIRE_APPROVAL,
            "above the approval floor: needs a held pinch",
            action.id,
            "approval_floor",
            limits,
        )

    return Decision(Verdict.ALLOW, "within limits", action.id, "within_limits", limits)


def policy_from_dict(raw: dict) -> Policy:
    return Policy(
        max_single_cents=int(raw.get("max_single_cents", 25_000)),
        daily_spend_cap_cents=int(raw.get("daily_spend_cap_cents", 60_000)),
        monthly_spend_cap_cents=int(raw.get("monthly_spend_cap_cents", 400_000)),
        approval_floor_cents=int(raw.get("approval_floor_cents", 5_000)),
        allowed_recipients=frozenset(raw.get("allowed_recipients", ())),
        blocked_actions=frozenset(raw.get("blocked_actions", ("unlink_account", "raise_limit", "export_credentials"))),
        max_new_subscriptions_per_week=int(raw.get("max_new_subscriptions_per_week", 2)),
    )
