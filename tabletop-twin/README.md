# Tabletop Twin

A miniature of one person's next ninety days of cash, standing on their real
table, that they can push around with their hands.

The twin is not a chatbot with a 3D backdrop. Its claims are geometry: how wide
the river of cash is, how high the walls of doubt are, how thick the fog over a
late invoice, how far the boat has drifted. Numbers appear only as captions that
repeat what the shape already says.

## The metaphor

- **River of cash** runs left to right along the timeline. Its width is the
  middle forecast.
- **Banks** on either side are the tenth and ninetieth percentile. The pessimistic
  wall dips below the table when the forecast says the money simply is not there.
- **Stones** are bills, sitting at their due dates. A stone under the waterline is
  a bill the forecast cannot cover.
- **Boats** are invoices that are already late, moored upstream. Fog over a boat is
  the probability of further delay; the mast records the worst lag seen.
- **Lake** is savings. Its depth is real, not symbolic.
- **Garden** is the twin's own track record. It grows only as its predictions
  resolve, and it is the reason to come back tomorrow.
- **Orb** is the twin. It looks at what it is talking about, and it points.

## The loop

Scrub ninety days by grabbing and turning the time wheel. Test a decision by
pulling a ribbon out of the river, which spawns a second, smaller world beside the
first. Test cancelling a subscription by pulling its pipe: the same second miniature
appears, and the twin says what the pipe was worth. Approve a purchase by holding a
pinch for a full second; reject it by saying so out loud on a button. Every gesture
is a request, never a mutation.

Four weeks of history are seeded so the table is alive in the first minute, with no
setup. A daily wind-down, a published accuracy score, and a garden that only the
passage of time can grow are the return hooks.

Where the table physically is gets settled at runtime rather than assumed. In an AR
session the first steady surface at table height and within arm's reach becomes it, and
the miniature turns to face whoever found it; a wall, the floor and anything across the
room are refused, and a placement is taken once and never revised, because a table that
slides when the estimate improves is worse than one that stays put. A browser, an
ungranted hit-test, and a room with nothing that qualifies all keep the authored pose.
The panel band sits above and behind the channel, each card tilted to the standing head
rather than to the room, so the shapes stay the subject and the words stay captions.

## Division of labour

Code computes every number. The forecast, the forks, the probabilities, the
payment verdicts and the accuracy score all come from deterministic simulation and
a state machine. The language model only chooses which tool to call, in what order,
and then explains the result in plain sentences. It cannot author a figure, and a
missing or slow model never blocks the table: the client degrades to "the twin is
not answering, nothing has been spent".

Every answer also says who produced it. A route of `muse:...` was answered by Meta's
Model API; a route beginning `rules (` carries the reason it was not, in the words the
failure actually gave — a refused credential, a rate limit that outlasted the one
repair it was offered, a gateway that hung up mid-sentence. The two halves of an
answer are reported separately, because a model that picks the tool and then cannot be
trusted with the phrasing is a different fact from a model that never called. Before
anything has been asked, the service names the route it is *configured* for and marks
it as not yet measured, which is the only claim the environment alone can support.

The answer arrives as it is phrased. The service speaks Meta's agentic endpoint first —
the one that can ask for several tools in a single reply and stream its words — and
asks again in the compatible shape when a gateway objects to the request rather than to
the credential. Streaming is not a licence to show half a sentence: the narration is
released one finished sentence at a time, and only after the numbers in it have been
checked against the forecast. A stream that invents a figure freezes where it is and the
table keeps the sentence the rules computed instead, so the words on the panel are always
either verified or absent. The same rule decides which model is asked at all: an entry
the provider publishes for images, segmentation or transcription is named as the wrong
tool and costs no request, while a name nobody has checked is tried rather than refused.

## Safety

Spending limits, per-recipient ceilings and approval rules are enforced in code
before any network call. Payments pass through a strict state machine keyed by an
idempotency key, and it has an explicit **unknown** state for a response that never
arrived. In `unknown` the twin is not permitted to retry blindly; it reconciles
first. Anything above the limits, or outside the allow-listed verbs, requires a
hold-pinch from the human. Denials are silent about money: no state changes.

