"""Single-process settlement coordinator: human clearance, swarm guard, then PayPal."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from threading import RLock
from uuid import uuid4

from swarm_oversight.monitor import Limits
from twin.audit.chain import Chain, ChainError
from twin.payments.machine import PaymentMachine, PaymentRecord, PaymentState

HUMAN_HOLD = "pointer_hold_1s"


@dataclass(frozen=True)
class Agreement:
    id: str
    agent: str
    payee: str
    amount_cents: int
    currency: str = "USD"

    def __post_init__(self):
        if not all(isinstance(s, str) and s.strip() for s in (self.id, self.agent, self.payee)):
            raise ValueError("agreement id, agent and payee must be named")
        if type(self.amount_cents) is not int or self.amount_cents <= 0:
            raise ValueError("agreement amount must be positive integer minor units")


@dataclass(frozen=True)
class Settlement:
    agreement: str
    agent: str
    payee: str
    amount_cents: int
    state: str
    provider_ref: str | None = None
    note: str = ""
    chain_state: str = ""

    @property
    def settled(self) -> bool:
        return self.state == PaymentState.SUCCEEDED.value


class HumanGate:
    """Trusted caller's explicit clearance, not an authentication or signing service."""

    def __init__(self, cleared: set[str] | None = None):
        self._cleared = set(cleared or ())

    def clear(self, agreement_id: str):
        self._cleared.add(agreement_id)

    def cleared(self, agreement_id: str) -> bool:
        return agreement_id in self._cleared


@dataclass
class PayPalHub:
    transport: object
    limits: Limits | None = None
    freeze: bool = True
    approval_floor_cents: int = 5_000
    gate: HumanGate = field(default_factory=HumanGate)
    currency: str = "USD"
    chain: Chain | None = None
    machine: PaymentMachine = field(init=False)
    oversight: object = field(init=False)
    settlements: list[Settlement] = field(init=False, default_factory=list)
    _agreements: dict[str, Agreement] = field(init=False, default_factory=dict)
    _payments: dict[str, PaymentRecord] = field(init=False, default_factory=dict)
    _latest: dict[str, Settlement] = field(init=False, default_factory=dict)
    _lock: object = field(init=False, default_factory=RLock)

    def __post_init__(self):
        from .bridge import SwarmOversight

        self.machine = PaymentMachine(approval_floor_cents=self.approval_floor_cents)
        self.oversight = SwarmOversight(self.limits, freeze=self.freeze)

    def settle(self, agreement: Agreement, tick: int = 0) -> Settlement:
        with self._lock:
            if agreement.currency != self.currency:
                raise ValueError("one hub must use one currency for its aggregate limits")
            previous = self._agreements.setdefault(agreement.id, agreement)
            if previous != agreement:
                raise ValueError("an agreement id cannot be reused with different payment terms")
            record = self._payments.get(agreement.id)
            if record is not None:
                if record.state is PaymentState.UNKNOWN:
                    self.machine.reconcile(record, self.transport)
                return self._payment_result(agreement, record)
            if not self.gate.cleared(agreement.id):
                return self._record(Settlement(
                    agreement.id, agreement.agent, agreement.payee, agreement.amount_cents,
                    "awaiting_human", note="no human clearance for this agreement"))
            if self.chain is not None:
                source = self.chain.agreement(agreement.id)
                if (source.get("from_role") != agreement.agent
                        or source.get("to_role") != agreement.payee
                        or int(source.get("amountCents", 0)) != agreement.amount_cents):
                    raise ValueError("payment terms do not match the chain agreement")
                if source.get("state") != "Attested":
                    raise ValueError("only an attested chain agreement can enter settlement")
                signed = source.get("signedBy", "")
                if not signed or int(signed, 16) == 0:
                    return self._record(Settlement(
                        agreement.id, agreement.agent, agreement.payee, agreement.amount_cents,
                        "awaiting_human", note="chain counterparty has not countersigned"))
            record = self.machine.open(agreement.id, agreement.amount_cents, agreement.payee,
                                       currency=agreement.currency, rail="paypal")
            self._payments[agreement.id] = record
            self.machine.propose(record)
            self.machine.approve(record, HUMAN_HOLD)
            self.oversight.submit(self.machine, record, self.transport, agreement.agent, tick)
            if record.state is PaymentState.UNKNOWN:
                self.machine.reconcile(record, self.transport)
            return self._payment_result(agreement, record)

    def _payment_result(self, agreement: Agreement, record: PaymentRecord) -> Settlement:
        result = Settlement(agreement.id, agreement.agent, agreement.payee, agreement.amount_cents,
                            record.state.value, record.provider_ref,
                            record.history[-1][2] if record.history else "")
        if self.chain is not None and result.settled:
            # A failed chain write must never send an already-paid fee to PayPal again.
            try:
                state = self.chain.agreement(agreement.id)["state"]
                if state == "Attested":
                    receipt = self.chain.write("settle", id=agreement.id, by_role=agreement.payee)
                    state = "Settled" if receipt.ok else "record_pending"
                result = replace(result, chain_state=state)
            except ChainError:
                result = replace(result, chain_state="record_pending")
        return self._record(result)

    def settle_all(self, agreements: list[Agreement], start_tick: int = 0) -> list[Settlement]:
        return [self.settle(a, start_tick + i) for i, a in enumerate(agreements)]

    def _record(self, settlement: Settlement) -> Settlement:
        self.settlements.append(settlement)
        self._latest[settlement.agreement] = settlement
        return settlement

    def state_of(self, agreement_id: str) -> str | None:
        """The payment state already held for an agreement, or None before it was opened."""
        record = self._payments.get(agreement_id)
        return record.state.value if record is not None else None

    @property
    def settled_cents(self) -> int:
        return sum(s.amount_cents for s in self._latest.values() if s.settled)

    @property
    def frozen(self) -> bool:
        return self.oversight.frozen

    @property
    def refusals(self):
        return self.oversight.refusals


def firm_agreements(case, firm=None, payee: str | None = None, *, bus=None,
                    review_id: str | None = None, currency: str = "USD") -> list[Agreement]:
    """Without a bus these are simulated instructions, not on-chain agreements."""
    from twin.audit.agents import Firm

    firm = firm or Firm()
    if bus is not None:
        if payee is not None:
            raise ValueError("on-chain agreements retain their recorded counterparty")
        review = firm.transact(case, bus)
        findings = {f["role"]: f for f in review["findings"]}
        return [Agreement(row["agreement"], row["role"], findings[row["role"]]["to_role"],
                          case.audit_fee_cents, currency)
                for row in review["agreements"] if row["state"] == "Attested"]
    identity = review_id or uuid4().hex
    return [Agreement(f"{identity}:{finding.role}", finding.role, payee or finding.to_role,
                      case.audit_fee_cents, currency)
            for finding in firm.review(case) if finding.binding]
