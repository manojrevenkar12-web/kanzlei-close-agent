"""The correct booking for an event, written separately from the engine (it reads only the chart
YAML and the tax YAML, never kanzlei.domain or kanzlei.engine), so a bug in the engine's rules
cannot hide in the answer key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from kanzlei_sim.scenario import Client, DocLine, Event, Firm, cents

CONFIG = Path(os.environ.get("KANZLEI_CONFIG_DIR", str(Path(__file__).resolve().parents[3] / "config")))


@dataclass(frozen=True)
class TLine:
    debit: int
    credit: int
    tax: str
    amount: int
    ref: str = ""  # Belegfeld 1 (invoice number), not part of the comparison

    def key(self) -> tuple[Any, ...]:
        return (self.debit, self.credit, self.tax, self.amount)


@lru_cache
def _chart(name: str) -> dict[str, Any]:
    d: dict[str, Any] = yaml.safe_load((CONFIG / "charts" / f"{name.lower()}.yaml").read_text(encoding="utf-8"))
    return d


@lru_cache
def _tax() -> dict[str, Any]:
    d: dict[str, Any] = yaml.safe_load((CONFIG / "tax.yaml").read_text(encoding="utf-8"))
    return d


def account(chart: str, family: str, tax: str, role: str | None = None) -> int:
    rows = _chart(chart)["accounts"]
    for fam, tx in ((family, tax), ("*", tax), (family, "*")):
        if fam == "*" and role is not None:
            continue
        for a in rows:
            if a["family"] == fam and str(a["tax"]) == tx and a.get("role") == role:
                return int(str(a["account"]))
    raise KeyError(f"{chart}: no account for {family}/{tax}/{role}")


def system(chart: str, key: str) -> int:
    return int(_chart(chart)["system"][key])


def _half_up(x: Decimal) -> int:
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _code(category: str, rate: int, side: str, client: Client, party_country: str, buyer_country: str) -> str:
    eu = set(_tax()["eu_countries"])
    if client.vat_regime == "klein":
        return "NONE"
    if client.vat_regime == "befreit":
        return "FREI" if side == "revenue" else "NONE"
    if category == "S":
        return ("U" if side == "revenue" else "V") + str(rate)
    if category == "AE":
        if side == "revenue":
            return "EU_SVC" if buyer_country in eu else "RC_OUT"
        return "RC_BAU19" if party_country == "DE" else ("RC_EU19" if party_country in eu else "RC_DRITT19")
    if category == "K":
        return "IGL" if side == "revenue" else "IGE19"
    if category == "E":
        return "FREI" if side == "revenue" else "NONE"
    if category == "O":
        return "RC_DRITT19" if side != "revenue" and party_country not in eu and party_country != "DE" else "NONE"
    return "NONE"


def _groups(lines: list[DocLine]) -> list[tuple[int, str, int]]:
    """(rate, category, gross cents) per tax group, tax rounded per group like an invoice."""
    acc: dict[tuple[int, str], int] = {}
    for ln in lines:
        acc[(ln.rate, ln.category)] = acc.get((ln.rate, ln.category), 0) + cents(ln.net)
    out = []
    for (rate, cat), net in acc.items():
        tax = _half_up(Decimal(net) * rate / 100) if cat == "S" else 0
        out.append((rate, cat, net + tax))
    return out


def _scale(parts: list[tuple[str, int, str | None]], total: int) -> list[tuple[str, int, str | None]]:
    whole = sum(p[1] for p in parts)
    if whole == total or whole == 0:
        return parts
    out, run = [], 0
    for i, (t, g, r) in enumerate(parts):
        v = total - run if i == len(parts) - 1 else round(g * total / whole)
        out.append((t, v, r))
        run += v
    return out


def portions(ev: Event, client: Client, firm: Firm, amount: int) -> list[tuple[str, int, str | None]]:
    """(tax code, gross cents, role) for an event's booking, before the 70/30 meals split."""
    assert ev.truth is not None
    t = ev.truth
    fam = t.family
    side = "revenue" if fam == "revenue" else "expense"
    party = client.party(ev.party)
    if t.portions:
        parts = [(p["tax"], cents(float(p["gross"])), p.get("role")) for p in t.portions]
        return _scale(parts, amount)
    doc = ev.document
    if t.tax is not None or doc is None or not doc.lines:
        parts = [(t.tax or "NONE", amount, None)]
    else:
        buyer_country = party.country if doc.direction == "out" else "DE"
        parts = [
            (_code(cat, rate, side, client, party.country, buyer_country), g, None)
            for rate, cat, g in _groups(doc.lines)
        ]
        parts = _scale(parts, amount)
    if fam == "equipment":
        parts = _equipment(parts, doc.lines if doc else [], client)
    return parts


