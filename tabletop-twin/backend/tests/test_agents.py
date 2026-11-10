"""Twenty-six roles, one question each, and no figure the harvested text did not state.

These tests read like the firm does: a verdict is only worth anything next to the run that
avoids it. Every threshold here is taken from `priors.json` and a case is built one year or one
cent on either side of it, so an amendment that moves a ceiling moves the test with it instead of
turning a green suite into a lie. The two exceptions are deliberate: the materiality percentage
must stay absent from the corpus for the silence test to mean anything, and a fabricated prior is
injected to prove that the silence is derived rather than written.

What this file does not test: that the chain enforces anything. That is `test_a2a.py`. And that
the corpus was parsed correctly - that is `test_priors.py`, and the two layers must be allowed to
fail separately.
"""

from __future__ import annotations

import io
import json
import os
import tempfile
from pathlib import Path

import pytest

from twin.audit import agents
from twin.audit.a2a import Bus
from twin.audit.agents import (BREACH, CLEAR, HOLD, SILENT, QUESTIONS, ROLES, Case, Firm, Finding,
                               ModelWords, Priors, RuleWords, _derogation, _letters, match_service)
from twin.audit.chain import spawn_sidecar
from twin.planner.model import ModelConfig, ModelPlanner, number_tokens
from twin.store import Store

USER = "test-firm"
CORPUS_NUMBERS = (
    "rotation_initial_max_years", "rotation_tendered_max_years", "rotation_with_tender_max_years",
    "key_partner_rotation_years", "partner_cooling_off_years", "auditor_return_cooldown_years",
    "non_audit_fee_cap_percent", "fee_dependence_percent", "participation_presumed_percent",
    "aml_record_retention_years", "non_audit_lookback_years",
    "transparency_report_deadline_months", "transparency_report_available_years",
)
# The desks whose rule the corpus states in words and not in a figure. Each has to stay quotable:
# a provision that falls out of the harvest has to fail here rather than turn six verdicts into
# silences that look like a quiet file.
CORPUS_PROVISIONS = (
    "contingent_audit_fees", "contingent_audit_fees_directive", "additional_report_to_committee",
    "public_register_particulars", "sustainability_service_prohibition",
)


@pytest.fixture(scope="module")
def p():
    """The derived priors, under the one name the firm's own code gives them."""
    p = Priors.load()
    absent = [name for name in CORPUS_NUMBERS if p.value(name) is None]
    assert not absent, f"the corpus no longer states {absent}: re-run python -m twin.audit.calibrate"
    mute = [name for name in CORPUS_PROVISIONS if p.provision(name).get("state") != "quoted"]
    assert not mute, f"the corpus no longer states {mute} in words: re-run the calibration"
    assert p.value("materiality_percent_of_turnover") is None, (
        "the corpus now states a materiality percentage: the silence below needs a new control")
    return p


@pytest.fixture(scope="module")
def chain():
    box = tempfile.mkdtemp(prefix="twin-agents-")
    with spawn_sidecar(journal=os.path.join(box, "firm.journal.jsonl"), wait_sec=120.0) as running:
        receipts = running.register_roles()
        assert len(receipts) == len(ROLES) and all(r.ok for r in receipts), (
            "the firm cannot speak for an agent the registry never hired")
        assert len(running.roles()["agents"]) == len(ROLES)
        yield running


@pytest.fixture()
def store():
    made = Store.temporary()
    try:
        yield made
    finally:
        made.close()


def clean(p: Priors, **over) -> Case:
    """An engagement that sits exactly on each derived figure and so breaches none of them.

    The worded rules are answered the same way as the numbered ones: the register particulars come
    out of the provision, not out of a list written here, so an amendment that adds a fourth
    particular moves this case rather than silently passing a partial entry.
    """
    cap = p.value("non_audit_fee_cap_percent")
    floor = p.value("fee_dependence_percent")
    retention = int(p.value("aml_record_retention_years"))
    lookback = int(p.value("non_audit_lookback_years"))
    deadline = int(p.value("transparency_report_deadline_months"))
    kept = int(p.value("transparency_report_available_years"))
    particulars = tuple(p.provision("public_register_particulars").get("points") or ())
    base = {
        "client": "Northgate Energy PLC", "is_pie": True,
        "audit_fee_cents": 200_000,
        "non_audit_fee_cents": int(200_000 * cap / 100.0),
        "non_audit_services": ("translating the client's handbook into French",),
        "turnover_eur": 48_000_000.0, "balance_sheet_eur": 20_000_000.0, "employees": 300.0,
        "years_auditing": int(p.value("rotation_initial_max_years")),
        "partner_years": int(p.value("key_partner_rotation_years")),
        "previously_audited": True,
        "years_since_previous": int(p.value("partner_cooling_off_years")),
        "tender_held": True,
        "firm_fee_from_client_cents": int(9_000_000 * floor / 100.0), "firm_total_fees_cents": 9_000_000,
        "kyc_checked_years_ago": retention, "file_retention_years": retention,
        "fee_arrangement": "fixed in advance", "non_audit_years": max(lookback - 1, 0),
        "months_since_year_end": max(deadline - 2, 0), "transparency_published": True,
        "transparency_kept_years": kept, "audit_report_issued": True, "committee_report_issued": True,
        "register_status": "registered", "register_particulars": particulars,
    }
    return Case(**{**base, **over})


