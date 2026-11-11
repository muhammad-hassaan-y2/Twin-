"""The audit firm's own scenarios, scored the same way the payment world is.

These cases decide nothing about the law - `test_priors.py` and `test_agents.py` already hold
the derivation and the verdicts to account. What is scored here is the *behaviour of the firm as
a system*: that a breach or a silence never becomes traffic somebody has to sign, that the
percentage a finding prints and the verdict it reached are computed from the same cents, that a
one-word match with the prohibition is escalated instead of read as permission, that a model's
sentence cannot move a threshold, and that every number the firm actually enforces is exercised
by at least one case here.

Nothing in this file reaches a chain, a model endpoint or a database. The agreements are
recorded by a stub bus, the model's reply is produced in-process, and the corpus is read from the
shipped derivation. A score from this file therefore means the same thing on a machine with no
keys as on one with all of them - which is the only way a guard case can be run with its guard
removed and still mean anything.
"""

from __future__ import annotations

import inspect
import io
import json
import re
from dataclasses import replace
from typing import Any

from twin.audit import agents
from twin.audit.a2a import STATES
from twin.audit.agents import (BREACH, CLEAR, HOLD, SILENT, Case, Firm, Finding, ModelWords,
                               Priors)
from twin.audit.corpus import measures
from twin.audit.finetune import build as build_corpus
from twin.audit.finetune import check as check_corpus
from twin.audit.finetune import facts_of, stated_names, sweep
from twin.eval.cases import Case as Scenario, Check, Run
from twin.eval.grounding import ungrounded
from twin.planner.model import ModelConfig, ModelPlanner, number_tokens

UNCALIBRATED = "uncalibrated"


class Sent:
    """What the stub bus hands back: enough of a receipt for the firm to keep walking."""

    def __init__(self, verb: str, agreement: str) -> None:
        self.verb, self.agreement, self.ok = verb, agreement, True
        self.refusal = None

    def as_dict(self) -> dict[str, Any]:
        return {"verb": self.verb, "ok": self.ok, "state": STATES[self.verb],
                "agreement": self.agreement, "gas_used": 0, "tick": 0, "events": []}


class Ledger:
    """A bus that remembers. No chain, so nothing is journalled and nothing settles.

    The real bus refuses writes the contract rejects; this one accepts every verb, because the
    question scored here is what the firm chose to send, not what the EVM made of it.
    """

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.store = None
        self.user_id = ""
        self.day = 0

    def send(self, verb: str, *, from_role: str, agreement: str = "", **fields: Any) -> Sent:
        self.sent.append({"verb": verb, "from_role": from_role,
                          "to_role": fields.get("to_role", ""),
                          "subject": fields.get("subject", ""),
                          "terms": fields.get("terms", ""),
                          "amount_cents": int(fields.get("amount_cents") or 0)})
        return Sent(verb, agreement or f"0x{len(self.sent):064x}")

    def waiting_on_humans(self) -> list[dict[str, Any]]:
        return []


def review(priors: Priors | None = None) -> tuple[Priors, Firm, list[tuple[Case, list[Finding]]]]:
    """Exercise the legacy sweep and explicit tax, size and finance facts."""
    p = priors or Priors.load()
    firm = Firm(p)
    cases = list(sweep(p))
    for delta in (-1, 1):
        cases.append(replace(
            cases[0], client_geo="DE", claims_small_undertaking=True, supply_in_reduced_category=True,
            standard_vat_rate_percent=p.value("vat_standard_rate_min_percent") + delta,
            reduced_vat_rate_percent=p.value("vat_reduced_rate_min_percent") + delta))
    return p, firm, [(case, firm.review(case)) for case in cases]


class Answer(io.BytesIO):
    def __enter__(self) -> "Answer":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def gateway(text: str) -> Any:
    """An endpoint that answers in both shapes, so whichever is tried first says the same thing."""

    def send(request: Any, timeout: float | None = None) -> Answer:
        payload = {"output": [{"type": "message", "content": [{"text": text}]}],
                   "choices": [{"message": {"content": text}}]}
        return Answer(json.dumps(payload).encode())

    return send


# --------------------------------------------------------------------------- the guards

