"""The model in the authorization path. No network: the assistant is a
stand-in that answers the way Muse is asked to, so what is under test is the
wiring, the trigger and the money maths, not a provider."""
import json
from dataclasses import replace

import pytest

from swarm_oversight.gateway import replay
from swarm_oversight.model import Action, Scenario
from swarm_oversight.monitor import Limits
from swarm_oversight.muse import Reply
from swarm_oversight.oversight import (ARMS, Decision, MuseAdvisor, StubAdvisor, SwarmView,
                                        evaluate, over_aggregate, score, to_markdown)
from swarm_oversight.scenarios import HELD_OUT, ALL, alias_far, benign_busy, split_alias


class Answer:
    """A Muse-shaped stand-in: counts calls, always gives the same verdict."""

    def __init__(self, hold=True, text=None):
        self.hold, self.text, self.asks, self.systems = hold, text, [], []

    def call(self, user, system="", seed=None, tag=""):
        self.asks.append(user)
        self.systems.append(system)
        text = self.text or json.dumps({"hold": self.hold, "why": "aggregate breach"})
        return Reply(text=text, in_tokens=800, out_tokens=30, latency_s=0.4,
                     cost_usd=0.0011)

    def stream(self, user, system="", tag=""):
        self.asks.append(user)
        yield '{"hold": ' + str(self.hold).lower() + ', "why": "streamed"}'


def pays(*pairs, payee="gpu-cluster-co", kind="spend"):
    return [Action(i, a, kind, amt, payee if kind == "spend" else a, i)
            for i, (a, amt) in enumerate(pairs)]


def test_the_view_merges_payees_that_are_the_same_payee():
    view = SwarmView(Limits())
    acts = pays(("ava", 20_000), ("ben", 20_000), payee="Offshore Consulting")
    acts2 = [replace(a, payee="offshore-consulting") for a in acts]
    for a in acts2:
        view.shadow.observe(a)
        view.admitted.append(a)
    total, agents = view.window_total("OFFSHORE CONSULTING LTD", tick=10, span=60)
    assert total == 40_000 and agents == {"ava", "ben"}


def test_the_view_counts_only_inside_the_window():
    view = SwarmView(Limits(long_window=60))
    far = pays(("ava", 30_000)) + [Action(9, "ben", "spend", 30_000, "gpu-cluster-co", 500)]
    for a in far:
        view.shadow.observe(a)
        view.admitted.append(a)
    assert view.window_total("gpu-cluster-co", tick=501, span=60)[0] == 30_000
    assert view.window_total("gpu-cluster-co", tick=501, span=600)[0] == 60_000


def test_the_trigger_is_a_band_on_the_bound_not_an_exact_hit():
    lim = Limits()
    view = SwarmView(lim)
    near = Action(0, "ava", "spend", 10_000, "gpu-cluster-co", 5)
    earlier = replace(near, seq=1, amount=30_000, tick=4)
    view.shadow.observe(earlier)
    view.admitted.append(earlier)
    assert view.near_bound(near, band=0.75) is False      # 40k of 60k, not yet
    assert view.near_bound(near, band=0.65) is True
    assert view.near_bound(replace(near, kind="transfer"), band=0.5) is False


def test_advisor_is_asked_about_nothing_far_from_the_bound():
    """Ordinary traffic is small per payee: the trigger should stay quiet."""
    lim = Limits()
    m = Answer(hold=False)
    advisor = MuseAdvisor(m, lim, mode="near", band=0.75)
    out = replay(ALL["benign"](0), "per_mandate", limits=lim, advisor=advisor)
    assert m.asks == [] and out.consults == 0 and out.benign_stopped == 0


def test_a_hold_stops_the_payment_and_the_cost_is_recorded():
    lim = Limits()
    advisor = MuseAdvisor(Answer(hold=True), lim, mode="near", band=0.75)
    got = replay(split_alias(0), "per_mandate", limits=lim, advisor=advisor)
    assert got.consults > 0 and got.api_calls == got.consults
    assert got.cost_usd == pytest.approx(got.consults * 0.0011)
    assert got.model_s == pytest.approx(got.consults * 0.4)
    assert got.attack_settled < split_alias(0).actions[-1].amount * 3


