"""Tax rules, the VAT return, matching and memory: the parts that decide."""

from __future__ import annotations

from datetime import date

from kanzlei.config import close_config, tax_config
from kanzlei.domain.chart import chart
from kanzlei.domain.models import ClientProfile, Line
from kanzlei.domain.tax import decide
from kanzlei.domain.ustva import compute
from kanzlei.engine.matching import Doc, Tx, match
from kanzlei.engine.memory import ClientMemory, Use
from kanzlei.formats.invoice import Invoice, InvoiceLine, Party, TaxBreakdown

TAX = tax_config()


def client(regime: str = "soll") -> ClientProfile:
    return ClientProfile(
        "c1", "f1", "Test GmbH", "SKR03", "direkt", regime, "monat", False, ("DE89370400440532013000",)
    )


def invoice(
    *taxes: tuple[str, int, int, int], seller_country: str = "DE", lines: list[InvoiceLine] | None = None, **kw: object
) -> Invoice:
    inv = Invoice(source="xrechnung-ubl", invoice_no="R1", issue_date=date(2026, 9, 3), delivery_from=date(2026, 9, 1))
    inv.seller = Party(
        "Lieferant GmbH", "Weg 1", "12345", "Kassel", seller_country, vat_id=f"{seller_country}123456789"
    )
    inv.buyer = Party("Test GmbH", "Str 2", "34117", "Kassel", "DE")
    inv.taxes = [TaxBreakdown(c, r, b, t) for c, r, b, t in taxes]
    inv.lines = lines or [InvoiceLine("Ware", sum(t[2] for t in taxes), taxes[0][1], taxes[0][0])]
    inv.net_cents = sum(t[2] for t in taxes)
    inv.tax_cents = sum(t[3] for t in taxes)
    inv.gross_cents = inv.net_cents + inv.tax_cents
    for k, v in kw.items():
        setattr(inv, k, v)
    return inv


def codes(d: object) -> list[tuple[str, int, str | None]]:
    return [(p.tax, p.gross_cents, p.role) for p in d.portions]  # type: ignore[attr-defined]


def test_standard_and_mixed_rates() -> None:
    d = decide(
        family="office_supplies", amount_cents=11900, inv=invoice(("S", 19, 10000, 1900)), client=client(), cfg=TAX
    )
    assert codes(d) == [("V19", 11900, None)] and not d.flags
    hotel = invoice(("S", 7, 10000, 700), ("S", 19, 2000, 380))
    d = decide(family="travel_lodging", amount_cents=13080, inv=hotel, client=client(), cfg=TAX)
    assert sorted(codes(d)) == [("V19", 2380, None), ("V7", 10700, None)]


def test_reverse_charge_cases() -> None:
    eu = invoice(("AE", 0, 5000, 0), seller_country="IE", notes=["Reverse charge"])
    assert codes(decide(family="software", amount_cents=5000, inv=eu, client=client(), cfg=TAX)) == [
        ("RC_EU19", 5000, None)
    ]
    bau = invoice(("AE", 0, 300000, 0), seller_country="DE")
    assert codes(decide(family="subcontractor", amount_cents=300000, inv=bau, client=client(), cfg=TAX)) == [
        ("RC_BAU19", 300000, None)
    ]
    us = invoice(("O", 0, 4276, 0), seller_country="US")
    assert codes(decide(family="software", amount_cents=4276, inv=us, client=client(), cfg=TAX))[0][0] == "RC_DRITT19"
    goods = invoice(("K", 0, 100000, 0), seller_country="PL")
    assert codes(decide(family="goods", amount_cents=100000, inv=goods, client=client(), cfg=TAX)) == [
        ("IGE19", 100000, None)
    ]


def test_revenue_to_eu_needs_the_customers_vat_id() -> None:
    out = invoice(("AE", 0, 400000, 0))
    out.buyer = Party("Brightwave B.V.", country="NL", vat_id="NL123456789B01")
    assert codes(decide(family="revenue", amount_cents=400000, inv=out, client=client(), cfg=TAX)) == [
        ("EU_SVC", 400000, None)
    ]
    out.buyer = Party("Unbekannt")
    assert "unsupported_tax" in decide(family="revenue", amount_cents=400000, inv=out, client=client(), cfg=TAX).flags