In front of those budget rules is a shorter layer that is not about the budget at all.
It asks whether a proposal is a thing this service can read: the bill it names has to be
in the ledger, its amount has to be a number of cents, a charge has to move something, and
the amount and the payee have to agree with the entry they cite. The difference matters
because the two layers can be changed by different people. A person can raise their own
approval floor as far as they like; nothing a model says can make a two-hundred-and-forty
dollar subscription cost sixty. Refusals from either layer carry the name of the rule that
stopped them, and a proposal stopped here never becomes a payment record at all — there is
nothing to cancel and no gesture that could revive it. [GUARDRAILS.md](GUARDRAILS.md)
writes out all six, and what each one is for.

A separate reliability check treats a settled payment as unfinished until its
business effect is seen. Until then the twin says so in the daily heartbeat — money
taken, outcome not observed — rather than marking the job done. The garden stays a
forecast score: only resolved predictions grow it.

## Who this twin can actually pay

A big share of the world cannot receive PayPal at all, and more can only send. So the
twin keeps a dated, editable catalog of which settlement route reaches which country,
what it charges, and how long it takes — and it treats that as a first-class answer
rather than an afterthought. Ask "how should I pay this?" and it quotes every route it
knows, cheapest first, and says plainly which ones cannot deliver and why.

Three rules keep that honest:

- **Geography is checked before money.** A payment the chosen route can never arrive
  is refused on that ground alone, and the refusal names the routes that could reach
  it. Somebody in a country the provider has left is told the truth instead of
  watching a charge fail at 3 a.m.
- **An unchecked map refuses nothing.** A route only blocks a country whose coverage
  was actually verified. A guessed refusal is worse than an honest decline, because a
  decline is something the payment machine can reason about and a lying policy is not.
- **Nothing is converted.** An amount stays in the currency of the ledger it came
  from and is written in that currency's own minor units. There is no exchange-rate
  source in this project, so a currency the route must handle appears only as part of
  its fee, never as a made-up number.

A route is only selectable when the deployment really has a transport for it. Two of
the catalog's routes are quoted but not wired here, and the service says so rather
than pretending. On top of that, reconciliation now runs in the background on a
timer, so a payment whose answer never arrived is chased overnight even when nobody
has the table open — and it still does not claim the paid-for thing arrived.

## Whose table this is

Anyone can open a world, and nobody has to sign up to see one. A browser carries a
device key, the service gives an unknown key a world of its own, and every account —
claimed or anonymous — owns its own ledger, payments, branches and history. What is
refused is a request that names nobody: with neither a bearer token nor a device key the
service answers 401 rather than guessing whose cash flow to draw. A device key is a
credential and is treated as one: it is stored only as a hash, and an id short enough to
guess is refused instead of trusted. A world is written to PostgreSQL after every change,
so the same table, the same history and the same ceilings are there after a restart — and
after a restart onto a different machine.

Nothing the twin did is thrown away. Each ask, verdict, rule, gesture and
reconciliation is kept as an append-only log and can be read back as entries or as a
summary in sentences — which is what a director of finance actually needs: not a
chat transcript, but who asked for what, what stopped it, and what is still open.
A withdrawal asked for after the money has already moved is recorded as the attempt
it was.

Every read of that trail takes a window: today, the last seven days, or the whole
history. Those are the three questions anybody actually asks at a table, and a fold that
does not say which one it answered is a number with no date on it. The same arithmetic
feeds two places — the summary a director reads, and the short brief the twin is handed
before it answers anything — so when it says what it already refused this week it is
quoting a logged row, not remembering one. The miniature carries that brief too, which is
why the money panel can state the twin's week without being asked.

## The firm beside the table

The twin answers questions about its own cash. A second miniature on the same service
answers questions about somebody else's: twenty-six audit, tax and finance roles reviewing
a historical EU legal snapshot and economic observations, with a card stating what they
decided. It is the same world, the same accounts, the same ledger and the same rule that a
figure nobody computed may not be spoken.

Three things keep it honest, and they are the reason it lives here rather than beside it:

- **Its thresholds are read out of the law, not remembered.** Nineteen of the twenty
  figures the firm quotes were derived from 919 articles across 9 statutes fetched from
  open EU sources, each with the article attached. One of them — materiality as a share
  of turnover — is left uncalibrated because no article states it, and a blank that says so
  is better than a plausible number. Six of the twenty-six desks go past the figures this
  pass had already derived: four answer from sentences the harvest states in words and no
  number at all — how a fee may be agreed, what the public register has to hold about the
  firm, which services a firm assuring sustainability reporting may not also sell — and two
  do arithmetic on figures the corpus only gave up under a second reading. All six are
  derived the same way, with the sentence kept verbatim and its lettered lists read out of
  it rather than copied here. Eight new desks add historical VAT comparisons, a renewable
  delegation term, human review of claimed small-company status, and three narrow Eurostat
  series: inflation, GDP per capita and sentiment. VAT comparisons do not certify current
  national compliance; the size desk cannot replace national classification. Finance
  observations carry their table, dimensions, flags and period, label any aggregate fallback,
  and stay silent when the file names no jurisdiction. Sentiment has no invented threshold.
