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

## CRM-fed audit pipeline

A dataset is a named batch of engagements, each stated in the figures a client's
file and fee ledger give. The pipeline parses every row strictly - a boolean is
not an integer, a rate must be finite, required columns cannot be blank - and then
checks the rows against each other: standard against reduced VAT rate, a client's
fee against the firm's total, a small-undertaking claim against the facts that
would support it, a missing jurisdiction, a missing multi-year fee history.
Errors block the row before any audit; warnings mark it for review and still
audit it. A blocked row is reported with the codes that blocked it and is never
priced.

A surviving row is reviewed by all 26 desks. Every binding `clear` or `hold`
finding on a priced engagement becomes an instruction, but nothing moves until a
person clears it by name. One aggregate bound applies across the whole principal,
not per engagement, and a refusal is reported on the instruction rather than
swallowed. Agreement IDs are dataset-scoped and stable, so replaying the same
batch neither reprices nor charges twice; new terms under an existing ID are a
conflict. A zero-fee engagement opens no instruction.

The pipeline can also write its CRM view: one JSON line per engagement with the
run ID, quality, issue codes, verdict counts and per-instruction state. CRM and
tool adapters read JSON files (a list, or an object with `records` and an optional
`dataset_id`) and CSV (one row per engagement, semicolon-separated list cells).
Provenance is the file's own name, never the local path. A batch whose dataset
does not match the pipeline's is refused before anything is audited.

## HTTP edge

The pipeline is served with bearer-token authentication and fails closed:

```sh
export OVERSIGHT_API_TOKEN=...            # required for any authenticated route
export OVERSIGHT_RAIL=paypal              # or simulated, which is labelled as such
export OVERSIGHT_PAYEE="Ashgrove Audit LLP"
export OVERSIGHT_PER_AGENT_LIMIT_CENTS=50000
export OVERSIGHT_PER_PAYEE_LIMIT_CENTS=60000
# OVERSIGHT_WINDOW=10 and OVERSIGHT_LONG_WINDOW=60 are optional
python -m uvicorn oversight_twin.api:app
```

- `GET /health` is unauthenticated and reports only the rail, recovery model and
  whether a token and payee are configured; it never echoes the token.
- `POST /v1/runs` audits a dataset's records and optionally applies named
  clearances.
- `GET /v1/runs/{run_id}` returns a run's latest state.
- `POST /v1/runs/{run_id}/clear` clears named instructions in a run.

Unknown runs are 404, unknown agreements and invalid bodies are 422, and with no
rail, no payee, no aggregate bound or no token the service answers 503 with the
missing setting rather than falling back to a simulated rail. The `paypal` rail
still accepts only sandbox credentials; live capture is refused.

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

The pipeline's runs and clearance state are likewise in memory: a restart forgets
runs, while the PayPal order memory goes with the transport it belongs to. The
HTTP token authenticates a caller to this process; it does not identify which
person cleared a payment. The CRM adapters read files - there is no vendor API
client, webhook receiver, schema registry or retry queue - and outcome lines are
appended, not reconciled against a CRM record. Quality checks are structural: they
find contradictions and missing facts, not the correctness of the facts a CRM was
told.