def test_kleinunternehmer_and_exempt_clients() -> None:
    inv = invoice(("S", 19, 10000, 1900))
    assert codes(decide(family="goods", amount_cents=11900, inv=inv, client=client("klein"), cfg=TAX)) == [
        ("NONE", 11900, None)
    ]
    assert codes(decide(family="goods", amount_cents=11900, inv=inv, client=client("befreit"), cfg=TAX)) == [
        ("NONE", 11900, None)
    ]
    assert codes(decide(family="revenue", amount_cents=50000, inv=None, client=client("befreit"), cfg=TAX)) == [
        ("FREI", 50000, None)
    ]


def test_meals_split_keeps_full_input_vat() -> None:
    inv = invoice(("S", 19, 10000, 1900), notes=["Anlass: Projekt; Teilnehmer: A, B"])
    d = decide(family="meals", amount_cents=11900, inv=inv, client=client(), cfg=TAX)
    assert codes(d) == [("V19", 8330, None), ("V19", 3570, "nondeductible")]
    assert "meals_details" not in d.flags
    d2 = decide(family="meals", amount_cents=11900, inv=invoice(("S", 19, 10000, 1900)), client=client(), cfg=TAX)
    assert "meals_details" in d2.flags


def test_equipment_by_unit_price() -> None:
    lines = [
        InvoiceLine("Kabel", 3000, 19, "S"),
        InvoiceLine("Monitor", 29000, 19, "S"),
        InvoiceLine("Notebook", 129900, 19, "S"),
    ]
    inv = invoice(("S", 19, 161900, 30761), lines=lines)
    d = decide(family="equipment", amount_cents=192661, inv=inv, client=client(), cfg=TAX)
    roles = {r for _, _, r in codes(d)}
    assert roles == {"small", "gwg", "asset"} and "asset_review" in d.flags
    assert sum(g for _, g, _ in codes(d)) == 192661
    # Two monitors at 500 net each are two low-value assets, not one asset of 1,000.
    two = invoice(("S", 19, 100000, 19000), lines=[InvoiceLine("Monitor", 100000, 19, "S", quantity=2)])
    assert {
        r for _, _, r in codes(decide(family="equipment", amount_cents=119000, inv=two, client=client(), cfg=TAX))
    } == {"gwg"}
    # A Kleinunternehmer cannot deduct VAT, so the limit applies to the gross price: 700 net = 833 gross > 800.
    k = invoice(("S", 19, 70000, 13300), lines=[InvoiceLine("Kamera", 70000, 19, "S")])
    assert {
        r for _, _, r in codes(decide(family="equipment", amount_cents=83300, inv=k, client=client("klein"), cfg=TAX))
    } == {"asset"}


def test_no_deduction_without_a_proper_invoice() -> None:
    bad = invoice(("S", 19, 50000, 9500))
    bad.delivery_from = None
    d = decide(family="goods", amount_cents=59500, inv=bad, client=client(), cfg=TAX)
    assert "invoice_incomplete" in d.flags
    d = decide(
        family="goods", amount_cents=59500, inv=bad, client=client(), cfg=TAX, has_receipt_answer="not_available"
    )
    assert codes(d) == [("NONE", 59500, None)] and not d.flags
    small = invoice(("S", 19, 10000, 1900))
    small.buyer = Party()
    small.delivery_from = None
    assert (
        "invoice_incomplete" not in decide(family="fuel", amount_cents=11900, inv=small, client=client(), cfg=TAX).flags
    )  # Kleinbetrag


def test_missing_receipts_and_standing_contracts() -> None:
    assert (
        "missing_receipt"
        in decide(family="office_supplies", amount_cents=5000, inv=None, client=client(), cfg=TAX).flags
    )
    d = decide(family="rent", amount_cents=150000, inv=None, client=client(), cfg=TAX, memory_tax="V19", recurring=True)
    assert codes(d) == [("V19", 150000, None)] and not d.flags
    d = decide(
        family="office_supplies", amount_cents=5000, inv=None, client=client(), cfg=TAX, has_receipt_answer="no_receipt"
    )
    assert codes(d) == [("NONE", 5000, None)] and not d.flags
    assert not decide(family="insurance", amount_cents=41000, inv=None, client=client(), cfg=TAX).flags


def test_cash_discount_and_partial_payment() -> None:
    inv = invoice(("S", 19, 100000, 19000))
    d = decide(family="goods", amount_cents=116620, inv=inv, client=client(), cfg=TAX)
    assert d.skonto_cents == 2380 and not d.flags and codes(d) == [("V19", 116620, None)]
    assert "partial_payment" in decide(family="goods", amount_cents=60000, inv=inv, client=client(), cfg=TAX).flags


