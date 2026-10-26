"""Renders a scenario into the files a firm and its clients hand over.

    camt.053 bank statements, XRechnung (UBL and CII), ZUGFeRD PDFs (CII embedded), plain PDF
    invoices in three layouts and till receipts, DATEV EXTF history and master data, firm.json.

Missing mandatory invoice details (DocSpec.missing) are left out of what is rendered.
"""

from __future__ import annotations

import io
import json
import zlib
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

from kanzlei.formats.extf import ExtfBooking, MasterRecord, write_buchungsstapel, write_stammdaten
from kanzlei_sim.scenario import Client, DocSpec, Event, Firm, Party, cents
from kanzlei_sim.truth import TLine, system

# --- helpers -------------------------------------------------------------------------------------


def _x(s: str) -> str:
    return escape(s, {'"': "&quot;"})


def _amt(c: int) -> str:
    return f"{c // 100}.{c % 100:02d}" if c >= 0 else f"-{(-c) // 100}.{(-c) % 100:02d}"


def _de(c: int) -> str:
    s = f"{abs(c) // 100:,}".replace(",", ".") + f",{abs(c) % 100:02d}"
    return ("-" if c < 0 else "") + s


def _half_up(x: Decimal) -> int:
    return int(x.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def tax_groups(doc: DocSpec) -> list[dict[str, Any]]:
    acc: dict[tuple[int, str], int] = {}
    for ln in doc.lines:
        acc[(ln.rate, ln.category)] = acc.get((ln.rate, ln.category), 0) + cents(ln.net)
    out = []
    for (rate, cat), net in acc.items():
        tax = _half_up(Decimal(net) * rate / 100) if cat == "S" else 0
        out.append({"rate": rate if cat == "S" else 0, "category": cat, "base": net, "tax": tax})
    return out


def totals(doc: DocSpec) -> tuple[int, int, int]:
    g = tax_groups(doc)
    net = sum(x["base"] for x in g)
    tax = sum(x["tax"] for x in g)
    return net, tax, net + tax


def _exemption(cat: str) -> str | None:
    return {
        "AE": "Steuerschuldnerschaft des Leistungsempfängers",
        "K": "Steuerfreie innergemeinschaftliche Lieferung",
        "E": "Steuerbefreit",
        "O": "Nicht im Inland steuerbar",
    }.get(cat)


def seller_buyer(client: Client, party: Party, doc: DocSpec) -> tuple[dict[str, Any], dict[str, Any]]:
    me = {
        "name": client.name,
        "street": client.street,
        "postcode": client.postcode,
        "city": client.city,
        "country": "DE",
        "vat_id": client.vat_id,
        "tax_no": None,
        "iban": client.iban,
    }
    them = {
        "name": party.name,
        "street": party.street,
        "postcode": party.postcode,
        "city": party.city,
        "country": party.country,
        "vat_id": party.vat_id,
        "tax_no": party.tax_no,
        "iban": party.iban,
    }
    return (them, me) if doc.direction == "in" else (me, them)


# --- XRechnung UBL --------------------------------------------------------------------------------


def ubl(client: Client, party: Party, doc: DocSpec) -> bytes:
    seller, buyer = seller_buyer(client, party, doc)
    net, tax, gross = totals(doc)
    miss = set(doc.missing)
    issue = doc.issue_date or date.today()

    def party_xml(p: dict[str, Any], is_seller: bool) -> str:
        tax_scheme = ""
        if p.get("vat_id") and not (is_seller and "seller_tax_id" in miss):
            tax_scheme = f"<cac:PartyTaxScheme><cbc:CompanyID>{_x(p['vat_id'])}</cbc:CompanyID><cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>"
        elif p.get("tax_no") and not (is_seller and "seller_tax_id" in miss):
            tax_scheme = f"<cac:PartyTaxScheme><cbc:CompanyID>{_x(p['tax_no'])}</cbc:CompanyID><cac:TaxScheme><cbc:ID>FC</cbc:ID></cac:TaxScheme></cac:PartyTaxScheme>"
        name = "" if (not is_seller and "buyer_name" in miss) else p["name"]
        addr = (
            ""
            if (is_seller and "seller_address" in miss)
            else (
                f"<cac:PostalAddress><cbc:StreetName>{_x(p['street'])}</cbc:StreetName><cbc:CityName>{_x(p['city'])}</cbc:CityName>"
                f"<cbc:PostalZone>{_x(p['postcode'])}</cbc:PostalZone><cac:Country><cbc:IdentificationCode>{p['country']}</cbc:IdentificationCode></cac:Country></cac:PostalAddress>"
            )
        )
        return f"<cac:Party>{addr}{tax_scheme}<cac:PartyLegalEntity><cbc:RegistrationName>{_x(name)}</cbc:RegistrationName></cac:PartyLegalEntity></cac:Party>"

    subs = "".join(
        f'<cac:TaxSubtotal><cbc:TaxableAmount currencyID="EUR">{_amt(g["base"])}</cbc:TaxableAmount><cbc:TaxAmount currencyID="EUR">{_amt(g["tax"])}</cbc:TaxAmount>'
        f"<cac:TaxCategory><cbc:ID>{g['category']}</cbc:ID><cbc:Percent>{g['rate']}</cbc:Percent>"
        + (
            f"<cbc:TaxExemptionReason>{_x(_exemption(g['category']) or '')}</cbc:TaxExemptionReason>"
            if g["category"] != "S"
            else ""
        )
        + "<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:TaxCategory></cac:TaxSubtotal>"
        for g in tax_groups(doc)
    )
    lines = "".join(
        f'<cac:InvoiceLine><cbc:ID>{i}</cbc:ID><cbc:InvoicedQuantity unitCode="C62">{ln.quantity:g}</cbc:InvoicedQuantity>'
        f'<cbc:LineExtensionAmount currencyID="EUR">{_amt(cents(ln.net))}</cbc:LineExtensionAmount>'
        f"<cac:Item><cbc:Name>{_x(ln.text)}</cbc:Name><cac:ClassifiedTaxCategory><cbc:ID>{ln.category}</cbc:ID><cbc:Percent>{ln.rate if ln.category == 'S' else 0}</cbc:Percent>"
        f"<cac:TaxScheme><cbc:ID>VAT</cbc:ID></cac:TaxScheme></cac:ClassifiedTaxCategory></cac:Item>"
        f'<cac:Price><cbc:PriceAmount currencyID="EUR">{_amt(round(cents(ln.net) / max(ln.quantity, 1)))}</cbc:PriceAmount></cac:Price></cac:InvoiceLine>'
        for i, ln in enumerate(doc.lines, start=1)
    )
    notes = "".join(f"<cbc:Note>{_x(n)}</cbc:Note>" for n in doc.notes)
    delivery = (
        ""
        if ("delivery_date" in miss or not doc.delivery_date)
        else f"<cac:Delivery><cbc:ActualDeliveryDate>{doc.delivery_date.isoformat()}</cbc:ActualDeliveryDate></cac:Delivery>"
    )
    pay = (
        f"<cac:PaymentMeans><cbc:PaymentMeansCode>58</cbc:PaymentMeansCode><cac:PayeeFinancialAccount><cbc:ID>{seller['iban']}</cbc:ID></cac:PayeeFinancialAccount></cac:PaymentMeans>"
        if seller.get("iban")
        else ""
    )
    terms = (
        f"<cac:PaymentTerms><cbc:Note>{_x(doc.payment_terms)}</cbc:Note></cac:PaymentTerms>"
        if doc.payment_terms
        else ""
    )
    number = "" if "invoice_no" in miss else f"<cbc:ID>{_x(doc.number)}</cbc:ID>"
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Invoice xmlns="urn:oasis:names:specification:ubl:schema:xsd:Invoice-2" '
        'xmlns:cac="urn:oasis:names:specification:ubl:schema:xsd:CommonAggregateComponents-2" '
        'xmlns:cbc="urn:oasis:names:specification:ubl:schema:xsd:CommonBasicComponents-2">'
        "<cbc:CustomizationID>urn:cen.eu:en16931:2017#compliant#urn:xeinkauf.de:kosit:xrechnung_3.0</cbc:CustomizationID>"
        "<cbc:ProfileID>urn:fdc:peppol.eu:2017:poacc:billing:01:1.0</cbc:ProfileID>"
        f"{number}<cbc:IssueDate>{issue.isoformat()}</cbc:IssueDate><cbc:InvoiceTypeCode>{'381' if doc.credit_note else '380'}</cbc:InvoiceTypeCode>{notes}"
        "<cbc:DocumentCurrencyCode>EUR</cbc:DocumentCurrencyCode><cbc:BuyerReference>n/a</cbc:BuyerReference>"
        f"<cac:AccountingSupplierParty>{party_xml(seller, True)}</cac:AccountingSupplierParty>"
        f"<cac:AccountingCustomerParty>{party_xml(buyer, False)}</cac:AccountingCustomerParty>"
        f"{delivery}{pay}{terms}"
        f'<cac:TaxTotal><cbc:TaxAmount currencyID="EUR">{_amt(tax)}</cbc:TaxAmount>{subs}</cac:TaxTotal>'
        f'<cac:LegalMonetaryTotal><cbc:LineExtensionAmount currencyID="EUR">{_amt(net)}</cbc:LineExtensionAmount>'
        f'<cbc:TaxExclusiveAmount currencyID="EUR">{_amt(net)}</cbc:TaxExclusiveAmount><cbc:TaxInclusiveAmount currencyID="EUR">{_amt(gross)}</cbc:TaxInclusiveAmount>'
        f'<cbc:PayableAmount currencyID="EUR">{_amt(gross)}</cbc:PayableAmount></cac:LegalMonetaryTotal>'
        f"{lines}</Invoice>"
    )
    return xml.encode("utf-8")


