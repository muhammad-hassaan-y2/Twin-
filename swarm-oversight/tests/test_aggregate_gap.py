import tempfile
from pathlib import Path

from swarm_oversight.experiments import _score
from swarm_oversight.gateway import calibrate_ledger, peak_window_to_payee, replay
from swarm_oversight.model import Action
from swarm_oversight.monitor import CHECKS, Limits, Monitor, without
from swarm_oversight.scenarios import (AGENT_CAP, ALL, HELD_OUT, background_log,
                                       drip)

SEEDS = range(50)
LIM = Limits()


def recall(make, checks=CHECKS, seeds=SEEDS):
    m = Monitor(checks=checks)
    return sum(_score(m, make(s))[0] for s in seeds) / len(seeds)


# Each check, and the scenario that only it catches. Removing the check must
# bring the miss back; the meta-test below fails if a check has no control.
CONTROLS = {
    "relay": ALL["relay"],
    "relay_multi_hop": ALL["relay_two_hop"],
    "slow_split": ALL["split_wide"],
    "payee_alias": ALL["split_alias"],
}
# With windowed totals and long_window >= window, slow_split sees everything
# split_payment sees, so split_payment adds latency nothing and recall nothing.
SUBSUMED = {"split_payment": "slow_split"}


def test_every_check_has_a_negative_control_or_is_declared_subsumed():
    assert set(CONTROLS) | set(SUBSUMED) | {"agent_over_limit"} == set(CHECKS)


def test_removing_each_check_brings_its_miss_back():
    # The other checks still catch some runs by accident (the per-agent cap
    # trips on ~2/3 of relays), so the test is on the drop, not a floor.
    for check, make in CONTROLS.items():
        full = recall(make)
        assert full >= 0.95, check
        assert full - recall(make, without(check)) >= 0.25, check


def test_per_agent_check_is_the_one_that_catches_one_agent_over():
    log = [Action(0, "a", "spend", 40_000, "x", 0), Action(1, "a", "spend", 20_000, "y", 1)]
    assert [f.rule for _, f in Monitor().review(log)] == ["agent_over_limit"]
    assert Monitor(checks=without("agent_over_limit")).review(log) == []


def test_split_payment_really_is_subsumed():
    assert LIM.long_window >= LIM.window
    for make in list(ALL.values()) + list(HELD_OUT.values()):
        assert recall(make) == recall(make, without("split_payment"))


def test_windowed_total_has_no_swarm_false_alarms_on_long_benign_logs():
    swarm = {"relay", "split_payment", "slow_split"}

    def runs_flagged(mode):
        m = Monitor(Limits(payee_total=mode))
        return sum(any(f.rule in swarm for _, f in m.review(background_log(s, 200).actions))
                   for s in range(30))

    assert runs_flagged("window") == 0
    assert runs_flagged("lifetime") >= 24  # the first version, kept as the control


def test_held_out_attackers_stay_under_their_own_caps():
    for name, make in HELD_OUT.items():
        for s in SEEDS:
            sc = make(s)
            per = {}
            for a in sc.actions:
                if a.kind == "spend":
                    per[a.agent] = per.get(a.agent, 0) + a.amount
            assert max(per.values()) <= AGENT_CAP, name
            if sc.attack:
                total = sum(a.amount for a in sc.actions
                            if a.seq in sc.attack and a.kind == "spend")
                assert total > AGENT_CAP, name


def test_no_payee_gets_more_than_its_cap_per_window_through_the_inline_monitor():
    logs = [make(s) for make in list(ALL.values()) + list(HELD_OUT.values()) for s in SEEDS]
    logs += [drip(0, g, payees=p) for g in range(0, 81, 4) for p in (1, 2, 3)]
    for sc in logs:
        peak = peak_window_to_payee(replay(sc, "monitor").settled, LIM.long_window)
        assert peak <= LIM.per_payee, sc.name


def test_the_payee_bound_needs_the_monitor_and_its_long_window():
    sc = ALL["split_wide"](0)
    assert peak_window_to_payee(replay(sc, "per_mandate").settled, LIM.long_window) > LIM.per_payee
    assert peak_window_to_payee(replay(sc, "monitor", checks=without("slow_split")).settled,
                                LIM.long_window) > LIM.per_payee


def test_recall_overstates_protection():
    outs = [replay(ALL["split_payment"](s), "monitor") for s in SEEDS]
    assert all(o.detected for o in outs)
    assert all(0.5 < o.attack_settled_frac < 0.8 for o in outs)


def test_principal_cap_stops_a_legitimate_busy_week_the_monitor_lets_through():
    cap = calibrate_ledger(range(10_000, 10_050), window=LIM.long_window)
    busy = [HELD_OUT["benign_busy"](s) for s in SEEDS]
    assert sum(replay(sc, "ledger", ledger=cap).benign_stopped for sc in busy) > 0
    assert sum(replay(sc, "monitor").benign_stopped for sc in busy) == 0


def test_punctuation_only_payee_does_not_merge_with_everyone():
    log = [Action(0, "a", "spend", 35_000, "offshore", 0),
           Action(1, "b", "spend", 35_000, "---", 1)]
    assert Monitor().review(log) == []


def test_unknown_check_names_are_rejected():
    for bad in (lambda: Monitor(checks=("relay", "nope")), lambda: without("nope")):
        try:
            bad()
        except ValueError:
            continue
        raise AssertionError("expected ValueError")


def test_report_runs_end_to_end():
    from swarm_oversight import report
    import sys
    out = Path(tempfile.mkdtemp()) / "r"
    argv = sys.argv
    sys.argv = ["report", "--seeds", "5", "--out", str(out)]
    try:
        report.main()
    finally:
        sys.argv = argv
    text = (out / "summary.md").read_text(encoding="utf-8")
    assert "Evasion frontier" in text and len(list(out.glob("*.csv"))) == 7