def test_vat_return() -> None:
    c = chart("SKR03")
    sysacc = set(c.system.values())

    def is_tax(a: int) -> bool:
        return a not in sysacc and not c.is_personal(a)

    lines = [
        Line(date(2026, 9, 1), 119000, 1200, 8400, "U19", "Verkauf"),
        Line(date(2026, 9, 2), 11900, 4930, 1200, "V19", "Büro"),
        Line(date(2026, 9, 3), 1190, 1200, 4930, "V19", "Gutschrift Büro"),
        Line(date(2026, 9, 4), 10000, 3123, 1200, "RC_EU19", "Cloud"),
        Line(date(2026, 9, 5), 50000, 3425, 70001, "IGE19", "Ware PL"),
        Line(date(2026, 9, 6), 400000, 1200, 8338, "EU_SVC", "Beratung NL"),
        Line(date(2026, 9, 7), 5000, 1800, 1200, "NONE", "Privat"),
    ]
    rows = compute(lines, TAX, is_tax)
    get = {k: (r.base_cents, r.tax_cents) for k, r in rows.items()}
    assert get["81"] == (100000, 19000)
    assert get["66"] == (0, 1900 - 190)  # the refund reduces input VAT
    assert get["46"] == (10000, 0) and get["47"] == (0, 1900) and get["67"] == (0, 1900)
    assert get["89"] == (50000, 9500) and get["61"] == (0, 9500)
    assert get["21"] == (400000, 0)
    assert get["83"] == (0, 19000 + 1900 + 9500 - 1710 - 1900 - 9500)
    assert rows["81"].base_euros == 1000


def test_matching() -> None:
    cfg, tax = close_config(), TAX

    def doc(
        i: int,
        gross: int,
        no: str,
        seller: str = "Lieferant GmbH",
        iban: str | None = None,
        issued: date = date(2026, 9, 1),
    ) -> Doc:
        inv = invoice(("S", 19, round(gross / 1.19), gross - round(gross / 1.19)))
        inv.gross_cents, inv.invoice_no, inv.issue_date, inv.seller_iban = gross, no, issued, iban
        inv.seller = Party(seller)
        return Doc(i, "in", inv)

    docs = [
        doc(1, 11900, "A-1"),
        doc(2, 11900, "A-2"),
        doc(3, 59500, "B-9", "Großhandel", "DE89370400440532013000"),
        doc(4, 20000, "C-1", "Kabel AG"),
        doc(5, 30000, "C-2", "Kabel AG"),
    ]
    txs = [
        Tx(10, date(2026, 9, 10), -11900, "Lieferant GmbH", None, "RE A-2"),
        Tx(11, date(2026, 9, 11), -58310, "Großhandel", "DE89370400440532013000", "B-9 abzgl. 2% Skonto"),
        Tx(12, date(2026, 9, 12), -50000, "Kabel AG", None, "Rechnungen C-1 C-2"),
        Tx(13, date(2026, 9, 13), -11900, "Lieferant GmbH", None, "Zahlung"),
    ]
    m = match(txs, docs, cfg, tax)
    assert m[10].doc_ids == [2]
    assert m[11].doc_ids == [3] and m[11].skonto
    assert sorted(m[12].doc_ids) == [4, 5]
    assert m[13].doc_ids == [1]


def test_memory_by_iban_and_name_and_direction() -> None:
    mem = ClientMemory(close_config())
    for k in range(6):
        mem.add(iban=None, name="Vogel Hausverwaltung GmbH", use=Use("rent", "V19", 125000, date(2026, 1 + k, 2)))
    mem.add(
        iban="DE89370400440532013000",
        name="Vogel Hausverwaltung GmbH",
        use=Use("rent", "V19", 125000, date(2026, 7, 2)),
    )
    hit = mem.lookup("DE89370400440532013000", "Vogel Hausverwaltung")
    assert hit and hit.dominant and hit.uses == 7 and hit.recurring
    mem.add(iban=None, name="Trattoria Da Paolo", use=Use("revenue", "U19", 50000, date(2026, 5, 1), money_in=True))
    mem.add(iban=None, name="Trattoria Da Paolo", use=Use("revenue", "U19", 70000, date(2026, 6, 1), money_in=True))
    assert (
        mem.lookup(None, "Trattoria Da Paolo", money_in=False) is None
        or not mem.lookup(None, "Trattoria Da Paolo", money_in=False).uses
    )  # type: ignore[union-attr]
    assert mem.lookup(None, "TRATTORIA DA PAOLO", money_in=True).family == "revenue"  # type: ignore[union-attr]
