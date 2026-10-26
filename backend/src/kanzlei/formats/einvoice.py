"""E-invoices (EN 16931): XRechnung as UBL or CII, and ZUGFeRD / Factur-X (CII inside a PDF).

Since 1 January 2025 every German business must be able to receive these. The XML is the
invoice; a PDF rendering of it is not, so the original bytes are archived as received.
"""

from __future__ import annotations

import io
from datetime import date
from xml.etree.ElementTree import Element

from pypdf import PdfReader

from kanzlei.domain.money import parse_amount
from kanzlei.domain.text import normalize_iban
from kanzlei.formats.invoice import Invoice, InvoiceLine, Party, TaxBreakdown
from kanzlei.formats.xml import FormatError, every, kid, local, parse_xml, text

ZUGFERD_NAMES = ("factur-x.xml", "zugferd-invoice.xml", "xrechnung.xml", "zugferd_invoice.xml")


def _amount(el: Element | None, path: str) -> int | None:
    t = text(el, path)
    return parse_amount(t) if t is not None else None


def _rate(t: str | None) -> int | None:
    if t is None:
        return None
    v = float(t)
    return round(v)


def _iso(t: str | None) -> date | None:
    return date.fromisoformat(t[:10]) if t else None


def _cii_date(t: str | None) -> date | None:
    if not t:
        return None
    t = t.strip()
    if len(t) == 8 and t.isdigit():
        return date(int(t[:4]), int(t[4:6]), int(t[6:8]))
    return _iso(t)


# --- UBL -----------------------------------------------------------------------------------------


def _ubl_party(p: Element | None) -> Party:
    party = Party()
    if p is None:
        return party
    party.name = text(p, "PartyLegalEntity/RegistrationName") or text(p, "PartyName/Name") or ""
    party.street = text(p, "PostalAddress/StreetName") or ""
    party.postcode = text(p, "PostalAddress/PostalZone") or ""
    party.city = text(p, "PostalAddress/CityName") or ""
    party.country = text(p, "PostalAddress/Country/IdentificationCode") or ""
    for pts in every(p, "PartyTaxScheme"):
        scheme = text(pts, "TaxScheme/ID")
        cid = text(pts, "CompanyID")
        if scheme == "VAT":
            party.vat_id = cid
        elif cid:
            party.tax_no = cid
    return party


def parse_ubl(root: Element) -> Invoice:
    credit = local(root.tag) == "CreditNote"
    inv = Invoice(source="xrechnung-ubl")
    inv.invoice_no = text(root, "ID")
    inv.type_code = text(root, "CreditNoteTypeCode" if credit else "InvoiceTypeCode") or ("381" if credit else "380")
    inv.issue_date = _iso(text(root, "IssueDate"))
    inv.currency = text(root, "DocumentCurrencyCode") or "EUR"
    inv.notes = [t for t in (text(n) for n in every(root, "Note")) if t]
    inv.delivery_from = _iso(text(root, "InvoicePeriod/StartDate")) or _iso(text(root, "Delivery/ActualDeliveryDate"))
    inv.delivery_to = _iso(text(root, "InvoicePeriod/EndDate")) or inv.delivery_from
    inv.seller = _ubl_party(kid(root, "AccountingSupplierParty/Party"))
    inv.buyer = _ubl_party(kid(root, "AccountingCustomerParty/Party"))
    inv.seller_iban = normalize_iban(text(root, "PaymentMeans/PayeeFinancialAccount/ID"))
    inv.due_date = _iso(text(root, "DueDate")) or _iso(text(root, "PaymentMeans/PaymentDueDate"))
    inv.payment_terms = text(root, "PaymentTerms/Note") or ""
    for tt in every(root, "TaxTotal"):
        for sub in every(tt, "TaxSubtotal"):
            inv.taxes.append(
                TaxBreakdown(
                    category=text(sub, "TaxCategory/ID") or "S",
                    rate=_rate(text(sub, "TaxCategory/Percent")) or 0,
                    base_cents=_amount(sub, "TaxableAmount") or 0,
                    tax_cents=_amount(sub, "TaxAmount") or 0,
                    exemption=text(sub, "TaxCategory/TaxExemptionReason"),
                )
            )
        if inv.tax_cents is None:
            inv.tax_cents = _amount(tt, "TaxAmount")
    line_tag = "CreditNoteLine" if credit else "InvoiceLine"
    for ln in every(root, line_tag):
        inv.lines.append(
            InvoiceLine(
                description=text(ln, "Item/Name") or text(ln, "Item/Description") or "",
                net_cents=_amount(ln, "LineExtensionAmount") or 0,
                rate=_rate(text(ln, "Item/ClassifiedTaxCategory/Percent")),
                category=text(ln, "Item/ClassifiedTaxCategory/ID"),
                quantity=float(text(ln, "InvoicedQuantity") or text(ln, "CreditedQuantity") or 1),
            )
        )
    inv.net_cents = _amount(root, "LegalMonetaryTotal/TaxExclusiveAmount")
    inv.gross_cents = _amount(root, "LegalMonetaryTotal/TaxInclusiveAmount")
    inv.payable_cents = _amount(root, "LegalMonetaryTotal/PayableAmount")
    return inv


# --- CII -----------------------------------------------------------------------------------------


