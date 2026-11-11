"""The two frontiers must hold for the reason claimed, and each carries a
control that fails if the reason is removed."""
from swarm_oversight.frontiers import adaptive_attack, makins_curve
from swarm_oversight.monitor import Limits

LIM = Limits()
CURVE = makins_curve(limits=LIM)


def test_per_mandate_leakage_rises_with_the_number_of_agents():
    outs = [r["per_mandate_out"] for r in CURVE]
    assert outs == sorted(outs) and outs[0] < outs[-1]
    assert all(r["per_mandate_detected"] == 0 for r in CURVE)


def test_the_per_payee_bound_caps_leakage_independent_of_n():
    outs = {r["monitor_out"] for r in CURVE}
    assert len(outs) == 1, outs                      # flat in N
    assert outs.pop() <= LIM.per_payee               # never over one bound
    assert all(r["monitor_detected"] == 1 for r in CURVE)


def test_removing_the_split_checks_makes_the_monitor_leak_like_per_mandate():
    # Negative control: the cap comes from the split checks, not the gateway.
    for r in CURVE:
        assert r["blind_out"] == r["per_mandate_out"], r["n"]
    assert [r["blind_out"] for r in CURVE] == [r["per_mandate_out"] for r in CURVE]
    assert CURVE[-1]["blind_out"] > CURVE[0]["blind_out"]


def test_the_adaptive_attacker_learns_the_exact_bound_and_window():
    r = adaptive_attack(freeze=False)
    assert r["learned_b"] == r["true_bound"]
    assert r["learned_w"] == r["true_window"] + 1    # inclusive window: W+1 is safe
    assert r["rejected_probes"] > 0 and r["detected"]


def test_the_adaptive_attacker_approaches_the_bound_but_never_exceeds_it():
    r = adaptive_attack(freeze=False)
    assert r["leaked"] <= r["bound"]
    assert r["leaked_frac_of_bound"] > 0.8           # reaches the ceiling


def test_freeze_stops_the_adaptive_attacker_at_the_first_probe():
    # Negative control on the reaction: hold-only lets it learn and drip; freeze
    # ends it on the first rejected probe, so it never learns the bound.
    r = adaptive_attack(freeze=True)
    assert r["frozen"] and r["rejected_probes"] == 1
    assert r["learned_b"] == 0 and r["leaked"] == 0
    hold = adaptive_attack(freeze=False)
    assert hold["leaked"] > r["leaked"]
