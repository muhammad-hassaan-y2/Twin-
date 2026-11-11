# Oversight Twin

Most agentic payments products harden each agent. That leaves the failure nobody is
watching: four agents, each inside its own approved mandate, spending the principal's
money past the principal's own limit. Oversight Twin is the seam where that gets caught.

A firm's 26 audit desks review a client's engagement. The findings become payment
instructions. A principal-wide monitor - not a per-agent cap - holds the aggregate
bound, a named person clears the money, PayPal moves it, and the chain records the
agreement. The merchant side of the same firm then bills the client from the review:
the amount comes from the firm's own figures, never from a model, and only a human's
name can approve a capture.

Three baselines meet here: the firm (`tabletop-twin`), the monitor (`swarm-oversight`)
and one PayPal rail that both of them use. `integration` is the only tree that extends
`tabletop-twin`, and it does not change `swarm-oversight`.

## The sixty-second tour

```sh
pip install -e ".[dev]"
python -m oversight_twin.showcase      # the whole story, measured, no key or network
python -m pytest -q                    # offline suite; PostgreSQL tests skip without a DSN
```

The showcase prints four acts, and every figure in them is computed during the run:

1. **The gap.** Four mandates, each approved and under its own ceiling, total 950.00
   against a 600.00 principal bound. Without oversight 950.00 settles; with it 500.00.
   The difference - 450.00 - is money no per-agent check can see.
2. **The price.** A reviewed engagement carries 26 findings across the desks and is
   priced at 200.00 from the case file, not from a model.
3. **The refusal.** A model asks to bill 0.01; the server prices 200.00 and reports the
   argument it ignored. A capture with no approver is refused. A capture signed by a
   person goes through.
4. **The restart.** A new process opens the same book, finds the order already captured,
   raises no second order, and prints the ledger with the actor and request id of each
   fact.

Then serve it:

```sh
export OVERSIGHT_API_TOKEN=...            # required; there is no default secret
export OVERSIGHT_RAIL=simulated           # a labelled, no-money rail; or paypal for sandbox
export OVERSIGHT_PAYEE="Ashgrove Audit LLP"
export OVERSIGHT_PER_AGENT_LIMIT_CENTS=50000
export OVERSIGHT_PER_PAYEE_LIMIT_CENTS=60000
python -m uvicorn oversight_twin.api:app
```

`http://127.0.0.1:8000/` is a one-page demo: type a token, read the book, open an
invoice, capture it under a name, watch the ledger grow, and ask the assistant a
question with the invoices you are willing to clear. The page carries no token and no
key; it sends the token you type only as an `Authorization` header.

## Settlement

Binding findings become payment instructions. With a contract bus, the firm first
proposes, accepts and attests the agreements on the local EVM. The hub uses their
actual chain IDs and amounts, requires both explicit caller clearance and the recorded
counterparty's countersignature, then submits through swarm oversight. Only a confirmed
PayPal capture allows the chain agreement to become settled. A lost chain-write reply
stays pending for reconciliation; it never causes another payment.

Without a bus, the same hub accepts simulated instructions for tests. Those IDs are not
chain records. Keep one hub instance per principal and currency: repeated or concurrent
calls reuse its payment record, and changed terms under an existing ID are refused.
Unknown outcomes permit lookup, not another charge.

## CRM-fed audit pipeline

A dataset is a named batch of engagements, each stated in the figures a client's file
and fee ledger give. The pipeline parses every row strictly - a boolean is not an
integer, a rate must be finite, required columns cannot be blank - and then checks the
rows against each other: standard against reduced VAT rate, a client's fee against the
firm's total, a small-undertaking claim against the facts that would support it, a
missing jurisdiction, a missing multi-year fee history. Errors block the row before any
audit; warnings mark it for review and still audit it. A blocked row is reported with
the codes that blocked it and is never priced.

