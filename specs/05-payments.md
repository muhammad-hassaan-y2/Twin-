# 05 — How money is moved, and how the twin stays honest about it

## A payment has a life

A payment is not a single moment. It is drafted, proposed, approved, sent, and
then either succeeds, fails, or becomes unknown. Each step has a legal next step,
and the service refuses anything else.

The important state is unknown: the provider may have taken the money but the
reply was lost. The service never sends the charge again in that state, because a
second send could charge twice. It asks the provider what happened first, and only
then decides.

Each attempt also has a unique key, so a repeated message over the network cannot
create a second charge.

## Approval

Below the person's approval floor, the policy's yes is enough and the payment
settles automatically. At or above it, only holding a pinch for one full second
settles it. Any other gesture is logged as a refused approval.

## Succeeded is not the same as delivered

A payment marked succeeded only means the money left. The service keeps a
separate fact for whether the thing that was paid for actually happened. Until
that is observed, the twin says "money taken, outcome not observed" instead of
claiming everything is fine.

## Payment methods

The service carries a dated catalog of payment methods: which countries they
reach, their fees, their currencies and how fast they settle.

- Reachability is checked before arithmetic. If a method cannot reach the
  recipient, the payment is refused and methods that can are named.
- There is no currency conversion. The amount stays in the ledger's currency; a
  different currency changes the fee, never the number.
- A method is only selected if this deployment can actually settle on it. The
  rest can be priced but not used.
- A sandbox method is available for development, including a way to lose the
  reply after charging so the unknown state can be practised.

## Checking up on unknowns

The client asks the provider about an unknown payment the next time it loads the
table. An optional background sweep can do the same for every account and write
the answer to the audit log. Neither ever marks a payment as delivered: a provider
confirming the money moved is not proof the paid-for thing arrived.
