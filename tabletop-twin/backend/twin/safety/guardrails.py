"""Checks a proposal must pass before it is eligible to be considered at all.

The policy engine next door is the person's spending rules: caps, floors, allowlists,
which rail reaches which country. Those are decisions about the budget, and a person can
change them. This module is about the proposal itself, and the model gets no say in it:
a figure that was never computed, an amount that contradicts the bill it names, a payee
that contradicts the bill it names, a charge that moves nothing, an event id that does
not exist.

Every rule here is the same claim wearing different clothes: **the model may ask, but it
may not tell the ledger what the ledger says.** The number that moves is the one in the
person's own events. Each rule answers with its own name, so the audit trail says which
one stopped a thing, and a refusal is never a matter of opinion about the prompt.

The six, in the order `CHECKS` runs them: `event_is_real`, `amount_is_a_number`,
`charge_is_positive`, `amount_matches_event`, `payee_matches_event`, `figures_are_given`.
The order matters in one way that is easy to miss: the first rule is what makes the two
middle ones applicable at all, because a proposal that names no real event has no ledger
fact to contradict.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from twin.domain.events import CashEvent
from twin.planner.model import number_tokens

# A check returns the sentence that refuses this proposal, or None to pass it on.
Check = Callable[["Proposal", "CashEvent | None", set[str]], "str | None"]


def parse_cents(raw: object) -> int | None:
    """Whole cents from whatever a tool call sent, or None when it is not a number.

    A model that sends "12 dollars" into a field the ledger keeps in cents has asked
    for something this service cannot size. Guessing at the size is not a guardrail, so
    the answer here is None and the caller reports which shape arrived.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw) if float(raw).is_integer() else None
    if isinstance(raw, str):
        try:
            return int(raw.strip().replace(",", ""))
        except ValueError:
            return None
    return None


def figures(*values: object) -> set[str]:
    """The number-tokens of values this code computed, in the spellings speech may use.

    The same normalisation the narrator is held to: `24000`, `240.0` and `240` cents are
    one fact, and a reason that quotes it in any of those forms is quoting the ledger.
    """
    out: set[str] = set()
    for value in values:
        if value is not None:
            out |= number_tokens(str(value))
    return out


@dataclass(frozen=True)
class Proposal:
    """One tool call, with the model's words kept apart from the ledger's.

    `stated_*` is what the model asked for, and is None or empty when it asked for
    nothing and let the named event decide. The resolved fields are what this service
    would actually move, and they are what the policy engine is asked about. Keeping
    both is the whole point: a guardrail that cannot tell who said a number cannot tell
    whether that number was invented.
    """

    verb: str
    event_id: str | None
    stated_amount_cents: int | None
    stated_recipient: str
    amount_cents: int
    recipient: str
    justification: str = ""
    is_charge: bool = False
    stated_amount_text: str = ""


@dataclass(frozen=True)
class Guard:
    """Which rule stopped this proposal, or that none of them did."""

    cleared: bool
    rule: str
    reason: str


CLEAR = Guard(True, "clear", "")


def _event_is_real(proposal: Proposal, event: CashEvent | None, given: set[str]) -> str | None:
    if proposal.event_id is not None and event is None:
        return f"'{proposal.event_id}' is not an event in this ledger"
    return None


def _amount_is_a_number(proposal: Proposal, event: CashEvent | None, given: set[str]) -> str | None:
    if proposal.stated_amount_text and proposal.stated_amount_cents is None:
        return f"the amount sent, {proposal.stated_amount_text!r}, is not a number of cents"
    return None


def _charge_is_positive(proposal: Proposal, event: CashEvent | None, given: set[str]) -> str | None:
    if proposal.is_charge and proposal.amount_cents <= 0:
        return f"a charge moves money, and {proposal.amount_cents} cents moves none"
    return None


def _amount_matches_event(proposal: Proposal, event: CashEvent | None, given: set[str]) -> str | None:
    if event is not None and proposal.stated_amount_cents is not None:
        if proposal.stated_amount_cents != event.amount_cents:
            return (f"{event.id} is {event.amount_cents} cents in this ledger,"
                    f" not {proposal.stated_amount_cents}")
    return None


def _payee_matches_event(proposal: Proposal, event: CashEvent | None, given: set[str]) -> str | None:
    if event is not None and proposal.stated_recipient and event.counterparty:
        if proposal.stated_recipient != event.counterparty:
            return f"{event.id} is owed to {event.counterparty}, not to {proposal.stated_recipient}"
    return None


def _figures_are_given(proposal: Proposal, event: CashEvent | None, given: set[str]) -> str | None:
    invented = {token for token in number_tokens(proposal.justification) if token not in given}
    if invented:
        return f"the reason quotes figures nobody computed: {sorted(invented)}"
    return None


CHECKS: tuple[tuple[str, Check], ...] = (
    ("event_is_real", _event_is_real),
    ("amount_is_a_number", _amount_is_a_number),
    ("charge_is_positive", _charge_is_positive),
    ("amount_matches_event", _amount_matches_event),
    ("payee_matches_event", _payee_matches_event),
    ("figures_are_given", _figures_are_given),
)

RULES = frozenset(name for name, _ in CHECKS)


def review(proposal: Proposal, *, event: CashEvent | None, given: set[str]) -> Guard:
    """The first rule this proposal breaks, in the order `CHECKS` says."""
    for name, check in CHECKS:
        reason = check(proposal, event, given)
        if reason:
            return Guard(False, name, reason)
    return CLEAR