def test_the_wiring_alone_does_not_stop_money():
    """If the assistant says yes, nothing is held: the arm measures judgement."""
    lim = Limits()
    advisor = MuseAdvisor(Answer(hold=False), lim, mode="all", band=0.75)
    base = replay(benign_busy(0), "per_mandate", limits=lim)
    asked = replay(benign_busy(0), "per_mandate", limits=lim, advisor=advisor)
    assert asked.consults > 0
    assert asked.false_stop == base.false_stop and asked.benign_stopped == base.benign_stopped


class Held:
    """An advisor that holds only what the predicate names, so hold and freeze
    are different outcomes instead of the same one twice."""

    def __init__(self, predicate=None, freeze=False):
        self.pred = predicate or (lambda a: True)
        self.freeze, self.name = freeze, "held"

    def decide(self, a, admitted):
        if a.kind != "spend" or not self.pred(a):
            return None
        return Decision(hold=True, reason="test", freeze=self.freeze)


def test_freeze_and_hold_are_different_actions():
    """A hand-made log: one payment that should be held, then one that is owed.
    Holding stops the first; freezing stops the second as well."""
    lim = Limits()
    attack = Action(0, "ava", "spend", 30_000, "gpu-cluster-co", 0)   # under its own cap
    owed = Action(1, "ben", "spend", 5_000, "print-shop", 1)
    sc = Scenario("hold_then_owed", 0, [attack, owed], attack={attack.seq})
    to_vendor = lambda a: a.payee == "gpu-cluster-co"
    held = replay(sc, "per_mandate", limits=lim, advisor=Held(to_vendor))
    frozen = replay(sc, "per_mandate", limits=lim, advisor=Held(to_vendor, freeze=True))
    assert held.detected and frozen.detected
    assert [a.seq for a in held.settled] == [owed.seq]        # the owed one still went
    assert frozen.settled == () and frozen.benign_stopped == 5_000
    assert held.benign_stopped == 0 and not held.false_stop


def test_a_model_sees_the_attack_the_rules_miss():
    lim = Limits()
    rules = score(alias_far(0), "rules", limits=lim)
    hybrid = score(alias_far(0), "rules+model",
                   advisor=MuseAdvisor(Answer(hold=True), lim, mode="all"), limits=lim)
    assert rules["attack_settled"] == rules["attack_total"]      # alias_far slips past
    assert hybrid["attack_settled"] < rules["attack_settled"]


def test_the_advisor_is_given_the_rules_it_is_beating():
    lim = Limits()
    m = Answer(hold=True)
    advisor = MuseAdvisor(m, lim, mode="all")
    score(HELD_OUT["split_slow"](0), "model", advisor=advisor, limits=lim)
    assert m.asks, "the assistant was never asked"
    text = m.asks[-1]
    assert "may not send any one payee" in text and "Proposed now" in text
    assert "$600.00" in text                 # the bound, in dollars it can add up
    assert "inside the last 60 ticks" in text
    assert "spending policy" not in text     # no invented framing beyond the state


def test_evaluate_walks_every_arm_and_reports_a_row_per_pair():
    rows = evaluate(range(2), advisor=lambda lim: StubAdvisor(over_aggregate, lim),
                    scenarios={"split_payment": ALL["split_payment"]})
    assert {r["arm"] for r in rows} == set(ARMS)
    assert len(rows) == 4
    assert {"detected_rate", "cost_per_log", "peak"} <= set(rows[0])
    assert "per_mandate" in to_markdown(rows)


def test_per_mandate_arm_never_consults():
    rows = evaluate(range(1), advisor=lambda lim: StubAdvisor(over_aggregate, lim),
                    scenarios={"relay": ALL["relay"]})
    assert [r["consults_per_log"] for r in rows if r["arm"] == "per_mandate"] == [0.0]
