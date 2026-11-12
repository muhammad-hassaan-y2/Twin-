"""PayPal Orders v2 & Payouts integration for the oversight_twin payment pipeline.

Handles OAuth2 client-credentials auth, order creation, order capture, payouts,
and graceful error handling so that network failures result in an UNKNOWN
reconciliation state rather than double-charging.
"""

from __future__ import annotations

import os
import uuid
import httpx
from typing import Dict, Any


class MoneyNotMoved(Exception):
    """Raised when a payment cannot be completed – either because a spending
    cap was breached locally (oversight guard) or because the PayPal API
    rejected the request.
    """
    pass


class PayPalClient:
    """PayPal Orders v2 & Payouts API client using client-credentials OAuth2."""

    SANDBOX_BASE = "https://api-m.sandbox.paypal.com"
    AUTH_URL = f"{SANDBOX_BASE}/v1/oauth2/token"
    ORDERS_URL = f"{SANDBOX_BASE}/v2/checkout/orders"
    PAYOUTS_URL = f"{SANDBOX_BASE}/v1/payments/payouts"

    def __init__(self, client_id: str, secret: str, http: httpx.AsyncClient | None = None) -> None:
        self.client_id = client_id
        self.secret = secret
        self._http = http or httpx.AsyncClient(timeout=15.0)
        self._access_token: str | None = None
        self._is_simulated = (
            client_id.startswith("test-")
            or client_id in ("mock", "simulated", "")
            or os.getenv("PAYPAL_SIMULATE", "").lower() in ("1", "true", "yes")
        )
        self._simulated_orders: Dict[str, Dict[str, Any]] = {}
        self._simulated_payouts: Dict[str, Dict[str, Any]] = {}

    async def _get_token(self) -> str:
        """Fetch or refresh the OAuth2 access token."""
        if self._is_simulated:
            return "simulated-access-token"
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
        usd_amount = f"{amount_cents / 100:.2f}"
        if self._is_simulated:
            order_id = f"ORDER-PP-{uuid.uuid4().hex[:12].upper()}"
            order = {
                "id": order_id,
                "status": "CREATED",
                "intent": "CAPTURE",
                "payee_id": payee_id,
                "purchase_units": [
                    {
                        "reference_id": f"ref-{payee_id}",
                        "amount": {"currency_code": "USD", "value": usd_amount},
                    }
                ],
                "create_time": "2026-11-12T00:00:00Z",
                "links": [
                    {"href": f"https://www.sandbox.paypal.com/checkoutnow?token={order_id}", "rel": "approve", "method": "GET"}
                ]
            }
            self._simulated_orders[order_id] = order
            return order

        token = await self._get_token()
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "custom_id": payee_id,
                    "amount": {
                        "currency_code": "USD",
                        "value": usd_amount,
                        "breakdown": {
                            "item_total": {
                                "currency_code": "USD",
                                "value": usd_amount,
                            }
                        },
                    },
                }
            ],
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = await self._http.post(self.ORDERS_URL, json=payload, headers=headers)
        if resp.status_code == 400:
            raise MoneyNotMoved("PayPal order creation failed (bad request)")
        resp.raise_for_status()
        return resp.json()

    async def capture_order(self, order_id: str) -> Dict[str, Any]:
        """Capture payment for an approved PayPal order.

        Returns capture details including capture ID and status COMPLETED.
        """
        if self._is_simulated:
            order = self._simulated_orders.get(order_id)
            if not order:
                order = {
                    "id": order_id,
                    "status": "CREATED",
                    "purchase_units": [{"amount": {"currency_code": "USD", "value": "10.00"}}],
                }
            capture_id = f"CAP-{uuid.uuid4().hex[:12].upper()}"
            order["status"] = "COMPLETED"
            order["purchase_units"][0]["payments"] = {
                "captures": [
                    {"id": capture_id, "status": "COMPLETED", "amount": order["purchase_units"][0]["amount"]}
                ]
            }
            self._simulated_orders[order_id] = order
            return order

        token = await self._get_token()
        url = f"{self.ORDERS_URL}/{order_id}/capture"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = await self._http.post(url, headers=headers)
        if resp.status_code == 400:
            raise MoneyNotMoved("PayPal capture failed (bad request / not approved)")
        resp.raise_for_status()
        return resp.json()

    async def get_order(self, order_id: str) -> Dict[str, Any]:
        """Fetch details of an existing PayPal order for reconciliation."""
        if self._is_simulated:
            if order_id in self._simulated_orders:
                return self._simulated_orders[order_id]
            return {"id": order_id, "status": "COMPLETED"}

        token = await self._get_token()
        url = f"{self.ORDERS_URL}/{order_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = await self._http.get(url, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def create_payout(self, recipient: str, amount_cents: int, note: str = "") -> Dict[str, Any]:
        """Disburse funds to a contractor or vendor via PayPal Payouts."""
        usd_amount = f"{amount_cents / 100:.2f}"
        batch_id = f"PAYOUT-BATCH-{uuid.uuid4().hex[:10].upper()}"

        if self._is_simulated:
            payout = {
                "batch_header": {
                    "payout_batch_id": batch_id,
                    "batch_status": "SUCCESS",
                    "sender_batch_header": {"email_subject": note or "Vendor Payout via AI Agent"},
                    "amount": {"currency": "USD", "value": usd_amount},
                },
                "items": [
                    {
                        "payout_item_id": f"ITEM-{uuid.uuid4().hex[:8].upper()}",
                        "transaction_status": "SUCCESS",
                        "receiver": recipient,
                        "amount": {"currency": "USD", "value": usd_amount},
                    }
                ]
            }
            self._simulated_payouts[batch_id] = payout
            return payout

        token = await self._get_token()
        payload = {
            "sender_batch_header": {
                "sender_batch_id": batch_id,
                "email_subject": note or "AI Agent Vendor Disbursement",
            },
            "items": [
                {
                    "recipient_type": "EMAIL" if "@" in recipient else "PAYPAL_ID",
                    "amount": {"value": usd_amount, "currency": "USD"},
                    "receiver": recipient,
                    "note": note,
                    "sender_item_id": f"item-{uuid.uuid4().hex[:8]}",
                }
            ],
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        resp = await self._http.post(self.PAYOUTS_URL, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()

    async def close(self) -> None:
        await self._http.aclose()
