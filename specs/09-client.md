# 09 — The table you touch

## Placing it

In augmented reality, the client looks for a flat, upward-facing surface at table
height, within arm's reach, that holds still for a moment. The first one it finds
becomes the table, and the miniature turns to face the person. Placement is
decided once per session; if no suitable surface is found, the authored pose is
used.

## What the hands do

| Gesture | What happens |
| --- | --- |
| Twist the time wheel | Move through the 90 days; the table redraws |
| Pull a ribbon | Ask "what if this moves?" and get a second miniature to compare |
| Pull a subscription pipe | Ask what cancelling that subscription is worth |
| Hold a pinch for one second | Approve the pending payment, once |

A gesture only sends a request. The client does not change the world locally and
does not decide anything. While a hand holds the wheel, the client stops writing
to it.

## Panels

Four panels float above and behind the river, tilted toward the viewer: captions,
approval, the time wheel, and payment methods. They are placed so the landscape
stays the subject.

## Accessibility

- Every spoken line is also written as a caption.
- Every gesture has a panel or ray alternative, except settling money, which
  always needs the deliberate one-second hold.
- Probability is shown by fog density and by size; risk by height and by position.
  Colour is never the only signal.
- The palette is colourblind-safe, and a state change moves the band, chip and
  border together while the chip spells the state.
- Rejecting a payment has its own button and writes a rejection, so closing a
  panel is never mistaken for a decision.