A surviving row is reviewed by all 26 desks. Every binding `clear` or `hold` finding on
a priced engagement becomes an instruction, but nothing moves until a person clears it
by name. One aggregate bound applies across the whole principal, not per engagement, and
a refusal is reported on the instruction rather than swallowed. Agreement IDs are
dataset-scoped and stable, so replaying the same batch neither reprices nor charges
twice; new terms under an existing ID are a conflict. A zero-fee engagement opens no
instruction.

The pipeline can also write its CRM view: one JSON line per engagement with the run ID,
quality, issue codes, verdict counts and per-instruction state. CRM and tool adapters
read JSON files (a list, or an object with `records` and an optional `dataset_id`) and
CSV (one row per engagement, semicolon-separated list cells). Provenance is the file's
own name, never the local path. A batch whose dataset does not match the pipeline's is
refused before anything is audited.

## HTTP edge

The service fails closed. With no token, no named payee, no rail or no aggregate bound
the routes answer 503 and name the missing setting; a run never falls back to a fake
rail without being labelled one.

| Setting | Meaning |
| --- | --- |
| `OVERSIGHT_API_TOKEN` | one shared bearer token; `OVERSIGHT_OPERATOR` names its holder (default `operator`) |
| `OVERSIGHT_API_TOKENS` | a JSON object `{token: name}`: one named identity per operator |
| `OVERSIGHT_RATE_LIMIT_PER_MIN` | requests per operator per minute (default 120, in-process) |
| `OVERSIGHT_MAX_BODY_BYTES` | largest accepted request body (default 1 500 000) |
| `OVERSIGHT_MAX_INVOICE_CENTS` | per-invoice pricing ceiling; a fee above it is refused, not clamped |
| `OVERSIGHT_RAIL` | `paypal` (sandbox only) or `simulated`, which labels itself |
| `OVERSIGHT_PAYEE` | the firm that receives these fees and invoices |
| `OVERSIGHT_PER_AGENT_LIMIT_CENTS`, `OVERSIGHT_PER_PAYEE_LIMIT_CENTS` | the aggregate bound the monitor enforces |
| `OVERSIGHT_WINDOW`, `OVERSIGHT_LONG_WINDOW` | the monitor's windows in seconds (default 10 and 60) |
| `OVERSIGHT_DATABASE_URL`, `OVERSIGHT_DB_SCHEMA` | durable book, and the schema it lives in (default `oversight`) |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | the assistant and invoice copy |
| `PAYPAL_CLIENT_ID`, `PAYPAL_SECRET`, `PAYPAL_ENVIRONMENT` | sandbox credentials for the `paypal` rail |

Routes:

- `GET /health` is unauthenticated and reports the rail, the billing store kind,
  whether a model is configured, whether a token is set, how many operators there are,
  and whether attribution is per-operator or shared. It never echoes a token or a key.
- `POST /v1/runs` audits a dataset's records and optionally applies named clearances.
- `GET /v1/runs/{run_id}` returns a run's latest state.
- `POST /v1/runs/{run_id}/clear` clears named instructions in a run.
- `POST /v1/billing/prepare` prices reviewed engagements into client invoices.
- `GET /v1/billing/invoices` and `GET /v1/billing/invoices/{id}` read the book. Reading
  one invoice asks the provider for its state and reconciles the book to it, recording
  the fact when they disagree.
- `POST /v1/billing/invoices/{id}/open` creates the PayPal order for a priced invoice.
- `POST /v1/billing/invoices/{id}/capture` captures a buyer-approved payment.
- `GET /v1/billing/invoices/{id}/events` returns that invoice's ledger.
- `GET /v1/billing/summary` reports billed, collected and outstanding.
- `GET /v1/billing/tools`, `POST /v1/billing/tool` and `POST /v1/billing/ask` are the
  assistant surface, described below.

