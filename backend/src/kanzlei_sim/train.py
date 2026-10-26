"""Training the two learned parts. Both write plain weights into config/; the engine never imports
scikit-learn.

1. The text classifier (engine/classifier.py): from the group's pooled history, every firm,
   both charts, in family space. Grouped cross-validation by counterparty estimates how it does
   on names it has never seen, which is the case it is for.
2. The decision model (engine/decision.py): from the development months, closed once with nothing
   booked automatically. The threshold is the lowest at which, in cross-validation grouped by
   client, wrong automatic bookings stay under `max_wrong_share` of what is booked automatically.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from scipy.sparse import csr_matrix, vstack
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold

from kanzlei.config import families, lexicon
from kanzlei.domain.text import normalize_name
from kanzlei.engine.classifier import DIM, Classifier, featurize
from kanzlei.engine.decision import FEATURES
from kanzlei_sim.run import Record
from kanzlei_sim.scenario import Firm, cents


def classifier_rows(firms: list[Firm], periods: list[str]) -> tuple[list[dict[int, float]], list[str], list[str]]:
    X: list[dict[int, float]] = []
    y: list[str] = []
    groups: list[str] = []
    for f in firms:
        for c in f.clients:
            for period in periods:
                for e in c.months.get(period, []):
                    if e.truth is None or e.truth.family == "clearing":
                        continue
                    p = c.party(e.party)
                    doc = e.document
                    if e.kind == "invoice":
                        assert doc is not None
                        money_in = doc.direction == "out"
                        amount = sum(cents(ln.net) for ln in doc.lines)
                        remittance = ""
                    else:
                        money_in = e.amount > 0
                        amount = cents(abs(e.amount))
                        remittance = e.reference
                    doc_text = ""
                    if doc is not None:
                        seller = p.name if doc.direction == "in" else c.name
                        doc_text = " ".join([seller, *(ln.text for ln in doc.lines), *doc.notes])
                    X.append(featurize(p.name, remittance, doc_text, money_in, amount))
                    y.append(e.truth.family)
                    groups.append(normalize_name(p.name) or p.key)
    return X, y, groups


def _matrix(rows: list[dict[int, float]]) -> csr_matrix:
    data, idx, ptr = [], [], [0]
    for r in rows:
        for k, v in r.items():
            idx.append(k)
            data.append(v)
        ptr.append(len(idx))
    return csr_matrix((np.array(data), np.array(idx), np.array(ptr)), shape=(len(rows), DIM))


def lexicon_rows() -> tuple[list[dict[int, float]], list[str]]:
    """One short pseudo-payment per lexicon word: what any bookkeeper knows before the first client
    (config/lexicon.yaml), so every family has a prior even where the group's history is thin."""
    fams = families()
    X, y = [], []
    for fam, words in lexicon().items():
        if fam not in fams:
            continue
        money_in = fams[fam].side == "revenue" or fam == "private_deposit"
        for w in words:
            X.append(featurize(w, w, w, money_in, 10000))
            y.append(fam)
    return X, y


def train_classifier(
    firms: list[Firm], periods: list[str], out: Path, c_reg: float = 4.0, lexicon_weight: float = 0.5
) -> dict[str, Any]:
    rows, y, groups = classifier_rows(firms, periods)
    lex_rows, lex_y = lexicon_rows()
    X = _matrix(rows)
    yy = np.array(y)
    XL, yL = _matrix(lex_rows), np.array(lex_y)
    folds = GroupKFold(n_splits=5)
    hits = 0
    for tr, te in folds.split(X, yy, groups):
        m = LogisticRegression(C=c_reg, max_iter=3000)
        m.fit(
            vstack([X[tr], XL]),
            np.concatenate([yy[tr], yL]),
            sample_weight=np.concatenate([np.ones(len(tr)), np.full(len(yL), lexicon_weight)]),
        )
        hits += int((m.predict(X[te]) == yy[te]).sum())
    model = LogisticRegression(C=c_reg, max_iter=3000)
    model.fit(
        vstack([X, XL]),
        np.concatenate([yy, yL]),
        sample_weight=np.concatenate([np.ones(len(yy)), np.full(len(yL), lexicon_weight)]),
    )
    clf = Classifier(
        classes=[str(c) for c in model.classes_],
        weights=model.coef_.astype(np.float32),
        bias=model.intercept_.astype(np.float32),
    )
    clf.save(out)
    return {
        "rows": len(y),
        "families": len(model.classes_),
        "cv_unseen_counterparty_accuracy": round(hits / len(y), 4),
        "label_counts": dict(Counter(y).most_common()),
    }


def wilson_upper(wrong: int, n: int, z: float = 1.96) -> float:
    """Upper end of the 95 % Wilson interval for a share `wrong`/`n`."""
    if n == 0:
        return 1.0
    p = wrong / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (centre + margin) / denom


def train_decision(records: list[Record], out: Path, max_wrong_share: float) -> dict[str, Any]:
    """Learns how often a proposal is wrong from what it rests on, on every proposal of the
    development months (rule-held ones included: they show which evidence is weak). The threshold
    applies to proposals no rule held: the lowest at which the 95 % upper bound of the wrong share
    among those booked automatically, out of fold, stays under `max_wrong_share`."""
    data = [r for r in records if r.features]
    X = np.array([r.features for r in data], dtype=float)
    y = np.array([1 if r.first_correct else 0 for r in data])
    eligible = np.array([not r.flags and r.first_route != "client" for r in data])
    groups = np.array([f"{r.client}:{r.period}" for r in data])
    mean, scale = X.mean(axis=0), X.std(axis=0)
    scale[scale == 0] = 1.0
    Xs = (X - mean) / scale
    oof = np.zeros(len(y))
    for tr, te in GroupKFold(n_splits=5).split(Xs, y, groups):
        if len(set(y[tr])) < 2:
            oof[te] = 1.0
            continue
        m = LogisticRegression(C=0.5, max_iter=3000, class_weight="balanced").fit(Xs[tr], y[tr])
        oof[te] = m.predict_proba(Xs[te])[:, 1]
    grid = [round(t, 3) for t in np.linspace(0.30, 0.995, 140)]
    stats = {}
    for t in grid:
        auto = eligible & (oof >= t)
        n_auto = int(auto.sum())
        wrong = int((auto & (y == 0)).sum())
        stats[t] = {
            "auto": n_auto,
            "wrong": wrong,
            "wrong_share": round(wrong / n_auto, 4) if n_auto else 0.0,
            "wrong_share_upper95": round(wilson_upper(wrong, n_auto), 4),
            "auto_share_of_eligible": round(n_auto / int(eligible.sum()), 4) if eligible.any() else 0.0,
        }
    allowed = [t for t in grid if stats[t]["auto"] and stats[t]["wrong_share_upper95"] <= max_wrong_share]
    threshold = min(allowed) if allowed else 1.01
    model = LogisticRegression(C=0.5, max_iter=3000, class_weight="balanced").fit(Xs, y)
    payload: dict[str, Any] = {
        "features": list(FEATURES),
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "coef": model.coef_[0].tolist(),
        "intercept": float(model.intercept_[0]),
        "threshold": threshold,
        "trained_on": {
            "proposals": len(y),
            "wrong": int((y == 0).sum()),
            "eligible": int(eligible.sum()),
            "client_months": len(set(groups)),
        },
        "cross_validation": {
            "threshold": threshold,
            **(stats.get(threshold) or {}),
            "max_wrong_share": max_wrong_share,
        },
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    payload["version"] = hashlib.sha256(json.dumps(payload["coef"]).encode()).hexdigest()[:10]
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload
