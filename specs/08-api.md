# 08 — What the table asks the service to do

The client and the service exchange JSON over HTTPS. A request must say whose
world it is, either with a signed-in token or with the device key. Missing both is
refused, and a token wins over a device key.

The service offers a small set of actions, grouped by what the person is doing.

## Identity and health

- create or claim a world, sign in, sign out
- read the account and world summary
- read whether the service, the model, the payment methods and the daily routine
  are ready

## The table

- load the current picture
- ask a question and get an answer plus a new picture
- receive the same answer sentence by sentence while it is being phrased
- move through the 90 days
- pull a bill or subscription and get a comparison
- advance to the next day and get the twin's observations

## Money

- approve with a gesture, or reject with a name and reason
- retry a failed payment, or reconcile an unknown one
- choose a payment method and price the options
- set a recipient ceiling or the opening balance
- read, add or remove ledger events

## Memory

- read the audit log, or the same log written as sentences
- read every payment record

Everything the client shows comes back in one scene description, so it never has
to ask several systems and stitch them together. When an answer streams, only
whole checked sentences are sent; the final complete message is the one displayed
and saved.