Every response carries an `X-Request-ID` (the caller's own, if supplied and sane), and
the id is written into every ledger fact the request produces. Unknown runs and invoices
are 404, invalid bodies 422, an operator past its rate 429, an oversized body 413.

With `OVERSIGHT_API_TOKENS`, the caller's name is the operator's own: a capture signed
for somebody else is 403, and omitting `approved_by` signs as the caller. With the
single shared token the body must still name the approver - the process cannot tell who
is on the other end of a shared secret, so it will not sign for them.

## Billing for businesses

A reviewed engagement can be sold as well as paid for. An invoice is priced at the
firm's own fee from the case and its 26 findings; a breach, an unreviewed engagement, a
zero fee or a fee above the configured ceiling is refused rather than billed. One
engagement holds at most one invoice, enforced in the store as well as in code; different
terms under the same engagement are recorded as a conflict, not silently repriced.

The merchant book keeps one PayPal order per invoice, records the approval link, captures
only after the buyer approves, and captures once. A lost reply becomes `unknown` and is
reconciled by reading the order id the book already stored - never by creating or
charging a second one. That matters more than it sounds: the idempotency key lives in
process memory, the order id lives in the book, so a restart reconciles from the book.
Billed, collected, outstanding and the invoices that still need a person are reported
together.

The assistant surface is a small JSON-Schema tool catalogue: list, price, open, status,
capture and summary. A model may price and open, but it cannot supply an amount - extra
arguments such as `amount_cents` are ignored and reported - and it cannot capture without
`approved_by`, the name of the person who approved the payment. Beyond that, a question
may only capture the invoices the caller named in `approved_invoices`; anything else is
refused, and tool output is treated as data rather than instructions, so an invoice line
that reads like a command is reported, not obeyed. The tool dispatcher, not the schema,
is the authority on every argument.

With no credentials the simulated merchant auto-approves orders and moves no money; the
rail label says so. Real capture still needs PayPal sandbox keys and a buyer approval
obtained at PayPal, which this process does not simulate for the merchant rail.

## Deployment

The service is one container — the `integration` target of the root Dockerfile, built
from the repository root because the integration imports its two sibling trees. It
runs in the shared dev stack alongside the twin backend and web:

```sh
# set OVERSIGHT_API_TOKEN in examples/postgres/.env, e.g.
python -c 'import secrets; print(secrets.token_urlsafe(32))'

tilt up     # integration API on http://localhost:8001
```

Without `OVERSIGHT_API_TOKEN` the authenticated routes answer 401 rather than exposing
an unauthenticated book. The stack runs as a non-root user, with one worker on purpose
- the rate meter, the runs and the model client are per process.

A local PostgreSQL comes with the stack; for a hosted book, point
`OVERSIGHT_DATABASE_URL` at a Neon branch and the local database is simply unused. The
container's process is a single writer, which is the shape the store is written for.

CI runs both halves on every change: the offline suite (including the local EVM sidecar)
asserts the showcase's measured figures, and a PostgreSQL service runs the store suite
against a real server.

## Durable book state

Without a configuration the book lives in process memory, and `/health` says so. Set
`OVERSIGHT_DATABASE_URL` to a PostgreSQL DSN and the book's invoices, payment entries,
conflicts and reviewed engagements are written to a dedicated schema (default
`oversight`, override with `OVERSIGHT_DB_SCHEMA`). A new process reads the book the old
one left: reopening a priced invoice returns its existing order instead of raising a
second one, a captured payment keeps the name of the person who approved it, and its
ledger keeps every fact in order. The database is touched on the first billing
operation, not at import, and a configured database that cannot be used fails the request
with 503 rather than quietly continuing in memory. Each entry's state is constrained in
the database to the states the book defines, writes compare the state they read before
overwriting it, and the ledger table is append-only.

A captured or failed row cannot be downgraded, by a slow worker or by anything else: the
store refuses the write and the caller receives the row that is actually stored.

Neon is the intended host: put its pooled `-pooler` DSN, which carries
`sslmode=require`, in `OVERSIGHT_DATABASE_URL`. The store is written for a transaction
pooler - it holds no session state, disables server-side prepared statements so one
cannot outlive the server session that prepared it, and creates its schema once under a
transaction-scoped advisory lock so concurrent cold starts cannot collide. Give each
environment its own schema or its own Neon branch; dropping the schema drops that book.
A suspended compute wakes on the first billing operation, which is why that operation,
not the import, pays the connect cost; an unreachable database is still a 503, never a
silent memory fallback. Point the store tests at a disposable branch - each Postgres test
makes and drops a throwaway schema, so the branch needs only the right to create schemas:

```sh
OVERSIGHT_TEST_DATABASE_URL='postgresql://...-pooler...' python -m pytest -q tests/test_store.py
```

## Gemini assistant

Set `GEMINI_API_KEY` in the environment to enable two optional surfaces. Invoice copy
may be reworded by the model, but a reply is used only when every number in it is already
on the invoice; otherwise the firm's own sentence is used and the route says why. The
assistant may call the same six billing tools a person can, and the dispatcher still
refuses what a model must not do: amounts come from the review, a capture needs the name
of a human approver supplied by the caller - the name the model writes into the call is
overridden - and only the invoices the caller cleared may be captured. A model fault is
a 502, not a billing outcome; without a key the assistant endpoint is 503. The service
lock is not held while the model thinks, so a slow answer cannot stall the book.

No live model call is part of the offline suite: the tests prove the wire format, the
tool refusals and the prompt boundary against a local fake.

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
python -m oversight_twin.showcase
python -m oversight_twin.demo
```

Tests cover every roster role through the real PayPal transport against a local HTTP
fake, human and chain gates, shared-payee limits, repeated calls, missing facts, and
sandbox-only configuration. With Node and chain dependencies present, the suite also
runs the local EVM-to-PayPal-to-EVM path using a temporary journal.

The billing, store and assistant tests run offline against a localhost fake for the
model endpoint and an in-memory store. The PostgreSQL tests run only when a database is
named, so a clean checkout never needs one. They check what the memory store cannot
prove: a second store object sees the first one's order, a captured entry keeps its
approver and its ledger, a state outside the known set is rejected by the database, one
engagement cannot hold two invoices, merchants are isolated, and a re-prepare replaces a
dataset's engagements.

Each guard was verified against a negative control: the guard is removed in one place,
the test that names it is run, and the failure is observed before the guard returns.
Controls include the order-id reconciliation (the book read as `awaiting_capture` instead
of `captured`), the terminal-state guard (a captured row fell back to `awaiting_buyer`),
the assistant's invoice allowlist (a cleared-only capture went through), the pricing
ceiling (a batch failed instead of one row being refused), the one-invoice-per-engagement
rule, operator identity (403 became 200), and the edge's environment wiring (the served
app ignored its configured limits).

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

This is a single-process prototype, not a production payment or custody service. The
socket fake models approved funding; real PayPal requires buyer approval. Orders collect
for the authenticated merchant: a role's `reference_id` is an accounting label, **not** a
PayPal payout destination. No arbitrary-agent payouts, VAT filing, national tax
certification or browser checkout is implemented.

The local chain uses deterministic demonstration keys. `HumanGate` is a trusted
caller's clearance interface, not authentication. The agent-fee hub's payment journal
and its idempotency-key memory live in the process; the merchant book's reconciliation
uses the order id it stored, so a restart reconciles, but an atomic transaction across
PayPal, the chain and the database is not claimed. A crash between the provider's answer
and the store write leaves that invoice `unknown` until reconciliation - the same invoice
is replayed, never recharged. Distributed locking and multi-process writers are not
claimed. Never create a new payment to resolve an unknown outcome.

The pipeline's runs and clearance state are in memory: a restart forgets runs, and the
PayPal transport's in-process order map goes with that transport - which is why the
billing book keeps the order id itself. The HTTP token authenticates a caller to this
process - named tokens attribute requests to people, but the token itself is the only
credential, and the rate meter is one worker's view. The CRM adapters read files - there
is no vendor API client, webhook receiver, schema registry or retry queue - and outcome
lines are appended, not reconciled against a CRM record. Quality checks are structural:
they find contradictions and missing facts, not the correctness of the facts a CRM was
told. The assistant is bounded by its tools, not by trust in the model: it may read and
act on the book, but it cannot set an amount or approve a capture, and stopping it is the
approver's decision.