- **The agreement is kept somewhere other than in this program's memory.** The roles are
  registered on a Solidity engagement contract on a local EVM sidecar, and the bytecode is
  a second authority that sometimes disagrees: an engagement one basis point past the fee
  cap is refused by the contract even where the rules call the finding binding, and the card
  prints the refusal name that came back out of the chain rather than a sentence about
  failure.
- **A refusal is still evidence.** Agent-to-agent messages go over the same bus, and a
  refused write is journalled like any other. Agreements stop at *attested* until the
  counterparty principal signs. The local sidecar's deterministic keys demonstrate this
  mechanism, not production human identity. The integration hub requires that signature
  before PayPal settlement and only records settlement after confirmed capture.

[`FIRM.md`](FIRM.md) covers the harvest, the verdicts, the contract and what the card is
allowed to claim. Where the twin only lets a model choose and explain, the firm goes further
and lets the model decide: given a key, each role's verdict comes from the endpoint, and the
service files it only after checking it against the text of the law it claims to quote - and
when the check refuses, the rule answers instead and the card says which of the two spoke.
With no key, which is how this machine runs, all twenty-six answers come from the same rule
planner as the twin, and say so.

## Accessibility

Every spoken line is also a caption. Every gesture has a voice and a gaze
alternative, and the panels are reachable by ray as well as by hand — except the one
hold that moves money, which stays a hold on purpose and refuses a click. The palette is
colourblind-safe and never the only channel: probability is carried by fog density
*and* size, risk by height *and* position relative to the table. The same rule holds
on the panels. A card changes its whole surface when its state changes — band, chip
and border together — and the chip carries the word for that state, so a person who
cannot tell the amber from the red still reads "your hold" or "offline". Nothing on
a panel is a colour alone, and the decision card names the decision it is asking for
and what the money would do. The hold that settles money is said twice over as well: five
marks that fill as the contact lasts, and the seconds it has actually lasted written
underneath, so a hand that never sees the gauge can still read the rule it is being asked to
meet.

## Scope

One fictional persona, a freelance illustrator with lumpy income. One domain, cash
flow. One horizon, ninety days. No bank linking, no investment advice, no crypto,
no multiplayer, no avatars of real people.

The firm beside the table is a second domain, added on purpose: European audit and
financial-statement rules, put to fourteen fictional engagements, answering only with
figures the harvest produced. It does not audit the twin's cash and the twin does not speak
for it; each has its own card. No real firm, real company or real statutory auditor is
modelled by any of the twenty-six roles, and none of this is advice to anybody with a filing
deadline.

## Running it

Two halves, and an optional third: a Python service that owns the simulation, policy and
model adapters, an Immersive Web SDK client that owns the table, and a contract sidecar the
firm can be pointed at when somebody wants its agreements kept outside either of them.

```sh
# service
python -m uvicorn twin.api.main:app --reload          # from the backend directory
python -m twin.eval                                   # the same directory, no server, no key

# client
npm install && npm run dev                            # from the web directory

# engagement contract, optional
node serve.mjs                                        # from the chain directory
```

That second line scores the service on the promises it makes, and it is the one command
here that answers a question no test asks. A test says a rule fired; the eval says whether
the run would look any different if the rule were not there. It reports cases passed,
checks passed, how many guard cases still catch their own seeded failure, and which policy
rules any case reaches at all. A rule nobody reaches is not a protection, and a case that
passes with its guard removed proves nothing; both fail the command rather than being
noted, so it can be run in a check the way the suite is.

