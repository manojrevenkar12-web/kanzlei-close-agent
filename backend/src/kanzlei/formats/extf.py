"""DATEV-Format (EXTF): Buchungsstapel (category 21) and Debitoren/Kreditoren (category 16).

Written the way DATEV imports it: semicolons, CR/LF, text in double quotes with inner quotes
doubled, decimal comma, Belegdatum as TTMM, Windows-1252. Only the leading columns that carry
data are written; DATEV treats the rest as empty. The reader maps columns by their header name,
so exports from other tools with more columns read the same way.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime

from kanzlei.domain.money import fmt_datev, parse_amount
from kanzlei.formats.xml import FormatError

BOOKING_COLUMNS = (
    "Umsatz (ohne Soll/Haben-Kz)",
    "Soll/Haben-Kennzeichen",
    "WKZ Umsatz",
    "Kurs",
    "Basis-Umsatz",
    "WKZ Basis-Umsatz",
    "Konto",
    "Gegenkonto (ohne BU-Schlüssel)",
    "BU-Schlüssel",
    "Belegdatum",
    "Belegfeld 1",
    "Belegfeld 2",
    "Skonto",
    "Buchungstext",
    "Postensperre",
    "Diverse Adressnummer",
    "Geschäftspartnerbank",
    "Sachverhalt",
    "Zinssperre",
    "Beleglink",
)
MASTER_COLUMNS = (
    "Konto",
    "Name (Adressatentyp Unternehmen)",
    "Adressatentyp",
    "Kurzbezeichnung",
    "EU-Land",
    "EU-UStID",
    "Straße",
    "Postleitzahl",
    "Ort",
    "Land",
    "Steuernummer",
    "IBAN 1",
)
_BELEGFELD = re.compile(r"[^A-Z0-9$&%*+\-/]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass(frozen=True)
class ExtfBooking:
    amount_cents: int
    sh: str  # "S": Konto is debited, "H": Konto is credited
    konto: int
    gegenkonto: int
    bu: str
    belegdatum: date
    belegfeld1: str = ""
    buchungstext: str = ""
    beleglink: str = ""

    @property
    def debit(self) -> int:
        return self.konto if self.sh == "S" else self.gegenkonto

    @property
    def credit(self) -> int:
        return self.gegenkonto if self.sh == "S" else self.konto


@dataclass(frozen=True)
class MasterRecord:
    account: int
    name: str
    vat_id: str | None = None
    country: str | None = None
    street: str = ""
    postcode: str = ""
    city: str = ""
    tax_no: str | None = None
    iban: str | None = None


@dataclass
class Header:
    category: int
    format_name: str
    berater: int
    mandant: int
    fiscal_year_start: date
    account_length: int
    date_from: date | None = None
    date_to: date | None = None
    label: str = ""
    locked: bool = False
    chart: str = ""
    extra: dict[str, str] = field(default_factory=dict)


def _q(s: str) -> str:
    return '"' + _CONTROL.sub(" ", s).replace('"', '""') + '"'


def belegfeld(s: str) -> str:
    return _BELEGFELD.sub("", s.upper())[:36]


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def _header_line(
    category: int,
    name: str,
    version: int,
    *,
    berater: int,
    mandant: int,
    fiscal_year_start: date,
    length: int,
    created: datetime,
    date_from: date | None = None,
    date_to: date | None = None,
    label: str = "",
    locked: bool = False,
    chart: str = "",
) -> str:
    fields = [
        _q("EXTF"),
        "700",
        str(category),
        _q(name),
        str(version),
        created.strftime("%Y%m%d%H%M%S") + f"{created.microsecond // 1000:03d}",
        "",
        _q("RE"),
        _q(""),
        _q(""),
        str(berater),
        str(mandant),
        _ymd(fiscal_year_start),
        str(length),
        _ymd(date_from) if date_from else "",
        _ymd(date_to) if date_to else "",
        _q(label[:30]),
        _q(""),
        "1" if category == 21 else "",
        "0" if category == 21 else "",
        ("1" if locked else "0") if category == 21 else "",
        _q("EUR") if category == 21 else _q(""),
        "",
        _q(""),
        "",
        "",
        _q(chart),
        "",
        "",
        _q(""),
        _q(""),
    ]
    return ";".join(fields)


def write_buchungsstapel(
    bookings: list[ExtfBooking],
    *,
    berater: int,
    mandant: int,
    fiscal_year_start: date,
    length: int,
    date_from: date,
    date_to: date,
    label: str,
    chart_code: str,
    locked: bool,
    created: datetime | None = None,
) -> bytes:
    """A DATEV Buchungsstapel. `chart_code` is '03' or '04'; `locked` sets Festschreibung."""
    for b in bookings:
        if b.amount_cents <= 0:
            raise ValueError("DATEV amounts are positive; the S/H flag carries the direction")
        if not date_from <= b.belegdatum <= date_to:
            raise ValueError(f"Belegdatum {b.belegdatum} outside the batch {date_from}..{date_to}")
    lines = [
        _header_line(
            21,
            "Buchungsstapel",
            13,
            berater=berater,
            mandant=mandant,
            fiscal_year_start=fiscal_year_start,
            length=length,
            created=created or datetime.now(),
            date_from=date_from,
            date_to=date_to,
            label=label,
            locked=locked,
            chart=chart_code,
        ),
        ";".join(BOOKING_COLUMNS),
    ]
    for b in bookings:
        row = [
            fmt_datev(b.amount_cents),
            _q(b.sh),
            _q("EUR"),
            "",
            "",
            _q(""),
            str(b.konto),
            str(b.gegenkonto),
            _q(b.bu),
            b.belegdatum.strftime("%d%m"),
            _q(belegfeld(b.belegfeld1)),
            _q(""),
            "",
            _q(b.buchungstext[:60]),
            "",
            _q(""),
            "",
            "",
            "",
            _q(b.beleglink[:210]),
        ]
        lines.append(";".join(row))
    return ("\r\n".join(lines) + "\r\n").encode("cp1252", errors="replace")


def write_stammdaten(
    records: list[MasterRecord],
    *,
    berater: int,
    mandant: int,
    fiscal_year_start: date,
    length: int,
    created: datetime | None = None,
) -> bytes:
    lines = [
        _header_line(
            16,
            "Debitoren/Kreditoren",
            5,
            berater=berater,
            mandant=mandant,
            fiscal_year_start=fiscal_year_start,
            length=length,
            created=created or datetime.now(),
        ),
        ";".join(MASTER_COLUMNS),
    ]
    for r in records:
        lines.append(
            ";".join(
                [
                    str(r.account),
                    _q(r.name[:50]),
                    _q("2"),
                    _q(r.name[:15]),
                    _q((r.country or "") if r.vat_id else ""),
                    _q(r.vat_id[2:] if r.vat_id else ""),
                    _q(r.street),
                    _q(r.postcode),
                    _q(r.city),
                    _q(r.country or ""),
                    _q(r.tax_no or ""),
                    _q(r.iban or ""),
                ]
            )
        )
    return ("\r\n".join(lines) + "\r\n").encode("cp1252", errors="replace")


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252")


def _rows(data: bytes) -> tuple[list[str], list[str], list[list[str]]]:
    text = _decode(data)
    rows = list(csv.reader(io.StringIO(text), delimiter=";", quotechar='"'))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if len(rows) < 2 or not rows[0] or rows[0][0] not in ("EXTF", "DTVF"):
        raise FormatError("not a DATEV-Format file (first field must be EXTF)")
    return rows[0], rows[1], rows[2:]


def _date8(s: str) -> date | None:
    s = s.strip()
    return date(int(s[:4]), int(s[4:6]), int(s[6:8])) if len(s) == 8 and s.isdigit() else None


def read_header(fields: list[str]) -> Header:
    def at(i: int) -> str:
        return fields[i].strip() if i < len(fields) else ""

    try:
        h = Header(
            category=int(at(2)),
            format_name=at(3),
            berater=int(at(10) or 0),
            mandant=int(at(11) or 0),
            fiscal_year_start=_date8(at(12)) or date(1900, 1, 1),
            account_length=int(at(13) or 4),
            date_from=_date8(at(14)),
            date_to=_date8(at(15)),
            label=at(16),
            locked=at(20) == "1",
            chart=at(26),
        )
    except ValueError as e:
        raise FormatError(f"DATEV header unreadable: {e}") from e
    return h


def read_buchungsstapel(data: bytes) -> tuple[Header, list[ExtfBooking]]:
    head, cols, rows = _rows(data)
    header = read_header(head)
    if header.category != 21:
        raise FormatError(f"expected a Buchungsstapel (21), got category {header.category}")
    idx = {name: i for i, name in enumerate(cols)}
    need = (
        "Umsatz (ohne Soll/Haben-Kz)",
        "Soll/Haben-Kennzeichen",
        "Konto",
        "Gegenkonto (ohne BU-Schlüssel)",
        "Belegdatum",
    )
    missing = [c for c in need if c not in idx]
    if missing:
        raise FormatError(f"Buchungsstapel without columns: {', '.join(missing)}")

    def get(row: list[str], name: str) -> str:
        i = idx.get(name)
        return row[i].strip() if i is not None and i < len(row) else ""

    ref_from = header.date_from or header.fiscal_year_start
    ref_to = header.date_to or ref_from
    out: list[ExtfBooking] = []
    for n, row in enumerate(rows, start=3):
        try:
            amount = parse_amount(get(row, "Umsatz (ohne Soll/Haben-Kz)"))
            sh = get(row, "Soll/Haben-Kennzeichen").upper()
            if sh not in ("S", "H"):
                raise ValueError(f"S/H flag {sh!r}")
            ttmm = get(row, "Belegdatum").zfill(4)
            day, month = int(ttmm[:2]), int(ttmm[2:4])
            year = ref_from.year if (month, day) >= (ref_from.month, ref_from.day) else ref_to.year
            out.append(
                ExtfBooking(
                    amount_cents=amount,
                    sh=sh,
                    konto=int(get(row, "Konto")),
                    gegenkonto=int(get(row, "Gegenkonto (ohne BU-Schlüssel)")),
                    bu=get(row, "BU-Schlüssel"),
                    belegdatum=date(year, month, day),
                    belegfeld1=get(row, "Belegfeld 1"),
                    buchungstext=get(row, "Buchungstext"),
                    beleglink=get(row, "Beleglink"),
                )
            )
        except ValueError as e:
            raise FormatError(f"line {n}: {e}") from e
    return header, out


def read_stammdaten(data: bytes) -> tuple[Header, list[MasterRecord]]:
    head, cols, rows = _rows(data)
    header = read_header(head)
    if header.category != 16:
        raise FormatError(f"expected Debitoren/Kreditoren (16), got category {header.category}")
    idx = {name: i for i, name in enumerate(cols)}

    def get(row: list[str], *names: str) -> str:
        for name in names:
            i = idx.get(name)
            if i is not None and i < len(row) and row[i].strip():
                return row[i].strip()
        return ""

    out = []
    for row in rows:
        acct = get(row, "Konto")
        if not acct:
            continue
        land = get(row, "EU-Land")
        ust = get(row, "EU-UStID")
        out.append(
            MasterRecord(
                account=int(acct),
                name=get(
                    row, "Name (Adressatentyp Unternehmen)", "Name (Adressatentyp keine Angabe)", "Kurzbezeichnung"
                ),
                vat_id=(land + ust) if ust else None,
                country=get(row, "Land") or land or None,
                street=get(row, "Straße"),
                postcode=get(row, "Postleitzahl"),
                city=get(row, "Ort"),
                tax_no=get(row, "Steuernummer") or None,
                iban=get(row, "IBAN 1", "IBAN-Nr. 1", "IBAN") or None,
            )
        )
    return header, out
