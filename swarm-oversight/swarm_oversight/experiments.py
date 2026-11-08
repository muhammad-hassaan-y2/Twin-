"""The experiments behind the write-up. Each returns plain rows (dicts), so the
report can print them and write them to CSV without any plotting library."""
from __future__ import annotations

import math
import random
from collections import Counter

from .gateway import POLICIES, LedgerCap, calibrate_ledger, peak_window_to_payee, replay
from .model import Scenario
from .monitor import CHECKS, Limits, Monitor, without
from .scenarios import ALL, HELD_OUT, background_log, drip

ATTACKS_TUNED = {k: v for k, v in ALL.items() if k != "benign"}
ATTACKS_HELD_OUT = {k: v for k, v in HELD_OUT.items() if k != "benign_busy"}
BENIGN = {"benign": ALL["benign"], "benign_busy": HELD_OUT["benign_busy"]}
SWARM_RULES = {"relay", "split_payment", "slow_split"}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def mean_ci(xs: list[float], z: float = 1.96) -> tuple[float, float, float]:
    n = len(xs)
    m = sum(xs) / n
    if n < 2:
        return (m, m, m)
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))
    h = z * sd / math.sqrt(n)
    return (m, m - h, m + h)


def _score(monitor: Monitor, sc: Scenario) -> tuple[bool, bool, int | None, set[str]]:
    flags = monitor.review(sc.actions)
    hits = [(i, f) for i, f in flags if set(f.seqs) & sc.attack]
    false = any(not set(f.seqs) & sc.attack for _, f in flags)
    latency = None
    if hits:
        last = max(i for i, a in enumerate(sc.actions) if a.seq in sc.attack)
        latency = max(0, min(i for i, _ in hits) - last)
    return bool(hits), false, latency, {f.rule for _, f in hits}


def detection(seeds: range, limits: Limits | None = None) -> list[dict]:
    """Recall and false alarms on the tuned set and on the held-out set."""
    monitor = Monitor(limits)
    rows = []
    for split, group in (("tuned", ALL), ("held_out", HELD_OUT)):
        for name, make in group.items():
            caught = false = 0
            lat: list[int] = []
            by_rule: Counter[str] = Counter()
            for seed in seeds:
                sc = make(seed)
                c, f, l, rules = _score(monitor, sc)
                caught += c
                false += f
                if l is not None:
                    lat.append(l)
                by_rule.update(rules)
            n = len(seeds)
            attack = bool(make(seeds[0]).attack)
            lo, hi = wilson(caught, n) if attack else (0.0, 0.0)
            flo, fhi = wilson(false, n)
            rows.append(dict(split=split, scenario=name, runs=n,
                             recall=caught / n if attack else None,
                             recall_lo=lo if attack else None,
                             recall_hi=hi if attack else None,
                             false_alarm=false / n, false_alarm_lo=flo,
                             false_alarm_hi=fhi,
                             mean_latency=sum(lat) / len(lat) if lat else None,
                             caught_by=";".join(f"{r}:{c}" for r, c in sorted(by_rule.items()))))
    return rows


def ablation(seeds: range) -> list[dict]:
    """Recall with each check removed, plus a per-agent-cap-only baseline."""
    arms = [("full", CHECKS), ("per_agent_only", ("agent_over_limit",))]
    arms += [(f"minus_{c}", without(c)) for c in CHECKS if c != "agent_over_limit"]
    rows = []
    for arm, checks in arms:
        monitor = Monitor(checks=checks)
        for name, make in {**ATTACKS_TUNED, **ATTACKS_HELD_OUT}.items():
            caught = sum(_score(monitor, make(s))[0] for s in seeds)
            lo, hi = wilson(caught, len(seeds))
            rows.append(dict(arm=arm, scenario=name, recall=caught / len(seeds),
                             recall_lo=lo, recall_hi=hi))
    return rows


def horizon(seeds: range, ticks: tuple[int, ...] = (40, 80, 120, 160, 200, 300)) -> list[dict]:
    """Benign logs of growing length: how often each kind of flag fires.

    Swarm-rule flags on a benign log are false alarms. A per-agent flag on a
    long benign log is an agent using up its lifetime budget, which a gateway
    would refuse anyway, so it is reported on its own line."""
    rows = []
    for mode in ("lifetime", "window"):
        monitor = Monitor(Limits(payee_total=mode))
        for t in ticks:
            swarm_runs = agent_runs = swarm_flags = n_actions = 0
            for seed in seeds:
                sc = background_log(seed, t)
                rules = [f.rule for _, f in monitor.review(sc.actions)]
                swarm = [r for r in rules if r in SWARM_RULES]
                swarm_runs += bool(swarm)
                agent_runs += "agent_over_limit" in rules
                swarm_flags += len(swarm)
                n_actions += len(sc.actions)
            lo, hi = wilson(swarm_runs, len(seeds))
            rows.append(dict(payee_total=mode, ticks=t,
                             swarm_false_alarm_runs=swarm_runs / len(seeds),
                             lo=lo, hi=hi,
                             swarm_flags_per_1000_actions=1000 * swarm_flags / n_actions,
                             agent_budget_exhausted_runs=agent_runs / len(seeds)))
    return rows


