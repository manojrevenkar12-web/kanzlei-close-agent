"""May this proposal be booked without a person looking at it?

A logistic model over what the proposal rests on (memory, classifier, document, match). Trained
by `python -m kanzlei_sim train` on development months, with the threshold chosen in grouped
cross-validation so that wrong automatic bookings stay under the configured rate. Without a model
file nothing is booked automatically.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

FEATURES = (
    "memory_share",
    "memory_uses_log",
    "memory_agrees",
    "classifier_p",
    "classifier_margin",
    "classifier_agrees",
    "has_document",
    "structured_document",
    "match_score",
    "tax_from_document",
    "recurring",
    "amount_deviation",
    "family_risk",
    "new_counterparty",
    "from_model_reader",
    "money_in",
)


@dataclass
class DecisionModel:
    mean: list[float]
    scale: list[float]
    coef: list[float]
    intercept: float
    threshold: float
    version: str = "none"

    @classmethod
    def load(cls, path: Path) -> DecisionModel:
        if not path.exists():
            return cls([0.0] * len(FEATURES), [1.0] * len(FEATURES), [0.0] * len(FEATURES), -10.0, 1.01, "missing")
        d = json.loads(path.read_text(encoding="utf-8"))
        if list(d["features"]) != list(FEATURES):
            raise ValueError("decision model was trained on other features; retrain it")
        return cls(
            d["mean"], d["scale"], d["coef"], float(d["intercept"]), float(d["threshold"]), d.get("version", "?")
        )

    def probability(self, x: list[float]) -> float:
        z = self.intercept + sum(
            c * (v - m) / s for c, v, m, s in zip(self.coef, x, self.mean, self.scale, strict=True)
        )
        return 1.0 / (1.0 + math.exp(-max(min(z, 40.0), -40.0)))
