"""`python -m twin.audit.judge` - the firm's judgement made by a model and checked against the law.

This is the inversion the rest of the subsystem was built to survive. Before it, a Python function
read the case, applied a threshold typed into a config, and handed the result to Muse to be phrased.
Muse never decided anything; it was a caption writer with an API key. Here the model is handed the
client's figures and six passages of harvested statute, and it decides: which rule governs, whether
this engagement sits inside it, and which colleague has to act. The verdict is its verdict.

What the code does instead of agreeing with it is verify it, in seven checks that need no opinion
about language:

1. the verdict is one of the four this firm recognises, in its vocabulary, not a synonym of one;
2. the citation names one article of this harvest, by the id of a passage it was actually given;
3. the quote appears, word for word, inside the passage it is attributed to - which is the check a
   model cannot answer its way out of, because the words are somebody else's;
4. every number in the sentence is either the client's figure or inside the quote, so a statutory
   limit has to have been read rather than remembered;
5. the figures it says it relied on are figures it was given;
6. the colleague it asks exists, and is not itself;
7. the sentence is short enough to be a caption, because a model that writes three paragraphs about
   a two-line finding is not reporting a rule.

A judgement that fails one of these is refused, the deterministic answer is used instead, and the
refusal is what the route says - never silently. That is the whole difference between a fallback and
a lie: the table has to be able to tell you which one it is showing you.

The passages are truncated before they are shown and the quote is checked against the truncated text
that was. A model that recites a true sentence it was never handed has reasoned from its own memory
of EU law, and this deployment does not claim to have read the Official Journal into a model's
weights.
"""

from __future__ import annotations

import dataclasses
import json
import re
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from twin.audit.agents import BREACH, CLEAR, HOLD, SILENT, Case, Finding, ROLES
from twin.audit.index import CorpusIndex
from twin.planner import muse
from twin.planner.model import SHAPE_REFUSALS, ModelConfig, ModelUnavailable, number_tokens

TOOL = "submit_judgement"
VERDICTS = (CLEAR, HOLD, BREACH, SILENT)

PASSAGES = 6
# The median harvested article is 588 characters and goes in whole. The window has to be wide enough
# to reach the point of a long one: Article 5(1)(c) - the prohibition on book-keeping, the rule this
# firm is asked about most - sits 1 393 characters into an article of 6 587, and a shorter window
# would show a model the heading of the prohibition and none of its list.
PASSAGE_CHARS = 2400
SENTENCE_CHARS = 400


def facts_of(case: Case) -> dict[str, Any]:
    """Everything the model may state as a figure about this client: its file, and nothing else.

    No threshold is in here. That is deliberate and it is the point - a fact list that carried the
    70% cap would let a model pass the number check by copying the answer out of the prompt.

    Booleans are kept even when they are false. `is_pie: false` is the fact that turns half the
    Regulation off for this client, and a filter that drops anything falsy would hand the model a file
    with no client type in it and invite it to guess.
    """
    facts: dict[str, Any] = {}
    for name, value in sorted(vars(case).items()):
        if isinstance(value, bool):
            facts[name] = value
        elif isinstance(value, (int, float, str, tuple)) and value not in (0, 0.0, "", ()):
            facts[name] = value
    facts["non_audit_percent_of_audit_fee"] = case.non_audit_percent()
    facts["client_share_of_firm_fees_percent"] = case.dependence_percent()
    return facts


def _shown(passages: list[dict[str, Any]]) -> dict[str, str]:
    """The exact text each id was rendered with, because that is what the model was allowed to read."""
    return {entry["law_id"]: entry["shown"] for entry in passages}


@dataclass
class Judgement:
    """One role's answer, and what the machine thought of it."""

    finding: Finding
    accepted: bool
    refusal: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    passages: int = 0


