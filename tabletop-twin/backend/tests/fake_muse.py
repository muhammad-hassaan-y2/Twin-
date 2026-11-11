"""A miniature Meta Model API, served on localhost, so the Muse route is testable with no key.

It answers on a socket rather than as a stub because the bugs worth finding live in
the transport: the ``Authorization: Bearer`` header, the two endpoint shapes, a 401
that must never be asked twice, a 429 that names the wait it wants, a stream whose
sentences arrive one at a time, and a reply that turns out not to be JSON at all.
"""

from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "muse-spark-1.3"
CHAT_PATH = "/v1/chat/completions"
RESPONSES_PATH = "/v1/responses"


def sse(events: list[tuple[str, dict]]) -> bytes:
    """Encode (event, payload) pairs the way an ``text/event-stream`` server does."""
    return "".join(f"event: {name}\ndata: {json.dumps(payload)}\n\n" for name, payload in events).encode()


def read_sse(lines) -> list[tuple[str, dict]]:
    """The inverse: collect the pairs back off a stream this client is being handed."""
    out: list[tuple[str, dict]] = []
    name = ""
    for line in lines:
        if line.startswith("event:"):
            name = line[len("event:"):].strip()
        elif line.startswith("data:"):
            out.append((name, json.loads(line[len("data:"):].strip())))
    return out


class Reply:
    """One scripted answer: a status, a body, optional headers, or no answer at all."""

    def __init__(self, status: int = 200, payload: dict | None = None, text: str | None = None,
                 headers: dict | None = None, drop: bool = False,
                 events: list[tuple[str, dict]] | None = None) -> None:
        self.status = status
        self.payload = payload
        self.text = text
        self.headers = headers or {}
        self.drop = drop
        self.events = events

    @property
    def streaming(self) -> bool:
        return self.events is not None

    @property
    def content_type(self) -> str:
        if self.events is not None:
            return "text/event-stream"
        return "application/json" if self.text is None else "text/html"

    @property
    def body(self) -> bytes:
        if self.events is not None:
            return sse(self.events)
        if self.text is not None:
            return self.text.encode()
        return json.dumps(self.payload if self.payload is not None else {}).encode()


def _chat(*, content: str = "", tool_calls: list | None = None) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"id": "gen-1", "model": MODEL, "choices": [{"index": 0, "message": message, "finish_reason": "stop"}]}


