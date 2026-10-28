"""Payment state machine.

The rule that matters: once a payment is SUBMITTED and the transport does not
answer cleanly, the record goes to UNKNOWN — and from UNKNOWN the only legal
move is to ask the provider what actually happened. Retrying blind is refused
in code, because a duplicate charge is the one failure this app cannot take
back.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum


class PaymentState(str, Enum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    RECONCILING = "reconciling"
    CANCELLED = "cancelled"


TERMINAL = frozenset({PaymentState.SUCCEEDED, PaymentState.FAILED, PaymentState.CANCELLED})

LEGAL = {
    PaymentState.DRAFT: {PaymentState.PROPOSED, PaymentState.CANCELLED},
    PaymentState.PROPOSED: {PaymentState.APPROVED, PaymentState.CANCELLED},
    PaymentState.APPROVED: {PaymentState.SUBMITTED, PaymentState.CANCELLED},
    PaymentState.SUBMITTED: {PaymentState.SUCCEEDED, PaymentState.FAILED, PaymentState.UNKNOWN},
    PaymentState.UNKNOWN: {PaymentState.RECONCILING},
    PaymentState.RECONCILING: {PaymentState.SUCCEEDED, PaymentState.FAILED, PaymentState.UNKNOWN},
    PaymentState.SUCCEEDED: set(),
    PaymentState.FAILED: {PaymentState.PROPOSED},
    PaymentState.CANCELLED: set(),
}


class IllegalTransition(RuntimeError):
    pass


class ApprovalRequired(RuntimeError):
    pass


class AmbiguousResult(RuntimeError):
    """Raised by transports when the provider's answer cannot be trusted."""


def idempotency_key(action_id: str, attempt: int) -> str:
    digest = hashlib.sha256(f"{action_id}:{attempt}".encode()).hexdigest()
    return f"tt-{digest[:24]}"


@dataclass
class PaymentRecord:
    action_id: str
    amount_cents: int
    recipient: str
    state: PaymentState = PaymentState.DRAFT
    attempt: int = 0
    idempotency_key: str = ""
    provider_ref: str | None = None
    history: list[tuple[float, str, str]] = field(default_factory=list)
    verified_outcome: str | None = None

    def __post_init__(self) -> None:
        if not self.idempotency_key:
            self.idempotency_key = idempotency_key(self.action_id, self.attempt)
        self._log(self.state.value, "created")

    def _log(self, state: str, note: str) -> None:
        self.history.append((time.time(), state, note))


class PaymentMachine:
    """Approve, submit, and — if anything is unclear — go look."""

    def __init__(self, approval_floor_cents: int = 5_000) -> None:
        self.approval_floor_cents = approval_floor_cents
        self._by_key: dict[str, PaymentRecord] = {}

    def open(self, action_id: str, amount_cents: int, recipient: str) -> PaymentRecord:
        record = PaymentRecord(action_id=action_id, amount_cents=amount_cents, recipient=recipient)
        self._by_key[record.idempotency_key] = record
        return record

    def get(self, idempotency_key: str) -> PaymentRecord:
        try:
            return self._by_key[idempotency_key]
        except KeyError as exc:
            raise KeyError(f"no payment for key {idempotency_key}") from exc

    def all(self) -> list[PaymentRecord]:
        """Every record this machine opened, deduplicated across retries.

        A retried payment keeps its identity and gains a second key, so the same
        object appears twice in the index.
        """
        return list({id(r): r for r in self._by_key.values()}.values())

    def propose(self, record: PaymentRecord) -> PaymentRecord:
        return self._move(record, PaymentState.PROPOSED, "policy allowed / awaiting approval")

    def cancel(self, record: PaymentRecord, reason: str = "cancelled") -> PaymentRecord:
        return self._move(record, PaymentState.CANCELLED, reason)

    def approve(self, record: PaymentRecord, gesture: str) -> PaymentRecord:
        """A gesture is only accepted if it is the one the policy asked for."""
        if record.amount_cents >= self.approval_floor_cents and gesture != "pinch_hold_1s":
            raise ApprovalRequired(
                f"{record.amount_cents}c needs a held pinch, not '{gesture}'"
            )
        return self._move(record, PaymentState.APPROVED, f"gesture={gesture}")

    def submit(self, record: PaymentRecord, transport) -> PaymentRecord:
        record = self._move(record, PaymentState.SUBMITTED, f"key={record.idempotency_key}")
        try:
            result = transport.charge(record.idempotency_key, record.amount_cents, record.recipient)
        except AmbiguousResult as exc:
            return self._move(record, PaymentState.UNKNOWN, f"ambiguous: {exc}")
        except Exception as exc:  # transport blew up: we do not know anything
            return self._move(record, PaymentState.UNKNOWN, f"transport error: {exc}")

        status = str(getattr(result, "status", "")).lower()
        if status in {"completed", "succeeded", "captured"}:
            record.provider_ref = getattr(result, "reference", None)
            return self._move(record, PaymentState.SUCCEEDED, f"ref={record.provider_ref}")
        if status in {"denied", "failed", "invalid"}:
            return self._move(record, PaymentState.FAILED, f"provider said {status}")
        return self._move(record, PaymentState.UNKNOWN, f"unrecognised status '{status}'")

    def reconcile(self, record: PaymentRecord, transport) -> PaymentRecord:
        """From UNKNOWN the only way out is a status lookup on the same key."""
        if record.state is not PaymentState.UNKNOWN:
            raise IllegalTransition(f"reconcile only applies to UNKNOWN, not {record.state.value}")
        record = self._move(record, PaymentState.RECONCILING, "asking the provider")
        try:
            truth = transport.lookup(record.idempotency_key)
        except Exception as exc:
            return self._move(record, PaymentState.UNKNOWN, f"lookup failed again: {exc}")

        status = str(getattr(truth, "status", "")).lower()
        if status in {"completed", "succeeded", "captured"}:
            record.provider_ref = getattr(truth, "reference", None)
            return self._move(record, PaymentState.SUCCEEDED, f"recovered ref={record.provider_ref}")
        if status in {"not_found", "denied", "failed", "invalid"}:
            return self._move(record, PaymentState.FAILED, f"provider confirmed {status}")
        return self._move(record, PaymentState.UNKNOWN, f"still unclear: {status}")

    def retry(self, record: PaymentRecord) -> PaymentRecord:
        """Blind retry is refused. The old key must be resolved first."""
        if record.state is PaymentState.UNKNOWN:
            raise IllegalTransition(
                "refusing to retry: the previous attempt is unresolved, "
                "a second charge could duplicate it"
            )
        if record.state is not PaymentState.FAILED:
            raise IllegalTransition(f"cannot retry from {record.state.value}")
        record.attempt += 1
        record.idempotency_key = idempotency_key(record.action_id, record.attempt)
        self._by_key[record.idempotency_key] = record
        return self._move(record, PaymentState.PROPOSED, f"fresh attempt {record.attempt}")

    def verify_outcome(self, record: PaymentRecord, outcome: str) -> PaymentRecord:
        """A SUCCEEDED payment is not done until the business effect is seen."""
        if record.state is not PaymentState.SUCCEEDED:
            raise IllegalTransition("outcome verification only applies to a succeeded payment")
        record.verified_outcome = outcome
        record._log(record.state.value, f"verified {outcome}")
        return record

    def _move(self, record: PaymentRecord, target: PaymentState, note: str) -> PaymentRecord:
        if target not in LEGAL[record.state]:
            raise IllegalTransition(f"{record.state.value} -> {target.value} is not legal")
        record.state = target
        record._log(target.value, note)
        return record