def _cii_party(p: Element | None) -> Party:
    party = Party()
    if p is None:
        return party
    party.name = text(p, "Name") or ""
    party.street = text(p, "PostalTradeAddress/LineOne") or ""
    party.postcode = text(p, "PostalTradeAddress/PostcodeCode") or ""
    party.city = text(p, "PostalTradeAddress/CityName") or ""
    party.country = text(p, "PostalTradeAddress/CountryID") or ""
    for reg in every(p, "SpecifiedTaxRegistration"):
        rid = kid(reg, "ID")
        if rid is None or not rid.text:
            continue
        if rid.attrib.get("schemeID") == "VA":
            party.vat_id = rid.text.strip()
        else:
            party.tax_no = rid.text.strip()
    return party


def parse_cii(root: Element, source: str = "xrechnung-cii") -> Invoice:
    inv = Invoice(source=source)
    doc = kid(root, "ExchangedDocument")
    inv.invoice_no = text(doc, "ID")
    inv.type_code = text(doc, "TypeCode") or "380"
    inv.issue_date = _cii_date(text(doc, "IssueDateTime/DateTimeString"))
    inv.notes = [t for t in (text(n, "Content") for n in every(doc, "IncludedNote")) if t]
    tx = kid(root, "SupplyChainTradeTransaction")
    agreement = kid(tx, "ApplicableHeaderTradeAgreement")
    inv.seller = _cii_party(kid(agreement, "SellerTradeParty"))
    inv.buyer = _cii_party(kid(agreement, "BuyerTradeParty"))
    delivery = kid(tx, "ApplicableHeaderTradeDelivery")
    d = _cii_date(text(delivery, "ActualDeliverySupplyChainEvent/OccurrenceDateTime/DateTimeString"))
    settlement = kid(tx, "ApplicableHeaderTradeSettlement")
    inv.currency = text(settlement, "InvoiceCurrencyCode") or "EUR"
    period_from = _cii_date(text(settlement, "BillingSpecifiedPeriod/StartDateTime/DateTimeString"))
    period_to = _cii_date(text(settlement, "BillingSpecifiedPeriod/EndDateTime/DateTimeString"))
    inv.delivery_from = period_from or d
    inv.delivery_to = period_to or d
    inv.seller_iban = normalize_iban(
        text(settlement, "SpecifiedTradeSettlementPaymentMeans/PayeePartyCreditorFinancialAccount/IBANID")
    )
    inv.payment_terms = text(settlement, "SpecifiedTradePaymentTerms/Description") or ""
    inv.due_date = _cii_date(text(settlement, "SpecifiedTradePaymentTerms/DueDateDateTime/DateTimeString"))
    for t in every(settlement, "ApplicableTradeTax"):
        inv.taxes.append(
            TaxBreakdown(
                category=text(t, "CategoryCode") or "S",
                rate=_rate(text(t, "RateApplicablePercent")) or 0,
                base_cents=_amount(t, "BasisAmount") or 0,
                tax_cents=_amount(t, "CalculatedAmount") or 0,
                exemption=text(t, "ExemptionReason"),
            )
        )
    for item in every(tx, "IncludedSupplyChainTradeLineItem"):
        inv.lines.append(
            InvoiceLine(
                description=text(item, "SpecifiedTradeProduct/Name") or "",
                net_cents=_amount(
                    item, "SpecifiedLineTradeSettlement/SpecifiedTradeSettlementLineMonetarySummation/LineTotalAmount"
                )
                or 0,
                rate=_rate(text(item, "SpecifiedLineTradeSettlement/ApplicableTradeTax/RateApplicablePercent")),
                category=text(item, "SpecifiedLineTradeSettlement/ApplicableTradeTax/CategoryCode"),
                quantity=float(text(item, "SpecifiedLineTradeDelivery/BilledQuantity") or 1),
            )
        )
    sums = kid(settlement, "SpecifiedTradeSettlementHeaderMonetarySummation")
    inv.net_cents = _amount(sums, "TaxBasisTotalAmount")
    inv.tax_cents = _amount(sums, "TaxTotalAmount")
    inv.gross_cents = _amount(sums, "GrandTotalAmount")
    inv.payable_cents = _amount(sums, "DuePayableAmount")
    return inv


def parse_einvoice_xml(data: bytes, source: str | None = None) -> Invoice:
    root = parse_xml(data)
    name = local(root.tag)
    if name in ("Invoice", "CreditNote"):
        inv = parse_ubl(root)
    elif name == "CrossIndustryInvoice":
        inv = parse_cii(root, source or "xrechnung-cii")
    else:
        raise FormatError(f"not an e-invoice (root element {name})")
    if inv.gross_cents is None and inv.net_cents is not None and inv.tax_cents is not None:
        inv.gross_cents = inv.net_cents + inv.tax_cents
    inv.check_totals()
    return inv


def embedded_xml(pdf: bytes) -> bytes | None:
    """The CII XML a ZUGFeRD / Factur-X PDF carries, if any."""
    try:
        reader = PdfReader(io.BytesIO(pdf))
        attachments = reader.attachments
    except Exception:
        return None
    for name, payloads in attachments.items():
        if name.lower() in ZUGFERD_NAMES and payloads:
            return payloads[0]
    return None


def parse_zugferd(pdf: bytes) -> Invoice | None:
    xml = embedded_xml(pdf)
    if xml is None:
        return None
    return parse_einvoice_xml(xml, source="zugferd")
