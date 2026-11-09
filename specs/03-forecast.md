# 03 — Forecasting, what-ifs and the twin's record

## The forecast

To answer "how will the next 90 days go?", the service plays the same 90 days
out thousands of times. Each run is slightly different because invoices arrive
late by different amounts. The result is a range, not a single number:

- the typical path, in the middle of all runs,
- a likely good path and a likely bad path,
- the chance of running out of money, and the first day that becomes more likely
  than not.

The river's width and its banks are those paths drawn as water.

## What-if forks

A fork changes exactly one decision — cancel a bill, chase an invoice, move a
date — and replays the 90 days with the same dice. Because only the decision
changed, any difference in the picture comes from that decision, not from luck.

The answer is a comparison: the worst balance, the first short day, the expected
late fees, the chance of running dry, and whether the range got narrower. It ends
with a one-word verdict such as better or worse.

## The twin's track record

When the twin says "there is a 70% chance you are short on day 40", that
statement is saved with the day it can be checked. When the day passes, it is
marked right or wrong.

Two things follow from those checks:

- a score of how honest the probabilities have been,
- the garden, which grows only when predictions resolve correctly. It is a
  scoreboard for accuracy, not a reward for using the app.

## The daily heartbeat

Each day the service walks through a short ordered routine written in the twin's
persona document: check what is due, what is late, what is unresolved, and say at
most one useful observation plus a wind-down line. The order lives in the
document, not in code.
