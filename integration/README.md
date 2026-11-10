# Oversight Twin

A PayPal-centred settlement hub for the twin's audit, tax and finance agents.
One payment machine and one principal-wide swarm monitor sit behind every fee.
The chain records agreements; PayPal handles the payment, not the legal opinion.
This branch extends tabletop-twin without changing swarm-oversight.

## Settlement

Binding findings become payment instructions. With a contract bus, the firm first
proposes, accepts and attests the agreements on the local EVM. The hub uses their
actual chain IDs and amounts, requires both explicit caller clearance and the
recorded counterparty's countersignature, then submits through swarm oversight.
Only a confirmed PayPal capture allows the chain agreement to become settled.
A lost chain-write reply stays pending for reconciliation; it never causes another payment.

Without a bus, the same hub accepts simulated instructions for tests. Those IDs
are not chain records. Keep one hub instance per principal and currency: repeated
or concurrent calls reuse its payment record, and changed terms under an existing
ID are refused. Unknown outcomes permit lookup, not another charge.

## EU evidence

The roster has 26 roles: the original 18, three historical VAT comparators, two
additional audit reviewers, and three Eurostat reporters. Rates, financial totals
and jurisdiction are explicit case facts; absent facts do not become zeroes.

The VAT source is the original 2006 Directive, not a current consolidated national
tax code. Its standard-rate provision includes an historical validity interval;
reduced-rate exceptions exist. These agents compare the snapshot and escalate
below-floor readings rather than certify compliance. Small-undertaking claims
require human review of national thresholds, headcount and multi-year eligibility.
The Eurostat reporters provide context, not lending or solvency decisions.

From `tabletop-twin/backend`, refresh the narrow statistical series and then derive
priors with their table, jurisdiction, period, dimensions and flags:

```sh
python -m twin.audit.harvest --only finance
python -m twin.audit.calibrate
```

The normal full harvest includes these finance slices too. Calibration needs the
local statutory corpus; after changing that corpus, rebuild its citation index with
`python -m twin.audit.index build`. A clean checkout can run the integration tests
from bundled derived priors without fetching or recalibrating anything.

## Verification

From `integration`:

```sh
python -m pytest -q
python -m oversight_twin.demo
```

Tests cover every roster role through the real PayPal transport against a local
HTTP fake, human and chain gates, shared-payee limits, repeated calls, missing
facts, and sandbox-only configuration. With Node and chain dependencies present,
the suite also runs the local EVM-to-PayPal-to-EVM path using a temporary journal.

The aggregate experiment submits three payments of 25,000 minor units to one
payee against a 60,000 bound. With oversight, 50,000 settles; removing the bound
lets all 75,000 settle. The demo also adds a legitimate 20,000 payment to a second
payee: freeze stops it, while hold-only permits it. Negative controls remove human
clearance, source figures or jurisdiction to show what each check contributes.

The backend's offline evaluation passes 115 checks over 26 scenarios, with all
18 guard-removal controls detecting their seeded failure and all 34 scored rules
reached. Contextual size ceilings and the renewable delegation term are not
counted as enforced thresholds.

## Optional real sandbox smoke

Supply a PayPal **sandbox** app's credentials through the process environment,
never a tracked file or chat message:

- `PAYPAL_CLIENT_ID`
- `PAYPAL_SECRET`
- `PAYPAL_ENVIRONMENT=sandbox`
- `PAYPAL_SANDBOX_SMOKE=1` (explicit opt-in)

```sh
python -m oversight_twin.live_smoke
```

Without keys or opt-in it skips without network access. It refuses live or
misspelled environments and attempts only USD 1.00 in sandbox funds. Missing
buyer approval remains pending, not captured; provider refusal is a failing
payment test, not a passing one. Exit codes: 0 confirmed capture or explicitly
reported skip; 1 failure; 2 disallowed configuration; 3 unresolved/pending.

## Deliberate limits

This is a single-process prototype, not a production payment or custody service.
The socket fake models approved funding; real PayPal requires buyer approval.
Orders collect for the authenticated merchant: a role's `reference_id` is an
accounting label, **not** a PayPal payout destination. No arbitrary-agent payouts,
VAT filing, national tax certification or browser checkout is implemented.

The local chain uses deterministic demonstration keys. `HumanGate` is a trusted
caller's clearance interface, not authentication. The payment journal and order-ID
mapping are in memory; crash-safe recovery, distributed locking, durable approval
storage and an atomic transaction across PayPal and the chain are not claimed.
Never restart or create a new payment to resolve an unknown outcome.