The client reads `VITE_TWIN_API` for the service origin. The service reads names of
credentials, never values checked into this repository. Muse — Meta's Model API —
needs one of them: `MODEL_API_KEY`, Meta's own variable name, or
`META_MODEL_API_KEY`. Its address and default model are the ones Meta publishes, so a
key alone is a whole route; `META_MODEL_BASE_URL` and `META_MODEL_NAME` replace them
when a deployment has a different agreement with the same API. Any other
OpenAI-compatible server has no published address, so it needs all three of its own:
`LLM_API_KEY` with `LLM_BASE_URL` and `LLM_MODEL`. Settlement reads
`PAYPAL_CLIENT_ID`, `PAYPAL_SECRET`, `PAYPAL_ENVIRONMENT`. A credential is the one
thing that is never assumed: with no model key the service still answers, from the
rule planner, and says which route it took. With no PayPal credentials it settles
against a deterministic sandbox transport; the real transport has to be asked for
explicitly and refuses to start without its credentials. `TWIN_DB_URL` names the
PostgreSQL server the worlds live on — and it is the one setting with no default, because
a table that only exists on the machine that served it is not somebody's world, it is a
cache. `TWIN_ALLOW_ORIGINS` says which client origins may call it (its default is the
origin the immersive client's own dev server uses, because a table that cannot reach
the service draws nothing), and `TWIN_RECONCILE_SEC` — off by default — turns on the
background sweep of payments that are still waiting for an answer.

The contract is off by default in the same way. `TWIN_CHAIN_URL` names the sidecar the
firm writes its agreements to, and `TWIN_CHAIN_TOKEN` is what the sidecar expects on
those calls; with neither set the service never asks for a chain, and the firm's card
says *no contract* and gives the reason instead of showing an empty list where agreements
would have been. The sidecar reads `TWIN_CHAIN_PORT` (8791), `TWIN_CHAIN_JOURNAL` and
`TWIN_PRIORS`, the last of which points it at the same derived thresholds the firm quotes,
so the fee cap the bytecode enforces is the one the harvest produced rather than a number
typed into a contract.

The test suite needs a server for the same reason the service does. Point
`TWIN_DB_URL` at one you already run and every test gets a schema of its own on it, so
nothing is read from a previous run and nothing is written to `public`. Leave it unset and
the suite starts a throwaway instance on localhost from the packaged binaries, in the temp
directory, with trust authentication — a fixture, not something to put real worlds on —
and stops it on the way out.

A headset has no keyboard, so the client never asks for one. The first visit generates
a device key — 32 random bytes it keeps — and carries it on every request; the service
opens a world behind a key it has not seen. Signing up is optional and late: it puts an
email and a password on the table that device already had, rather than opening a second
one beside it. To land on an account you already have, open the app once with
`?email=...&password=...`, and a browser with no world of its own joins that account
from then on.

## Verification status

The historical full-service run below predates the twenty-six-role expansion. Current
integration checks use a local PayPal HTTP fake and a real local EVM; no real PayPal sandbox
capture or wider-roster UI run is claimed. The full PostgreSQL suite could not be rerun in
this pass because the local test database did not start; isolated regressions are separate
from the earlier full-suite evidence.

The earlier service run covered 432 tests for the forecast, the forks, the policy
engine, the guardrails in front of it, the payment state machine, the settlement catalog,
the accounts, the world a device opens for itself, the audit trail, the then-eighteen roles, the
law they cite and the checks that decide whether a citation is good enough to file, the
contract they write to, the real PayPal transport and the Muse route —
each of the last two against a gateway that answers on a socket, so a refused credential,
a rate limit, a reply that never arrives, a stream that invents a figure mid-sentence and
a gateway that refuses one request shape are all exercised here rather than discovered in
production. The firm is run both ways it can be met: with no chain configured, where the
answer is an empty list plus the reason it is empty, and against a sidecar the test stands
up itself, where what the suite asserts is the bytecode's own refusal of an engagement past
the cap. Opening a world is two writes, so two first visits from one device are raced
against each other on purpose — and the race was run with the guard switched off first,
to check that there is something to guard. No test ever holds a real credential: the
environment is emptied around every one of them, and a test that wants an endpoint stands
it up itself. The whole suite runs against a real PostgreSQL server, one schema per test,
and the run above was measured against a server started from the packaged binaries on this
machine: 432 passed in 184.98 seconds. It was 426 in 337.11 seconds before the
six desks that read sentences were added, 388 in 212.22 seconds before the law was
indexed and the judgements put to a gateway, 328 in 91.14 seconds before the socket
gateways, and 287 in 41 seconds against the file the database replaced — the growth is part
more tests and part a socket instead of a memory-mapped file. It is bought back the first
time a world has to survive onto a different host.

