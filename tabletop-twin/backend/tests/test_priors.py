"""Every number the firm enforces has to be findable in the text it quotes, or it is not enforced.

This is the layer where a transcription error becomes a rule, so the tests are built to fail in
the two directions that matter: a prior that quotes a sentence which does not contain its own
number, and a prior that would still come out the same if the corpus said something else. The
second is tested by handing the finder a statute of the firm's own making - if a number moves in
the text and does not move in the prior, the prior was typed rather than read.

What this file does not test: that the corpus was fetched correctly (that is the manifest) or
that an agent draws the right conclusion from a prior (that is `test_agents.py`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from twin.audit.corpus import measures, sentences
from twin.audit.priors import RULES, Rule, derive, derive_bands, derive_services, find, load_statutes

CALIBRATED = {rule.name for rule in RULES} - {"materiality_percent_of_turnover"}


@pytest.fixture(scope="module")
def statutes():
    return load_statutes()


def article(text: str, name: str = "5", heading: str = "Article 5") -> dict[str, Any]:
    return {"articles": [{"article": name, "text": f"{heading}\n{text}"}], "celex": "32000L0001"}


# ------------------------------------------------------- provenance: a number names its sentence

def test_a_calibrated_prior_quotes_the_sentence_that_carries_its_number(statutes):
    for rule in RULES:
        prior = find(rule, statutes)
        if not prior.calibrated:
            continue
        in_quote = [m["value"] for m in measures(prior.quote) if m["measure"] == prior.unit]
        assert prior.value in in_quote, (
            f"{rule.name} says {prior.value} but its own quote only holds {in_quote}")
        assert prior.celex and prior.article, f"{rule.name} quotes nothing it can be traced to"


def test_the_one_number_the_corpus_does_not_state_says_so(statutes):
    """Materiality is an auditing standard's judgement, not a figure in EU law.

    The rule is listed so the run proves the absence rather than papering over it: an unset
    prior has no value, no article, and a note that explains itself.
    """
    prior = find(next(r for r in RULES if r.name == "materiality_percent_of_turnover"), statutes)
    assert prior.value is None and not prior.celex and prior.hits == 0
    assert "materiality" in prior.note.lower()
    doc = derive(statutes)
    assert doc["uncalibrated"] == ["materiality_percent_of_turnover"]
    assert doc["priors"]["materiality_percent_of_turnover"]["state"] == "uncalibrated"


# ------------------------------------------------ the finder reads the text rather than a table

def test_a_number_that_moves_in_the_text_moves_in_the_prior():
    """The same rule, run against a statute this test wrote.

    If the result were the shipped 10 years, the finder would be reading a constant.
    """
    rule = next(r for r in RULES if r.name == "rotation_initial_max_years")
    moved = find(rule, [article(
        "Neither the initial engagement of a particular statutory auditor or audit firm shall "
        "exceed a maximum duration of 14 years. By way of derogation, Member States may provide "
        "for a period of 3 years.", name="17")])
    assert moved.value == 14.0 and moved.celex == "32000L0001" and moved.article == "17"
    assert "14 years" in moved.quote

    absent = find(rule, [article("The auditor shall be appointed for a reasonable period.", name="17")])
    assert absent.value is None and absent.hits == 0, "a rule with no sentence has no number"


def test_a_ceiling_and_a_floor_in_one_sentence_are_two_different_rules():
    """'a maximum period of seven years' and 'at least four years' are both durations.

    The one that binds is the one the rule asked for, so a rule has to say - and a test has to
    be able to show that switching the answer over switches the pick.
    """
    text = ("The key audit partner shall rotate within a maximum period of seven years and may be "
            "replaced after a period of at least four years.")
    ceiling = Rule("ceiling", ("key audit partner",), "duration_years", pick="max")
    floor = Rule("floor", ("key audit partner",), "duration_years", pick="min")
    assert find(ceiling, [article(text, "42")]).value == 7.0
    assert find(floor, [article(text, "42")]).value == 4.0


def test_two_amounts_in_one_sentence_split_by_position():
    """The size ceilings print as one sentence with two figures, so the second is found by place."""
    text = ("Member States shall not exceed EUR 6 000 000 for the balance sheet total and "
            "EUR 12 000 000 for the net turnover.")
    sheet = Rule("sheet", ("shall not exceed", "balance sheet total"), "amount_eur",
                 adjacent="for the balance sheet total")
    turnover = Rule("turn", ("shall not exceed", "net turnover"), "amount_eur",
                    adjacent="for the net turnover")
    assert find(sheet, [article(text, "3")]).value == 6_000_000.0
    assert find(turnover, [article(text, "3")]).value == 12_000_000.0
    # Control: the sentence still says both of the rule's things, but its only figure sits
    # after the words instead of before them. The position rule reports that it found no
    # number where it looked rather than borrowing the one it can see.
    lonely = find(turnover, [article("A Member State shall not exceed for the net turnover "
                                     "the figure of EUR 12 000 000.", "3")])
    assert lonely.value is None and lonely.hits == 1, "it saw the sentence and refused the number"
    assert "immediately before" in lonely.note


def test_a_number_spelled_in_two_words_is_one_number():
    """The consolidated Regulation prints its outer ceiling as "twenty four years".

    Read as a bare word list it becomes a four-year extension, and a firm that enforces four
    years where the law says twenty-four is worse than one that quotes nothing.
    """
    text = "The maximum duration may be extended to (a) 20 years, or (b) twenty four years."
    got = {m["value"] for m in measures(text) if m["measure"] == "duration_years"}
    assert got == {20.0, 24.0} and 4.0 not in got
    outer = Rule("outer", ("years",), "duration_years", pick="max", within=0)
    assert find(outer, [article(text, "17")]).value == 24.0
    assert measures("ninety nine years")[0]["value"] == 99.0


# ------------------------------------------------------------------ the Article 5 list, walked

def test_the_prohibition_is_walked_in_order_and_keeps_its_letters():
    services = derive_services()
    letters = [c["letter"] for c in services["categories"]]
    assert letters == list("abcdefghijk"), f"Article 5(1) stopped at {letters[-1]}"
    assert services["celex"] == "32014R0537" and services["article"] == "5"
    assert all(c["text"] and c["title"] for c in services["categories"])
    # (a), (g) and (k) are heads of roman sub-paragraphs; (d) is not a head, and a walk that
    # ran past its own stop would hand it somebody else's list.
    heads = {c["letter"] for c in services["categories"] if c["subs"]}
    assert heads == {"a", "g", "k"}, heads
    for category in services["categories"]:
        for sub in category["subs"]:
            assert sub["letter"] in ("i", "ii", "iii", "iv", "v", "vi", "vii"), sub
            # The shortest real sub-point is "payroll tax;", so this proves the walk kept the
            # words rather than only the letter - it is not a test for a sentence.
            assert len(sub["text"]) > 5, sub


def test_the_derogation_names_sub_points_and_not_the_conditions_of_the_waiver():
    """5(3) has two lists in it: the points that may be allowed, and the conditions for allowing.

    Reading the second as the first would have made bookkeeping derogable, which it is not.
    """
    services = derive_services()
    points = services["derogation"]["points"]
    assert set(points) == {"a", "f"}
    assert points["a"] == ["i", "iv", "v", "vi", "vii"]
    assert "c" not in points, "bookkeeping is not derogable, and a wrong slice would say it is"
    assert all(letter not in ("a", "b", "c") for letter in points["f"]) or points["f"] == []
    assert "provided that" not in services["derogation"]["points_text"].lower()
    assert services["approval"].lower().startswith("a statutory auditor")


def test_the_size_ladder_pairs_each_figure_with_the_label_it_sits_under(statutes):
    ladder = derive_bands(statutes)
    bands = ladder["bands"]
    assert ladder["article"] == "3"
    assert {"micro-undertakings", "small undertakings", "medium-sized undertakings",
            "large undertakings"} <= set(bands)
    assert bands["small undertakings"]["balance_sheet_total_eur"] == 4_000_000.0
    assert bands["small undertakings"]["net_turnover_eur"] == 8_000_000.0
    assert bands["small undertakings"]["average_employees"] == 50.0
    assert bands["micro-undertakings"]["balance_sheet_total_eur"] == 350_000.0
    # The ladder only means something if it climbs, and climbing is checked rather than assumed.
    assert (bands["micro-undertakings"]["balance_sheet_total_eur"]
            < bands["small undertakings"]["balance_sheet_total_eur"]
            < bands["medium-sized undertakings"]["balance_sheet_total_eur"])
    assert json.dumps(ladder)  # the whole thing has to survive the trip through the data file


def test_the_shipped_file_is_the_derivation_and_not_an_edit(statutes):
    """The agents read `data/priors.json`; this reads the corpus and proves they are the same.

    A hand-tuned value in that file would pass every agent test and still be a rule somebody
    invented, so the comparison is against a fresh derivation rather than a list of figures.
    """
    doc = derive(statutes)
    assert set(doc["priors"]) == CALIBRATED | {"materiality_percent_of_turnover"}
    assert doc["derived_from"]["statutes"] == len(statutes) > 0
    assert doc["non_audit_services"]["categories"]
    shipped = json.loads((Path(__file__).resolve().parents[1] / "twin" / "audit" / "data" /
                          "priors.json").read_text(encoding="utf-8"))
    assert json.dumps(shipped, sort_keys=True) == json.dumps(doc, sort_keys=True), (
        "priors.json is stale: run python -m twin.audit.calibrate")
