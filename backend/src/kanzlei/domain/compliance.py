"""Is this invoice good enough to deduct input VAT? § 14 Abs. 4 UStG, § 33 UStDV, § 14a UStG."""

from __future__ import annotations

from kanzlei.config import TaxConfig
from kanzlei.formats.invoice import Invoice

LABELS = {
    "seller_name": "Name des leistenden Unternehmers",
    "seller_address": "Anschrift des leistenden Unternehmers",
    "buyer_name": "Name des Leistungsempfängers",
    "seller_tax_id": "Steuernummer oder USt-IdNr. des Leistenden",
    "issue_date": "Ausstellungsdatum",
    "invoice_no": "Rechnungsnummer",
    "description": "Menge und Art der Leistung",
    "delivery_date": "Zeitpunkt der Lieferung oder Leistung",
    "net_by_rate": "Entgelt nach Steuersätzen",
    "tax_by_rate": "Steuersatz und Steuerbetrag",
    "gross": "Bruttobetrag",
    "rate": "Steuersatz",
    "reverse_charge_note": "Hinweis auf die Steuerschuldnerschaft des Leistungsempfängers",
    "buyer_vat_id": "USt-IdNr. des Leistungsempfängers",
}


def _present(inv: Invoice, field: str) -> bool:
    match field:
        case "seller_name":
            return bool(inv.seller.name)
        case "seller_address":
            return inv.seller.has_address
        case "buyer_name":
            return bool(inv.buyer.name)
        case "seller_tax_id":
            return bool(inv.seller.vat_id or inv.seller.tax_no)
        case "issue_date":
            return inv.issue_date is not None
        case "invoice_no":
            return bool(inv.invoice_no)
        case "description":
            return any(ln.description.strip() for ln in inv.lines)
        case "delivery_date":
            return inv.delivery_from is not None
        case "net_by_rate":
            return bool(inv.taxes) and all(t.base_cents or t.category != "S" for t in inv.taxes)
        case "tax_by_rate":
            return bool(inv.taxes) and all((t.rate > 0 and t.tax_cents > 0) or t.category != "S" for t in inv.taxes)
        case "gross":
            return inv.gross_cents is not None
        case "rate":
            return bool(inv.taxes)
    return True


def missing_fields(inv: Invoice, cfg: TaxConfig) -> list[str]:
    """Required details the invoice lacks (empty list: complete)."""
    small = inv.gross_cents is not None and inv.gross_cents <= cfg.kleinbetrag_gross_cents
    required = cfg.pflichtangaben_klein if small else cfg.pflichtangaben_full
    return [f for f in required if not _present(inv, f)]


def reverse_charge_notes(inv: Invoice, cfg: TaxConfig) -> list[str]:
    """§ 14a: what a reverse-charge invoice should state. Missing notes do not cost the deduction
    (the recipient owes the tax either way) but are worth telling the client's supplier."""
    if not any(t.category == "AE" for t in inv.taxes):
        return []
    out = []
    blob = " ".join([*inv.notes, *(t.exemption or "" for t in inv.taxes)]).lower()
    if cfg.reverse_charge_note.lower() not in blob and "reverse charge" not in blob:
        out.append("reverse_charge_note")
    if inv.seller.country and inv.seller.country != "DE" and not inv.buyer.vat_id:
        out.append("buyer_vat_id")
    return out
