# 04 — Two gates before money or a claim

Every request that could move money, change a limit or make a factual claim
passes two independent gates, in this order.

## Gate 1: is the request truthful and readable?

These are fixed checks about the request itself, not about the person's budget.
They refuse when, for example:

- the bill being paid does not exist,
- the amount is not a whole number of cents,
- the amount or the payee does not match the bill named,
- the justification quotes a number that code did not calculate.

The last one is the important one: the model may ask, but it may not tell the
ledger what the ledger says. A request stopped here leaves no payment behind,
because there is nothing real to cancel. It is recorded once, word for word.

## Gate 2: does this person allow it?

This gate applies the person's own spending policy. It answers allow, ask for
approval, or deny, and names the rule that decided. Among other things it
considers:

- actions that are never allowed,
- recipients that are not on the allowlist,
- whether the chosen payment method can reach the recipient at all,
- a ceiling per recipient, and limits per payment, per day and per month,
- how many new subscriptions are allowed per week.

Small payments inside the limits settle automatically. Larger ones need the
one-second hold. A policy denial still creates a real payment record and cancels
it, so the attempt stays visible. Moving a date or chasing an invoice never enters
the payment system at all.

Every refusal carries the name of the rule that refused it.
