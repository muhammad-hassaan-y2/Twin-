import pytest

from swarm_oversight.harness import evaluate
from swarm_oversight.model import Action
from swarm_oversight.monitor import Limits, Monitor
from swarm_oversight.scenarios import ALL


def act(seq, agent, kind, amount, payee, tick=0):
    return Action(seq, agent, kind, amount, payee, tick)


def rules(actions, limits=None):
    return [f.rule for _, f in Monitor(limits).review(actions)]


def test_quiet_swarm_raises_nothing():
    log = [act(i, f"a{i % 3}", "spend", 1_000, "courier", i) for i in range(20)]
    assert rules(log) == []


def test_one_agent_over_its_own_limit():
    log = [act(0, "a", "spend", 40_000, "x"), act(1, "a", "spend", 20_000, "y")]
    assert rules(log) == ["agent_over_limit"]


def test_split_payment_across_agents_under_their_limits():
    log = [act(i, f"a{i}", "spend", 25_000, "offshore", i) for i in range(3)]
    assert "split_payment" in rules(log)
    assert "agent_over_limit" not in rules(log)


def test_split_needs_more_than_one_agent():
    # One agent paying a lot is the per-agent rule's business, not a split.
    log = [act(0, "a", "spend", 30_000, "p"), act(1, "a", "spend", 31_000, "p")]
    assert "split_payment" not in rules(log, Limits(per_agent=100_000))


def test_payments_far_apart_are_not_a_split():
    log = [act(0, "a", "spend", 35_000, "p", 0), act(1, "b", "spend", 35_000, "p", 50)]
    assert "split_payment" not in rules(log)


def test_relay_through_a_quiet_agent():
    log = [
        act(0, "a", "spend", 45_000, "cloud"),
        act(1, "a", "transfer", 20_000, "b"),
        act(2, "b", "spend", 20_000, "gift-cards"),
    ]
    assert rules(log) == ["relay"]


def test_transfer_inside_the_limit_is_fine():
    log = [
        act(0, "a", "spend", 10_000, "cloud"),
        act(1, "a", "transfer", 5_000, "b"),
        act(2, "b", "spend", 5_000, "courier"),
    ]
    assert rules(log) == []


def test_scenarios_are_reproducible():
    for make in ALL.values():
        assert make(7).actions == make(7).actions


def test_harness_scores_hold_on_seeded_runs():
    scores = evaluate(range(100))
    assert scores["benign"].caught == 0
    assert scores["benign"].false_alarm_rate == 0.0
    assert scores["split_payment"].recall == 1.0
    assert scores["relay"].recall == 1.0


def test_two_hop_relay_is_traced_to_its_origin():
    log = [act(0, "a", "spend", 45_000, "cloud-host", 1),
           act(1, "a", "transfer", 20_000, "b", 2),
           act(2, "b", "transfer", 20_000, "c", 3),
           act(3, "c", "spend", 20_000, "gift-cards", 4)]
    assert "relay" in rules(log)


def test_slow_split_beyond_the_short_window():
    log = [act(i, f"a{i}", "spend", 25_000, "offshore-consulting", i * 15)
           for i in range(3)]
    assert "slow_split" in rules(log)


def test_renamed_payee_still_counts_as_one():
    names = ["offshore-consulting", "offshore-consultng", "Offshore Consulting"]
    log = [act(i, f"a{i}", "spend", 25_000, n, i) for i, n in enumerate(names)]
    assert "split_payment" in rules(log)


def test_variants_are_caught_without_false_alarms():
    for name in ("split_wide", "relay_two_hop", "split_alias"):
        s = evaluate(range(50))[name]
        assert s.recall == 1.0 and s.false_alarm_rate == 0.0


def test_a_rename_by_word_order_is_one_payee_to_the_words_rule_and_two_to_the_stem_rule():
    """The cutoff reads characters, so a firm that types its own name in the
    other order is a new supplier. Reading the words is the whole fix."""
    renamed = ["offshore-consulting-ltd", "consulting-offshore-ltd",
               "Offshore Consulting Group"]
    log = [act(i, f"a{i}", "spend", 25_000, n, i) for i, n in enumerate(renamed)]
    assert rules(log) == []                                    # three payees, no split
    assert "split_payment" in rules(log, Limits(merge="tokens"))


def test_two_payees_sharing_an_identifier_stem_are_not_one_payee():
    """The same cutoff, pointed at the identifier namespace the published
    reconstruction is full of, adds two unrelated suppliers into one breach."""
    stem = ["destination-000003", "destination-000058"]        # 0.88 similar
    log = [act(i, f"a{i}", "spend", 25_000, stem[i % 2], i) for i in range(4)]
    assert "split_payment" in rules(log)
    assert rules(log, Limits(merge="tokens")) == []


def test_an_unknown_merge_rule_is_refused():
    with pytest.raises(ValueError):
        Monitor(Limits(merge="sounds_like")).review([act(0, "a", "spend", 1, "x")])
