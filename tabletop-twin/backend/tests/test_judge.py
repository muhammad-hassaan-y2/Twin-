"""What the model route guarantees, and which guard each refusal came from.

Every test here speaks to `FakeMuse` over a localhost socket with the real harvested statute behind
it, because the claim being tested is a transport claim and a verification claim at once: that a
model's verdict reaches the engagement file when it can be checked, and the firm's own rule reaches
it when it cannot. Nothing here needs a key.

Each guard gets the treatment the rest of this suite uses - the honest judgement, and that judgement
with this one guard bent, showing the failure the guard exists to stop. A guard nobody can turn off
is a guard nobody can trust:

* the vocabulary, so a synonym of a verdict is not read as one;
* the passage id, so a citation names an article this harvest actually has;
* the quote against the passage *that was sent*, so a true sentence the model remembered is refused;
* the figures, so a statutory limit has to have been read rather than invented;
* the facts it claims to have used, and the colleague it claims must act.

What these tests also record, plainly: a judgement that passes every guard is filed even when it
contradicts the deterministic answer. That is the deal this subsystem makes on purpose. The checks
prove the words are in the law and the numbers are the client's; they cannot prove the reading is
right - which is why an agreement still waits for a human signature no route here can produce.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import pytest

from fake_muse import MODEL, FakeMuse
from twin.audit import judge as judge_module
from twin.audit.agents import BREACH, CLEAR, SILENT, QUESTIONS, ROLES, Case, Firm, Finding, Priors
from twin.audit.index import LAW_FILE, CorpusIndex, normalise
from twin.audit.judge import PASSAGES, PASSAGE_CHARS, SENTENCE_CHARS, TOOL, Judge, facts_of
from twin.planner.model import MUSE, RESPONSES, ModelConfig

ANSWERED = "The passage quoted above reaches this engagement, so the firm may proceed."
CRED_VARS = ("META_MODEL_BASE_URL", "META_MODEL_API_KEY", "META_MODEL_NAME", "MODEL_API_KEY",
             "LLM_BASE_URL", "LLM_API_KEY", "LLM_MODEL")


@pytest.fixture(scope="module")
def p():
    return Priors.load()


@pytest.fixture(scope="module")
def index():
    made = CorpusIndex.load()
    assert made.state == "checked", "the harvested text is absent, so no quote could be checked here"
    return made


@pytest.fixture()
def muse(monkeypatch):
    """A live gateway, with exactly one endpoint pointed at it."""
    for name in CRED_VARS:
        monkeypatch.delenv(name, raising=False)
    fake = FakeMuse()
    base = fake.start()
    monkeypatch.setenv("MODEL_API_KEY", "muse-key")
    monkeypatch.setenv("META_MODEL_BASE_URL", base)
    try:
        yield fake
    finally:
        fake.stop()


def engagement(**over) -> Case:
    return Case(client="Northgate Energy PLC", is_pie=True, audit_fee_cents=200_000,
                non_audit_fee_cents=140_000, non_audit_services=("keeping the client's books",),
                turnover_eur=48_000_000.0, balance_sheet_eur=20_000_000.0, employees=300.0,
                years_auditing=9, partner_years=6, tender_held=True, previously_audited=True,
                years_since_previous=4, kyc_checked_years_ago=5, file_retention_years=5,
                firm_fee_from_client_cents=1_800_000, firm_total_fees_cents=9_000_000, **over)


def rule(p: Priors, role: str, case: Case | None = None) -> Finding:
    """The answer the firm gives itself - what every refusal below has to return to."""
    return dict(QUESTIONS)[role](case or engagement(), p)


def judge_for(fake: FakeMuse, made: CorpusIndex) -> Judge:
    config = ModelConfig(base_url=fake.url, api_key="muse-key", model=MODEL, provider=MUSE,
                         api=RESPONSES)
    # `sleeper` is stubbed because one test scripts a rate limit, and a suite should not spend two
    # real seconds proving the client honoured it.
    return Judge(config, made, sleeper=lambda _seconds: None)


@dataclass
class Stage:
    """One role, the passages Muse would be shown for it, and a sentence worth quoting."""

    judge: Judge
    role: str
    base: Finding
    facts: dict
    entry: dict
    quote: str


def stage_for(made: Judge, p: Priors, role: str, position: int = 0) -> Stage:
    case = engagement()
    base = rule(p, role, case)
    facts = facts_of(case)
    passages = made.retrieve(role, base.asks, facts)
    for entry in passages[position:]:
        for sentence in re.split(r"(?<=[.!?]) ", entry["shown"]):
            if len(sentence.strip()) >= 48:
                return Stage(made, role, base, facts, entry, sentence.strip())
    raise AssertionError(f"{role}: retrieval offered no sentence long enough to quote")


@pytest.fixture()
def stage(p, index, muse) -> Stage:
    return stage_for(judge_for(muse, index), p, "rotation-tracker")


def judgement(entry: dict, quote: str, **over) -> dict:
    """A judgement a model could honestly have made - then one field bent, per test."""
    args = {"verdict": CLEAR, "law_id": entry["law_id"], "celex": entry["celex"],
            "article": entry["article"], "quote": quote, "sentence": ANSWERED,
            "relied_on": ["years_auditing"], "asks_of_role": "audit-committee-liaison"}
    return {**args, **over}


def filed(fake: FakeMuse, made: Judge, stage: Stage, args: dict) -> tuple[Finding, str]:
    """Put `args` in Muse's mouth over a socket, and return what was filed and why it was refused."""
    fake.replies.clear()
    fake.responses_tool((TOOL, args))
    finding = made.judge(stage.role, stage.base.asks, stage.facts, lambda: stage.base)
    return finding, str(finding.numbers.get("muse_refused") or "")


