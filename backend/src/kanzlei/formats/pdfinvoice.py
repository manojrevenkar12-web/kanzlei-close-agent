"""Reads a German invoice PDF that has no e-invoice data, from its text layer.

This is a layout reader: labels in their common spellings ("Rechnungsnummer", "Rg.-Nr."), amounts
next to them. It reports what it could not find instead of guessing; an invoice whose total it
cannot read goes to a person (or, for firms that allow it, to the model reader). Scans without a
text layer are out of scope here (docs/adr/0003).
"""

from __future__ import annotations

import io
import re
from datetime import date

from pypdf import PdfReader

from kanzlei.domain.money import parse_amount
from kanzlei.domain.text import country_of_vat_id, normalize_iban
from kanzlei.formats.invoice import Invoice, InvoiceLine, Party, TaxBreakdown

AMOUNT = r"(-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2})"
DATE = r"(\d{1,2}\.\d{1,2}\.\d{4})"

_NO = re.compile(
    r"(?:Rechnungsnummer|Rechnungs-Nr\.?|Rechnung\s+Nr\.?|Rg\.?\s*-?\s*Nr\.?|Beleg-?Nr\.?|Invoice\s+No\.?)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-/.]{1,30})",
    re.I,
)
_ISSUE = re.compile(r"(?:Rechnungsdatum|Belegdatum|Datum der Rechnung|Ausstellungsdatum|Datum)\s*:?\s*" + DATE, re.I)
_DELIVERY = re.compile(
    r"(?:Leistungsdatum|Lieferdatum|Leistungszeitraum|Liefer-/Leistungsdatum|Leistung erbracht am)\s*:?\s*"
    + DATE
    + r"(?:\s*(?:-|–|bis)\s*"
    + DATE
    + r")?",
    re.I,
)
_GROSS = re.compile(
    r"(?:Gesamtbetrag|Rechnungsbetrag|Summe brutto|Bruttobetrag|Gesamt brutto|Endbetrag|Zu zahlen|Zahlbetrag|Gesamtsumme)\s*(?:\(brutto\))?\s*:?\s*(?:EUR|€)?\s*"
    + AMOUNT,
    re.I,
)
_NET = re.compile(
    r"(?:Nettobetrag|Summe netto|Zwischensumme netto|Gesamt netto|Netto(?:summe)?)\s*:?\s*(?:EUR|€)?\s*" + AMOUNT, re.I
)
_TAX = re.compile(
    r"(?:zzgl\.\s*)?(?:USt\.?|MwSt\.?|Umsatzsteuer|Mehrwertsteuer)\s*(\d{1,2})\s*%\s*(?:auf\s*"
    + AMOUNT
    + r")?\s*:?\s*(?:EUR|€)?\s*"
    + AMOUNT,
    re.I,
)
_TAX_ALT = re.compile(
    r"(\d{1,2})\s*%\s*(?:USt\.?|MwSt\.?|Umsatzsteuer)\s*(?:auf\s*" + AMOUNT + r")?\s*:?\s*(?:EUR|€)?\s*" + AMOUNT, re.I
)
_VAT_ID = re.compile(
    r"(?:USt-?Id(?:Nr)?\.?|USt\.?-?IdNr\.?|Umsatzsteuer-Identifikationsnummer|VAT(?: ID)?)\s*:?\s*([A-Z]{2}\s?[0-9A-Z]{8,12})",
    re.I,
)
_TAX_NO = re.compile(r"(?:Steuernummer|St\.?-?Nr\.?)\s*:?\s*(\d{2,3}/\d{3}/\d{4,5})", re.I)
_IBAN = re.compile(r"IBAN\s*:?\s*([A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,3})?)")
_POSTCODE = re.compile(r"\b(\d{5})\s+([A-ZÄÖÜ][\wäöüßÄÖÜ .\-]+)$")
_LINE = re.compile(
    r"^(?:\d+\s+)?(.{3,80}?)\s+(\d+(?:,\d+)?)\s*(?:x|Stk\.?|Std\.?|h)?\s+"
    + AMOUNT
    + r"\s+"
    + AMOUNT
    + r"(?:\s*€)?(?:\s+(\d{1,2})\s*%)?$"
)
_RC = re.compile(r"Steuerschuldnerschaft des Leistungsempfängers|reverse charge|§\s*13b", re.I)
_CREDIT = re.compile(r"\bGutschrift\b|\bRechnungskorrektur\b|\bStornorechnung\b", re.I)


def _d(t: str | None) -> date | None:
    if not t:
        return None
    dd, mm, yy = (int(x) for x in t.split("."))
    try:
        return date(yy, mm, dd)
    except ValueError:
        return None


def pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def read_invoice_text(raw: str) -> Invoice:
    inv = Invoice(source="pdf")
    lines = [" ".join(x.split()) for x in raw.splitlines()]
    lines = [x for x in lines if x]
    if not lines:
        inv.issues.append("kein Text im PDF (Scan?)")
        return inv
    body = "\n".join(lines)

    # Letterhead: the seller is the first line; its address is the first postcode line after it.
    seller = Party(name=lines[0])
    for i, ln in enumerate(lines[1:6], start=1):
        m = _POSTCODE.search(ln)
        if m:
            seller.postcode, seller.city = m.group(1), m.group(2).strip()
            seller.street = lines[i - 1] if i - 1 > 0 else ""
            break
    if (m2 := _VAT_ID.search(body)) is not None:
        seller.vat_id = m2.group(1).replace(" ", "").upper()
        seller.country = country_of_vat_id(seller.vat_id) or "DE"
    if (m3 := _TAX_NO.search(body)) is not None:
        seller.tax_no = m3.group(1)
    if not seller.country:
        seller.country = "DE"
    inv.seller = seller

    # Buyer: the block after "Rechnung an" / "Empfänger", else the first name after the letterhead.
    for i, ln in enumerate(lines):
        if re.match(r"^(Rechnung an|Rechnungsempfänger|Empfänger|Kunde)\s*:?\s*$", ln, re.I) and i + 1 < len(lines):
            inv.buyer = Party(name=lines[i + 1], street=lines[i + 2] if i + 2 < len(lines) else "")
            pc = _POSTCODE.search(lines[i + 3]) if i + 3 < len(lines) else None
            if pc:
                inv.buyer.postcode, inv.buyer.city = pc.group(1), pc.group(2).strip()
            break

    if (m := _NO.search(body)) is not None:
        inv.invoice_no = m.group(1).rstrip(".")
    if (m := _ISSUE.search(body)) is not None:
        inv.issue_date = _d(m.group(1))
    if (m := _DELIVERY.search(body)) is not None:
        inv.delivery_from = _d(m.group(1))
        inv.delivery_to = _d(m.group(2)) or inv.delivery_from
    if (m := _IBAN.search(body)) is not None:
        inv.seller_iban = normalize_iban(m.group(1))
    if _CREDIT.search(body):
        inv.type_code = "381"

    gross = [parse_amount(m.group(1)) for m in _GROSS.finditer(body)]
    inv.gross_cents = gross[-1] if gross else None
    net = [parse_amount(m.group(1)) for m in _NET.finditer(body)]
    inv.net_cents = net[-1] if net else None

    rc = bool(_RC.search(body))
    seen: set[int] = set()
    for rx in (_TAX, _TAX_ALT):
        for m in rx.finditer(body):
            rate = int(m.group(1))
            if rate in seen:
                continue
            seen.add(rate)
            base = parse_amount(m.group(2)) if m.group(2) else None
            tax = parse_amount(m.group(3))
            if base is None:
                base = round(tax * 100 / rate) if rate else 0
            inv.taxes.append(TaxBreakdown(category="S", rate=rate, base_cents=base, tax_cents=tax))
    if rc and not inv.taxes:
        base = inv.net_cents if inv.net_cents is not None else inv.gross_cents
        if base is not None:
            inv.taxes.append(
                TaxBreakdown(category="AE", rate=0, base_cents=base, tax_cents=0, exemption="Reverse charge")
            )
    if inv.taxes:
        inv.tax_cents = sum(t.tax_cents for t in inv.taxes)
        if inv.net_cents is None:
            inv.net_cents = sum(t.base_cents for t in inv.taxes)
    if inv.gross_cents is None and inv.net_cents is not None and inv.tax_cents is not None:
        inv.gross_cents = inv.net_cents + inv.tax_cents
    if rc:
        inv.notes.append("Steuerschuldnerschaft des Leistungsempfängers")

    for ln in lines:
        m = _LINE.match(ln)
        if m and not _GROSS.search(ln) and not _NET.search(ln):
            line_rate = int(m.group(5)) if m.group(5) else None
            inv.lines.append(
                InvoiceLine(
                    description=m.group(1).strip(),
                    net_cents=parse_amount(m.group(4)),
                    rate=line_rate,
                    category="S" if line_rate else None,
                    quantity=float(m.group(2).replace(",", ".")),
                )
            )
    if not inv.lines:
        # No table found: keep the words around the amounts as the description.
        desc = [ln for ln in lines[3:] if not re.search(AMOUNT, ln) and len(ln) > 3][:3]
        if desc:
            inv.lines.append(
                InvoiceLine(description=" ".join(desc), net_cents=inv.net_cents or 0, rate=None, category=None)
            )

    if inv.gross_cents is None:
        inv.issues.append("Gesamtbetrag nicht lesbar")
    inv.check_totals()
    return inv


def read_invoice_pdf(data: bytes) -> Invoice:
    try:
        raw = pdf_text(data)
    except Exception as e:
        inv = Invoice(source="pdf")
        inv.issues.append(f"PDF nicht lesbar: {e}")
        return inv
    return read_invoice_text(raw)
