"""Readers and writers: bank statements, e-invoices, PDFs, DATEV."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from kanzlei.engine.close import Engine
from kanzlei.formats.camt import parse_camt053
from kanzlei.formats.einvoice import embedded_xml, parse_einvoice_xml
from kanzlei.formats.extf import (
    ExtfBooking,
    MasterRecord,
    read_buchungsstapel,
    read_stammdaten,
    write_buchungsstapel,
    write_stammdaten,
)
from kanzlei.formats.xml import FormatError
from kanzlei_sim import render
from kanzlei_sim.world import DEV


def _docs(world: list[Any]) -> list[tuple[Any, Any, Any]]:
    out = []
    for f in world:
        for c in f.clients:
            for p in DEV:
                for e in c.months[p]:
                    if e.document is not None and e.document.format != "none":
                        out.append((c, c.party(e.party), e.document))
    return out


def test_statement_reads_and_reconciles(world: list[Any]) -> None:
    c = world[0].clients[1]
    xml, closing = render.camt053(c, DEV[0], c.months[DEV[0]], 1_000_000)
    st = parse_camt053(xml)[0]
    pays = [e for e in c.months[DEV[0]] if e.kind == "payment"]
    assert len(st.entries) == len(pays)
    assert st.opening_cents + sum(e.amount_cents for e in st.entries) == st.closing_cents == closing
    assert st.iban == c.iban
    card = [e for e in st.entries if e.end_to_end_id is None]
    assert card and all(e.counterparty_iban is None for e in card)


def test_statement_that_does_not_add_up_is_rejected(world: list[Any]) -> None:
    c = world[0].clients[1]
    xml, _ = render.camt053(c, DEV[0], c.months[DEV[0]], 1_000_000)
    broken = xml.replace(
        b'<Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">', b'<Cd>CLBD</Cd></CdOrPrtry></Tp><Amt Ccy="EUR">1', 1
    )
    with pytest.raises(FormatError, match="balances differ"):
        parse_camt053(broken)


def test_xml_bombs_are_refused() -> None:
    bomb = b"""<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa"><!ENTITY b "&a;&a;&a;&a;&a;&a;">]><Invoice>&b;</Invoice>"""
    with pytest.raises(FormatError):
        parse_einvoice_xml(bomb)
    xxe = b"""<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><Invoice><ID>&e;</ID></Invoice>"""
    with pytest.raises(FormatError):
        parse_einvoice_xml(xxe)


def test_every_rendered_document_reads_back(world: list[Any]) -> None:
    """All formats and PDF layouts: invoice number, totals and the tax breakdown come back."""
    seen: dict[str, int] = {}
    for c, party, doc in _docs(world):
        name, data = render.document(c, party, doc)
        inv, fmt, _ = Engine.read_document(Engine.__new__(Engine), data, name)
        seen[fmt] = seen.get(fmt, 0) + 1
        _net, _tax, gross = render.totals(doc)
        assert inv.gross_cents == gross, (fmt, doc.number)
        if "invoice_no" not in doc.missing:
            assert inv.invoice_no == doc.number, (fmt, doc.number)
        want = sorted(
            (g["category"], g["rate"], g["base"], g["tax"]) for g in render.tax_groups(doc) if g["category"] == "S"
        )
        got = sorted((t.category, t.rate, t.base_cents, t.tax_cents) for t in inv.taxes if t.category == "S")
        assert got == want, (fmt, doc.number)
        if fmt != "pdf":
            assert not inv.issues, inv.issues
    assert {"xrechnung-ubl", "xrechnung-cii", "zugferd", "pdf"} <= set(seen)


def test_zugferd_carries_cii(world: list[Any]) -> None:
    c, party, doc = next(x for x in _docs(world) if x[2].format == "zugferd")
    _, data = render.document(c, party, doc)
    assert data[:4] == b"%PDF"
    assert b"CrossIndustryInvoice" in (embedded_xml(data) or b"")


def test_reverse_charge_and_buyer_vat_on_pdf(world: list[Any]) -> None:
    from kanzlei.formats.pdfinvoice import pdf_text, read_invoice_text

    for c, party, doc in _docs(world):
        if doc.format == "pdf" and doc.direction == "out" and any(ln.category == "AE" for ln in doc.lines):
            inv = read_invoice_text(pdf_text(render.document(c, party, doc)[1]))
            assert inv.buyer.vat_id == party.vat_id and inv.buyer.country == party.country
            assert any(t.category == "AE" for t in inv.taxes)
            return
    pytest.fail("no reverse-charge PDF in the world")


def test_extf_round_trip() -> None:
    rows = [
        ExtfBooking(11900, "H", 1200, 4930, "9", date(2026, 1, 5), "RE-2026/01", 'Bürobedarf "Schreiber"'),
        ExtfBooking(500000, "S", 1200, 8400, "", date(2025, 12, 30), "AR 7", "Kunde Ölmühle"),
    ]
    data = write_buchungsstapel(
        rows,
        berater=41230,
        mandant=10101,
        fiscal_year_start=date(2025, 1, 1),
        length=4,
        date_from=date(2025, 12, 1),
        date_to=date(2026, 1, 31),
        label="Test",
        chart_code="03",
        locked=True,
    )
    assert data.startswith(b'"EXTF";700;21;"Buchungsstapel";13;')
    assert b"\r\n" in data and "Ölmühle".encode("cp1252") in data
    header, back = read_buchungsstapel(data)
    assert header.chart == "03" and header.locked and header.mandant == 10101
    assert back[0].belegdatum == date(2026, 1, 5) and back[1].belegdatum == date(
        2025, 12, 30
    )  # TTMM across the year end
    assert back[0].buchungstext == 'Bürobedarf "Schreiber"' and back[0].belegfeld1 == "RE-2026/01"
    assert back[0].debit == 4930 and back[0].credit == 1200
    with pytest.raises(ValueError):
        write_buchungsstapel(
            [ExtfBooking(100, "S", 1200, 4930, "", date(2026, 3, 1))],
            berater=1,
            mandant=1,
            fiscal_year_start=date(2026, 1, 1),
            length=4,
            date_from=date(2026, 1, 1),
            date_to=date(2026, 1, 31),
            label="x",
            chart_code="03",
            locked=False,
        )


def test_master_data_round_trip() -> None:
    data = write_stammdaten(
        [MasterRecord(70001, "Kartonagen Łódź Sp. z o.o.", "PL1234567890", "PL", iban="PL61109010140000071219812874")],
        berater=1,
        mandant=2,
        fiscal_year_start=date(2026, 1, 1),
        length=4,
    )
    _, recs = read_stammdaten(data)
    assert (
        recs[0].account == 70001 and recs[0].vat_id == "PL1234567890" and recs[0].iban == "PL61109010140000071219812874"
    )


def test_not_datev_is_refused() -> None:
    with pytest.raises(FormatError):
        read_buchungsstapel(b"Konto;Betrag\r\n1200;5\r\n")