def a_breach_or_a_silence_opens_nothing(run: Run) -> list[Check]:
    """Only a verdict that permits the work may start an agreement somebody has to sign."""
    p, firm, walked = review(run_priors(run))
    bus = Ledger()
    opened: list[dict[str, Any]] = []
    for case, _ in walked:
        opened += firm.transact(case, bus)["agreements"]
    wrong = [row for row in opened if row["verdict"] not in (CLEAR, HOLD)]
    verbs = {entry["verb"] for entry in bus.sent}
    return [
        Check("the swept cases contain a breach", True,
              any(finding.verdict == BREACH for _, findings in walked for finding in findings)),
        Check("and a silence", True,
              any(finding.verdict == SILENT for _, findings in walked for finding in findings)),
        Check("neither opened an agreement", [], wrong),
        Check("but something was opened", True, len(opened) > 0),
        Check("each one is waiting on a human", {"Attested"}, {row["state"] for row in opened}),
        Check("nothing was settled by an agent", [], [verb for verb in verbs if verb == "settle"]),
        Check("every agreement was accepted by the counterparty", True,
              all(entry["verb"] != "propose" or entry["to_role"] for entry in bus.sent)),
    ]


def _binding_ignores_the_verdict(run: Run) -> Any:
    """Take the verdict out of what counts as binding, and put it back afterwards."""
    holder = Finding.__dict__["binding"]

    def careless(self: Finding) -> bool:
        return True

    Finding.binding = property(careless)
    return lambda: setattr(Finding, "binding", holder)


def a_rule_the_corpus_never_stated_stays_quiet(run: Run) -> list[Check]:
    """Materiality is a standard's judgement, so no agreement may rest on a number for it."""
    p, firm, walked = review(run_priors(run))
    prior = p.prior("materiality_percent_of_turnover")
    materiality = [finding for _, findings in walked for finding in findings
                   if finding.role == "materiality-reviewer"]
    silent_binding = [finding for _, findings in walked for finding in findings
                      if finding.verdict == SILENT and finding.binding]
    invented = [finding for _, findings in walked for finding in findings
                if finding.verdict == SILENT
                and re.search(r"(?<!\d)(\d{1,3})(?![\d])%", finding.sentence)]
    return [
        Check("the corpus states no materiality figure", UNCALIBRATED, prior.get("state")),
        Check("so the role has no value to quote", False, prior.get("value") is not None),
        Check("every materiality finding is silent", True,
              bool(materiality) and all(f.verdict == SILENT for f in materiality)),
        Check("and says the law gave it nothing", True,
              all("no lawful number" in f.sentence or "no turnover" in f.sentence
                  for f in materiality)),
        Check("no silence binds anybody", [], silent_binding),
        Check("no silence quotes a percentage it invented", [], invented),
    ]


def _materiality_invented(run: Run) -> Any:
    """Calibrate the uncalibratable: hand the firm a percentage nobody read out of the law.

    The descriptor is taken from `__dict__` and put back verbatim. Reading it through the class
    gives a bound method or a bare function instead of the classmethod, so a control that
    "restored" it would leave the next scenario measuring the wreckage rather than the code.
    """
    holder = Priors.__dict__["load"]
    shipped = Priors.load().doc

    def load(*args: Any, **kwargs: Any) -> Priors:
        doc = json.loads(json.dumps(shipped))
        prior = doc["priors"]["materiality_percent_of_turnover"]
        prior.update({"value": 1.0, "state": "calibrated", "celex": "32000R0001", "article": "1",
                      "quote": "materiality shall be taken as 1 per cent of net turnover."})
        return Priors(doc)

    Priors.load = staticmethod(load)
    return lambda: setattr(Priors, "load", holder)