That last habit is now a file of its own. Six failures with known answers — a payment
left in a state nobody owns, a rail the catalog says cannot reach a country, a narration
quoting a figure it was never given, a click offered in place of a hold, a ledger write
that never lands, a database connection the server closed mid-session — each runs twice:
once expecting the bad outcome with the guard switched off, once expecting the machine to
stop it. A test that only asks whether the fix is present can pass against a fix that does
nothing; one that has to produce the failure first cannot. The six guardrails are held to
the same pair, each with only its own rule removed: without `event_is_real` a charge for a
bill nobody owns settles with no hand on it, without `payee_matches_event` the card asks
for a hold on the wrong company, without `charge_is_positive` a payment of zero dollars is
written into the ledger as though money moved.

The client typechecks and builds, and its scene document validates against the SDK's
own schema and component catalog, so every asset id, component and field the code names
is real. Its account paths were then run in a real browser against the dev server, from a
profile with nothing stored: the first visit opened a table of its own with no signup and
no token, every request it made answered 200 and nothing reached the console, signing up
afterwards returned the same account, so did logging in with a token, logging out left the
device on that same world, reloading came back to it, and a second browser profile was
given a different one. A pipe pulled with a pointer forked a second world, and the
streamed answer was checked the same way, against a localhost stand-in for the model
gateway rather than a paid endpoint: the caption arrived in two pieces about a second
apart and the answer the world kept was the whole verified sentence, with the route
reported as the model that produced it.

The four panels a person reads were then rebuilt and driven the same way: the caption
card, the card that asks for a decision, the panel listing money that has left the
table, and the plate above the time wheel. Each is now a layout rather than a stack of
lines — a state band, a byline that keeps route, account and day apart instead of
squeezing them into one row, one caption at a size meant to be read at arm's length, and
a two-by-two grid of asks where four buttons used to wrap over each other. Each state a
card can be in moves the band, the chip and the card border at once, and the chip carries
the word for the state, so amber and blue are never the only difference.

That run put a real decision through them. A payment above the approval floor was
proposed over HTTP and the client's own heartbeat surfaced it on the decision card with
the amount, the recipient, the rail, the fee and the rule that stopped it, while the
money panel showed the same row. A pointer press on the card's reject button then sent
the refusal to the service: the request answered 200, the ledger kept it as a rejection
naming who refused and why, the record left the money panel, and the caption card
changed its whole surface to say that the record now reads cancelled. Nothing reached
the console and no request failed.

Closing that card is not the same as deciding, which is why the button writes to the
ledger rather than hiding the panel: a refusal that only moves pixels leaves no trace
for the person who has to explain the payment later.

The other half of that decision was checked rather than assumed. A button was put on the
card to settle a payment with a click, and the machine refused it — the ledger kept an
approval refusal saying that the amount needs a hold and recording the click as
the gesture that was tried. So the button is gone and the card now says in words what
the rule is: only a hold settles, and a click can only say no. A lighter touch is not an
accessibility improvement on a payment; a different hold is. Two holds are accepted now,
each named for the input that made it: a pinch held near the coin, and a pointer pressed
on it and not lifted. Both are the same second of continuous contact, and a shorter one is
refused by the same rule whoever made it, so a table with no keyboard and a screen with no
hands settle a payment the same way and leave the same trace behind.

That browser run is also where a defect nobody had asked for turned up. A request naming
a device in the moment between its account existing and its ledger landing was handed the
account with nothing in it, which surfaced as a request that never answered rather than as
an error anyone could read. It is now waited for, tested from both sides, and gone from
the log above.

The settlement-rail, currency and background-reconciliation work is covered by the
service tests and by the client typecheck and build, and the panels that report it are
rendered by the running client as above.

What a browser could not do before was the hand, so the hand was rebuilt as a second
input rather than excused. A pointer pressed on the coin and held for the full second now
settles a payment, and it was driven that way rather than argued: a fresh device world
with nothing stored, a payment above the approval floor proposed over HTTP, the client's
own heartbeat surfacing it, then a press of two hundred milliseconds on the coin — which
asked for nothing at all, because the hold rule does not care how many fingers made it —
and then a press and hold of the full second, which sent exactly one approval, was answered
with the payment settled, and left the gesture written in the ledger as the one a pointer
made. Nothing reached the console in either case.

