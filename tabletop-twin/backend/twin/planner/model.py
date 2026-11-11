"""Muse Spark / Claude through an OpenAI-compatible endpoint.

Two shapes are spoken here. Meta's own agentic endpoint, ``/v1/responses``, is used
for Muse: it carries ``instructions`` and ``input``, returns parallel ``function_call``
items, and streams narration as ``response.output_text.delta`` events. The
``/chat/completions`` shape — which Meta states is drop-in compatible with the OpenAI
SDK — is the fallback for every endpoint, and the one the generic route uses, because
an unverified address is a plain OpenAI-compatible server by definition.

Each endpoint is configured on its own and reported under its own name: a route that
says ``muse:...`` was answered by Meta's Model API, never by whatever happened to be in
the environment. What may be defaulted is decided by who publishes it: Meta publishes
the address, the default model and the variable name, so a key alone is a complete Muse
configuration. A credential is the one thing never assumed into existence.

Two guards matter more than the rest. `assert_numbers_are_given`: a model that invents
a plausible dollar figure is worse than a model that says nothing, so narration is
checked against the numbers the forecast actually produced. And a stream is released
sentence by sentence, each one verified before it is shown, so an invented figure
never reaches the panel even while the rest of the sentence is still arriving.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from urllib.parse import urlparse

from . import muse
from .rules import RulePlanner
from .tools import REGISTRY, ToolCall, ToolError, parse_calls

MUSE = "muse"
GENERIC = "openai-compatible"

MUSE_BASE_URL = muse.BASE_URL
MUSE_MODEL = muse.DEFAULT_MODEL
RESPONSES = muse.RESPONSES
CHAT = muse.CHAT

# A refusal worth asking twice about: the endpoint objected to the shape of the
# request, not to who sent it. A timeout or a rate limit is not that.
SHAPE_REFUSALS = (400, 404, 422)

MUSE_KEY_VARS = ("META_MODEL_API_KEY", "MODEL_API_KEY")
MUSE_BASE_VARS = ("META_MODEL_BASE_URL",)
MUSE_MODEL_VARS = ("META_MODEL_NAME",)
GENERIC_KEY_VARS = ("LLM_API_KEY", "OPENAI_COMPAT_API_KEY")
GENERIC_BASE_VARS = ("LLM_BASE_URL", "OPENAI_COMPAT_BASE_URL")
GENERIC_MODEL_VARS = ("LLM_MODEL", "OPENAI_COMPAT_MODEL")

MAX_RETRY_SEC = 2.0
DETAIL_LIMIT = 140


@dataclass
class ModelConfig:
    base_url: str
    api_key: str
    model: str
    provider: str = GENERIC
    api: str = CHAT
    timeout_sec: float = 20.0
    max_output_tokens: int = 512
    max_retry_sec: float = MAX_RETRY_SEC
    supplied: dict[str, str] = field(default_factory=dict)

    @property
    def route(self) -> str:
        return f"{self.provider}:{self.model}"

    @property
    def host(self) -> str:
        return urlparse(self.base_url).netloc or self.base_url

    def url(self, api: str = "") -> str:
        return f"{self.base_url}{muse.endpoint_path(api or self.api)}"

    def endpoints(self) -> list[str]:
        """The shapes this endpoint may be asked in, best first.

        A model Meta only publishes for images or transcription is not asked in any
        of them, and a model Meta does not publish on ``/v1/responses`` is not asked
        there either. The compatible shape is listed last and only when Meta lists the
        model on it: a refusal of a request shape is not a refusal of the model, but
        asking a model where nobody publishes it would only spend a second request.
        """
        if muse.refusal(self.model):
            return []
        shapes = [self.api] if muse.serves(self.model, self.api) else []
        if CHAT not in shapes and muse.serves(self.model, CHAT):
            shapes.append(CHAT)
        return shapes

    def spoken(self, api: str) -> str:
        return self.route if api == self.api else f"{self.route} via {api}"

    def request(self, body: dict, api: str) -> urllib.request.Request:
        return urllib.request.Request(
            self.url(api),
            data=json.dumps(body).encode(),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )

    def reply(self, body: dict, api: str = "", opener=urllib.request.urlopen) -> dict:
        """One call, read in full, translated into a payload or into a reason worth showing."""
        response = self.send(body, api, opener)
        with response:
            raw = response.read()
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise ModelUnavailable(f"{self.host} answered with something that is not JSON") from error

    def send(self, body: dict, api: str = "", opener=urllib.request.urlopen):
        """Open the socket and fail here, not lazily, so a refusal is never silent."""
        request = self.request(body, api or self.api)
        try:
            return opener(request, timeout=self.timeout_sec)
        except urllib.error.HTTPError as error:
            raise _refusal(error, self) from error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise ModelUnavailable(f"{self.host} did not answer ({type(error).__name__})") from error

    def stream(self, body: dict, api: str = "", opener=urllib.request.urlopen):
        """Yield (event, payload) pairs from a streaming reply, closing it when done."""
        response = self.send(body, api, opener)

        def lines():
            try:
                yield from muse.iter_events(response)
            finally:
                try:
                    response.close()
                except Exception:
                    pass

        return lines()


class ModelUnavailable(Exception):
    """Why the endpoint did not answer, worded so it can be spoken as a route."""

    def __init__(self, reason: str, *, status: int | None = None, retryable: bool = False,
                 retry_after_sec: float | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.retryable = retryable
        self.retry_after_sec = retry_after_sec

    def wait_sec(self, cap: float) -> float:
        """The pause the endpoint asked for, bounded by what this table will wait."""
        wanted = cap if self.retry_after_sec is None else self.retry_after_sec
        return max(0.0, min(wanted, cap))


def _refusal(error: urllib.error.HTTPError, config: ModelConfig) -> ModelUnavailable:
    code = error.code
    detail = _snippet(_body_of(error))
    tail = f": {detail}" if detail else ""
    if code in (401, 403):
        where = config.supplied.get("api_key")
        stamp = f" (key from {where})" if where else ""
        return ModelUnavailable(f"HTTP {code} refused the credential for {config.route}{stamp}{tail}", status=code)
    if code == 429:
        return ModelUnavailable(f"HTTP 429 rate limited by {config.host}{tail}", status=code,
                                retryable=True, retry_after_sec=_retry_after(error))
    if code >= 500:
        return ModelUnavailable(f"HTTP {code} from {config.host}{tail}", status=code, retryable=True)
    return ModelUnavailable(f"HTTP {code} from {config.url(config.api)}{tail}", status=code)


def _retry_after(error: urllib.error.HTTPError) -> float | None:
    raw = error.headers.get("Retry-After") if error.headers else None
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _body_of(error: urllib.error.HTTPError) -> str:
    try:
        return error.read().decode("utf-8", "replace")
    except (OSError, ValueError):
        return ""


def _snippet(text: str) -> str:
    """Flatten whatever the endpoint said into one short, log-safe clause."""
    clean = " ".join(text.split())
    if len(clean) > DETAIL_LIMIT:
        clean = clean[:DETAIL_LIMIT].rstrip() + "..."
    return clean


def _first(names: tuple[str, ...]) -> tuple[str, str]:
    """The value and the name of the first of these variables that is set."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value, name
    return "", ""