def _tool_call(name: str, args: dict) -> dict:
    return {"id": f"call-{name}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


def _function_call(name: str, args: dict, call_id: str = "") -> dict:
    """A responses-shaped call: flat, with ``name`` and ``arguments`` beside the type."""
    return {"type": "function_call", "call_id": call_id or f"call-{name}",
            "name": name, "arguments": json.dumps(args)}


def _responses(*, text: str = "", calls: list | None = None) -> dict:
    output: list[dict] = []
    if calls:
        output.extend(calls)
    if text:
        output.append({"type": "message", "role": "assistant",
                       "content": [{"type": "output_text", "text": text}]})
    return {"id": "resp-1", "model": MODEL, "status": "completed", "output": output}


def _error(message: str) -> dict:
    return {"error": {"message": message, "type": "invalid_request_error"}}


class FakeMuse:
    def __init__(self, key: str = "muse-key", model: str = MODEL) -> None:
        self.key = key
        self.model = model
        self.replies: list[Reply] = []
        self.paths: list[str] = []
        self.bodies: list[dict] = []
        self.headers: list[dict] = []
        self.rejected: list[str] = []
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ serving

    def start(self) -> str:
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(self))
        # A short poll interval so teardown notices promptly: two dozen fixtures' worth
        # of the default half-second is longer than every assertion in this file.
        self._thread = threading.Thread(target=self._server.serve_forever,
                                        kwargs={"poll_interval": 0.05}, daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    @property
    def url(self) -> str:
        """A base URL in the shape ``ModelConfig`` expects: it appends the endpoint path."""
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}/v1"

    @property
    def host(self) -> str:
        assert self._server is not None
        return f"127.0.0.1:{self._server.server_address[1]}"

    @property
    def calls(self) -> int:
        return len(self.paths)

    @property
    def last_body(self) -> dict:
        return self.bodies[-1]

    @property
    def tools_asked_for(self) -> set[str]:
        asked = self.last_body.get("tools") or []
        return {t.get("name") or t.get("function", {}).get("name") for t in asked}

    # ---------------------------------------------------------------- scripting

    def tool(self, name: str, args: dict) -> None:
        """A chat/completions answer carrying one tool call."""
        self.replies.append(Reply(payload=_chat(tool_calls=[_tool_call(name, args)])))

    def responses_tool(self, *calls: tuple[str, dict]) -> None:
        """A /v1/responses answer. Several calls in one reply is the point of the shape."""
        self.replies.append(Reply(payload=_responses(
            calls=[_function_call(name, args, call_id=f"call-{index}") for index, (name, args) in enumerate(calls)])))

    def narration(self, said: str) -> None:
        self.replies.append(Reply(payload=_chat(content=said)))

    def responses_narration(self, said: str) -> None:
        self.replies.append(Reply(payload=_responses(text=said)))

    def stream(self, *pieces: str, final: str | None = None) -> None:
        """A /v1/responses answer that arrives as a stream, one event per piece.

        ``final`` overrides what ``response.completed`` carries, which is how a test
        can make the finished sentence differ from the fragments.
        """
        events: list[tuple[str, dict]] = [("response.created", {"id": "resp-1", "status": "in_progress"})]
        for piece in pieces:
            events.append(("response.output_text.delta", {"item_id": "msg-1", "delta": piece}))
        events.append(("response.completed", _responses(text=final if final is not None else "".join(pieces))))
        self.replies.append(Reply(events=events))

    def refuse(self, status: int = 429, *, detail: str = "slow down", retry_after: str | None = None,
               times: int = 1) -> None:
        headers = {"Retry-After": retry_after} if retry_after is not None else {}
        self.replies.extend(Reply(status, payload=_error(detail), headers=headers) for _ in range(times))

    def gibberish(self, status: int = 200, text: str = "<html>502 Bad Gateway</html>") -> None:
        self.replies.append(Reply(status, text=text))

    def silence(self) -> None:
        """Do the work, then hang up: the reply never arrives."""
        self.replies.append(Reply(drop=True))

    # ---------------------------------------------------------------- endpoints

    def respond(self, method: str, path: str, headers: dict, body: bytes) -> Reply:
        self.paths.append(f"{method} {path}")
        if method != "POST":
            return Reply(405, payload=_error("this endpoint only takes POST"))
        if path not in (CHAT_PATH, RESPONSES_PATH):
            return Reply(404, payload=_error(f"no such path: {path}"))
        bearer = headers.get("authorization", "")
        if bearer != f"Bearer {self.key}":
            self.rejected.append(bearer)
            return Reply(401, payload=_error("Invalid API key provided"))
        parsed = json.loads(body or b"{}")
        self.bodies.append(parsed)
        self.headers.append(headers)
        if parsed.get("model") != self.model:
            return Reply(404, payload=_error(f"Model '{parsed.get('model')}' is not available"))
        if path == RESPONSES_PATH and not str(parsed.get("input") or ""):
            return Reply(400, payload=_error("input is required"))
        if not self.replies:
            return Reply(500, payload=_error("FakeMuse has nothing scripted for this call"))
        reply = self.replies[0]
        if path == RESPONSES_PATH:
            if parsed.get("stream") and not reply.streaming:
                return Reply(500, payload=_error("FakeMuse was asked to stream but only has a one-shot answer scripted"))
            if not parsed.get("stream") and reply.streaming:
                return Reply(500, payload=_error("FakeMuse has a stream scripted for a one-shot call"))
        # A scripted answer only answers the shape it was written for, so a test that
        # believes it exercised /v1/responses cannot quietly be shown chat JSON.
        # A reply with no JSON in it at all — a hung-up socket, a gateway's HTML error
        # page — is not a shape question, so it is delivered as scripted.
        if reply.payload is not None and reply.status < 400 and not reply.streaming:
            want = "output" if path == RESPONSES_PATH else "choices"
            if want not in reply.payload:
                return Reply(400, payload=_error(
                    f"this scripted answer is not {path}-shaped (it has no '{want}')"
                ))
        self.replies.pop(0)
        return reply


def _make_handler(app: FakeMuse):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):  # noqa: N802 - required by BaseHTTPRequestHandler
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            headers = {k.lower(): v for k, v in self.headers.items()}
            reply = app.respond(self.command, self.path, headers, body)
            if reply.drop:
                # The turn was generated and the answer is gone. A real gateway does
                # this on a timeout, and the client must not read it as a fresh ask.
                self.close_connection = True
                try:
                    self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                return
            raw = reply.body
            self.send_response(reply.status)
            self.send_header("Content-Type", reply.content_type)
            for key, value in reply.headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *args):
            pass

    return Handler
