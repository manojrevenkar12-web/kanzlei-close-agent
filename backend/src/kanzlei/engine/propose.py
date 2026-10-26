"""Turns one payment or one invoice into a booking proposal, with the reasons and the route.

Order of evidence for *what* it is: the client's answer, own-account transfer, the client's own
invoice, the client's history (memory), the text classifier, the model reader (if allowed).
*How it is taxed* is never learned: domain/tax.py decides from the invoice and the rules.
*Whether a person must look*: rule flags first, then the decision model.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from kanzlei.config import CloseConfig, TaxConfig, families
from kanzlei.domain.chart import Chart
from kanzlei.domain.models import CLIENT_FLAGS, ClientProfile, Line, Proposal, Reason
from kanzlei.domain.money import fmt_de
from kanzlei.domain.tax import Portion, TaxDecision, decide
from kanzlei.domain.text import name_similarity, normalize_iban, normalize_name
from kanzlei.engine.classifier import Classifier, featurize, top2
from kanzlei.engine.decision import DecisionModel
from kanzlei.engine.matching import Doc, Match, Tx
from kanzlei.engine.memory import ClientMemory, MemoryHit

STRUCTURED = {"xrechnung-ubl", "xrechnung-cii", "zugferd"}
CLIENT_ORDER = ("private_or_business", "missing_receipt", "invoice_incomplete", "meals_details", "unknown_credit")


@dataclass
class Counterparty:
    kind: str  # kreditor | debitor
    account: int
    name: str
    iban: str | None = None
    vat_id: str | None = None
    country: str | None = None
    new: bool = False


@dataclass
class Context:
    client: ClientProfile
    chart: Chart
    memory: ClientMemory
    classifier: Classifier | None
    decision: DecisionModel
    tax: TaxConfig
    close: CloseConfig
    period_start: date
    period_end: date
    counterparties: list[Counterparty] = field(default_factory=list)
    suggest_family: Callable[[str], str | None] | None = None  # the model reader, if allowed

    def find_counterparty(self, kind: str, *, iban: str | None, vat_id: str | None, name: str) -> Counterparty | None:
        ib = normalize_iban(iban)
        for c in self.counterparties:
            if c.kind == kind and (
                (ib and c.iban == ib) or (vat_id and c.vat_id and c.vat_id.upper() == vat_id.upper())
            ):
                return c
        best, score = None, 0.0
        for c in self.counterparties:
            if c.kind != kind:
                continue
            s = name_similarity(name, c.name)
            if s > score:
                best, score = c, s
        return best if best and score >= 0.9 else None

    def new_counterparty(
        self, kind: str, *, name: str, iban: str | None, vat_id: str | None, country: str | None
    ) -> Counterparty:
        lo, hi = self.chart.creditors if kind == "kreditor" else self.chart.debtors
        start = 70001 if kind == "kreditor" else 10001
        used = {c.account for c in self.counterparties}
        acct = max([a for a in used if lo <= a <= hi] + [start - 1]) + 1
        cp = Counterparty(kind, acct, name, normalize_iban(iban), vat_id, country, new=True)
        self.counterparties.append(cp)
        return cp


def clamp(d: date | None, lo: date, hi: date) -> date:
    if d is None:
        return lo
    return min(max(d, lo), hi)


def _probs(ctx: Context, name: str, remittance: str, doc_text: str, money_in: bool, amount: int) -> dict[str, float]:
    if ctx.classifier is None:
        return {}
    return ctx.classifier.probabilities(featurize(name, remittance, doc_text, money_in, amount))


def _choose_family(
    ctx: Context,
    *,
    name: str,
    iban: str | None,
    money_in: bool,
    hit: MemoryHit | None,
    probs: dict[str, float],
    text_for_model: str,
    answers: dict[str, Any],
    issued_by_client: bool,
) -> tuple[str | None, str, list[Reason]]:
    fams = families()
    if answers.get("family") in fams:
        f = answers["family"]
        return f, "answer", [Reason("answer", f"Angabe des Mandanten: {fams[f].label}")]
    ib = normalize_iban(iban)
    if ib and ib in ctx.client.own_ibans:
        return "transfer", "rule", [Reason("own_account", "Überweisung zwischen eigenen Konten")]
    if issued_by_client:
        return "revenue", "document", [Reason("own_invoice", "Ausgangsrechnung des Mandanten")]
    best, p, _ = top2(probs)
    if (
        hit
        and hit.dominant
        and best
        and best != hit.family
        and p >= ctx.close.memory_overruled_by_classifier_p
        and probs.get(hit.family, 0.0) < ctx.close.memory_overruled_if_memory_family_p_below
    ):
        return (
            best,
            "conflict",
            [
                Reason(
                    "memory_conflict",
                    f"Bisher als {fams[hit.family].label} gebucht, dieser Umsatz lautet aber eindeutig auf {fams[best].label}",
                )
            ],
        )
    if hit and hit.dominant and hit.family in fams:
        acct = ctx.chart.account_for(hit.family, hit.tax)
        where = f" (Konto {ctx.chart.fmt(acct)})" if acct else ""
        return (
            hit.family,
            "memory",
            [
                Reason(
                    "memory",
                    f"Bisher {hit.uses}× gebucht, davon {round(hit.share * 100)} % als {fams[hit.family].label}{where}",
                )
            ],
        )
    best, p, _ = top2(probs)
    if ctx.suggest_family and (best is None or p < 0.55):
        suggested = ctx.suggest_family(text_for_model)
        if suggested in fams:
            return (
                suggested,
                "llm",
                [Reason("llm", f"Sprachmodell schlägt vor: {fams[suggested].label} (geprüft: Familie existiert)")],
            )
    if best:
        why = [Reason("classifier", f"Text deutet auf {fams[best].label} ({round(p * 100)} %)")]
        if hit and not hit.dominant:
            why.append(Reason("memory_mixed", f"Bisher uneinheitlich gebucht ({hit.uses}×)"))
        return best, "classifier", why
    return None, "none", [Reason("unknown", "Keine Grundlage für einen Vorschlag")]


def _features(
    *,
    hit: MemoryHit | None,
    family: str | None,
    probs: dict[str, float],
    docs: list[Doc],
    match: Match | None,
    td: TaxDecision | None,
    source: str,
    money_in: bool,
    amount: int,
) -> list[float]:
    fams = families()
    best, _p, margin = top2(probs)
    risk = fams[family].risk if family in fams else 2
    return [
        hit.share if hit else 0.0,
        math.log1p(hit.uses) if hit else 0.0,
        (1.0 if hit.family == family else 0.0) if hit else 0.5,
        probs.get(family or "", 0.0),
        margin,
        1.0 if best == family else 0.0,
        1.0 if docs else 0.0,
        1.0 if any(d.invoice.source in STRUCTURED for d in docs) else 0.0,
        match.score if match else 0.0,
        1.0 if td and td.source == "document" else 0.0,
        1.0 if hit and hit.recurring else 0.0,
        min(hit.amount_deviation(amount), 3.0) if hit else 1.0,
        float(risk),
        1.0 if hit is None else 0.0,
        1.0 if source == "llm" else 0.0,
        1.0 if money_in else 0.0,
    ]


def _route(
    ctx: Context,
    flags: list[str],
    conf: float,
    *,
    new_counterparty: bool,
    answered: bool,
    classifier_p: float = 1.0,
    source: str = "",
) -> str:
    if any(f in CLIENT_FLAGS for f in flags):
        return "client"
    if flags:
        return "review"
    if answered:
        return "auto"
    if new_counterparty and (
        ctx.close.never_auto_new_counterparty
        or (source in ("classifier", "llm") and classifier_p < ctx.close.new_counterparty_min_classifier_p)
    ):
        return "review"
    return "auto" if conf >= ctx.decision.threshold else "review"


def _portion_lines(
    ctx: Context,
    portions: list[Portion],
    family: str,
    *,
    other: int,
    other_is_debit: bool,
    on: date,
    text: str,
    doc_ref: str,
    flags: list[str],
) -> list[Line]:
    lines: list[Line] = []
    for p in portions:
        acct = ctx.chart.account_for(family, p.tax, p.role)
        if acct is None:
            if "no_account" not in flags:
                flags.append("no_account")
            acct = ctx.chart.system["suspense"]
        debit, credit = (other, acct) if other_is_debit else (acct, other)
        lines.append(Line(on, p.gross_cents, debit, credit, p.tax, text[:60], family, p.role, doc_ref))
    return lines


def _sort_flags(flags: list[str]) -> list[str]:
    order = {f: i for i, f in enumerate(CLIENT_ORDER)}
    return sorted(dict.fromkeys(flags), key=lambda f: (order.get(f, 99), f))


def propose_payment(
    ctx: Context,
    tx: Tx,
    docs: list[Doc],
    match: Match | None,
    *,
    answers: dict[str, Any] | None = None,
    cleared: dict[int, int] | None = None,
    force_family: str | None = None,
    force_tax: str | None = None,
) -> Proposal:
    """`cleared`: doc id -> personal account, for invoices already booked on receipt (OPOS)."""
    answers = dict(answers or {})
    if force_family:
        answers["family"] = force_family
    money_in = tx.amount_cents > 0
    amount = abs(tx.amount_cents)
    hit = ctx.memory.lookup(tx.iban, tx.name, money_in=money_in)
    doc_text = " ".join(d.invoice.text for d in docs)
    probs = _probs(ctx, tx.name, tx.remittance, doc_text, money_in, amount)
    issued = bool(docs) and all(d.direction == "out" for d in docs) and not any(d.invoice.is_credit_note for d in docs)
    family, source, reasons = _choose_family(
        ctx,
        name=tx.name,
        iban=tx.iban,
        money_in=money_in,
        hit=hit,
        probs=probs,
        text_for_model=f"{tx.name} | {tx.remittance} | {doc_text}"[:600],
        answers=answers,
        issued_by_client=issued,
    )
    flags: list[str] = []
    if match:
        reasons.append(Reason("match", "Beleg zugeordnet: " + ", ".join(match.reasons)))
        if match.ambiguous:
            flags.append("ambiguous_match")
    bank = ctx.chart.system["bank"]
    doc_ref = next((d.invoice.invoice_no for d in docs if d.invoice.invoice_no), "") or ""
    text = tx.name or tx.remittance
    td: TaxDecision | None = None
    lines: list[Line] = []
    cp_info: dict[str, Any] = {"name": tx.name, "iban": normalize_iban(tx.iban)}

    if cleared and docs and all(d.id in cleared for d in docs) and family not in ("transfer",):
        # OPOS: the invoice is already on a personal account; the payment settles it.
        targets = []
        for d in docs:
            main = max(d.invoice.taxes, key=lambda t: t.base_cents) if d.invoice.taxes else None
            rate = main.rate if main and main.category == "S" else 19
            targets.append(
                OpenItem(
                    "kreditor" if d.direction == "in" else "debitor",
                    cleared[d.id],
                    d.invoice.invoice_no or "",
                    d.gross,
                    rate,
                    "",
                    None,
                )
            )
        lines, flags2, why = clearing_lines(ctx, tx, targets)
        flags += flags2
        reasons = [Reason("clearing", "Ausgleich offener Posten"), *why, *reasons]
        conf = match.score if match else 0.0
        route = "client" if any(f in CLIENT_FLAGS for f in flags) else ("review" if flags or conf < 0.8 else "auto")
        return Proposal("clearing", "NONE", lines, conf, route, reasons, _sort_flags(flags), "rule", [], cp_info)

    if family is None:
        flags.append("low_confidence")
        acct = ctx.chart.system["suspense"]
        lines = [
            Line(
                tx.on,
                amount,
                bank if money_in else acct,
                acct if money_in else bank,
                "NONE",
                text[:60],
                None,
                None,
                doc_ref,
            )
        ]
        return Proposal(None, None, lines, 0.0, "review", reasons, _sort_flags(flags), source, [], cp_info)

    if (
        family == "private_withdrawal"
        and source == "classifier"
        and not money_in
        and probs.get("private_withdrawal", 0.0) < ctx.close.ask_private_min_p
    ):
        business = [(f, v) for f, v in probs.items() if f in families() and families()[f].side == "expense"]
        if business:
            family = max(business, key=lambda fv: fv[1])[0]
            reasons.append(
                Reason("weak_private", "Privat nur schwach angedeutet: betrieblicher Vorschlag, bitte prüfen")
            )
            flags.append("low_confidence")
    fam = families()[family]
    portions: list[Portion] = []
    if docs:
        total = sum(d.gross for d in docs) or amount
        run = 0
        for i, d in enumerate(docs):
            part = amount - run if i == len(docs) - 1 else round(d.gross * amount / total)
            run += part
            dd = decide(
                family=family,
                amount_cents=part,
                inv=d.invoice,
                client=ctx.client,
                cfg=ctx.tax,
                memory_tax=hit.tax if hit and hit.dominant else None,
                recurring=bool(hit and hit.recurring),
                has_receipt_answer=answers.get("receipt"),
                meals_details=bool(answers.get("meals_details")),
            )
            td = dd if td is None else td
            if td is not dd:
                td.flags += dd.flags
                td.reasons += dd.reasons
            portions += dd.portions
        assert td is not None
    else:
        td = decide(
            family=family,
            amount_cents=amount,
            inv=None,
            client=ctx.client,
            cfg=ctx.tax,
            memory_tax=hit.tax if hit and hit.dominant and hit.family == family else None,
            recurring=bool(hit and hit.recurring and hit.family == family),
            has_receipt_answer=answers.get("receipt"),
            meals_details=bool(answers.get("meals_details")),
        )
        portions = td.portions
    if force_tax:
        portions = [Portion(force_tax, p.gross_cents, p.role, p.note) for p in portions]
    flags += td.flags
    reasons += td.reasons
    if source == "conflict":
        flags.append("memory_conflict")
    if family == "private_withdrawal" and source not in ("memory", "answer") and not money_in:
        flags.append("private_or_business")
    if fam.side == "revenue" and not money_in and source == "classifier":
        flags.append("low_confidence")
    lines = _portion_lines(
        ctx, portions, family, other=bank, other_is_debit=money_in, on=tx.on, text=text, doc_ref=doc_ref, flags=flags
    )
    x = _features(
        hit=hit,
        family=family,
        probs=probs,
        docs=docs,
        match=match,
        td=td,
        source=source,
        money_in=money_in,
        amount=amount,
    )
    conf = ctx.decision.probability(x)
    flags = _sort_flags(flags)
    known = hit is not None and hit.dominant
    route = _route(
        ctx,
        flags,
        conf,
        new_counterparty=not known,
        answered=source == "answer" or bool(answers),
        classifier_p=probs.get(family, 0.0),
        source=source,
    )
    main_tax = max(portions, key=lambda p: p.gross_cents).tax if portions else None
    return Proposal(family, main_tax, lines, conf, route, reasons, flags, source, x, cp_info)


@dataclass
class OpenItem:
    """An unsettled invoice on a personal account (from history or earlier months)."""

    kind: str  # kreditor | debitor
    account: int
    doc_ref: str
    balance_cents: int  # outstanding, > 0
    rate: int  # main VAT rate of the invoice (for a cash discount)
    name: str
    iban: str | None


def clearing_lines(ctx: Context, tx: Tx, targets: list[OpenItem]) -> tuple[list[Line], list[str], list[Reason]]:
    """Payment against open items; a shortfall within the cash-discount rates is booked as Skonto."""
    money_in = tx.amount_cents > 0
    amount = abs(tx.amount_cents)
    bank = ctx.chart.system["bank"]
    text = tx.name or tx.remittance
    total = sum(t.balance_cents for t in targets) or amount
    lines: list[Line] = []
    flags: list[str] = []
    reasons: list[Reason] = []
    run = 0
    for i, t in enumerate(targets):
        paid = amount - run if i == len(targets) - 1 else round(t.balance_cents * amount / total)
        run += paid
        if money_in:
            lines.append(Line(tx.on, paid, bank, t.account, "NONE", text[:60], "clearing", None, t.doc_ref))
        else:
            lines.append(Line(tx.on, paid, t.account, bank, "NONE", text[:60], "clearing", None, t.doc_ref))
        disc = t.balance_cents - paid
        if disc > 0:
            customer = t.kind == "debitor"
            code = ("U" if customer else "V") + str(t.rate)
            fam = "skonto_granted" if customer else "skonto_received"
            acct = ctx.chart.account_for(fam, code)
            if acct is None:
                flags.append("no_account")
                acct = ctx.chart.system["suspense"]
            if customer:
                lines.append(Line(tx.on, disc, acct, t.account, code, "Skonto " + text[:50], fam, None, t.doc_ref))
            else:
                lines.append(Line(tx.on, disc, t.account, acct, code, "Skonto " + text[:50], fam, None, t.doc_ref))
            reasons.append(Reason("skonto", f"Skonto {fmt_de(disc)}"))
        elif disc < 0:
            flags.append("partial_payment")
    return lines, flags, reasons


def match_open_item(ctx: Context, tx: Tx, items: list[OpenItem]) -> tuple[OpenItem, float] | None:
    """The open item a payment settles: amount (or amount less Skonto) and reference or payee."""
    kind = "debitor" if tx.amount_cents > 0 else "kreditor"
    amount = abs(tx.amount_cents)
    refs = tx.remittance.upper().replace(" ", "")
    ib = normalize_iban(tx.iban)
    found: list[tuple[float, OpenItem]] = []
    for it in items:
        if it.kind != kind or it.balance_cents <= 0:
            continue
        ok = amount == it.balance_cents or any(
            abs(amount - round(it.balance_cents * (100 - p) / 100)) <= 1 for p in ctx.tax.skonto_percent
        )
        if not ok:
            continue
        ref = bool(it.doc_ref) and it.doc_ref.upper().replace(" ", "") in refs
        who = bool(ib and it.iban == ib) or name_similarity(tx.name, it.name) >= 0.8
        if ref or who:
            found.append(((0.6 if ref else 0.0) + (0.35 if who else 0.0), it))
    if not found:
        return None
    found.sort(key=lambda x: -x[0])
    if len(found) > 1 and found[1][0] >= found[0][0]:
        return None
    return found[0][1], found[0][0]


def propose_open_item(ctx: Context, tx: Tx, item: OpenItem, score: float) -> Proposal:
    lines, flags, why = clearing_lines(ctx, tx, [item])
    reasons = [
        Reason(
            "clearing",
            f"Ausgleich offener Posten {item.doc_ref or ''} ({'Kreditor' if item.kind == 'kreditor' else 'Debitor'} {item.account})",
        ),
        *why,
    ]
    route = "review" if flags or score < 0.9 else "auto"
    return Proposal(
        "clearing",
        "NONE",
        lines,
        score,
        route,
        reasons,
        _sort_flags(flags),
        "rule",
        [],
        {"name": tx.name, "iban": normalize_iban(tx.iban), "account": item.account},
    )


def propose_invoice(
    ctx: Context,
    doc: Doc,
    *,
    answers: dict[str, Any] | None = None,
    force_family: str | None = None,
    force_tax: str | None = None,
) -> Proposal:
    """OPOS: an invoice booked on receipt against the supplier's (or customer's) personal account."""
    answers = dict(answers or {})
    if force_family:
        answers["family"] = force_family
    inv = doc.invoice
    incoming = doc.direction == "in"
    kind = "kreditor" if incoming else "debitor"
    party = inv.seller if incoming else inv.buyer
    cp = ctx.find_counterparty(kind, iban=inv.seller_iban if incoming else None, vat_id=party.vat_id, name=party.name)
    flags: list[str] = []
    reasons: list[Reason] = []
    if cp is None:
        cp = ctx.new_counterparty(
            kind,
            name=party.name or "Unbekannt",
            iban=inv.seller_iban if incoming else None,
            vat_id=party.vat_id,
            country=party.country,
        )
        flags.append("new_creditor")
        reasons.append(
            Reason("new_counterparty", f"Neuer {'Kreditor' if incoming else 'Debitor'} {cp.account}: {cp.name}")
        )
    else:
        reasons.append(Reason("counterparty", f"{'Kreditor' if incoming else 'Debitor'} {cp.account}: {cp.name}"))
    amount = inv.gross_cents or 0
    hit = ctx.memory.lookup(cp.iban, cp.name, money_in=not incoming)
    probs = _probs(ctx, party.name, "", inv.text, not incoming, amount)
    family, source, why = _choose_family(
        ctx,
        name=party.name,
        iban=cp.iban,
        money_in=not incoming,
        hit=hit,
        probs=probs,
        text_for_model=f"{party.name} | {inv.text}"[:600],
        answers=answers,
        issued_by_client=not incoming,
    )
    reasons += why
    cp_info = {
        "name": cp.name,
        "iban": cp.iban,
        "account": cp.account,
        "kind": kind,
        "new": cp.new,
        "vat_id": cp.vat_id,
        "country": cp.country,
    }
    on = clamp(inv.issue_date, ctx.period_start, ctx.period_end)
    doc_ref = inv.invoice_no or ""
    if family is None or amount <= 0:
        flags.append("low_confidence" if amount > 0 else "unreadable_document")
        sus = ctx.chart.system["suspense"]
        lines = (
            [Line(on, max(amount, 1), sus, cp.account, "NONE", party.name[:60], None, None, doc_ref)]
            if incoming
            else [Line(on, max(amount, 1), cp.account, sus, "NONE", party.name[:60], None, None, doc_ref)]
        )
        return Proposal(None, None, lines, 0.0, "review", reasons, _sort_flags(flags), source, [], cp_info)
    td = decide(
        family=family,
        amount_cents=amount,
        inv=inv,
        client=ctx.client,
        cfg=ctx.tax,
        has_receipt_answer=answers.get("receipt"),
        meals_details=bool(answers.get("meals_details")),
        opos_invoice=True,
    )
    portions = td.portions
    if force_tax:
        portions = [Portion(force_tax, p.gross_cents, p.role, p.note) for p in portions]
    flags += td.flags
    reasons += td.reasons
    # Supplier invoice: expense debit / Kreditor credit. Customer invoice: Debitor debit / revenue credit.
    # A credit note turns the direction round.
    other_is_debit = (not incoming) != inv.is_credit_note
    lines = _portion_lines(
        ctx,
        portions,
        family,
        other=cp.account,
        other_is_debit=other_is_debit,
        on=on,
        text=party.name,
        doc_ref=doc_ref,
        flags=flags,
    )
    x = _features(
        hit=hit,
        family=family,
        probs=probs,
        docs=[doc],
        match=None,
        td=td,
        source=source,
        money_in=not incoming,
        amount=amount,
    )
    conf = ctx.decision.probability(x)
    flags = _sort_flags(flags)
    known = not cp.new and hit is not None and hit.dominant
    route = _route(
        ctx,
        flags,
        conf,
        new_counterparty=not known,
        answered=source == "answer" or bool(answers),
        classifier_p=probs.get(family, 0.0),
        source=source,
    )
    main_tax = max(portions, key=lambda p: p.gross_cents).tax if portions else None
    return Proposal(family, main_tax, lines, conf, route, reasons, flags, source, x, cp_info)


def counterparty_key(name: str) -> str:
    return normalize_name(name)