def one(p: Priors, role: str, **over) -> Finding:
    return next(f for f in Firm(p).review(clean(p, **over)) if f.role == role)


def figures(finding: Finding) -> set[str]:
    """Every number this finding was allowed to speak: its own arithmetic and its own citation."""
    given = number_tokens(json.dumps(finding.numbers, sort_keys=True))
    return given | number_tokens(json.dumps(finding.cite, sort_keys=True))


# --------------------------------------------------------------------- the arithmetic

def test_the_tenure_rule_reads_three_ceilings_and_not_one(p):
    initial = int(p.value("rotation_initial_max_years"))
    tendered = int(p.value("rotation_tendered_max_years"))
    outer = int(p.value("rotation_with_tender_max_years"))
    firm = Firm(p)

    at_initial = one(p, "engagement-partner", years_auditing=initial)
    assert at_initial.verdict == CLEAR

    past_initial = one(p, "engagement-partner", years_auditing=initial + 1, tender_held=False)
    assert past_initial.verdict == BREACH and not past_initial.binding
    assert str(initial) in past_initial.sentence

    # Between the two extensions the file has to say something the case does not: which kind
    # of tender it was. That is a hold, and a hold that binds somebody.
    between = one(p, "engagement-partner", years_auditing=tendered + 1, tender_held=True)
    assert between.verdict == HOLD and between.binding
    assert between.to_role == "audit-committee-liaison"
    assert str(tendered) in between.sentence and str(outer) in between.sentence

    past_outer = one(p, "engagement-partner", years_auditing=outer + 1, tender_held=True)
    assert past_outer.verdict == BREACH
    assert float(p.cite("rotation_with_tender_max_years")["value"]) == outer

    # Control on the tiers themselves: they are three different numbers in the text, and a
    # firm that read only two of them would have called the between-case a breach.
    assert initial < tendered < outer


def test_the_partner_clock_and_the_gap_the_clients_kind_sets(p):
    rotate = int(p.value("key_partner_rotation_years"))
    partner_gap = int(p.value("partner_cooling_off_years"))
    general_gap = int(p.value("auditor_return_cooldown_years"))

    assert one(p, "rotation-tracker", partner_years=rotate).verdict == CLEAR
    late = one(p, "rotation-tracker", partner_years=rotate + 1)
    assert late.verdict == BREACH and str(rotate) in late.sentence

    returned = one(p, "rotation-tracker", previously_audited=True, years_since_previous=partner_gap - 1)
    assert returned.verdict == BREACH and returned.cite["celex"] == p.cite("partner_cooling_off_years")["celex"]
    # The sentence the Regulation uses has no "at least" in it, so the rule that found this
    # number could not have been the one that found the Directive's.
    assert returned.cite["celex"] != p.cite("auditor_return_cooldown_years")["celex"]

    settled = one(p, "rotation-tracker", previously_audited=True, years_since_previous=partner_gap)
    assert settled.verdict == CLEAR and "gap" in settled.sentence

    # A client that is not a public-interest entity is measured by the Directive's floor, which
    # is the smaller of the two - so the same run has to be read against a different article.
    elsewhere = one(p, "rotation-tracker", is_pie=False, previously_audited=True,
                    years_since_previous=general_gap - 1)
    assert elsewhere.verdict == BREACH
    assert elsewhere.cite["celex"] == p.cite("auditor_return_cooldown_years")["celex"]


def test_the_fee_cap_and_the_dependence_floor_are_the_same_arithmetic_twice(p):
    cap = p.value("non_audit_fee_cap_percent")
    allowed = int(200_000 * cap / 100.0)
    at = one(p, "non-audit-assessor", non_audit_fee_cents=allowed)
    over = one(p, "non-audit-assessor", non_audit_fee_cents=allowed + 1)
    assert (at.verdict, over.verdict) == (CLEAR, BREACH)
    assert at.binding and not over.binding, "a breach opens no agreement for a person to sign"
    assert float(over.cite["value"]) == cap

    floor = p.value("fee_dependence_percent")
    firm_total = 9_000_000
    dependent = one(p, "fraud-risk-assessor", firm_total_fees_cents=firm_total,
                    firm_fee_from_client_cents=int(firm_total * floor / 100.0) + 1)
    assert dependent.verdict == BREACH
    assert one(p, "fraud-risk-assessor", firm_total_fees_cents=firm_total,
               firm_fee_from_client_cents=int(firm_total * floor / 100.0)).verdict == CLEAR


def test_an_empty_ledger_is_not_a_zero_ratio(p):
    """A fee the file never stated is not a fee of zero, and does not bind anybody either."""
    no_fees = one(p, "non-audit-assessor", audit_fee_cents=0)
    assert no_fees.verdict == SILENT and not no_fees.binding
    no_ledger = one(p, "fraud-risk-assessor", firm_total_fees_cents=0)
    assert no_ledger.verdict == SILENT
    no_policy = one(p, "evidence-archivist", file_retention_years=0)
    assert no_policy.verdict == SILENT
    assert one(p, "evidence-archivist", file_retention_years=1).verdict == BREACH


# ------------------------------------------------------------------- the prohibition

