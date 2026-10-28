# Twin

One project: **Tabletop Twin** — a miniature of a person's next ninety days of
cash, standing on their real table, that they can push around with their hands.

It is a digital twin in the literal sense: something about a business is simulated
closely enough to be asked questions, and the answers are drawn as geometry rather
than typed into a chart. A Python service owns the ledger, the forecast, the
spending policy, the payment state machine and the twin's persona; an Immersive Web
SDK client owns the table, the gestures and the captions. Every world belongs to an
account, and every number on the table was computed by code, never by a language
model.

    tabletop-twin/backend    the service, its persona documents and its tests
    tabletop-twin/web        the immersive client

Start with [tabletop-twin/README.md](tabletop-twin/README.md) for what it is and how
to run it, and [tabletop-twin/backend/README.md](tabletop-twin/backend/README.md)
for what the service guarantees.
