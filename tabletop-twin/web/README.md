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

## Where the table is

The surface this twin stands on is looked for rather than assumed. In an AR session the
first steady, upward-facing hit that sits at table height and within arm's reach becomes
the table, and the miniature turns to face whoever found it. A wall, the floor, a shelf
and anything across the room are all rejected, and a placement is taken once per session
and never revised, because a table that slides across the room when the estimate
improves is worse than one that stays where the app put it. With no session, no granted
hit-test, or nothing that qualifies, the authored pose stands — which is what a browser
without a headset sees, and what the orb's pointing is computed in, so a rotated table
still points at the right bill.

The panel band sits above and behind the table rather than across it. The three cards are
at chest height, clear of the channel, and the wheel's own readout hovers beside the
wheel instead of over it; every tilt is worked out from the standing head position, so a
card faces the person rather than the room.

## Accessibility

Speech is mirrored as captions on a panel, so the app is complete with sound off.
Every gesture has a ray-clickable equivalent on the panels, with one deliberate
exception: settling a payment above the approval floor takes a one-second hold, and no
button on any panel does it. That is the machine's rule, not a missing control — the
payment state machine refuses an approval whose gesture is not one of the two holds it
names, a pinch near the coin or a pointer pressed on it, and writes the refusal down — so
the alternative is a different hold rather than a lighter touch. A controller squeeze
counts, and so does a mouse held down on the coin, which is what makes the rule reachable
on a screen with no hands in it. Refusing has a button. Probability, risk and
growth are each carried by two channels — fog density and size, height and
position relative to the table, garden growth rather than a dial — so colour is
never the only signal, and the palette is chosen to stay separable for colourblind
viewers. The same holds on the panels: a state change moves the band, the chip and the
card border together, and the chip spells the state out, so no panel asks a person to
read a colour to know what is being asked of them.

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
and field authored in the scene or written at runtime is provably declared.

The four panels were then rendered by the running client in a real browser against the
dev server, from a device world with nothing stored. The caption card, the decision
card, the money panel and the plate above the wheel all drew from the client's own
redraw rather than from any test harness. A pointer press on the decision card's reject
button sent the refusal to the service, which answered 200 and kept it as a rejection
naming the reviewer and the reason; the caption card changed its whole surface to say
what the record now reads, and the money panel went back to saying nothing is
mid-flight. The same run tried to settle a payment with a click instead of a hold and
the machine refused it, so the exception described under Accessibility is measured, not
intended. Nothing reached the console and no request failed.

What this machine cannot reach is a session, and that gap has not moved. What did move is
the pointer: the coin now answers a pressed pointer held for the full second, and it was
driven that way in a real browser against a running service. A press of two hundred
milliseconds on the coin sent nothing at all. A press and hold of the full second sent
exactly one approval, whose gesture the service recorded as the one a pointer made, and the
payment settled. The same run then read an **unknown** payment out of the database and asked
the provider about it once, which left a reconcile entry in the ledger and took the record
out of the fog. So the one-second hold is proven as far as a mouse can prove it. What
remains unproven here is the near grab itself, the squeeze that holds it, the panel state
that only shows while a hold is settling, and how any of this reads from inside a headset.

The managed editor did become command-ready for this pass, and the composition was
checked with it rather than argued about: three renders of the authored hero view, the
first of which showed the panel band sitting so low and so wide that its bottom edges
covered the river, which is what moved the cards up and back and lifted the hero frame's
aim to the content centre. The scene document reports valid with no warnings on every
one of those renders, and the running app boots in a real browser with the placement
system registered — canvas present, WebXR available, nothing in the console beyond the
GPU driver's own readback warnings.

None of that is AR evidence. The XR app target never attached on this machine, so the
placement code has never seen a real surface, has never had a hit-test source granted,
and has never turned a miniature to face a person. Nothing in this file should be read
as "tested on a headset" until someone runs it.