# ------------------------------------------------------------------------- who decides

def test_a_checked_judgement_is_filed_with_the_models_own_verdict(p, index, muse):
    """The model's verdict, not the rule's, is what the engagement file says."""
    made = judge_for(muse, index)
    stage = stage_for(made, p, "engagement-partner")
    contrary = BREACH if stage.base.verdict != BREACH else CLEAR
    finding, why = filed(muse, made, stage,
                         judgement(stage.entry, stage.quote, verdict=contrary,
                                   asks_of_role="rotation-tracker"))
    assert why == ""
    assert finding.verdict == contrary, "the model decided nothing; the rule is still speaking"
    assert finding.sentence == ANSWERED and finding.route == made.config.route


def test_the_models_choice_of_colleague_is_what_binds(p, index, muse):
    """`binding` follows the judgement, so the colleague the model names is who the chain asks."""
    made = judge_for(muse, index)
    stage = stage_for(made, p, "tender-administrator")
    clear, _ = filed(muse, made, stage, judgement(stage.entry, stage.quote, verdict=CLEAR))
    assert clear.to_role == "audit-committee-liaison" and clear.binding
    breach, _ = filed(muse, made, stage, judgement(stage.entry, stage.quote, verdict=BREACH))
    assert breach.verdict == BREACH and not breach.binding, "a breach must never propose a deal"


def test_a_filed_citation_carries_the_digest_of_the_article_it_quotes(p, index, muse):
    """The stored finding can be anchored: the article id, its text hash, and a proof to the root."""
    made = judge_for(muse, index)
    stage = stage_for(made, p, "independence-monitor")
    finding, why = filed(muse, made, stage, judgement(stage.entry, stage.quote))
    assert why == ""
    cite = finding.cite
    assert cite["state"] == "verified" and cite["law_id"] == stage.entry["law_id"]
    assert re.fullmatch(r"[0-9a-f]{64}", cite["text_sha256"])
    assert cite["quote"] == stage.quote[:300]
    proof = index.proof({"law_id": cite["law_id"]})
    assert proof["anchored"] and proof["root"] == index.law["root"]


