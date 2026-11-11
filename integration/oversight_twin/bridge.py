"""swarm-oversight's principal-wide monitor at tabletop-twin's settlement seam.

The twin approves and submits each payment individually; every one can be under
its own ceiling and still belong to an aggregate no single mandate was allowed.
This module closes that gap in the twin's real settlement path. It wraps the
twin's transport: before a charge reaches PayPal (or the sandbox), the payment is
fed to one principal-wide swarm ``Session`` as an ``Action``. If the aggregate
crosses the per-payee bound, the wrapper raises the twin's own ``MoneyNotMoved``,
which the state machine turns into ``FAILED`` with the refusing rule named -- and
the provider is never called.

Neither baseline is modified. The wrapper implements the same ``charge``/``lookup``
contract the twin's ``PaymentMachine.submit`` already expects, so it guards the
real ``PayPalTransport`` and the ``SandboxTransport`` identically.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from swarm_oversight.model import Action, Flag
from swarm_oversight.monitor import CHECKS, Limits, Monitor, Session
from twin.payments.machine import MoneyNotMoved, PaymentMachine, PaymentRecord


def record_action(record: PaymentRecord, seq: int, agent: str, tick: int) -> Action:
    """Map a twin payment record onto a swarm action. Both already speak integer
    minor units, so the amount crosses unchanged; the recipient is the payee and
    the proposing mandate is the agent."""
    return Action(seq=seq, agent=agent, kind="spend", amount=record.amount_cents,
                  payee=record.recipient, tick=tick)


@dataclass
class Oversight:
    """One principal's swarm state, shared by every payment that principal settles.

    A refused payment is still observed into the session, exactly as the swarm
    gateway does it: the held amount inflates the payee's window total, so under
    hold-only the next payment to the same payee is read against it. ``freeze``
    additionally stops the whole principal after the first breach."""
    session: Session
    freeze: bool = True
    frozen: bool = False
    seq: int = 0
    refusals: list[tuple[str, int, str, tuple[str, ...]]] = field(default_factory=list)

    def check(self, agent: str, amount: int, payee: str, tick: int) -> list[Flag]:
        if self.frozen:
            return [Flag("swarm_frozen", (), "the principal is frozen for review")]
        flags = self.session.observe(Action(self.seq, agent, "spend", amount, payee, tick))
        self.seq += 1
        if flags:
            self.refusals.append((agent, amount, payee, tuple(f.rule for f in flags)))
            if self.freeze:
                self.frozen = True
        return flags


class OversightTransport:
    """Decorates a twin transport. The state machine still drives approve / submit
    / reconcile; this only decides whether a charge may leave. A breach raises
    ``MoneyNotMoved`` (refused before any charge existed), so the record lands
    ``FAILED`` and no network call is made. ``lookup`` passes straight through:
    oversight prevents a charge, it does not rewrite reconciliation of one already
    in flight."""

    def __init__(self, inner, oversight: Oversight, agent: str, tick: int) -> None:
        self.inner = inner
        self.oversight = oversight
        self.agent = agent
        self.tick = tick

    def charge(self, idempotency_key: str, amount_cents: int, recipient: str,
               currency: str = "USD"):
        flags = self.oversight.check(self.agent, amount_cents, recipient, self.tick)
        if flags:
            rules = ", ".join(sorted({f.rule for f in flags}))
            raise MoneyNotMoved(f"swarm oversight refused: {rules}")
        return self.inner.charge(idempotency_key, amount_cents, recipient, currency=currency)

    def lookup(self, idempotency_key: str):
        return self.inner.lookup(idempotency_key)


class SwarmOversight:
    """The principal-wide oversight layer. Construct once per principal, then
    submit each payment through it. ``freeze`` is the reaction to a breach: stop
    the whole principal (the shipped behaviour) or hold only the breaching payment.

    The twin enforces its own per-payment approval floor, so ``agent_over_limit``
    is not re-checked here -- exactly as the swarm gateway excludes it from its
    inline session. The swarm layer's job is the cross-mandate aggregate."""

    def __init__(self, limits: Limits | None = None, freeze: bool = True,
                 checks: tuple[str, ...] | None = None) -> None:
        self.limits = limits or Limits()
        ch = checks if checks is not None else tuple(c for c in CHECKS if c != "agent_over_limit")
        self.oversight = Oversight(Monitor(self.limits, ch).session(), freeze=freeze)

    def submit(self, machine: PaymentMachine, record: PaymentRecord, transport,
               agent: str, tick: int) -> PaymentRecord:
        return machine.submit(record, OversightTransport(transport, self.oversight, agent, tick))

    @property
    def frozen(self) -> bool:
        return self.oversight.frozen

    @property
    def refusals(self) -> list[tuple[str, int, str, tuple[str, ...]]]:
        return self.oversight.refusals