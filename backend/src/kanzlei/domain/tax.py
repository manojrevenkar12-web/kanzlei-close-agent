"""Tax treatment of one payment or invoice. Rules decide; nothing here reads a model's opinion.

Input: the booking family (what it is for), the amount, the invoice if there is one, the client's
VAT regime and what the client's history says. Output: gross portions per tax code and role, plus
the flags that hold the item for a person.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from kanzlei.config import Family, TaxConfig, families
from kanzlei.domain.compliance import missing_fields
from kanzlei.domain.models import INPUT_VAT, ClientProfile, Reason
from kanzlei.domain.money import share, split_gross
from kanzlei.formats.invoice import Invoice


@dataclass
class Portion:
    tax: str
    gross_cents: int
    role: str | None = None
    note: str = ""


@dataclass
class TaxDecision:
    portions: list[Portion]
    flags: list[str] = field(default_factory=list)
    reasons: list[Reason] = field(default_factory=list)
    skonto_cents: int = 0
    source: str = "default"  # document | memory | default | answer


def _code_for(
    category: str, rate: int, *, revenue: bool, seller_country: str, buyer_country: str, eu: frozenset[str], goods: bool
) -> str | None:
    if category == "S":
        if rate == 19:
            return "U19" if revenue else "V19"
        if rate == 7:
            return "U7" if revenue else "V7"
        return None
    if category == "AE":
        if revenue:
            return "EU_SVC" if buyer_country in eu else "RC_OUT"
        if seller_country == "DE" or not seller_country:
            return "RC_BAU19"
        if seller_country in eu:
            return "IGE19" if goods else "RC_EU19"
        return "RC_DRITT19"
    if category == "K":
        return "IGL" if revenue else "IGE19"
    if category == "E":
        return "FREI" if revenue else "NONE"
    if category == "O" and not revenue and seller_country and seller_country != "DE" and not goods:
        # A foreign seller outside the scope of its own VAT: the German recipient owes the tax
        # on the service (§ 3a Abs. 2, § 13b Abs. 1 / Abs. 2 Nr. 1 UStG).
        return "RC_EU19" if seller_country in eu else "RC_DRITT19"
    if category in ("Z", "O", "G"):
        return "NONE" if not revenue else None
    return None


def _allocate(parts: list[tuple[str, int]], total: int) -> list[tuple[str, int]]:
    """Scales portions to `total`, keeping the sum exact (last portion takes the rounding)."""
    whole = sum(p for _, p in parts)
    if whole == total or whole == 0:
        return parts
    out: list[tuple[str, int]] = []
    run = 0
    for i, (code, p) in enumerate(parts):
        v = total - run if i == len(parts) - 1 else round(p * total / whole)
        out.append((code, v))
        run += v
    return out


def _from_invoice(
    inv: Invoice, fam: Family, client: ClientProfile, cfg: TaxConfig
) -> tuple[list[tuple[str, int]], list[str]]:
    revenue = fam.side == "revenue"
    seller_c = (inv.seller.country or "DE").upper()
    buyer_c = (inv.buyer.country or "DE").upper()
    goods = fam.code == "goods"
    parts: list[tuple[str, int]] = []
    problems: list[str] = []
    taxes = inv.taxes
    if not taxes and inv.gross_cents is not None:
        foreign = seller_c != "DE"
        if foreign and not revenue:
            code = ("IGE19" if goods else "RC_EU19") if seller_c in cfg.eu_countries else "RC_DRITT19"
            return [(code, inv.gross_cents)], problems
        problems.append("unsupported_tax")
        return [(fam.tax, inv.gross_cents)], problems
    if revenue and any(t.category == "AE" for t in taxes) and not (inv.buyer.country or inv.buyer.vat_id):
        problems.append("unsupported_tax")  # § 14a: a reverse-charge invoice names the customer's VAT id
    for t in taxes:
        found = _code_for(
            t.category,
            t.rate,
            revenue=revenue,
            seller_country=seller_c,
            buyer_country=buyer_c,
            eu=cfg.eu_countries,
            goods=goods,
        )
        if found is None:
            problems.append("unsupported_tax")
        code_t = found if found is not None else fam.tax
        gross = t.base_cents + (t.tax_cents if t.category == "S" else 0)
        parts.append((code_t, gross))
    return parts, problems


def decide(
    *,
    family: str,
    amount_cents: int,
    inv: Invoice | None,
    client: ClientProfile,
    cfg: TaxConfig,
    memory_tax: str | None = None,
    recurring: bool = False,
    has_receipt_answer: str | None = None,
    meals_details: bool = False,
    opos_invoice: bool = False,
) -> TaxDecision:
    """`amount_cents` is what was paid (or the invoice total for an invoice booked on receipt)."""
    fam = families()[family]
    d = TaxDecision(portions=[])

    if fam.side == "balance":
        # Wages, taxes, social security, private and own-account transfers are not VAT events,
        # whatever a receipt says (a private purchase's VAT is never input VAT).
        d.portions = [Portion("NONE", amount_cents)]
        d.reasons.append(Reason("kein_ust", f"{fam.label}: kein umsatzsteuerlicher Vorgang"))
        d.source = "rule"
        return d
    # Kleinunternehmer and tax-free practices: the regime decides the tax code, but whether an
    # invoice exists still matters (the expense must be proven, the income explained).
    regime_code: str | None = None
    if client.vat_regime == "klein":
        regime_code = "NONE"
    elif client.vat_regime == "befreit":
        regime_code = "FREI" if fam.side == "revenue" else "NONE"
    if inv is not None and inv.gross_cents is not None:
        parts, problems = _from_invoice(inv, fam, client, cfg)
        d.flags += problems
        whole = sum(p for _, p in parts)
        if whole != amount_cents and not opos_invoice:
            diff = whole - amount_cents
            pct = {p: round(whole * p / 100) for p in cfg.skonto_percent}
            if diff > 0 and any(abs(diff - v) <= 1 for v in pct.values()):
                d.skonto_cents = diff
                d.reasons.append(Reason("skonto", f"Skonto abgezogen ({diff / 100:.2f} €)".replace(".", ",")))
            else:
                d.flags.append("partial_payment")
            parts = _allocate(parts, amount_cents)
        d.portions = [Portion(code, gross) for code, gross in parts]
        d.source = "document"
        codes = sorted({p.tax for p in d.portions})
        d.reasons.append(Reason("tax_from_invoice", "Steuer laut Rechnung: " + ", ".join(codes)))
        if any(p.tax in INPUT_VAT for p in d.portions):
            missing = missing_fields(inv, cfg)
            if missing and has_receipt_answer != "not_available":
                d.flags.append("invoice_incomplete")
                d.reasons.append(Reason("pflichtangaben", "Es fehlen: " + ", ".join(missing)))
            elif missing:
                d.portions = [Portion("NONE", amount_cents)]
                d.reasons.append(Reason("no_deduction", "Keine korrigierte Rechnung: ohne Vorsteuer gebucht"))
    else:
        code = memory_tax or fam.tax
        d.source = "memory" if memory_tax else "default"
        d.portions = [Portion(code, amount_cents)]
        needs_doc = fam.receipt and (regime_code is not None or code not in ("NONE", "FREI"))
        if needs_doc and not (fam.recurring_ok and recurring):
            if has_receipt_answer == "no_receipt":
                d.portions = [Portion("NONE", amount_cents)]
                d.reasons.append(Reason("eigenbeleg", "Kein Beleg vorhanden: Eigenbeleg, ohne Vorsteuer"))
            elif fam.side == "revenue":
                d.flags.append("unknown_credit")
            else:
                d.flags.append("missing_receipt")
        elif needs_doc:
            d.reasons.append(Reason("dauerrechnung", "Laufender Vertrag: Vertrag gilt als Rechnung"))

    if regime_code is not None:
        d.portions = [Portion(regime_code, p.gross_cents, p.role, p.note) for p in d.portions]
        d.flags = [f for f in d.flags if f not in ("invoice_incomplete", "unsupported_tax")]
        d.reasons = [r for r in d.reasons if r.code not in ("tax_from_invoice", "pflichtangaben")]
        if client.vat_regime == "klein":
            d.reasons.append(
                Reason("kleinunternehmer", "Kleinunternehmer (§ 19 UStG): keine Vorsteuer, keine Umsatzsteuer")
            )
        else:
            d.reasons.append(
                Reason("steuerfrei", "Steuerfreie Umsätze ohne Vorsteuerabzug (§ 4 Nr. 14, § 15 Abs. 2 UStG)")
            )
        d.source = "rule" if d.source in ("default", "memory") else d.source

    # Family rules that split an amount between accounts.
    if family == "meals":
        out: list[Portion] = []
        for p in d.portions:
            ded = share(p.gross_cents, cfg.meals_deductible_share)
            out.append(Portion(p.tax, ded, None, "abzugsfähig"))
            out.append(Portion(p.tax, p.gross_cents - ded, "nondeductible", "nicht abzugsfähig"))
        d.portions = out
        d.reasons.append(
            Reason("bewirtung", f"Bewirtung: {int(cfg.meals_deductible_share * 100)} % abzugsfähig, Vorsteuer voll")
        )
        if not meals_details and not _has_meals_details(inv):
            d.flags.append("meals_details")
    elif family == "equipment":
        d.portions, asset = _equipment_roles(d.portions, inv, cfg)
        if asset:
            d.flags.append("asset_review")
            d.reasons.append(Reason("anlagegut", "Wirtschaftsgut über der GWG-Grenze: Anlagenverzeichnis"))
    d.portions = [p for p in d.portions if p.gross_cents != 0]
    return d


def _has_meals_details(inv: Invoice | None) -> bool:
    if inv is None:
        return False
    blob = " ".join(inv.notes).lower()
    return "anlass" in blob and "teilnehmer" in blob


def _net(p: Portion, cfg: TaxConfig) -> int:
    rate = cfg.rates.get(p.tax)
    if p.tax in INPUT_VAT and rate:
        return split_gross(p.gross_cents, rate)[0]
    return p.gross_cents


def _equipment_roles(portions: list[Portion], inv: Invoice | None, cfg: TaxConfig) -> tuple[list[Portion], bool]:
    """Small items are expensed, items up to the GWG limit written off at once, dearer ones
    capitalised. The limit applies per item (unit price), so invoice lines decide when present."""

    def role_for(unit_net: int) -> str:
        if unit_net <= cfg.small_net_cents:
            return "small"
        if unit_net <= cfg.gwg_net_cents:
            return "gwg"
        return "asset"

    if inv is not None and inv.lines and all(ln.net_cents > 0 for ln in inv.lines) and len(portions) == 1:
        p = portions[0]
        total_net = sum(ln.net_cents for ln in inv.lines)
        groups: dict[str, int] = {}
        vat = p.tax in INPUT_VAT
        for ln in inv.lines:
            # Without input VAT deduction the VAT belongs to the cost, so the limit applies to gross.
            basis = ln.net_cents if vat else ln.net_cents + round(ln.net_cents * (ln.rate or 0) / 100)
            unit = round(basis / max(ln.quantity, 1))
            r = role_for(unit)
            groups[r] = groups.get(r, 0) + ln.net_cents
        parts = (
            _allocate([(r, net) for r, net in groups.items()], p.gross_cents)
            if total_net
            else [("small", p.gross_cents)]
        )
        out = [Portion(p.tax, g, r) for r, g in parts]
    else:
        out = [Portion(p.tax, p.gross_cents, role_for(_net(p, cfg))) for p in portions]
    return out, any(p.role == "asset" for p in out)