# --- CII (XRechnung CII and ZUGFeRD) --------------------------------------------------------------


def cii(client: Client, party: Party, doc: DocSpec) -> bytes:
    seller, buyer = seller_buyer(client, party, doc)
    net, tax, gross = totals(doc)
    miss = set(doc.missing)
    issue = doc.issue_date or date.today()

    def d102(d: date) -> str:
        return f'<udt:DateTimeString format="102">{d.strftime("%Y%m%d")}</udt:DateTimeString>'

    def party_xml(tag: str, p: dict[str, Any], is_seller: bool) -> str:
        reg = ""
        if not (is_seller and "seller_tax_id" in miss):
            if p.get("vat_id"):
                reg = f'<ram:SpecifiedTaxRegistration><ram:ID schemeID="VA">{_x(p["vat_id"])}</ram:ID></ram:SpecifiedTaxRegistration>'
            elif p.get("tax_no"):
                reg = f'<ram:SpecifiedTaxRegistration><ram:ID schemeID="FC">{_x(p["tax_no"])}</ram:ID></ram:SpecifiedTaxRegistration>'
        name = "" if (not is_seller and "buyer_name" in miss) else p["name"]
        addr = (
            ""
            if (is_seller and "seller_address" in miss)
            else (
                f"<ram:PostalTradeAddress><ram:PostcodeCode>{_x(p['postcode'])}</ram:PostcodeCode><ram:LineOne>{_x(p['street'])}</ram:LineOne>"
                f"<ram:CityName>{_x(p['city'])}</ram:CityName><ram:CountryID>{p['country']}</ram:CountryID></ram:PostalTradeAddress>"
            )
        )
        return f"<ram:{tag}><ram:Name>{_x(name)}</ram:Name>{addr}{reg}</ram:{tag}>"

    items = "".join(
        f"<ram:IncludedSupplyChainTradeLineItem><ram:AssociatedDocumentLineDocument><ram:LineID>{i}</ram:LineID></ram:AssociatedDocumentLineDocument>"
        f"<ram:SpecifiedTradeProduct><ram:Name>{_x(ln.text)}</ram:Name></ram:SpecifiedTradeProduct>"
        f"<ram:SpecifiedLineTradeAgreement><ram:NetPriceProductTradePrice><ram:ChargeAmount>{_amt(round(cents(ln.net) / max(ln.quantity, 1)))}</ram:ChargeAmount></ram:NetPriceProductTradePrice></ram:SpecifiedLineTradeAgreement>"
        f'<ram:SpecifiedLineTradeDelivery><ram:BilledQuantity unitCode="C62">{ln.quantity:g}</ram:BilledQuantity></ram:SpecifiedLineTradeDelivery>'
        f"<ram:SpecifiedLineTradeSettlement><ram:ApplicableTradeTax><ram:TypeCode>VAT</ram:TypeCode><ram:CategoryCode>{ln.category}</ram:CategoryCode>"
        f"<ram:RateApplicablePercent>{ln.rate if ln.category == 'S' else 0}</ram:RateApplicablePercent></ram:ApplicableTradeTax>"
        f"<ram:SpecifiedTradeSettlementLineMonetarySummation><ram:LineTotalAmount>{_amt(cents(ln.net))}</ram:LineTotalAmount></ram:SpecifiedTradeSettlementLineMonetarySummation>"
        "</ram:SpecifiedLineTradeSettlement></ram:IncludedSupplyChainTradeLineItem>"
        for i, ln in enumerate(doc.lines, start=1)
    )
    taxes = "".join(
        f"<ram:ApplicableTradeTax><ram:CalculatedAmount>{_amt(g['tax'])}</ram:CalculatedAmount><ram:TypeCode>VAT</ram:TypeCode>"
        + (
            f"<ram:ExemptionReason>{_x(_exemption(g['category']) or '')}</ram:ExemptionReason>"
            if g["category"] != "S"
            else ""
        )
        + f"<ram:BasisAmount>{_amt(g['base'])}</ram:BasisAmount><ram:CategoryCode>{g['category']}</ram:CategoryCode>"
        f"<ram:RateApplicablePercent>{g['rate']}</ram:RateApplicablePercent></ram:ApplicableTradeTax>"
        for g in tax_groups(doc)
    )
    notes = "".join(f"<ram:IncludedNote><ram:Content>{_x(n)}</ram:Content></ram:IncludedNote>" for n in doc.notes)
    delivery = (
        ""
        if ("delivery_date" in miss or not doc.delivery_date)
        else f"<ram:ActualDeliverySupplyChainEvent><ram:OccurrenceDateTime>{d102(doc.delivery_date)}</ram:OccurrenceDateTime></ram:ActualDeliverySupplyChainEvent>"
    )
    pay = (
        f"<ram:SpecifiedTradeSettlementPaymentMeans><ram:TypeCode>58</ram:TypeCode><ram:PayeePartyCreditorFinancialAccount><ram:IBANID>{seller['iban']}</ram:IBANID></ram:PayeePartyCreditorFinancialAccount></ram:SpecifiedTradeSettlementPaymentMeans>"
        if seller.get("iban")
        else ""
    )
    terms = (
        f"<ram:SpecifiedTradePaymentTerms><ram:Description>{_x(doc.payment_terms)}</ram:Description></ram:SpecifiedTradePaymentTerms>"
        if doc.payment_terms
        else ""
    )
    number = "" if "invoice_no" in miss else f"<ram:ID>{_x(doc.number)}</ram:ID>"
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rsm:CrossIndustryInvoice xmlns:rsm="urn:un:unece:uncefact:data:standard:CrossIndustryInvoice:100" '
        'xmlns:ram="urn:un:unece:uncefact:data:standard:ReusableAggregateBusinessInformationEntity:100" '
        'xmlns:udt="urn:un:unece:uncefact:data:standard:UnqualifiedDataType:100">'
        "<rsm:ExchangedDocumentContext><ram:GuidelineSpecifiedDocumentContextParameter><ram:ID>urn:cen.eu:en16931:2017</ram:ID>"
        "</ram:GuidelineSpecifiedDocumentContextParameter></rsm:ExchangedDocumentContext>"
        f"<rsm:ExchangedDocument>{number}<ram:TypeCode>{'381' if doc.credit_note else '380'}</ram:TypeCode><ram:IssueDateTime>{d102(issue)}</ram:IssueDateTime>{notes}</rsm:ExchangedDocument>"
        f"<rsm:SupplyChainTradeTransaction>{items}"
        f"<ram:ApplicableHeaderTradeAgreement><ram:BuyerReference>n/a</ram:BuyerReference>{party_xml('SellerTradeParty', seller, True)}{party_xml('BuyerTradeParty', buyer, False)}</ram:ApplicableHeaderTradeAgreement>"
        f"<ram:ApplicableHeaderTradeDelivery>{delivery}</ram:ApplicableHeaderTradeDelivery>"
        f"<ram:ApplicableHeaderTradeSettlement><ram:InvoiceCurrencyCode>EUR</ram:InvoiceCurrencyCode>{pay}{taxes}{terms}"
        f"<ram:SpecifiedTradeSettlementHeaderMonetarySummation><ram:LineTotalAmount>{_amt(net)}</ram:LineTotalAmount><ram:TaxBasisTotalAmount>{_amt(net)}</ram:TaxBasisTotalAmount>"
        f'<ram:TaxTotalAmount currencyID="EUR">{_amt(tax)}</ram:TaxTotalAmount><ram:GrandTotalAmount>{_amt(gross)}</ram:GrandTotalAmount><ram:DuePayableAmount>{_amt(gross)}</ram:DuePayableAmount>'
        "</ram:SpecifiedTradeSettlementHeaderMonetarySummation></ram:ApplicableHeaderTradeSettlement>"
        "</rsm:SupplyChainTradeTransaction></rsm:CrossIndustryInvoice>"
    )
    return xml.encode("utf-8")