def the_words_and_the_verdict_agree_on_one_ratio(run: Run) -> list[Check]:
    """A finding may not print a comfortable ratio and then call it a breach.

    The verdict compares cents; the sentence prints a percentage rounded to two places. Both live
    in the same engagement file, so a reader has to be able to get from one to the other. Three
    claims follow, and each is measured from the cents in `numbers` rather than from whatever
    helper the sentence was built with - otherwise a rounding mistake would be checked by the
    thing it came from:

    the figure printed is the figure the cents give, the verdict is the one the cents give, and
    when the rounded figure lands exactly on the ceiling the sentence shows the cents that
    decided it, because at that point the words alone cannot tell a clear from a breach.
    """
    p, _firm, walked = review(run_priors(run))
    limits = {
        "non-audit-assessor": (p.value("non_audit_fee_cap_percent"), "percent_of_audit_fee",
                               "non_audit_fee_cents", "audit_fee_cents"),
        "fraud-risk-assessor": (p.value("fee_dependence_percent"), "percent_of_firm_fees",
                                "firm_fee_from_client_cents", "firm_total_fees_cents"),
    }
    offenders: list[dict[str, Any]] = []
    seen = {role: set() for role in limits}
    on_the_ceiling = {role: 0 for role in limits}
    for _case, findings in walked:
        for finding in findings:
            if finding.role not in limits:
                continue
            limit, key, part_key, whole_key = limits[finding.role]
            part, whole = finding.numbers.get(part_key), finding.numbers.get(whole_key)
            said, verdict = finding.numbers.get(key), finding.verdict
            seen[finding.role].add(verdict)
            if None in (limit, said, part, whole) or not whole:
                offenders.append({"role": finding.role, "why": "the ratio has no cents behind it"})
                continue
            exact = round(100.0 * part / whole, 2)
            past = part > whole * limit / 100.0
            if said != exact:
                offenders.append({"role": finding.role,
                                  "why": f"it prints {said}% where its own cents give {exact}%"})
            elif f"{said:g}%" not in finding.sentence:
                offenders.append({"role": finding.role,
                                  "why": f"it decided {said}% and filed {finding.sentence!r}"})
            elif (verdict == BREACH) != past:
                offenders.append({"role": finding.role,
                                  "why": f"{part} of {whole} cents is "
                                         f"{'past' if past else 'within'} a {limit:g}% limit and it "
                                         f"says {verdict}"})
            elif said == limit:
                on_the_ceiling[finding.role] += 1
                hidden = [value for value in (part, whole) if str(value) not in finding.sentence]
                if hidden:
                    offenders.append({"role": finding.role,
                                      "why": f"{said}% is the ceiling itself and the sentence "
                                             f"hides {hidden}, which is what decided {verdict}"})
    return [
        Check("no ratio contradicts the cents it was made from", [], offenders),
        Check("the sweep puts a ratio on the ceiling, not only near it", True,
              all(count for count in on_the_ceiling.values())),
        Check("both ratio roles were asked", True, all(seen.values())),
        Check("and each was told both ways", True,
              all(seen[role] >= {CLEAR, BREACH} for role in seen)),
    ]


def _ratios_rounded_to_whole_numbers(run: Run) -> Any:
    """Round the printed ratio to a whole percent, which is where it stops matching the cents."""
    holder = Case.__dict__["dependence_percent"]

    def careless(self: Case) -> float:
        return float(int(round(holder(self))))

    Case.dependence_percent = careless
    return lambda: setattr(Case, "dependence_percent", holder)


def a_weak_match_is_escalated_not_cleared(run: Run) -> list[Check]:
    """One word in common with the prohibition is not permission, and not a breach either."""
    p, _firm, walked = review(run_priors(run))
    asked = [(case, finding) for case, findings in walked
             for finding in findings if finding.role == "independence-monitor"]
    forbidden = [finding for _, finding in asked if finding.verdict == BREACH]
    escalated = [finding for _, finding in asked if finding.verdict == HOLD]
    cleared = [finding for _, finding in asked if finding.verdict == CLEAR]
    to_committee = [finding for finding in escalated + cleared if finding.to_role]
    return [
        Check("a service the list names is refused", True, bool(forbidden)),
        Check("by a point of Article 5(1) it can quote", True,
              all(f.cite.get("point") and f.cite.get("celex") for f in forbidden)),
        Check("a one-word match is held, not cleared", True, bool(escalated)),
        Check("and sent to the committee that decides it", "audit-committee-liaison",
              escalated[0].to_role if escalated else ""),
        Check("a cleared request still goes to the committee", True,
              bool(cleared) and all(f.to_role == "audit-committee-liaison" for f in cleared
                                    if f.verdict == CLEAR and f.numbers.get("requested"))),
        Check("nothing here forbids a service on a single word", True,
              all(len(finding.numbers.get("matches", [])) == 0 or
                  max(entry["words_in_common"] for entry in finding.numbers["matches"]) >= 2
                  for finding in forbidden)),
        Check("every question the firm asks has an owner", True, bool(to_committee)),
    ]


def _match_everything_to_nothing(run: Run) -> Any:
    """Make the matcher blind: every request then shares no word with the prohibition."""
    original = agents.match_service

    def blind(request: str, priors: Priors) -> tuple[dict[str, Any], int]:
        return {}, 0

    agents.match_service = blind
    return lambda: setattr(agents, "match_service", original)


