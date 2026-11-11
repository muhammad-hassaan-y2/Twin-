"""A live model back end: Meta's Model API (Muse), over the standard library.

Two entry points, because the two jobs here are different:

    call()    one-shot chat completion. Used where a yes/no is needed before a
              payment is let through, so the whole answer has to be in hand.
    stream()  /responses with stream=true, text deltas as they arrive. Used for
              the long red-team plans, where waiting for the end is wasted time.

Defaults are Muse: base url https://api.meta.ai/v1, model muse-spark-1.3.
Anything OpenAI-shaped works by overriding the base url.

    SWARM_LLM_API_KEY / META_MODEL_API_KEY   bearer token
    SWARM_LLM_MODEL   / MUSE_MODEL           model id
    SWARM_LLM_BASE_URL / MUSE_BASE_URL        endpoint root
    SWARM_LLM_RPM     / MUSE_RPM              request-per-minute ceiling

    python -m swarm_oversight.muse --ping          # is it reachable
    python -m swarm_oversight.muse --stream "..."  # watch tokens arrive

Public preview numbers to keep in mind when costing a run: 3000 requests and
4M tokens per minute, $1.25 in / $4.25 out per million tokens for Muse Spark,
$4 / $20 for Muse Wonder.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

BASE_URL = "https://api.meta.ai/v1"
MODEL = "muse-spark-1.3"
# dollars per million tokens, (input, output); matched on the model id prefix
PRICING = {"muse-spark": (1.25, 4.25), "muse-wonder": (4.0, 20.0)}


def cost_usd(model: str, in_tokens: int, out_tokens: int) -> float:
    for prefix, (pin, pout) in PRICING.items():
        if model.startswith(prefix):
            return pin * in_tokens / 1e6 + pout * out_tokens / 1e6
    return 0.0


def _env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.environ.get(n)
        if v:
            return v
    return default


def first_json(text: str) -> dict:
    """The first balanced JSON object in `text` that parses, else {}."""
    text = re.sub(r"```(?:json)?", "", text)
    for start in (m.start() for m in re.finditer(r"\{", text)):
        depth = 0
        for end in range(start, len(text)):
            depth += {"{": 1, "}": -1}.get(text[end], 0)
            if depth == 0:
                try:
                    obj = json.loads(text[start:end + 1])
                except json.JSONDecodeError:
                    break
                return obj if isinstance(obj, dict) else {}
    return {}


@dataclass
class Reply:
    text: str = ""
    in_tokens: int = 0
    out_tokens: int = 0
    latency_s: float = 0.0
    calls: int = 1
    cost_usd: float = 0.0


class Muse:
    """`_post` and `_sse` are the two seams; the offline controls replace them."""

    def __init__(self, model: str = MODEL, base_url: str = BASE_URL,
                 api_key: str = "", rpm: float = 0.0, temperature: float = 0.3,
                 max_tokens: int = 700, trace: Path | None = None,
                 timeout: float = 90.0, attempts: int = 6):
        self.model, self.base, self.key = model, base_url.rstrip("/"), api_key
        self.temperature, self.max_tokens, self.timeout = temperature, max_tokens, timeout
        self.attempts, self.trace = attempts, trace
        self.gap = 60.0 / rpm if rpm else 0.0
        self.last = 0.0
        self.total_cost = 0.0
        self.total_calls = 0

    @classmethod
    def from_env(cls, **kw) -> "Muse":
        return cls(model=_env("SWARM_LLM_MODEL", "MUSE_MODEL", default=MODEL),
                   base_url=_env("SWARM_LLM_BASE_URL", "MUSE_BASE_URL", default=BASE_URL),
                   api_key=_env("SWARM_LLM_API_KEY", "META_MODEL_API_KEY", "MUSE_API_KEY"),
                   rpm=float(_env("SWARM_LLM_RPM", "MUSE_RPM", default="0") or 0), **kw)

    @staticmethod
    def available() -> bool:
        return bool(_env("SWARM_LLM_API_KEY", "META_MODEL_API_KEY", "MUSE_API_KEY"))

    # --- transport -----------------------------------------------------------

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.key:
            h["Authorization"] = f"Bearer {self.key}"
        return h

    def _wait(self) -> None:
        gap_left = self.last + self.gap - time.time()
        if gap_left > 0:
            time.sleep(gap_left)
        self.last = time.time()

    def _post(self, path: str, body: dict) -> dict:
        url = self.base + path
        for attempt in range(self.attempts):
            self._wait()
            req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                         headers=self._headers())
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read())
            except urllib.error.HTTPError as e:
                retryable = e.code in (408, 409, 429, 500, 502, 503, 504)
                if attempt == 0 and e.code == 400 and body.pop("seed", None) is not None:
                    continue  # endpoint that will not accept a seed; ask once without
                if retryable and attempt < self.attempts - 1:
                    time.sleep(min(30.0, 2 ** attempt * 1.5))
                    continue
                raise RuntimeError(f"HTTP {e.code} from {url}: {e.read()[:300]!r}") from None
            except urllib.error.URLError:
                if attempt < self.attempts - 1:
                    time.sleep(min(30.0, 2 ** attempt * 1.5))
                    continue
                raise
        raise RuntimeError(f"unreachable: {url}")

    def _sse(self, path: str, body: dict) -> Iterator[dict]:
        """Yield each `data:` event in a streaming response."""
        self._wait()
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(),
                                     headers={**self._headers(), "Accept": "text/event-stream"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            for line in io_lines(r):
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload and payload != "[DONE]":
                    try:
                        yield json.loads(payload)
                    except json.JSONDecodeError:
                        continue

    # --- calls ---------------------------------------------------------------

    def call(self, user: str, system: str = "", seed: int | None = None,
             tag: str = "") -> Reply:
        msgs = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": user}]
        body = {"model": self.model, "messages": msgs, "temperature": self.temperature,
                "max_tokens": self.max_tokens}
        if seed is not None:
            body["seed"] = seed
        start = time.time()
        resp = self._post("/chat/completions", body)
        text = (((resp.get("choices") or [{}])[0]).get("message") or {}).get("content") or ""
        usage = resp.get("usage") or {}
        out = Reply(text=text, in_tokens=int(usage.get("prompt_tokens") or 0),
                    out_tokens=int(usage.get("completion_tokens") or 0),
                    latency_s=time.time() - start)
        self._record(out, tag, user)
        return out

    def ask_json(self, user: str, system: str = "", seed: int | None = None,
                 tag: str = "") -> tuple[dict, Reply]:
        """Ask for JSON only and take the first object that parses."""
        r = self.call(user, system + "\nReply with a single JSON object, no prose.",
                      seed=seed, tag=tag)
        return first_json(r.text), r

    def stream(self, user: str, system: str = "", max_tokens: int | None = None,
               tag: str = "") -> Iterator[str]:
        """Real-time: text deltas as Muse produces them, via the Responses API."""
        msgs = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": user}]
        body = {"model": self.model, "input": msgs, "stream": True,
                "max_output_tokens": max_tokens or self.max_tokens}
        start, chunks = time.time(), []
        for event in self._sse("/responses", body):
            if event.get("type", "").endswith("output_text.delta"):
                d = event.get("delta") or ""
                if d:
                    chunks.append(d)
                    yield d
        out = Reply(text="".join(chunks), latency_s=time.time() - start)
        self._record(out, tag, user)

    def _record(self, r: Reply, tag: str, user: str) -> None:
        r.cost_usd = cost_usd(self.model, r.in_tokens, r.out_tokens)
        self.total_cost += r.cost_usd
        self.total_calls += r.calls
        if self.trace:
            with self.trace.open("a", encoding="utf-8") as f:
                f.write(json.dumps(dict(tag=tag, model=self.model, prompt=user,
                                        reply=r.text, in_tokens=r.in_tokens,
                                        out_tokens=r.out_tokens, cost_usd=round(r.cost_usd, 6),
                                        latency_s=round(r.latency_s, 3))) + "\n")


def io_lines(response) -> Iterator[str]:
    for raw in response:
        yield raw.decode("utf-8", "replace").rstrip("\r\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt", nargs="?", default="Say OK.")
    ap.add_argument("--ping", action="store_true")
    ap.add_argument("--stream", action="store_true")
    ap.add_argument("--model", default=_env("SWARM_LLM_MODEL", "MUSE_MODEL", default=MODEL))
    args = ap.parse_args()
    if not Muse.available():
        raise SystemExit("no key: set SWARM_LLM_API_KEY (or META_MODEL_API_KEY)")
    muse = Muse.from_env(model=args.model)
    prompt = "Reply with the single word OK." if args.ping else args.prompt
    if args.stream:
        for delta in muse.stream(prompt, tag="ping" if args.ping else "cli"):
            print(delta, end="", flush=True)
        print()
    else:
        print(muse.call(prompt, tag="ping" if args.ping else "cli").text)
    print(f"[{muse.model}] {muse.total_calls} calls, ${muse.total_cost:.6f}")


if __name__ == "__main__":
    main()
