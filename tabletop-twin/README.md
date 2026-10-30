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

## Division of labour

Code computes every number. The forecast, the forks, the probabilities, the
payment verdicts and the accuracy score all come from deterministic simulation and
a state machine. The language model only chooses which tool to call, in what order,
and then explains the result in plain sentences. It cannot author a figure, and a
missing or slow model never blocks the table: the client degrades to "the twin is
not answering, nothing has been spent".

## Safety

Spending limits, per-recipient ceilings and approval rules are enforced in code
before any network call. Payments pass through a strict state machine keyed by an
idempotency key, and it has an explicit **unknown** state for a response that never
arrived. In `unknown` the twin is not permitted to retry blindly; it reconciles
first. Anything above the limits, or outside the allow-listed verbs, requires a
hold-pinch from the human. Denials are silent about money: no state changes.

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

Anyone can open a world. An account is created with an email and a password, and a
browser that has never signed in provisions its own so the table is never empty;
every request after that carries a bearer token, and a request without one is
refused rather than answered with somebody else's cash flow. A world is written down
after every change, so the same table, the same history and the same ceilings are
there after a restart.

Nothing the twin did is thrown away. Each ask, verdict, rule, gesture and
reconciliation is kept as an append-only log and can be read back as entries or as a
summary in sentences — which is what a director of finance actually needs: not a
chat transcript, but who asked for what, what stopped it, and what is still open.
A withdrawal asked for after the money has already moved is recorded as the attempt
it was.

## Accessibility

Every spoken line is also a caption. Every gesture has a voice and a gaze
alternative, and the panels are reachable by ray as well as by hand. The palette is
colourblind-safe and never the only channel: probability is carried by fog density
*and* size, risk by height *and* position relative to the table.

## Scope

One fictional persona, a freelance illustrator with lumpy income. One domain, cash
flow. One horizon, ninety days. No bank linking, no investment advice, no crypto,
no multiplayer, no avatars of real people.

## Running it

Two halves: a Python service that owns the simulation, policy and model adapters,
and an Immersive Web SDK client that owns the table.

```sh
# service
python -m uvicorn twin.api.main:app --reload          # from the backend directory

# client
npm install && npm run dev                            # from the web directory
```

The client reads `VITE_TWIN_API` for the service origin. The service reads names of
credentials, never values checked into this repository: `LLM_API_KEY`,
`LLM_BASE_URL`, `LLM_MODEL` for a text planner, `META_MODEL_API_KEY`,
`META_MODEL_BASE_URL`, `META_MODEL_NAME` for the Muse route, and `PAYPAL_CLIENT_ID`,
`PAYPAL_SECRET`, `PAYPAL_ENVIRONMENT` for settlement. With no model keys the service
still answers and says which route it took. With no PayPal credentials it settles
against a deterministic sandbox transport; the real transport has to be asked for
explicitly and refuses to start without its credentials. `TWIN_DB_PATH` moves the
store, `TWIN_ALLOW_ORIGINS` says which client origins may call it, and
`TWIN_RECONCILE_SEC` — off by default — turns on the background sweep of payments
that are still waiting for an answer.

A headset has no keyboard, so the client signs itself in: the first visit opens its
own account and keeps it. To put a table on an account you already have, open the
app once with `?email=...&password=...` and it joins that world from then on.

## Verification status

The service is covered by 208 tests that run the forecast, the forks, the policy
engine, the payment state machine, the settlement catalog, the accounts, the audit
trail and the real PayPal transport against a gateway that answers on a socket.

The client typechecks and builds, and its scene document validates against the SDK's
own schema and component catalog, so every asset id, component and field the code
names is real. Its account paths were then run in a real browser against the dev
server: an account is provisioned before the first fetch, every request after it
carries a bearer token, an anonymous request is refused, a pipe pulled with a pointer
forks a second world, and a payment left in **unknown** is reconciled by the client on
the next heartbeat without being asked.

The settlement-rail, currency and background-reconciliation work added in this round
is covered by the service tests and by the client typecheck and build. It was not
driven in a browser or an XR session on this machine, so nothing about how those
panels look or feel on the table should be read as tested.

Live immersive evidence was **not** captured on this machine: the managed XR browser
would not start alongside the browser already running here, so no claim about headset
poses, hand tracking, controller rays or framing should be read as tested. Run
`npm run dev` on a clean machine to get that evidence.
