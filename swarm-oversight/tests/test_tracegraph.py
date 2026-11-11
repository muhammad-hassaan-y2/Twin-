"""Reading a real swarm's shape, and what the shape does to the claims.

These run on hand-built graphs, not on the 15 MB download: what is under test
is that the measurement and scoring code is right, not that the incident
happened to look a certain way. The incident numbers live in
`results/trace_shape.json`, which the module writes from the published records.
"""
import random
from collections import Counter

import pytest

from swarm_oversight.model import Action, Scenario
from swarm_oversight.monitor import Limits, Monitor
from swarm_oversight.tracegraph import (Graph, Shape, bound_table, capacity, measure,
                                        order_ticks, scenarios, score, sweep,
                                        to_markdown, violates)

A = "destination-000003"
B = "destination-000058"          # differs from A by two digits, and merges with it


def star(widths, dests=((A, 10),)):
    """A two-level graph shaped like the published one: parents, children, no chain."""
    g = Graph(nodes=sum(widths) + len(widths), kinds=Counter({"payload": sum(widths)}))
    for p, w in enumerate(widths):
        pid = f"P{p}"
        g.children[pid] = [f"{pid}C{c}" for c in range(w)]
        for c in g.children[pid]:
            g.parents[c] = pid
    for name, n in dests:
        g.dest_counts[name] += n
    return g


def log(payees, amount=20_000, ticks=None):
    acts = [Action(i, ["ava", "ben", "cal", "dee"][i % 4], "spend", amount, p,
                   i if ticks is None else ticks[i])
            for i, p in enumerate(payees)]
    return Scenario("log", 0, acts, attack={a.seq for a in acts})


def test_the_published_shape_is_a_forest_of_stars():
    m = measure(star([1, 3, 858]))
    assert m["edges"] == 862 and m["parent_nodes"] == 3
    assert m["intermediate_nodes"] == 0          # so no relay depth is observable
    assert m["hops_observable"] == 1
    assert m["max_fan_out"] == 858 and m["fan_out"]["median"] == 3
    assert m["with_time"] == 0                   # not one record carries a clock


def test_orderings_of_the_same_graph_disagree_about_the_window():
    lim, rng = Limits(), random.Random(0)
    assert order_ticks(6, "tight", lim, rng) == [0, 1, 2, 3, 4, 5]
    assert order_ticks(6, "worst", lim, rng) == [i * (lim.long_window + 1) for i in range(6)]
    spread = order_ticks(6, "random", lim, random.Random(1))
    assert spread == sorted(spread) and len(set(spread)) == 6


def test_the_same_fanout_is_a_breach_in_one_ordering_and_not_in_another():
    lim, pays = Limits(), 9_000                   # 8 x $90 = $720 against a $600 bound
    g = star([8])
    tight = scenarios(g, range(1), "tight", pays, 1, lim)[0]
    worst = scenarios(g, range(1), "worst", pays, 1, lim)[0]
    assert violates(tight, lim) and not violates(worst, lim)
    assert violates(worst, lim, order_free=True)   # $720 in total, clock or no clock
    assert score([tight], lim)["recall"] == 1.0
    assert score([tight], lim)["money_out_of_violations"] == 0.0
    assert score([worst], lim)["violation_rate"] == 0.0
    assert score([worst], lim)["violation_rate_order_free"] == 1.0
    # no breach in the window, so recall is not a number the ordering supports
    assert score([worst], lim)["recall"] is None and score([worst], lim)["missed"] == 0


def test_a_numbered_payee_namespace_makes_the_alias_rule_over_merge():
    """The defect the real data found: two different payees, one long shared
    prefix, and a monitor that adds them together and calls it a breach."""
    lim = Limits()
    sc = log([A, A, B, B])
    assert not violates(sc, lim)                 # $400 each, under $600
    assert Monitor(lim).review(sc.actions)       # $800 merged, so flagged
    assert score([sc], lim)["false_alarms_on_clean"] == 1.0
    assert score([sc], lim, ("split_payment", "slow_split"))["false_alarms_on_clean"] == 0.0


def test_removal_of_the_alias_rule_is_what_clears_the_false_alarm():
    """Negative control on the control: put the rule back and it returns."""
    lim = Limits()
    sc = log([A, A, B, B])
    off = score([sc], lim, ("split_payment", "slow_split"))["false_alarms_on_clean"]
    on = score([sc], lim)["false_alarms_on_clean"]
    assert (off, on) == (0.0, 1.0)


def test_sweep_reports_the_denomination_it_assumed():
    g = star([1, 2, 4, 8, 16, 40], dests=((A, 10), (B, 4)))
    rows = sweep(g, range(6), payments=(9_000, 300_000))
    assert {(r["payment_cents"], r["ordering"]) for r in rows} >= {(9000, "tight"),
                                                                   (300000, "worst")}
    small = [r for r in rows if r["payment_cents"] == 9_000 and r["ordering"] == "tight"][0]
    big = [r for r in rows if r["payment_cents"] == 300_000 and r["ordering"] == "tight"][0]
    assert big["violation_rate"] > small["violation_rate"]


def test_capacity_says_the_bound_is_per_identity_not_per_swarm():
    g = star([2], dests=tuple((f"destination-{i:06d}", 1) for i in range(120)))
    cap = capacity(g, Limits())
    assert cap["distinct_payees_observed"] == 120
    assert cap["payees_to_move_1m"] == pytest.approx(10_000_000 / 60_000, rel=1e-2)
    # what the pool covers is measured in whole $100k runs, not in swarm size
    assert cap["runs_the_pool_can_hide"] == pytest.approx(120 / (10_000_000 / 60_000), rel=.02)
    assert cap["pool_needed_for_1m"] == pytest.approx((10_000_000 / 60_000) / 120, rel=1e-2)
    # a pool short of the need cannot carry a full run on distinct identities alone
    thin = capacity(star([2], dests=tuple((f"destination-{i:06d}", 1) for i in range(40))))
    assert thin["runs_the_pool_can_hide"] < 1 and thin["pool_needed_for_1m"] > 1


def test_the_table_names_every_column_it_fills():
    g = star([1, 8], dests=((A, 5),))
    text = to_markdown(sweep(g, range(3), payments=(9_000,)), capacity(g), measure(g))
    assert "violation rate" in text and "over-merged" in text and "no clock" in text
    assert "distinct payees" in text and "858" not in text.splitlines()[0]


def test_the_interval_survives_as_rows():
    t = bound_table(star([1, 8, 20], dests=((A, 9),)), range(4))
    assert {"pool1_tight", "pool4_worst"} <= set(t)
    assert {"over_merged", "lifetime", "aggregate", "no_alias"} <= set(t["pool1_tight"])
