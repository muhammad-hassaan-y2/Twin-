"""The rule planner: the same job, no model, no key, no network.

This is not a stub for when a model is unavailable — it is the baseline the
model has to beat, and the reason the demo still runs on a plane with no wifi.
"""

from __future__ import annotations

import json
import re

from .tools import ToolCall


class RulePlanner:
    """Deterministic intent routing over the same five tools."""

    name = "rules"

    _CHASE = re.compile(r"\b(chase|nudge|remind|follow up|invoice|get paid|unpaid|overdue)\b|has ?n[o']?t paid|still not paid|\bdoes not owe\b", re.I)
    _CANCEL = re.compile(r"\b(cancel|kill|stop|unsubscribe|drop)\b", re.I)
    _WHEN = re.compile(r"\b(day|by)\s+(\d{1,3})\b|\b(\d{1,3})\s*days?\b", re.I)
    _DRY = re.compile(r"\b(run out|dry|shortfall|broke|empty|low)\b", re.I)
    _COMPARE = re.compile(r"\b(what if|would|compare|instead|better|fork|branch)\b", re.I)
    _SHOW = re.compile(r"\b(show|look|point|highlight|where)\b", re.I)
    _RAILS = re.compile(
        r"\b(rail|paypal|wise|wire|bank transfer|cross[- ]border|currency|settle|which way)\b", re.I
    )

    def plan(self, intent: str, context: dict) -> list[ToolCall]:
        text = (intent or "").strip()
        horizon = int(context.get("horizon_days", 90))
        calls: list[ToolCall] = [ToolCall("forecast", {"horizon_days": horizon}, "every answer starts from the numbers")]

        cancellable = [e for e in context.get("cancellable", ()) if _matches(e, text)]
        chasable = [e for e in context.get("chasable", ()) if _matches(e, text)]
        named = [e for e in context.get("events", ()) if _matches(e, text)]

        if self._CANCEL.search(text) and cancellable:
            calls.append(
                ToolCall(
                    "fork",
                    {"label": f"cancel {cancellable[0]['label']}", "cancel_event_ids": [cancellable[0]["id"]]},
                    "the user named something they could stop paying for",
                )
            )
        if self._CHASE.search(text) and chasable:
            calls.append(
                ToolCall(
                    "fork",
                    {"label": f"chase {chasable[0]['label']}", "chase_event_ids": [chasable[0]["id"]]},
                    "the user named an inbound that is late",
                )
            )
        if self._DRY.search(text) or self._WHEN.search(text):
            day = _day_from(text)
            target = {"target": "driest"} if day is None else {"target": "day", "id": str(day)}
            calls.append(ToolCall("highlight", target, "the user asked when the water is thinnest"))
        if self._SHOW.search(text) and not chasable and not cancellable:
            calls.append(ToolCall("highlight", {"target": "driest"}, "a bare request to look at the world"))
        if self._COMPARE.search(text) and cancellable:
            calls.append(
                ToolCall(
                    "fork",
                    {"label": f"drop {cancellable[0]['label']}", "cancel_event_ids": [cancellable[0]["id"]]},
                    "the user is weighing a change",
                )
            )
        if self._RAILS.search(text):
            args = {"event_id": named[0]["id"]} if named else {}
            calls.append(ToolCall("quote_rails", args, "the user asked how this payment should be moved"))
        if len(calls) == 1:
            calls.append(
                ToolCall("highlight", {"target": "driest"}, "nothing specific was asked, so show the pinch")
            )
        return _dedupe(calls)

    def narrate(self, intent: str, results: list[dict], context: dict | None = None) -> str:
        """Plain-language readout assembled from computed facts only."""
        quoted = next((result for result in results if "quotes" in result), None)
        if quoted:
            options = [row for row in quoted["quotes"] if not row["excluded"]]
            where = quoted["country"] or "that recipient"
            if not options:
                return f"None of my rails can reach {where}. Wire one that serves it and ask again."
            cheapest = options[0]
            return (
                f"{cheapest['label']} is the cheapest of the rails I have for {where}: "
                f"{cheapest['fee_dollars']} to move {quoted['amount_dollars']}. "
                f"I am currently settling on {quoted['settles_on']}."
            )
        for result in results:
            if "delta" in result:
                d = result["delta"]
                return (
                    f"{result['label']}: the floor moves {d['min_balance_change_dollars']} dollars and the "
                    f"cost changes by {d['cost_change_dollars']}. I read that as {d['verdict']}."
                )
            if "forecast" in result:
                f = result["forecast"]
                if f.get("shortfall_day") is not None:
                    return (
                        f"The river thins at day {f['pinch_day']}, and on one run in two you are under water "
                        f"by day {f['shortfall_day']}."
                    )
                if f["dry_run_percent"]:
                    return (
                        f"The middle path never goes under — its lowest is {f['median_low_dollars']} dollars "
                        f"around day {f['pinch_day']} — but {f['dry_run_percent']} of {f['runs']} runs do."
                    )
                return (
                    f"Lowest point is {f['median_low_dollars']} dollars around day {f['pinch_day']}. "
                    f"You stay above water across all {f['runs']} runs."
                )
        return "I ran the numbers and nothing changed."


def _dedupe(calls: list[ToolCall]) -> list[ToolCall]:
    """Two rules can read the same sentence and ask for the same fork once each.

    A label is speech, not an effect, so it stays out of the signature.
    """
    seen: set[tuple] = set()
    out: list[ToolCall] = []
    for call in calls:
        effect = {k: v for k, v in call.args.items() if k != "label"}
        signature = (call.tool, json.dumps(effect, sort_keys=True))
        if signature in seen:
            continue
        seen.add(signature)
        out.append(call)
    return out


def _matches(entry: dict, text: str) -> bool:
    haystack = text.lower()
    words = [w for w in re.split(r"[^a-z0-9]+", entry.get("label", "").lower()) if len(w) > 3]
    return any(w in haystack for w in words) or entry.get("id", "").lower() in haystack


def _day_from(text: str) -> int | None:
    match = RulePlanner._WHEN.search(text)
    if not match:
        return None
    for group in match.groups():
        if group and group.isdigit():
            return int(group)
    return None
