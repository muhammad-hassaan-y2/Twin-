# The firm beside the table

A second miniature lives on the same service as the cash twin. Twenty-six audit roles answer
questions about European company-audit, tax and financial-statement rules, and the table draws
what they decided. It is not a separate product: it shares the accounts, the world a
device opens for itself, the ledger, the guardrails and the eval command, and it inherits
the rule that a number nobody computed may not be spoken.

## Where its numbers come from

The firm quotes twenty statutory figures from a historical legal snapshot, including audit
rotation limits, fee caps, size thresholds and VAT rate provisions. Nineteen were read from
919 articles across 9 statutes fetched from open EU sources; each derived figure keeps its
source article and exact quote. The original eight-statute manifest and the additional VAT
source are separate records, not a claim that the original harvest included the later fetch.
The harvest can be re-run and the arithmetic repeated. Traceability does not establish that
an old provision is current law or that a Member State has no applicable derogation.

One of the twenty is left uncalibrated on purpose. Materiality is normally expressed as a
percentage of turnover, and nothing in that corpus states the percentage, so the firm
refuses to quote one it could only have invented. A blank that says "nobody wrote this
down" is a better answer than a plausible number.

Every threshold card carries the article it came from and a state — derived, or waiting.
The card is the unit of trust here: a figure with no provenance is not loaded, and a model
may not move one. That last claim has a guard case, and the case has its negative control.

Not every rule in this harvest is a figure. Four of the twenty-six desks answer from a sentence
that states a rule in words and no number at all: how an audit fee may be calculated, when the
committee's additional report is owed, what the public register has to hold about the firm, and
which services a firm that assures sustainability reporting may not sell to the same entity. Two
more desks do arithmetic, but on figures this harvest only gave up under a second reading: the
ceiling that averages the non-audit fee over three consecutive financial years, and the
transparency report that is due four months after the year end and has to stay available for
five. All six are derived the way the numbers always have been - a phrase selects the article,
the sentence is kept verbatim, and a lettered list inside it is read out rather than copied, so
this firm expects three register particulars because the Directive prints three and not because
a programmer wrote three. A provision the corpus stops stating reads as an absence, and the desk
built on it goes silent instead of remembering the law.

Three of the eight new desks compare declared VAT rates with the original 2006 Directive,
not current consolidated law. Its standard-rate clause is explicitly dated 2006–2010;
reduced rates also have derogations. A below-snapshot rate therefore asks for human review,
not a breach finding, and an above-floor rate is not a compliance certificate. A missing
rate is distinct from a declared zero. The band desk reads the rate for the declared category.

Two more desks report the renewable delegation term in Article 48a(2) and refer claimed
small-undertaking status for human review. The latter cannot classify a company from two
ceiling figures: national choices, headcount, the two-of-three test and financial-year history
matter. The final three desks report narrow Eurostat inflation, GDP-per-capita and sentiment
series, retaining dimensions, flags, source and period. Sentiment has no locally invented
threshold. Missing jurisdiction or evidence produces silence; an available EU fallback is
labelled as an aggregate rather than presented as a national observation.

## What a review says

Put an engagement to the firm and each of the twenty-six roles answers once. Every answer is a
verdict, a sentence, and the citation the sentence is standing on. There are four verdicts:
**clear** means the desk's check passed or its observation is informational, not a legal
certification; **hold** asks for an action or human review; **breach** reports a violation of
the rule being checked; **silent** means the desk lacks authority or evidence for this fact.

A finding *binds* only when it names the role that has to act and the verdict is clear or
hold. On the first engagement of the review corpus that comes out as fifteen clear, two hold,
zero breach, nine silent, and five findings that bind somebody. Asked over the whole corpus the
twenty-six roles return 364 findings - 177 clear, 45 hold, 14 breach and 128 silent - of which 78
bind somebody. The corpus is fourteen engagements across seven fictional companies, each one
placed exactly on, one year past or one cent over a derived boundary, and the numbers above are
what the machine returned, not what was expected of it. The eight desks added since the first
eighteen account for the wider silent tally: the corpus was written before they existed, so it
names no jurisdiction, declares no VAT rate and claims no small-undertaking exemption, and a desk
given none of the facts it asks about stays silent rather than inventing them. The one new desk
that does bind over this corpus is the delegation desk, which quotes a figure about the firm's own
regulatory clock and so answers regardless of the client's file.

## Who decides, and who checks

The verdict is the model's, when a model is wired in. Each role's answer - verdict,
sentence, the article it is standing on, and the colleague it asks to act - comes back from
the endpoint, and the firm files it only if the machine can check it. The checks need no
opinion about language. Seven of them, each one a fact about text:

- the verdict is a word this firm recognises, and there is a sentence to read at all, of a
  length a card can hold;
- the answer names a passage, and that passage is one of the six that were sent to it;
- the passage resolves in the harvest under the reference and digest the answer repeated;
- the quote is inside the text that was sent, word for word - not inside the model's
  recollection of a regulation, which is the failure all of this exists to catch;
