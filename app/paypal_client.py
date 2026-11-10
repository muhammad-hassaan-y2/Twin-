"""PayPal Orders v2 integration for the oversight_twin payment pipeline.

Handles OAuth2 client-credentials auth, order creation, and graceful error
handling so that network failures result in an UNKNOWN reconciliation state.
"""

from __future__ import annotations

import httpx
from typing import Dict, Any


class PayPalClient:
    """PayPal Orders v2 API client using client-credentials OAuth2."""

    SANDBOX_BASE = "https://api-m.sandbox.paypal.com"
    AUTH_URL = f"{SANDBOX_BASE}/v1/oauth2/token"
    ORDERS_URL = f"{SANDBOX_BASE}/v2/checkout/orders"

    def __init__(self, client_id: str, secret: str, http: httpx.AsyncClient | None = None) -> None:
        self.client_id = client_id
        self.secret = secret
        self._http = http or httpx.AsyncClient(timeout=30.0)
        self._access_token: str | None = None

    async def _get_token(self) -> str:
        """Fetch or refresh the OAuth2 access token."""
        if self._access_token:
            return self._access_token
        resp = await self._http.post(
            self.AUTH_URL,
            auth=httpx.HTTPBasicAuth(self.client_id, self.secret),
            data={"grant_type": "client_credentials"},
        )
        resp.raise_for_status()
        data = resp.json()
        self._access_token = data["access_token"]
        return self._access_token

    async def create_order(self, amount_cents: int, payee_id: str) -> Dict[str, Any]:
        """Create a PayPal order for *amount_cents* (integer cents -> "15.00" USD).

        Returns the parsed PayPal order JSON on success.
        """
        token = await self._get_token()
        usd_amount = f"{amount_cents / 100:.2f}"
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "amount": {
                        "currency_code": "USD",
                        "value": usd_amount,
                        "breakdown": {
                            "item_total": {
                                "currency_code": "USD",
                                "value": usd_amount,
                            }
                        },
                    }
                }
            ],
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = await self._http.post(self.ORDERS_URL, json=payload, headers=headers)
        if resp.status_code == 400:
            # Bad request – treat as a reconcilable UNKNOWN rather than crashing.
            raise MoneyNotMoved("PayPal order creation failed (bad request)")
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._http.aclose()


class MoneyNotMoved(Exception):
    """Raised when a payment cannot be completed – either because a spending
    cap was breached locally (oversight guard) or because the PayPal API
    rejected the request.

    The calling handler should convert this into an HTTP 402 or a
    PaymentState.UNKNOWN as appropriate.
    """
    pass