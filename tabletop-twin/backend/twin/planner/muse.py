"""Meta's published API surface: which model runs where, and the shapes it speaks.

The field names here were read off Meta's own documentation, not inferred from
another vendor. ``POST https://api.meta.ai/v1/responses`` requires ``model`` and
``input``, accepts ``instructions``, ``tools``, ``tool_choice``,
``parallel_tool_calls``, ``stream`` and ``max_output_tokens``, and answers with an
``output`` array whose items are ``message``, ``function_call`` or ``reasoning``.
Streaming emits ``response.output_text.delta``,
``response.function_call_arguments.delta`` and ``response.completed``.

What the documentation does not pin down is the shape of a *tool definition* on
``/v1/responses``. That is treated as evidence about the endpoint rather than about
the twin: a request whose tool catalogue is refused is asked again over
``/chat/completions``, whose tool shape Meta does state is drop-in compatible with the
OpenAI SDK, and the route reports which of the two finally answered.

The catalogue follows the same rule the settlement catalog follows: an unchecked model
name is never a reason to refuse. It records what Meta publishes so that a mistake can
be named precisely — and it stays data, editable without touching the planner.
"""

from __future__ import annotations

import json
from typing import Iterable, Iterator

RESPONSES = "responses"
CHAT = "chat"

BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"
PATHS = {RESPONSES: "/responses", CHAT: "/chat/completions"}

# endpoints Meta lists for the model, and whether it is published to write text at all.
CATALOGUE: dict[str, tuple[tuple[str, ...], bool]] = {
    "muse-wonder-1.0": (("responses", "chat-completions", "messages"), True),
    "muse-spark-1.3": (("responses", "chat-completions", "messages"), True),
    "muse-spark-1.2": (("responses", "chat-completions", "messages"), True),
    "muse-spark-1.1": (("responses", "chat-completions", "messages"), True),
    "muse-spark-1.3-contributor": (("responses", "chat-completions", "messages"), True),
    "muse-spark-1.2-contributor": (("responses", "chat-completions", "messages"), True),
    "muse-image-1.0": (("responses", "images"), False),
    "sam-3.1": (("responses",), False),
    "muse-voice-transcribe-1.0": (("asr",), False),
}


def serves(model: str, api: str) -> bool:
    """Whether Meta publishes this model on this endpoint. An unknown name is allowed."""
    entry = CATALOGUE.get(model)
    if entry is None:
        return True
    documented = entry[0]
    return api in documented or (api == CHAT and "chat-completions" in documented)


def writes_text(model: str) -> bool:
    entry = CATALOGUE.get(model)
    return True if entry is None else entry[1]


def refusal(model: str) -> str:
    """Why this model cannot run the table, or '' when nothing is wrong with it."""
    if writes_text(model):
        return ""
    return f"{model} is published for {'/'.join(CATALOGUE[model][0])}, not for writing text"


def describe(model: str) -> dict:
    """What the catalogue knows about one model — for health, never for a decision."""
    entry = CATALOGUE.get(model)
    return {
        "model": model,
        "published": entry is not None,
        "endpoints": list(entry[0]) if entry else [],
        "writes_text": writes_text(model),
    }


def endpoint_path(api: str) -> str:
    return PATHS.get(api, PATHS[CHAT])


def responses_tools(tools: Iterable) -> list[dict]:
    """The flat function definition a responses request carries."""
    return [
        {"type": "function", "name": tool.name, "description": tool.description, "parameters": tool.parameters}
        for tool in tools
    ]


def responses_body(model: str, *, instructions: str = "", user_input="", tools: list | None = None,
                   tool_choice: str = "", parallel: bool = False, stream: bool = False,
                   max_output_tokens: int = 0) -> dict:
    body: dict = {"model": model, "input": user_input}
    if instructions:
        body["instructions"] = instructions
    if tools:
        body["tools"] = tools
    if tool_choice:
        body["tool_choice"] = tool_choice
    if parallel:
        body["parallel_tool_calls"] = True
    if stream:
        body["stream"] = True
    if max_output_tokens:
        body["max_output_tokens"] = max_output_tokens
    return body


def chat_body(model: str, messages: list[dict], *, tools: list | None = None, tool_choice: str = "",
              stream: bool = False, max_tokens: int = 0) -> dict:
    body: dict = {"model": model, "messages": messages}
    if tools:
        body["tools"] = tools
    if tool_choice:
        body["tool_choice"] = tool_choice
    if stream:
        body["stream"] = True
    if max_tokens:
        body["max_tokens"] = max_tokens
    return body


def _message_of(payload: dict) -> dict:
    """The first choice's message of a chat-shaped reply, and never an IndexError.

    A `/v1/responses` payload has no `choices` at all, so reading the first one blindly turned every
    call-less reply into a crash rather than an empty answer. Both readers below go through this.
    """
    choices = payload.get("choices") or []
    first = choices[0] if choices else None
    return (first.get("message") if isinstance(first, dict) else None) or {}


def function_calls(payload: dict) -> list[dict]:
    """Every function call in one reply, from either shape.

    Parallel calls are ordinary here: one ask can return several items, and all of
    them are handed to the validator, which is the only thing that decides whether a
    call is real.
    """
    output = payload.get("output")
    if isinstance(output, list):
        calls = [item for item in output if isinstance(item, dict) and item.get("type") == "function_call"]
        if calls:
            return calls
    return list(_message_of(payload).get("tool_calls") or [])


def text_of(payload: dict) -> str:
    """The prose a reply carries, joined across every message item."""
    parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict) or item.get("type") not in (None, "message", "output_message"):
            continue
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(str(part.get("text", "")) for part in content if isinstance(part, dict))
        elif isinstance(item.get("text"), str):
            parts.append(item["text"])
    if not parts:
        message = _message_of(payload)
        if isinstance(message.get("content"), str):
            parts.append(message["content"])
    return "\n".join(part for part in parts if part).strip()


def iter_events(stream) -> Iterator[tuple[str, dict]]:
    """Read ``text/event-stream`` as (event, data) pairs.

    Blank lines end an event, ``:`` lines are keep-alives, and a data payload that
    is not JSON — including the ``[DONE]`` sentinel some gateways send — arrives as an
    empty dict rather than an exception, because a stream must not die on punctuation.
    """
    event, data = "", []
    for raw in stream:
        line = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else raw
        line = line.rstrip("\r\n")
        if not line:
            if data:
                payload: dict = {}
                try:
                    parsed = json.loads("\n".join(data))
                    payload = parsed if isinstance(parsed, dict) else {}
                except ValueError:
                    payload = {}
                yield event, payload
            event, data = "", []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "event":
            event = value
        elif field == "data":
            data.append(value)


def delta_of(event: str, payload: dict) -> str:
    """The words a stream event adds, and nothing else.

    Argument deltas are deliberately ignored: a tool call is not shown to anybody
    until the code has run it and checked its numbers, so streaming its JSON gains
    nothing and risks a figure escaping half-formed.
    """
    if event.endswith("output_text.delta") or event.endswith("text.delta"):
        value = payload.get("delta")
        return value if isinstance(value, str) else ""
    return ""
