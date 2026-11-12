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

import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple, Any, Dict, Set

# Ensure swarm-oversight directory is in sys.path
_SWARM_DIR = Path(__file__).resolve().parent.parent / "swarm-oversight"
if _SWARM_DIR.is_dir() and str(_SWARM_DIR) not in sys.path:
    sys.path.insert(0, str(_SWARM_DIR))

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

    state: str  # "PENDING", "COMPLETED", "FAILED", "UNKNOWN", "AWAITING_HUMAN"
    reason: str | None = None
    paypal_order_id: str | None = None
    paypal_order_json: dict | None = None


class Session:
    """Action-log session used by the oversight_twin guard.

    * ``observe(action)`` appends the action and runs ``Monitor.review()``.
    * If the monitor flags a cap breach the state will be ``FAILED``;
      the FastAPI endpoint must then raise ``MoneyNotMoved`` (HTTP 402).
    * On success the state stays ``PENDING`` until the caller explicitly
      routes the charge to PayPal and calls ``record_spend()``.
    """

    def __init__(self, monitor: Monitor | None = None, limits: Limits | None = None) -> None:
        self.limits = limits or Limits()
        self.monitor = monitor or Monitor(self.limits)
        self._log: List[BaseAction] = []
        self._latest_state: PaymentState = PaymentState(state="PENDING")
        self.successful_spend_cents: int = 0
        self.blocked_attempts: List[Dict[str, Any]] = []
        self.active_mandates: Dict[str, int] = {}
        self.cleared_agreements: Set[str] = set()
        self.transactions: List[Dict[str, Any]] = []

    def observe(self, action: Action, mandate_cap_cents: int | None = None) -> PaymentState:
        """Record *action* and recompute the latest ``PaymentState``."""
        if mandate_cap_cents is not None:
            self.active_mandates[action.agent] = mandate_cap_cents
        elif action.agent not in self.active_mandates:
            self.active_mandates[action.agent] = self.limits.per_agent

        # Check explicit mandate cap first
        effective_cap = mandate_cap_cents if mandate_cap_cents is not None else self.limits.per_agent
        if action.amount > effective_cap:
            self._latest_state = PaymentState(
                state="FAILED",
                reason=f"{action.agent} spent {action.amount} > {effective_cap}",
            )
            self.blocked_attempts.append({
                "seq": action.seq,
                "agent": action.agent,
                "amount": action.amount,
                "payee": action.payee,
                "reason": self._latest_state.reason,
                "tick": action.tick,
            })
            return self._latest_state

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
        
        if state == "FAILED":
            self.blocked_attempts.append({
                "seq": action.seq,
                "agent": action.agent,
                "amount": action.amount,
                "payee": action.payee,
                "reason": reason,
                "tick": action.tick,
            })
            
        self._latest_state = PaymentState(state=state, reason=reason)
        return self._latest_state

    @staticmethod
    def _derive_state_from_flags(flags: list) -> tuple[str, str | None]:
        """Map monitor flags to a ``PaymentState``."""
        if not flags:
            return "PENDING", None

        for _idx, flag in flags:
            rule = flag.rule
            if "over_limit" in rule or "relay" in rule or "split" in rule:
                return "FAILED", flag.reason or "Spending cap breached"
        return "FAILED", "; ".join(flag.reason for _idx, flag in flags)

    def record_spend(self, amount_cents: int = 0, tx_meta: dict | None = None) -> None:
        """Explicitly record a successful spend so metrics and log stay consistent."""
        if amount_cents > 0:
            self.successful_spend_cents += amount_cents
        if tx_meta:
            self.transactions.append(tx_meta)
        self._latest_state = PaymentState(state="COMPLETED", reason=None)

    def clear_agreement(self, agreement_id: str) -> None:
        """Record human clearance for an agreement or payout above threshold."""
        self.cleared_agreements.add(agreement_id)

    def is_cleared(self, agreement_id: str) -> bool:
        return agreement_id in self.cleared_agreements


class MoneyNotMoved(Exception):
    """Raised by the FastAPI handler when the oversight guard detected a
    spending-cap breach.
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