def test_one_review_can_carry_two_authors(p, index, muse):
    """The route belongs to a judgement, not to an engagement.

    A review in which every desk answers the same way cannot tell apart a card that counts
    them separately from one that prints a single route for the whole ask.
    """
    made = judge_for(muse, index)
    refused_at = [position for position in range(len(ROLES)) if position % 3 == 0]
    for position, role in enumerate(ROLES):
        stage = stage_for(made, p, role)
        args = judgement(stage.entry, stage.quote, asks_of_role="")
        if position in refused_at:
            args["quote"] = "a sentence this harvest never printed"
        muse.responses_tool((TOOL, args))
    findings = Firm(p, judge=made).review(engagement())
    refused = [finding for finding in findings if "muse refused" in finding.route]
    decided = [finding for finding in findings if finding.route == made.config.route]
    assert muse.calls == len(ROLES)
    assert len(refused) == len(refused_at) and len(decided) == len(ROLES) - len(refused_at)
    assert all(str(finding.numbers["muse_refused"]) for finding in refused)
    assert all("muse_refused" not in finding.numbers for finding in decided)


# ------------------------------------------------------------------------- the guards


def test_a_verdict_outside_the_four_is_refused(stage, muse):
    finding, why = filed(muse, stage.judge, stage, judgement(stage.entry, stage.quote,
                                                             verdict="violation"))
    assert finding.verdict == stage.base.verdict
    assert "not a verdict this firm recognises" in why


def test_a_citation_that_names_no_passage_is_refused(stage, muse):
    finding, why = filed(muse, stage.judge, stage, judgement(stage.entry, stage.quote, law_id=""))
    assert finding.verdict == stage.base.verdict and "named no passage" in why


def test_a_citation_outside_the_passages_shown_is_refused(stage, muse):
    _finding, why = filed(muse, stage.judge, stage, judgement(stage.entry, stage.quote,
                                                              law_id="law-99999"))
    assert f"law-99999 is not one of the {PASSAGES} passages" in why


def test_a_quote_too_short_to_vouch_for_anything_is_refused(stage, muse):
    _finding, why = filed(muse, stage.judge, stage, judgement(stage.entry, stage.entry["shown"][:20]))
    assert "too short to vouch" in why


def test_a_citation_whose_reference_fights_its_own_id_is_refused(p, index, muse):
    """The id and the printed reference have to agree, or the finding cites two articles at once."""
    made = judge_for(muse, index)
    stage = stage_for(made, p, "audit-committee-liaison")
    other = next(entry for entry in made.retrieve(stage.role, stage.base.asks, stage.facts)
                 if entry["law_id"] != stage.entry["law_id"])
    _finding, why = filed(muse, made, stage, judgement(
        stage.entry, stage.quote, celex=other["celex"], article=other["article"]))
    assert f"but {stage.entry['law_id']} is" in why


def test_a_sentence_that_is_in_no_article_is_refused(stage, muse):
    _finding, why = filed(muse, stage.judge, stage, judgement(
        stage.entry, "Auditors shall refuse any engagement whose total fees exceed nine million euros."))
    assert "does not appear in" in why


def test_a_true_sentence_from_beyond_the_window_is_refused(p, index, muse):
    """The check that separates reading from remembering.

    Article 5 runs past 6 500 characters and only the first PASSAGE_CHARS are sent. A model quoting
    point (1)(j) accurately has not read the passage this firm handed it, and this deployment does not
    claim to have put the Official Journal into a model's weights - so an accurate quote from outside
    the window is refused exactly like an invented one from inside it.
    """
    made = judge_for(muse, index)
    stage = stage_for(made, p, "independence-monitor")
    full = normalise(made.index.find(stage.entry["law_id"]).text)
    assert len(full) > PASSAGE_CHARS, "this control needs a passage longer than the window"
    tail = next(part.strip() for part in re.split(r"(?<=[.!?]) ", full[PASSAGE_CHARS:])
                if len(part.strip()) >= 48)
    assert tail.lower() not in normalise(stage.entry["shown"]).lower()
    finding, why = filed(muse, made, stage, judgement(stage.entry, tail))
    assert finding.verdict == stage.base.verdict
    assert "remembered rather than read" in why