The same kind of run then chased an **unknown** payment, which had only ever been observed
on an older build. One settled record was put back to **unknown** while the service was
stopped, so that the number the client read came out of the database rather than out of a
test fixture, and the first heartbeat that carried it asked the provider exactly once: one
reconcile request, a reconcile entry in the ledger beside the approval that had caused it,
and the record left the fog. What it left the fog *as* is the part worth reading twice.
The stand-in gateway's own memory is per-process, and the process had been restarted, so
the provider said it had never seen the charge and the machine wrote **failed** — not the
**succeeded** the same browser session had produced a few steps earlier. That is the rule
working, not a bug found: the provider is the authority, and chasing is not the same as
forgiving. A
real gateway remembers a captured order across anybody's restart, which is exactly why the
transport that talks to one is the piece that cannot be pointed at a localhost stand-in by
way of an environment variable.

What the suite checks and what it would notice are different questions, and the second one
is now scored on its own. `python -m twin.eval` ran 26 promises as 114 checks, caught 18 of
18 seeded failures with each guard switched off one at a time, and reached 24 of 24 policy
rules. It needed no key and no server: every figure it argues about came out of the code
under test. Two of those checks were added because the case they belonged to was passing on
vacancy — a rule that refuses a smuggled figure proves nothing until the same sentence with
a computed figure in it is allowed, and a summary that counts rows proves nothing until the
run is shown to have produced rows to count.

Eight of those promises belong to the firm, and they are the kind that would otherwise be
argued about rather than run: a breach or a silence that opens no agreement, a rule nobody
stated that keeps a role quiet instead of letting it guess, words that have to agree with
the verdict printed beside them, a weak match that is escalated rather than rounded up, and
a model that cannot move a threshold. Five of them carry a negative control that still
catches its own seeded failure. The other three are measurements rather than guards: every
figure traces to a fact in the harvest, every threshold the code actually enforces is
exercised by some case, and the training corpus describes this firm rather than a generic
one.

Memory was tested for the first time as its own subject, and the test found something. The
windowed folds reversed the trail on one branch and not on the other, so the same week read
from a session and read from the database came back in opposite orders. No count was wrong,
and order was never meant to mean anything — which is exactly why nobody noticed until a
test asked. Order is now not part of the contract, stated rather than implied. The edges
are checked the same way: the seventh day is inside a week and the eighth is outside it, a
row this code cannot place in time stays visible instead of quietly dropping out of a
summary, and the brief the twin is handed before it answers says the same figures the
summary endpoint computes from the same rows.

The panels were driven in a browser again for the states they did not have. Seven exist
now: listening, thinking, speaking, your hold, pinch sent, asking the rail, offline. A bill
above the approval floor put through HTTP surfaced the decision card with a hold gauge —
five marks, one per fifth of the approval second, filled from the same measurement the coin
keeps rather than from a frame counter — and the money panel gained the twin's own week
under its list of open payments, which is the backend's fold and not a client-side count.
The score in a caption byline, "keeps 76% of 12", is read off the orb's own component, which
the world fills from the payload; no panel works that number out a second time. Taking the
service away — every request aborted, nothing else touched — moved all three cards to the
offline treatment at once; the orb's float and the water's ripple are gated on the same
published state, and that part is a claim about code this run reached, not a motion a still
frame can show.

That run also found the first real defect of the pass. The separator the panels join their
lines with was a middle dot, and the bundled font atlas does not contain it, so every joined
figure on the money and decision cards drew a small box where a number should be. The
separator and the two spoken sentences that leaned on an em dash are plain ASCII now, which
is the rule this project already states and had not followed everywhere; the run above is
the one that shows the boxes gone, not the one that found them.