# --- PDFs ------------------------------------------------------------------------------------------

LAYOUTS = [
    {
        "no": "Rechnungsnummer",
        "date": "Rechnungsdatum",
        "delivery": "Leistungsdatum",
        "net": "Nettobetrag",
        "vat": "zzgl. USt {rate} %",
        "gross": "Gesamtbetrag",
        "to": "Rechnung an",
        "vat_id": "USt-IdNr.",
        "tax_no": "Steuernummer",
    },
    {
        "no": "Rechnung Nr.",
        "date": "Datum",
        "delivery": "Lieferdatum",
        "net": "Summe netto",
        "vat": "MwSt. {rate} %",
        "gross": "Zu zahlen",
        "to": "Rechnungsempfänger",
        "vat_id": "USt-IdNr",
        "tax_no": "St.-Nr.",
    },
    {
        "no": "Rg.-Nr.",
        "date": "Belegdatum",
        "delivery": "Leistungszeitraum",
        "net": "Zwischensumme netto",
        "vat": "{rate} % Umsatzsteuer",
        "gross": "Rechnungsbetrag",
        "to": "Kunde",
        "vat_id": "Umsatzsteuer-Identifikationsnummer",
        "tax_no": "Steuernummer",
    },
]


def _pdf(lines: list[str]) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1)
    y = 800
    for text in lines:
        if y < 60:
            c.showPage()
            y = 800
        c.setFont("Helvetica", 10)
        c.drawString(56, y, text)
        y -= 15
    c.showPage()
    c.save()
    return buf.getvalue()