def test_a_figure_that_belongs_to_nobody_is_refused(stage, muse):
    _finding, why = filed(muse, stage.judge, stage, judgement(
        stage.entry, stage.quote, sentence="The 27 percent cap in the quoted point binds."))
    assert "neither the client's nor inside the quote" in why


def test_a_reliance_on_a_fact_never_given_is_refused(stage, muse):
    _finding, why = filed(muse, stage.judge, stage, judgement(
        stage.entry, stage.quote, relied_on=["materiality_percent_of_turnover"]))
    assert "not a fact it was given" in why


def test_a_colleague_that_does_not_exist_is_refused(stage, muse):
    _finding, why = filed(muse, stage.judge, stage, judgement(
        stage.entry, stage.quote, asks_of_role="chief-financial-officer"))
    assert "is not a role of this firm" in why


def test_a_role_cannot_ask_itself_to_act(stage, muse):
    _finding, why = filed(muse, stage.judge, stage, judgement(
        stage.entry, stage.quote, asks_of_role=stage.role))
    assert "cannot ask itself" in why


def test_a_caption_longer_than_a_finding_is_refused(stage, muse):
    _finding, why = filed(muse, stage.judge, stage, judgement(stage.entry, stage.quote,
                                                              sentence="word " * 210))
    assert "longer than a finding caption" in why


def test_a_judgement_with_no_sentence_is_refused(stage, muse):
    _finding, why = filed(muse, stage.judge, stage, judgement(stage.entry, stage.quote, sentence=""))
    assert "carried no sentence" in why


def test_a_caption_exactly_at_the_limit_is_kept(stage, muse):
    """The length guard is a caption rule, not a content rule, so the boundary is tested on the line."""
    finding, why = filed(muse, stage.judge, stage, judgement(stage.entry, stage.quote,
                                                             sentence="a" * SENTENCE_CHARS))
    assert why == "" and finding.sentence == "a" * SENTENCE_CHARS


def test_a_refused_judgement_keeps_none_of_its_own_words(stage, muse):
    """The refused sentence never reaches the file, and the reason is where a reader finds it."""
    lying = judgement(stage.entry, "Auditors shall refuse any engagement whose total fees exceed "
                                   "nine million euros.")
    finding, why = filed(muse, stage.judge, stage, lying)
    assert "nine million" not in finding.sentence
    assert finding.sentence == stage.base.sentence
    assert finding.cite == stage.base.cite, "a refusal cites the rule that answered, not the model"
    assert stage.judge.refusals[-1]["reason"] == why


# ------------------------------------------------------------------------- the guards are load-bearing

def test_removing_the_number_check_lets_an_invented_cap_through(monkeypatch, stage, muse):
    monkeypatch.setattr(judge_module, "_figures_are_given", lambda *ignored: True)
    finding, why = filed(muse, stage.judge, stage, judgement(
        stage.entry, stage.quote, sentence="The 27 percent cap in the quoted point binds."))
    assert why == "" and "27" in finding.sentence


def test_removing_the_citation_check_lets_a_thin_quote_through(monkeypatch, stage, muse):
    """A quote of three words is not evidence, and the check that says so is `index.verify`'s."""
    monkeypatch.setattr(stage.judge.index, "verify", lambda cite: "")
    finding, why = filed(muse, stage.judge, stage, judgement(stage.entry, stage.entry["shown"][:20]))
    assert why == "" and len(finding.cite["quote"]) < 24


def test_widening_the_window_lets_a_remembered_sentence_through(monkeypatch, p, index, muse):
    monkeypatch.setattr(judge_module, "PASSAGE_CHARS", 100_000)
    made = judge_for(muse, index)
    stage = stage_for(made, p, "independence-monitor")
    full = normalise(made.index.find(stage.entry["law_id"]).text)
    tail = next(part.strip() for part in re.split(r"(?<=[.!?]) ", full[PASSAGE_CHARS:])
                if len(part.strip()) >= 48)
    finding, why = filed(muse, made, stage, judgement(stage.entry, tail))
    assert why == "", "the sentence was refused for a reason that is no longer the window"


