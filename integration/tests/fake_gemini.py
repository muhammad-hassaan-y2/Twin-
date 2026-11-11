"""A miniature Gemini OpenAI-compatible endpoint on localhost, for testing the real client.

The bugs worth finding live on the wire: whether the key travels as a bearer token, whether the
tool catalog arrives in the shape the provider reads, what a model does with the tools, and what
the client does when the endpoint fails. Replies are scripted so every branch is reproducible.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def answer(text: str) -> dict:
    return {
        "model": "gemini-test",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4},
    }


def tool_calls(*calls: tuple[str, dict], call_id: str = "call_1") -> dict:
    return {
        "model": "gemini-test",
        "choices": [{"index": 0, "message": {
            "role": "assistant", "content": "",
            "tool_calls": [
                {"id": f"{call_id}_{index}", "type": "function",
                 "function": {"name": name, "arguments": json.dumps(arguments)}}
                for index, (name, arguments) in enumerate(calls)
            ],
        }}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 6},
    }


class FakeGemini:
    def __init__(self, api_key: str = "test-gemini-key",
                 replies: list[dict] | None = None) -> None:
        self.api_key = api_key
        self.replies = list(replies or ())
        self.bodies: list[dict] = []
        self.raw_bodies: list[str] = []
        self.headers: list[dict] = []
        self.paths: list[str] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> str:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(self))
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

    def respond(self, path: str, headers: dict, raw: bytes) -> tuple[int, dict]:
        """Return (status, payload). Keys in headers are lower-cased."""
        self.paths.append(path)
        self.headers.append(headers)
        self.raw_bodies.append(raw.decode(errors="replace"))
        self.bodies.append(json.loads(raw or b"{}"))
        if headers.get("authorization") != f"Bearer {self.api_key}":
            return 401, {"error": {"code": 401, "message": "API key not valid"}}
        if not self.replies:
            return 500, {"error": {"code": 500, "message": "no scripted reply"}}
        reply = self.replies.pop(0)
        if callable(reply):
            reply = reply(self.bodies[-1])
        return 200, reply


def _make_handler(app: FakeGemini):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802 - required by BaseHTTPRequestHandler
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            headers = {k.lower(): v for k, v in self.headers.items()}
            status, payload = app.respond(self.path, headers, raw)
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    return Handler
