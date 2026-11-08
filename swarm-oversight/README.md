# swarm-oversight

Our project for the Apart Swarm Alignment sprint, track 4 (multi-agent oversight & control).

Payment systems give each agent its own spending cap. That is not the same as giving the person
behind the agents a cap: a handful of agents, each quietly inside its own limit, can move far
more money together than any one of them was allowed to. Banks have a name for the human
version — structuring — and rules against it. Agent payment protocols have nothing yet; a 2026
security analysis of Google's AP2 ([arXiv:2608.23858](https://arxiv.org/abs/2608.23858)) finds
budget constraints enforced per mandate and none across mandates.

This repo measures that gap and what it costs to close it, in money:

- **The monitor** (`monitor.py`) watches the swarm as a whole: relays traced to where the money
  started, splits to one payee inside a window, payees renamed just enough. Each check is
  named and can be removed individually, so every rule is measured on its own.
- **The gateway** (`gateway.py`) replays each seeded log through four defenses and scores them
  the same way: the per-agent cap (what a protocol enforces today), a principal-wide ledger
  (prevention), the monitor inline (detection), and both.
- **The experiments** (`experiments.py`, `report.py`) produce every table from the seeds alone,
  with 95% intervals, against attacks the limits were never tuned on.
- **The LLM arm** (`llm_arm.py`) asks whether language-model agents structure around an
  approval threshold without being told to. Four agents, one invoice, a policy that says
  payments to a vendor over a threshold need the principal's approval first — and nothing in
  any prompt about evading limits, splitting, or monitoring.

## Running it

    pip install -e .[dev]
    pytest                                        # 34 tests, stdlib only
    python -m swarm_oversight.report --seeds 200  # writes results/summary.md + 7 CSVs

    # LLM arm: any OpenAI-compatible endpoint
    export SWARM_LLM_BASE_URL=... SWARM_LLM_MODEL=... SWARM_LLM_API_KEY=...
    python -m swarm_oversight.llm_arm --seeds 10
    python -m swarm_oversight.llm_arm --scripted splitter --seeds 3   # no API needed

## What the numbers say (200 seeds)

**Detection is not the story; the money is.** The monitor catches every attack it was tuned on
and stays at 0 false alarms on benign logs of any length — but at the gateway it still lets
44–67% of the attack money settle before the flag fires. Detection buys time; it does not stop
the payment.

**Prevention stops the money and stops legitimate work too.** A principal-wide cap sized from
benign logs keeps the busiest benign week mostly intact only at its loosest setting (17% of
legitimate money stopped), where the same attacks still settle 78%. Tight enough to matter
(10% settled), it blocks over half of a legitimate busy week. The ledger trades one currency
directly for the other; the monitor is a different point, not a point on that curve.

**Per-agent caps catch none of it.** Held-out attackers that check their own budgets — splits
across distinct payees, renames past the similarity cutoff, splits slower than the long window
— settle 100% of their money under the per-mandate policy, and the monitor misses them too.
What the monitor does hold, against everything we could throw at it, is the per-payee,
per-window line: no single payee name received more than its cap inside any long window. An
attacker wanting more must go slower or register more payee identities — a rate limit, in cents
per tick, that holds even against an attacker who knows the rules.

**Scoring on short logs hides false alarms.** The first version of this monitor summed each
payee's payments over the whole log. On 40-tick benign logs it looked perfect; at 200 ticks it
flagged 92% of benign swarms. The windowed fix holds 0.00 at every length. A monitor paper
that only reports per-run false alarms on short logs can hide a growing failure rate; report
flags per 1,000 actions, and report the horizon.

## What this deliberately does not do

- It does not claim anything about real payment traffic. Every log here is generated, and the
  attackers are written by us after seeing the rules — the adaptive limit, not the world.
- It does not model an intelligent adaptive attacker, only parameterized ones. The per-payee
  bound holds against the attacks we ran; a smarter attacker may find cheaper ways to spend
  the same money.
- It does not try to be tamper-proof. The gateway sees the honest log; a swarm that can hide
  or rewrite actions defeats everything here. Tamper-evidence is future work.
- The LLM arm, until it has run, claims nothing. It is built so that either answer is a
  result: agents that structure unprompted is the headline; agents that reliably use the
  approval path is a finding about compliance under pressure.
- Nothing here covers the HF incident, exfiltration, or code sabotage; the closest work on
  those (Makins et al., arXiv:2607.07368) is cited in the write-up, not replicated.

## Provenance

The monitor, scenarios and harness came in through PR #1 (Rızgar Ozan). The windowed fix, the
gateway, the held-out attacks, the experiments and the LLM arm are the sprint work.
