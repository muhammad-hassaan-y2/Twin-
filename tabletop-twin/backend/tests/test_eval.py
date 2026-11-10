"""The eval is only evidence if something can prove it is blind.

`twin.eval` runs every scenario twice — once as the code stands, once with the one
protection that scenario exists to watch removed. This file asserts the five things a
reviewer would otherwise have to take on faith: that the corpus lands on its known
answers, that every guard scenario *fails* when its guard is missing, that a control
puts the world back the way it found it, that the spoken-figure checker rejects a
number nobody computed, and that the coverage number is computed from the code's own
vocabulary rather than a list someone maintains beside it.

The corpus is two worlds — the payment twin and the audit firm — and nothing here is
allowed to test only one of them.
"""

from __future__ import annotations

from dataclasses import replace

from twin.eval import harness
from twin.eval.cases import CASES, Run
from twin.eval.firm import FIRM_CASES
from twin.eval.grounding import collect, ungrounded

WHOLE = CASES + FIRM_CASES


def test_the_corpus_lands_on_every_known_answer():
    result = harness.report()
    metrics = result["metrics"]
    broken = [row["slug"] for row in result["cases"] if not row["passed"]]
    assert broken == [], "\n".join(
        f"{row['slug']}: {check['name']} wanted {check['expected']!r} got {check['actual']!r}"
        for row in result["cases"] for check in row["checks"] if not check["ok"]
    )
    assert metrics["cases_passed"] == metrics["cases"] == len(WHOLE)
    assert metrics["checks"] == sum(len(row["checks"]) for row in result["cases"]) > 40


def test_every_guard_scenario_notices_its_guard_being_removed():
    """A case that passes with its protection gone has stopped proving anything."""
    teeth = harness.report()["metrics"]
    assert teeth["hollow_cases"] == []
    assert teeth["guard_cases_with_teeth"] == teeth["guard_cases"] >= 12
    assert {row["kind"] for row in harness.report()["cases"]} == {"guard", "measure"}


def test_the_teeth_audit_notices_a_control_that_was_neutered():
    """The discipline pointed at itself: a no-op control must show up as a hollow case."""

    def blind(run: Run):
        return None

    for probe in (CASES[0], FIRM_CASES[0]):
        neutered = replace(probe, control=blind)
        result = harness.report(cases=(neutered, *(c for c in WHOLE if c is not probe)))
        assert result["metrics"]["hollow_cases"] == [probe.slug]


def test_a_control_leaves_the_world_as_it_found_it():
    """Removing a guard is a temporary condition, or the next score measures the wreckage.

    Every control edits a class or a module and hands back the thing that puts it right. A
    restore that puts the member back in a shape the code does not use — a bare function where
    a classmethod stood, say — does not fail loudly. It makes the scenarios that run afterwards
    crash, or worse, quietly pass in a broken world. So each control is run, and the same
    scenario is then run again and required to land on its known answers.
    """
    for case in WHOLE:
        if case.kind != "guard" or case.control is None:
            continue
        harness.run_case(case, control=True)
        after = harness.run_case(case)
        assert after["passed"], f"{case.slug} still fails after its control was undone: " + ", ".join(
            f"{check['name']} wanted {check['expected']!r} got {check['actual']!r}"
            for check in after["checks"] if not check["ok"])
    assert harness.report()["metrics"]["broken_cases"] == []


def test_the_grounding_checker_accepts_a_computed_figure_and_refuses_an_invented_one():
    run = Run.fresh()
    run.propose(amount_cents=900, recipient="Ashgrove Studios")
    run.note_all()
    computed = str(run.session.policy.approval_floor_cents)
    assert ungrounded(f"The floor is {computed} cents.", run.facts) == []
    # The invented figure is the same shape as a real one: same sentence, same units,
    # and nothing in this world produced it.
    assert ungrounded("The floor is 9,123,456 cents.", run.facts) == ["9123456"]


def test_a_percent_and_a_dollar_restatement_of_one_fact_is_not_a_new_number():
    facts = collect({"dry_run_percent": 0.125, "min_balance_dollars": -255.0})
    assert ungrounded("12 percent of the paths went under, about 255 dollars below.", facts) == []
    assert ungrounded("26 percent of the paths went under.", facts) == ["26"]


def test_coverage_is_measured_from_the_engine_not_from_a_list_kept_beside_it():
    rules = harness.engine_rules()
    assert "recipient_allowlist" in rules and "approval_floor" in rules
    thresholds = harness.threshold_rules()
    assert "non_audit_fee_cap_percent" in thresholds
    seen = harness.report()["metrics"]
    assert set(seen["rules_reachable"]) == set(rules) | set(harness.guardrail_rules()) | set(thresholds)
    assert seen["rules_missed"] == [], "every rule this code can answer with is reached by a scenario"
    assert set(seen["rules_reached"]) <= set(seen["rules_reachable"])
    assert seen["rule_coverage_pct"] == 100
    assert "public_register_particulars" in thresholds
    assert "vat_standard_rate_min_percent" in thresholds
    assert "size_balance_sheet_ceiling_eur" not in thresholds
    assert "delegation_period_years" not in thresholds


def test_the_command_exits_clean_on_the_shipped_corpus():
    assert harness.main([]) == 0


def test_every_case_states_a_promise_and_carries_three_answers():
    """A scenario with two checks is a guess; one with no promise is not a scenario."""
    for case in WHOLE:
        assert len(case.promise.split()) >= 8, case.slug
        if case.kind == "guard":
            assert case.control is not None, case.slug
        checks = case.run(Run.fresh())
        assert len(checks) >= 3, f"{case.slug} says one thing and proves nothing around it"
        for check in checks:
            assert isinstance(check, harness.Check)
            assert len(check.name.split()) >= 2 and check.expected is not None