def test_the_prohibition_is_read_out_of_the_statute_and_not_off_a_card(p):
    categories = {c["letter"]: c for c in p.services["categories"]}
    assert list(categories) == [chr(letter) for letter in range(ord("a"), ord("k") + 1)], (
        "Article 5(1) stopped walking at " + ",".join(categories))

    bookkeeping = categories["c"]["text"].rstrip("; ")
    finding = one(p, "independence-monitor", non_audit_services=(bookkeeping,))
    assert finding.verdict == BREACH and not finding.binding
    matched = finding.numbers["matches"][0]
    assert matched["point"] == "c" and matched["words_in_common"] >= 2
    assert finding.cite["point"] == "c"
    # The derogation in 5(3) names sub-points of (a) and nothing under (c), so a firm that
    # quoted a waiver here would be quoting a permission that does not exist.
    assert _derogation(p, "c") == []

    tax = one(p, "independence-monitor", non_audit_services=(categories["a"]["text"].rstrip(": "),))
    assert tax.verdict == BREACH and tax.numbers["matches"][0]["point"] == "a"
    assert "derogate" in tax.sentence, "the waiver is part of the rule, so it belongs in the line"
    assert _derogation(p, "a"), "and it has to be a waiver the text really names"

    # Control: the same category on a client the Article does not reach.
    not_pie = one(p, "independence-monitor", is_pie=False, non_audit_services=(bookkeeping,))
    assert not_pie.verdict == CLEAR and "public-interest" in not_pie.sentence


def test_a_weak_word_match_is_a_question_not_an_answer(p):
    """One word in common is how a false positive is made, so it is escalated instead of judged."""
    almost = one(p, "independence-monitor", non_audit_services=("bookkeeping of the ledgers",))
    category, score = match_service("bookkeeping of the ledgers", p)
    assert score == 1 and category["letter"] == "c"
    assert almost.verdict == HOLD and almost.binding and almost.to_role == "audit-committee-liaison"

    nothing = one(p, "independence-monitor",
                  non_audit_services=("translating the client's handbook into French",))
    assert match_service("translating the client's handbook into French", p)[1] == 0
    assert nothing.verdict == CLEAR and nothing.binding
    # A service the prohibition does not name still needs the committee's approval, so the
    # monitor's clear and the liaison's hold are the same decision seen from two desks.
    liaison = one(p, "audit-committee-liaison", non_audit_services=("tax advice",))
    assert liaison.verdict == HOLD and liaison.cite["point"] == "4"
    assert one(p, "audit-committee-liaison", is_pie=False, non_audit_services=("tax advice",)).verdict == SILENT


# ------------------------------------------------------------------------ the silences

def test_a_silent_role_is_the_corpus_being_quiet_not_the_agent_being_lazy(p):
    assert "materiality_percent_of_turnover" in p.uncalibrated()
    silent = one(p, "materiality-reviewer")
    assert silent.verdict == SILENT and not silent.binding
    assert silent.numbers["state"] == "uncalibrated"

    # Negative control: give the same agent a calibrated prior and it stops being silent and
    # starts doing arithmetic - which is the only thing it is allowed to do with a number.
    doc = json.loads(json.dumps(p.doc))
    doc["priors"]["materiality_percent_of_turnover"] = {
        "value": 5.0, "state": "calibrated", "celex": "32000R0000", "article": "9",
        "quote": "materiality of 5 per cent of turnover", "unit": "percent",
    }
    with_number = Firm(Priors(doc)).review(clean(p))
    found = next(f for f in with_number if f.role == "materiality-reviewer")
    assert found.verdict == HOLD and found.binding
    assert found.numbers["materiality_eur"] == pytest.approx(48_000_000.0 * 5.0 / 100.0)
    assert f"{found.numbers['materiality_eur']:,.0f}" in found.sentence


def test_a_finding_cannot_quote_a_number_it_was_not_given(p):
    """The prose may restate the arithmetic; it may not add to it.

    Article and CELEX figures are allowed because a citation is provenance rather than a
    calculation, and they arrive from the same dict the verdict was drawn from.
    """
    cases = [
        clean(p),
        clean(p, years_auditing=int(p.value("rotation_with_tender_max_years")) + 2,
              partner_years=int(p.value("key_partner_rotation_years")) + 4,
              previously_audited=True, years_since_previous=0, is_pie=False),
        clean(p, non_audit_services=("bookkeeping and preparing accounting records", "valuation of shares"),
              non_audit_fee_cents=199_000, parent_holding_percent=80.0),
        clean(p, audit_fee_cents=0, firm_total_fees_cents=0, file_retention_years=0,
              non_audit_services=()),
        clean(p, non_audit_years=int(p.value("non_audit_lookback_years")),
              prior_audit_fees_cents=(200_000, 200_000, 200_000),
              prior_non_audit_fees_cents=(199_000, 199_000, 199_000),
              months_since_year_end=12, transparency_published=False, transparency_kept_years=0,
              audit_report_issued=False, committee_report_issued=False, register_status="",
              register_particulars=(), fee_arrangement="contingent on the outcome of the transaction",
              sustainability_assurance=True),
    ]
    for case in cases:
        for finding in Firm(p).review(case):
            stray = number_tokens(finding.sentence) - figures(finding)
            assert not stray, f"{finding.role} said {sorted(stray)} that its own figures do not hold"


# ------------------------------------------------------- the desks that read words, not figures

def without_provision(p: Priors, name: str) -> Priors:
    """The same priors with one quoted sentence taken out of the harvest.

    Each of these six desks has a guard whose whole job is to notice that the corpus stopped
    stating its rule, and a guard like that is only proven by deleting what it guards against.
    """
    doc = json.loads(json.dumps(p.doc))
    doc["provisions"][name] = {"state": "not_in_corpus", "quote": ""}
    return Priors(doc)


