"""The plain data the engine works on, independent of the database."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

INPUT_VAT = {"V19", "V7"}
OUTPUT_VAT = {"U19", "U7"}
REVERSE = {"RC_EU19", "RC_BAU19", "RC_DRITT19", "IGE19"}


@dataclass(frozen=True)
class ClientProfile:
    id: str
    firm_id: str
    name: str
    chart: str  # SKR03 | SKR04
    booking_method: str  # direkt | opos
    vat_regime: str  # soll | ist | klein | befreit
    vat_period: str  # monat | quartal
    dauerfrist: bool
    own_ibans: tuple[str, ...]
    vat_id: str | None = None
    mandant_nr: int = 0
    berater_nr: int = 0
    fiscal_year_start_month: int = 1
    llm_allowed: bool = False


@dataclass
class Line:
    """One booking line: `amount_cents` (gross, > 0) moves from `credit` to `debit`."""

    date: date
    amount_cents: int
    debit: int
    credit: int
    tax: str
    text: str
    family: str | None = None
    role: str | None = None
    doc_ref: str = ""

    def key(self) -> tuple[int, int, str, int]:
        return (self.debit, self.credit, self.tax, self.amount_cents)

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["date"] = self.date.isoformat()
        return d

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Line:
        return cls(
            date=date.fromisoformat(d["date"]),
            amount_cents=int(d["amount_cents"]),
            debit=int(d["debit"]),
            credit=int(d["credit"]),
            tax=d["tax"],
            text=d.get("text", ""),
            family=d.get("family"),
            role=d.get("role"),
            doc_ref=d.get("doc_ref", ""),
        )


@dataclass
class Reason:
    code: str
    text: str


# Flags that hold an item. "client": only the client can resolve it; "review": staff decide.
CLIENT_FLAGS = {
    "missing_receipt": "Beleg fehlt",
    "private_or_business": "Privat oder betrieblich?",
    "meals_details": "Anlass und Teilnehmer der Bewirtung fehlen",
    "unknown_credit": "Zahlungseingang ohne Rechnung",
    "invoice_incomplete": "Rechnung unvollständig (§ 14 UStG)",
}
REVIEW_FLAGS = {
    "asset_review": "Anlagegut über 800 € netto",
    "ambiguous_match": "Mehrere passende Rechnungen",
    "partial_payment": "Zahlung weicht von der Rechnung ab",
    "duplicate_invoice": "Rechnung bereits gebucht",
    "no_account": "Kein Konto für diese Steuerart im Kontenrahmen",
    "new_creditor": "Neuer Kreditor",
    "unreadable_document": "Beleg nicht lesbar",
    "unsupported_tax": "Steuerfall nicht automatisiert",
    "client_answer": "Antwort des Mandanten prüfen",
    "low_confidence": "Vorschlag unsicher",
    "memory_conflict": "Text widerspricht bisherigen Buchungen",
}


@dataclass
class Proposal:
    family: str | None
    tax: str | None
    lines: list[Line]
    confidence: float
    route: str  # auto | review | client
    reasons: list[Reason] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    source: str = "rules"
    features: list[float] = field(default_factory=list)
    counterparty: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "tax": self.tax,
            "lines": [ln.to_json() for ln in self.lines],
            "confidence": round(self.confidence, 4),
            "route": self.route,
            "reasons": [asdict(r) for r in self.reasons],
            "flags": self.flags,
            "source": self.source,
            "features": self.features,
            "counterparty": self.counterparty,
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> Proposal:
        return cls(
            family=d.get("family"),
            tax=d.get("tax"),
            lines=[Line.from_json(x) for x in d.get("lines", [])],
            confidence=float(d.get("confidence", 0)),
            route=d.get("route", "review"),
            reasons=[Reason(**r) for r in d.get("reasons", [])],
            flags=list(d.get("flags", [])),
            source=d.get("source", "rules"),
            features=list(d.get("features", [])),
            counterparty=dict(d.get("counterparty", {})),
        )
