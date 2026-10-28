# Tabletop Twin service

The half that knows what a dollar is. It owns the ledger, the forecast, the forks,
the spending policy, the payment state machine, and the twin's voice, and it hands
the client a description of a scene rather than a chat reply.

## Division of labour

A seeded Monte Carlo produces the percentiles, the probability that cash runs dry on
a given day, and which day hurts most. A fork engine runs the same world again under
one changed decision and reports the difference. A calibration score compares what
the twin predicted with what actually happened, and that score — not an opinion — is
what grows the garden the client draws.

A language model chooses which of those tools to call and then explains the result.
It is never handed the job of arithmetic: narration is checked against the numbers
the code actually produced, and a model that speaks a figure nobody computed is
rejected rather than displayed. When no model is configured, or the one configured
is unreachable, the same tool choices come from a rule planner and the service
reports which route it took. Nothing on the table depends on a model answering.

## Supervision, not trust

Spending limits, single-payment caps, rolling daily and monthly ceilings, a
recipient allowlist, and a weekly new-subscription allowance are enforced in code.
A model response cannot widen any of them, and asking to is itself a blocked action.
Three verdicts come out of the policy engine: allow, require a hold-pinch from the
human, or deny.

Payments move through a strict state machine keyed by an idempotency key, and one
state is **unknown**: the request left, the answer never came. From there a blind
retry is refused, because a second charge could duplicate the first; the machine
asks the provider what actually happened and only then moves. A payment is not
considered finished when the money is taken — it is finished when its business
effect has been observed, and until then the twin says as much in the daily
heartbeat instead of treating the job as done.

By default settlement runs against a deterministic sandbox transport that can be
told to decline a recipient or swallow a reply after charging, so the awkward states
are exercised in tests rather than discovered in production. The real transport is
opt-in and needs its credentials. Because that transport is real HTTP, it is also
tested against a gateway that actually answers on a socket: one that loses a reply
after taking the money, one that replays an idempotency key, and one that refuses a
credential before any order exists.

## Whose world it is

Nobody sees anybody else's table. An account is created with an email and a
password, and every request after that carries a bearer token; without one, the
service answers 401 rather than guessing who is asking. Each account owns its own
ledger, branches, payments, ceilings and history, and a world survives a restart
because it is written to SQLite after every call that changes it.

Everything the twin did is kept as an append-only action log — the ask, the verdict,
the rule that decided it, the gesture that settled it, the reconciliation that
finished it — and a human can read it back through an audit endpoint or as a
summary in sentences. A withdrawal asked for after the money has already moved is
recorded as the attempt it was, refused or not.

## The persona

One fictional freelance illustrator, four weeks of seeded history, ninety days
ahead. A daily heartbeat narrates what changed, what is at risk, and what the twin
got right; a wind-down closes the day with the median path, the thinnest bank, an
accuracy percentage and the garden stage.

The heartbeat is written as `heartbeat.md`, and its numbered steps are the loop the
service actually runs: a step with no rule behind it is reported as unwired by the
health endpoint rather than quietly skipped. The character's voice, the things it is
forbidden to say, and the order it speaks in all live in those documents, so the
tone is editable without touching the simulation.

## Running it

```sh
python -m pip install -e ".[dev]"
python -m uvicorn twin.api.main:app --reload
python -m pytest
```

Model and settlement credentials are read from the environment by name, and no value
is kept in this repository. `TWIN_DB_PATH` says where the worlds live (`twin.db` in the working directory by
default, which is why it is git-ignored), and `TWIN_ALLOW_ORIGINS` lists the client
origins allowed to call it.
