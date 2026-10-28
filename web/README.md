# Tabletop Twin client

The AR half: a miniature of the next ninety days of one person's cash, standing on
the table in front of them, about ninety centimetres wide.

## What this client is allowed to know

Nothing about money. It asks a service for a scene description and draws it. Every
height, width, opacity and caption on the table is copied or scaled from that
payload; the client adds no arithmetic, no thresholds, and no verdicts of its own.
If the service is unreachable it says so plainly, stops offering approvals, and
spends nothing.

The three-dimensional forms are authored in code as reusable assets so that a
quantile wall, a stone, a boat or a wheel can be placed many times and scaled
independently. Their proportions come from the metaphor, not from a downloaded
model, and each one keeps its own named parts so a hand or a ray can act on the
right piece of it.

## Hands only

Turning the time wheel scrubs the horizon. Pulling a ribbon out of the river forks
a branch and spawns a second miniature. Pulling a subscription pipe and letting it
return asks whether that subscription should be cancelled. Holding a pinch for a
full second on the approval token approves; a shorter hold does nothing. Each
gesture sends a request and waits; none of them changes state on their own.

The river itself is deliberately not grabbable, and the wheel is only ever written
by the client when no hand is holding it, so a gesture and the drawing system never
fight over the same transform.

## Accessibility

Speech is mirrored as captions on a panel, so the app is complete with sound off.
Every gesture has a ray-clickable equivalent on the panels. Probability, risk and
growth are each carried by two channels — fog density and size, height and
position relative to the table, garden growth rather than a dial — so colour is
never the only signal, and the palette is chosen to stay separable for colourblind
viewers.

## Running it

```sh
npm install
npm run dev
```

Set `VITE_TWIN_API` if the service is not on its default origin. `npm run typecheck`
and `npm run build` must both pass before a change is considered finished.

## Verification status

Typechecking and the production build pass. The scene document validates against the
SDK's own scene schema and against a component catalog built from the framework's
real components plus the ones this app registers, so every asset id, component name
and field authored in the scene or written at runtime is provably declared. Live
visual, gesture and XR evidence was not captured here: the managed editor never
became command-ready on this machine, so nothing in this file should be read as
"tested on a headset" until someone runs it.