def pdf_invoice(client: Client, party: Party, doc: DocSpec) -> bytes:
    seller, buyer = seller_buyer(client, party, doc)
    L = LAYOUTS[doc.layout % len(LAYOUTS)]
    miss = set(doc.missing)
    net, _tax, gross = totals(doc)
    out = [seller["name"]]
    if "seller_address" not in miss:
        out += [seller["street"], f"{seller['postcode']} {seller['city']}"]
    out.append("")
    if "buyer_name" not in miss:
        out += [L["to"], buyer["name"], buyer["street"], f"{buyer['postcode']} {buyer['city']}"]
    out.append("")
    out.append("Gutschrift" if doc.credit_note else "Rechnung")
    if "invoice_no" not in miss:
        out.append(f"{L['no']}: {doc.number}")
    out.append(f"{L['date']}: {(doc.issue_date or date.today()).strftime('%d.%m.%Y')}")
    if "delivery_date" not in miss and doc.delivery_date:
        out.append(f"{L['delivery']}: {doc.delivery_date.strftime('%d.%m.%Y')}")
    out.append("")
    out.append("Pos Beschreibung Menge Einzelpreis Gesamt")
    for i, ln in enumerate(doc.lines, start=1):
        unit = round(cents(ln.net) / max(ln.quantity, 1))
        rate = f" {ln.rate} %" if ln.category == "S" else ""
        out.append(f"{i} {ln.text} {ln.quantity:g} Stk {_de(unit)} {_de(cents(ln.net))} €{rate}")
    out.append("")
    groups = tax_groups(doc)
    out.append(f"{L['net']}: {_de(net)} €")
    for g in groups:
        if g["category"] == "S":
            out.append(f"{L['vat'].format(rate=g['rate'])} auf {_de(g['base'])} €: {_de(g['tax'])} €")
    out.append(f"{L['gross']}: {_de(gross)} €")
    out.append("")
    out += list(doc.notes)
    if doc.payment_terms:
        out.append(doc.payment_terms)
    if any(ln.category in ("AE", "K") for ln in doc.lines) and buyer.get("vat_id") and "buyer_vat_id" not in miss:
        out.append(f"USt-IdNr. Leistungsempfänger: {buyer['vat_id']}")
    if "seller_tax_id" not in miss:
        if seller.get("vat_id"):
            out.append(f"{L['vat_id']}: {seller['vat_id']}")
        elif seller.get("tax_no"):
            out.append(f"{L['tax_no']}: {seller['tax_no']}")
    if seller.get("iban"):
        out.append(f"IBAN: {seller['iban']}")
    return _pdf(out)