def _from_names(base_vars: tuple[str, ...], key_vars: tuple[str, ...], model_vars: tuple[str, ...],
                provider: str, api: str = CHAT, default_base: str = "",
                default_model: str = "") -> ModelConfig | None:
    base, base_var = _first(base_vars)
    key, key_var = _first(key_vars)
    model, model_var = _first(model_vars)
    # A key is the only thing that cannot be assumed into existence.
    if not key:
        return None
    base = base or default_base
    model = model or default_model
    # A generic server has no published address or model, so a key alone is not an endpoint.
    if not base or not model:
        return None
    supplied = {"api_key": key_var, "base_url": base_var, "model": model_var}
    return ModelConfig(base_url=base.rstrip("/"), api_key=key, model=model,
                       provider=provider, api=api, supplied=supplied)


def providers_from_env() -> list[ModelConfig]:
    """Every endpoint this machine is configured for, most preferred first.

    Muse wins when both are present, and the fallback to rules is reached only
    after the endpoints actually tried have failed — so a route is a report, not
    a guess.
    """
    out = [
        _from_names(MUSE_BASE_VARS, MUSE_KEY_VARS, MUSE_MODEL_VARS, MUSE, api=RESPONSES,
                    default_base=MUSE_BASE_URL, default_model=MUSE_MODEL),
        _from_names(GENERIC_BASE_VARS, GENERIC_KEY_VARS, GENERIC_MODEL_VARS, GENERIC, api=CHAT),
    ]
    return [config for config in out if config is not None]


