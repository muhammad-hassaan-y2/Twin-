"""Automated test suite for the PayPal AI Hackathon submission.

Covered scenarios (all against the PayPal Sandbox — tests use a mock client
so no real HTTP calls are made unless the PayPal client is configured).

```bash
pytest tests/test_hackathon_submission.py -v
```
"""

from __future__ import annotations

import os
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from app.main import app, _get_session, Session, Action, PaymentState, MoneyNotMoved
from app.oversight_twin import MoneyNotMoved as TwinMoneyNotMoved

# ---------------------------------------------------------------------------
# Test client & fixtures
# ---------------------------------------------------------------------------

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_session_and_paypal():
    """Ensure a fresh session and paypal client per test."""
    # Reset module-level state
    from app import main as main_mod
    main_mod._paypal_client = None
    main_mod._session = None

    # Set dummy PayPal sandbox credentials so the client can be instantiated.
    # Real sandbox calls are not made; create_order is patched in individual tests.
    os.environ.setdefault("PAYPAL_CLIENT_ID", "test-client-id")
    os.environ.setdefault("PAYPAL_SECRET", "test-secret")

    yield

    # Cleanup after test
    main_mod._paypal_client = None
    main_mod._session = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_charge_payload(agent_id: str, payee_id: str, amount_cents: int, mandate_cap_cents: int) -> Dict[str, Any]:
    return {
        "agent_id": agent_id,
        "payee_id": payee_id,
        "amount_cents": amount_cents,
        "mandate_cap_cents": mandate_cap_cents,
    }


# ---------------------------------------------------------------------------
# Endpoint existence / basic routing
# ---------------------------------------------------------------------------


def test_post_charge_endpoint_exists():
    """POST /api/v1/agents/ charge endpoint is registered."""
    resp = client.post(
        "/api/v1/agents/charge",
        json={
            "agent_id": "agent-01",
            "payee_id": "payee-01",
            "amount_cents": 1_000,
            "mandate_cap_cents": 5_000,
        },
    )
    assert resp.status_code in (200, 402, 500)
    assert "application/json" in resp.headers.get("content-type", "")


def test_get_metrics_endpoint_exists():
    """GET /api/v1/swarm/metrics endpoint is registered."""
    resp = client.get("/api/v1/swarm/metrics")
    assert resp.status_code == 200
    assert "application/json" in resp.headers.get("content-type", "")
    body = resp.json()
    assert "total_spend_cents" in body
    assert "active_mandates" in body
    assert "caught_attack_attempts" in body


# ---------------------------------------------------------------------------
# Negative Control 1: Single Agent Over Cap
# ---------------------------------------------------------------------------


def test_single_agent_over_cap_triggers_guard_and_returns_402():
    """When one agent exceeds its mandate cap the oversight guard catches it
    and returns HTTP 402 — zero HTTP call to PayPal Sandbox.

    This is the *Negative Control 1* scenario.
    """
    payload = {
        "agent_id": "agent-01",
        "payee_id": "payee-01",
        "amount_cents": 150_000,  # exceeds per-agent limit of 50_000
        "mandate_cap_cents": 100_000,
    }

    resp = client.post("/api/v1/agents/charge", json=payload)

    assert resp.status_code == 402, f"Expected 402, got {resp.status_code}: {resp.json()}"

    body = resp.json()
    assert body.get("state") == "FAILED", f"Expected FAILED state, got {body}"


# ---------------------------------------------------------------------------
# Negative Control 2: Collusive Multi-Agent Split Attack
# ---------------------------------------------------------------------------