def pdf_receipt(client: Client, party: Party, doc: DocSpec) -> bytes:
    """A till receipt (Kleinbetragsrechnung): no buyer, total and rate."""
    _net, _tax, gross = totals(doc)
    out = [party.name, party.street, f"{party.postcode} {party.city}", ""]
    out.append(f"Datum: {(doc.issue_date or date.today()).strftime('%d.%m.%Y')} Beleg-Nr. {doc.number}")
    for ln in doc.lines:
        out.append(f"{ln.text} {_de(_half_up(Decimal(cents(ln.net)) * (100 + ln.rate) / 100))}")
    out.append(f"Summe brutto: {_de(gross)} EUR")
    for g in tax_groups(doc):
        if g["category"] == "S":
            out.append(f"MwSt. {g['rate']} % auf {_de(g['base'])}: {_de(g['tax'])}")
    out += list(doc.notes)
    if party.vat_id:
        out.append(f"USt-IdNr.: {party.vat_id}")
    if party.tax_no:
        out.append(f"Steuernummer: {party.tax_no}")
    return _pdf(out)


def zugferd(client: Client, party: Party, doc: DocSpec) -> bytes:
    visual = pdf_invoice(client, party, doc)
    w = PdfWriter()
    for page in PdfReader(io.BytesIO(visual)).pages:
        w.add_page(page)
    w.add_attachment("factur-x.xml", cii(client, party, doc))
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def document(client: Client, party: Party, doc: DocSpec) -> tuple[str, bytes]:
    """(file name, bytes) for a document spec."""
    stem = (doc.number or "beleg").replace("/", "-")
    if doc.format == "xrechnung-ubl":
        return f"{stem}.xml", ubl(client, party, doc)
    if doc.format == "xrechnung-cii":
        return f"{stem}.xml", cii(client, party, doc)
    if doc.format == "zugferd":
        return f"{stem}.pdf", zugferd(client, party, doc)
    _, _, gross = totals(doc)
    if gross <= 25000 and doc.direction == "in" and not doc.missing and party.role != "customer" and doc.layout == 0:
        return f"{stem}.pdf", pdf_receipt(client, party, doc)
    return f"{stem}.pdf", pdf_invoice(client, party, doc)


