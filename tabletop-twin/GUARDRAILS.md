# Guardrails

What a proposal has to be before anyone is allowed to decide whether it is permitted.

This service already has a policy engine: single-payment caps, rolling daily and
monthly ceilings, per-recipient ceilings, a recipient allowlist, a weekly
new-subscription allowance, an approval floor, and a rail-coverage map that refuses a
payment to a country the chosen route cannot reach. Every one of those is a decision
about **this person's budget**, and this person can change any of them tomorrow.

Guardrails are the layer in front of it, and they are not about the budget at all. They
are about whether the thing being asked is a thing this service can read. A person who
raises their approval floor to a thousand dollars has made a choice. A proposal that
names a bill that is not in their ledger, or that calls a two-hundred-and-forty-dollar
subscription a sixty-dollar one, has not made a choice — it has contradicted a fact, and
the only question is whether the machine notices.

The one sentence all six rules say: **the model may ask, but it may not tell the ledger
what the ledger says.**

## What is not a guardrail

Three things people usually mean by "AI safety" are deliberately absent here, and the
absence is a decision, not an oversight.

There is no classifier over the prompt. Nothing reads the words for intent, tone or
harmfulness, and nothing refuses because a request seemed manipulative. A refusal here is
always a fact about the ledger, the arithmetic or the shape of a number, which means it
can be shown to a person, argued with, and — where the person is allowed to change it —
changed. A verdict that came from a model's opinion about another model's phrasing could
not be audited by anybody.

There is no content moderation. The twin's own voice is governed by its persona
document, not by this layer.

And there is no widening. A guardrail can only stop a proposal or pass it; none of them
can authorise a payment, raise a limit, or supply an amount that the ledger does not
contain. Where a guardrail mentions a number it is quoting something already computed.

## The six

They run in a fixed order, cheapest first, and the first one is load-bearing in a way
that is easy to miss: a proposal that names no real event has no ledger fact to
contradict, so the two middle rules can never fire for it. That is why an invented event
id is refused before anything is said about its amount.

**`event_is_real`** — a named ledger event has to exist. Without this rule, a charge
against a bill nobody owns still passes the budget: it has an allow-listed payee, it is
under the approval floor, and so the policy engine approves it and it settles with no
hand on it at all. Naming a real event is what makes everything else checkable.

**`amount_is_a_number`** — an amount that cannot be read as whole cents is refused by
name. What arrives otherwise is a string like "twelve dollars" into a field the ledger
keeps in cents. The tempting fallback is to use the bill's own amount, which is exactly
the danger: a human is then asked to hold a payment for a figure the model never named,
and the audit trail says nothing about the number that was actually asked for.

**`charge_is_positive`** — a charge that moves nothing is not a charge. Zero is under
every cap, so the policy engine waves it through and it settles; a payment of zero
dollars in the ledger is not a harmless artefact, it is a record that says this service
moved money and did not.

**`amount_matches_event`** — when the proposal names a bill and states an amount, the
two have to agree. The bill does not get to be re-priced by whoever mentioned it. The
number that moves is read out of the person's own events, not out of the request.

**`payee_matches_event`** — the same for the counterparty. Both names in the worked case
are on the allowlist, so nothing about the budget complains; only the ledger knows that
this invoice is owed to Suite Works and not to Guild Mutual. Left alone, a person is
handed a card asking them to hold a payment for the wrong company, and their approval is
the thing that makes it look legitimate.

**`figures_are_given`** — the reason attached to a payment may only quote figures this
code already computed: the amount in cents and in currency units, the named event's own
numbers, the day, the fee, and the person's own limits. A justification that says "the
club usually bills 4,200 for this" when nothing in the world contains 4,200 is a
fabricated reason sitting next to real money. This is the same discipline the narration
is held to — a streamed sentence is not shown until the figure inside it has been checked
against the forecast — applied to the prose that accompanies a charge.

## What a stopped proposal looks like

A refusal from this layer is not a cancelled payment, because it was never a payment. No
record enters the state machine, no idempotency key exists, nothing is left pending for a
gesture that could revive it, and no transport is contacted. The verdict is `deny`, the
`rule` field names which of the six stopped it, and the reason says what the ledger
actually says. One audit entry of kind `guardrail` is written, carrying the proposal as
it arrived — the stated amount, the stated payee, the justification verbatim — so a
person reading the trail later can see the exact thing that was refused rather than a
sanitised summary of it.

