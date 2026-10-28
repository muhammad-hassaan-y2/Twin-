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
first. Test cancelling a subscription by pulling its pipe and letting it go back.
Approve a purchase by holding a pinch for a full second; reject it by saying so out
loud on a button. Every gesture is a request, never a mutation.

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
explicitly and refuses to start without its credentials.

## Verification status

Backend behaviour is covered by its test suite. The client typechecks, builds, and
its scene document validates against the SDK's own schema and component catalog, so
every asset id, component and field the code and the scene name is real. Live
visual and XR evidence was **not** captured: the managed editor on this machine
never became command-ready, so no screenshot, gesture or framing claim here should
be taken as tested until someone runs it.
