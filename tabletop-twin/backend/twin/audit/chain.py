"""The client for the chain the agent agreements live on.

Two failures look alike here and must never be confused. `ChainDown` means the sidecar did
not answer at all: nothing was recorded, and the firm is running on its rules alone. A
refusal means the chain answered perfectly and said no: the transaction happened, the gas
was spent, and the reason is in the receipt. The first is this process's problem. The second
is an answer an agent has to live with.

A write that times out is neither. It may have landed while the socket was open, so this
raises rather than retrying, and the caller finds out by reading the chain back - the same
rule the payment machine runs on, for the same reason.

There is a fourth case, and it raises too. A transaction the EVM would not accept at all -
one signed by an account this chain never funded - is not a contract refusing an offer,
because no contract was reached and nothing was journalled. Only a write that came back with
a receipt has a `Refusal`.
"""

from __future__ import annotations

import contextlib
import http.client
import json
import os
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

DEFAULT_URL = "http://127.0.0.1:8791"
REPO_ROOT = Path(__file__).resolve().parents[3]
SERVE = REPO_ROOT / "chain" / "serve.mjs"
ROSTER = REPO_ROOT / "chain" / "roster.json"


class ChainError(RuntimeError):
    pass


class ChainDown(ChainError):
    """The sidecar is not answering. No agreement was created or changed."""


class ChainUnreachable(ChainError):
    """A read timed out. The chain is probably fine; this call simply does not know."""


class AmbiguousWrite(ChainError):
    """A write timed out after it may have landed. Read the chain; do not resend."""


@dataclass(frozen=True)
class Refusal:
    """What the bytecode said when it said no."""

    name: str
    args: tuple[Any, ...] = ()
    selector: str = ""

    def __str__(self) -> str:
        return f"{self.name}({', '.join(str(a) for a in self.args)})" if self.args else self.name


@dataclass(frozen=True)
class Receipt:
    """One transaction and what it cost. A refused write still has a receipt."""

    ok: bool
    op: str
    status: int = 0
    id: str | None = None
    gas_used: int = 0
    wei_spent: int = 0
    tick: int = 0
    # The position this write's events took in the chain's log. A refused write burns one
    # too: the transaction ran, and the cursor counts transactions, not successes.
    seq: int = 0
    events: tuple[dict, ...] = ()
    refusal: Refusal | None = None
    state_root: str = ""
    terms_hash: str = ""
    evidence_hash: str = ""

    @property
    def event_names(self) -> list[str]:
        return [event.get("name", "") for event in self.events]


@dataclass
class Chain:
    """Reads and writes against the sidecar. Stateless apart from the URL it was given."""

    url: str = ""
    token: str = ""
    timeout_sec: float = 20.0
    opener: Callable[..., Any] = urllib.request.urlopen

    def __post_init__(self) -> None:
        # Both are read here rather than at import so a test that clears the environment
        # really does get a client that points nowhere, instead of one that remembered.
        self.url = self.url or os.environ.get("TWIN_CHAIN_URL", "http://127.0.0.1:8791")
        self.token = self.token or os.environ.get("TWIN_CHAIN_TOKEN", "")

    # ------------------------------------------------------------------ transport

    def _request(self, method: str, path: str, body: dict | None = None) -> dict:
        headers = {"content-type": "application/json"}
        if self.token:
            headers["x-twin-chain-token"] = self.token
        request = urllib.request.Request(
            self.url + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
            method=method,
        )
        try:
            with self.opener(request, timeout=self.timeout_sec) as response:
                return json.loads(response.read().decode() or "{}")
        except urllib.error.HTTPError as error:
            # 4xx from the sidecar is a well-formed answer about a bad request, not a
            # dead chain: the reason is in the body and the caller needs to see it.
            try:
                payload = json.loads(error.read().decode() or "{}")
            except Exception:  # noqa: BLE001 - an HTML error page means the process is wrong
                raise ChainDown(f"{self.url} answered {error.code} without a body") from error
            if error.code == 404 and "no route" in str(payload.get("error", "")):
                raise ChainError(payload["error"]) from error
            raise ChainError(f"{method} {path}: {payload.get('error', error.code)}") from error
        except socket.timeout as error:
            raise ChainUnreachable(f"{method} {path} timed out after {self.timeout_sec}s") from error
        # Order matters: a reset mid-response is both an HTTPException and an OSError, and it
        # belongs with the timeouts, because the request may already have been executed. A
        # refused connection means nothing was ever sent, which is a different answer.
        except http.client.HTTPException as error:
            raise ChainUnreachable(f"{method} {path} broke: {error}") from error
        except OSError as error:
            raise ChainDown(f"{self.url} is not answering: {error}") from error

    def get(self, path: str) -> dict:
        return self._request("GET", path)

    def write(self, op: str, **payload: Any) -> Receipt:
        body = {"op": op, **{k: v for k, v in payload.items() if v is not None}}
        try:
            answer = self._request("POST", "", body)
        except ChainUnreachable as error:
            raise AmbiguousWrite(f"{op} may have landed: {error}") from error
        if "error" in answer and "ok" not in answer:
            raise ChainError(f"{op}: {answer['error']}")
        refusal = answer.get("error")
        return Receipt(
            ok=bool(answer.get("ok")),
            op=op,
            status=int(answer.get("status") or 0),
            id=answer.get("id"),
            gas_used=int(answer.get("gas_used") or 0),
            wei_spent=int(answer.get("wei_spent") or 0),
            tick=int(answer.get("tick") or 0),
            seq=int(answer.get("seq") or 0),
            events=tuple(answer.get("events") or ()),
            refusal=Refusal(refusal["name"], tuple(refusal.get("args") or ()), refusal.get("selector", ""))
            if refusal
            else None,
            state_root=str(answer.get("state_root") or ""),
            terms_hash=str(answer.get("terms_hash") or ""),
            evidence_hash=str(answer.get("evidence_hash") or ""),
        )

    # -------------------------------------------------------------------- reads

    def alive(self) -> bool:
        try:
            return "registry" in self.get("/status")
        except ChainError:
            return False

    def status(self) -> dict:
        return self.get("/status")

    def roles(self) -> dict:
        return self.get("/roles")

    def agreements(self) -> list[dict]:
        return list(self.get("/agreements").get("agreements") or [])

    def agreement(self, agreement_id: str) -> dict:
        return self.get(f"/agreement?id={agreement_id}")

    def inbox(self, role: str, after: int = 0) -> dict:
        return self.get(f"/inbox?role={role}&after={int(after)}")

    # -------------------------------------------------------------------- setup

    def register_roles(self, missing_only: bool = True) -> list[Receipt]:
        """Put every roster role on the chain, signed by the firm key.

        Idempotent by intent: an agent that is already registered is skipped, because the
        contract refuses a duplicate and a startup that burns gas on a refusal every time
        it runs teaches nobody anything.
        """
        roster = json.loads(Path(ROSTER).read_text(encoding="utf-8"))
        on_chain: set[str] = set()
        if missing_only:
            on_chain = {agent["role"] for agent in self.roles().get("agents") or [] if agent.get("known")}
        receipts = []
        for agent in roster.get("agents") or []:
            if agent["role"] in on_chain:
                continue
            receipts.append(self.write("register", **agent))
        return receipts


