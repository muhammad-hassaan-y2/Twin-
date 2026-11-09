# Tabletop Twin — specs

Tabletop Twin is a hand-sized model of one person's next 90 days of money,
placed on their real table and moved with their hands. The cash flow is drawn as
a landscape: a river of money, stones that are bills, a boat that is a late
invoice. The person can bend the future by pulling on it, and the twin explains
what would happen.

These documents explain the product without prescribing the code. Read 01 first;
the rest add one subject each.

| Spec | What it explains |
| --- | --- |
| [01-product](01-product.md) | What the product is, what the table shows, what a session feels like |
| [02-architecture](02-architecture.md) | The two halves and one turn of the loop |
| [03-forecast](03-forecast.md) | The 90-day range, what-if comparisons, and the twin's track record |
| [04-policy-and-guardrails](04-policy-and-guardrails.md) | The two gates every request passes |
| [05-payments](05-payments.md) | The life of a payment and how unknowns are handled |
| [06-planner](06-planner.md) | What the twin may do, and what it may say |
| [07-accounts-and-storage](07-accounts-and-storage.md) | Private worlds, saved state and the audit trail |
| [08-api](08-api.md) | What the table asks the service to do |
| [09-client](09-client.md) | Placement, gestures, panels and accessibility |
| [10-verification](10-verification.md) | What is tested, and what is not yet proven |

## Five promises

1. Every number on the table is calculated by code, never invented by a language
   model.
2. The table draws and listens; it never calculates money or decides anything.
3. A request without a known account is refused; the service never guesses whose
   money it is looking at.
4. When a payment outcome is unknown, the service checks before charging again;
   it never retries blindly.
5. Every refusal names the rule that refused it.
