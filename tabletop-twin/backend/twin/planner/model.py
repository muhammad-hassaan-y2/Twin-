"""Muse Spark / Claude through an OpenAI-compatible endpoint.

Meta's Model API advertises drop-in compatibility with the OpenAI SDK, so one
adapter covers Muse Spark, Claude, or any local server that speaks the same
shape. Each endpoint is configured on its own and reported under its own name:
a route that says ``muse:...`` was answered by Meta's Model API, never by
whatever happened to be in the environment. There is no default base URL and no
default key: without both, the planner degrades to the rule planner and says so.

The guard that matters is `assert_numbers_are_given`. A model that invents a
plausible dollar figure is worse than a model that says nothing, so narration
is checked against the numbers the forecast actually produced.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .rules import RulePlanner
from .tools import REGISTRY, ToolCall, ToolError, parse_calls

MUSE = "muse"
GENERIC = "openai-compatible"


@dataclass
class ModelConfig:
    base_url: str
    api_key: str
    model: str
    provider: str = GENERIC
    timeout_sec: float = 20.0
    max_output_tokens: int = 512

    @property
    def route(self) -> str:
        return f"{self.provider}:{self.model}"

    def reply(self, body: dict, opener=urllib.request.urlopen) -> dict:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        with opener(request, timeout=self.timeout_sec) as response:
            return json.loads(response.read())


def _from_names(base_vars: tuple[str, ...], key_vars: tuple[str, ...], model_vars: tuple[str, ...], provider: str) -> ModelConfig | None:
    base = next((os.environ[v] for v in base_vars if os.environ.get(v)), "")
    key = next((os.environ[v] for v in key_vars if os.environ.get(v)), "")
    model = next((os.environ[v] for v in model_vars if os.environ.get(v)), "")
    if not base or not key or not model:
        return None
    return ModelConfig(base_url=base.rstrip("/"), api_key=key, model=model, provider=provider)


def providers_from_env() -> list[ModelConfig]:
    """Every endpoint this machine is configured for, most preferred first.

    Muse wins when both are present, and the fallback to rules is reached only
    after the endpoints actually tried have failed — so a route is a report, not
    a guess.
    """
    out = [
        _from_names(("META_MODEL_BASE_URL",), ("META_MODEL_API_KEY",), ("META_MODEL_NAME",), MUSE),
        _from_names(("LLM_BASE_URL", "OPENAI_COMPAT_BASE_URL"), ("LLM_API_KEY", "OPENAI_COMPAT_API_KEY"),
                    ("LLM_MODEL", "OPENAI_COMPAT_MODEL"), GENERIC),
    ]
    return [config for config in out if config is not None]


def providers_configured() -> list[str]:
    """Names only. An endpoint is reported as configured without repeating its key."""
    return [config.provider for config in providers_from_env()]


class NumberFabrication(Exception):
    pass


class ModelPlanner:
    """Asks a model which tool to run. Never lets it do arithmetic."""

    name = "model"

    def __init__(self, config: ModelConfig, opener=urllib.request.urlopen, fallback: RulePlanner | None = None) -> None:
        self.config = config
        self._opener = opener
        self.fallback = fallback or RulePlanner()
        self.last_route = ""
        self.voice_prompt = ""

    @property
    def provider(self) -> str:
        return self.config.provider

    @classmethod
    def from_env(cls) -> "ModelPlanner | None":
        configs = providers_from_env()
        return cls(configs[0]) if configs else None

    def plan(self, intent: str, context: dict) -> list[ToolCall]:
        messages = [
            {"role": "system", "content": self._system_prompt(context)},
            {"role": "user", "content": intent},
        ]
        try:
            payload = self._post(
                {
                    "model": self.config.model,
                    "messages": messages,
                    "tools": [t.to_openai() for t in REGISTRY.values()],
                    "tool_choice": "auto",
                    "max_tokens": self.config.max_output_tokens,
                }
            )
            choice = payload["choices"][0]["message"]
            calls = parse_calls(choice.get("tool_calls") or [])
            if not calls:
                raise ToolError("model returned no tool call")
            self.last_route = self.config.route
            return calls
        except (ToolError, KeyError, json.JSONDecodeError, urllib.error.URLError, TimeoutError, OSError) as error:
            self.last_route = f"rules (model unavailable: {type(error).__name__})"
            return self.fallback.plan(intent, context)

    def narrate(self, intent: str, results: list[dict], context: dict | None = None) -> str:
        """Phrase the outcome in the persona's voice, then verify every number."""
        context = context or {}
        facts = json.dumps(_number_surface(results), sort_keys=True)
        given = number_tokens(facts)
        voice = self.voice_prompt or context.get("voice_prompt", "")
        try:
            payload = self._post(
                {
                    "model": self.config.model,
                    "messages": [
                        {"role": "system", "content": voice + "\nOnly use numbers from the FACTS block."},
                        {"role": "user", "content": f"FACTS: {facts}\n\nSay what changed, in one or two sentences."},
                    ],
                    "max_tokens": 160,
                }
            )
            text = payload["choices"][0]["message"]["content"].strip()
            self.assert_numbers_are_given(text, given)
            self.last_route = self.config.route
            return text
        except (NumberFabrication, ToolError, KeyError, json.JSONDecodeError, urllib.error.URLError, TimeoutError, OSError):
            self.last_route = "rules (narration fell back)"
            return self.fallback.narrate("", results)

    @staticmethod
    def assert_numbers_are_given(text: str, given: set[str]) -> None:
        """Every number spoken must be a number the code produced.

        There is no allowance for "structural" digits: a model that says it is
        90 percent sure on a Tuesday is stating two facts nobody computed.
        """
        invented = {n for n in number_tokens(text) if n not in given}
        if invented:
            raise NumberFabrication(f"model produced numbers that were never computed: {sorted(invented)}")

    def _system_prompt(self, context: dict) -> str:
        events = ", ".join(f"{e['id']}={e['label']}" for e in context.get("events", ())[:24])
        return (
            "You are the planner for a cash-flow twin. Choose tools; never state numbers yourself.\n"
            f"Horizon: {context.get('horizon_days', 90)} days. "
            f"Current day: {context.get('day', 0)}. "
            f"Balance: {context.get('balance_cents', 0)} cents.\n"
            f"Ledger events: {events}\n"
            "Prefer forecast, then fork if the user is weighing a change, then highlight if they should look at something."
        )

    def _post(self, body: dict) -> dict:
        return self.config.reply(body, self._opener)


def _number_surface(results: list[dict]) -> dict:
    """Everything the model is allowed to say, already rounded for speech."""
    surface = []
    for result in results:
        clean = {}
        for key, value in result.items():
            if isinstance(value, dict):
                clean[key] = {k: v for k, v in value.items() if isinstance(v, (int, float, str, type(None)))}
            else:
                clean[key] = value
        surface.append(clean)
    return {"results": surface}


def number_tokens(text: str) -> set[str]:
    """Every number in a string, in the forms speech and JSON agree on.

    ``255.0``, ``255`` and ``4,200`` all normalise so that a model may restate a
    computed figure without restating it exactly.
    """
    out: set[str] = set()
    for raw in re.findall(r"\d[\d,]*(?:\.\d+)?", text):
        cleaned = raw.replace(",", "")
        out.add(cleaned)
        if "." in cleaned:
            out.add(cleaned.split(".", 1)[0])
            out.add(cleaned.rstrip("0").rstrip("."))
    return out
