"""The twin earns its keep by being checked.

Every claim the orb makes is stored as a prediction with a probability and a
resolution day. When the day arrives, the outcome is recorded and the score
moves. That score is what grows the garden.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Iterable


class Outcome(str, Enum):
    OPEN = "open"
    HIT = "hit"
    MISSED = "missed"


@dataclass
class Prediction:
    id: str
    subject: str
    statement: str
    probability: float
    made_on_day: int
    resolves_on_day: int
    outcome: Outcome = Outcome.OPEN
    tool: str = "forecast"
    check: dict = field(default_factory=dict)

    def due_by(self, day: int) -> bool:
        return self.outcome is Outcome.OPEN and self.resolves_on_day <= day

    def resolve(self, happened: bool) -> None:
        if self.outcome is not Outcome.OPEN:
            raise ValueError(f"{self.id} already resolved")
        self.outcome = Outcome.HIT if happened else Outcome.MISSED

    def to_dict(self) -> dict:
        data = asdict(self)
        data["outcome"] = self.outcome.value
        return data


@dataclass
class Calibration:
    """Brier score over resolved predictions, mapped to something a human reads."""

    records: list[Prediction] = field(default_factory=list)

    def add(self, prediction: Prediction) -> Prediction:
        self.records.append(prediction)
        return prediction

    def resolve(self, prediction_id: str, happened: bool) -> Prediction:
        for record in self.records:
            if record.id == prediction_id:
                record.resolve(happened)
                return record
        raise KeyError(prediction_id)

    @property
    def resolved(self) -> Iterable[Prediction]:
        return (r for r in self.records if r.outcome is not Outcome.OPEN)

    @property
    def brier(self) -> float | None:
        scored = list(self.resolved)
        if not scored:
            return None
        total = 0.0
        for record in scored:
            label = 1.0 if record.outcome is Outcome.HIT else 0.0
            total += (record.probability - label) ** 2
        return total / len(scored)

    @property
    def accuracy_pct(self) -> int | None:
        """0-100 where 100 means every probability matched what happened."""
        score = self.brier
        if score is None:
            return None
        return round((1.0 - score) * 100)

    @property
    def resolved_count(self) -> int:
        return sum(1 for _ in self.resolved)

    @property
    def garden_stage(self) -> int:
        """Four weeks of confirmed predictions should visibly grow something."""
        return min(5, self.resolved_count // 3 + (1 if self.brier is not None and self.brier < 0.20 else 0))

    def reliability_bins(self, buckets: int = 5) -> list[dict]:
        """Calibration curve: predicted probability vs observed frequency."""
        groups: list[list[Prediction]] = [[] for _ in range(buckets)]
        for record in self.resolved:
            index = min(buckets - 1, int(record.probability * buckets))
            groups[index].append(record)
        out = []
        for i, group in enumerate(groups):
            if not group:
                continue
            predicted = sum(r.probability for r in group) / len(group)
            observed = sum(1 for r in group if r.outcome is Outcome.HIT) / len(group)
            out.append(
                {
                    "bin": f"{i / buckets:.1f}-{(i + 1) / buckets:.1f}",
                    "n": len(group),
                    "predicted": round(predicted, 3),
                    "observed": round(observed, 3),
                    "gap": round(abs(predicted - observed), 3),
                }
            )
        return out