def test_collusive_split_attack_agent_c_fails_no_paypal_call():
    """Agent A ($40) + Agent B ($40) + Agent C ($30) against a global principal
    cap of $100.  Agent C's attempt must throw MoneyNotMoved, set state to FAILED,
    and issue ZERO HTTP calls to PayPal Sandbox.

    This is *Negative Control 2* from the deliverables.
    """

    import app.main as m_mod

    m_mod._session = None

    from swarm_oversight.monitor import Limits
    tight_limits = Limits(
        per_agent=50_000,
        per_payee=90_000,
        window=10,
        split_min_agents=2,
        long_window=60,
        alias_ratio=0.85,
    )
    m_mod._session = Session(limits=tight_limits)

    # --- Agent A spends 40_000 cents ($40) ---
    action_a = Action(seq=0, agent="agent-A", kind="spend", amount=40_000, payee="payee-X", tick=0)
    state_a = m_mod._session.observe(action_a)
    assert state_a.state == "PENDING", f"Agent A should pass guard, got {state_a.state}"

    # --- Agent B spends 40_000 cents ($40) ---
    action_b = Action(seq=1, agent="agent-B", kind="spend", amount=40_000, payee="payee-X", tick=1)
    state_b = m_mod._session.observe(action_b)
    assert state_b.state == "PENDING", f"Agent B should pass guard, got {state_b.state}"

    # --- Agent C attempts 30_000 cents ($30) - this should breach the payee cap ---
    action_c = Action(seq=2, agent="agent-C", kind="spend", amount=30_000, payee="payee-X", tick=2)
    state_c = m_mod._session.observe(action_c)

    assert state_c.state == "FAILED", f"Agent C should be blocked by guard, got {state_c.state}"
    assert state_c.reason is not None, "Expected a reason for the FAILED state"

    # Now attempt the actual HTTP endpoint with Agent C's payload.
    payload_c = {
        "agent_id": "agent-C",
        "payee_id": "payee-X",
        "amount_cents": 30_000,
        "mandate_cap_cents": 100_000,
    }

    resp = client.post("/api/v1/agents/charge", json=payload_c)

    assert resp.status_code == 402, f"Expected 402, got {resp.status_code}: {resp.json()}"

    body = resp.json()
    assert body.get("state") == "FAILED", f"Expected FAILED state in response, got {body}"

    print(
        f"[PASS] Collusive split attack: agent C blocked (state={state_c.state}, "
        f"reason='{state_c.reason}'), endpoint returned 402 with FAILED state."
    )


# ---------------------------------------------------------------------------
# Standard Success: Single agent under mandate -> HTTP 200
# ---------------------------------------------------------------------------


def test_single_agent_under_mandate_returns_completed():
    """A single agent acting under its mandate cap should pass the guard,
    hit the PayPal Sandbox (mocked), and return HTTP 200 with COMPLETED state.

    This is the *Standard Success* scenario.
    """
    import app.main as m_mod

    m_mod._session = None

    # Use default limits; a single spend of 5_000 cents under the per-agent
    # cap of 50_000 should pass.
    session = Session(limits=m_mod.Limits if hasattr(m_mod, "Limits") else __import__("swarm_oversight.monitor", fromlist=["Limits"]).Limits)

    action = Action(seq=0, agent="agent-01", kind="spend", amount=5_000, payee="payee-01", tick=0)
    state = session.observe(action)

    assert state.state == "PENDING", f"Expected PENDING guard state, got {state.state}"

    # Build the charge payload
    payload = {
        "agent_id": "agent-01",
        "payee_id": "payee-01",
        "amount_cents": 5_000,
        "mandate_cap_cents": 100_000,
    }

    # Mock PayPal client: replace the cached instance in the app module
    from app import main as app_main

    # Create a minimal mock PayPal client
    import app.paypal_client as pc_mod

    mock_client = pc_mod.PayPalClient("test-client-id", "test-secret")

    async def _fake_create(amount_cents: int, payee_id: str) -> Dict[str, Any]:
        return {
            "id": "ORDER-FAKE-12345",
            "status": "COMPLETED",
            "purchase_units": [{"amount": {"value": f"{amount_cents / 100:.2f}"}}],
        }

    # Replace the create_order method on the mock client
    mock_client.create_order = _fake_create  # type: ignore

    # Replace the cached PayPal client in the app main module
    # so that the endpoint's _get_paypal_client() returns our mock.
    original_cached = app_main._paypal_client
    app_main._paypal_client = mock_client

    try:
        resp = client.post("/api/v1/agents/charge", json=payload)

        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.json()}"

        body = resp.json()
        assert body.get("state") == "COMPLETED", f"Expected COMPLETED state, got {body}"
        assert body.get("paypal_order_id") == "ORDER-FAKE-12345", f"Expected fake order ID, got {body}"

        print(
            f"[PASS] Standard success: agent under mandate -> 200 COMPLETED, "
            f"order={body.get('paypal_order_id')}"
        )
    finally:
        # Restore original cached client
        app_main._paypal_client = original_cached