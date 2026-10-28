"""A miniature PayPal v2 orders API, served on localhost, for testing the real transport.

It is HTTP on a socket rather than a stub because the bugs worth finding live in
the transport itself: Basic auth on the token call, the created-then-captured
two-step, ``PayPal-Request-Id`` replay, and what happens when a reply never
arrives after the money moved.
"""

from __future__ import annotations

import base64
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class FakePayPal:
    def __init__(self, client_id: str = "test-client", secret: str = "test-secret") -> None:
        self.client_id = client_id
        self.secret = secret
        self.orders: dict[str, dict] = {}
        self.by_request_id: dict[str, str] = {}
        self.token_calls = 0
        self.create_calls = 0
        self.capture_calls = 0
        self.replays = 0
        self.path_calls: list[str] = []
        self.timeout_keys: set[str] = set()  # 500 after the order exists
        self.drop_keys: set[str] = set()  # reply lost in the wire after the order exists
        self.drop_capture_keys: set[str] = set()  # capture happens, the answer never arrives
        self.decline_recipients: set[str] = set()
        self._counter = 0
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ serving

    def start(self) -> str:
        handler = _make_handler(self)
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    @property
    def url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}"

    @property
    def captured_cents(self) -> int:
        return sum(o["_cents"] for o in self.orders.values() if o["status"] == "COMPLETED")

    def respond(self, method: str, path: str, headers: dict, body: bytes) -> tuple[int, dict, bool]:
        """Return (status, json_body, drop_the_reply). Keys in headers are lower-cased."""
        self.path_calls.append(f"{method} {path}")
        if path == "/v1/oauth2/token":
            return self._token(headers)
        if not self._bearer_ok(headers):
            return 401, {"name": "INVALID_TOKEN", "message": "auth token not recognised"}, False
        if path == "/v2/checkout/orders" and method == "POST":
            return self._orders(headers, body)
        if path.endswith("/capture") and path.startswith("/v2/checkout/orders/"):
            return self._capture(headers, path)
        return 404, {"name": "RESOURCE_NOT_FOUND"}, False

    # ---------------------------------------------------------------- endpoints

    def _token(self, headers: dict) -> tuple[int, dict, bool]:
        self.token_calls += 1
        want = "Basic " + base64.b64encode(f"{self.client_id}:{self.secret}".encode()).decode()
        if headers.get("authorization") != want:
            return 401, {"name": "INVALID_CLIENT", "message": "the credentials do not match"}, False
        return 200, {"access_token": "A21A.mock.token", "expires_in": 300, "token_type": "BEARER"}, False

    def _orders(self, headers: dict, body: bytes) -> tuple[int, dict, bool]:
        request_id = headers.get("paypal-request-id", "")
        payload = json.loads(body or b"{}")

        # The reconcile call: same path, but it asks about a past attempt.
        if "idempotency_id" in payload:
            key = payload["idempotency_id"]
            order_id = self.by_request_id.get(key)
            if order_id is None:
                return 200, {"resources": []}, False
            return 200, {"resources": [_public(self.orders[order_id])]}, False

        if request_id in self.by_request_id:
            self.replays += 1
            return 201, _public(self.orders[self.by_request_id[request_id]]), False

        unit = payload["purchase_units"][0]
        cents = round(float(unit["amount"]["value"]) * 100)
        recipient = unit["reference_id"]
        if recipient in self.decline_recipients:
            return 422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "PAYMENT_DECLINED"}]}, False

        self.create_calls += 1
        self._counter += 1
        order_id = f"MOCK{self._counter:06d}"
        order = {"id": order_id, "status": "CREATED", "custom_id": unit.get("custom_id", ""),
                 "recipient": recipient, "_cents": cents, "captures": []}
        self.orders[order_id] = order
        self.by_request_id[request_id] = order_id

        if request_id in self.drop_keys:
            return 201, _public(order), True  # the order exists; the answer is gone
        if request_id in self.timeout_keys:
            return 500, {"name": "INTERNAL_SERVER_ERROR"}, False
        return 201, _public(order), False

    def _capture(self, headers: dict, path: str) -> tuple[int, dict, bool]:
        order_id = path.split("/")[4]
        order = self.orders.get(order_id)
        if order is None:
            return 404, {"name": "ORDER_NOT_FOUND"}, False
        self.capture_calls += 1
        if order["status"] == "COMPLETED":
            return 409, {"name": "ORDER_ALREADY_CAPTURED"}, False
        order["status"] = "COMPLETED"
        order["captures"] = [{"id": f"CAP{order_id}", "status": "COMPLETED",
                              "amount": {"currency_code": "USD", "value": f"{order['_cents'] // 100}.{order['_cents'] % 100:02d}"}}]
        if headers.get("paypal-request-id", "") in {f"{k}:capture" for k in self.drop_capture_keys}:
            return 201, _public(order), True
        return 201, _public(order), False

    def _bearer_ok(self, headers: dict) -> bool:
        return headers.get("authorization", "").startswith("Bearer ")


def _public(order: dict) -> dict:
    return {k: v for k, v in order.items() if not k.startswith("_")}


def _make_handler(app: FakePayPal):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802 - required by BaseHTTPRequestHandler
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            headers = {k.lower(): v for k, v in self.headers.items()}
            status, payload, drop = app.respond(self.command, self.path, headers, body)
            if drop:
                # The work is done and the reply is gone: hang up mid-connection so the
                # client sees a closed socket instead of an answer, exactly as a real
                # network fault would.
                self.close_connection = True
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                return
            raw = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    return Handler