A policy denial, by contrast, does create a record and cancel it, because the payment was
real and this person's rules said no. The two kinds of refusal are kept apart in the log
for that reason: one is "this was never a possible payment", the other is "this was a
possible payment and you did not allow it".

Below the layer, the tool surface is still a plain validator: it checks that a call names
one of five known tools and passes only recognised arguments. It does not evaluate JSON
Schema bounds like a declared minimum, and this layer does not depend on it. A malformed
argument that gets past the validator is met by `amount_is_a_number`; a validly-shaped
lie about a real bill is met by `amount_matches_event`. Neither layer trusts the other,
and neither can spend anything.

## Proving it

Each rule carries two tests, and the pair is the point. One shows the rule firing. The
other re-runs the *same* proposal with only that one rule taken out and requires the bad
outcome to actually happen: the invented bill really does settle, the zero really does
land in the ledger, the hold card really does ask for the wrong company. A control that
switches off the whole guard proves only that the guard does something; a control that
removes one rule proves which rule was doing it. The last test in that file notices if
any rule has lost either half and refuses to let the suite go green on a rule nobody can
demonstrate.

This is the same discipline the seeded-failure corpus uses for the older hazards — a
payment stuck in unknown, an unreachable rail, an invented figure mid-stream, a click
offered in place of a hold, a ledger that has not landed, a database socket that the
server closed. A test written by whatever fixed the bug tends to ask a soft question, so
every one of these has to be able to produce the failure first.

The discipline now has a score. `python -m twin.eval` runs each guarded promise twice —
once whole, once with only its own rule taken out — and reports how many of them still
catch the failure they seeded, beside which policy rules any case reaches at all. A guard
that has lost its control and a rule nobody ever exercises both fail the command, so
"covered" is a number the run produces rather than a word somebody chose.

## The firm's rules are the same shape

The audit roles beside the table get the same treatment, and the same five sentences
carry it. A breach or a silence opens no agreement. A rule nobody stated keeps a role
quiet instead of letting it infer one. The words a role says have to agree with the
verdict printed beside them. A weak match is escalated rather than rounded up. And a
model may not move a threshold: the figures come from the harvest, with the article
attached, and a sentence cannot edit the number it is quoting.

Each of those five is run twice in `python -m twin.eval`, once whole and once with only
its own rule removed, and each still produces the failure it was seeded with. They are
counted in the same 18 controls as the six above, not kept in a separate tally that
flatters the total.

## Once the model decides, the checks move, they do not go away

The sixth sentence above - a model may not move a threshold - is the one that used to carry
the whole of the firm's distance from the model, because the model only ever wrote a caption
under a verdict the rules had reached. Now the verdict, the sentence, the article and the
colleague being asked to act all come from the endpoint, and what stands between that and an
agreement is a list of checks that need no opinion about language: the verdict is a word this
firm has, the quote is inside the passage that was actually sent, the passage resolves in the
harvest under the reference and digest it repeats, every figure spoken belongs to the client's
file or to the quote, the facts leaned on were handed over, the colleague exists and is not the
one answering.

Three of those are worth naming for what they catch. The quote is matched against the text
that went out and not against the article as a whole, so a sentence that is genuinely in the
law but was never shown is refused as remembered rather than read - which is the model's
normal failure, and the one a fluent answer hides best. The derived thresholds are kept out
of the ask entirely, because a prompt containing the answer turns the number check into
copying. And when the harvest's text is not on the machine, no request is made: an index of
digests can prove a citation exists but cannot prove a quote is honest, so the alternative to
checking is not a weaker check, it is silence, and the route says that in words.

What a guard does *not* do here is decide whether the answer is right. A checked judgement can
disagree with the one the rules would have reached, and nothing notices, because the checks are
about traceability. That is the part of the deal the previous section was written to keep small:
the model cannot move a figure, cannot sign, and cannot stop a rule from speaking when its own
answer cannot be traced back to a passage - and the substitution is reported rather than hidden.

## A second authority, which can say no twice

The firm's agreements are written to a contract, and the contract is not this service.
Its bytecode checks the fee cap on every proposal, so an engagement one basis point past
the cap is refused with `FeeCapBreached` and nothing is recorded — including where the
rules call a finding binding. That is the case worth reading carefully, because it is the
one place in this project where two correct authorities disagree, and the answer is not to
pick a winner. The card shows both counts: what the roles bound, and what the chain would
not take.

What this layer still refuses to do is treat a refusal as a failure to retry. A rejected
offer is journalled like an accepted one, because a trail that only keeps successes is not
evidence, it is a story.