def test_a_fee_that_hinges_on_the_result_is_refused_at_both_layers(p):
    """Article 4(1) for the client the Regulation reaches, Article 25 for the one it does not."""
    contingent = one(p, "contingent-fee-reviewer", fee_arrangement="contingent on the deal closing")
    assert contingent.verdict == BREACH and not contingent.binding, "a forbidden fee opens nothing"
    assert (contingent.cite["celex"], contingent.cite["article"]) == ("32014R0537", "4")

    # The Directive obliges Member States to keep the same rule for every statutory audit, so a
    # non-public-interest client gets an answer instead of a shrug - and it is a different article.
    other = one(p, "contingent-fee-reviewer", is_pie=False, fee_arrangement="a share of the tax saved")
    assert (other.cite["celex"], other.cite["article"]) == ("32006L0043", "25")
    assert other.verdict == CLEAR

    # Stating what a client pays is not stating how the figure was arrived at.
    quiet = one(p, "contingent-fee-reviewer", fee_arrangement="")
    assert quiet.verdict == SILENT and quiet.numbers["fee_arrangement"] == "not stated"
    assert "will not read a silence" in quiet.sentence

    # Control: with the sentence gone the desk has no wording to test, and says so.
    mute = next(f for f in Firm(without_provision(p, "contingent_audit_fees")).review(
        clean(p, fee_arrangement="contingent on the deal closing")) if f.role == "contingent-fee-reviewer")
    assert mute.verdict == SILENT and "no sentence" in mute.sentence


def test_the_multi_year_ceiling_waits_for_the_years_it_averages_over(p):
    """Article 4(2) is a mean, so a file with too few years in it is a hold, not a clear."""
    need = int(p.value("non_audit_lookback_years"))
    cap = p.value("non_audit_fee_cap_percent")
    at_cap = int(round(200_000 * cap / 100.0))

    early = one(p, "multi-year-fee-reviewer")
    assert early.verdict == CLEAR and early.numbers["years_until_ceiling"] == 1
    assert early.numbers["lookback_years"] == p.value("non_audit_lookback_years")

    thin = one(p, "multi-year-fee-reviewer", non_audit_years=need, prior_audit_fees_cents=(200_000,))
    assert thin.verdict == HOLD and thin.binding and thin.to_role == "engagement-partner"
    assert thin.numbers["years_stated"] == {"audit": 1, "non_audit": 0}

    inside = one(p, "multi-year-fee-reviewer", non_audit_years=need,
                 prior_audit_fees_cents=(200_000,) * need,
                 prior_non_audit_fees_cents=(at_cap,) * need)
    assert inside.verdict == CLEAR and inside.numbers["allowed_average_cents"] == at_cap
    # One cent is the whole distance between the two verdicts, and it is the same one cent the
    # single-year cap is measured with, because the derived figure is the same 70 in both.
    over = one(p, "multi-year-fee-reviewer", non_audit_years=need,
               prior_audit_fees_cents=(200_000,) * need,
               prior_non_audit_fees_cents=(at_cap + 1,) * need)
    assert over.verdict == BREACH and not over.binding
    assert over.numbers["average_non_audit_fee_cents"] == at_cap + 1


def test_the_transparency_clock_runs_on_the_firm_not_on_the_client(p):
    deadline = int(p.value("transparency_report_deadline_months"))
    floor = int(p.value("transparency_report_available_years"))

    late = one(p, "transparency-report-reviewer", transparency_published=False,
               months_since_year_end=deadline)
    assert late.verdict == BREACH and not late.binding
    still_time = one(p, "transparency-report-reviewer", transparency_published=False,
                     months_since_year_end=0)
    assert still_time.verdict == HOLD and still_time.binding
    assert still_time.numbers["months_left"] == deadline

    short = one(p, "transparency-report-reviewer", transparency_kept_years=max(floor - 1, 0))
    assert short.verdict == BREACH
    unbounded = one(p, "transparency-report-reviewer", transparency_kept_years=0)
    assert unbounded.verdict == HOLD and unbounded.to_role == "quality-review-partner", (
        "published is not the same question as kept, and a file that answers one is held on the other")

    # Article 13 binds a firm whose audit client is a public-interest entity, and that is the end
    # of the rule for this engagement rather than a licence to assume the answer.
    assert one(p, "transparency-report-reviewer", is_pie=False).verdict == SILENT


def test_the_committee_report_is_late_only_against_the_audit_report(p):
    """Article 11 sets no date, so this desk cannot answer until the file says what was issued."""
    after = one(p, "committee-report-reviewer", committee_report_issued=False, audit_report_issued=True)
    assert after.verdict == BREACH and not after.binding
    neither = one(p, "committee-report-reviewer", committee_report_issued=False, audit_report_issued=False)
    assert neither.verdict == HOLD and neither.to_role == "audit-committee-liaison"
    assert one(p, "committee-report-reviewer", is_pie=False).verdict == SILENT
    mute = next(f for f in Firm(without_provision(p, "additional_report_to_committee")).review(
        clean(p, committee_report_issued=False, audit_report_issued=True))
        if f.role == "committee-report-reviewer")
    assert mute.verdict == SILENT, "a deadline the corpus stopped stating is not a passed deadline"