# --- bank statements -----------------------------------------------------------------------------

BANK_CODES = {
    "lastschrift": "PMNT+RDDT+ESDD",
    "ueberweisung": "PMNT+ICDT+ESCT",
    "karte": "PMNT+CCRD+POSD",
    "gutschrift": "PMNT+RCDT+ESCT",
}


def camt053(client: Client, period: str, events: list[Event], opening: int) -> tuple[bytes, int]:
    pays = [e for e in events if e.kind == "payment"]
    total = sum(cents(e.amount) for e in pays)
    closing = opening + total
    y, m = int(period[:4]), int(period[5:7])
    start = date(y, m, 1)
    end = date(y + (m // 12), m % 12 + 1, 1)
    entries = []
    for i, e in enumerate(pays, start=1):
        p = client.party(e.party)
        amt = cents(e.amount)
        ind = "CRDT" if amt > 0 else "DBIT"
        role = "Dbtr" if amt > 0 else "Cdtr"
        on = (e.on or start).isoformat()
        name = p.name
        acct = f"<{role}Acct><Id><IBAN>{p.iban}</IBAN></Id></{role}Acct>" if p.iban else ""
        mandate = f"<MndtId>M{zlib.crc32(p.key.encode()) % 10**8:08d}</MndtId>" if e.method == "lastschrift" else ""
        parties = (
            f"<RltdPties><{role}><Pty><Nm>{_x(name)}</Nm></Pty></{role}>{acct}</RltdPties>"
            if not p.key.startswith("bank")
            else ""
        )
        info = f"<AddtlNtryInf>{_x(name)}</AddtlNtryInf>" if p.key.startswith("bank") else ""
        entries.append(
            f'<Ntry><NtryRef>{i}</NtryRef><Amt Ccy="EUR">{_amt(abs(amt))}</Amt><CdtDbtInd>{ind}</CdtDbtInd><Sts><Cd>BOOK</Cd></Sts>'
            f"<BookgDt><Dt>{on}</Dt></BookgDt><ValDt><Dt>{on}</Dt></ValDt><AcctSvcrRef>{client.mandant_nr}{period.replace('-', '')}{i:04d}</AcctSvcrRef>"
            f"<BkTxCd><Prtry><Cd>{BANK_CODES.get(e.method, 'PMNT')}</Cd><Issr>DK</Issr></Prtry></BkTxCd>"
            f"<NtryDtls><TxDtls><Refs><EndToEndId>{'NOTPROVIDED' if e.method == 'karte' else _x(e.id)}</EndToEndId>{mandate}</Refs>{parties}"
            f"<RmtInf><Ustrd>{_x(e.reference[:140])}</Ustrd></RmtInf></TxDtls></NtryDtls>{info}</Ntry>"
        )
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.08"><BkToCstmrStmt>'
        f"<GrpHdr><MsgId>{client.mandant_nr}-{period}</MsgId><CreDtTm>{end.isoformat()}T06:00:00</CreDtTm></GrpHdr>"
        f"<Stmt><Id>{client.mandant_nr}-{period}</Id><ElctrncSeqNb>{m}</ElctrncSeqNb><CreDtTm>{end.isoformat()}T06:00:00</CreDtTm>"
        f"<FrToDt><FrDtTm>{start.isoformat()}T00:00:00</FrDtTm><ToDtTm>{date.fromordinal(end.toordinal() - 1).isoformat()}T23:59:59</ToDtTm></FrToDt>"
        f"<Acct><Id><IBAN>{client.iban}</IBAN></Id><Ccy>EUR</Ccy></Acct>"
        f'<Bal><Tp><CdOrPrtry><Cd>OPBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">{_amt(abs(opening))}</Amt><CdtDbtInd>{"CRDT" if opening >= 0 else "DBIT"}</CdtDbtInd><Dt><Dt>{start.isoformat()}</Dt></Dt></Bal>'
        f'<Bal><Tp><CdOrPrtry><Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">{_amt(abs(closing))}</Amt><CdtDbtInd>{"CRDT" if closing >= 0 else "DBIT"}</CdtDbtInd><Dt><Dt>{date.fromordinal(end.toordinal() - 1).isoformat()}</Dt></Dt></Bal>'
        + "".join(entries)
        + "</Stmt></BkToCstmrStmt></Document>"
    )
    return xml.encode("utf-8"), closing


# --- DATEV history and the firm package ------------------------------------------------------------


def extf_history(
    firm: Firm, client: Client, rows: list[tuple[date, TLine, str, str]], date_from: date, date_to: date
) -> bytes:
    """`rows`: (date, line, Buchungstext, Belegfeld 1) as the firm booked them."""
    ch = firm.chart
    system_accounts = {system(ch, k) for k in ("bank", "cash", "transit", "suspense")}

    def plain(a: int) -> bool:
        return a in system_accounts or 10000 <= a <= 99999

    out = []
    for on, ln, text, ref in rows:
        if not plain(ln.debit) and plain(ln.credit):
            konto, gegen, sh = ln.credit, ln.debit, "H"
        else:
            konto, gegen, sh = ln.debit, ln.credit, "S"
        out.append(ExtfBooking(ln.amount, sh, konto, gegen, _bu(ch, gegen, ln.tax), on, ref, text))
    fy = date(date_from.year, 1, 1)
    return write_buchungsstapel(
        out,
        berater=firm.berater_nr,
        mandant=client.mandant_nr,
        fiscal_year_start=fy,
        length=4,
        date_from=date_from,
        date_to=date_to,
        label="Buchungen Vorjahr",
        chart_code=ch[-2:],
        locked=True,
        created=datetime(2026, 7, 1, 8, 0, 0),
    )


def _bu(chart: str, account: int, tax: str) -> str:
    from kanzlei_sim.truth import _chart

    d = _chart(chart)
    for a in d["accounts"]:
        if int(str(a["account"])) == account and a.get("auto"):
            return ""
    return str(d["bu_keys"].get(tax, ""))


def extf_master(firm: Firm, client: Client) -> bytes:
    recs = [
        MasterRecord(p.account, p.name, p.vat_id, p.country, p.street, p.postcode, p.city, p.tax_no, p.iban)
        for p in client.parties
        if p.account
    ]
    return write_stammdaten(
        recs,
        berater=firm.berater_nr,
        mandant=client.mandant_nr,
        fiscal_year_start=date(2025, 1, 1),
        length=4,
        created=datetime(2026, 7, 1, 8, 0, 0),
    )


def firm_json(firm: Firm) -> dict[str, Any]:
    return {
        "firm": {
            "id": firm.id,
            "name": firm.name,
            "city": firm.city,
            "chart": firm.chart,
            "berater_nr": firm.berater_nr,
            "llm_agreement_on": firm.llm_agreement_on.isoformat() if firm.llm_agreement_on else None,
        },
        "staff": firm.staff,
        "clients": [
            {
                "id": c.id,
                "mandant_nr": c.mandant_nr,
                "name": c.name,
                "legal_form": c.legal_form,
                "industry": c.industry,
                "booking_method": c.booking_method,
                "vat_regime": c.vat_regime,
                "vat_period": c.vat_period,
                "dauerfrist": c.dauerfrist,
                "vat_id": c.vat_id,
                "own_ibans": [c.iban],
                "contact_name": c.contact_name,
                "contact_email": c.contact_email,
                "assigned": c.assigned,
            }
            for c in firm.clients
        ],
    }


def write_package(firm: Firm, root: Path, history: dict[str, bytes], master: dict[str, bytes]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "firm.json").write_text(json.dumps(firm_json(firm), ensure_ascii=False, indent=2), encoding="utf-8")
    for c in firm.clients:
        d = root / "clients" / c.id
        d.mkdir(parents=True, exist_ok=True)
        if c.id in master:
            (d / "EXTF_Stammdaten.csv").write_bytes(master[c.id])
        if c.id in history:
            (d / "EXTF_Buchungsstapel_Historie.csv").write_bytes(history[c.id])
