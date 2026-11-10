"""Oversight twin guard — sits inline in the PayPal execution pipeline.

Responsibilities
----------------
* Accept an ``Action`` via ``Session.observe()``.
* Run the existing ``Monitor.review()`` on the accumulated log.
* If a spending-cap breach is detected, raise ``MoneyNotMoved`` so the
  FastAPI handler returns HTTP 402 / FAILED state without calling PayPal.
* If the action is clean, return the session's latest ``PaymentState`` so
  the caller can route the charge to the PayPal client.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple, Any

from swarm_oversight.model import Action as BaseAction, Flag
from swarm_oversight.monitor import Monitor, Limits


@dataclass(frozen=True)
class Action:
    """Wrapper action seen by the FastAPI layer — conforms to the monitor's
    expected shape (seq, agent, kind="spend", amount, payee, tick)."""

    seq: int
    agent: str
    kind: str = "spend"
    amount: int = 0
    payee: str = ""
    tick: int = 0


@dataclass
class PaymentState:
    """Runtime state of a charge attempt."""

    state: str  # "PENDING", "COMPLETED", "FAILED", "UNKNOWN"
    reason: str | None = None
    paypal_order_id: str | None = None
    paypal_order_json: dict | None = None


class Session:
    """Simple action-log session used by the oversight_twin guard.

    * ``observe(action)`` appends the action and runs ``Monitor.review()``.
    * If the monitor flags a cap breach the state will be ``FAILED``;
      the FastAPI endpoint must then raise ``MoneyNotMoved`` (HTTP 402).
    * On success the state stays ``PENDING`` until the caller explicitly
      routes the charge to PayPal and calls ``record_spend()``.
    """

    def __init__(self, monitor: Monitor | None = None, limits: Limits | None = None) -> None:
        self.monitor = monitor or Monitor(limits or Limits())
        self._log: List[BaseAction] = []
        self._latest_state: PaymentState = PaymentState(state="PENDING")

    def observe(self, action: Action) -> PaymentState:
        """Record *action* and recompute the latest ``PaymentState``.

        Returns the updated state.  If the monitor detects a cap breach the
        returned state will be ``FAILED``; the FastAPI endpoint must then
        raise ``MoneyNotMoved`` so that no PayPal HTTP call is made.
        """
        base = BaseAction(
            seq=action.seq,
            agent=action.agent,
            kind=action.kind,
            amount=action.amount,
            payee=action.payee,
            tick=action.tick,
        )
        self._log.append(base)
        flags = self.monitor.review(self._log)
        state, reason = self._derive_state_from_flags(flags)
        self._latest_state = PaymentState(state=state, reason=reason)
        return self._latest_state

    @staticmethod
    def _derive_state_from_flags(flags: list) -> tuple[str, str | None]:
        """Map monitor flags to a ``PaymentState``.

        The monitor returns ``(index, flag)`` pairs collapsed into
        ``(state, reason)``.
        """
        if not flags:
            return "PENDING", None

        # Any over_limit, relay, or split flag means the cap was breached
        # locally — do not call PayPal.
        for _idx, flag in flags:
            rule = flag.rule
            if "over_limit" in rule or "relay" in rule or "split" in rule:
                return "FAILED", flag.reason or "Spending cap breached"
        # Unknown flags still block the payment.
        return "FAILED", "; ".join(flag.reason for _idx, flag in flags)

    def record_spend(self) -> None:
        """Explicitly record a successful spend so the log stays consistent
        when the FastAPI endpoint decides to route the charge to PayPal.
        """
        # The log is already consistent because the caller only reaches here
        # after the guard passed (FAILED was not returned).  We just update
        # the latest state to COMPLETED.
        self._latest_state = PaymentState(state="COMPLETED", reason=None)


class MoneyNotMoved(Exception):
    """Raised by the FastAPI handler when the oversight guard detected a
    spending-cap breach.  The handler should return HTTP 402 and set the
    charge state to ``FAILED`` without touching the PayPal API.

    Always store ``reason`` as an attribute for API handlers and tests.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason