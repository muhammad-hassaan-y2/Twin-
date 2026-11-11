"""Gemini for the parts of billing where a model is useful and cannot move money.

Two surfaces, both optional:

* invoice copy - the model rewrites the client-facing line, and `invoice_line` drops the reply
  unless every figure in it is already on the invoice;
* an assistant - the model may call the billing tools, so a person can ask "what is outstanding?"
  or "open the Acme invoice". Amounts come from the firm's review, never from the model, and a
  capture needs a named human approver that the caller supplies, not the model.

Credentials come from `GEMINI_API_KEY` only (never a file, never a default). The endpoint is the
Google AI Studio OpenAI-compatible surface, and `test_server_url` points the same client at a
localhost server for tests; it is never read from the environment.
"""
from __future__ import annotations

import http.client
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from .commerce import Writer
from .commerce_tools import CommerceTools

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
MODEL = "gemini-3.5-flash-lite"

SYSTEM = (
    "You are the billing assistant for a professional-services firm. Use the tools to read the "
    "book and act on it. Amounts are set by the firm's review and cannot be changed by you: "
    "never invent, round or state a figure that a tool did not return. You cannot approve a "
    "capture; only a human approver supplied by the operator can, and the tool refuses yours. "
    "If a tool refuses, say what it refused and why. Be brief."
)


class ModelUnavailable(RuntimeError):
    """The model endpoint could not answer. This is a service fault, not a billing outcome."""


class AssistantUnavailable(RuntimeError):
    """No model is configured, so there is no assistant to ask."""


@dataclass(frozen=True)
class GeminiConfig:
    api_key: str = field(repr=False)  # a key must not travel into a log through a repr
    model: str = MODEL
    timeout_sec: float = 30.0
    temperature: float = 0.0
    test_server_url: str | None = None
    """Point the same client at a local gateway. Never read from the environment."""

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValueError("a Gemini key must be non-empty when one is configured")
        if not self.model.strip():
            raise ValueError("a Gemini model id must be named")
        if self.timeout_sec <= 0:
            raise ValueError("the model timeout must be positive")

    @property
    def base_url(self) -> str:
        return self.test_server_url or BASE_URL

    @property
    def endpoint(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"

    @classmethod
    def from_env(cls) -> "GeminiConfig | None":
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            return None
        return cls(api_key=key,
                   model=os.environ.get("GEMINI_MODEL", MODEL).strip() or MODEL,
                   timeout_sec=float(os.environ.get("GEMINI_TIMEOUT_SEC", "30") or 30))


@dataclass(frozen=True)
class Reply:
    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    in_tokens: int = 0
    out_tokens: int = 0
    model: str = ""


class GeminiClient:
    """Chat completions over the OpenAI-compatible surface, with tools when asked."""

    def __init__(self, config: GeminiConfig, opener=urllib.request.urlopen) -> None:
        self.config = config
        self._opener = opener

    @property
    def model(self) -> str:
        return self.config.model

    def chat(self, messages: list[dict[str, Any]], *,
             tools: list[dict[str, Any]] | None = None) -> Reply:
        body: dict[str, Any] = {"model": self.config.model, "messages": messages,
                                "temperature": self.config.temperature}
        if tools:
            body["tools"] = tools
        request = urllib.request.Request(
            self.config.endpoint,
            data=json.dumps(body).encode(),
            method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.config.api_key}"},
        )
        try:
            with self._opener(request, timeout=self.config.timeout_sec) as response:
                payload = json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            raise ModelUnavailable(f"the model endpoint answered HTTP {error.code}") from error
        except (urllib.error.URLError, TimeoutError, http.client.HTTPException, OSError) as error:
            raise ModelUnavailable(f"the model endpoint could not be reached ({error})") from error
        choices = payload.get("choices") or []
        if not choices:
            raise ModelUnavailable("the model endpoint returned no choices")
        message = choices[0].get("message") or {}
        usage = payload.get("usage") or {}
        return Reply(
            text=str(message.get("content") or "").strip(),
            tool_calls=list(message.get("tool_calls") or ()),
            in_tokens=int(usage.get("prompt_tokens") or 0),
            out_tokens=int(usage.get("completion_tokens") or 0),
            model=str(payload.get("model") or self.config.model),
        )

    def writer(self) -> Writer:
        """The invoice-copy writer `commerce.invoice_line` expects."""

        def write(prompt: str, _facts: dict[str, Any]) -> str:
            return self.chat([{"role": "user", "content": prompt}]).text

        return write


def function_schemas(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The billing catalog in the shape an OpenAI-compatible tools field wants."""
    return [{"type": "function",
             "function": {"name": tool["name"], "description": tool["description"],
                          "parameters": tool["input_schema"]}}
            for tool in catalog]


def _parse_call(call: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    function = call.get("function") or {}
    name = str(function.get("name") or "")
    raw = function.get("arguments")
    if isinstance(raw, dict):
        return name, raw
    try:
        parsed = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return name, {}
    return name, parsed if isinstance(parsed, dict) else {}


@dataclass
class Assistant:
    """A bounded tool loop. The dispatcher is the authority; the model only asks."""

    client: GeminiClient
    tools: CommerceTools
    max_steps: int = 6

    def ask(self, question: str, *, approved_by: str | None = None) -> dict[str, Any]:
        if not isinstance(question, str) or not question.strip():
            raise ValueError("an assistant needs a question")
        approver = (approved_by or "").strip()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": question.strip()},
        ]
        tools = function_schemas(self.tools.catalog())
        steps: list[dict[str, Any]] = []
        model = self.client.model
        for _ in range(self.max_steps):
            reply = self.client.chat(messages, tools=tools)
            model = reply.model or model
            if not reply.tool_calls:
                return {"answer": reply.text, "steps": steps, "model": model,
                        "in_tokens": reply.in_tokens, "out_tokens": reply.out_tokens}
            messages.append({"role": "assistant", "content": reply.text,
                             "tool_calls": reply.tool_calls})
            for index, call in enumerate(reply.tool_calls):
                name, arguments = _parse_call(call)
                result, allowed = self._dispatch(name, arguments, approver)
                steps.append({"tool": name, "arguments": arguments,
                              "allowed": allowed, "result": result})
                messages.append({"role": "tool",
                                 "tool_call_id": str(call.get("id") or f"call_{index}"),
                                 "content": json.dumps(result)})
        return {"answer": "", "steps": steps, "model": model,
                "stopped": f"the model used all {self.max_steps} steps without answering"}

    def _dispatch(self, name: str, arguments: dict[str, Any],
                  approver: str) -> tuple[dict[str, Any], bool]:
        if name == "billing_capture":
            # The operator's approver wins over anything the model wrote into the call.
            if not approver:
                return ({"ok": False,
                         "refused": ("a named person must approve the capture; an assistant "
                                     "cannot approve its own spending")}, False)
            arguments = dict(arguments, approved_by=approver)
        return self.tools.call(name, arguments), True
