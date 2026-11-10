# Oversight Twin — the integration

The seam that joins the two projects in this repository into one system. It is
additive: neither **tabletop-twin** nor **swarm-oversight** is modified.

## Why these two belong together

tabletop-twin settles one principal's money through a real payment state machine
and a real transport — PayPal Orders v2, or a deterministic sandbox. Every payment
is individually approved and can sit under its own ceiling. swarm-oversight's
thesis is that per-mandate ceilings do not bind the principal *across* mandates:
several agents, each inside its own limit, can move more to one payee together
than any one was allowed. That is the aggregate gap.

The twin is the real settlement path; swarm-oversight is the principal-wide
defence. Joined, the twin's settlement gains the cross-mandate aggregate bound it
could not enforce on its own.

## The seam

The integration wraps the twin's transport. Before a charge reaches PayPal, the
payment is fed to one principal-wide swarm monitor session. If the aggregate
crosses the per-payee bound, the wrapper takes the twin's own "refused before any
charge" path, so the record lands **failed** with the refusing rule named and the
provider is never called. Because the wrapper keeps the transport contract the
state machine already expects, it guards the real PayPal transport and the sandbox
identically, and reconciliation of a payment already in flight is left untouched.

The reaction is a setting, as in swarm-oversight: freeze the whole principal on the
first breach, or hold only the breaching payment.

## What it proves

One principal, three mandates paying one payee 25,000c each under a 60,000c bound:

- **per-mandate only** (the twin as shipped): 75,000c settles — the gap.
- **with oversight**: 50,000c settles, the third payment failed, no PayPal call.

The negative control is the point: removing the oversight layer reproduces the gap
exactly. The end-to-end tests run the *real* PayPal transport against the twin's
localhost socket fake and count the orders actually created — two with oversight,
three without — so the seam is proven on the production code path, not only in a
stub. The integration also leaves the twin's own safety intact: a payment whose
reply never arrives still goes to the unknown state and still cannot be retried
blind, and the rail geography layer still refuses a country PayPal cannot reach.

## Running it

From this directory, with no database, no server and no key:

    python -m pytest                  # 11 tests: negative controls + PayPal end to end
    python -m oversight_twin.demo     # the gap, closed, in the twin's settlement path

Importing the integration package puts both sibling projects on the path, so the
bridge uses them straight from the checkout — nothing to install, and no change to
either baseline.