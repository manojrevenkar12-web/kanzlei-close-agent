"""Which family a payment belongs to, read from its words.

Signed feature hashing over the counterparty's name, the payment reference and the invoice lines,
plus the firm-neutral lexicon (config/lexicon.yaml). A multinomial logistic regression trained on
the pooled history of every firm in the group (in family space, so SKR03 and SKR04 firms learn
from each other). Training lives in kanzlei_sim/train.py; here only the weights are applied.
"""

from __future__ import annotations

import math
import zlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from kanzlei.config import config_dir, lexicon
from kanzlei.domain.text import fold, normalize_name, tokens

DIM = 1 << 13


def _h(s: str) -> tuple[int, float]:
    v = zlib.crc32(s.encode("utf-8"))
    return v % DIM, (1.0 if (v >> 20) & 1 else -1.0)


def featurize(counterparty: str, remittance: str, doc_text: str, money_in: bool, amount_cents: int) -> dict[int, float]:
    feats: dict[int, float] = {}

    def add(key: str, w: float = 1.0) -> None:
        i, s = _h(key)
        feats[i] = feats.get(i, 0.0) + s * w

    cp = normalize_name(counterparty)
    for w in cp.split():
        add("c:" + w, 1.5)
    padded = f" {cp} "
    for i in range(len(padded) - 3):
        add("g:" + padded[i : i + 4], 0.4)
    for w in tokens(remittance):
        if not w.isdigit():
            add("r:" + w)
    for w in tokens(doc_text):
        if not w.isdigit():
            add("d:" + w, 0.8)
    blob = fold(" ".join((counterparty, remittance, doc_text)))
    for fam, words in lexicon().items():
        hits = sum(1 for w in words if w in blob)
        if hits:
            add("lex:" + fam, 2.0 * min(hits, 2))
    add("dir:in" if money_in else "dir:out", 1.0)
    bucket = int(math.log2(max(abs(amount_cents), 100) / 100))
    add(f"amt:{min(bucket, 14)}", 0.5)
    norm = math.sqrt(sum(v * v for v in feats.values())) or 1.0
    return {k: v / norm for k, v in feats.items()}


@dataclass
class Classifier:
    classes: list[str]
    weights: np.ndarray  # (classes, DIM)
    bias: np.ndarray  # (classes,)

    @classmethod
    def load(cls, path: Path | None = None) -> Classifier | None:
        p = path or (config_dir() / "classifier.npz")
        if not p.exists():
            return None
        z = np.load(p, allow_pickle=False)
        return cls(classes=[str(c) for c in z["classes"]], weights=z["weights"], bias=z["bias"])

    def save(self, path: Path) -> None:
        np.savez_compressed(
            path,
            classes=np.array(self.classes),
            weights=self.weights.astype(np.float32),
            bias=self.bias.astype(np.float32),
        )

    def probabilities(self, feats: dict[int, float]) -> dict[str, float]:
        if not feats:
            return {}
        idx = np.fromiter(feats.keys(), dtype=np.int64)
        val = np.fromiter(feats.values(), dtype=np.float64)
        z = self.weights[:, idx] @ val + self.bias
        z = z - z.max()
        e = np.exp(z)
        p = e / e.sum()
        return {c: float(v) for c, v in zip(self.classes, p, strict=True)}


def top2(probs: dict[str, float]) -> tuple[str | None, float, float]:
    """(best family, its probability, margin over the second)."""
    if not probs:
        return None, 0.0, 0.0
    ranked = sorted(probs.items(), key=lambda kv: -kv[1])
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    return ranked[0][0], ranked[0][1], ranked[0][1] - second
