"""The tool surface the twin may reach for.

A model's entire power here is choosing one of these four names and filling in
arguments that this module then validates. It cannot compute, cannot spend, and
cannot widen a limit, because none of those are expressible as a tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


class ToolError(ValueError):
    pass


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    required_args: tuple[str, ...] = ()

    def to_openai(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def validate(self, args: dict) -> dict:
        for key in self.required_args:
            if key not in args:
                raise ToolError(f"{self.name} is missing '{key}'")
        allowed = set(self.parameters.get("properties", {}))
        extra = set(args) - allowed
        if extra:
            raise ToolError(f"{self.name} got unknown arguments: {sorted(extra)}")
        return args


@dataclass(frozen=True)
class ToolCall:
    tool: str
    args: dict = field(default_factory=dict)
    reason: str = ""


FORECAST = Tool(
    name="forecast",
    description="Re-run the Monte Carlo cash-flow forecast over the horizon and report P10/P50/P90.",
    parameters={
        "type": "object",
        "properties": {
            "horizon_days": {"type": "integer", "minimum": 7, "maximum": 180},
            "runs": {"type": "integer", "minimum": 500, "maximum": 20000},
        },
    },
)

FORK = Tool(
    name="fork",
    description="Spawn a second miniature world with one intervention applied, and compare it to the baseline.",
    parameters={
        "type": "object",
        "properties": {
            "label": {"type": "string"},
            "cancel_event_ids": {"type": "array", "items": {"type": "string"}},
            "chase_event_ids": {"type": "array", "items": {"type": "string"}},
            "shift": {"type": "object", "additionalProperties": {"type": "integer"}},
        },
        "required": ["label"],
    },
    required_args=("label",),
)

HIGHLIGHT = Tool(
    name="highlight",
    description="Point the orb at something in the world: a day, an event, or a branch.",
    parameters={
        "type": "object",
        "properties": {
            "target": {"type": "string", "enum": ["day", "event", "branch", "driest"]},
            "id": {"type": "string"},
            "note": {"type": "string"},
        },
        "required": ["target"],
    },
    required_args=("target",),
)

PROPOSE_ACTION = Tool(
    name="propose_action",
    description="Propose a payment or subscription change for the policy engine to judge. Never executes anything.",
    parameters={
        "type": "object",
        "properties": {
            "verb": {
                "type": "string",
                "enum": ["pay_bill", "chase_invoice", "cancel_subscription", "start_subscription", "shift_payment"],
            },
            "event_id": {"type": "string"},
            "amount_cents": {"type": "integer", "minimum": 0},
            "recipient": {"type": "string"},
            "justification": {"type": "string"},
        },
        "required": ["verb"],
    },
    required_args=("verb",),
)

REGISTRY: dict[str, Tool] = {t.name: t for t in (FORECAST, FORK, HIGHLIGHT, PROPOSE_ACTION)}


def parse_calls(raw: Iterable[dict]) -> list[ToolCall]:
    """Accept only tool names and arguments this registry recognises."""
    calls: list[ToolCall] = []
    for item in raw:
        # OpenAI-compatible endpoints nest the call; a hand-written one does not.
        function = item.get("function") or {}
        name = function.get("name") or item.get("name") or item.get("tool")
        tool = REGISTRY.get(str(name))
        if tool is None:
            raise ToolError(f"'{name}' is not a tool the twin has")
        args = function.get("arguments") or item.get("args") or item.get("arguments") or {}
        if isinstance(args, str):
            import json

            try:
                args = json.loads(args or "{}")
            except json.JSONDecodeError as exc:
                raise ToolError(f"{name} sent arguments that are not JSON") from exc
        calls.append(ToolCall(tool=str(name), args=tool.validate(dict(args)), reason=item.get("reason", "")))
    return calls


def handler_map(executor) -> dict[str, Callable[..., dict]]:
    """Bind each tool to a method on the world executor."""
    return {name: getattr(executor, f"tool_{name}") for name in REGISTRY}
