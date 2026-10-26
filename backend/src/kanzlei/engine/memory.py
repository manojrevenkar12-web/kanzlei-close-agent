"""What this client's books say about a counterparty: how it was booked before, how often, how much.

Built from the firm's imported DATEV history and from everything booked since. A counterparty
is found by IBAN first, then by its normalized name.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from kanzlei.config import CloseConfig
from kanzlei.domain.text import name_similarity, normalize_iban, normalize_name


@dataclass(frozen=True)
class Use:
    family: str
    tax: str
    amount_cents: int
    on: date


@dataclass
class MemoryHit:
    key: str
    family: str
    tax: str
    share: float
    uses: int
    months: int
    recurring: bool
    median_cents: int
    dominant: bool
    by: str  # iban | name | fuzzy

    def amount_deviation(self, amount_cents: int) -> float:
        if self.median_cents <= 0:
            return 1.0
        return abs(abs(amount_cents) - self.median_cents) / self.median_cents


@dataclass
class ClientMemory:
    cfg: CloseConfig
    uses: dict[str, list[Use]] = field(default_factory=dict)

    def add(self, *, iban: str | None, name: str, use: Use) -> None:
        keys = []
        ib = normalize_iban(iban)
        if ib:
            keys.append("iban:" + ib)
        nn = normalize_name(name)
        if nn:
            keys.append("name:" + nn)
        for k in keys:
            self.uses.setdefault(k, []).append(use)

    def _hit(self, key: str, by: str) -> MemoryHit | None:
        uses = self.uses.get(key)
        if not uses:
            return None
        fam_tax = Counter((u.family, u.tax) for u in uses)
        (family, tax), _n = fam_tax.most_common(1)[0]
        same = [u for u in uses if u.family == family]
        share = len(same) / len(uses)
        months = {(u.on.year, u.on.month) for u in same}
        amounts = [abs(u.amount_cents) for u in same]
        med = int(statistics.median(amounts)) if amounts else 0
        tol = self.cfg.recurring_amount_tolerance
        stable = sum(1 for a in amounts if med and abs(a - med) / med <= tol)
        recurring = len(months) >= self.cfg.recurring_min_months and stable >= 0.8 * len(amounts)
        dominant = len(uses) >= self.cfg.memory_min_uses and share >= self.cfg.memory_dominant_share
        return MemoryHit(key, family, tax, share, len(uses), len(months), recurring, med, dominant, by)

    def lookup(self, iban: str | None, name: str) -> MemoryHit | None:
        ib = normalize_iban(iban)
        if ib and (hit := self._hit("iban:" + ib, "iban")):
            return hit
        nn = normalize_name(name)
        if not nn:
            return None
        if hit := self._hit("name:" + nn, "name"):
            return hit
        best, score = None, 0.0
        for k in self.uses:
            if not k.startswith("name:"):
                continue
            s = name_similarity(nn, k[5:])
            if s > score:
                best, score = k, s
        if best and score >= 0.86:
            return self._hit(best, "fuzzy")
        return None
