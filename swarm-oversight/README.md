# swarm-oversight

Our project for the Apart Swarm Alignment sprint, track 4 (multi-agent oversight & control).

Payment systems give each agent its own spending cap. That is not the same as giving the person
behind the agents a cap: a handful of agents, each quietly inside its own limit, can move far
more money together than any one of them was allowed to. Banks have a name for the human
version — structuring — and rules against it. A 2026 security analysis of Google's AP2
([arXiv:2608.23858](https://arxiv.org/abs/2608.23858), Aviv et al., *Beyond the Mandate*)
formalises constraint enforcement *within* a mandate chain (a closed mandate stays inside its
open mandate's approved limits, and cumulative limits hold across reuse, SR5/SR7). We checked
this against the paper: neither line of defence binds the principal *across* separately issued
mandates to different agents. That cross-mandate aggregate is the seam we measure.

This repo measures that gap and what it costs to close it, in money:

- **The monitor** (`monitor.py`) watches the swarm as a whole: relays traced to where the money
  started, splits to one payee inside a window, payees renamed just enough. Each check is
  named and can be removed individually, so every rule is measured on its own.
- **The gateway** (`gateway.py`) replays each seeded log through four defenses and scores them
  the same way: the per-agent cap (what a protocol enforces today), a principal-wide ledger
  (prevention), the monitor inline (detection), and both. How it reacts to a flag — hold the
  payment, or freeze the swarm — is a setting, not a constant, because otherwise a rule and a
  model are compared on their judgement *and* their reflexes at once.
- **The experiments** (`experiments.py`, `report.py`) produce every table from the seeds alone,
  with 95% intervals, against attacks the limits were never tuned on.
- **The model in the loop** (`oversight.py`, `muse.py`) puts an assistant at the seam where a
  payment is about to settle, and charges it: calls, dollars from the published price table, and
  the seconds it spends inside the decision. The gateway only ever asks about payments the rules
  already let through, so a model can decline to hold but can never release.
- **The protocol arms** (`aicontrol.py`) run [AI Control](https://arxiv.org/abs/2312.06942) at
  that seam — trusted editing, untrusted monitoring, monitoring with the draft withheld,
  monitor-releases — over populations where the seats are honest, subverted, bought, paranoid or
  colluding, with honeypot probing. Each seat's competence and honesty is a free parameter.
- **The real swarm** (`tracegraph.py`) measures the published reconstruction of a real
  multi-agent incident (Swarm Traces, and the AI Village corpus behind it) with the same
  monitor, using only the fields the records actually carry.
- **The LLM arm** (`llm_arm.py`) asks whether language-model agents structure around an
  approval threshold without being told to. Four agents, one invoice, a policy that says
  payments to a vendor over a threshold need the principal's approval first — and nothing in
  any prompt about evading limits, splitting, or monitoring.
- **Live model evidence** (`gemini.py`, `live_experiments.py`) runs the identity and persuasion
  judgements against a real model (Gemini), with ground truth from the scenario construction:
  pairwise precision/recall of same-vendor merges, and a paired blind/honest/adversarial-draft
  review of true breaches. The Gemini client is a separate derived config; the OpenAI/MUSE
  baseline is untouched.
- **Log tampering** (`tampering.py`) lets the suspects edit their published log (rename payees,
  drop actions, under-report amounts) and compares detection on the agent log against the
  gateway, which reads settled instructions rather than reports.

## Running it

    pip install -e .[dev]
    pytest                                        # 109 tests, stdlib only
    python -m swarm_oversight.report --seeds 200  # writes results/summary.md + 7 CSVs
    python -m swarm_oversight.tracegraph          # the published incident data
    python -m swarm_oversight.aicontrol --seeds 50 --merge prefix --out results
    python -m swarm_oversight.aicontrol --seeds 50 --merge both --out results
    python -m swarm_oversight.aicontrol --seeds 200 --identity-sweep --out results
    python -m swarm_oversight.tampering --seeds 50 --out results
    python -m swarm_oversight.pdf_report --out report.pdf   # write-up: 4 body pages + refs/appendix

    # LLM arm: any OpenAI-compatible endpoint, or Meta's MUSE API
    export SWARM_LLM_BASE_URL=... SWARM_LLM_MODEL=... SWARM_LLM_API_KEY=...
    python -m swarm_oversight.llm_arm --seeds 10
    python -m swarm_oversight.llm_arm --scripted splitter --seeds 3   # no API needed

    # Live Gemini evidence (own key, own derived config; baseline untouched)
    export GEMINI_API_KEY=...
    python -m swarm_oversight.live_experiments identity --seeds 3 --out results/live
    python -m swarm_oversight.live_experiments persuasion --seeds 3 --out results/live
    python -m swarm_oversight.llm_arm --model gemini-3.5-flash-lite --topologies chain --seeds 2

The protocol tables (AI Control arms) still use offline stand-ins that answer through the
identical code path, so those numbers are about protocol structure and the price of a call,
not about any model's quality. The identity, persuasion, tampering and structuring results
below are live Gemini runs; they are small-n and establish mechanisms, not population rates.

## What the numbers say (200 seeds for the rules, 50 for the model arms)

**Detection is not the story; the money is.** The monitor catches every attack it was tuned on
and stays at 0 false alarms on the benign log lengths tested (40–300 ticks) — but at the gateway
it still lets 43–67% of the attack money settle before the flag fires. Detection buys time; it
does not stop the payment.

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
flagged 92% of benign swarms. The windowed fix holds 0.00 at every length tested (40–300 ticks).
A monitor paper that only reports per-run false alarms on short logs can hide a growing failure
rate; report flags per 1,000 actions, and report the horizon.

**The supervisor's edge turned out to be a string rule, and we could price it.** To make the
comparison fair, the model had to be able to differ from the rule at all, so payee identity
became a switch: merge names on a shared prefix and character similarity, or on the set of
meaningful words, or count each payment toward both. A model reading identity by words moves
pooled attack money from 0.785 to 0.752 for $0.0116 a log and 1.71 calls inside the payment
decision. Counting each payment toward *both* readings and holding the flagged payment instead
of freezing the swarm settles the same 0.752 — scenario by scenario, in every scenario with
attack money — holds less legitimate money (0.071 against 0.121), and costs nothing. Two string
comparisons and one change of reaction dominate a model arm. The honest reading of that is a
defect report on our own monitor: the shipped merge rule was wrong in both directions, merging
identifier namespaces that were nothing of the kind and missing a word-order swap, and the
model was being paid to compensate for the bug.

**Live Gemini confirms what a model adds, and what it does not.** On payee identity the model
merges renames and misspellings the string rules miss (split_renamed recall 1.00 against the
prefix rule's 0.00) without false-merging identifier namespaces (benign_stem precision 1.00,
zero false merges) — the genuine addition is knowing who a vendor is, not comparing strings.
On persuasion, an adversarial draft flipped 0 of 6 unambiguous breaches from hold to allow:
the channel does nothing where the arithmetic is clear. On structuring, four live agents given
a $900 invoice and a $500 approval threshold asked for approval and never split; remove the
threshold from the policy and the same model spontaneously split the invoice across two agents
in 1 of 2 episodes — the aggregate gap arising unprompted, and the monitor flagged it. And when
the suspects edit their published log (rename, drop, under-report), agent-log detection
collapses (0.50 → 0.01/0.00/0.00) while the gateway, which reads settled instructions not
reports, is unchanged. All live runs are small-n: mechanisms, not rates.

**Safety in the protocol arms is authority, not judgement.** Nothing behind the rules settled
more attack money than the rules did, in any of 294 (population, arm, scenario) triples —
including a fully bought reviewer and a colluding pair. Withholding the actor's draft from the
reviewer is the only arm that beats a colluding pair (0.785 → 0.755), because the text the
models choose is the channel they collude through. Letting a reviewer's *allow* clear a flag is
worse than having no reviewer: the same pair settles 0.923, the per-mandate figure, at 48 calls
a log. A honeypot retires a reviewer who cannot pass it — permanently, for the whole log —
which cuts a paranoid seat's bill 4.5x and gives back the attack money that seat was catching.
That is a control, not a fallback.

**The published incident data checks the shapes and refuses to validate two of them.** 189,579
records, 61,125 edges, fan-out median 1 and p99 12: swarms do fan out. But 0 nodes are both a
parent and a child, so relay depth is unobservable there, and 0 records carry a time, so no
windowed number can be scored on it. What it does give is the identity pool: 28,086 distinct
destinations, the busiest taking 14.6% of the marks. Moving $100,000 in $600-per-payee-window
slices needs 100000/600 ≈ 166.7 payees, so the observed pool covers 168.5 such runs without a
single amount over the bound.

## What this deliberately does not do

- It does not claim anything about real payment traffic. Every log scored end-to-end here is
  generated, and the attackers are written by us after seeing the rules — the adaptive limit,
  not the world.
- It does not model an intelligent adaptive attacker, only parameterized ones. The per-payee
  bound holds against the attacks we ran; a smarter attacker may find cheaper ways to spend
  the same money.
- It does not claim tamper-proofing against an attacker who controls the gateway. What it does
  show is that the gateway ledger is built from settled instructions outside the agents' reach,
  so the three log edits the suspects can make (rename, drop, under-report) collapse agent-log
  detection but leave the gateway unchanged. Tampering with the settlement path itself is out
  of scope.
- The protocol stand-ins are not models. Every AI Control result is a statement about a
  protocol under an assumed failure rate, and the rates are parameters. The live Gemini arms
  (identity, persuasion, structuring) are real but small-n.
- The free two-reading rule cannot do the thing a model is for. An abbreviation that only
  resolves if you know who the vendor is — "OC Advisory Ltd" for the same offshore consultancy
  — is not a string comparison, and no scenario here measures it. The held-out attacks that
  settle 1.000 in every column are that gap's neighbourhood, and a 1.000 there says something
  about our stand-in, not about models.
- Relay depth and every windowed figure are unvalidated externally: the incident reconstruction
  has no intermediate nodes and no timestamps, so it cannot check the parts of this that use
  both.
- Nothing here covers the HF incident, exfiltration, or code sabotage; the closest work on
  those (Makins et al., arXiv:2607.07368) is cited in the write-up, not replicated.

## Provenance and prior work

**No code in `swarm-oversight/` predates the sprint.** The earliest commit is 2026-11-07, inside
the hackathon window. The monitor, scenarios and harness came in through PR #1 (Rızgar Ozan) on
that date; the windowed fix, the gateway, the held-out attacks, the experiments, the identity
switch, the AI Control and live-model arms, the tampering demonstration and the real-data
measurement are the sprint work (Muhammad Hassaan Shaukat). The repository's `tabletop-twin/`
directory is an unrelated October 2026 project and contributes no code or ideas to this
submission. `report.pdf` is the write-up; it is built from the tables in `results/` at build
time, so it cannot drift from the numbers it describes.
