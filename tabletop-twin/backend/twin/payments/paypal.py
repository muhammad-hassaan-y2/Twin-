"""PayPal transport.

Two implementations behind one shape: the real v2 orders API, and a sandbox
fake that can be told to lose a response — because the interesting behaviour
is not the happy path, it is what the machine does when the answer never
arrives.

Credentials come from the environment. Nothing here has a default secret.
"""

from __future__ import annotations

import base64
import http.client
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from twin.payments.machine import AmbiguousResult, MoneyNotMoved
from twin.payments.rails import load_catalog


@dataclass(frozen=True)
class ProviderResult:
    status: str
    reference: str | None = None
    raw: dict | None = None


class TransportTimeout(AmbiguousResult):
    """The request may or may not have landed. The caller must treat this as unknown."""


class ProviderNotFound(MoneyNotMoved):
    """The provider says it has no record of that attempt — a real answer to a lookup."""


def to_amount(amount_cents: int, currency: str = "USD") -> str:
    """Minor units in the shape a v2 body wants: '12.34', '150', '1.234'.

    Sending two decimals for a zero-decimal currency is the classic way to get an
    order rejected, so the exponent comes from the catalog, not from here.
    """
    return load_catalog().amount_string(amount_cents, currency)


_STATUS_MAP = {
    "COMPLETED": "completed",
    "CAPTURED": "completed",
    "APPROVED": "pending",      # approved but not captured: not the same as paid
    "CREATED": "pending",
    "DECLINED": "denied",
    "INVALID": "invalid",
    "VOIDED": "not_found",
}


@dataclass
class PayPalConfig:
    client_id: str
    secret: str
    environment: str = "sandbox"
    timeout_sec: float = 8.0
    test_server_url: str | None = None
    """Point the same transport at a local gateway. Never read from the environment."""

    @property
    def base_url(self) -> str:
        if self.test_server_url:
            return self.test_server_url
        return (
            "https://api-m.sandbox.paypal.com"
            if self.environment == "sandbox"
            else "https://api-m.paypal.com"
        )

    @classmethod
    def from_env(cls) -> "PayPalConfig | None":
        client_id = os.environ.get("PAYPAL_CLIENT_ID")
        secret = os.environ.get("PAYPAL_SECRET")
        if not client_id or not secret:
            return None
        return cls(
            client_id=client_id,
            secret=secret,
            environment=os.environ.get("PAYPAL_ENVIRONMENT", "sandbox"),
        )