def test_widening_the_vocabulary_lets_a_synonym_of_a_verdict_through(monkeypatch, stage, muse):
    monkeypatch.setattr(judge_module, "VERDICTS", ("clear", "hold", "breach", "silent", "violation"))
    finding, why = filed(muse, stage.judge, stage, judgement(stage.entry, stage.quote,
                                                             verdict="violation"))
    assert why == "" and finding.verdict == "violation"


def test_adding_a_role_lets_an_invented_colleague_through(stage, muse):
    stage.judge.roles = tuple(stage.judge.roles) + ("chief-financial-officer",)
    finding, why = filed(muse, stage.judge, stage, judgement(
        stage.entry, stage.quote, asks_of_role="chief-financial-officer"))
    assert why == "" and finding.to_role == "chief-financial-officer"


def test_giving_the_model_the_answer_lets_its_reliance_pass(stage, muse):
    stage.facts["materiality_percent_of_turnover"] = 5.0
    finding, why = filed(muse, stage.judge, stage, judgement(
        stage.entry, stage.quote, relied_on=["materiality_percent_of_turnover"]))
    assert why == "", "the check is the membership of that dict, and nothing else"


def test_loosening_the_caption_limit_lets_an_essay_through(monkeypatch, stage, muse):
    monkeypatch.setattr(judge_module, "SENTENCE_CHARS", 100_000)
    finding, why = filed(muse, stage.judge, stage, judgement(stage.entry, stage.quote,
                                                             sentence="word " * 210))
    assert why == "" and len(finding.sentence) > 400


# ------------------------------------------------------------------------- what is in the prompt

def test_no_derived_threshold_reaches_the_prompt(p):
    """A fact list that carried the answers would let a model pass the number check by copying them."""
    given = set(facts_of(engagement()))
    leaked = set(p.doc.get("priors") or {}) & given
    assert not leaked, f"the prompt would have stated the answer {sorted(leaked)}"
    assert {"client", "is_pie", "years_auditing"} <= given


def test_every_question_gets_its_own_passages(p, index, muse):
    """The query is the question, not the client's file.

    Appending the fact keys and values was tried and measured: every role came back with the same
    three articles, because an engagement file is written in the same vocabulary as the statute that
    governs it. This is the control that notices if that ever comes back.
    """
    made = judge_for(muse, index)
    seen = []
    for role in ROLES:
        passages = made.retrieve(role, rule(p, role).asks, facts_of(engagement()))
        assert len(passages) == PASSAGES
        seen.append(frozenset(entry["law_id"] for entry in passages))
    assert len(set(seen)) >= 8, "retrieval has stopped distinguishing the questions"


def test_the_law_block_carries_the_ids_and_the_words_they_are_checked_against(p, index, muse):
    made = judge_for(muse, index)
    asked = rule(p, "quality-review-partner").asks
    facts = facts_of(engagement())
    passages = made.retrieve("quality-review-partner", asked, facts)
    text = made.ask_text(asked, facts, passages)
    assert f"QUESTION: {asked}" in text
    for entry in passages:
        assert f"[{entry['law_id']}] {entry['ref']}" in text
        assert entry["shown"][:80] in text


# ------------------------------------------------------------------------- the transport

def test_a_review_asks_once_per_role_and_files_twelve_judgements(p, index, muse):
    made = judge_for(muse, index)
    case = engagement()
    for role in ROLES:
        stage = stage_for(made, p, role)
        muse.responses_tool((TOOL, judgement(stage.entry, stage.quote, asks_of_role="")))
    findings = Firm(p, judge=made).review(case)
    assert len(findings) == len(ROLES) and muse.calls == len(ROLES)
    assert all(f.route == made.config.route for f in findings), [f.route for f in findings]
    assert all(f.cite.get("state") == "verified" for f in findings)
    assert made.refusals == []