class Judge:
    """Asks Muse for a verdict, and refuses it when it cannot be checked."""

    name = "model"

    def __init__(self, config: ModelConfig, index: CorpusIndex, roles: tuple[str, ...] = ROLES,
                 opener=urllib.request.urlopen, sleeper=time.sleep) -> None:
        self.config = config
        self.index = index
        self.roles = roles
        self._opener = opener
        self._sleeper = sleeper
        self.refusals: list[dict[str, str]] = []
        self.attempts = 0
        self.last_route = ""

    @classmethod
    def from_env(cls, index: CorpusIndex | None = None) -> "Judge | None":
        """None when this machine is configured for no model at all, which is the common case here."""
        from twin.planner.model import providers_from_env

        configs = providers_from_env()
        if not configs:
            return None
        return cls(configs[0], index or CorpusIndex.load())

    # ------------------------------------------------------------------------ asking

    def instructions(self, role: str, question: str) -> str:
        return (
            f"You are the {role} of an EU statutory audit firm deciding one question about one"
            f" engagement: {question}.\n"
            "Decide from the LAW passages below. Nobody else has read them and nothing else knows"
            " what they say, so a rule you remember is worth nothing here - if it is not in a"
            " passage, it is not a rule you may apply.\n"
            f"Answer with {TOOL}. Its fields:\n"
            "  verdict: 'clear' (the rule was checked and the engagement sits inside it),"
            " 'hold' (the rule binds and something must happen first), 'breach' (the engagement is"
            " already outside the rule), or 'silent' (these passages state no rule for this"
            " question - silence is a complete answer, not a failure).\n"
            "  law_id, celex, article: the one passage you relied on, copied from its own line.\n"
            "  quote: a sentence copied out of that passage word for word, punctuation and all."
            " Not a summary. Not a paraphrase. The exact words.\n"
            "  sentence: one line for the engagement file, in English, stating what the rule means"
            " for this client.\n"
            "  relied_on: the FACTS keys whose figures you used.\n"
            "  asks_of_role: the colleague who must act on this, or '' when nobody must.\n"
            "Every number in 'sentence' must be a figure from FACTS or a figure inside your quote."
            " If neither holds a figure the rule needs, say so and return 'silent'."
        )

    def ask_text(self, question: str, facts: dict[str, Any], passages: list[dict[str, Any]]) -> str:
        law = "\n".join(f"[{entry['law_id']}] {entry['ref']}\n{entry['shown']}" for entry in passages)
        return (f"QUESTION: {question}\n\nFACTS:\n{json.dumps(facts, sort_keys=True, default=list)}"
                f"\n\nLAW:\n{law or '(nothing was retrieved - return silent)'}")

    def retrieve(self, role: str, question: str, facts: dict[str, Any]) -> list[dict[str, Any]]:
        """The six passages this judgement will be checked against.

        The query is the role and its question, and the figures are deliberately left out of it. They
        were in here once, and measured over all eighteen desks: with the fact keys and values appended,
        the eighteen questions answered with only eleven distinct articles between them, and three of
        those - the Accounting Directive's size definitions, the Audit Regulation's transparency report,
        the CSRD's scope - came back in all eighteen sets. A client's file is written in the same
        vocabulary as the statute that governs it, so a retriever that answers every question with the
        articles everybody mentions is not retrieving. The figures belong in the FACTS block, where the
        model reads them as facts rather than as search terms.
        """
        return self.index.passages(f"{role.replace('-', ' ')} {question}", PASSAGES, PASSAGE_CHARS)

    def bodies(self, instructions: str, user: str) -> list[tuple[str, dict]]:
        """Both request shapes, in the order this endpoint is published to answer.

        Meta documents `/v1/responses` tools but not their exact definition shape, so a refusal of
        that body is answered by asking again over the OpenAI-compatible chat endpoint rather than by
        giving up on the model. `tool_choice` is "auto" in both because that is the only value Meta
        states either endpoint accepts; forcing the call is the instruction's job, and `_args_of`
        reads bare JSON out of prose so a model that answers in text instead of by calling the tool is
        still checked rather than dropped.
        """
        schema = {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": list(VERDICTS)},
                "law_id": {"type": "string"},
                "celex": {"type": "string"},
                "article": {"type": "string"},
                "quote": {"type": "string"},
                "sentence": {"type": "string"},
                "relied_on": {"type": "array", "items": {"type": "string"}},
                "asks_of_role": {"type": "string", "enum": [""] + list(self.roles)},
            },
            "required": ["verdict", "law_id", "quote", "sentence", "asks_of_role"],
        }
        tool = {"name": TOOL, "description": "The firm's judgement, made from the law passages above.",
                "parameters": schema}
        return [
            (muse.RESPONSES, muse.responses_body(
                self.config.model, instructions=instructions, user_input=user,
                tools=[{"type": "function", **tool}], tool_choice="auto",
                max_output_tokens=self.config.max_output_tokens)),
            (muse.CHAT, muse.chat_body(
                self.config.model, [{"role": "system", "content": instructions},
                                    {"role": "user", "content": user}],
                tools=[{"type": "function", "function": tool}], tool_choice="auto",
                max_tokens=self.config.max_output_tokens)),
        ]

    def _post(self, body: dict, api: str) -> dict:
        self.attempts += 1
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

    def _args_of(self, payload: dict) -> dict[str, Any]:
        """The judgement inside a reply, whether it came as a tool call or as bare JSON."""
        for call in muse.function_calls(payload):
            function = call.get("function") or {}
            if (function.get("name") or call.get("name")) != TOOL:
                continue
            raw = function.get("arguments") or call.get("arguments") or call.get("args") or {}
            return json.loads(raw) if isinstance(raw, str) else dict(raw)
        text = muse.text_of(payload)
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return {}
        return {}

    def ask(self, role: str, question: str, facts: dict[str, Any]) -> Judgement | None:
        """One role's judgement from the endpoint, or None when the endpoint never answered.

        None is not a refusal: it is the absence of an answer, and the difference is in the route -
        "rules (muse did not answer: HTTP 503)" reads differently to a person than "rules (muse
        refused: the quote is not in Article 5)".
        """
        if self.index.state != "checked":
            # Hashes alone cannot check a quote, and a route that says "muse decided" when nothing
            # could have been checked is the one lie this design cannot tell. So the asking never
            # starts, and the requests are not spent on answers that would all be thrown away.
            self.last_route = ("rules (the harvested text is not on this machine, so no quote could"
                               " have been checked)")
            return None
        passages = self.retrieve(role, question, facts)
        bodies = self.bodies(self.instructions(role, question), self.ask_text(question, facts, passages))
        failure: Exception | None = None
        for api, body in bodies:
            if api not in self.config.endpoints():
                continue
            try:
                args = self._args_of(self._post(body, api))
            except (ModelUnavailable, json.JSONDecodeError, KeyError, urllib.error.URLError,
                    TimeoutError, OSError) as error:
                failure = error
                if not _refused_the_shape(error):
                    break
                continue
            if not args:
                failure = ModelUnavailable("the reply carried no judgement to read")
                continue
            self.last_route = self.config.spoken(api)
            return self.check(role, question, facts, args, passages)
        self.last_route = f"rules (muse did not answer: {_why(failure)})"
        return None

    # ------------------------------------------------------------------------ verifying

    def check(self, role: str, question: str, facts: dict[str, Any], args: dict[str, Any],
              passages: list[dict[str, Any]]) -> Judgement:
        verdict = str(args.get("verdict", "")).strip().lower()
        sentence = " ".join(str(args.get("sentence", "")).split())
        quote = str(args.get("quote", ""))
        law_id = str(args.get("law_id", "")).strip()
        asks_of = str(args.get("asks_of_role", "")).strip()
        cite = {"law_id": law_id, "celex": str(args.get("celex", "")).strip(),
                "article": str(args.get("article", "")).strip(), "quote": quote}
        shown = _shown(passages)
        relied = [str(key) for key in (args.get("relied_on") or [])]
        unexplained = [key for key in relied if key not in facts]
        resolved = self.index.verify(cite)

        reason = ""
        if verdict not in VERDICTS:
            reason = f"'{verdict}' is not a verdict this firm recognises"
        elif not sentence:
            reason = "the judgement carried no sentence for the engagement file"
        elif len(sentence) > SENTENCE_CHARS:
            reason = f"the sentence is {len(sentence)} characters, longer than a finding caption"
        elif not law_id:
            reason = "it named no passage, so nothing could be checked against what it read"
        elif law_id not in shown:
            reason = f"{law_id} is not one of the {len(passages)} passages it was shown"
        elif resolved:
            reason = resolved
        elif _fold(quote) not in _fold(shown[law_id]):
            reason = (f"that sentence is in the article but not in the {PASSAGE_CHARS} characters of it"
                      " that were sent, so it was remembered rather than read")
        elif not _figures_are_given(sentence, facts, quote):
            reason = "the sentence states a figure that is neither the client's nor inside the quote"
        elif unexplained:
            reason = ("it relied on " + ", ".join(f"'{key}'" for key in unexplained)
                      + ", which is not a fact it was given")
        elif asks_of and asks_of not in self.roles:
            reason = f"'{asks_of}' is not a role of this firm"
        elif asks_of == role:
            reason = "a role cannot ask itself to act"

        numbers = dict(facts)
        numbers.update({"verdict": verdict or "none", "law_id": law_id, "relied_on": relied,
                        "passages": len(passages),
                        "ref": next((p["ref"] for p in passages if p["law_id"] == law_id), "")})
        finding_cite = ({**self.index.cite_of(cite), "quote": quote[:300]} if not reason else
                        {"law_id": law_id, "state": "refused", "why": reason})
        finding = Finding(role, question, verdict if verdict in VERDICTS else SILENT,
                          sentence or "The model's answer could not be checked, so the firm's own rule"
                                      " stands.", numbers, finding_cite, asks_of,
                          self.last_route or self.config.route)
        if reason:
            self.refusals.append({"role": role, "reason": reason, "route": self.last_route})
            return Judgement(finding, False, reason, args, len(passages))
        return Judgement(finding, True, "", args, len(passages))

    def judge(self, role: str, question: str, facts: dict[str, Any],
              fallback: Callable[[], Finding]) -> Finding:
        """The judgement, or the rule it fell back to - with whichever of the two happened named.

        A refused judgement keeps none of itself. Not the verdict, because it was not checkable, and
        not its sentence, because the engagement file cannot show words the firm could not trace back
        to a passage. What survives the refusal is the reason, and it survives in two places: in the
        route, which is where a fallback becomes visible instead of invisible, and in the numbers, so
        a panel can say which rule was substituted and why.
        """
        base = fallback()
        answer = self.ask(role, question, facts)
        if answer is None:
            return dataclasses.replace(base, route=self.last_route)
        if answer.accepted:
            return answer.finding
        return dataclasses.replace(base, route=f"rules (muse refused: {answer.refusal})",
                                   numbers={**base.numbers, "muse_refused": answer.refusal})

    def describe(self) -> dict[str, Any]:
        return {"route": self.last_route or self.config.route, "provider": self.config.provider,
                "model": self.config.model, "host": self.config.host, "refused": len(self.refusals),
                "articles": self.index.counts()}


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().strip(' .').lower()