def providers_configured() -> list[str]:
    """Names only. An endpoint is reported as configured without repeating its key."""
    return [config.provider for config in providers_from_env()]


def route_details() -> list[dict]:
    """What each configured endpoint is, derived from the environment alone.

    Nothing here opens a socket: a deployment can say which model it intends to
    speak to, in which shape, and which of those words came from the operator rather
    than from a published default, without proving it at the cost of a request.
    """
    return [
        {
            "provider": config.provider,
            "model": config.model,
            "host": config.host,
            "api": config.api,
            "api_alternatives": config.endpoints(),
            "endpoint": config.url(),
            "timeout_sec": config.timeout_sec,
            "catalogue": muse.describe(config.model),
            "unusable": muse.refusal(config.model),
            "supplied_by": dict(config.supplied),
            # Fields with no variable behind them came from a published default.
            "assumed": sorted(name for name, source in config.supplied.items() if not source),
            "preferred": index == 0,
        }
        for index, config in enumerate(providers_from_env())
    ]


class NumberFabrication(Exception):
    pass


class ModelPlanner:
    """Asks a model which tool to run. Never lets it do arithmetic."""

    name = "model"

    def __init__(self, config: ModelConfig, opener=urllib.request.urlopen,
                 fallback: RulePlanner | None = None, sleeper=time.sleep) -> None:
        self.config = config
        self._opener = opener
        self._sleeper = sleeper
        self.fallback = fallback or RulePlanner()
        self.last_route = ""
        self.voice_prompt = ""
        self.attempts = 0

    @property
    def provider(self) -> str:
        return self.config.provider

    @property
    def route(self) -> str:
        """The endpoint this planner is pointed at, before anyone has asked it anything."""
        return self.config.route

    @classmethod
    def from_env(cls) -> "ModelPlanner | None":
        configs = providers_from_env()
        return cls(configs[0]) if configs else None

    def plan(self, intent: str, context: dict) -> list[ToolCall]:
        blocked = muse.refusal(self.config.model)
        if blocked:
            self.last_route = f"rules ({blocked})"
            return self.fallback.plan(intent, context)
        system = self._system_prompt(context)
        bodies = [
            (RESPONSES, muse.responses_body(
                self.config.model, instructions=system, user_input=intent,
                tools=muse.responses_tools(REGISTRY.values()), tool_choice="auto",
                parallel=True, max_output_tokens=self.config.max_output_tokens)),
            (CHAT, muse.chat_body(
                self.config.model,
                [{"role": "system", "content": system}, {"role": "user", "content": intent}],
                tools=[t.to_openai() for t in REGISTRY.values()], tool_choice="auto",
                max_tokens=self.config.max_output_tokens)),
        ]
        return self._ask_tools(bodies, intent, context)

    def _ask_tools(self, bodies: list[tuple[str, dict]], intent: str, context: dict) -> list[ToolCall]:
        failure: Exception | None = None
        for api, body in bodies:
            if api not in self.config.endpoints():
                continue
            try:
                payload = self._post(body, api)
                calls = parse_calls(muse.function_calls(payload))
                if not calls:
                    raise ToolError("model returned no tool call")
                self.last_route = self.config.spoken(api)
                return calls
            except (ModelUnavailable, ToolError, KeyError, json.JSONDecodeError,
                    urllib.error.URLError, TimeoutError, OSError) as error:
                failure = error
                if not _refused_the_shape(error):
                    break
        self.last_route = f"rules ({_why(failure)})"
        return self.fallback.plan(intent, context)

    def narrate(self, intent: str, results: list[dict], context: dict | None = None,
                on_delta=None) -> str:
        """Phrase the outcome in the persona's voice, then verify every number.

        ``on_delta`` sees the narration a sentence at a time, and only after that
        sentence has passed the same check the finished text has to pass.
        """
        context = context or {}
        facts = json.dumps(_number_surface(results), sort_keys=True)
        given = number_tokens(facts)
        voice = self.voice_prompt or context.get("voice_prompt", "")
        ask = f"FACTS: {facts}\n\nSay what changed, in one or two sentences."
        blocked = muse.refusal(self.config.model)
        if blocked:
            self.last_route = f"rules (narration fell back: {blocked})"
            return self.fallback.narrate("", results)
        bodies = [
            (RESPONSES, muse.responses_body(
                self.config.model, instructions=voice + "\nOnly use numbers from the FACTS block.",
                user_input=ask, max_output_tokens=160, stream=on_delta is not None)),
            (CHAT, muse.chat_body(
                self.config.model,
                [{"role": "system", "content": voice + "\nOnly use numbers from the FACTS block."},
                 {"role": "user", "content": ask}], max_tokens=160)),
        ]
        failure: Exception | None = None
        for api, body in bodies:
            if api not in self.config.endpoints():
                continue
            try:
                if api == RESPONSES and body.get("stream"):
                    text = self._stream_text(body, given, on_delta)
                else:
                    text = muse.text_of(self._post(body, api))
                if not text:
                    raise ToolError("model returned no words")
                self.assert_numbers_are_given(text, given)
                self.last_route = self.config.spoken(api)
                return text
            except (NumberFabrication, ModelUnavailable, ToolError, KeyError, json.JSONDecodeError,
                    urllib.error.URLError, TimeoutError, OSError) as error:
                failure = error
                if not _refused_the_shape(error):
                    break
        self.last_route = f"rules (narration fell back: {_why(failure)})"
        return self.fallback.narrate("", results)

    def _stream_text(self, body: dict, given: set[str], on_delta) -> str:
        """Read a stream, releasing only sentences whose numbers have been checked.

        Once a sentence fails the check the caption is frozen where it is: the words
        already shown were all computed, and the rest is replaced by the rule
        planner's own sentence when this returns.
        """
        text = ""
        shown = 0
        trusting = True
        for event, payload in self.config.stream(body, RESPONSES, self._opener):
            if event.endswith("completed") and payload:
                final = muse.text_of(payload)
                if final:
                    text = final
            piece = muse.delta_of(event, payload)
            if piece:
                text += piece
            if not trusting or on_delta is None:
                continue
            release, safe = safe_release(text, given)
            if not safe:
                trusting = False
                continue
            if len(release) > shown:
                on_delta(release[shown:])
                shown = len(release)
        return text.strip()

    def _post(self, body: dict, api: str) -> dict:
        """Ask once. If the answer is 'busy', wait the pause asked for and ask once more.

        One repair attempt, never a loop: an endpoint that is refusing a credential
        does not become honest because it was asked twice, and a rate limit that
        survives the wait is a rate limit the table should not sit through again.
        """
        self.attempts = 1
        try:
            return self.config.reply(body, api, self._opener)
        except ModelUnavailable as error:
            if not error.retryable:
                raise
            self._sleeper(error.wait_sec(self.config.max_retry_sec))
        self.attempts += 1
        try:
            return self.config.reply(body, api, self._opener)
        except ModelUnavailable as again:
            raise ModelUnavailable(f"{again.reason} (asked twice)", status=again.status) from again

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


def _refused_the_shape(error: Exception) -> bool:
    """Only a rejection of the request's shape is worth re-asking in another shape."""
    return isinstance(error, ModelUnavailable) and error.status in SHAPE_REFUSALS


def _why(error: Exception | None) -> str:
    if error is None:
        return "no endpoint answered"
    if isinstance(error, ModelUnavailable):
        return error.reason
    if isinstance(error, KeyError):
        return f"the reply had no {error.args[0]!r}" if error.args else "the reply was missing a field"
    if isinstance(error, json.JSONDecodeError):
        return "the reply was not JSON"
    return " ".join(str(error).split()) or type(error).__name__


def safe_release(text: str, given: set[str]) -> tuple[str, bool]:
    """The part of a narration that may be shown yet, and whether the rest is trusted.

    Only whole sentences are released, because a number is only verifiable once it is
    finished: "about $4" and "about $4,200" arrive in the same sentence and mean
    different things.
    """
    released, safe = 0, True
    start = 0
    for index, character in enumerate(text):
        if character not in ".!?\n":
            continue
        segment = text[start:index + 1]
        if not number_tokens(segment).issubset(given):
            safe = False
            break
        released = index + 1
        start = index + 1
    return text[:released], safe


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