def test_the_register_desk_counts_the_particulars_the_article_prints(p):
    required = list(p.provision("public_register_particulars")["points"])
    assert required, "the lettered list has to be readable out of Article 16"

    partial = one(p, "register-entry-reviewer", register_particulars=tuple(required[:-1]))
    assert partial.verdict == HOLD and partial.binding
    assert partial.numbers["particulars_missing"] == [required[-1]]

    gone = one(p, "register-entry-reviewer", register_status="struck off")
    assert gone.verdict == BREACH and not gone.binding
    blank = one(p, "register-entry-reviewer", register_status="")
    assert blank.verdict == SILENT, "this firm's own register entry is a fact the file has to state"

    # Control: an entry that states the three letters is only clear because the text lists three.
    # Give the same case an unreadable list and completeness becomes somebody's job again.
    doc = json.loads(json.dumps(p.doc))
    doc["provisions"]["public_register_particulars"]["points"] = []
    blind = next(f for f in Firm(Priors(doc)).review(clean(p)) if f.role == "register-entry-reviewer")
    assert blind.verdict == HOLD and blind.to_role == "quality-review-partner"


def test_the_assurance_desk_carries_only_the_points_the_text_carries(p):
    """Article 25c repeats part of the Article 5(1) list, so it cannot be that list from memory."""
    prohibited = list(p.provision("sustainability_service_prohibition")["points"])
    categories = {c["letter"]: c for c in p.services["categories"]}
    assert prohibited and set(prohibited) < set(categories), (
        "the subset has to be a subset, or the two desks are the same desk")

    inside = categories[prohibited[0]]["text"].rstrip("; :.")
    assured = one(p, "sustainability-assurance-reviewer", sustainability_assurance=True,
                  non_audit_services=(inside,))
    assert assured.verdict == BREACH and not assured.binding
    assert assured.numbers["matches"][0]["point"] == prohibited[0]

    outside_letter = sorted(set(categories) - set(prohibited))[0]
    allowed = one(p, "sustainability-assurance-reviewer", sustainability_assurance=True,
                  non_audit_services=(categories[outside_letter]["text"].rstrip("; :."),))
    assert allowed.verdict == CLEAR and allowed.binding
    assert f"points {_letters(prohibited)}" in allowed.sentence
    # The same service asked at the independence desk is a different question with a different
    # answer, and that is the text's doing, not this firm's: 25c carries a subset of 5(1).
    elsewhere = categories[outside_letter]["text"].rstrip("; :.")
    assert one(p, "independence-monitor", non_audit_services=(elsewhere,)).verdict == BREACH

    # A firm that assures nothing has no Article 25c engagement to check, which is a different
    # fact from an engagement that passes, and the two must not print the same line.
    plain = one(p, "sustainability-assurance-reviewer", non_audit_services=(inside,))
    assert plain.verdict == SILENT and plain.numbers["sustainability_assurance"] is False
    assert one(p, "sustainability-assurance-reviewer", sustainability_assurance=True,
               non_audit_services=()).verdict == CLEAR


# ------------------------------------------------------------------ the twenty-six desks

def test_the_roles_are_the_agents_the_chain_will_answer(p):
    roster = json.loads((Path(__file__).resolve().parents[2] / "chain" / "roster.json")
                        .read_text(encoding="utf-8"))
    assert set(ROLES) == {agent["role"] for agent in roster["agents"]}
    assert len(ROLES) == len(QUESTIONS) == len(roster["agents"]) == 26
    assert [role for role, _ in agents.QUESTIONS] == list(ROLES)

    firm = Firm(p)
    findings = firm.review(clean(p))
    assert [f.role for f in findings] == list(ROLES)
    assert all(f.role and f.asks and f.verdict in (CLEAR, BREACH, HOLD, SILENT) for f in findings)
    assert all(f.numbers for f in findings), "a verdict with no figures cannot be checked"
    assert sum(1 for f in findings if f.verdict == SILENT) >= 1, (
        "a firm that answers every question has invented an answer for at least one")


def test_a_review_that_answers_as_the_wrong_role_is_a_bug_not_a_finding(p, monkeypatch):
    def imposter(case, priors):
        return Finding("rotation-tracker", "answered from the wrong desk", CLEAR, "seven years")

    monkeypatch.setattr(agents, "QUESTIONS", (("engagement-partner", imposter),))
    with pytest.raises(AssertionError, match="answered as rotation-tracker"):
        Firm(p).review(clean(p))


# ------------------------------------------------------------------------- the words

class Inkwell:
    """A planner that says the line it was handed, so the words layer can be watched alone."""

    def __init__(self, text: str, route: str):
        self.text, self.last_route, self.route = text, route, route
        self.facts: list = []

    def narrate(self, ask, results, context=None, on_delta=None):
        self.facts = results
        return self.text


