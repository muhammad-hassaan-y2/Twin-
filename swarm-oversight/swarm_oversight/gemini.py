"""A live Gemini back end, separate from the Muse baseline.

Same wire protocol (OpenAI-compatible chat completions), different endpoint,
different env vars, so a Gemini run never touches the Muse configuration:

    GEMINI_API_KEY   bearer token (required)
    GEMINI_MODEL     model id, default gemini-3.5-flash-lite
    GEMINI_RPM       optional request-per-minute ceiling

The endpoint rejects the `seed` field, so it is never sent; episodes are made
reproducible by temperature 0 and by keeping every prompt and reply.

Billing tier of a key cannot be verified from the wire, so this client records
tokens and calls and reports no dollar figure. Tables built from it are labelled
accordingly.

    python -m swarm_oversight.gemini --ping
"""
from __future__ import annotations

import argparse
import os

from .muse import Muse, Reply

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
MODEL = "gemini-3.5-flash-lite"


class Gemini(Muse):
    family = "gemini"

    def __init__(self, model: str = MODEL, api_key: str = "", rpm: float = 0.0,
                 temperature: float = 0.0, **kw):
        super().__init__(model=model, base_url=BASE_URL, api_key=api_key,
                         rpm=rpm, temperature=temperature, **kw)

    @classmethod
    def from_env(cls, **kw) -> "Gemini":
        key = os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise SystemExit("set GEMINI_API_KEY")
        return cls(model=os.environ.get("GEMINI_MODEL", MODEL), api_key=key,
                   rpm=float(os.environ.get("GEMINI_RPM", "0") or 0), **kw)

    def call(self, user: str, system: str = "", seed: int | None = None,
             tag: str = "") -> Reply:
        return super().call(user, system=system, seed=None, tag=tag)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ping", action="store_true")
    args = ap.parse_args()
    client = Gemini.from_env()
    r = client.call("Reply with the single word OK.", tag="ping")
    print(r.text)
    print(f"[{client.model}] {r.in_tokens} in / {r.out_tokens} out tokens, "
          f"{r.latency_s:.1f}s (no dollar figure: key billing tier unverified)")


if __name__ == "__main__":
    main()