@contextlib.contextmanager
def spawn_sidecar(
    journal: str | Path | None = None,
    port: int | None = None,
    cap_source: str | Path | None = None,
    wait_sec: float = 90.0,
    extra_env: dict | None = None,
):
    """Start the sidecar on a port of its own, wait for it, and take it down again.

    A test that needs a chain should not have to be told to open one first, and a
    developer who forgets to should not be looking at a wall of `ChainDown`. The journal
    argument is what keeps the two chains apart: a test points it somewhere temporary so
    the real agreement history is never the one under test.
    """
    node = shutil.which("node") or os.environ.get("TWIN_NODE", "")
    if not node:
        raise ChainDown("node is not on PATH, so the chain sidecar cannot start")
    if not SERVE.exists():
        raise ChainDown(f"no sidecar at {SERVE}")
    port = port or _free_port()
    env = {**os.environ, "TWIN_CHAIN_PORT": str(port)}
    if journal:
        env["TWIN_CHAIN_JOURNAL"] = str(journal)
    if cap_source:
        env["TWIN_PRIORS"] = str(cap_source)
    env.update(extra_env or {})
    log = subprocess.PIPE
    process = subprocess.Popen(  # noqa: S603 - the command is this repository's own script
        [node, str(SERVE)], cwd=str(SERVE.parent), env=env, stdout=log, stderr=subprocess.STDOUT, text=True
    )
    chain = Chain(url=f"http://127.0.0.1:{port}", timeout_sec=30.0)
    deadline = time.time() + wait_sec
    try:
        while time.time() < deadline:
            if process.poll() is not None:
                raise ChainDown(f"sidecar exited with {process.returncode}: {(process.stdout.read() if process.stdout else '')[-500:]}")
            with contextlib.suppress(ChainError):
                if chain.alive():
                    break
            time.sleep(0.4)
        else:
            process.kill()
            raise ChainDown(f"sidecar did not answer on {port} within {wait_sec}s")
        yield chain
    finally:
        if process.poll() is None:
            process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=10)
        if process.poll() is None:
            process.kill()


def _free_port() -> int:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def role_names() -> list[str]:
    return [agent["role"] for agent in json.loads(Path(ROSTER).read_text(encoding="utf-8")).get("agents") or []]


def roster() -> dict:
    return json.loads(Path(ROSTER).read_text(encoding="utf-8"))


def describe(receipts: Iterable[Receipt]) -> list[dict]:
    """Receipts as plain dicts, for the log and for a panel."""
    return [
        {
            "op": r.op,
            "ok": r.ok,
            "id": r.id,
            "gas_used": r.gas_used,
            "tick": r.tick,
            "refused": str(r.refusal) if r.refusal else None,
            "events": list(r.event_names),
        }
        for r in receipts
    ]
