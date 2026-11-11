"""What the twin remembers, read back as figures the code can prove.

The summariser only counts rows in the action ledger. It never asks a model to
recall something, so a summary is correct with no key and no network, and every
number in it traces to a logged decision.

A whole-history count answers "what has this table ever done" and nothing else,
which is not the question a person standing at the table is asking. Every fold
here therefore takes a window: *day* is what happened today, *week* is the last
seven days of them, *all* is the history. The window is a filter on the day each
entry was written down, so it costs nothing to check and cannot drift.
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

# How many days of the ledger each window reaches back over. `None` is the whole
# trail, which is what an auditor asks for and what a person glancing at the table
# never means.
WINDOWS: dict[str, int | None] = {"day": 1, "week": 7, "all": None}


def windowed(entries: list[dict], *, day: int, window: str = "all") -> list[dict]:
    """The rows written inside this window, in whatever order the trail arrived in.

    Order is deliberately not part of this contract: a session's log is appended oldest
    first and the store's read comes newest first, and every fold below is a counter, so
    both must give the same figures. An entry with no day on it is kept rather than
    dropped: a row this code cannot place in time is a bug in the writer, and silently
    losing it from a summary would hide that instead of showing it.
    """
    if window not in WINDOWS:
        raise ValueError(f"'{window}' is not a window this memory understands: {sorted(WINDOWS)}")
    span = WINDOWS[window]
    if span is None:
        return list(entries)
    return [entry for entry in entries if day - int(entry.get("day", day)) < span]


def per_day(entries: list[dict], *, day: int, window: str = "week") -> list[dict]:
    """The shape of the trail by day, so a week of nothing looks like one."""
    rows = windowed(entries, day=day, window=window)
    span = WINDOWS[window] or 1
    buckets: dict[int, Counter[str]] = {}
    for entry in rows:
        buckets.setdefault(int(entry.get("day", day)), Counter())[str(entry.get("kind", ""))] += 1
    return [
        {
            "day": offset,
            "asks": buckets.get(offset, Counter()).get("intent", 0),
            "moves": buckets.get(offset, Counter()).get("policy", 0),
            "refusals": buckets.get(offset, Counter()).get("approval_refused", 0)
            + buckets.get(offset, Counter()).get("rejection", 0),
        }
        for offset in range(max(0, day - span + 1), day + 1)
    ]


def summarise(entries: list[dict], *, persona: str, day: int, open_payments: int,
              window: str = "all") -> dict:
    """Fold the ledger into a shape an executive can read in ten seconds."""
    rows = windowed(entries, day=day, window=window)
    counts = Counter(str(entry.get("kind", "")) for entry in rows)
    verdicts = Counter(
        str(entry.get("verdict")) for entry in rows if entry.get("kind") == "policy" and entry.get("verdict")
    )
    rules = Counter(
        str(entry.get("rule")) for entry in rows if entry.get("kind") == "policy" and entry.get("verdict") == "deny"
    )
    per_recipient: Counter[str] = Counter()
    for entry in rows:
        if entry.get("kind") == "approval" and entry.get("recipient"):
            per_recipient[str(entry["recipient"])] += int(entry.get("amount_cents") or 0)

    moved = sum(per_recipient.values())
    refused = [
        {"rule": rule, "count": count} for rule, count in sorted(rules.items(), key=lambda pair: (-pair[1], pair[0]))
    ]
    rejections = [entry for entry in rows if entry.get("kind") == "rejection"]
    turned_down = sum(1 for entry in rejections if entry.get("applied"))
    too_late = len(rejections) - turned_down
    where = {"day": "today", "week": "this week", "all": "so far"}[window]
    sentences = [
        f"{persona} handled {counts.get('intent', 0)} asks and put forward "
        f"{counts.get('policy', 0)} money moves {where}."
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
        "window": window,
        "since_day": max(0, day - (WINDOWS[window] or day + 1) + 1),
        "entries_considered": len(rows),
        "entries_available": len(entries),
        "by_kind": {kind: counts.get(kind, 0) for kind in KINDS if counts.get(kind)},
        "verdicts": dict(verdicts),
        "denied_by_rule": refused,
        "settled_cents_by_recipient": dict(per_recipient.most_common(8)),
        "total_settled_cents": moved,
        "human_rejections": turned_down,
        "rejected_withdrawal_attempts": too_late,
        "open_payments": open_payments,
        "per_day": per_day(rows, day=day, window="week" if WINDOWS[window] is None or WINDOWS[window] > 7 else window),
        "said": " ".join(sentences),
    }


def digest(entries: list[dict], *, day: int, open_payments: int) -> dict:
    """What the twin is told about its own recent decisions when it is asked something.

    Before this, a question about yesterday could only be answered about today: the
    planner saw the ledger and the forecast, never the trail of what it had already
    refused or already moved. The numbers in here are the same arithmetic the summary
    endpoint makes, from the same rows, so a model that quotes them is quoting a log
    entry rather than a memory.
    """
    week = summarise(entries, persona="", day=day, open_payments=open_payments, window="week")
    today = summarise(entries, persona="", day=day, open_payments=open_payments, window="day")
    return {
        "window_days": WINDOWS["week"],
        "asks_this_week": week["by_kind"].get("intent", 0),
        "moves_this_week": week["by_kind"].get("policy", 0),
        "settled_cents_this_week": week["total_settled_cents"],
        "refused_this_week": sum(row["count"] for row in week["denied_by_rule"]),
        "held_gestures_refused_this_week": week["by_kind"].get("approval_refused", 0),
        "unresolved_payments": open_payments,
        "asks_today": today["by_kind"].get("intent", 0),
        "moves_today": today["by_kind"].get("policy", 0),
        "top_denied_rule": week["denied_by_rule"][0]["rule"] if week["denied_by_rule"] else "",
        "said": week["said"],
    }
