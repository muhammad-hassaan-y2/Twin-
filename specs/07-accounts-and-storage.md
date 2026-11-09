# 07 — Accounts, saved worlds and the audit trail

## No sign-up to start

A browser or headset is identified by a long random device key. The first time it
appears, it gets a private world. Nobody has to create an account, and the service
never guesses whose world it is: a request with neither a token nor a device key
is refused.

Later, the person can claim that world with an email and password. Claiming
happens once; after that the credentials belong to the account, not the device.
Signing in from a new device connects it to the account. Signing out forgets the
token but leaves the table reachable from that device.

## One world per account

A world holds the ledger, the forecast history, predictions, what-if comparisons,
payment records and policy changes. It is written after every change and restored
after a restart. Money is stored as whole minor units, never as a floating-point
number.

If a saved world refers to a payment method this deployment cannot use, it falls
back to the sandbox method and records that it did.

## Everything is written down

Every action is appended to a log: what was asked, what was refused and by which
rule, which gesture was used, when a payment was reconciled, and every edit to the
ledger. Nothing rewrites the past.

The same log can be read as sentences — who asked for what, what stopped it, what
is still open — so a person can ask "what happened?" and get an answer rather than
a table of rows.

## Outside connections

An account can create a key for an outside tool. That tool can push one event, such
as a bill or an invoice, to the account. The key decides whose ledger receives it.
