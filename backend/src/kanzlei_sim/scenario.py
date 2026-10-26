"""The scenario format: firms, clients, counterparties, past bookings and one month of events,
each event with the booking a careful accountant would make (the truth).

The development world (world.py) is generated in this format; blind sets are written in it by
hand (blind/WRITING_CASES.md). The renderer turns a scenario into the files a firm hands over:
DATEV history, bank statements, e-invoices and PDFs. The engine never sees the truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Party:
    key: str
    name: str
    role: str = "supplier"  # supplier | customer | other
    iban: str | None = None
    vat_id: str | None = None
    tax_no: str | None = None
    country: str = "DE"
    street: str = ""
    postcode: str = ""
    city: str = ""
    account: int | None = None  # Kreditor/Debitor number (OPOS clients)


@dataclass
class HistorySpec:
    """A counterparty's bookings over the past months (feeds the DATEV history)."""

    party: str
    family: str
    tax: str
    amount: float  # gross per booking, signed like the bank sees it (- out, + in)
    months: int = 12
    per_month: int = 1
    vary: float = 0.0  # relative spread of the amount
    text: str = ""  # Buchungstext; defaults to the party name


@dataclass
class DocLine:
    text: str
    net: float
    rate: int = 19
    category: str = "S"
    quantity: float = 1.0


@dataclass
class DocSpec:
    format: str  # xrechnung-ubl | xrechnung-cii | zugferd | pdf | none
    number: str = ""
    issue_date: date | None = None
    delivery_date: date | None = None
    lines: list[DocLine] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)  # Pflichtangaben left out on purpose
    arrives: str = "with_statement"  # with_statement | on_request | never
    notes: list[str] = field(default_factory=list)
    payment_terms: str = ""
    credit_note: bool = False
    layout: int = 0  # PDF layout variant
    direction: str = "in"  # in: received by the client; out: issued by the client


@dataclass
class Truth:
    family: str
    tax: str | None = None  # single tax code; None: derive from the document lines
    portions: list[dict[str, Any]] = field(default_factory=list)  # [{tax, gross}] for explicit splits
    note: str = ""


@dataclass
class Event:
    id: str
    kind: str  # payment | invoice (OPOS: an invoice booked on receipt)
    party: str
    amount: float = 0.0  # payments: signed bank amount
    on: date | None = None
    reference: str = ""
    method: str = "ueberweisung"  # ueberweisung | lastschrift | karte | gutschrift
    document: DocSpec | None = None
    settles: list[str] = field(default_factory=list)  # payment of OPOS invoice events
    truth: Truth | None = None
    says: dict[str, Any] = field(default_factory=dict)  # what the client answers, per question
    answers: bool = True  # does the client answer questions at all


@dataclass
class Client:
    id: str
    mandant_nr: int
    name: str
    legal_form: str
    industry: str
    booking_method: str
    vat_regime: str
    vat_period: str = "monat"
    dauerfrist: bool = False
    vat_id: str | None = None
    iban: str = ""
    street: str = ""
    postcode: str = ""
    city: str = ""
    contact_name: str = ""
    contact_email: str = ""
    assigned: list[str] = field(default_factory=list)
    parties: list[Party] = field(default_factory=list)
    history: list[HistorySpec] = field(default_factory=list)
    months: dict[str, list[Event]] = field(default_factory=dict)  # period -> events
    opening_cents: int = 2_500_000

    def party(self, key: str) -> Party:
        for p in self.parties:
            if p.key == key:
                return p
        raise KeyError(f"{self.id}: unknown party {key}")


@dataclass
class Firm:
    id: str
    name: str
    city: str
    chart: str
    berater_nr: int
    llm_agreement_on: date | None = None
    staff: list[dict[str, str]] = field(default_factory=list)
    clients: list[Client] = field(default_factory=list)


# --- YAML (blind sets) -------------------------------------------------------------------------


def _d(v: Any) -> date | None:
    if v is None or isinstance(v, date):
        return v
    return date.fromisoformat(str(v))


def load(path: Path) -> Firm:
    d = yaml.safe_load(path.read_text(encoding="utf-8"))
    f = d["firm"]
    firm = Firm(
        f["id"],
        f["name"],
        f.get("city", ""),
        f["chart"],
        int(f["berater_nr"]),
        _d(f.get("llm_agreement_on")),
        d.get("staff", []),
    )
    for c in d["clients"]:
        client = Client(
            id=c["id"],
            mandant_nr=int(c["mandant_nr"]),
            name=c["name"],
            legal_form=c.get("legal_form", ""),
            industry=c.get("industry", ""),
            booking_method=c["booking_method"],
            vat_regime=c["vat_regime"],
            vat_period=c.get("vat_period", "monat"),
            dauerfrist=bool(c.get("dauerfrist", False)),
            vat_id=c.get("vat_id"),
            iban=c.get("iban", ""),
            street=c.get("street", ""),
            postcode=str(c.get("postcode", "")),
            city=c.get("city", ""),
            contact_name=c.get("contact_name", ""),
            contact_email=c.get("contact_email", ""),
            assigned=list(c.get("assigned", [])),
        )
        for p in c.get("parties", []):
            client.parties.append(Party(**{k: (str(v) if k == "postcode" else v) for k, v in p.items()}))
        for h in c.get("history", []):
            client.history.append(HistorySpec(**h))
        for period, events in (c.get("months") or {}).items():
            evs = []
            for e in events:
                doc = None
                if e.get("document"):
                    ds = dict(e["document"])
                    ds["lines"] = [DocLine(**ln) for ln in ds.get("lines", [])]
                    ds["issue_date"] = _d(ds.get("issue_date"))
                    ds["delivery_date"] = _d(ds.get("delivery_date"))
                    doc = DocSpec(**ds)
                tr = Truth(**e["truth"]) if e.get("truth") else None
                evs.append(
                    Event(
                        id=str(e["id"]),
                        kind=e.get("kind", "payment"),
                        party=e["party"],
                        amount=float(e.get("amount", 0)),
                        on=_d(e.get("on")),
                        reference=e.get("reference", ""),
                        method=e.get("method", "ueberweisung"),
                        document=doc,
                        settles=list(e.get("settles", [])),
                        truth=tr,
                        says=dict(e.get("says") or {}),
                        answers=bool(e.get("answers", True)),
                    )
                )
            client.months[str(period)] = evs
        firm.clients.append(client)
    return firm


def cents(x: float) -> int:
    return round(x * 100)
