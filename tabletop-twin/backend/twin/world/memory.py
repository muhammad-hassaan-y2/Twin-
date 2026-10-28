"""What the twin remembers, read back as figures the code can prove.

The summariser only counts rows in the action ledger. It never asks a model to
recall something, so a summary is correct with no key and no network, and every
number in it traces to a logged decision.
"""

from __future__ import annotations

from collections import Counter

KINDS = (
    "intent",
    "policy",
    "approval",
    "approval_refused",
    "rejection",
    "retry",
    "reconcile",
    "heartbeat",
    "event_added",
    "event_removed",
    "ceiling_set",
)


def summarise(entries: list[dict], *, persona: str, day: int, open_payments: int) -> dict:
    """Fold the ledger into a shape an executive can read in ten seconds."""
    counts = Counter(str(entry.get("kind", "")) for entry in entries)
    verdicts = Counter(
        str(entry.get("verdict")) for entry in entries if entry.get("kind") == "policy" and entry.get("verdict")
    )
    rules = Counter(
        str(entry.get("rule")) for entry in entries if entry.get("kind") == "policy" and entry.get("verdict") == "deny"
    )
    per_recipient: Counter[str] = Counter()
    for entry in entries:
        if entry.get("kind") == "approval" and entry.get("recipient"):
            per_recipient[str(entry["recipient"])] += int(entry.get("amount_cents") or 0)

    moved = sum(per_recipient.values())
    refused = [
        {"rule": rule, "count": count} for rule, count in sorted(rules.items(), key=lambda pair: -pair[1])
    ]
    rejections = [entry for entry in entries if entry.get("kind") == "rejection"]
    turned_down = sum(1 for entry in rejections if entry.get("applied"))
    too_late = len(rejections) - turned_down
    sentences = [
        f"{persona} handled {counts.get('intent', 0)} asks and put forward {counts.get('policy', 0)} money moves."
    ]
    if moved:
        sentences.append(f"{moved / 100:.2f} dollars settled onward to {len(per_recipient)} recipient(s).")
    if verdicts.get("deny"):
        top = refused[0]["rule"] if refused else "the caps"
        sentences.append(f"{verdicts['deny']} were refused in code, most often by '{top}'.")
    if counts.get("approval_refused") or turned_down:
        sentences.append(
            f"{counts.get('approval_refused', 0)} gesture(s) were rejected as not an approval and "
            f"{turned_down} ask(s) a human turned down."
        )
    if too_late:
        sentences.append(f"{too_late} withdrawal(s) were refused because the money had already moved or settled.")
    if open_payments:
        sentences.append(f"{open_payments} payment(s) are still unresolved.")

    return {
        "persona": persona,
        "day": day,
        "entries_considered": len(entries),
        "by_kind": {kind: counts.get(kind, 0) for kind in KINDS if counts.get(kind)},
        "verdicts": dict(verdicts),
        "denied_by_rule": refused,
        "settled_cents_by_recipient": dict(per_recipient.most_common(8)),
        "total_settled_cents": moved,
        "human_rejections": turned_down,
        "rejected_withdrawal_attempts": too_late,
        "open_payments": open_payments,
        "said": " ".join(sentences),
    }
