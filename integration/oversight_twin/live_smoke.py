"""Explicit opt-in, sandbox-only smoke; never treats a refusal as successful settlement."""
from __future__ import annotations

import os
import sys
from uuid import uuid4

from swarm_oversight.monitor import Limits
from twin.payments.paypal import PayPalConfig, PayPalTransport

from .hub import Agreement, HumanGate, PayPalHub


def main(argv: list[str] | None = None) -> int:
    if argv:
        print("Usage: python -m oversight_twin.live_smoke (fixed USD 1.00 sandbox attempt)")
        return 2
    config = PayPalConfig.from_env()
    if config is not None and (config.environment != "sandbox" or config.test_server_url):
        print("REFUSED: this smoke test only permits the PayPal sandbox.")
        return 2
    if config is None or os.environ.get("PAYPAL_SANDBOX_SMOKE") != "1":
        print("SKIPPED: set PAYPAL_CLIENT_ID, PAYPAL_SECRET and PAYPAL_SANDBOX_SMOKE=1.")
        print("No network request or payment was made.")
        return 0
    agreement = Agreement(f"sandbox-smoke-{uuid4().hex}", "sandbox-smoke", "tabletop-twin", 100)
    limits = Limits(per_agent=100, per_payee=100, window=10, long_window=60, merge="both")
    hub = PayPalHub(PayPalTransport(config), limits=limits, gate=HumanGate({agreement.id}))
    try:
        result = hub.settle(agreement)
    except Exception:
        # Provider exception text can contain credentials; only emit our fixed messages.
        print("FAILED: sandbox request could not be completed; no success is claimed.")
        return 1
    print(f"PayPal sandbox: USD 1.00 attempt, state={result.state}.")
    if result.settled:
        print("PASS: the sandbox confirmed capture (test funds only).")
        return 0
    if result.state == "unknown":
        print("PENDING: buyer approval or reconciliation is required; capture is not confirmed.")
        print("Do not start another payment to resolve this attempt.")
        return 3
    print("FAILED: the sandbox refused settlement; this is not a passing payment test.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
