"""Runnable proof that the integration closes the aggregate gap in the twin's
real settlement path. One principal, four mandates: three pay one payee an amount
each under its own ceiling, a fourth pays a different, legitimate payee. Every
payment is individually approved by a held gesture. Together the three cross the
principal's per-payee bound -- the gap a per-mandate ceiling cannot see.

    python -m oversight_twin.demo            # run from integration/
"""
from __future__ import annotations

from swarm_oversight.monitor import Limits
from twin.payments.machine import PaymentMachine, PaymentState
from twin.payments.paypal import SandboxTransport

from .bridge import SwarmOversight

# (mandate / agent, cents, payee, tick)
PAYMENTS = [
    ("mandate-0", 25_000, "offshore-consulting", 0),
    ("mandate-1", 25_000, "offshore-consulting", 1),
    ("mandate-2", 25_000, "offshore-consulting", 2),
    ("mandate-3", 20_000, "cloud-host", 3),
]
LIMITS = Limits(per_agent=50_000, per_payee=60_000, window=10, long_window=60, merge="both")


def settle(payments, oversight: SwarmOversight | None = None):
    """Drive the twin's real state machine + sandbox transport. With no oversight
    this is the twin as shipped; with it, every submit crosses the swarm bound."""
    machine = PaymentMachine(approval_floor_cents=5_000)
    transport = SandboxTransport()
    rows, settled = [], 0
    for agent, amount, payee, tick in payments:
        rec = machine.open(f"{agent}:{payee}:{tick}", amount, payee, rail="sandbox")
        machine.propose(rec)
        machine.approve(rec, "pinch_hold_1s")  # the human approved THIS payment
        if oversight is None:
            machine.submit(rec, transport)
        else:
            oversight.submit(machine, rec, transport, agent, tick)
        ok = rec.state is PaymentState.SUCCEEDED
        settled += amount if ok else 0
        rows.append((agent, amount, payee, rec.state.value))
    return settled, rows


def main() -> None:
    attempted = sum(a for _, a, _, _ in PAYMENTS)
    print("One principal, four mandates. Each payment is individually approved and")
    print(f"under its own ceiling; the three to one payee total 75000c against a")
    print(f"{LIMITS.per_payee}c per-payee bound inside {LIMITS.window} ticks.\n")

    base, rows = settle(PAYMENTS)
    print(f"per-mandate only (the twin as shipped): {base}c of {attempted}c settled")
    for r in rows:
        print("   ", r)

    ov = SwarmOversight(LIMITS, freeze=True)
    frz, rows = settle(PAYMENTS, ov)
    print(f"\n+ swarm oversight, freeze: {frz}c settled, frozen={ov.frozen}")
    for r in rows:
        print("   ", r)
    print("    refusals:", ov.refusals)

    ov2 = SwarmOversight(LIMITS, freeze=False)
    hold, rows = settle(PAYMENTS, ov2)
    print(f"\n+ swarm oversight, hold only: {hold}c settled, frozen={ov2.frozen}")
    for r in rows:
        print("   ", r)

    print(f"\nThe gap: per-mandate lets {base}c out. The principal-wide bound holds the")
    print(f"one-payee aggregate to {frz}c; freeze also stops the legitimate fourth")
    print(f"payment, hold-only lets it through ({hold}c). Same approved payments, same")
    print("state machine, same transport -- the only change is the oversight layer.")


if __name__ == "__main__":
    main()