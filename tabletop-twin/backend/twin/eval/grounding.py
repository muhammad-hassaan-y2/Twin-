"""Which figures the twin is allowed to say out loud.

A sentence a model writes is checked against the numbers it was handed before any of
it reaches a panel. Nothing checks the sentences the *code* writes: the heartbeat
formats dollar amounts, day numbers and percentages itself, and a formatting mistake
there is indistinguishable from an invented figure once it is on the table.

This is the same rule applied to that path. A figure may be spoken if it came out of
this service — a forecast, a tool result, a ledger row, a policy limit — in one of the
forms speech honestly uses. Everything else is invented, whoever wrote the sentence.
"""

from __future__ import annotations

from twin.planner.model import number_tokens


def speech_forms(value: object) -> set[str]:
    """One computed figure, in every shape a spoken sentence may put it in.

    ``0.62`` may honestly be said as "62 percent" and ``-123.4`` as "about 123 dollars
    below"; those are restatements, not new numbers. What is not allowed is a figure no
    computation produced, however neatly it is worded.
    """
    if isinstance(value, bool):
        return set()
    if isinstance(value, (int, float)):
        magnitude = abs(value)
        out: set[str] = set()
        for candidate in (value, magnitude, int(value), int(magnitude)):
            out |= number_tokens(str(candidate))
        if magnitude <= 1:
            out |= number_tokens(str(round(magnitude * 100)))
            out |= number_tokens(str(int(magnitude * 100)))
        return out
    if isinstance(value, str):
        return number_tokens(value)
    return set()


def collect(value: object) -> set[str]:
    """Every figure inside a payload this code produced, however deeply it is nested."""
    out: set[str] = set()
    if isinstance(value, dict):
        for item in value.values():
            out |= collect(item)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            out |= collect(item)
    else:
        out |= speech_forms(value)
    return out


def ungrounded(text: str, facts: set[str]) -> list[str]:
    """The figures in this sentence that nothing computed."""
    return sorted(token for token in number_tokens(text) if token not in facts)
