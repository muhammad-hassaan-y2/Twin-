# Twin

This repository holds two projects and the integration that joins them.

- **tabletop-twin** — a miniature of one person's next ninety days of cash,
  standing on their real table, that they can push around with their hands. A
  Python service owns the ledger, the forecast, the spending policy, a payment
  state machine and a real PayPal settlement transport; an Immersive Web SDK
  client owns the table, the gestures and the captions. Every world belongs to an
  account, and every number on the table is computed by code, never by a language
  model.

- **swarm-oversight** — the Apart Swarm Alignment sprint entry (Track 4,
  multi-agent oversight and control). It measures the aggregate gap in agent
  payment protocols such as Google's AP2: a per-mandate spending cap does not bind
  the principal across separately issued mandates. A swarm-level monitor and a
  gateway score defences in money, from seeded logs, with confidence intervals and
  negative controls.

- **integration** — the joined system: a PayPal-centred settlement hub and a client
  billing desk guarded by swarm-oversight. Twenty-six audit, tax and finance roles
  review an engagement; binding findings become payment instructions; a named person
  clears them; the principal-wide monitor holds the aggregate bound; the merchant book
  bills the client through PayPal and captures once. A model can act on that book only
  through tools that refuse to set an amount or approve a payment. This branch extends
  tabletop-twin; swarm-oversight is unchanged.

Each project's own README says what it is and how to run it. Start with
[tabletop-twin/README.md](tabletop-twin/README.md) and
[swarm-oversight/README.md](swarm-oversight/README.md), and read
[integration/README.md](integration/README.md) for the joined system. From `integration`,
`python -m oversight_twin.showcase` tells the whole story in one command, with every
figure measured during the run.