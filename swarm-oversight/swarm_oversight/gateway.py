"""Where the money actually moves: a payment gateway replaying a log.

Each policy decides, action by action, whether a payment settles. Scores are in
cents, so prevention and detection can be compared on the same axis: how much
attack money got out, and how much legitimate spending was stopped.

    per_mandate     each agent's own cap, refused at the gateway. This is the
                    per-mandate budget a payment protocol enforces today.
    ledger          per_mandate plus one cap on the whole principal's spending
                    over a rolling window, refused at the gateway.
    monitor         per_mandate plus the swarm monitor inline: the payment that
                    raises a flag is held and the swarm is frozen for review.
    ledger+monitor  both.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from .model import Action, Scenario
from .monitor import CHECKS, Limits, Monitor


@dataclass(frozen=True)
class LedgerCap:
    cap: int        # cents the whole principal may spend inside `window` ticks
    window: int


@dataclass(frozen=True)
class Outcome:
    attack_total: int
    attack_settled: int
    benign_total: int
    benign_stopped: int
    detected: bool          # some flag or refusal touched an attack action
    false_stop: bool        # some benign payment was refused, held or frozen
    settled: tuple[Action, ...] = ()   # spends that actually went out

    @property
    def attack_settled_frac(self) -> float:
        return self.attack_settled / self.attack_total if self.attack_total else 0.0

    @property
    def benign_stopped_frac(self) -> float:
        return self.benign_stopped / self.benign_total if self.benign_total else 0.0


POLICIES = ("per_mandate", "ledger", "monitor", "ledger+monitor")


def replay(sc: Scenario, policy: str, limits: Limits | None = None,
           ledger: LedgerCap | None = None,
           checks: tuple[str, ...] = CHECKS) -> Outcome:
    if policy not in POLICIES:
        raise ValueError(policy)
    lim = limits or Limits()
    use_ledger = "ledger" in policy
    use_monitor = "monitor" in policy
    if use_ledger and ledger is None:
        raise ValueError("ledger policy needs a LedgerCap")
    # The per-agent cap is enforced by the gateway itself, so the monitor does
    # not need to re-flag it.
    session = Monitor(lim, tuple(c for c in checks if c != "agent_over_limit")).session()
    spent: dict[str, int] = {}
    settled: deque[tuple[int, int]] = deque()  # (tick, amount) inside ledger window
    settled_sum = 0
    frozen = False
    out = dict(attack_total=0, attack_settled=0, benign_total=0, benign_stopped=0)
    detected = false_stop = False
    went_out: list[Action] = []

    for a in sc.actions:
        is_attack = a.seq in sc.attack
        if use_ledger:
            while settled and a.tick - settled[0][0] >= ledger.window:
                settled_sum -= settled.popleft()[1]
        if a.kind == "spend":
            out["attack_total" if is_attack else "benign_total"] += a.amount
        ok = _decide(a, frozen, lim, spent, ledger if use_ledger else None, settled_sum)
        if ok and use_monitor and session.observe(a):
            ok, frozen = False, True
        if a.kind != "spend":
            continue
        if ok:
            went_out.append(a)
            spent[a.agent] = spent.get(a.agent, 0) + a.amount
            if use_ledger:
                settled.append((a.tick, a.amount))
                settled_sum += a.amount
            if is_attack:
                out["attack_settled"] += a.amount
        elif is_attack:
            detected = True
        else:
            out["benign_stopped"] += a.amount
            false_stop = True
    return Outcome(detected=detected, false_stop=false_stop,
                   settled=tuple(went_out), **out)


def peak_window_to_payee(settled: tuple[Action, ...], span: int) -> int:
    """Most money any single payee name received inside span+1 consecutive ticks."""
    best = 0
    by_payee: dict[str, list[Action]] = {}
    for a in settled:
        by_payee.setdefault(a.payee, []).append(a)
    for pays in by_payee.values():
        for p in pays:
            best = max(best, sum(q.amount for q in pays if 0 <= q.tick - p.tick <= span))
    return best


def _decide(a: Action, frozen: bool, lim: Limits, spent: dict[str, int],
            ledger: LedgerCap | None, settled_sum: int) -> bool:
    if frozen:
        return False
    if a.kind != "spend":
        return True
    if spent.get(a.agent, 0) + a.amount > lim.per_agent:
        return False
    if ledger is not None and settled_sum + a.amount > ledger.cap:
        return False
    return True


def calibrate_ledger(seeds: range, window: int, ticks: int = 100,
                     quantile: float = 0.99) -> LedgerCap:
    """Set the principal cap from benign logs only: the given quantile of the
    largest rolling-window spend seen per log. Use seeds the evaluation never sees."""
    from .scenarios import background_log
    peaks = []
    for seed in seeds:
        acts = background_log(seed, ticks).actions
        best = 0
        for i, a in enumerate(acts):
            total = sum(b.amount for b in acts[: i + 1]
                        if b.kind == "spend" and a.tick - b.tick < window)
            best = max(best, total)
        peaks.append(best)
    peaks.sort()
    return LedgerCap(cap=peaks[min(len(peaks) - 1, int(quantile * len(peaks)))],
                     window=window)
