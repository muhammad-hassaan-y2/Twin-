# 10 — How we know it works

## The service

The backend tests cover the forecast, what-if comparisons, spending rules, the
truth checks, the payment lifecycle, payment methods, the model route, accounts,
the daily routine and the persona. They run against a real PostgreSQL: either a
server you name, or a throwaway one started and stopped by the tests.

Two kinds of tests are worth calling out:

- Regression tests take a known failure, run it with the protection in place, then
  remove that one protection and prove the bad outcome returns.
- Every truth-check rule has a test where it fires, and a control where only that
  rule is removed.

No test uses a real credential. Refused credentials, rate limits, lost replies and
invented figures are exercised against gateways that answer on a real socket.

## The client

Type checking and the production build must pass, and the scene document must
validate against the SDK schema. Account flows, panels, rejection and streaming
have been driven in a real browser against the development server.

## What is not proven yet

- A one-second hand pinch and the final settling panel state.
- Any real headset session: no table surface, head pose, hand tracking, controller
  ray or final placement has been tested on a device.
- Immersive renders have only been seen through the managed editor.

To close that gap, run the client with a headset and drive the gestures in an
immersive session. Until then, do not describe these as tested.

## Running the checks

- Backend: install the package with its development extras and run the test suite.
- Client: install, then run the type check and the production build.