def _figures_are_given(sentence: str, facts: dict[str, Any], quote: str) -> bool:
    """Every number spoken is a number the client's file holds or the quoted law states.

    Comparison goes through `number_tokens`, which is how a model may say 70 when the facts said 70.0
    and the statute wrote "70 %`. What it may not do is say 85.
    """
    allowed = number_tokens(json.dumps(facts, sort_keys=True, default=list))
    allowed |= number_tokens(quote)
    return number_tokens(sentence).issubset(allowed)


def _refused_the_shape(error: Exception) -> bool:
    return isinstance(error, ModelUnavailable) and error.status in SHAPE_REFUSALS


def _why(error: Exception | None) -> str:
    if error is None:
        return "no endpoint answered"
    if isinstance(error, ModelUnavailable):
        return error.reason
    return " ".join(str(error).split()) or type(error).__name__


def main(argv: list[str]) -> int:
    from twin.audit.agents import Priors, QUESTIONS
    from twin.audit.service import engagements

    judge = Judge.from_env()
    if judge is None:
        print("No model is configured here. Set MODEL_API_KEY (Meta's own name for it is"
              " META_MODEL_API_KEY) and this command asks Muse for every judgement.\n"
              "Without it the firm still answers - by its own rules, and it says which route spoke.")
        return 1
    index = judge.index
    print(f"asking {index.counts()['articles']} articles of law of {judge.config.route}"
          f" ({index.state})")
    cases = engagements()
    case = cases[int(argv[argv.index("--engagement") + 1]) if "--engagement" in argv else 0]
    priors = Priors.load()
    counts = {"decided": 0, "refused": 0, "unanswered": 0}
    for role, answer in QUESTIONS:
        base = answer(case, priors)
        found = judge.judge(role, base.asks, facts_of(case), lambda base=base: base)
        mark = ("refused" if "muse refused" in found.route
                else "unanswered" if found.route.startswith("rules") else "decided")
        counts[mark] += 1
        print(f"  {role:26s} {found.verdict:7s} {mark:10s} {found.cite.get('law_id',''):>7}"
              f"  {found.sentence[:92]}")
    print(f"{len(QUESTIONS)} roles, {counts['decided']} decided by muse, {counts['refused']} refused,"
          f" {counts['unanswered']} unanswered, {judge.attempts} requests spent")
    for refusal in judge.refusals:
        print(f"  why: {refusal['role']}: {refusal['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