- every figure the sentence speaks is the client's own or sits inside that quote;
- the facts it says it leaned on are facts it was handed;
- the colleague it asks to act is a role of this firm, and is not itself.

For the quote check to mean anything, the law has to be addressable rather than merely
stored. The rebuilt corpus index covers all 919 harvested articles, with searchable text
and a digest for each; adding sources requires rebuilding it. That lets a citation be resolved and a
quote matched against the bytes instead of against anybody's memory of them. The same reason
decides what goes into the ask: none of the figures the firm derived from the harvest is in
it, neither among the facts the model is handed nor anywhere else, because an answer that
could copy the right number out of its own prompt has been checked by nothing. Each role's
question is searched on its own words too - putting the client's file into the search was
tried, and measured over the original eighteen desks. Their eighteen questions then answered with only
eleven distinct articles between them, and three of those came back for every single one: a
client's file is written in the same vocabulary as the statute that governs it, so a retriever
handed the figures stops retrieving and starts matching the words everybody uses.

A judgement that fails a check is not filed, and it is not quietly swapped out either. The
deterministic rule stands in - its verdict, its words, its article - and the route says that
this happened and names the check that refused. The same is said when the endpoint never
answers, and when the harvested text is not on this machine at all, in which case no request
is spent: nothing could have been checked, and a card crediting the model with a decision no
machine could have verified would be reporting a thing that cannot happen.

That is the deliberate half of the deal. A checked judgement can still disagree with the
answer the rules would have given, and no check can notice, because the checks are about
traceability and not about being right. What bounds it is what bounded it before: no agent
signs, no model moves a threshold, and a person reads the sentence.

## The contract

The roles do not only email each other. They are registered on a Solidity engagement
contract running on a local EVM sidecar, and their agreements are written to it: an offer,
an acceptance, the terms each side is held to. Two things follow from putting the agreement
somewhere other than in this program's memory.

The first is that the bytecode is a second authority, and it disagrees. The contract checks
the fee cap on every proposal — 70% of the audit fee, itself derived from the regulation
rather than configured — and an engagement one basis point past the cap is refused with
`FeeCapBreached(140001, 140000)`. Nothing is recorded. That refusal is not this app's
opinion about itself; it is a name that came back out of compiled contract code, and the
panel prints that name rather than a sentence about failure. It means a finding the rules
call binding can still be a refusal on the contract, and the two accounts are both true at
once, so the card shows both.

The second is that an agreement stops at **Attested** until its registered counterparty
principal countersigns. The local sidecar derives demonstration keys, including principal
keys; these prove contract mechanics, not production human identity or custody. The PayPal
hub checks that countersignature and caller clearance before payment, then records chain
settlement only after confirmed capture. Its tests sign explicitly as a separate step.

## Agent to agent

Between the roles, messages go over the same contract bus, and a refused write is still
journalled. That distinction is the whole point of the transport: an offer that was rejected
is evidence about what the firm tried, and a transport that drops refusals silently turns
the trail into a success story. The transcript is readable end to end, and the panel can say
which agreement is waiting on a person instead of leaving an empty row where it would have
been.

## Training

"Train" means two different things here, and only one of them happened.

What happened is calibration: the thresholds were fitted against the harvested corpus by
counting what the articles actually say, which is arithmetic over text somebody else wrote,
with the article left attached to the result. What is shipped but not run is a fine-tuning
dataset built from the firm's own logged decisions, and a script that would consume it. No
weights were trained on this machine, no checkpoint exists, and nothing in the app loads
one. The dataset is an artefact you can audit before you spend anything on it, not a claim
that the model got better.

## What the table shows

One card, four states, and every figure on it copied from a response. *On contract* when the
sidecar answered, with the roles it hired. *No contract* when it did not, with the reason the
service gave — "TWIN_CHAIN_URL is not set, so this app never asks for a chain" is a state of
the deployment, not an error. *Asking* while a review is in flight. *Offline* when the twin
stopped answering, and then the card says that instead of holding its previous numbers up as
current.

The card states how many figures were derived out of how many articles, which engagement was
put to the firm, the verdict tally, the one finding that costs the most to leave out, how
many agreements are on the contract, and how many wait for a signature. It also says who wrote
what. The leading sentence carries a byline - the model, or the rule that stood in for it and
why - and the line under it counts the whole review from each finding's own route rather than
from one route for the engagement, because one ask can be refused and the next accepted. With
no model credential every byline reads "rules" and the count collapses to "the words above came
from the rules route", which is true: the whole subsystem runs with nothing paid for.

## What is not claimed

No public network. No human signature authority. No trained weights. No materiality
percentage. The corpus is a snapshot of what open EU sources served at one time on one
machine, and a figure whose harvest cannot be reproduced should be treated as wrong until it
is. The model route has never been asked of a real endpoint on this machine either: the
judgement, the seven checks and the fallbacks are exercised against a miniature gateway that
answers the way Meta's does, on a socket, with a key that is a string in a test. So every
verdict logged here, and every sentence the example card shows, came from the rules - and the
card says so, which is the only part of this that a reader has to take on trust.
