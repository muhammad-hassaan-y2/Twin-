"""Looking things up when nobody is standing at the table.

An ``unknown`` payment is a question the provider never answered. A client can
re-ask it on its next heartbeat, but that only helps while somebody keeps the
world open, and a charge that is neither settled nor refused is the last state
anybody should leave sitting overnight.

The sweep reads the store directly and rebuilds payment machines rather than
whole sessions: asking what happened to an attempt needs no Monte Carlo. It runs
only against a live transport, because a sandbox fake answers from its own memory
— a fake that restarted would report a real charge as never having happened.
"""

from __future__ import annotations

import json
import os
import threading
import time
from typing import Iterable

from twin.payments.machine import PaymentMachine, PaymentRecord, PaymentState
from twin.store import Store


def record_from_row(row: dict) -> PaymentRecord:
    return PaymentRecord(
        action_id=row["action_id"],
        amount_cents=int(row["amount_cents"]),
        recipient=row["recipient"],
        state=PaymentState(row["state"]),
        attempt=int(row["attempt"]),
        idempotency_key=row["idempotency_key"],
        provider_ref=row["provider_ref"],
        history=[tuple(entry) for entry in json.loads(row["history_json"])],
        verified_outcome=row["verified_outcome"],
        currency=row.get("currency") or "USD",
        rail=row.get("rail") or "sandbox",
        country=row.get("country") or "",
        fee_cents=int(row.get("fee_cents") or 0),
    )


def sweep(store: Store, transport, *, user_ids: Iterable[str] | None = None) -> dict:
    """Ask the provider about every unresolved payment. One lookup per attempt."""
    wanted = None if user_ids is None else {str(user) for user in user_ids}
    rows = [row for row in store.payments_in_state(PaymentState.UNKNOWN.value)
            if wanted is None or row["user_id"] in wanted]
    settled = failed = unclear = 0
    by_user: dict[str, list[dict]] = {}
    for row in rows:
        by_user.setdefault(row["user_id"], []).append(row)

    for user_id, items in by_user.items():
        machine = PaymentMachine()
        for row in items:
            machine.adopt(record_from_row(row))
        day = int((store.world_row(user_id) or {}).get("day") or 0)
        for row in items:
            record = machine.get(row["idempotency_key"])
            # Deliberately no verify_outcome here: the provider's answer says the money
            # moved, not that the thing it paid for arrived. The heartbeat reports that gap.
            machine.reconcile(record, transport)
            store.save_payment(
                user_id, record, verb=row["verb"], direction=row["direction"], settled_day=row["settled_day"]
            )
            store.append_log(
                user_id, day, "reconcile",
                {"action_id": record.action_id, "state": record.state.value, "source": "scheduler",
                 "attempt": record.attempt, "idempotency_key": record.idempotency_key},
            )
            if record.state is PaymentState.SUCCEEDED:
                settled += 1
            elif record.state is PaymentState.FAILED:
                failed += 1
            else:
                unclear += 1

    summary = {"checked": len(rows), "settled": settled, "failed": failed,
               "still_unknown": unclear, "at": time.time()}
    return summary


def interval_sec() -> float:
    """How often to sweep. Unset or zero means the reconciler never starts."""
    try:
        return max(0.0, float(os.environ.get("TWIN_RECONCILE_SEC", "0")))
    except (TypeError, ValueError):
        return 0.0


class ReconciliationLoop(threading.Thread):
    """Sweep on a timer, in the background, with nothing to look at."""

    def __init__(self, store: Store, transport, interval: float) -> None:
        super().__init__(daemon=True, name="twin-reconciler")
        self.store = store
        self.transport = transport
        self.interval = interval
        self.sweeps = 0
        self.last: dict | None = None
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.last = sweep(self.store, self.transport)
                self.sweeps += 1
            except Exception as exc:  # a broken sweep must not kill the process
                self.last = {"error": type(exc).__name__, "at": time.time()}

    def stop(self) -> None:
        self._stop.set()

    def status(self) -> dict:
        return {
            "running": self.is_alive(),
            "interval_sec": self.interval,
            "sweeps": self.sweeps,
            "last_sweep": self.last,
            "open_unknowns": len(self.store.payments_in_state(PaymentState.UNKNOWN.value)),
        }


def start(store: Store) -> ReconciliationLoop | None:
    """Start the loop if this deployment can answer a lookup, and was asked to."""
    from twin.payments.paypal import PayPalConfig, PayPalTransport

    interval = interval_sec()
    if interval <= 0:
        return None
    config = PayPalConfig.from_env()
    if config is None:
        return None
    loop = ReconciliationLoop(store, PayPalTransport(config), interval)
    loop.start()
    return loop
