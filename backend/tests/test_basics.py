"""Money, text, chart: the small pieces everything rests on."""

from __future__ import annotations

import pytest

from kanzlei.domain.chart import chart
from kanzlei.domain.money import fmt_datev, fmt_de, parse_amount, round_half_up, share, split_gross, tax_on_net
from kanzlei.domain.text import find_invoice_numbers, iban_valid, name_similarity, normalize_name, redact
from kanzlei_sim.ids import iban


@pytest.mark.parametrize(
    ("text", "cents"),
    [("1.234,56", 123456), ("1234.56", 123456), ("-12,00", -1200), ("0,5", 50), ("1.000", 100000), ("17 €", 1700)],
)
def test_parse_amount(text: str, cents: int) -> None:
    assert parse_amount(text) == cents


@pytest.mark.parametrize("text", ["", "abc", "9,999", "1,2,3"])
def test_parse_amount_rejects(text: str) -> None:
    with pytest.raises(ValueError):
        parse_amount(text)


def test_formats() -> None:
    assert fmt_de(123456) == "1.234,56 €"
    assert fmt_de(-5, currency=False) == "-0,05"
    assert fmt_datev(-123456) == "1234,56"


def test_rounding_and_vat() -> None:
    assert round_half_up(5, 2) == 3 and round_half_up(-5, 2) == -3
    assert split_gross(11900, 19) == (10000, 1900)
    assert split_gross(1, 19) == (1, 0)
    assert tax_on_net(10050, 19) == 1910  # 19.095 -> 19.10
    assert share(1000, 0.7) == 700 and share(1001, 0.7) == 701  # 700.7 -> 701


def test_iban() -> None:
    assert iban_valid("DE89 3704 0044 0532 0130 00")
    assert not iban_valid("DE89 3704 0044 0532 0130 01")
    for c in ("DE", "AT", "NL", "IE", "PL"):
        assert iban_valid(iban(c, "seed"))


def test_names() -> None:
    assert normalize_name("Telekom Deutschland GmbH") == "telekom deutschland"
    assert normalize_name("Müller & Söhne GmbH & Co. KG") == "müller söhne"
    assert name_similarity("Stadtwerke Leipzig GmbH", "STADTWERKE LEIPZIG") == 1.0
    assert name_similarity("Hotel Kranich", "Gasthaus Zum Anker") < 0.5


def test_invoice_numbers_in_reference() -> None:
    assert "2026-0412" in find_invoice_numbers("RE 2026-0412 abzgl. Skonto")
    assert "RG55192" in find_invoice_numbers("Rechnung RG55192 Kundennr 88123")


def test_redaction() -> None:
    text = (
        "Zahlung an DE89370400440532013000, Rückfragen an max@firma.example oder +49 30 1234567, USt-IdNr DE123456789"
    )
    out = redact(text)
    assert (
        "DE89370400440532013000" not in out
        and "max@firma.example" not in out
        and "1234567" not in out
        and "DE123456789" not in out
    )


def test_chart_mapping_both_charts() -> None:
    for name, expect in (
        ("SKR03", {"tel": 4920, "rc_eu": 3123, "gwg": 480, "nd": 4654, "bank": 1200}),
        ("SKR04", {"tel": 6805, "rc_eu": 5923, "gwg": 670, "nd": 6644, "bank": 1800}),
    ):
        c = chart(name)
        assert c.account_for("telecom", "V19") == expect["tel"]
        assert c.account_for("software", "RC_EU19") == expect["rc_eu"]
        assert c.account_for("equipment", "V19", "gwg") == expect["gwg"]
        assert c.account_for("meals", "V19", "nondeductible") == expect["nd"]
        assert c.system["bank"] == expect["bank"]
        assert c.account_for("telecom", "IGE19") is None  # cannot be expressed: needs a person
        assert c.bu_key(expect["tel"], "V19") == "9"
        assert c.bu_key(c.account_for("revenue", "U19") or 0, "U19") == ""  # automatic account
    assert chart("SKR03").fmt(480) == "0480"
    assert chart("SKR03").tax_of(8400, "") == "U19"
    assert chart("SKR03").tax_of(4920, "8") == "V7"