def _equipment(
    parts: list[tuple[str, int, str | None]], lines: list[DocLine], client: Client
) -> list[tuple[str, int, str | None]]:
    eq = _tax()["equipment"]
    small, gwg = int(eq["small_net_cents"]), int(eq["gwg_net_cents"])

    def role(unit_net: int) -> str:
        return "small" if unit_net <= small else ("gwg" if unit_net <= gwg else "asset")

    if len(parts) == 1 and lines:
        tax, gross, _ = parts[0]
        vat = tax in ("V19", "V7")
        by_role: dict[str, int] = {}
        for ln in lines:
            net = cents(ln.net)
            # Without input VAT deduction the VAT is part of the cost (unit value = gross).
            unit_basis = net if vat else _half_up(Decimal(net) * (100 + ln.rate) / 100)
            r = role(round(unit_basis / max(ln.quantity, 1)))
            by_role[r] = by_role.get(r, 0) + net
        return _scale([(tax, n, r) for r, n in by_role.items()], gross)
    out = []
    for tax, gross, _ in parts:
        net = _half_up(Decimal(gross) * 100 / (100 + int(tax[1:]))) if tax in ("V19", "V7") else gross
        out.append((tax, gross, role(net)))
    return out


def _meals_split(parts: list[tuple[str, int, str | None]]) -> list[tuple[str, int, str | None]]:
    share = Decimal(str(_tax()["meals_deductible_share"]))
    out = []
    for tax, g, _ in parts:
        ded = _half_up(Decimal(g) * share)
        out += [(tax, ded, None), (tax, g - ded, "nondeductible")]
    return [p for p in out if p[1]]


def event_lines(
    ev: Event, client: Client, firm: Firm, personal: dict[str, int], invoices: dict[str, Event]
) -> list[TLine]:
    """The correct booking lines of one event (payment or OPOS invoice)."""
    assert ev.truth is not None
    ch = firm.chart
    bank = system(ch, "bank")
    t = ev.truth
    if ev.kind == "invoice":
        assert ev.document is not None
        doc = ev.document
        amount = gross_cents(doc.lines)
        parts = portions(ev, client, firm, amount)
        if t.family == "meals":
            parts = _meals_split(parts)
        pa = personal[ev.party]
        out = []
        for tax, g, role in parts:
            acct = account(ch, t.family, tax, role)
            supplier = doc.direction == "in"
            normal = not doc.credit_note
            # Supplier invoice: expense to Kreditor; customer invoice: Debitor to revenue; credit notes reverse.
            if supplier == normal:
                out.append(TLine(acct, pa, tax, g, doc.number))
            else:
                out.append(TLine(pa, acct, tax, g, doc.number))
        return out
    amount = cents(abs(ev.amount))
    money_in = ev.amount > 0
    if t.family == "clearing":
        out = []
        total_gross = sum(gross_cents(invoices[i].document.lines) for i in ev.settles)  # type: ignore[union-attr]
        run = 0
        for k, inv_id in enumerate(ev.settles):
            inv = invoices[inv_id]
            assert inv.document is not None
            g = gross_cents(inv.document.lines)
            paid = amount - run if k == len(ev.settles) - 1 else round(g * amount / total_gross)
            run += paid
            pa = personal[inv.party]
            ref = inv.document.number
            out.append(TLine(bank, pa, "NONE", paid, ref) if money_in else TLine(pa, bank, "NONE", paid, ref))
            disc = g - paid
            if disc > 0:
                main = max(_groups(inv.document.lines), key=lambda x: x[2])
                rate = main[0] if main[1] == "S" else 19
                if inv.document.direction == "out":
                    out.append(TLine(account(ch, "skonto_granted", f"U{rate}"), pa, f"U{rate}", disc, ref))
                else:
                    out.append(TLine(pa, account(ch, "skonto_received", f"V{rate}"), f"V{rate}", disc, ref))
        return out
    parts = portions(ev, client, firm, amount)
    if t.family == "meals":
        parts = _meals_split(parts)
    out = []
    for tax, g, role in parts:
        acct = account(ch, t.family, tax, role)
        out.append(TLine(bank, acct, tax, g) if money_in else TLine(acct, bank, tax, g))
    return out


def gross_cents(lines: list[DocLine]) -> int:
    return sum(g for _, _, g in _groups(lines))
