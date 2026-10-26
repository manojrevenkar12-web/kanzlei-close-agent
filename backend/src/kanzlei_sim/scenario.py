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
    skonto: bool = False  # a payment settling invoices less 2 % cash discount


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
                        amount=float(e["amount"]) if isinstance(e.get("amount"), (int, float)) else 0.0,
                        on=_d(e.get("on", e.get(True))),  # YAML 1.1 reads a bare `on` key as true
                        reference=e.get("reference", ""),
                        method=e.get("method", "ueberweisung"),
                        document=doc,
                        settles=list(e.get("settles", [])),
                        truth=tr,
                        says=dict(e.get("says") or {}),
                        answers=bool(e.get("answers", True)),
                        skonto=bool(e.get("skonto", False)),
                    )
                )
            client.months[str(period)] = evs
        _complete(client)
        firm.clients.append(client)
    return firm


def _complete(client: Client) -> None:
    """Fills in what a scenario writer may leave to the machine: IBANs and VAT ids marked
    `auto`, and payment amounts that follow from the documents (`amount` left out)."""
    from kanzlei_sim.ids import iban, vat_id
    from kanzlei_sim.truth import gross_cents

    if client.iban in ("", "auto"):
        client.iban = iban("DE", client.id + ":own")
    if client.vat_id == "auto":
        client.vat_id = vat_id("DE", client.id)
    for p in client.parties:
        if p.iban == "auto":
            p.iban = iban(p.country if p.role != "other" else "DE", client.id + p.key)
        if p.vat_id == "auto":
            p.vat_id = vat_id(p.country, client.id + p.key)
    invoices = {e.id: e for evs in client.months.values() for e in evs if e.kind == "invoice"}
    for evs in client.months.values():
        for e in evs:
            if e.kind != "payment" or e.amount:
                continue
            if e.settles:
                total = 0
                sign = -1
                for i in e.settles:
                    d = invoices[i].document
                    assert d is not None, f"{e.id}: settles {i} without a document"
                    g = gross_cents(d.lines)
                    sign = 1 if d.direction == "out" else -1
                    if d.credit_note:
                        sign = -sign
                    total += g
                paid = round(total * 0.98) if e.skonto else total
                e.amount = sign * paid / 100
            elif e.document is not None and e.document.lines:
                g = gross_cents(e.document.lines)
                sign = 1 if e.document.direction == "out" else -1
                if e.document.credit_note:
                    sign = -sign
                e.amount = sign * g / 100
            else:
                raise ValueError(f"{client.id} {e.id}: payment without amount and without a document")


def cents(x: float) -> int:
    return round(x * 100)


TAX_CODES = {
    "V19",
    "V7",
    "U19",
    "U7",
    "RC_EU19",
    "RC_BAU19",
    "RC_DRITT19",
    "IGE19",
    "IGL",
    "EU_SVC",
    "RC_OUT",
    "FREI",
    "NONE",
}
FORMATS = {"xrechnung-ubl", "xrechnung-cii", "zugferd", "pdf", "none"}
CATEGORIES = {"S", "AE", "K", "E", "Z", "O"}
MISSING = {
    "seller_name",
    "seller_address",
    "buyer_name",
    "seller_tax_id",
    "invoice_no",
    "delivery_date",
    "buyer_vat_id",
}


def validate(firm: Firm) -> list[str]:
    """Problems in a hand-written scenario (empty: fine). Checks form, not judgment."""
    from kanzlei.config import families
    from kanzlei.engine.queries import OPTIONS

    fams = set(families()) | {"clearing"}
    out: list[str] = []
    if firm.chart not in ("SKR03", "SKR04"):
        out.append(f"firm {firm.id}: chart must be SKR03 or SKR04")
    logins = {s["login"] for s in firm.staff}
    if not any(s["role"] == "berater" for s in firm.staff):
        out.append(f"firm {firm.id}: needs a staff member with role berater")
    for c in firm.clients:
        where = f"{firm.id}/{c.id}"
        if c.booking_method not in ("direkt", "opos"):
            out.append(f"{where}: booking_method must be direkt or opos")
        if c.vat_regime not in ("soll", "ist", "klein", "befreit"):
            out.append(f"{where}: vat_regime must be soll, ist, klein or befreit")
        if not c.assigned or any(a not in logins for a in c.assigned):
            out.append(f"{where}: assigned must name staff logins of the firm")
        keys = {p.key for p in c.parties}
        if len(keys) != len(c.parties):
            out.append(f"{where}: party keys must be unique")
        for h in c.history:
            if h.party not in keys:
                out.append(f"{where}: history for unknown party {h.party}")
            if h.family not in fams or h.family == "clearing":
                out.append(f"{where}: history family {h.family} unknown")
            if h.tax not in TAX_CODES:
                out.append(f"{where}: history tax {h.tax} unknown")
        ids: set[str] = set()
        invoices = {e.id for evs in c.months.values() for e in evs if e.kind == "invoice"}
        for period, evs in c.months.items():
            for e in evs:
                w = f"{where} {e.id}"
                if e.id in ids:
                    out.append(f"{w}: duplicate event id")
                ids.add(e.id)
                if e.party not in keys:
                    out.append(f"{w}: unknown party {e.party}")
                if e.kind not in ("payment", "invoice"):
                    out.append(f"{w}: kind must be payment or invoice")
                if e.kind == "payment" and (e.on is None or e.on.strftime("%Y-%m") != period):
                    out.append(f"{w}: payment date must lie in {period}")
                if e.kind == "invoice" and (e.document is None or c.booking_method != "opos"):
                    out.append(f"{w}: invoice events need a document and an OPOS client")
                for s in e.settles:
                    if s not in invoices:
                        out.append(f"{w}: settles unknown invoice {s}")
                if e.truth is None:
                    out.append(f"{w}: truth missing")
                else:
                    if e.truth.family not in fams:
                        out.append(f"{w}: truth family {e.truth.family} unknown")
                    if e.truth.tax is not None and e.truth.tax not in TAX_CODES:
                        out.append(f"{w}: truth tax {e.truth.tax} unknown")
                    if e.truth.family == "clearing" and not e.settles:
                        out.append(f"{w}: clearing only for payments that settle invoices")
                d = e.document
                if d is not None:
                    if d.format not in FORMATS:
                        out.append(f"{w}: document format {d.format} unknown")
                    if d.arrives not in ("with_statement", "on_request", "never"):
                        out.append(f"{w}: arrives must be with_statement, on_request or never")
                    if d.direction not in ("in", "out"):
                        out.append(f"{w}: direction must be in or out")
                    if not d.lines:
                        out.append(f"{w}: document without lines")
                    for ln in d.lines:
                        if ln.category not in CATEGORIES:
                            out.append(f"{w}: line category {ln.category} unknown")
                        if ln.category == "S" and ln.rate not in (7, 19):
                            out.append(f"{w}: S lines have rate 7 or 19")
                    for m in d.missing:
                        if m not in MISSING:
                            out.append(f"{w}: missing field {m} unknown (one of {sorted(MISSING)})")
                for reason, ans in e.says.items():
                    if reason not in OPTIONS:
                        out.append(f"{w}: says.{reason} is not a question the firm asks ({sorted(OPTIONS)})")
                        continue
                    if ans.get("choice") not in {o["value"] for o in OPTIONS[reason]}:
                        out.append(f"{w}: says.{reason}.choice must be one of {[o['value'] for o in OPTIONS[reason]]}")
    return out