def a_models_sentence_cannot_move_a_threshold(run: Run) -> list[Check]:
    """Muse writes the line. The threshold in it is the one the corpus stated."""
    p, _firm, walked = review(run_priors(run))
    case = next(c for c, _ in walked)
    finding = next(f for _c, findings in walked for f in findings
                   if f.role == "non-audit-assessor")
    cap = p.value("non_audit_fee_cap_percent")
    dishonest = ModelWords(ModelPlanner(
        ModelConfig(base_url="https://models.test/v1", api_key="not-a-key", model="muse-test"),
        opener=gateway(f"The ceiling is {cap + 20} per cent, so this is comfortably clear.")))
    moved = dishonest.phrase(finding, case)
    honest = ModelWords(ModelPlanner(
        ModelConfig(base_url="https://models.test/v1", api_key="not-a-key", model="muse-test"),
        opener=gateway("The work sits at the cap rather than past it.")))
    kept = honest.phrase(finding, case)
    quiet = ModelWords(ModelPlanner(
        ModelConfig(base_url="https://models.test/v1", api_key="not-a-key", model="muse-test"),
        opener=gateway(""))).phrase(finding, case)
    return [
        Check("the invented threshold never reaches the file", True,
              f"{cap + 20:g}" not in moved.sentence),
        Check("the derived one still stands", cap, moved.numbers["cap_percent"]),
        Check("and the fallback is visible in the route", True, moved.route.startswith("rules")),
        Check("a sentence that invents nothing is kept", True, not kept.route.startswith("rules")),
        Check("kept under the model's own route", True, "muse-test" in kept.route),
        Check("a reply with no words in it is a fallback too", True, quiet.route.startswith("rules")),
        Check("the verdict is not the model's to change", finding.verdict, moved.verdict),
    ]


def _numbers_can_be_invented(run: Run) -> Any:
    """Delete the check that every spoken figure was a given figure."""
    holder = ModelPlanner.__dict__["assert_numbers_are_given"]

    def careless(text: str, given: set[str]) -> None:
        return None

    ModelPlanner.assert_numbers_are_given = staticmethod(careless)
    return lambda: setattr(ModelPlanner, "assert_numbers_are_given", holder)


# --------------------------------------------------------------------------- the measures

def run_priors(run: Run) -> Priors:
    """The shipped derivation, once per scenario rather than once per role."""
    if not hasattr(run, "_firm_priors"):
        run._firm_priors = Priors.load()
    return run._firm_priors


def every_figure_in_a_finding_traces_to_a_fact(run: Run) -> list[Check]:
    """The rule route writes the sentences, so this is where the grounding rule is measured.

    `test_finetune.py` holds the same rule for the model's path. Here it is asked of the
    sentences this code formats itself, because a f-string that prints a figure nobody computed
    looks exactly like an honest one on a panel.
    """
    _p, _firm, walked = review(run_priors(run))
    offenders: list[dict[str, Any]] = []
    quoted = 0
    for _case, findings in walked:
        for finding in findings:
            stray = ungrounded(finding.sentence, facts_of(finding))
            quoted += int(bool(number_tokens(finding.sentence)))
            if stray:
                offenders.append({"role": finding.role, "figures": stray,
                                  "sentence": finding.sentence})
    binding_without_a_cite = [finding.role for _c, findings in walked for finding in findings
                              if finding.binding and not (finding.cite.get("celex")
                                                          or finding.cite.get("state"))]
    return [
        Check("no sentence states a figure the case did not produce", [], offenders),
        Check("most of them state at least one", True, quoted >= 60),
        Check("every binding finding names where its rule came from", [], binding_without_a_cite),
    ]


def enforced_thresholds() -> set[str]:
    """Read threshold names from code, excluding absent materiality and contextual figures."""
    source = inspect.getsource(agents)
    read = set(re.findall(r'\.(?:value|cite|prior)\("([a-z_]+)"\)', source))
    context_only = {"materiality_percent_of_turnover", "delegation_period_years",
                    "size_balance_sheet_ceiling_eur", "size_net_turnover_ceiling_eur"}
    return read - context_only


def enforced_provisions(p: Priors) -> set[str]:
    """Which worded sentences the firm reads, taken from the code that reads them.

    Six desks judge from a rule the corpus states in words rather than a figure, and those rules
    are calibrations too: one that no scenario reaches is a rule this firm has never proved it
    applies. The names are matched against what the corpus calibrated, so a string the source
    mentions for some other reason cannot join the roster on its own.
    """
    source = inspect.getsource(agents)
    named = set(re.findall(r'"([a-z_]+)"', source))
    return {name for name in p.provisions if name in named}


