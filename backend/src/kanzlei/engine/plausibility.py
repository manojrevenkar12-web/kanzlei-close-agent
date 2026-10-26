"""Is this month's VAT return in line with the client's last year? Robust, per Kennzahl.

A value far from the median of earlier months (robust z-score over the median absolute
deviation) and by more than a minimum amount is flagged for the tax advisor before sign-off.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from kanzlei.config import CloseConfig
from kanzlei.domain.money import fmt_de

WATCH = {"81": "base", "86": "base", "66": "tax", "83": "tax", "46": "base", "84": "base", "41": "base", "21": "base"}


@dataclass
class Flag:
    kz: str
    value_cents: int
    median_cents: int
    text: str


def check(
    current: dict[str, dict[str, int]],
    history: list[dict[str, dict[str, int]]],
    cfg: CloseConfig,
    labels: dict[str, str],
) -> list[Flag]:
    """`current`/`history`: kz -> {"base_cents", "tax_cents"}; history is one dict per earlier month."""
    if len(history) < cfg.plaus_min_months:
        return []
    flags: list[Flag] = []
    for kz, field in WATCH.items():
        key = f"{field}_cents"
        past = [h.get(kz, {}).get(key, 0) for h in history[-cfg.plaus_months :]]
        now = current.get(kz, {}).get(key, 0)
        if not any(past) and not now:
            continue
        med = statistics.median(past)
        mad = statistics.median([abs(v - med) for v in past]) * 1.4826
        diff = abs(now - med)
        if diff < cfg.plaus_min_abs_cents:
            continue
        z = diff / mad if mad > 0 else float("inf")
        if z >= cfg.plaus_mad_k:
            what = "Bemessungsgrundlage" if field == "base" else "Betrag"
            flags.append(
                Flag(
                    kz,
                    now,
                    int(med),
                    f"Kz {kz} ({labels.get(kz, kz)}): {what} {fmt_de(now)}, üblich {fmt_de(int(med))} (Median {len(past)} Monate)",
                )
            )
    return flags