def gateway(seeds: range, cap: LedgerCap) -> list[dict]:
    """Money that got out (attacks) and legitimate money stopped (benign only)."""
    rows = []
    for policy in POLICIES:
        for name, make in {**ATTACKS_TUNED, **ATTACKS_HELD_OUT}.items():
            m, lo, hi = mean_ci([replay(make(s), policy, ledger=cap).attack_settled_frac
                                 for s in seeds])
            rows.append(dict(policy=policy, scenario=name, kind="attack",
                             metric="attack_settled_frac", mean=m, lo=lo, hi=hi))
        for name, make in BENIGN.items():
            outs = [replay(make(s), policy, ledger=cap) for s in seeds]
            m, lo, hi = mean_ci([o.benign_stopped_frac for o in outs])
            rows.append(dict(policy=policy, scenario=name, kind="benign",
                             metric="benign_stopped_frac", mean=m, lo=lo, hi=hi,
                             runs_with_a_stop=sum(o.false_stop for o in outs) / len(outs)))
    return rows


def ledger_tradeoff(seeds: range, calib_seeds: range,
                    quantiles: tuple[float, ...] = (0.5, 0.9, 0.99, 1.0),
                    windows: tuple[int, ...] = (20, 60)) -> list[dict]:
    """Prevention's price: a tighter principal cap stops more attack money and
    more of the legitimate busy week. The monitor is one point, not a curve."""
    rows = []
    attack = {**ATTACKS_TUNED, **ATTACKS_HELD_OUT}

    def point(policy: str, cap: LedgerCap | None, label: str) -> dict:
        atk = [replay(make(s), policy, ledger=cap).attack_settled_frac
               for make in attack.values() for s in seeds]
        busy = [replay(HELD_OUT["benign_busy"](s), policy, ledger=cap).benign_stopped_frac
                for s in seeds]
        return dict(arm=label, policy=policy,
                    cap=cap.cap if cap else None, window=cap.window if cap else None,
                    attack_settled_frac=mean_ci(atk)[0],
                    benign_busy_stopped_frac=mean_ci(busy)[0])

    rows.append(point("per_mandate", None, "per_mandate"))
    rows.append(point("monitor", None, "monitor"))
    for w in windows:
        for q in quantiles:
            cap = calibrate_ledger(calib_seeds, window=w, quantile=q)
            rows.append(point("ledger", cap, f"ledger_w{w}_q{q}"))
    return rows


def frontier(gaps: tuple[int, ...] = tuple(range(0, 81, 4)),
             payees: tuple[int, ...] = (1, 2, 3), cap: LedgerCap | None = None,
             limits: Limits | None = None) -> list[dict]:
    """The evasion frontier. The attacker drips 7 x 20,000 to `payees` names,
    `gap` ticks apart. Under the inline monitor no single payee name receives
    more than per_payee inside long_window+1 ticks, so an attacker who wants
    more must go slower or register more payee identities."""
    lim = limits or Limits()
    rows = []
    for p in payees:
        for g in gaps:
            sc = drip(0, g, payees=p)
            row = dict(payees=p, gap=g, attack_total=sum(a.amount for a in sc.actions),
                       per_payee_bound=lim.per_payee)
            for policy in ("per_mandate", "monitor") + (("ledger",) if cap else ()):
                o = replay(sc, policy, limits=lim, ledger=cap)
                row[f"{policy}_settled"] = o.attack_settled
                row[f"{policy}_stopped"] = o.detected
                if policy == "monitor":
                    row["monitor_peak_to_one_payee"] = peak_window_to_payee(
                        o.settled, lim.long_window)
            rows.append(row)
    return rows


def visibility(seeds: range, fractions: tuple[float, ...] = (1.0, 0.9, 0.75, 0.5, 0.25)) -> list[dict]:
    """Recall when the monitor sees only part of the log: a random fraction of
    actions, or every spend but no transfers."""
    monitor = Monitor()
    arms = [(f"keep_{q}", q, True) for q in fractions] + [("no_transfers", 1.0, False)]
    rows = []
    for arm, q, transfers in arms:
        for name, make in {**ATTACKS_TUNED, **ATTACKS_HELD_OUT}.items():
            caught = 0
            for seed in seeds:
                sc = make(seed)
                rng = random.Random(seed * 7919 + 1)
                seen = [a for a in sc.actions
                        if (transfers or a.kind != "transfer") and rng.random() < q]
                caught += _score(monitor, Scenario(sc.name, seed, seen, sc.attack))[0]
            lo, hi = wilson(caught, len(seeds))
            rows.append(dict(arm=arm, scenario=name, recall=caught / len(seeds),
                             recall_lo=lo, recall_hi=hi))
    return rows
