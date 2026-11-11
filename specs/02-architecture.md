# 02 — How it is put together

Think of it as two halves that never trade places.

**The service (Python).** It owns the ledger, the forecast, the spending rules,
the payment records and the history. It is the only part allowed to calculate a
number, decide whether an action is allowed, or move money.

**The table (web client).** It draws the miniature in augmented reality, watches
the hands and voice, and sends what the person did to the service. It never
calculates money and never decides anything.

## One turn of the loop

1. The person pulls a bill two days later.
2. The client sends "move this bill" to the service.
3. The service checks the request, recomputes the 90 days, and saves the result.
4. The service answers with a new description of the table.
5. The client redraws the river, stones and captions from that description.

The client has no second source of truth. If the connection drops, it says so
and stops offering approvals rather than guessing.

## Accounts and storage

A browser or headset is given a private world the first time it connects, with
no sign-up. Later the person can claim that world with an email and password.
Worlds are stored in a database so they survive a restart, and the service is the
only writer.

## What the split guarantees

- Numbers come from code. A language model may choose what to look at or say,
  but it cannot invent a figure.
- A request without a known account is refused; the service never guesses whose
  money it is looking at.
- An action is attempted only after it passes the truth checks and the person's
  own spending rules.
