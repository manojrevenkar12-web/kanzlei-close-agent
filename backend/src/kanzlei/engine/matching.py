"""Which invoice does a payment settle?

Evidence per pair: the amount (exact, or less a cash discount), the invoice number in the payment
reference, the IBAN the invoice asks to be paid to, the names, the dates. One payment may settle
several invoices of one supplier. Pairs are assigned best first; when the runner-up is as good,
the payment is marked ambiguous and a person picks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import combinations

from kanzlei.config import CloseConfig, TaxConfig
from kanzlei.domain.text import find_invoice_numbers, name_similarity, normalize_iban
from kanzlei.formats.invoice import Invoice


@dataclass(frozen=True)
class Tx:
    id: int
    on: date
    amount_cents: int  # signed
    name: str
    iban: str | None
    remittance: str


@dataclass(frozen=True)
class Doc:
    id: int
    direction: str  # in: the client received it; out: the client issued it
    invoice: Invoice

    @property
    def gross(self) -> int:
        return self.invoice.payable_cents or self.invoice.gross_cents or 0

    def party_name(self) -> str:
        return self.invoice.seller.name if self.direction == "in" else self.invoice.buyer.name


@dataclass
class Match:
    tx_id: int
    doc_ids: list[int]
    score: float
    skonto: bool = False
    ambiguous: bool = False
    reasons: list[str] = field(default_factory=list)


def _direction_fits(tx: Tx, doc: Doc) -> bool:
    credit_note = doc.invoice.is_credit_note
    money_in = tx.amount_cents > 0
    if doc.direction == "in":
        return money_in == credit_note  # pay a supplier's invoice; receive a supplier's refund
    return money_in != credit_note  # receive a customer's payment; refund a customer


def _amount_score(paid: int, gross: int, tax: TaxConfig) -> tuple[float, bool]:
    if gross <= 0:
        return 0.0, False
    if paid == gross:
        return 1.0, False
    for p in tax.skonto_percent:
        if abs(paid - round(gross * (100 - p) / 100)) <= 1:
            return 0.85, True
    return 0.0, False


def pair_score(tx: Tx, docs: list[Doc], cfg: CloseConfig, tax: TaxConfig) -> tuple[float, bool, list[str]]:
    paid = abs(tx.amount_cents)
    gross = sum(d.gross for d in docs)
    amount, skonto = _amount_score(paid, gross, tax)
    if amount == 0.0:
        return 0.0, False, []
    reasons = ["Betrag stimmt" if not skonto else "Betrag abzüglich Skonto"]
    refs = {r.replace(" ", "") for r in find_invoice_numbers(tx.remittance)}
    ref_hits = 0
    for d in docs:
        no = (d.invoice.invoice_no or "").upper().replace(" ", "")
        if no and (no in refs or (len(no) >= 4 and no in tx.remittance.upper().replace(" ", ""))):
            ref_hits += 1
    ref = ref_hits / len(docs)
    if ref:
        reasons.append("Rechnungsnummer im Verwendungszweck")
    tx_iban = normalize_iban(tx.iban)
    iban = 1.0 if tx_iban and all(d.direction == "in" and d.invoice.seller_iban == tx_iban for d in docs) else 0.0
    if iban:
        reasons.append("IBAN laut Rechnung")
    name = min(name_similarity(tx.name, d.party_name()) for d in docs)
    if name >= 0.8:
        reasons.append("Name stimmt")
    first = min((d.invoice.issue_date or tx.on) for d in docs)
    lag = (tx.on - first).days
    when = 1.0 if 0 <= lag <= 45 else (0.6 if -cfg.window_days_after <= lag <= cfg.window_days_before else 0.0)
    score = 0.45 * amount + 0.25 * max(ref, iban) + 0.20 * name + 0.10 * when
    return score, skonto, reasons


def match(txs: list[Tx], docs: list[Doc], cfg: CloseConfig, tax: TaxConfig) -> dict[int, Match]:
    """Best assignment of payments to invoices. Returns tx id -> Match for matched payments."""
    cands: list[Match] = []
    by_tx: dict[int, list[Match]] = {}
    for tx in txs:
        lo, hi = tx.on - timedelta(days=cfg.window_days_before), tx.on + timedelta(days=cfg.window_days_after)
        pool = [
            d
            for d in docs
            if _direction_fits(tx, d) and (d.invoice.issue_date is None or lo <= d.invoice.issue_date <= hi)
        ]
        found: list[Match] = []
        for d in pool:
            s, sk, rs = pair_score(tx, [d], cfg, tax)
            if s >= cfg.min_match_score:
                found.append(Match(tx.id, [d.id], s, sk, reasons=rs))
        if not found and cfg.max_combination > 1:
            # Several invoices of one supplier paid at once.
            groups: dict[str, list[Doc]] = {}
            for d in pool:
                key = d.invoice.seller_iban or d.party_name().lower()
                groups.setdefault(key, []).append(d)
            for group in groups.values():
                if len(group) < 2 or sum(d.gross for d in group) < abs(tx.amount_cents):
                    continue
                for k in range(2, min(cfg.max_combination, len(group)) + 1):
                    for combo in combinations(group, k):
                        if sum(d.gross for d in combo) != abs(tx.amount_cents):
                            continue
                        s, sk, rs = pair_score(tx, list(combo), cfg, tax)
                        if s >= cfg.min_match_score:
                            found.append(
                                Match(
                                    tx.id,
                                    [d.id for d in combo],
                                    s,
                                    sk,
                                    reasons=[*rs, f"{k} Rechnungen zusammen bezahlt"],
                                )
                            )
        by_tx[tx.id] = sorted(found, key=lambda m: -m.score)
        cands += found

    taken: set[int] = set()
    out: dict[int, Match] = {}
    for m in sorted(cands, key=lambda m: -m.score):
        if m.tx_id in out or taken & set(m.doc_ids):
            continue
        rivals = [
            r
            for r in by_tx[m.tx_id]
            if r is not m and not (taken & set(r.doc_ids)) and set(r.doc_ids) != set(m.doc_ids)
        ]
        if rivals and rivals[0].score >= m.score - 0.05:
            m.ambiguous = True
        out[m.tx_id] = m
        taken |= set(m.doc_ids)
    return out