def every_threshold_the_firm_enforces_is_exercised(run: Run) -> list[Check]:
    """A derived number no scenario quotes is a number this firm has never proved it applies."""
    p, _firm, walked = review(run_priors(run))
    reached: set[str] = set()
    quoted: set[str] = set()
    for _case, findings in walked:
        for finding in findings:
            reached.update(stated_names(p, finding))
            quote = str(finding.cite.get("quote", ""))
            if quote:
                quoted.add(quote[:300])
    wanted = enforced_thresholds()
    read = enforced_provisions(p)
    # A sentence the corpus stopped stating is the last check's business, not this one's: the desk
    # that answers "the text says nothing here" has exercised its rule exactly as written.
    worded = {name for name in read if p.provision(name)}
    stated = {name for name in worded
              if str((p.provision(name) or {}).get("quote", ""))[:300] in quoted}
    run.rules |= (reached & wanted) | stated
    return [
        Check("every enforced threshold is stated by some finding", sorted(wanted - reached), []),
        Check("every enforced sentence is quoted by some finding", sorted(worded - stated), []),
        Check("the sweep is what reaches them", True,
              len(reached) >= len(wanted) and stated == worded),
        Check("and the corpus really did calibrate them", [],
              [name for name in wanted if p.value(name) is None]
              + [name for name in read if not p.provision(name)]),
    ]


def the_training_corpus_describes_this_firm(run: Run) -> list[Check]:
    """The fine-tuning files are a claim about this code; scored here like any other claim."""
    doc = build_corpus()
    problems = check_corpus(doc)
    meta = doc["meta"]
    counts = meta["counts"]
    return [
        Check("no row states a figure its case denied", [], problems),
        Check("one row per role per case", counts["cases"] * counts["roles"], counts["supervised"]),
        Check("every verdict is taught", True, all(n > 0 for n in meta["verdicts"].values())),
        Check("every role is taught", True,
              {row["role"] for row in meta["rows"]} == {role for role, _ in agents.QUESTIONS}),
        Check("no weight on this machine was trained", False, meta["trained_here"]),
        Check("the rows came from the rule route, not a model", [],
              sorted({row["route"] for row in meta["rows"]} - {"rules"})),
        Check("and from the corpus this deployment ships", p_corpus(), meta["corpus"]),
    ]


def p_corpus() -> dict[str, Any]:
    """The derivation the sidecar says it read, taken from the file the firm reads."""
    return Priors.load().doc.get("derived_from", {})


# --------------------------------------------------------------------------- the registry

FIRM_CASES: tuple[Scenario, ...] = (
    Scenario(
        "breach_or_silence_opens_nothing",
        "a verdict that permits no work starts no agreement anybody has to sign",
        a_breach_or_a_silence_opens_nothing, _binding_ignores_the_verdict),
    Scenario(
        "unstated_rule_stays_quiet",
        "where the corpus stated no number, the firm says so instead of inventing one",
        a_rule_the_corpus_never_stated_stays_quiet, _materiality_invented),
    Scenario(
        "words_and_verdict_agree",
        "the percentage a finding prints is the one its verdict was made against",
        the_words_and_the_verdict_agree_on_one_ratio, _ratios_rounded_to_whole_numbers),
    Scenario(
        "weak_match_is_escalated",
        "one word in common with the prohibition is a question for the committee, not a clearance",
        a_weak_match_is_escalated_not_cleared, _match_everything_to_nothing),
    Scenario(
        "model_cannot_move_a_threshold",
        "Muse may write the sentence; the threshold in it is the one the corpus stated",
        a_models_sentence_cannot_move_a_threshold, _numbers_can_be_invented),
    Scenario(
        "every_figure_traces_to_a_fact",
        "no sentence the firm files states a figure the case did not produce",
        every_figure_in_a_finding_traces_to_a_fact, kind="measure"),
    Scenario(
        "every_enforced_threshold_is_exercised",
        "each number the firm reads out of the priors is quoted by a scenario here",
        every_threshold_the_firm_enforces_is_exercised, kind="measure"),
    Scenario(
        "training_corpus_describes_this_firm",
        "the fine-tuning rows are a true account of this code, not of the code somebody meant",
        the_training_corpus_describes_this_firm, kind="measure"),
)