class Answer(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def gateway(text: str):
    """An endpoint that answers in both shapes, so whichever one is tried first says it."""

    def send(request, timeout=None):
        payload = {"output": [{"type": "message", "content": [{"text": text}]}],
                   "choices": [{"message": {"content": text}}]}
        return Answer(json.dumps(payload).encode())

    return send


def test_a_model_writes_the_sentence_and_cannot_move_the_threshold(p):
    honest = Inkwell("Non-audit work is 70% of the audit fee, which is the ceiling.", "responses:muse-test")
    finding = ModelWords(honest).phrase(one(p, "non-audit-assessor"), clean(p))
    assert finding.sentence == honest.text and finding.route == "responses:muse-test"
    assert finding.verdict == CLEAR and finding.binding, "the words changed, the decision did not"
    assert json.loads(json.dumps(honest.facts[0], sort_keys=True))["cap_percent"] == (
        p.value("non_audit_fee_cap_percent"))

    # A planner that only repeats the line it was given cannot be used to prove the guard, so
    # the guard is run end to end through the real one, which checks every number in the reply
    # against the figures it was handed. The fallback has to be visible in the route: a
    # sentence that quietly stopped coming from the model is a bug report nobody reads.
    planner = ModelPlanner(ModelConfig(base_url="https://models.example/v1", api_key="not-a-key",
                                       model="muse-test"), opener=gateway("The cap is 90 per cent."))
    checked = ModelWords(planner).phrase(one(p, "non-audit-assessor"), clean(p))
    assert checked.route.startswith("rules"), checked.route
    assert "never computed" in checked.route and "90" in checked.route, checked.route
    assert "90" not in checked.sentence
    assert checked.numbers["cap_percent"] == p.value("non_audit_fee_cap_percent")

    # Control on the same path: a reply that only restates the figures it was handed is kept,
    # and kept under the model's own route.
    plain = ModelPlanner(ModelConfig(base_url="https://models.example/v1", api_key="not-a-key",
                                     model="muse-test"),
                         opener=gateway("The work sits at the 70 per cent ceiling."))
    kept = ModelWords(plain).phrase(one(p, "non-audit-assessor"), clean(p))
    assert not kept.route.startswith("rules"), kept.route
    assert kept.sentence == "The work sits at the 70 per cent ceiling."

    said_nothing = Inkwell("", "responses:muse-test")
    quiet = ModelWords(said_nothing).phrase(one(p, "materiality-reviewer"), clean(p))
    assert quiet.sentence == one(p, "materiality-reviewer").sentence
    assert quiet.route.startswith("rules"), "an empty reply is a fallback, and says so"
    assert RuleWords().phrase(one(p, "non-audit-assessor"), clean(p)).route == "rules"


def test_the_firm_with_no_key_still_decides(p, monkeypatch):
    for name in ("META_MODEL_BASE_URL", "META_MODEL_API_KEY", "LLM_API_KEY", "OPENAI_COMPAT_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    firm = Firm.from_env()
    assert isinstance(firm.words, RuleWords) and firm.words.name == "rules"
    assert firm.words.describe()["route"] == "rules"
    assert [f.route for f in firm.review(clean(p))] == ["rules"] * len(ROLES)


# ------------------------------------------------------------------------ the traffic

def test_transact_opens_only_the_findings_that_bind(p, chain, store):
    bus = Bus(chain, store=store, user_id=USER, day=4)
    case = clean(p)
    summary = Firm(p).transact(case, bus)

    findings = {f["role"]: f for f in summary["findings"]}
    binding = {role for role, f in findings.items() if f["binding"]}
    assert binding, "a case with nothing to sign proves nothing about traffic"
    assert {row["role"] for row in summary["agreements"]} == binding
    assert sum(summary["counts"].values()) == len(ROLES)
    assert summary["route"] == {"route": "rules",
                                "why": "no model endpoint is configured, so the firm uses its own words"}

    for row in summary["agreements"]:
        assert [step["verb"] for step in row["steps"]] == ["propose", "accept", "attest"], row["steps"]
        assert row["state"] == "Attested", row
        assert bus.chain.agreement(row["agreement"])["state"] == "Attested"

    waiting = {row["agreement"] for row in summary["waiting_on_humans"]}
    assert waiting == {row["agreement"] for row in summary["agreements"]}
    assert not [row for row in chain.agreements() if row["state"] == "Settled"], (
        "no agent of this firm holds a key that could close one of these")

    rows = store.agent_messages(USER, limit=80)
    assert len({row["delivery_id"] for row in rows}) == len(rows) == len(summary["agreements"]) * 3
    logged = [entry for entry in store.read_log(USER) if entry["kind"] == "audit_review"]
    assert logged and logged[0]["opened"] == len(binding)
    assert logged[0]["blocked"] == [role for role, f in findings.items() if f["verdict"] == BREACH]
    assert logged[0]["waiting"] == len(waiting)


def test_a_breaching_fee_freezes_every_agreement_that_carries_it(p, chain, store):
    """The rule says breach, the bytecode says the same, and the two agree on the arithmetic.

    The assessor opens nothing because its own finding is a breach. The other roles still have
    binding findings, and every one of those proposals carries the same two fee figures - so
    the contract refuses them, and the refusal is what the panels show.
    """
    bus = Bus(chain, store=store, user_id=USER, day=5)
    allowed = int(200_000 * p.value("non_audit_fee_cap_percent") / 100.0)
    summary = Firm(p).transact(clean(p, non_audit_fee_cents=allowed + 50), bus)
    findings = {f["role"]: f for f in summary["findings"]}

    assert findings["non-audit-assessor"]["verdict"] == BREACH
    assert "non-audit-assessor" not in {row["role"] for row in summary["agreements"]}
    opened = {row["agreement"] for row in summary["agreements"] if row["state"] == "Attested"}
    assert not opened, "the cap is arithmetic, so it binds every offer that quotes these fees"
    refused = [row for row in summary["agreements"] if row["state"] == "refused"]
    assert refused and all(row["steps"][0]["refused"].startswith("FeeCapBreached") for row in refused)
    assert all(len(row["steps"]) == 1 for row in refused), "a refused offer is not chased by an accept"

    mirror = store.agent_messages(USER, limit=80)
    assert mirror and {row["state"] for row in mirror} == {"refused"}
    assert {row["refusal"].split("(")[0] for row in mirror} == {"FeeCapBreached"}

    # Control: the same case one cent back inside the cap, and the traffic flows again.
    again = Bus(chain, store=store, user_id=USER, day=5)
    cleared = Firm(p).transact(clean(p, non_audit_fee_cents=allowed), again)
    assert [row["state"] for row in cleared["agreements"]] and all(
        row["state"] == "Attested" for row in cleared["agreements"])


# ---------------------------------------------------- snapshot comparisons and finance context

VAT_DESKS = (
    ("vat-standard-rate-officer", "standard", False),
    ("vat-reduced-rate-officer", "reduced", True),
    ("vat-rate-band-reviewer", "standard", False),
    ("vat-rate-band-reviewer", "reduced", True),
)
FINANCE_DESKS = (
    ("macro-inflation-reporter", "hicp_inflation_percent"),
    ("gdp-per-capita-reporter", "gdp_per_capita_eur"),
    ("economic-sentiment-monitor", "economic_sentiment_index"),
)


@pytest.mark.parametrize("role,kind,reduced", VAT_DESKS)
@pytest.mark.parametrize("reported,verdict", [
    ("missing", SILENT), ("zero", HOLD), ("below", HOLD), ("at", CLEAR), ("above", CLEAR),
])
def test_vat_rates_compare_only_with_the_original_snapshot(p, role, kind, reduced, reported, verdict):
    name = f"vat_{kind}_rate_min_percent"
    floor = p.value(name)
    assert floor is not None and floor > 0
    rate = {"missing": None, "zero": 0.0, "below": floor / 2,
            "at": floor, "above": floor + 1}[reported]
    finding = one(p, role, supply_in_reduced_category=reduced,
                  **{f"{kind}_vat_rate_percent": rate})

    assert finding.verdict == verdict
    assert finding.numbers[f"{kind}_vat_rate_percent"] == rate
    assert finding.numbers["floor_percent"] == floor
    assert finding.cite == dict(p.cite(name), snapshot="original 2006",
                                scope="not current tax compliance")
    assert "original 2006" in finding.sentence
    assert "not current tax compliance" in finding.sentence or "no current tax compliance" in finding.sentence
    if verdict == SILENT:
        assert not finding.binding
    else:
        assert finding.binding and finding.to_role == "engagement-partner"
        assert ("informational only" if verdict == CLEAR else "human must review") in finding.sentence
        assert ("31 December 2010" if kind == "standard" else "derogations") in finding.sentence


@pytest.mark.parametrize("reduced", [False, True])
@pytest.mark.parametrize("selected", ["missing", "below", "above"])
def test_vat_band_uses_the_declared_category_not_the_other_reported_rate(p, reduced, selected):
    kind, other = ("reduced", "standard") if reduced else ("standard", "reduced")
    floor, other_floor = p.value(f"vat_{kind}_rate_min_percent"), p.value(f"vat_{other}_rate_min_percent")
    assert floor is not None and other_floor is not None
    rate = {"missing": None, "below": floor / 2, "above": floor + 1}[selected]
    other_rate = other_floor / 2 if selected == "above" else other_floor + 1
    finding = one(p, "vat-rate-band-reviewer", supply_in_reduced_category=reduced,
                  **{f"{kind}_vat_rate_percent": rate, f"{other}_vat_rate_percent": other_rate})
    assert finding.verdict == {"missing": SILENT, "below": HOLD, "above": CLEAR}[selected]
    assert finding.numbers["rate_kind"] == kind
    assert finding.numbers["floor_percent"] == floor
    assert finding.cite["value"] == str(floor)

    # Even a missing *other* floor must not prevent the declared category being compared.
    doc = json.loads(json.dumps(p.doc))
    del doc["priors"][f"vat_{other}_rate_min_percent"]
    assert one(Priors(doc), "vat-rate-band-reviewer", supply_in_reduced_category=reduced,
               **{f"{kind}_vat_rate_percent": rate}).verdict == finding.verdict


@pytest.mark.parametrize("role,kind,reduced", VAT_DESKS)
def test_removing_the_selected_vat_prior_mutes_its_comparison(p, role, kind, reduced):
    name = f"vat_{kind}_rate_min_percent"
    floor = p.value(name)
    assert floor is not None
    facts = {"supply_in_reduced_category": reduced, f"{kind}_vat_rate_percent": floor + 1}
    assert one(p, role, **facts).verdict == CLEAR
    doc = json.loads(json.dumps(p.doc))
    del doc["priors"][name]
    finding = one(Priors(doc), role, **facts)
    assert finding.verdict == SILENT and not finding.binding
    assert finding.numbers["floor_percent"] is None


def test_reduced_vat_desk_needs_a_reduced_category_even_when_a_rate_is_reported(p):
    floor = p.value("vat_reduced_rate_min_percent")
    assert floor is not None
    for rate in (0.0, floor + 1):
        finding = one(p, "vat-reduced-rate-officer", reduced_vat_rate_percent=rate,
                      supply_in_reduced_category=False)
        assert finding.verdict == SILENT and not finding.binding
        assert finding.cite == dict(p.cite("vat_reduced_rate_min_percent"), snapshot="original 2006",
                                    scope="not current tax compliance")
        assert not number_tokens(finding.sentence) - figures(finding)


@pytest.mark.parametrize("claimed", [False, True])
@pytest.mark.parametrize("balance_side,turnover_side", [(-1, -1), (-1, 1), (1, -1), (1, 1)])
def test_small_status_is_never_classified_from_national_threshold_maxima(p, claimed, balance_side,
                                                                      turnover_side):
    balance = p.value("size_balance_sheet_ceiling_eur")
    turnover = p.value("size_net_turnover_ceiling_eur")
    assert balance is not None and turnover is not None
    finding = one(p, "size-ceiling-reviewer", claims_small_undertaking=claimed,
                  balance_sheet_eur=balance + balance_side, turnover_eur=turnover + turnover_side)
    assert finding.verdict == (HOLD if claimed else SILENT)
    assert finding.numbers["classification_modeled"] is False
    assert finding.numbers["balance_sheet_ceiling_eur"] == balance
    assert finding.numbers["net_turnover_ceiling_eur"] == turnover
    assert finding.binding == claimed
    if claimed:
        assert finding.to_role == "engagement-partner"
        assert "national thresholds" in finding.sentence
        assert "headcount" in finding.sentence and "two-consecutive-year" in finding.sentence


def test_small_status_claim_still_needs_review_when_the_maxima_are_unavailable(p):
    doc = json.loads(json.dumps(p.doc))
    for name in ("size_balance_sheet_ceiling_eur", "size_net_turnover_ceiling_eur"):
        del doc["priors"][name]
    finding = one(Priors(doc), "size-ceiling-reviewer", claims_small_undertaking=True)
    assert finding.verdict == HOLD and finding.binding
    assert finding.numbers["classification_modeled"] is False


def test_delegation_cites_the_inserted_article_and_a_renewable_not_lifetime_term(p):
    name = "delegation_period_years"
    years = p.value(name)
    assert years is not None
    doc = json.loads(json.dumps(p.doc))
    doc["priors"][name]["value"] = years + 2
    for source in (p, Priors(doc)):
        finding = one(source, "delegation-standards-reviewer")
        assert finding.verdict == CLEAR
        assert finding.numbers == {"delegation_period_years": source.value(name), "renewable": True}
        assert finding.cite == dict(source.cite(name), target_celex="32006L0043", target_article="48a(2)")
        assert "renewable" in finding.sentence and "not a lifetime limit" in finding.sentence
        assert "current status" in finding.sentence
    del doc["priors"][name]
    assert one(Priors(doc), "delegation-standards-reviewer").verdict == SILENT


@pytest.fixture(scope="module")
def finance_geo(p):
    available = [set(p.doc["finance"][name]["series"]) for _, name in FINANCE_DESKS]
    common = set.intersection(*available)
    assert common, "the finance desks need a common harvested jurisdiction for the controls"
    return sorted(common)[0]


@pytest.mark.parametrize("role,name", FINANCE_DESKS)
def test_finance_desks_are_silent_without_a_geo_or_source(p, finance_geo, role, name):
    reported = one(p, role, client_geo=finance_geo)
    assert reported.verdict == CLEAR
    assert reported.numbers[name] == p.finance(name, finance_geo)["value"]
    assert reported.cite == p.finance_cite(name, finance_geo)
    missing_geo = one(p, role, client_geo="")
    assert missing_geo.verdict == SILENT and not missing_geo.binding

    doc = json.loads(json.dumps(p.doc))
    del doc["finance"]
    missing_source = one(Priors(doc), role, client_geo=finance_geo)
    assert missing_source.verdict == SILENT and not missing_source.binding
    assert missing_source.numbers[name] is None
    assert missing_source.cite["state"] == "not_in_corpus"


@pytest.mark.parametrize("muted_role,removed", FINANCE_DESKS)
def test_removing_one_finance_source_mutes_only_its_own_desk(p, finance_geo, muted_role, removed):
    doc = json.loads(json.dumps(p.doc))
    del doc["finance"][removed]
    changed = Priors(doc)
    for role, name in FINANCE_DESKS:
        finding = one(changed, role, client_geo=finance_geo)
        if role == muted_role:
            assert finding.verdict == SILENT and finding.numbers[name] is None
            assert not finding.binding
        else:
            assert finding == one(p, role, client_geo=finance_geo)
            assert finding.verdict == CLEAR


@pytest.mark.parametrize("value", [99.0, 101.0], ids=["below-100", "above-100"])
def test_economic_sentiment_is_informational_on_both_sides_of_100(p, finance_geo, value):
    doc = json.loads(json.dumps(p.doc))
    name = "economic_sentiment_index"
    doc["finance"][name]["series"][finance_geo]["value"] = value
    source = Priors(doc)
    finding = one(source, "economic-sentiment-monitor", client_geo=finance_geo)
    assert finding.verdict == CLEAR
    assert finding.numbers[name] == value and finding.cite == source.finance_cite(name, finance_geo)
    assert "informational only" in finding.sentence and "no threshold or trend inferred" in finding.sentence
    assert set(finding.numbers) == {"client_geo", "reference_geo", name, "reference_period"}
    assert "centre" not in finding.sentence.lower() and "center" not in finding.sentence.lower()
