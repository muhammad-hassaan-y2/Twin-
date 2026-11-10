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

- **integration** — the seam between them. swarm-oversight's principal-wide
  monitor is enforced at tabletop-twin's real settlement boundary, so the twin's
  PayPal and rail payments gain the cross-mandate aggregate bound that neither
  project enforces alone. It is additive: both baselines are unchanged.

Each project's own README says what it is and how to run it. Start with
[tabletop-twin/README.md](tabletop-twin/README.md) and
[swarm-oversight/README.md](swarm-oversight/README.md), and read
[integration/README.md](integration/README.md) for the joined system and the one
command that demonstrates the gap being closed.