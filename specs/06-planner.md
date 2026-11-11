# 06 — The twin's brain: what it may do and say

## Five things the twin can do

The language model's entire power is choosing one of five actions and filling in
arguments that the service checks:

| Action | What it asks for |
| --- | --- |
| Forecast | Recompute the 90-day range |
| Fork | Recompute with one decision changed, and compare |
| Highlight | Point the orb at a day, a bill, a what-if or the driest point |
| Propose | Suggest a payment or subscription change; it executes nothing |
| Quote rails | Price every payment method and name those that cannot reach the country |

It cannot add a sixth action, invent an argument, do arithmetic, or move money.

## Model or rules

There are two planners behind the same interface:

- a deterministic rule-based planner that always works with no key and no
  network, and
- a model planner that asks a hosted model and falls back to the rules on any
  failure.

The table always works. A missing or slow model never blocks it; the twin simply
says who answered. Every answer reports its route: the model, or the rules and
the reason the model was not used. Credentials are never printed.

## What it is allowed to say

A number that was not calculated is never spoken. Before an answer is shown, its
numbers are checked against the figures code produced. When the answer is
streamed, only whole sentences that pass that check are released. If a sentence
fails, it is not shown; the rule planner's verified sentence replaces the whole
answer.

The final complete answer is what the table displays and what the world records.
