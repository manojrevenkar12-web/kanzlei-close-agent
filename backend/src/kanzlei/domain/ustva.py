"""The VAT return (Umsatzsteuer-Voranmeldung) from booking lines.

Each line carries a tax code. The side the tax-bearing account sits on gives the sign: an expense
debited is input tax, an expense credited (a refund) reduces it; revenue credited is a sale.
Bases are reported in full euros in the return (ELSTER), tax amounts in cents.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from kanzlei.config import TaxConfig
from kanzlei.domain.models import Line
from kanzlei.domain.money import split_gross, tax_on_net

OUTPUT_SIDE = {"U19", "U7", "IGL", "EU_SVC", "RC_OUT", "FREI"}


@dataclass
class Row:
    kz: str
    label: str
    base_cents: int = 0
    tax_cents: int = 0

    @property
    def base_euros(self) -> int:
        """ELSTER wants the base in full euros, cents dropped."""
        return int(self.base_cents / 100)


def compute(
    lines: Iterable[Line],
    cfg: TaxConfig,
    is_tax_account: Callable[[int], bool],
) -> dict[str, Row]:
    """`is_tax_account(account)` tells which side of a line carries the tax (not bank, not a
    personal account)."""
    rows: dict[str, Row] = {}

    def row(kz: str) -> Row:
        if kz not in rows:
            rows[kz] = Row(kz, cfg.kennzahl_labels.get(kz, kz))
        return rows[kz]

    for ln in lines:
        if ln.tax in ("NONE", "") or ln.tax not in cfg.kennzahlen:
            continue
        spec = cfg.kennzahlen[ln.tax]
        d_tax, c_tax = is_tax_account(ln.debit), is_tax_account(ln.credit)
        on_debit = d_tax if d_tax != c_tax else True
        sign = (-1 if on_debit else 1) if ln.tax in OUTPUT_SIDE else 1 if on_debit else -1
        rate = int(spec.get("rate", cfg.rates.get(ln.tax, 0)))
        if ln.tax in ("U19", "U7", "V19", "V7"):
            net, tax = split_gross(ln.amount_cents, cfg.rates[ln.tax])
        else:
            net, tax = ln.amount_cents, (tax_on_net(ln.amount_cents, rate) if rate else 0)
        if "base" in spec:
            r = row(spec["base"])
            r.base_cents += sign * net
            if ln.tax in ("U19", "U7", "IGE19"):
                r.tax_cents += sign * tax  # the tax column next to the base
        if "tax" in spec and spec["tax"] != spec.get("base"):
            row(spec["tax"]).tax_cents += sign * tax
        if "input" in spec:
            row(spec["input"]).tax_cents += sign * tax

    owed = sum(r.tax_cents for k, r in rows.items() if k in ("81", "86", "47", "85", "89"))
    deductible = sum(r.tax_cents for k, r in rows.items() if k in ("66", "61", "67"))
    r83 = row("83")
    r83.tax_cents = owed - deductible
    return dict(sorted(rows.items(), key=lambda kv: (kv[0] == "83", kv[0])))


def to_json(rows: dict[str, Row]) -> list[dict[str, object]]:
    return [
        {"kz": r.kz, "label": r.label, "base_cents": r.base_cents, "base_euros": r.base_euros, "tax_cents": r.tax_cents}
        for r in rows.values()
    ]