The firm's card was driven again in the managed runtime for the eighteen-role roster, and the
live element text and component values were read out of the running app rather than out of a
preview. (The panel evidence in this section is that run's verbatim output, captured before the
roster grew to twenty-six; the counts it quotes — 18 roles, 17 of 18 figures, 299 articles in 8
statutes, 252 findings — are the eighteen-desk run's, not the current roster's. [`FIRM.md`](FIRM.md)
carries the re-measured twenty-six-desk tally: 919 articles in 9 statutes, 19 of 20 figures
derived, 364 findings over the same fourteen engagements. The card was not re-driven in the
managed runtime for the wider roster, so nothing here claims it was.) With the service up and no
chain anywhere near it, the card read *no contract*, "18
roles named, none hired - no contract was reached", "17 of 18 figures derived out of 299
articles in 8 statutes - 1 left uncalibrated", and the reason the service gave, naming the
variable that was not set. A controller was aimed at the card's button and its trigger pressed,
and the card then carried what eighteen roles actually returned for the first engagement:
"clear 14 - hold 2 - breach 0 - silent 2", the binding finding with the article it cites
("engagement-partner (rules): 10 of at most 20 years on a tender, 10 without one
(32014R0537 art 17)."), and "the words above came from the rules route", which is true because
no key was ever supplied.

The sidecar was started and the service restarted with `TWIN_CHAIN_URL` pointing at it, and the
page reloaded onto it: the same card moved to *on contract* with "18 of 18 roles hired". One
press opened four agreements on the contract with four waiting on a signature — the four
findings that bind somebody on that engagement, and nothing else — and a second press advanced
the engagement to 2 of 14 with "clear 11 - hold 5 - breach 0 - silent 2", six agreements and ten
waiting, the chain itself answering 18 roles and 10 agreements. Those are cumulative counts read
off the chain, not a client keeping its own tally. Every string in all 252 findings the fourteen
engagements return was then scanned: no sentence and no other text field a card prints holds a
non-ASCII character, and the only non-ASCII bytes anywhere in a response are inside the quoted
article text, which the card does not display, so nothing reaches the atlas gap the money panel's
separator fell into.

The eighteen answers are no longer written by this program. Each role's verdict, its sentence,
the article it stands on and the colleague it asks to act now come from the endpoint when one
is configured, and the service files an answer only after checking it against the text it
claims to quote: the 299 articles are indexed by id and by the digest of their own bytes, so a
citation resolves to a stored article and a quote is matched against the characters that were
sent, not against a memory of a regulation. Everything said above about what happens then was
run against the localhost stand-in and never against a paid endpoint. A review of eighteen roles
asked over a socket files eighteen judgements carrying the model's verdict rather than the rule's;
the same review with one thing bent at a time - a quote the harvest never
printed, a figure belonging to nobody, a reference that fights its own passage id, a role
asking itself to act, a sentence reaching past the window that was sent - returns the rule's
words instead, with the refusing check named in the route. One of those runs has twelve accepted
and six refused, because a route that belongs to a judgement rather than to an engagement is
worth nothing unless a review can carry two authors at once - which is what the card's byline,
and the count under it, now read off each finding. The byline quoted above is live panel text,
read out of the running app in the state this machine can reach: every finding's own, and every
one of them rules, because no key was set. What no panel has been watched showing is the mixed
review itself - twelve model answers and six refusals at one table - because that state is only
produced by the test that bends six of the eighteen, and it is counted there.
The command that puts one engagement to a real endpoint exits non-zero when no key is set, so a
run that quietly printed eighteen rules answers cannot be mistaken for a run that asked a model.

What a browser still cannot do is the headset. The token is picked up by a near grab and
held there by a squeeze, the wheel turns under a hand, and none of that has been watched
from inside a session on this machine; the state machine underneath all of it is tested in
the service, and the gestures that drive it are tested as far as a pointer can reach them.

Live immersive evidence was still not captured, but the composition no longer rests on
argument: the managed editor became command-ready for this pass and the table was measured
through it. Three renders of the authored hero view, the first of which showed the panel
band sitting low enough and wide enough that its bottom edges covered the river — the
metaphor was behind the captions. That is what lifted the three cards above and behind the
channel, put the wheel's readout beside the wheel instead of across it, tilted every panel
to the standing head rather than to the room, and moved the hero frame's aim onto the
content centre. The scene document reported valid with no warnings on all three renders,
and the running app boots in a real browser with the surface-placement system registered,
canvas up, WebXR available and nothing in the console but the GPU driver's own readback
warnings. The shadows on the props are the one change these renders cannot
show: the editor draws on black, so a caught shadow has nothing to land on, and that work
only tells in AR, where the plate is the difference between a miniature resting on a table
and one floating above it. It now covers the stones, banks, boats, pipes and sprouts that
the payload grows at runtime as well as the ones the scene document places, because a prop
drawn from a ledger never passes through the document and has to be introduced to the light
where it is made. Opaque parts cast; the translucent bank walls only receive, because a
glass wall that threw a shadow would put a stripe across the whole table.

What never attached here is an XR session. The placement code has not seen a real surface,
no hit-test source has been granted on this machine, and no claim about headset poses, hand
tracking, controller rays or where this miniature actually lands should be read as tested.
Run `npm run dev` with a headset attached to get that evidence.