def test_a_silent_endpoint_leaves_the_rules_answering_and_says_so(p, index, muse):
    made = judge_for(muse, index)
    stage = stage_for(made, p, "evidence-archivist")
    finding = made.judge(stage.role, stage.base.asks, stage.facts, lambda: stage.base)
    assert finding.verdict == stage.base.verdict and "muse did not answer" in finding.route
    assert muse.calls == 2, "a 500 is asked twice, never three times"
    assert "muse_refused" not in finding.numbers, "an endpoint that never spoke is not a refusal"


def test_a_refused_credential_is_not_asked_twice(p, index, muse):
    made = judge_for(muse, index)
    muse.refuse(401, detail="Invalid API key provided")
    stage = stage_for(made, p, "aml-compliance-officer")
    finding = made.judge(stage.role, stage.base.asks, stage.facts, lambda: stage.base)
    assert finding.verdict == stage.base.verdict and "refused the credential" in finding.route
    assert muse.calls == 1


def test_a_refused_request_shape_is_asked_again_the_other_way(p, index, muse):
    """Meta does not publish the tool-definition shape for /v1/responses, so the chat shape answers.

    The answer scripted below is chat-shaped, which the gateway refuses over /v1/responses with a
    400. The route then has to name the shape that actually replied, because a report that names the
    wrong one is a report nobody can act on.
    """
    made = judge_for(muse, index)
    stage = stage_for(made, p, "group-audit-coordinator")
    muse.tool(TOOL, judgement(stage.entry, stage.quote))
    finding = made.judge(stage.role, stage.base.asks, stage.facts, lambda: stage.base)
    assert finding.sentence == ANSWERED
    assert finding.route == f"{made.config.route} via chat", finding.route
    assert muse.calls == 2 and made.attempts == 2


def test_a_judgement_delivered_as_prose_is_still_checked(p, index, muse):
    """`tool_choice` is only ever sent as the value Meta states both shapes accept, so prose happens."""
    made = judge_for(muse, index)
    stage = stage_for(made, p, "fraud-risk-assessor")
    muse.responses_narration("Sure. " + json.dumps(judgement(stage.entry, stage.quote)) + " done.")
    finding = made.judge(stage.role, stage.base.asks, stage.facts, lambda: stage.base)
    assert finding.sentence == ANSWERED and finding.route == made.config.route
    assert muse.calls == 1, "a prose judgement is read, not re-asked"


def test_silence_is_a_complete_answer_and_buys_no_second_request(p, index, muse):
    made = judge_for(muse, index)
    stage = stage_for(made, p, "materiality-reviewer")
    finding, why = filed(muse, made, stage, judgement(
        stage.entry, stage.quote, verdict=SILENT,
        sentence="These passages state no threshold for materiality, so the firm has no figure here."))
    assert finding.verdict == SILENT and why == "" and made.refusals == []
    assert muse.calls == 1, "a silent answer is a complete answer, not a reason to ask again"


def test_with_nothing_to_check_against_nothing_is_asked(p, muse):
    """Hashes without text cannot check a quote, so the endpoint is never called.

    This is the fresh-clone case: `law.json` is tracked and the corpus text is not. A deployment that
    reported "muse:muse-spark-1.3" here would be reporting a route it had never verified.
    """
    hashed = CorpusIndex(json.loads(LAW_FILE.read_text(encoding="utf-8")), statutes=[])
    assert hashed.state == "hashed" and hashed.counts()["with_text"] == 0
    made = judge_for(muse, hashed)
    base = rule(p, "engagement-partner")
    finding = made.judge(base.role, base.asks, facts_of(engagement()), lambda: base)
    assert muse.calls == 0
    assert "no quote could have been checked" in finding.route
    assert finding.verdict == base.verdict


def test_no_key_means_the_firm_never_reaches_for_a_model(p, monkeypatch):
    for name in CRED_VARS:
        monkeypatch.delenv(name, raising=False)
    assert Judge.from_env() is None
    firm = Firm(p)
    assert firm.judge is None
    assert all(f.route == "rules" for f in firm.review(engagement()))
    assert firm.describe()["route"] == "rules"