class PayPalTransport:
    """Orders v2 with PayPal-Request-Id set to our idempotency key.

    The order is always raised in the ledger's own currency. Nothing here
    converts: a spread cost is estimated by the rail catalog, and the provider's
    own rate is what actually moves the money.
    """

    def __init__(self, config: PayPalConfig, opener=urllib.request.urlopen) -> None:
        self.config = config
        self._opener = opener
        self._token: tuple[str, float] | None = None

    def charge(self, idempotency_key: str, amount_cents: int, recipient: str,
               currency: str = "USD") -> ProviderResult:
        order = self._post(
            "/v2/checkout/orders",
            {
                "intent": "CAPTURE",
                "purchase_units": [
                    {
                        "reference_id": recipient or "tabletop-twin",
                        "custom_id": idempotency_key,
                        "amount": {"currency_code": currency, "value": to_amount(amount_cents, currency)},
                    }
                ],
            },
            extra_headers={"PayPal-Request-Id": idempotency_key},
        )
        order_id = order.get("id")
        status = self._map(order.get("status", ""))
        if status == "pending" and order_id:
            captured = self._post(
                f"/v2/checkout/orders/{order_id}/capture",
                {},
                extra_headers={"PayPal-Request-Id": f"{idempotency_key}:capture"},
            )
            status = self._map(captured.get("status", ""))
            return ProviderResult(status=status, reference=order_id, raw=captured)
        return ProviderResult(status=status, reference=order_id, raw=order)

    def lookup(self, idempotency_key: str) -> ProviderResult:
        """Ask what happened to a specific attempt instead of paying again."""
        try:
            found = self._post(
                "/v2/checkout/orders",
                {"idempotency_id": idempotency_key},
                extra_headers={"PayPal-Request-Id": f"{idempotency_key}:lookup"},
            )
        except ProviderNotFound as exc:
            return ProviderResult(status="not_found", raw={"reason": str(exc)})
        orders = found.get("resources") or []
        if not orders:
            return ProviderResult(status="not_found", raw=found)
        order = orders[0]
        return ProviderResult(status=self._map(order.get("status", "")), reference=order.get("id"), raw=order)

    def _map(self, provider_status: str) -> str:
        return _STATUS_MAP.get(str(provider_status).upper(), "unknown")

    def _post(self, path: str, body: dict, extra_headers: dict | None = None) -> dict:
        request = urllib.request.Request(
            self.config.base_url + path,
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._access_token()}",
                **(extra_headers or {}),
            },
        )
        return self._send(request)

    def _access_token(self) -> str:
        if self._token and self._token[1] > time.time():
            return self._token[0]
        basic = base64.b64encode(f"{self.config.client_id}:{self.config.secret}".encode()).decode()
        request = urllib.request.Request(
            self.config.base_url + "/v1/oauth2/token",
            data=b"grant_type=client_credentials",
            method="POST",
            headers={
                "Authorization": f"Basic {basic}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        payload = self._send(request)
        token = payload.get("access_token")
        if not token:
            name = str((payload.get("detail") or {}).get("name", "no access token in the reply"))
            raise MoneyNotMoved(f"the provider refused our credentials ({name})")
        self._token = (token, time.time() + int(payload.get("expires_in", 300)) - 30)
        return self._token[0]

    def _send(self, request: urllib.request.Request) -> dict:
        try:
            with self._opener(request, timeout=self.config.timeout_sec) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            body = error.read()
            try:
                detail = json.loads(body)
            except Exception:
                detail = {"raw": body[:400].decode(errors="replace")}
            # A 5xx or a 408 on a request we already sent is not a "no".
            if error.code >= 500 or error.code == 408:
                raise TransportTimeout(f"HTTP {error.code}") from error
            # Everything else was refused before the provider did the work, so no
            # money can be in flight. Say which rule refused it instead of inventing
            # a status the provider never returned.
            name = str(detail.get("name") or f"HTTP {error.code}")
            if error.code == 404:
                raise ProviderNotFound(f"the provider has no such resource ({name})") from error
            raise MoneyNotMoved(f"the provider refused the call ({name})") from error
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException, OSError) as error:
            # urllib only wraps faults raised while *sending*. A connection the provider
            # closes after taking the request arrives as a bare http.client error, and
            # that is exactly the case that must read as "unknown".
            raise TransportTimeout(str(error)) from error


class SandboxTransport:
    """Deterministic stand-in. `blackout_keys` swallow the reply after the
    provider has taken the money, which is the case a naive client gets wrong."""

    def __init__(self, blackout_keys: set[str] | None = None, decline_recipients: set[str] | None = None) -> None:
        self.blackout_keys = blackout_keys or set()
        self.decline_recipients = decline_recipients or set()
        self.charged: dict[str, ProviderResult] = {}
        self.charge_calls = 0
        self.lookup_calls = 0

    def charge(self, idempotency_key: str, amount_cents: int, recipient: str,
               currency: str = "USD") -> ProviderResult:
        self.charge_calls += 1
        if recipient in self.decline_recipients:
            result = ProviderResult(status="denied", reference=None)
            self.charged[idempotency_key] = result
            return result
        result = ProviderResult(status="completed", reference=f"SAND-{idempotency_key[-8:]}")
        self.charged[idempotency_key] = result
        if idempotency_key in self.blackout_keys:
            raise TransportTimeout("response lost after the provider accepted it")
        return result

    def lookup(self, idempotency_key: str) -> ProviderResult:
        self.lookup_calls += 1
        return self.charged.get(idempotency_key, ProviderResult(status="not_found"))
